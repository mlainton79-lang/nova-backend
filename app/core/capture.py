"""Small capture helpers for low-risk notes."""

import re
from typing import Any, Dict


_SECRETISH_RE = re.compile(
    r"\b(password|passcode|api[_ -]?key|secret|token|refresh[_ -]?token|"
    r"access[_ -]?token|authorization|bearer|private[_ -]?key|seed phrase)\b",
    re.IGNORECASE,
)


def _normalise_capture_text(text: str) -> str:
    return " ".join(str(text or "").split())


def _is_secretish(text: str) -> bool:
    return bool(_SECRETISH_RE.search(text or ""))


async def capture_note(text: str, category: str = "capture") -> Dict[str, Any]:
    clean_text = _normalise_capture_text(text)
    clean_category = _normalise_capture_text(category) or "capture"
    if not clean_text:
        return {
            "ok": False,
            "saved": False,
            "status": "empty",
            "error": "capture text is required",
        }
    if len(clean_text) > 2000:
        return {
            "ok": False,
            "saved": False,
            "status": "too_long",
            "error": "capture text must be 2000 characters or fewer",
        }
    if _is_secretish(clean_text):
        return {
            "ok": False,
            "saved": False,
            "status": "rejected_sensitive",
            "error": "capture looks credential-like; not saved",
        }

    try:
        from app.core.semantic_memory import add_semantic_memory

        saved = await add_semantic_memory(
            category=clean_category[:50],
            text=clean_text,
            importance=1.0,
        )
    except Exception as e:
        return {
            "ok": False,
            "saved": False,
            "status": "error",
            "error": f"{type(e).__name__}: {str(e)[:120]}",
        }

    return {
        "ok": True,
        "saved": bool(saved),
        "status": "saved" if saved else "duplicate_or_not_saved",
        "category": clean_category[:50],
    }
