"""
Plan Executor v0 — R2.4.

Walks a plan (from app.core.goal_planner.plan_goal) and executes its
steps in order, exercising every prior brick of the self-extending-agent
track end-to-end:

  goal → planner (R2.2) → registry lookup (R2.1) → governor (R2.1b)
       → executor (this) → verified result → gate → resume

This is the LITMUS test for the four-layer engine, not a feature pass.
Per master_plan_v3_self_extending_agent.md: "The Vinted worker is the
convenient first test [...] chosen as a litmus for the engine, not
because selling is a priority."

v0 scope:
- In-memory execution. No plan-persistence table — plans flow through
  one HTTP request, paused state returned to caller, resumed by caller
  passing approval_token on a follow-up call. Plan persistence
  (`tony_plans`) lands later if/when long-running agents need to span
  HTTP requests.
- Tiny capability dispatcher. v0 knows how to execute exactly two
  capabilities (`brave_search`, `chat`) — enough to prove the engine
  runs end-to-end on a non-trivial goal. Adding more capabilities is
  one dispatch case each; deliberately not generalised yet.
- Halts on first non-ready step (gap, needs_approval, or execution
  failure) and returns the paused state. Caller decides what to do
  next: supply an approval_token and re-run; or fix the gap; or
  accept the partial result.

Acceptance criterion: a goal can be planned, executed where ready,
paused on governor-required approval, and resumed by passing an
approval_token. The executor never bypasses the governor — every
needs_approval step is re-evaluated with the token before execution.
"""
from typing import Any, Dict, Optional


