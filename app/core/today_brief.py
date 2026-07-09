"""
Today brief - one actionable daily surface for Nova.
"""
from typing import Any, Dict, List


def _safe_count(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _build_health_flags(
    email_digest: Dict[str, Any],
    recent_activity: List[Dict[str, Any]],
    codebase_stats: Dict[str, Any],
    approval_summary: Dict[str, Any],
) -> List[Dict[str, str]]:
    flags: List[Dict[str, str]] = []

    if email_digest and not email_digest.get("ok", True):
        flags.append({
            "code": "gmail_connection",
            "severity": "warning",
            "message": "Gmail triage has connection errors.",
        })

    if _safe_count(approval_summary.get("high_risk_count")):
        flags.append({
            "code": "high_risk_approvals",
            "severity": "attention",
            "message": "High-risk approvals are waiting.",
        })

    if codebase_stats.get("error"):
        flags.append({
            "code": "codebase_sync_error",
            "severity": "warning",
            "message": "Codebase sync status could not be read.",
        })
    elif not codebase_stats.get("sources"):
        flags.append({
            "code": "codebase_sync_missing",
            "severity": "info",
            "message": "Codebase sync has no indexed sources.",
        })

    failed_recent = [
        r for r in recent_activity[:5]
        if str(r.get("status", "")).lower() in ("failed", "error")
    ]
    if failed_recent:
        flags.append({
            "code": "recent_run_failed",
            "severity": "warning",
            "message": "Recent Nova runs include failures.",
        })

    return flags


def _empty_email_attention(error: str | None = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"urgent": [], "needs_reply": [], "errors": []}
    if error:
        payload["errors"].append(error)
    return payload


def _get_email_attention(limit: int = 3) -> Dict[str, Any]:
    try:
        from app.core.email_triage import list_triage_items
    except Exception as e:
        return _empty_email_attention(f"{type(e).__name__}: {e}")

    attention = _empty_email_attention()
    for kind, output_key in (("urgent", "urgent"), ("needs_reply", "needs_reply")):
        try:
            result = list_triage_items(kind, limit=limit)
        except Exception as e:
            attention["errors"].append(f"{kind}: {type(e).__name__}: {e}")
            continue
        if not result.get("ok"):
            attention["errors"].append(f"{kind}: {result.get('error', 'unknown error')}")
            continue
        attention[output_key] = result.get("items", [])[:limit]
    return attention


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
        from app.core.approval_lock import (
            build_pending_approval_summary,
            list_active_pending_approvals,
        )

        approvals = list_active_pending_approvals(limit=10)
    except Exception:
        approvals = []
        approval_summary = {
            "count": 0,
            "has_pending": False,
            "high_risk_count": 0,
            "risk_counts": {"high": 0, "medium": 0, "low": 0, "unknown": 0},
            "cards": [],
        }
    else:
        approval_summary = build_pending_approval_summary(approvals)

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
    email_attention = _get_email_attention(limit=3)
    next_actions = _build_next_actions(
        approvals_count=len(approvals),
        email_digest=email_digest,
        recent_activity=recent_activity,
        codebase_stats=codebase_stats,
    )
    health_flags = _build_health_flags(
        email_digest=email_digest,
        recent_activity=recent_activity,
        codebase_stats=codebase_stats,
        approval_summary=approval_summary,
    )

    return {
        "ok": True,
        "briefing": briefing,
        "attention": {
            "pending_approvals_count": len(approvals),
            "approvals": approval_summary,
            "email": {
                "ok": email_digest.get("ok"),
                "count": email_digest.get("count"),
                "urgent_count": email_digest.get("urgent_count"),
                "needs_reply_count": email_digest.get("needs_reply_count"),
                "error": email_digest.get("error"),
                "errors": email_digest.get("errors") or [],
            } if email_digest else None,
            "email_attention": email_attention,
            "recent_activity_count": len(recent_activity),
            "codebase": codebase_stats,
        },
        "health_flags": health_flags,
        "next_actions": next_actions,
        "email_attention": email_attention,
        "approval_cards": approval_summary["cards"][:5],
        "pending_approvals": approvals[:5],
        "recent_activity": recent_activity[:5],
    }
