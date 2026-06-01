"""
Autonomy Governor — R2.1b skeleton.

Pure classifier + policy layer. Given a capability registry entry
(`tony_capabilities` row, see `app/core/capabilities.py`), this module
answers two questions:

  1. classify_capability(cap)  →  action class:
       read_only | internal_write | external_effect | financial | self_modify
  2. evaluate_action(cap, approval_token=None)  →  policy decision:
       {allowed: bool, action_class: str, reason: str, requires_approval: bool,
        approval_satisfied: bool}

Policy (default-deny for external-effect / financial / self-modifying
actions unless the capability is pre-greenlit via approval_required=False
on the row OR the caller passes a non-empty approval_token):

  read_only          → allow
  internal_write     → allow
  external_effect    → require approval (cap row approval_required=False
                       counts as pre-approved by Matthew during
                       registration; otherwise caller must pass an
                       approval_token)
  financial          → require approval (same rules; tighter audit
                       because it costs money)
  self_modify        → require approval (modifies Nova's own code or
                       behaviour rules; safety-critical)

Kill-switch: `GOVERNOR_ENABLED` env var (default `true`). Setting to
false/0/no/off disables the policy enforcement — every action becomes
allowed regardless of class. Same shape as
`RETRIEVAL_FABRICATION_GUARD_ENABLED` (38a604c) and
`CODE_INTELLIGENCE_AUTO_REWRITE_ENABLED` (68b9dd0).

R2.1b deliberately does NOT wire the governor into chat_stream /
council / gap_detector. Wiring belongs to R2.2 (planner) and R2.3
(gap_detector refactor — split detection from acquisition). The
governor exists now so the planner has a policy framework to consult
from day one (per the Codex review, two rounds, 2026-06-01).

Observability: `governor.evaluation` events are recorded via
`record_run_event` for every evaluate_action call where the result
denies or requires approval. Findable via
`/api/v1/debug/recent-events?subsystem=governor.policy`. Best-effort —
the governor itself never raises.
"""
import os
from typing import Any, Dict, Optional


# ── Action classes ────────────────────────────────────────────────────────

READ_ONLY = "read_only"
INTERNAL_WRITE = "internal_write"
EXTERNAL_EFFECT = "external_effect"
FINANCIAL = "financial"
SELF_MODIFY = "self_modify"

ALL_ACTION_CLASSES = frozenset(
    {READ_ONLY, INTERNAL_WRITE, EXTERNAL_EFFECT, FINANCIAL, SELF_MODIFY}
)

# Action classes that require approval by default.
APPROVAL_REQUIRED_CLASSES = frozenset({EXTERNAL_EFFECT, FINANCIAL, SELF_MODIFY})


# ── Self-modification signal patterns ─────────────────────────────────────
# Capability_keys (substring match) that classify as self_modify regardless
# of other flags. Conservative — these all touch Nova's own code or
# behaviour rules and must always require approval.
_SELF_MODIFY_KEY_MARKERS = (
    "autonomous_push",
    "code_edit_",
    "capability_builder",
    "self_improvement_loop",
    "auto_rewrite",
    "rewrite_function",
)


# ── Kill-switch ───────────────────────────────────────────────────────────

def _is_enabled() -> bool:
    """Read GOVERNOR_ENABLED env var. Default true.

    Truthy values: anything except false/0/no/off (case-insensitive).
    When false, every action is allowed regardless of class — clean
    rollback without code revert if a false-deny surfaces in production.
    """
    v = os.environ.get("GOVERNOR_ENABLED", "true").strip().lower()
    return v not in ("false", "0", "no", "off")


# ── Classification ────────────────────────────────────────────────────────

def classify_capability(cap: Dict[str, Any]) -> str:
    """Return the action class for a capability row.

    Reads from the canonical `tony_capabilities` shape (see
    `app/core/capabilities.py::_row_to_dict`). Accepts the legacy alias
    keys too (`name` for capability_key, `endpoint` for locator) because
    R2.1's facade returns both — callers passing get_capabilities()
    rows work directly.

    Priority order (first match wins):
      1. self_modify  if capability_key contains a self-mod marker
      2. financial    if cost_type indicates spending AND external_effect
      3. external_effect  if external_effect=True
      4. internal_write   if risk_level is medium/high/critical
      5. read_only        otherwise
    """
    if not isinstance(cap, dict):
        return READ_ONLY  # safest default for unparseable input

    capability_key = (cap.get("capability_key") or cap.get("name") or "").lower()
    external_effect = bool(cap.get("external_effect"))
    cost_type = (cap.get("cost_type") or "free").lower()
    risk_level = (cap.get("risk_level") or "low").lower()

    # 1. Self-modification (highest precedence — overrides every other
    #    classification because the safety implications dominate)
    if any(marker in capability_key for marker in _SELF_MODIFY_KEY_MARKERS):
        return SELF_MODIFY

    # 2. Financial — spends money externally
    if external_effect and cost_type in ("metered", "platform_fee", "metered_paid"):
        return FINANCIAL

    # 3. External effect — anything that mutates state outside Nova
    #    (sends messages, posts listings, makes API writes to external
    #    services)
    if external_effect:
        return EXTERNAL_EFFECT

    # 4. Internal write — touches Nova's own state with non-trivial risk
    #    (medium/high/critical risk_level signals "could break Nova if
    #    misused" — schema migration, memory consolidation, etc.)
    if risk_level in ("medium", "high", "critical"):
        return INTERNAL_WRITE

    # 5. Default — read-only or trivial internal write
    return READ_ONLY


