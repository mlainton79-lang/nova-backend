"""Quality checks for Nova memory capture and retrieval."""

from typing import Any, Dict


def _normalise(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def score_retrieval_result(expected_text: str, results: list[dict]) -> Dict[str, Any]:
    expected = _normalise(expected_text)
    matched = None
    for index, item in enumerate(results or []):
        text = _normalise(item.get("text", ""))
        if expected and (expected in text or text in expected):
            matched = {"rank": index + 1, "id": item.get("id")}
            break

    return {
        "ok": matched is not None,
        "matched": matched,
        "result_count": len(results or []),
        "status": "pass" if matched is not None else "not_found",
    }


async def run_capture_retrieval_eval(
    text: str = "The blue folder is for nursery forms.",
    query: str = "nursery forms blue folder",
) -> Dict[str, Any]:
    from app.core.capture import capture_note
    from app.core.semantic_memory import search_memories

    capture = await capture_note(text, category="daily_capture")
    results = await search_memories(query, top_k=5, category="daily_capture")
    score = score_retrieval_result(text, results)
    return {
        "ok": bool(capture.get("ok")) and score["ok"],
        "capture": capture,
        "query": query,
        "score": score,
        "results": results,
    }
