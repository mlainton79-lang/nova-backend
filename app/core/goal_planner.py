"""
Goal Planner v0 — R2.2.

Layer 1 of the self-extending-agent track. Given a stated goal, decompose
it into ordered atomic steps; for each step identify the required
capability from the registry; consult the governor for what would be
allowed; classify each step as `ready`, `needs_approval`, or `gap`.

CRITICAL: this module does NOT execute anything. It produces a structured
plan. Execution belongs to R2.4 (first end-to-end tool) and beyond; gap
handling belongs to R2.3 (gap_detector refactor — split detection from
acquisition).

Wiring (R2.2):
- Reads tony_capabilities via `app.core.capabilities.list_capabilities`
- Consults the governor via `app.core.governor.evaluate_action`
- Calls Gemini via `app.core.model_router.gemini_json` with task='planning'

Plan shape returned by `plan_goal()`:

    {
      "ok": bool,
      "goal": str,
      "steps": [
        {
          "step_number": int,
          "description": str,
          "required_capability": str | None,    # capability_key suggested by the LLM
          "registry_match": dict | None,         # the actual tony_capabilities row if matched
          "governor_decision": dict | None,      # evaluate_action() result
          "status": "ready" | "needs_approval" | "gap"
        },
        ...
      ],
      "summary": {"ready": int, "needs_approval": int, "gap": int, "total": int},
      "gaps": [{"step_number": int, "description": str, "suggested_capability": str}],
      "error": str | None
    }

Reference: nova-docs/master_plan_v3_self_extending_agent.md (R2.2 section),
nova-docs/ops/reviews/2026-06-01/codex-review-master-plan-v2.md (build
order rationale).
"""
from typing import Any, Dict, List, Optional


def _get_active_capabilities_for_prompt(max_chars: int = 16000) -> str:
    """Format the active registry as a compact list for the planner prompt.

    Includes capability_key + description only — enough for the LLM to
    pick a candidate, without bloating the prompt. Excludes deprecated
    and not_built_placeholder rows (planner shouldn't propose using
    something that isn't built).

    max_chars bumped from 4000 to 16000 on 2026-06-02 — with 60+ active
    capabilities alphabetically sorted, vinted_* and vision_* rows were
    being truncated out of the prompt, so the planner couldn't see them
    and routed those steps to `gap`. Pro tier comfortably handles a
    16000-char preamble.
    """
    try:
        from app.core.capabilities import list_capabilities
        caps = list_capabilities(status="active")
    except Exception as e:
        return f"[capabilities registry unavailable: {type(e).__name__}: {e}]"

    lines: List[str] = []
    total_chars = 0
    for cap in caps:
        key = cap.get("capability_key") or cap.get("name") or "?"
        desc = (cap.get("description") or "")[:160]
        ctype = cap.get("capability_type") or "?"
        line = f"- {key} [{ctype}]: {desc}"
        if total_chars + len(line) + 1 > max_chars:
            lines.append("- … (capabilities list truncated for prompt budget)")
            break
        lines.append(line)
        total_chars += len(line) + 1
    return "\n".join(lines) if lines else "(no active capabilities registered)"


async def _decompose_via_llm(goal_text: str, capabilities_text: str) -> Optional[Dict[str, Any]]:
    """Call Gemini to decompose the goal into ordered steps + capability
    suggestions. Returns the parsed JSON or None on failure (truncation,
    parse error, etc.).
    """
    prompt = f"""You are Tony's goal planner. Decompose the goal below into
ordered, atomic steps. For each step, identify which capability from the
registry is needed.

Goal: {goal_text}

Available capabilities (registry — pick from these, do not invent):
{capabilities_text}

Rules:
- Each step should be ONE concrete action — not "do X and Y" but "do X" then "do Y".
- For each step, pick the SINGLE best matching capability_key from the list above.
- If no capability fits a step, set "capability" to "gap" and add a brief
  "suggested_capability" hint naming what would be needed.
- If the goal is impossible or unclear, return one step with capability=
  "unclear" and a description explaining why.
- Keep it to 6 steps or fewer for v0.

Respond in JSON:
{{
  "steps": [
    {{
      "description": "one-sentence description of the step",
      "capability": "<capability_key from registry OR 'gap' OR 'unclear'>",
      "suggested_capability": "optional — only if capability='gap'"
    }}
  ]
}}"""
    try:
        from app.core.model_router import gemini_json
        return await gemini_json(prompt, task="planning", max_tokens=2048)
    except Exception as e:
        print(f"[GOAL_PLANNER] Decomposition LLM call failed: {type(e).__name__}: {e}")
        return None


