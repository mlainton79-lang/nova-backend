"""Deterministic quality checks for Nova's daily Capture/Resume/Review loop."""

from typing import Any, Dict, Iterable, List


def _has_nonempty_list(payload: Dict[str, Any], key: str) -> bool:
    return isinstance(payload.get(key), list) and bool(payload.get(key))


def _score_checks(checks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    check_list = list(checks)
    passed = sum(1 for check in check_list if check["passed"])
    total = len(check_list)
    return {
        "passed": passed,
        "total": total,
        "score": round(passed / total, 3) if total else 0.0,
        "checks": check_list,
    }


def evaluate_today_brief_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = [
        {
            "name": "has_briefing_text",
            "passed": bool(str(payload.get("briefing") or "").strip()),
            "message": "Today Brief should include user-facing briefing text.",
        },
        {
            "name": "has_next_actions",
            "passed": _has_nonempty_list(payload, "next_actions"),
            "message": "Today Brief should always include next_actions.",
        },
        {
            "name": "has_health_flags_array",
            "passed": isinstance(payload.get("health_flags"), list),
            "message": "Today Brief should expose health_flags as a list.",
        },
        {
            "name": "has_email_attention",
            "passed": isinstance(payload.get("email_attention"), dict),
            "message": "Today Brief should expose email_attention previews.",
        },
        {
            "name": "has_approval_cards_array",
            "passed": isinstance(payload.get("approval_cards"), list),
            "message": "Today Brief should expose approval_cards as a list.",
        },
    ]
    result = _score_checks(checks)
    result["surface"] = "today_brief"
    return result


def evaluate_daily_review_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = [
        {
            "name": "has_review_text",
            "passed": bool(str(payload.get("review") or "").strip()),
            "message": "Daily Review should include user-facing review text.",
        },
        {
            "name": "has_follow_up_actions",
            "passed": _has_nonempty_list(payload, "follow_up_actions"),
            "message": "Daily Review should always include follow_up_actions.",
        },
        {
            "name": "has_signals",
            "passed": isinstance(payload.get("signals"), dict),
            "message": "Daily Review should expose raw signals for debugging.",
        },
        {
            "name": "has_run_ledger_signal",
            "passed": isinstance((payload.get("signals") or {}).get("run_ledger"), dict),
            "message": "Daily Review should include Run Ledger signal data.",
        },
    ]
    result = _score_checks(checks)
    result["surface"] = "daily_review"
    return result


def evaluate_capture_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = [
        {
            "name": "has_boolean_ok",
            "passed": isinstance(payload.get("ok"), bool),
            "message": "Capture result should include boolean ok.",
        },
        {
            "name": "has_boolean_saved",
            "passed": isinstance(payload.get("saved"), bool),
            "message": "Capture result should include boolean saved.",
        },
        {
            "name": "has_status",
            "passed": bool(str(payload.get("status") or "").strip()),
            "message": "Capture result should include a status string.",
        },
    ]
    result = _score_checks(checks)
    result["surface"] = "capture"
    return result


def combine_daily_loop_quality(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    result_list = list(results)
    passed = sum(int(result.get("passed") or 0) for result in result_list)
    total = sum(int(result.get("total") or 0) for result in result_list)
    return {
        "ok": True,
        "passed": passed,
        "total": total,
        "score": round(passed / total, 3) if total else 0.0,
        "surfaces": result_list,
        "status": "pass" if total and passed == total else "needs_attention",
    }
