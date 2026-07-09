"""
Today brief - one actionable daily surface for Nova.
"""
from typing import Any, Dict, List


def _safe_count(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _build_next_actions(
    approvals_count: int,
    email_digest: Dict[str, Any],
    recent_activity: List[Dict[str, Any]],
    codebase_stats: Dict[str, Any],
) -> List[str]:
    actions = []
    if approvals_count:
        actions.append(f"Review {approvals_count} pending approval(s).")

    if email_digest:
        if not email_digest.get("ok", True):
            actions.append("Check Gmail connection errors.")
        elif _safe_count(email_digest.get("needs_reply_count")):
            actions.append(f"Review {_safe_count(email_digest.get('needs_reply_count'))} email reply draft(s).")
        elif _safe_count(email_digest.get("urgent_count")):
            actions.append(f"Read {_safe_count(email_digest.get('urgent_count'))} urgent email(s).")

    if codebase_stats.get("error"):
        actions.append("Check codebase sync status.")
    elif not codebase_stats.get("sources"):
        actions.append("Run codebase sync so Nova can resume code work accurately.")

    failed_recent = [
        r for r in recent_activity[:5]
        if str(r.get("status", "")).lower() in ("failed", "error")
    ]
    if failed_recent:
        actions.append("Review recent failed Nova run(s).")

    if not actions:
        actions.append("No urgent action surfaced.")
    return actions


async def get_today_brief() -> Dict[str, Any]:
    """Gather the main daily signals into one stable response shape."""
    briefing = ""
    briefing_state: Dict[str, Any] = {}
    try:
        from app.core.intelligent_briefing import get_intelligent_briefing

        result = await get_intelligent_briefing()
        briefing = result.get("briefing", "") or ""
        briefing_state = result.get("state", {}) or {}
    except Exception as e:
        briefing = "Briefing unavailable."
        briefing_state = {"error": f"{type(e).__name__}: {e}"}

    try:
        from app.core.approval_lock import list_active_pending_approvals

        approvals = list_active_pending_approvals(limit=10)
    except Exception:
        approvals = []

    try:
        from app.core.run_ledger import recent_runs

        recent_activity = recent_runs(limit=5)
    except Exception:
        recent_activity = []

    try:
        from app.core.codebase_sync import get_codebase_stats

        codebase_stats = get_codebase_stats()
    except Exception as e:
        codebase_stats = {"error": f"{type(e).__name__}: {e}"}

    email_digest = briefing_state.get("email_digest") or {}
    next_actions = _build_next_actions(
        approvals_count=len(approvals),
        email_digest=email_digest,
        recent_activity=recent_activity,
        codebase_stats=codebase_stats,
    )

    return {
        "ok": True,
        "briefing": briefing,
        "attention": {
            "pending_approvals_count": len(approvals),
            "email": {
                "ok": email_digest.get("ok"),
                "count": email_digest.get("count"),
                "urgent_count": email_digest.get("urgent_count"),
                "needs_reply_count": email_digest.get("needs_reply_count"),
                "error": email_digest.get("error"),
                "errors": email_digest.get("errors") or [],
            } if email_digest else None,
            "recent_activity_count": len(recent_activity),
            "codebase": codebase_stats,
        },
        "next_actions": next_actions,
        "pending_approvals": approvals[:5],
        "recent_activity": recent_activity[:5],
    }
