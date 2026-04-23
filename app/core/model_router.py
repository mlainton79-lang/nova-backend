"""
Tony's Model Router.

Uses the best model for each task:
- gemini-2.5-pro: deep reasoning, complex analysis, legal/financial, council synthesis
- gemini-2.5-flash: fast tasks, emotional intelligence, quick lookups, transcription
- claude-sonnet-4-6: council chair, final synthesis, personality-heavy responses

Never use Flash when Pro would give a meaningfully better answer.
Never use Pro when Flash is fast enough and accurate enough.
"""
import os
import re
import json
import logging
from typing import Optional

from app.core import gemini_client

log = logging.getLogger(__name__)

# Sentinel tier values used by choose_model() for task classification.
# The actual model strings sent to Gemini live in app/core/gemini_client.py
# (env: GEMINI_PRO_PRIMARY / GEMINI_PRO_FALLBACK / GEMINI_FLASH_MODEL).
GEMINI_PRO = "pro"
GEMINI_FLASH = "flash"


def choose_model(task: str) -> str:
    """Choose the right Gemini tier for a given task type."""
    pro_tasks = {
        "reasoning", "legal", "financial", "planning", "strategy",
        "analysis", "synthesis", "world_model", "learning_synthesis",
        "document_generation", "agent", "goal_planning", "research"
    }
    flash_tasks = {
        "emotional_intelligence", "transcription", "embedding",
        "news", "weather", "quick_lookup", "notification",
        "deduplication", "classification"
    }

    task_lower = task.lower()
    for t in pro_tasks:
        if t in task_lower:
            return GEMINI_PRO
    return GEMINI_FLASH


async def gemini(
    prompt: str,
    task: str = "general",
    max_tokens: int = 2048,
    temperature: float = 0.2,
    system: str = None,
) -> Optional[str]:
    """
    Unified Gemini call with automatic tier selection.
    Use this everywhere instead of raw httpx calls to Gemini.

    Returns the generated text on success, None on any failure —
    preserving the None-on-failure contract that ~34 downstream files
    depend on. Actual fallback logic (pro-primary → pro-stable) lives
    in gemini_client.generate_content.
    """
    tier = choose_model(task)  # "pro" or "flash"

    # Pro-tier reasoning calls get Google Search grounding. Flash-tier
    # tasks (emotional classification, dedup, quick lookups) don't
    # benefit from fresh external facts and skip grounding.
    tools = [{"google_search": {}}] if tier == "pro" else None

    try:
        response = await gemini_client.generate_content(
            tier=tier,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            system_instruction=system,
            tools=tools,
            generation_config={
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
            timeout=30.0,
            caller_context=f"model_router.{task}",
        )
        text = gemini_client.extract_text(response)
        return text or None
    except gemini_client.GeminiClientError as e:
        log.warning("[MODEL_ROUTER] %s tier exhausted for task=%s: %s", tier, task, e)
        return None
    except Exception as e:
        log.warning(
            "[MODEL_ROUTER] %s unexpected failure for task=%s: %s: %s",
            tier, task, type(e).__name__, e,
        )
        return None


async def gemini_json(
    prompt: str,
    task: str = "general",
    max_tokens: int = 2048,
    temperature: float = 0.1
) -> Optional[dict]:
    """Gemini call expecting JSON response. Parses and returns dict."""
    result = await gemini(prompt, task=task, max_tokens=max_tokens, temperature=temperature)
    if not result:
        return None
    try:
        cleaned = re.sub(r'```json|```', '', result).strip()
        return json.loads(cleaned)
    except Exception:
        # Try to extract JSON from response
        match = re.search(r'\{.*\}', result, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return None