def _resolve_step(step_payload: Dict[str, Any], step_number: int,
                  approval_token: Optional[str]) -> Dict[str, Any]:
    """Look up the capability for a step, consult the governor, classify
    the step as ready / needs_approval / gap. Pure function over the
    registry and governor — no execution.
    """
    description = (step_payload.get("description") or "").strip()
    required = (step_payload.get("capability") or "").strip()
    suggested = (step_payload.get("suggested_capability") or "").strip()

    base = {
        "step_number": step_number,
        "description": description,
        "required_capability": required if required and required not in ("gap", "unclear") else None,
        "registry_match": None,
        "governor_decision": None,
    }

    # Gap or unclear — no registry consult.
    if required in ("gap", "unclear", ""):
        base.update({
            "status": "gap",
            "suggested_capability": suggested or required or None,
        })
        return base

    # Try exact lookup first; fall back to fuzzy lookup.
    try:
        from app.core.capabilities import get_capability, lookup_capabilities
        match = get_capability(required)
        if match is None:
            candidates = lookup_capabilities(query=required, status="active")
            match = candidates[0] if candidates else None
    except Exception as e:
        base.update({
            "status": "gap",
            "suggested_capability": required,
            "error": f"registry lookup failed: {type(e).__name__}: {e}",
        })
        return base

    if match is None:
        base.update({
            "status": "gap",
            "suggested_capability": required,
        })
        return base

    base["registry_match"] = match

    # Consult the governor.
    try:
        from app.core.governor import evaluate_action
        decision = evaluate_action(match, approval_token=approval_token)
    except Exception as e:
        base.update({
            "status": "gap",
            "suggested_capability": required,
            "error": f"governor evaluation failed: {type(e).__name__}: {e}",
        })
        return base

    base["governor_decision"] = decision

    if decision.get("allowed"):
        base["status"] = "ready"
    elif decision.get("requires_approval"):
        base["status"] = "needs_approval"
    else:
        base["status"] = "gap"  # denied for a reason other than approval — treat as gap
    return base


async def plan_goal(goal_text: str, approval_token: Optional[str] = None) -> Dict[str, Any]:
    """Plan a goal end-to-end. Pure planning — never executes anything.

    Args:
        goal_text: the goal as a natural-language string
        approval_token: optional non-empty string indicating Matthew has
            pre-approved actions this run. R2.1b governor accepts any
            non-empty string as approval; R2.3 will tighten the contract.

    Returns the plan dict (shape documented at module top). On any
    upstream failure (empty goal, LLM returns nothing, registry/governor
    unreachable), returns `{ok: False, error: "..."}` with a partial
    plan if available.
    """
    if not goal_text or not goal_text.strip():
        return {
            "ok": False,
            "goal": goal_text or "",
            "steps": [],
            "summary": {"ready": 0, "needs_approval": 0, "gap": 0, "total": 0},
            "gaps": [],
            "error": "empty_goal",
        }

    goal_text = goal_text.strip()
    capabilities_text = _get_active_capabilities_for_prompt()
    decomp = await _decompose_via_llm(goal_text, capabilities_text)

    if not decomp or not isinstance(decomp, dict):
        return {
            "ok": False,
            "goal": goal_text,
            "steps": [],
            "summary": {"ready": 0, "needs_approval": 0, "gap": 0, "total": 0},
            "gaps": [],
            "error": "decomposition_failed",
        }

    raw_steps = decomp.get("steps", []) or []
    if not isinstance(raw_steps, list):
        return {
            "ok": False,
            "goal": goal_text,
            "steps": [],
            "summary": {"ready": 0, "needs_approval": 0, "gap": 0, "total": 0},
            "gaps": [],
            "error": "decomposition_returned_non_list_steps",
        }

    resolved: List[Dict[str, Any]] = []
    for i, raw in enumerate(raw_steps[:6], start=1):  # cap at 6 per the prompt rule
        if not isinstance(raw, dict):
            continue
        resolved.append(_resolve_step(raw, i, approval_token))

    summary = {
        "ready": sum(1 for s in resolved if s["status"] == "ready"),
        "needs_approval": sum(1 for s in resolved if s["status"] == "needs_approval"),
        "gap": sum(1 for s in resolved if s["status"] == "gap"),
        "total": len(resolved),
    }

    gaps = [
        {
            "step_number": s["step_number"],
            "description": s["description"],
            "suggested_capability": s.get("suggested_capability"),
        }
        for s in resolved if s["status"] == "gap"
    ]

    plan = {
        "ok": True,
        "goal": goal_text,
        "steps": resolved,
        "summary": summary,
        "gaps": gaps,
        "error": None,
    }

    _emit_plan_event(goal_text, summary)
    return plan


def _emit_plan_event(goal_text: str, summary: Dict[str, int]) -> None:
    """Best-effort observability — never raises."""
    try:
        from app.observability import record_run_event, EventSeverity
        sev = EventSeverity.INFO if summary["total"] > 0 else EventSeverity.WARNING
        record_run_event(
            event_type="goal_planner_plan_produced",
            severity=sev,
            subsystem="goal_planner",
            message=(
                f"plan produced: total={summary['total']} ready={summary['ready']} "
                f"needs_approval={summary['needs_approval']} gap={summary['gap']}"
            ),
            metadata={
                "goal_chars": len(goal_text),
                "total_steps": summary["total"],
                "ready": summary["ready"],
                "needs_approval": summary["needs_approval"],
                "gap": summary["gap"],
            },
        )
    except Exception:
        pass
