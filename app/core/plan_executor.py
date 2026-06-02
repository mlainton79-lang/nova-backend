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
from typing import Any, Dict, List, Optional


def _format_prior_results(prior_results: Optional[List[Dict[str, Any]]]) -> str:
    """Compact preamble describing earlier-step outputs. Used by dispatchers
    that opt in to chain-aware execution (today: chat, gmail_send). Empty
    list / None returns "" so callers can do `prefix =
    _format_prior_results(...); if prefix: prompt = prefix + prompt`.

    Dict/list results are dumped as JSON (capped at 1500 chars each)
    rather than stringified with per-key truncation — the old shape
    hid inner fields like gmail_read's parsed from_address from
    downstream LLMs even when those fields existed. String results
    are truncated at 800 chars; other types stringified and capped.
    """
    if not prior_results:
        return ""
    import json as _json
    lines = ["Earlier steps in this plan produced these results:"]
    for r in prior_results:
        cap_key = r.get("capability_key", "?")
        sn = r.get("step_number", "?")
        verified = r.get("verified", False)
        result = r.get("result")
        if isinstance(result, (dict, list)):
            try:
                summary = _json.dumps(result, default=str)[:1500]
            except Exception:
                summary = str(result)[:1500]
        elif isinstance(result, str):
            summary = result[:800]
        else:
            summary = str(result)[:400]
        lines.append(f"- Step {sn} ({cap_key}, verified={verified}): {summary}")
    lines.append("")
    return "\n".join(lines) + "\n"