async def _execute_step(step: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one step's underlying capability.

    Returns:
      {ok: bool, result: any, verified: bool, method: str, [error: str]}

    For v0 the dispatcher handles two capability_keys:
      - brave_search: calls app.core.brave_search.brave_search(query)
      - chat:         calls app.core.model_router.gemini(prompt)

    Unknown capabilities return ok=False with a clear error. Extending
    the dispatcher is one elif each as more capabilities prove
    themselves through the engine.
    """
    cap = step.get("registry_match") or {}
    capability_key = (cap.get("capability_key") or cap.get("name") or "").strip()
    capability_type = cap.get("capability_type", "")
    description = (step.get("description") or "").strip()

    if not capability_key:
        return {
            "ok": False,
            "error": "step has no registry_match — cannot dispatch",
            "verified": False,
            "method": "none",
        }

    # --- Dispatcher (v0: 2 capabilities) -----------------------------------

    if capability_key == "brave_search":
        try:
            from app.core.brave_search import brave_search
            result = await brave_search(description)
            return {
                "ok": bool(result),
                "result": (result or "")[:1000],
                "verified": bool(result),
                "method": "brave_search",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"brave_search failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "brave_search",
            }

    if capability_key == "chat":
        try:
            from app.core.model_router import gemini
            # The step description is the prompt. v0 keeps this simple —
            # later versions may inject upstream-step results as context.
            text = await gemini(description, task="general", max_tokens=1024)
            return {
                "ok": bool(text),
                "result": (text or "")[:1500],
                "verified": bool(text and text.strip()),
                "method": "gemini_general",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"chat failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gemini_general",
            }

    if capability_key == "gmail_send":
        # Sends email. Three layers of safety:
        #   1. Governor (R2.1b) default-denies external_effect+approval_required
        #      — only an approval_token from the caller unlocks reaching this
        #      branch (registry row corrected R2.4+ via seed_capabilities_v1).
        #   2. LLM parameter extraction: gemini_json against the step
        #      description, expected fields {account, to, subject, body}.
        #   3. Strict validation before send: account must be in the
        #      connected Gmail accounts list; `to` must look like a real
        #      email address; all four fields must be non-empty strings.
        #      Any failure → refuse cleanly with the reason. No fallback
        #      "best guess" send.
        try:
            from app.core.gmail_service import get_all_accounts, send_email
            from app.core.model_router import gemini_json
            import re as _re

            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no Gmail accounts connected — cannot send",
                    "verified": False,
                    "method": "gmail_send",
                }

            accounts_list = ", ".join(accounts)
            extract_prompt = (
                f"Extract structured email-send parameters from this step "
                f"description.\n\n"
                f"Description: {description}\n\n"
                f"Available accounts to send FROM (pick exactly one): "
                f"{accounts_list}\n\n"
                f"Rules:\n"
                f"- `account` must be one of the available accounts above, "
                f"verbatim.\n"
                f"- `to` must be a complete valid email address. If the "
                f"description names a person without an email address, "
                f"return null for `to` — do NOT guess an address.\n"
                f"- `subject` and `body` must both be non-empty strings.\n"
                f"- If ANY field cannot be determined safely, return null "
                f"for that field rather than guessing.\n\n"
                f"Respond in JSON:\n"
                f'{{"account": "<from_account>", "to": "<recipient_email>", '
                f'"subject": "<subject>", "body": "<body>"}}'
            )
            # disable_thinking: structured-extraction is trivial-shape (one
            # small dict). Without this, gemini-2.5-flash's thinking-mode
            # consumes the budget on internal reasoning, returns null, and
            # the dispatcher then can't validate. Forces flash + thinkingBudget=0.
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=1024,
                disable_thinking=True,
            )

            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "gmail_send",
                }

            account = (params.get("account") or "").strip()
            to_addr = (params.get("to") or "").strip()
            subject = (params.get("subject") or "").strip()
            body = (params.get("body") or "").strip()

            # Strict validation — refuse rather than send wrong-shaped mail.
            if account not in accounts:
                return {
                    "ok": False,
                    "error": (
                        f"extracted account '{account}' is not in connected "
                        f"accounts list — refusing to send. Available: {accounts_list}"
                    ),
                    "verified": False,
                    "method": "gmail_send",
                    "extracted": {"account": account, "to": to_addr,
                                  "subject_chars": len(subject), "body_chars": len(body)},
                }
            email_re = _re.compile(r"^[\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,}$")
            if not to_addr or not email_re.match(to_addr):
                return {
                    "ok": False,
                    "error": (
                        f"extracted `to` is not a valid email address "
                        f"(got {to_addr!r}) — refusing to send. The "
                        f"description must contain an explicit recipient "
                        f"email; v0 dispatcher does not guess from name."
                    ),
                    "verified": False,
                    "method": "gmail_send",
                    "extracted": {"account": account, "to": to_addr,
                                  "subject_chars": len(subject), "body_chars": len(body)},
                }
            if not subject:
                return {
                    "ok": False,
                    "error": "extracted subject is empty — refusing to send",
                    "verified": False,
                    "method": "gmail_send",
                }
            if not body:
                return {
                    "ok": False,
                    "error": "extracted body is empty — refusing to send",
                    "verified": False,
                    "method": "gmail_send",
                }

            success = await send_email(account, to_addr, subject, body)
            return {
                "ok": bool(success),
                "result": {
                    "from": account,
                    "to": to_addr,
                    "subject": subject,
                    "body_chars": len(body),
                    "sent": bool(success),
                },
                "verified": bool(success),
                "method": "gmail_send",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"gmail_send failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gmail_send",
            }

    if capability_key == "gmail_read":
        # Reads across all connected Gmail accounts via search_all_accounts,
        # which internally calls build_smart_query to translate NL→Gmail
        # operators (e.g. "emails from Christine" → from:Christine). The
        # step description is treated as the search intent verbatim;
        # planner-produced descriptions like "Read recent unread emails"
        # pass through to Gmail's search. Empty results are an honest
        # outcome (verified=False, ok=True — the read ran, found nothing).
        try:
            from app.core.gmail_service import search_all_accounts
            emails = await search_all_accounts(description, max_per_account=5)
            # Compact summary — full email bodies would bloat the trace.
            # Keep enough to confirm the read worked and feed downstream steps.
            summary = [
                {
                    "account": e.get("account"),
                    "from": (e.get("from") or "").split("<")[0].strip(),
                    "subject": (e.get("subject") or "")[:80],
                    "date": (e.get("date") or "")[:16],
                    "snippet": (e.get("snippet") or "")[:200],
                }
                for e in (emails or [])[:10]
            ]
            return {
                "ok": True,
                "result": {"emails": summary, "count": len(emails or [])},
                "verified": len(summary) > 0,
                "method": "gmail_search_all_accounts",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"gmail_read failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gmail_search_all_accounts",
            }

    # Unknown — refuse cleanly rather than guess.
    return {
        "ok": False,
        "error": (
            f"v0 executor has no dispatcher for capability "
            f"'{capability_key}' (type={capability_type}). "
            f"Add a case to plan_executor._execute_step to extend."
        ),
        "verified": False,
        "method": "none",
    }


async def execute_plan(
    plan: Dict[str, Any],
    approval_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a plan produced by app.core.goal_planner.plan_goal.

    Walks steps in order:
      - status='ready'           → execute, capture result + verification
      - status='needs_approval'  → if approval_token absent → halt + return paused;
                                   if present → re-evaluate governor → execute
      - status='gap'             → halt, return paused with gap reason
      - execution exception      → halt, return paused with execution_failed

    Returns:
      {
        ok: bool,
        goal: str,
        executed_steps: [...],   # steps that actually ran (status='done' or 'failed')
        paused_step: dict|None,  # the step that halted execution (None on full success)
        total_steps: int,
        executed_count: int,
      }
    """
    executed_steps = []
    paused_step: Optional[Dict[str, Any]] = None
    steps = plan.get("steps", []) or []

    for step in steps:
        step_number = step.get("step_number")
        status = step.get("status")

        # --- Gap: cannot execute. Halt. -----------------------------------
        if status == "gap":
            paused_step = {
                "step_number": step_number,
                "reason": "gap",
                "step": step,
                "details": (
                    "no registered capability for this step; "
                    "R2.3's detect-and-record path can propose one"
                ),
            }
            break

        # --- Needs approval: re-evaluate governor with the token ----------
        if status == "needs_approval":
            if not approval_token:
                paused_step = {
                    "step_number": step_number,
                    "reason": "needs_approval",
                    "step": step,
                    "details": (
                        f"governor requires approval for action_class="
                        f"{(step.get('governor_decision') or {}).get('action_class', '?')}; "
                        f"resume by re-calling with approval_token"
                    ),
                }
                break
            # Re-evaluate with the token. If governor still denies (e.g.,
            # capability changed since plan was produced), halt.
            try:
                from app.core.governor import evaluate_action
                new_decision = evaluate_action(
                    step.get("registry_match") or {},
                    approval_token=approval_token,
                )
            except Exception as e:
                paused_step = {
                    "step_number": step_number,
                    "reason": "governor_evaluation_failed",
                    "step": step,
                    "details": f"{type(e).__name__}: {e}",
                }
                break
            if not new_decision.get("allowed"):
                paused_step = {
                    "step_number": step_number,
                    "reason": "governor_denied_with_token",
                    "step": step,
                    "details": new_decision,
                }
                break
            # Token accepted — fall through to execution.

        elif status != "ready":
            # Unknown status — be conservative, halt.
            paused_step = {
                "step_number": step_number,
                "reason": "unknown_status",
                "step": step,
                "details": f"unexpected step status: {status!r}",
            }
            break

        # --- Execute -------------------------------------------------------
        outcome = await _execute_step(step)
        executed_steps.append({
            **step,
            "execution": outcome,
            "final_status": "done" if outcome.get("ok") else "failed",
        })
        if not outcome.get("ok"):
            paused_step = {
                "step_number": step_number,
                "reason": "execution_failed",
                "step": step,
                "details": outcome.get("error") or "step executor returned ok=False",
            }
            break

    trace = {
        "ok": paused_step is None,
        "goal": plan.get("goal"),
        "executed_steps": executed_steps,
        "paused_step": paused_step,
        "total_steps": len(steps),
        "executed_count": len(executed_steps),
    }
    _emit_execution_event(trace)
    return trace


def _emit_execution_event(trace: Dict[str, Any]) -> None:
    """Best-effort observability — never raises."""
    try:
        from app.observability import record_run_event, EventSeverity
        sev = EventSeverity.INFO if trace["ok"] else EventSeverity.WARNING
        paused = trace.get("paused_step") or {}
        record_run_event(
            event_type="plan_executor_run",
            severity=sev,
            subsystem="plan_executor",
            message=(
                f"plan run: ok={trace['ok']} executed={trace['executed_count']}/"
                f"{trace['total_steps']} paused_reason={paused.get('reason') or 'none'}"
            ),
            metadata={
                "total_steps": trace["total_steps"],
                "executed_count": trace["executed_count"],
                "ok": trace["ok"],
                "paused_reason": paused.get("reason"),
                "paused_step_number": paused.get("step_number"),
            },
        )
    except Exception:
        pass


async def run_goal(goal_text: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """Compose: plan_goal → execute_plan. The full end-to-end loop.

    Returns:
      {
        ok: bool,
        plan: <the plan dict from goal_planner.plan_goal>,
        execution: <the trace from execute_plan>,
        error: str | None,
      }
    """
    try:
        from app.core.goal_planner import plan_goal
        plan = await plan_goal(goal_text, approval_token=approval_token)
    except Exception as e:
        return {
            "ok": False,
            "plan": None,
            "execution": None,
            "error": f"plan_goal raised: {type(e).__name__}: {e}",
        }

    if not plan.get("ok"):
        return {
            "ok": False,
            "plan": plan,
            "execution": None,
            "error": plan.get("error") or "plan produced no steps",
        }

    execution = await execute_plan(plan, approval_token=approval_token)
    return {
        "ok": execution.get("ok", False),
        "plan": plan,
        "execution": execution,
        "error": None,
    }
