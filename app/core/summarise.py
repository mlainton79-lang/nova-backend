"""
Small text summarisation helper for the /summarise compatibility endpoint.
"""
import os
import re
from typing import Optional


def _fallback_summary(text: str, max_sentences: int = 5) -> str:
    """Deterministic fallback when an LLM is unavailable."""
    clean = " ".join((text or "").split())
    if not clean:
        return ""

    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", clean)
        if s.strip()
    ]
    if not sentences:
        return clean[:800]
    return " ".join(sentences[:max(1, max_sentences)])[:1200]


async def summarise_text(
    text: str,
    instruction: Optional[str] = None,
    max_sentences: int = 5,
) -> dict:
    """Summarise user-provided text. Never raises for normal empty input."""
    source = text or ""
    stripped = source.strip()
    if not stripped:
        return {"ok": False, "error": "text is required", "summary": ""}

    max_sentences = min(max(int(max_sentences or 5), 1), 10)
    clipped = stripped[:12000]

    if not os.environ.get("GEMINI_API_KEY"):
        return {
            "ok": True,
            "summary": _fallback_summary(clipped, max_sentences=max_sentences),
            "model": "fallback",
            "input_chars": len(source),
            "truncated": len(stripped) > len(clipped),
        }

    prompt = f"""Summarise this for Matthew in British English.

Keep it practical and concise. Use no more than {max_sentences} short sentences.
Preserve names, dates, deadlines, amounts, and actions if present.
{("Extra instruction: " + instruction.strip()) if instruction else ""}

Text:
{clipped}
"""

    try:
        from app.core import gemini_client

        resp = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": 500, "temperature": 0.2},
            timeout=15.0,
            caller_context="summarise_endpoint",
        )
        summary = gemini_client.extract_text(resp).strip()
        if not summary:
            summary = _fallback_summary(clipped, max_sentences=max_sentences)
            model = "fallback"
        else:
            model = "gemini_flash"
        return {
            "ok": True,
            "summary": summary[:1600],
            "model": model,
            "input_chars": len(source),
            "truncated": len(stripped) > len(clipped),
        }
    except Exception:
        return {
            "ok": True,
            "summary": _fallback_summary(clipped, max_sentences=max_sentences),
            "model": "fallback",
            "input_chars": len(source),
            "truncated": len(stripped) > len(clipped),
        }