async def _execute_step(step: Dict[str, Any],
                         payload: Optional[Dict[str, Any]] = None,
                         prior_results: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Execute one step's underlying capability.

    Returns:
      {ok: bool, result: any, verified: bool, method: str, [error: str]}

    Args:
      step: the planner-produced step dict (description + registry_match)
      payload: optional caller-supplied dict for structured/binary inputs
        that can't be extracted from a description (e.g. uploaded photos,
        CSV files, audio). Capabilities that need such inputs read from
        this dict by a documented key (e.g. vinted_draft_create reads
        payload["images"]).
      prior_results: optional list of {step_number, capability_key,
        description, result, verified} dicts from steps that already
        executed in this plan run. Opt-in per dispatcher — capabilities
        that benefit from chain-aware context (chat especially) inject
        them into their prompts via _format_prior_results. Capabilities
        that don't need it ignore the param.

    Dispatcher branches are one elif each. Adding a new capability is:
    pick a stable capability_key, write a branch returning the
    {ok, result, verified, method} contract, optionally read inputs from
    `payload` and/or `prior_results`. Unknown capabilities return ok=False
    with a clear error.
    """
    cap = step.get("registry_match") or {}
    capability_key = (cap.get("capability_key") or cap.get("name") or "").strip()
    capability_type = cap.get("capability_type", "")
    description = (step.get("description") or "").strip()
    payload = payload or {}
    prior_results = prior_results or []

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
            # Chain-aware: prepend prior step results so chat steps that
            # follow a search/read/vision step can actually reason about
            # what those steps found. _format_prior_results returns ""
            # when there are none, so step 1 chat behaviour is unchanged.
            prior_block = _format_prior_results(prior_results)
            full_prompt = prior_block + description if prior_block else description
            text = await gemini(full_prompt, task="general", max_tokens=1024)
            return {
                "ok": bool(text),
                "result": (text or "")[:1500],
                "verified": bool(text and text.strip()),
                "method": "gemini_general",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"chat failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gemini_general",
            }

    if capability_key == "reason":
        # Gap-bridge reasoning capability. The planner naturally
        # decomposes goals into [read → analyse → write] but the
        # `analyse` step has no concrete read/write capability to
        # match — it becomes a `gap` and the executor halts. `reason`
        # exists to satisfy those intermediate steps. Same underlying
        # gemini call as chat, but the prompt frames the model as a
        # bridge in a multi-step plan, biasing toward structured
        # concrete output the downstream step can consume rather than
        # a conversational reply.
        try:
            from app.core.model_router import gemini
            from datetime import datetime
            prior_block = _format_prior_results(prior_results)
            today_str = datetime.utcnow().strftime("%Y-%m-%d (%A)")
            prompt = (
                (prior_block if prior_block else "")
                + "You are running an intermediate REASONING step inside "
                "a multi-step plan. The next steps will use your output "
                "to act. Analyse the prior step results above (if any) "
                "and the request below. Be brief, structured, and "
                "concrete — output exactly what the next step needs, "
                "no preamble, no conversational fluff. If the request "
                "is to pick a value (a time slot, a recipient, an item) "
                "give that value plainly. If it's to summarise, give "
                "the bullet points without commentary.\n\n"
                f"Today's date is {today_str} UTC. Any relative dates "
                "you produce ('tomorrow', 'next Tuesday', a specific "
                "time slot) MUST resolve against this date, not against "
                "your training cutoff. ISO timestamps must use this "
                "year.\n\n"
                "Request:\n"
                + description
            )
            # task="general" → flash tier, no Google Search grounding.
            # Reasoning here is over the prior_results context (internal
            # data), not the open web — grounding wastes tokens. Flash
            # keeps thinking-mode enabled at a lower thinking-budget than
            # pro, leaving enough output budget for the structured answer.
            # Original task="reasoning" attempt landed thoughts=2045
            # output=0 (per Litmus 14a).
            text = await gemini(prompt, task="general", max_tokens=2048)
            return {
                "ok": bool(text),
                "result": (text or "")[:1500],
                "verified": bool(text and text.strip()),
                "method": "gemini_reason",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"reason failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gemini_reason",
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
            # Chain-aware: if prior steps produced gmail_read results,
            # inject them as context so the extractor can resolve
            # "reply to John" → look up John's address rather than
            # refusing/guessing. The safety rule shifts from "don't
            # guess" to "look in prior results first, return null only
            # if not found there."
            prior_block = _format_prior_results(prior_results)
            extract_prompt = (
                (prior_block if prior_block else "")
                + f"Extract structured email-send parameters from this step "
                f"description.\n\n"
                f"Description: {description}\n\n"
                f"Available accounts to send FROM (pick exactly one): "
                f"{accounts_list}\n\n"
                f"Rules:\n"
                f"- `account` must be one of the available accounts above, "
                f"verbatim.\n"
                f"- `to` must be a complete valid email address. If the "
                f"description names a person without an explicit email "
                f"address, FIRST check the prior step results above for "
                f"that person's address (e.g. the `from` field of a prior "
                f"gmail_read result). If found there, use it. If NOT "
                f"found, return null for `to` — do NOT guess or invent.\n"
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
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"gmail_send failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gmail_send",
            }

    if capability_key == "vision_image":
        # Analyse an image with Gemini Vision. Read-only — vision analysis
        # doesn't mutate anything external. Reads image from payload the
        # same way vinted_draft_create does (images[0] OR image_base64).
        # The step description doubles as the vision prompt — what should
        # Tony look for / report on. Returns the analysis text.
        try:
            from app.core.vision import tony_see
            images = payload.get("images") or []
            if images:
                first = images[0] if isinstance(images[0], dict) else {}
                image_base64 = first.get("base64") or ""
                image_mime = first.get("mime") or "image/jpeg"
            else:
                image_base64 = payload.get("image_base64") or ""
                image_mime = payload.get("image_mime") or "image/jpeg"

            if not image_base64:
                return {
                    "ok": False,
                    "error": (
                        "vision_image requires an image in the payload "
                        "(payload.images=[{base64, mime}] or payload.image_base64). "
                        "Step descriptions cannot carry binary data."
                    ),
                    "verified": False,
                    "method": "vision_image",
                }

            prompt = description or "Describe what's in this image. Be specific about objects, text, colours, and condition."
            text = await tony_see(image_base64, prompt, image_mime)
            return {
                "ok": bool(text),
                "result": (text or "")[:2000],
                "verified": bool(text and text.strip() and "error" not in (text or "").lower()[:80]),
                "method": "vision_image",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"vision_image failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "vision_image",
            }

    if capability_key == "gmail_delete_permanent":
        # IRREVERSIBLE permanent delete. Two-layer kill-switch on top of
        # all the standard destructive-dispatcher safety:
        #   1. Governor (R2.1b) default-denies absent approval_token.
        #   2. GMAIL_PERMANENT_DELETE_ENABLED env var must be true. Even
        #      with a valid approval_token the dispatcher refuses if the
        #      env var is off — defense in depth so a leaked or
        #      misapplied token can't trigger an irreversible purge.
        # Then the standard gmail_delete safety stack: extractor with
        # match_evidence, strict validation, verify-by-GET, evidence
        # cross-check, then permanent delete via gmail_service.delete_email.
        # Prefer gmail_delete (reversible trash) for any case where Trash
        # would be acceptable — this capability exists only for genuine
        # permanent-purge requirements.
        import os as _os
        if _os.environ.get("GMAIL_PERMANENT_DELETE_ENABLED", "false").strip().lower() not in ("true", "1", "yes", "on"):
            return {
                "ok": False,
                "error": (
                    "GMAIL_PERMANENT_DELETE_ENABLED is off — refusing. "
                    "Permanent gmail delete is double-gated: governor "
                    "approval AND this env var. Use gmail_delete "
                    "(reversible trash) instead, or set "
                    "GMAIL_PERMANENT_DELETE_ENABLED=true on the web "
                    "service if a permanent purge is genuinely needed."
                ),
                "verified": False,
                "method": "gmail_delete_permanent",
            }

        try:
            from app.core.gmail_service import (
                get_all_accounts, delete_email, get_email_body
            )
            from app.core.model_router import gemini_json

            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no Gmail accounts connected",
                    "verified": False,
                    "method": "gmail_delete_permanent",
                }
            accounts_list = ", ".join(accounts)

            prior_block = _format_prior_results(prior_results)
            extract_prompt = (
                (prior_block if prior_block else "")
                + f"Extract structured Gmail-message-PERMANENT-DELETE "
                f"parameters from this step description.\n\n"
                f"⚠ WARNING: this is PERMANENT, IRREVERSIBLE deletion. "
                f"There is no Trash. No 30-day grace. If you pick the "
                f"wrong message it is gone forever. Be conservative.\n\n"
                f"Description: {description}\n\n"
                f"Available accounts (pick the one that owns the message): "
                f"{accounts_list}\n\n"
                f"Rules:\n"
                f"- `account` must be one of the available accounts, verbatim.\n"
                f"- `message_id` is the Gmail message id. Typically hex-"
                f"alphanumeric 16-20 chars.\n"
                f"- If prior step results above include a gmail_read with "
                f"emails, match the description's explicit cues against "
                f"those emails (subject, sender, date). If multiple match, "
                f"OR no email's fields match the cues, OR the description "
                f"is ambiguous, return null for message_id. Do NOT guess.\n"
                f"- `match_evidence` is your stated reason for picking "
                f"this id: a substring of subject/from/date that justifies "
                f"the match. VERIFIED against the actual message before "
                f"the delete proceeds. If you cannot articulate it, "
                f"return null for both message_id and match_evidence.\n\n"
                f"Respond in JSON:\n"
                f'{{"account": "<account>", '
                f'"message_id": "<gmail_message_id_or_null>", '
                f'"match_evidence": "<substring_from_subject_or_from_or_date>"}}'
            )
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=512,
                disable_thinking=True,
            )

            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "gmail_delete_permanent",
                }

            account = (params.get("account") or "").strip()
            message_id = (params.get("message_id") or "").strip()
            match_evidence = (params.get("match_evidence") or "").strip()

            if account not in accounts:
                return {
                    "ok": False,
                    "error": (
                        f"extracted account '{account}' is not in connected "
                        f"accounts — refusing. Available: {accounts_list}"
                    ),
                    "verified": False,
                    "method": "gmail_delete_permanent",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            if not message_id:
                return {
                    "ok": False,
                    "error": "extracted message_id is empty — refusing permanent delete.",
                    "verified": False,
                    "method": "gmail_delete_permanent",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            if not match_evidence:
                return {
                    "ok": False,
                    "error": (
                        "extractor did not provide match_evidence — refusing "
                        "permanent delete. Even more important here than for "
                        "trash since this is irreversible."
                    ),
                    "verified": False,
                    "method": "gmail_delete_permanent",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }

            existing = await get_email_body(account, message_id)
            if not existing or not existing.get("id"):
                return {
                    "ok": False,
                    "error": (
                        f"could not fetch message {message_id} before "
                        f"permanent delete — refusing."
                    ),
                    "verified": False,
                    "method": "gmail_delete_permanent",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            deleted_from = (existing.get("from") or "")[:120]
            deleted_subject = (existing.get("subject") or "")[:120]
            deleted_date = (existing.get("date") or "")[:32]

            # Match-evidence cross-check.
            ev_lower = match_evidence.lower()
            haystack = (deleted_subject + " " + deleted_from + " " + deleted_date).lower()
            if ev_lower not in haystack:
                return {
                    "ok": False,
                    "error": (
                        f"match_evidence '{match_evidence}' does NOT appear "
                        f"in the fetched message's subject/from/date — "
                        f"refusing PERMANENT delete. LLM extractor picked "
                        f"an id that doesn't match its own stated evidence."
                    ),
                    "verified": False,
                    "method": "gmail_delete_permanent",
                    "extracted": {
                        "account": account,
                        "message_id": message_id,
                        "match_evidence": match_evidence,
                        "fetched_subject": deleted_subject,
                        "fetched_from": deleted_from,
                        "fetched_date": deleted_date,
                    },
                }

            success = await delete_email(account, message_id)
            return {
                "ok": bool(success),
                "result": {
                    "account": account,
                    "message_id": message_id,
                    "deleted_from": deleted_from,
                    "deleted_subject": deleted_subject,
                    "deleted_date": deleted_date,
                    "deleted": bool(success),
                    "permanent": True,
                    "reversible": False,
                },
                "verified": bool(success),
                "method": "gmail_delete_permanent",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"gmail_delete_permanent failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gmail_delete_permanent",
            }

    if capability_key == "gmail_delete":
        # Destructive sibling of gmail_send. Uses trash_email — REVERSIBLE
        # 30-day-retention destructive, not permanent. Same three-layer
        # safety as calendar_delete:
        #   1. Registry: external_effect=True, approval_required=True →
        #      governor default-denies without approval_token.
        #   2. LLM extraction of {account, message_id} with disable_thinking
        #      and chain-aware prior_results — typically resolves the id
        #      by matching the description against a prior gmail_read's
        #      `id` field.
        #   3. Strict validation + verify-by-GET BEFORE trash: fetch via
        #      get_email_body, surface from/subject/date in the trace,
        #      then trash. If GET fails → refuse cleanly.
        try:
            from app.core.gmail_service import (
                get_all_accounts, trash_email, get_email_body
            )
            from app.core.model_router import gemini_json

            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no Gmail accounts connected",
                    "verified": False,
                    "method": "gmail_delete",
                }
            accounts_list = ", ".join(accounts)

            prior_block = _format_prior_results(prior_results)
            extract_prompt = (
                (prior_block if prior_block else "")
                + f"Extract structured Gmail-message-DELETE parameters from "
                f"this step description. The action is MOVE TO TRASH "
                f"(reversible — 30 days retention).\n\n"
                f"Description: {description}\n\n"
                f"Available accounts (pick the one that owns the message): "
                f"{accounts_list}\n\n"
                f"Rules:\n"
                f"- `account` must be one of the available accounts, verbatim.\n"
                f"- `message_id` is the Gmail message id of the email to "
                f"trash. It is a hex-alphanumeric string typically 16-20 "
                f"characters.\n"
                f"- If prior step results above include a gmail_read with "
                f"emails, FIRST match the description against those emails. "
                f"For each candidate, the description usually quotes a "
                f"subject, names a sender, or gives a date — use ONLY those "
                f"explicit cues. If multiple emails could match, OR no "
                f"email's subject/from/date matches the description's "
                f"explicit cues, return null for message_id. Do NOT guess "
                f"or pick the first one in the list.\n"
                f"- `match_evidence` is your stated reason for picking this "
                f"id: a substring of the matching email's subject, OR a "
                f"substring of the from-line, OR a substring of the date. "
                f"This will be verified against the actual message before "
                f"the trash proceeds — if the fetched message doesn't "
                f"contain your stated evidence, the trash is REFUSED. So "
                f"only return evidence you're certain matches.\n"
                f"- If you cannot articulate a specific match_evidence "
                f"substring, return null for both message_id and "
                f"match_evidence.\n\n"
                f"Respond in JSON:\n"
                f'{{"account": "<account>", '
                f'"message_id": "<gmail_message_id_or_null>", '
                f'"match_evidence": "<substring_from_subject_or_from_or_date>"}}'
            )
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=512,
                disable_thinking=True,
            )

            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "gmail_delete",
                }

            account = (params.get("account") or "").strip()
            message_id = (params.get("message_id") or "").strip()
            match_evidence = (params.get("match_evidence") or "").strip()

            if account not in accounts:
                return {
                    "ok": False,
                    "error": (
                        f"extracted account '{account}' is not in connected "
                        f"accounts — refusing. Available: {accounts_list}"
                    ),
                    "verified": False,
                    "method": "gmail_delete",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            if not message_id:
                return {
                    "ok": False,
                    "error": (
                        "extracted message_id is empty — refusing to trash. "
                        "Either no prior gmail_read provided context, or "
                        "the description didn't match any prior message."
                    ),
                    "verified": False,
                    "method": "gmail_delete",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            if not match_evidence:
                return {
                    "ok": False,
                    "error": (
                        "extractor did not provide match_evidence — refusing "
                        "to trash. Destructive actions require the LLM to "
                        "state which subject/from/date substring justified "
                        "the id resolution, so the dispatcher can verify "
                        "against the fetched message."
                    ),
                    "verified": False,
                    "method": "gmail_delete",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }

            # Verify-by-GET before trash. If the GET fails (wrong id,
            # message deleted), refuse cleanly — trashing the wrong
            # message would be worse than refusing.
            existing = await get_email_body(account, message_id)
            if not existing or not existing.get("id"):
                return {
                    "ok": False,
                    "error": (
                        f"could not fetch message {message_id} before "
                        f"trash — refusing. Message may not exist or be "
                        f"accessible to this account."
                    ),
                    "verified": False,
                    "method": "gmail_delete",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            trashed_from = (existing.get("from") or "")[:120]
            trashed_subject = (existing.get("subject") or "")[:120]
            trashed_date = (existing.get("date") or "")[:32]

            # Match-evidence cross-check: the fetched message MUST contain
            # the LLM's stated match_evidence in subject, from, or date.
            # Catches the failure mode where the LLM picked an arbitrary
            # id from prior_results without actually matching the goal —
            # exactly what trashed Matthew's April draft in the first
            # gmail_delete live test (2026-06-02).
            ev_lower = match_evidence.lower()
            haystack = (
                (trashed_subject + " " + trashed_from + " " + trashed_date).lower()
            )
            if ev_lower not in haystack:
                return {
                    "ok": False,
                    "error": (
                        f"match_evidence '{match_evidence}' does NOT appear "
                        f"in the fetched message's subject/from/date — "
                        f"refusing to trash. LLM extractor picked an id "
                        f"that doesn't match its own stated evidence."
                    ),
                    "verified": False,
                    "method": "gmail_delete",
                    "extracted": {
                        "account": account,
                        "message_id": message_id,
                        "match_evidence": match_evidence,
                        "fetched_subject": trashed_subject,
                        "fetched_from": trashed_from,
                        "fetched_date": trashed_date,
                    },
                }

            success = await trash_email(account, message_id)
            return {
                "ok": bool(success),
                "result": {
                    "account": account,
                    "message_id": message_id,
                    "trashed_from": trashed_from,
                    "trashed_subject": trashed_subject,
                    "trashed_date": trashed_date,
                    "trashed": bool(success),
                    "reversible": True,
                    "retention_days": 30,
                },
                "verified": bool(success),
                "method": "gmail_delete",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"gmail_delete failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gmail_delete",
            }

    if capability_key == "calendar_delete":
        # Destructive sibling of calendar_write. Same three-layer safety:
        #   1. Registry: external_effect=True, approval_required=True
        #      (seed_capabilities_v1) → governor default-denies absent
        #      approval_token.
        #   2. LLM extraction of {account, event_id} with disable_thinking
        #      and chain-aware context — typically resolves event_id by
        #      matching the description against a prior calendar_read
        #      result's `id` field.
        #   3. Strict validation + EXTRA verify-by-GET BEFORE DELETE.
        #      Fetch the event via get_event, surface its title/start in
        #      the trace, then call delete_event. If the event doesn't
        #      exist or the GET errors, refuse cleanly — destroying the
        #      wrong event is much worse than refusing a delete.
        try:
            from app.core.gmail_service import get_all_accounts
            from app.core.calendar_service import delete_event, get_event
            from app.core.model_router import gemini_json

            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no connected accounts — calendar uses Gmail OAuth tokens",
                    "verified": False,
                    "method": "calendar_delete",
                }
            accounts_list = ", ".join(accounts)

            prior_block = _format_prior_results(prior_results)
            extract_prompt = (
                (prior_block if prior_block else "")
                + f"Extract structured calendar-event-DELETE parameters from "
                f"this step description.\n\n"
                f"Description: {description}\n\n"
                f"Available accounts (calendar uses Gmail OAuth — pick one): "
                f"{accounts_list}\n\n"
                f"Rules:\n"
                f"- `account` must be one of the available accounts, verbatim.\n"
                f"- `event_id` is the Google Calendar event id of the event "
                f"to delete. Typically 20-30 char alphanumeric.\n"
                f"- If prior step results above include a calendar_read with "
                f"events, FIRST match the description against those events "
                f"by title and/or start time. If multiple match, OR no "
                f"event's title/start matches the description's explicit "
                f"cues, return null for event_id. Do NOT guess.\n"
                f"- `match_evidence` is your stated reason for picking this "
                f"id: a substring of the matching event's title OR a "
                f"substring of its start datetime. This is VERIFIED against "
                f"the fetched event before delete — if the actual event "
                f"doesn't contain your stated evidence, the delete is "
                f"REFUSED. So only return evidence you're certain matches.\n"
                f"- If you cannot articulate a specific match_evidence, "
                f"return null for both event_id and match_evidence.\n\n"
                f"Respond in JSON:\n"
                f'{{"account": "<account>", '
                f'"event_id": "<google_event_id_or_null>", '
                f'"match_evidence": "<substring_from_title_or_start>"}}'
            )
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=512,
                disable_thinking=True,
            )

            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "calendar_delete",
                }

            account = (params.get("account") or "").strip()
            event_id = (params.get("event_id") or "").strip()
            match_evidence = (params.get("match_evidence") or "").strip()

            if account not in accounts:
                return {
                    "ok": False,
                    "error": (
                        f"extracted account '{account}' is not in connected "
                        f"accounts — refusing. Available: {accounts_list}"
                    ),
                    "verified": False,
                    "method": "calendar_delete",
                    "extracted": {"account": account, "event_id": event_id, "match_evidence": match_evidence},
                }
            if not event_id:
                return {
                    "ok": False,
                    "error": (
                        "extracted event_id is empty — refusing to delete. "
                        "Either no prior calendar_read provided context, or "
                        "the description didn't match any prior event."
                    ),
                    "verified": False,
                    "method": "calendar_delete",
                    "extracted": {"account": account, "event_id": event_id, "match_evidence": match_evidence},
                }
            if not match_evidence:
                return {
                    "ok": False,
                    "error": (
                        "extractor did not provide match_evidence — refusing "
                        "to delete. Destructive actions require the LLM to "
                        "state which title/start substring justified the id "
                        "resolution, so the dispatcher can verify against "
                        "the fetched event."
                    ),
                    "verified": False,
                    "method": "calendar_delete",
                    "extracted": {"account": account, "event_id": event_id, "match_evidence": match_evidence},
                }

            # Extra safety: GET the event first, surface what's about to be
            # destroyed in the trace, then DELETE. If the GET fails, refuse.
            existing = await get_event(account, event_id)
            if not existing.get("ok"):
                return {
                    "ok": False,
                    "error": (
                        f"could not fetch event {event_id} before delete — "
                        f"refusing. {existing.get('error', '')[:200]}"
                    ),
                    "verified": False,
                    "method": "calendar_delete",
                    "extracted": {"account": account, "event_id": event_id, "match_evidence": match_evidence},
                }
            event_obj = existing.get("event", {}) or {}
            event_title = event_obj.get("summary", "(no title)")
            event_start = (event_obj.get("start") or {}).get("dateTime") \
                          or (event_obj.get("start") or {}).get("date") or ""

            # Match-evidence cross-check: the fetched event MUST contain
            # the LLM's stated match_evidence in title or start. Same
            # safety pattern as gmail_delete — catches the case where the
            # LLM picks an arbitrary id from prior_results without
            # actually matching the goal.
            ev_lower = match_evidence.lower()
            haystack = (event_title + " " + event_start).lower()
            if ev_lower not in haystack:
                return {
                    "ok": False,
                    "error": (
                        f"match_evidence '{match_evidence}' does NOT appear "
                        f"in the fetched event's title or start — refusing "
                        f"to delete. LLM extractor picked an id that "
                        f"doesn't match its own stated evidence."
                    ),
                    "verified": False,
                    "method": "calendar_delete",
                    "extracted": {
                        "account": account,
                        "event_id": event_id,
                        "match_evidence": match_evidence,
                        "fetched_title": event_title,
                        "fetched_start": event_start,
                    },
                }

            result = await delete_event(account, event_id)
            success = bool(result.get("ok"))
            return {
                "ok": success,
                "result": {
                    "account": account,
                    "event_id": event_id,
                    "deleted_title": event_title,
                    "deleted_start": event_start,
                    "deleted": success,
                    "calendar_api_response": result.get("error", "")[:200]
                                              if not success
                                              else f"HTTP {result.get('status_code')}",
                },
                "verified": success,
                "method": "calendar_delete",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"calendar_delete failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "calendar_delete",
            }

    if capability_key == "vinted_draft_create":
        # Generates a Vinted listing draft from photo(s). This is the first
        # capability that needs binary input not extractable from a step
        # description — payload threading was added to execute_plan for this
        # class of capability.
        #
        # Caller passes payload={"images": [{"base64": "...", "mime": "image/jpeg"}, ...]}
        # OR payload={"image_base64": "...", "image_mime": "image/jpeg"} (single).
        # Without images the dispatcher refuses cleanly — full_listing_pipeline
        # would otherwise fall back to "Unknown item" and produce a useless
        # draft.
        #
        # Read-only by registry classification (low risk, no approval needed)
        # — drafts are local artefacts; nothing is posted externally. The
        # downstream "actually post to Vinted" capability is the separate
        # vinted_playwright_operator (status=not_built, approval_required=True).
        try:
            images = payload.get("images") or []
            image_base64 = payload.get("image_base64") or ""
            image_mime = payload.get("image_mime") or "image/jpeg"
            user_notes = payload.get("user_notes") or description  # description doubles as notes
            condition = payload.get("condition") or "good"

            if not images and not image_base64:
                return {
                    "ok": False,
                    "error": (
                        "vinted_draft_create requires images in the payload "
                        "(payload.images=[{base64, mime}] or payload.image_base64). "
                        "Step descriptions cannot carry binary data — caller "
                        "must supply photos via the run-goal payload field."
                    ),
                    "verified": False,
                    "method": "vinted_draft_create",
                }

            from app.core.vinted import full_listing_pipeline
            result = await full_listing_pipeline(
                image_base64=image_base64,
                image_mime=image_mime,
                platform="vinted",
                condition=condition,
                user_notes=user_notes,
                images=images,
            )
            listing = (result or {}).get("listing") or {}
            warnings = (result or {}).get("warnings") or []
            # Verified = pipeline didn't fall back AND produced a non-Unknown title
            verified = (
                "vision_identification" not in warnings
                and bool(listing.get("title"))
                and listing.get("title", "").lower() != "unknown item"
            )
            return {
                "ok": bool(listing),
                "result": {
                    "title": (listing.get("title") or "")[:120],
                    "description_chars": len(listing.get("description") or ""),
                    "price": listing.get("price"),
                    "category": listing.get("category"),
                    "condition": listing.get("condition"),
                    "warnings": warnings,
                    "fallbacks_used": warnings,
                },
                "verified": verified,
                "method": "vinted_draft_create",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"vinted_draft_create failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "vinted_draft_create",
            }

    if capability_key == "calendar_read":
        # Read-only: upcoming events from the first connected Gmail account
        # (calendar uses the same OAuth tokens with calendar scope). Returns
        # compact event summary suitable for downstream chat/summarise steps.
        try:
            from app.core.gmail_service import get_all_accounts
            from app.core.calendar_service import get_upcoming_events
            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no connected accounts — calendar uses Gmail OAuth tokens",
                    "verified": False,
                    "method": "calendar_read",
                }
            account = accounts[0]
            events = await get_upcoming_events(account, days=7)
            # Include the Google event `id` so chain-aware consumers
            # (calendar_delete especially) can resolve "delete the test
            # event tomorrow" → match by title/time, then use the id.
            # Same pattern as gmail_read returning from_address.
            summary = [
                {
                    "id": e.get("id"),
                    "title": e.get("title") or e.get("summary") or "(no title)",
                    "start": (e.get("start") or "")[:19],
                    "end": (e.get("end") or "")[:19],
                    "location": (e.get("location") or "")[:80],
                }
                for e in (events or [])[:10]
            ]
            return {
                "ok": True,
                "result": {"account": account, "events": summary, "count": len(events or [])},
                "verified": len(summary) > 0,
                "method": "calendar_read",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"calendar_read failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "calendar_read",
            }

    if capability_key == "calendar_write":
        # Three-layer safety, same pattern as gmail_send:
        #   1. Registry: external_effect=True, approval_required=True
        #      (set by seed_capabilities_v1) → governor default-denies
        #      without approval_token.
        #   2. LLM extraction of {account, title, start_iso, end_iso,
        #      description?, location?} with disable_thinking=True
        #      (trivial-shape JSON, no reasoning needed).
        #   3. Strict validation before create_event: account in connected
        #      accounts; start_iso and end_iso parse as datetimes; end >
        #      start; title non-empty. Any failure → clean refusal with
        #      the named failing field. No fabricated event creation.
        try:
            from app.core.gmail_service import get_all_accounts
            from app.core.calendar_service import create_event
            from app.core.model_router import gemini_json
            from datetime import datetime

            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no connected accounts — calendar uses Gmail OAuth tokens",
                    "verified": False,
                    "method": "calendar_write",
                }
            accounts_list = ", ".join(accounts)

            # Chain-aware: if prior steps produced calendar_read results,
            # inject them so the extractor can pick slots that don't
            # conflict with existing events. Useful for goals like
            # "find a free hour tomorrow and schedule X" or "book a
            # meeting after my last event today."
            prior_block = _format_prior_results(prior_results)
            extract_prompt = (
                (prior_block if prior_block else "")
                + f"Extract structured calendar-event-creation parameters from "
                f"this step description.\n\n"
                f"Description: {description}\n\n"
                f"Available accounts (calendar uses Gmail OAuth — pick one): "
                f"{accounts_list}\n\n"
                f"Today's date: {datetime.utcnow().strftime('%Y-%m-%d')} (UTC)\n\n"
                f"Rules:\n"
                f"- `account` must be one of the available accounts, verbatim.\n"
                f"- `start_iso` and `end_iso` MUST be full ISO 8601 datetimes "
                f"like '2026-06-02T15:00:00'. If the description gives "
                f"relative times (e.g. 'tomorrow 3pm'), resolve them against "
                f"today's date above. End must be after start.\n"
                f"- If prior step results above include calendar_read events, "
                f"prefer a slot that does NOT overlap with any existing "
                f"event (look at each event's start/end). For goals like "
                f"'find a free time' or 'after my last meeting', use those "
                f"events to choose a non-conflicting time. Brief gap-of-15-"
                f"minutes between adjacent events is fine; overlapping is "
                f"not.\n"
                f"- `title` must be a non-empty string.\n"
                f"- `description` and `location` are optional — return empty "
                f"strings if not mentioned.\n"
                f"- If ANY required field cannot be determined safely, "
                f"return null for that field rather than guessing.\n\n"
                f"Respond in JSON:\n"
                f'{{"account": "<account>", "title": "<title>", '
                f'"start_iso": "<YYYY-MM-DDTHH:MM:SS>", '
                f'"end_iso": "<YYYY-MM-DDTHH:MM:SS>", '
                f'"description": "<optional desc>", '
                f'"location": "<optional location>"}}'
            )
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=1024,
                disable_thinking=True,
            )

            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "calendar_write",
                }

            account = (params.get("account") or "").strip()
            title = (params.get("title") or "").strip()
            start_iso = (params.get("start_iso") or "").strip()
            end_iso = (params.get("end_iso") or "").strip()
            desc = (params.get("description") or "").strip()
            location = (params.get("location") or "").strip()

            if account not in accounts:
                return {
                    "ok": False,
                    "error": (
                        f"extracted account '{account}' is not in connected "
                        f"accounts — refusing. Available: {accounts_list}"
                    ),
                    "verified": False,
                    "method": "calendar_write",
                    "extracted": {"account": account, "title": title,
                                  "start_iso": start_iso, "end_iso": end_iso},
                }
            if not title:
                return {
                    "ok": False,
                    "error": "extracted title is empty — refusing to create event",
                    "verified": False,
                    "method": "calendar_write",
                }
            try:
                start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return {
                    "ok": False,
                    "error": (
                        f"start_iso/end_iso did not parse as ISO datetimes "
                        f"(got start={start_iso!r}, end={end_iso!r}) — "
                        f"refusing to create event"
                    ),
                    "verified": False,
                    "method": "calendar_write",
                }
            if end_dt <= start_dt:
                return {
                    "ok": False,
                    "error": (
                        f"end ({end_iso}) is not after start ({start_iso}) "
                        f"— refusing to create event"
                    ),
                    "verified": False,
                    "method": "calendar_write",
                }

            result = await create_event(account, title, start_iso, end_iso,
                                        description=desc, location=location)
            success = bool(result.get("ok"))
            return {
                "ok": success,
                "result": {
                    "account": account,
                    "title": title,
                    "start": start_iso,
                    "end": end_iso,
                    "created": success,
                    "calendar_api_response": (result.get("event") or {}).get("id")
                                              or result.get("error", "")[:200],
                },
                "verified": success,
                "method": "calendar_write",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"calendar_write failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "calendar_write",
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
            import re as _re
            emails = await search_all_accounts(description, max_per_account=5)

            # Parse "Name <email@domain.com>" RFC-822 from-lines so chain-
            # aware consumers (gmail_send reply-resolution especially) can
            # find the actual email address. Display name and parsed
            # address both kept; raw is preserved too.
            _addr_re = _re.compile(r"<([\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,})>")
            _bare_re = _re.compile(r"^[\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,}$")
            def _parse_from(raw: str) -> tuple:
                raw = (raw or "").strip()
                m = _addr_re.search(raw)
                if m:
                    addr = m.group(1)
                    name = raw[: m.start()].strip(" \"\t<>")
                    return name or addr, addr, raw
                if _bare_re.match(raw):
                    return raw, raw, raw
                return raw, "", raw

            # Compact summary — full email bodies would bloat the trace.
            # Keep enough to confirm the read worked and feed downstream steps.
            # `id` (Gmail message id) is included so chain-aware consumers
            # (gmail_delete especially) can resolve "trash that vinted email
            # from earlier" → match by subject/from/date → pull the id.
            # Same pattern as calendar_read's id addition.
            summary = []
            for e in (emails or [])[:10]:
                name, addr, raw = _parse_from(e.get("from") or "")
                summary.append({
                    "id": e.get("id"),
                    "account": e.get("account"),
                    "from_name": name,
                    "from_address": addr,  # parsed email (empty if not present)
                    "from": raw,           # raw RFC-822 from-line, preserved
                    "subject": (e.get("subject") or "")[:80],
                    "date": (e.get("date") or "")[:16],
                    "snippet": (e.get("snippet") or "")[:200],
                })
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
    payload: Optional[Dict[str, Any]] = None,
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
    prior_results: List[Dict[str, Any]] = []
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
        outcome = await _execute_step(step, payload=payload, prior_results=prior_results)
        executed_steps.append({
            **step,
            "execution": outcome,
            "final_status": "done" if outcome.get("ok") else "failed",
        })
        # Build the chain-aware-execution accumulator from successful steps
        # only. Failures don't propagate forward — downstream steps
        # shouldn't reason about garbage outputs.
        if outcome.get("ok"):
            cap_inner = step.get("registry_match") or {}
            prior_results.append({
                "step_number": step_number,
                "capability_key": (cap_inner.get("capability_key") or cap_inner.get("name") or "?"),
                "description": step.get("description"),
                "result": outcome.get("result"),
                "verified": bool(outcome.get("verified")),
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


async def run_goal(
    goal_text: str,
    approval_token: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compose: plan_goal → execute_plan. The full end-to-end loop.

    Args:
      goal_text: natural-language goal
      approval_token: optional non-empty string greenlighting external-effect
        and self-modify class steps (see app/core/governor.py)
      payload: optional dict for structured/binary step inputs (see
        _execute_step). Threads through to each step's dispatcher.

    Returns:
      {ok, plan, execution, error}
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

    execution = await execute_plan(plan, approval_token=approval_token, payload=payload)
    return {
        "ok": execution.get("ok", False),
        "plan": plan,
        "execution": execution,
        "error": None,
    }