# ── Policy evaluation ─────────────────────────────────────────────────────

def evaluate_action(
    cap: Dict[str, Any],
    approval_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply the governor policy. Returns a structured decision.

    Args:
        cap: capability registry row (canonical or facade shape)
        approval_token: opaque non-empty string indicating the caller
            has Matthew's approval for THIS specific action invocation.
            R2.1b doesn't define how approval tokens are minted; that
            comes with R2.3's governed acquisition path. For now, any
            non-empty string counts as "explicitly approved."

    Returns:
        {
          allowed: bool,
          action_class: str,
          reason: str,
          requires_approval: bool,    # would this class normally need approval?
          approval_satisfied: bool,   # is the approval requirement satisfied?
        }

    The function is pure and never raises. If the governor kill-switch
    is off, returns allowed=True with reason="governor_disabled" so
    callers can log the rollback explicitly.
    """
    action_class = classify_capability(cap) if isinstance(cap, dict) else READ_ONLY
    requires_approval = action_class in APPROVAL_REQUIRED_CLASSES

    # Kill-switch: when GOVERNOR_ENABLED=false, every action is allowed.
    if not _is_enabled():
        decision = {
            "allowed": True,
            "action_class": action_class,
            "reason": "governor_disabled",
            "requires_approval": requires_approval,
            "approval_satisfied": False,
        }
        _emit_decision(cap, decision)
        return decision

    # No approval needed at this class — allow.
    if not requires_approval:
        return {
            "allowed": True,
            "action_class": action_class,
            "reason": "class_does_not_require_approval",
            "requires_approval": False,
            "approval_satisfied": False,
        }

    # Approval needed. Check the row's pre-approval flag — if the
    # capability was registered with approval_required=False, Matthew
    # already greenlit this class of action at registration time.
    cap_approval_required = bool(cap.get("approval_required", True)) if isinstance(cap, dict) else True
    if not cap_approval_required:
        decision = {
            "allowed": True,
            "action_class": action_class,
            "reason": "pre_approved_at_registration",
            "requires_approval": True,
            "approval_satisfied": True,
        }
        _emit_decision(cap, decision)
        return decision

    # Approval needed AND not pre-approved. Caller must pass a token.
    if approval_token and isinstance(approval_token, str) and approval_token.strip():
        decision = {
            "allowed": True,
            "action_class": action_class,
            "reason": "approval_token_present",
            "requires_approval": True,
            "approval_satisfied": True,
        }
        _emit_decision(cap, decision)
        return decision

    # Default-deny.
    decision = {
        "allowed": False,
        "action_class": action_class,
        "reason": "approval_required_but_not_provided",
        "requires_approval": True,
        "approval_satisfied": False,
    }
    _emit_decision(cap, decision)
    return decision


# ── Observability ─────────────────────────────────────────────────────────

def _emit_decision(cap: Dict[str, Any], decision: Dict[str, Any]) -> None:
    """Best-effort run_event for every non-trivial decision (denies,
    approvals, pre-approvals, kill-switch overrides). Read-only allows
    don't emit — they'd dwarf the signal once the governor is wired in.
    Must never raise.
    """
    try:
        from app.observability import record_run_event, EventSeverity
        severity = EventSeverity.WARNING if not decision["allowed"] else EventSeverity.INFO
        capability_key = (cap.get("capability_key") or cap.get("name") or "?") if isinstance(cap, dict) else "?"
        record_run_event(
            event_type="governor_action_evaluated",
            severity=severity,
            subsystem="governor.policy",
            message=(
                f"governor: {decision['action_class']} action "
                f"{'denied' if not decision['allowed'] else 'allowed'} — "
                f"{decision['reason']} (capability={capability_key})"
            ),
            metadata={
                "capability_key": capability_key,
                "action_class": decision["action_class"],
                "allowed": decision["allowed"],
                "reason": decision["reason"],
                "requires_approval": decision["requires_approval"],
                "approval_satisfied": decision["approval_satisfied"],
            },
        )
    except Exception:
        pass
