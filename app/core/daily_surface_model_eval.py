"""Model-assisted evals for Nova's Today Brief and Daily Review surfaces."""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


SURFACE_RUBRICS = {
    "today_brief": [
        "Names the current situation in plain language.",
        "Gives concrete next actions instead of vague encouragement.",
        "Surfaces risks, blocked approvals, or data-source health issues.",
        "Keeps raw debug detail out of the user-facing briefing.",
    ],
    "daily_review": [
        "Summarises what changed today in plain language.",
        "Includes practical follow-up actions.",
        "Uses activity signals instead of generic reflection.",
        "Avoids claiming certainty when signal data is missing.",
    ],
}


def _compact_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)[:12000]


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = [
            line for line in cleaned.splitlines()
            if not line.strip().startswith("```")
        ]
        cleaned = "\n".join(lines).strip()

    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first < 0 or last < first:
        return None
    try:
        parsed = json.loads(cleaned[first:last + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def build_daily_surface_judge_prompt(surface: str, payload: Dict[str, Any]) -> str:
    rubric = SURFACE_RUBRICS.get(surface)
    if not rubric:
        raise ValueError(f"Unknown daily surface: {surface}")

    rubric_text = "\n".join(f"- {item}" for item in rubric)
    return f"""You are judging a Nova daily-loop product surface.

Surface: {surface}

Rubric:
{rubric_text}

Payload JSON:
{_compact_json(payload)}

Return STRICT JSON only:
{{
  "score": 0.0,
  "passed": false,
  "reasons": ["short concrete reason"],
  "recommendations": ["short concrete improvement"]
}}"""


def _list_len(payload: Dict[str, Any], key: str) -> int:
    value = payload.get(key)
    return len(value) if isinstance(value, list) else 0


def _dict_has_any(payload: Dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    return isinstance(value, dict) and bool(value)


def heuristic_daily_surface_score(surface: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Cheap local judge used when no model key is available."""
    checks: List[Dict[str, Any]]
    if surface == "today_brief":
        briefing = str(payload.get("briefing") or "").strip()
        checks = [
            {"name": "briefing_text", "passed": bool(briefing)},
            {"name": "next_actions", "passed": _list_len(payload, "next_actions") > 0},
            {"name": "health_flags", "passed": isinstance(payload.get("health_flags"), list)},
            {"name": "email_attention", "passed": isinstance(payload.get("email_attention"), dict)},
            {"name": "approval_cards", "passed": isinstance(payload.get("approval_cards"), list)},
        ]
    elif surface == "daily_review":
        review = str(payload.get("review") or "").strip()
        signals = payload.get("signals") if isinstance(payload.get("signals"), dict) else {}
        checks = [
            {"name": "review_text", "passed": bool(review)},
            {"name": "follow_up_actions", "passed": _list_len(payload, "follow_up_actions") > 0},
            {"name": "signals", "passed": _dict_has_any(payload, "signals")},
            {"name": "run_ledger_signal", "passed": isinstance(signals.get("run_ledger"), dict)},
        ]
    else:
        raise ValueError(f"Unknown daily surface: {surface}")

    passed_count = sum(1 for check in checks if check["passed"])
    total = len(checks)
    failed = [check["name"] for check in checks if not check["passed"]]
    score = round(passed_count / total, 3) if total else 0.0
    return {
        "surface": surface,
        "judge": "heuristic",
        "score": score,
        "passed": score >= 0.8,
        "reasons": (
            ["Surface has the expected user-facing structure."]
            if not failed else [f"Missing or weak checks: {', '.join(failed)}."]
        ),
        "recommendations": (
            [] if not failed else [f"Strengthen: {', '.join(failed)}."]
        ),
        "checks": checks,
    }


def _normalise_model_judgement(
    surface: str,
    parsed: Dict[str, Any],
    fallback: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        score = float(parsed.get("score", fallback["score"]))
    except (TypeError, ValueError):
        score = fallback["score"]
    score = max(0.0, min(1.0, round(score, 3)))

    reasons = parsed.get("reasons")
    if not isinstance(reasons, list):
        reason = parsed.get("reason")
        reasons = [str(reason)] if reason else fallback["reasons"]
    reasons = [str(reason)[:240] for reason in reasons if str(reason).strip()] or fallback["reasons"]

    recommendations = parsed.get("recommendations")
    if not isinstance(recommendations, list):
        recommendations = fallback.get("recommendations", [])
    recommendations = [
        str(item)[:240] for item in recommendations if str(item).strip()
    ][:5]

    return {
        "surface": surface,
        "judge": "gemini",
        "score": score,
        "passed": bool(parsed.get("passed", score >= 0.8)),
        "reasons": reasons[:5],
        "recommendations": recommendations,
        "fallback_score": fallback["score"],
    }


async def judge_daily_surface(surface: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    fallback = heuristic_daily_surface_score(surface, payload)
    if not os.environ.get("GEMINI_API_KEY"):
        return fallback

    prompt = build_daily_surface_judge_prompt(surface, payload)
    try:
        from app.core import gemini_client

        response_json = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={
                "maxOutputTokens": 512,
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
            timeout=20.0,
            caller_context="daily_surface_model_eval",
        )
        parsed = _extract_json_object(gemini_client.extract_text(response_json))
        if not parsed:
            return {**fallback, "judge_note": "model returned no parseable JSON"}
        return _normalise_model_judgement(surface, parsed, fallback)
    except Exception as exc:
        return {**fallback, "judge_note": f"model judge error: {str(exc)[:160]}"}


def combine_daily_surface_model_evals(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    result_list = list(results)
    average = (
        round(sum(float(result.get("score") or 0) for result in result_list) / len(result_list), 3)
        if result_list else 0.0
    )
    return {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "score": average,
        "status": "pass" if result_list and all(result.get("passed") for result in result_list) else "needs_attention",
        "surfaces": result_list,
    }


async def run_daily_surface_model_eval() -> Dict[str, Any]:
    from app.core.daily_review import get_daily_review
    from app.core.today_brief import get_today_brief

    today_payload = await get_today_brief()
    review_payload = await get_daily_review()

    return combine_daily_surface_model_evals([
        await judge_daily_surface("today_brief", today_payload),
        await judge_daily_surface("daily_review", review_payload),
    ])
