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
    disable_thinking: bool = False,
) -> Optional[str]:
    """
    Unified Gemini call with automatic tier selection.
    Use this everywhere instead of raw httpx calls to Gemini.

    Returns the generated text on success, None on any failure —
    preserving the None-on-failure contract that ~34 downstream files
    depend on. Actual fallback logic (pro-primary → pro-stable) lives
    in gemini_client.generate_content.

    disable_thinking=True is for trivially-shaped responses (one number,
    one phrase, a yes/no, an enum) where Gemini 2.5's thinking-mode
    overhead (250-500 tokens of internal reasoning, billed against
    maxOutputTokens) is pure waste. Forces tier='flash' because pro
    rejects `thinkingBudget: 0` with HTTP 400 "This model only works in
    thinking mode." — flash-tier is the only one that accepts the
    no-think contract. Callers asking for non-trivial reasoning should
    leave this False even on cheap tasks.
    """
    if disable_thinking:
        tier = "flash"
    else:
        tier = choose_model(task)  # "pro" or "flash"

    # Pro-tier reasoning calls get Google Search grounding. Flash-tier
    # tasks (emotional classification, dedup, quick lookups) don't
    # benefit from fresh external facts and skip grounding.
    tools = [{"google_search": {}}] if tier == "pro" else None

    generation_config: dict = {
        "maxOutputTokens": max_tokens,
        "temperature": temperature,
    }
    if disable_thinking:
        generation_config["thinkingConfig"] = {"thinkingBudget": 0}

    try:
        response = await gemini_client.generate_content(
            tier=tier,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            system_instruction=system,
            tools=tools,
            generation_config=generation_config,
            timeout=30.0,
            caller_context=f"model_router.{task}",
        )
        text = gemini_client.extract_text(response)

        # MAX_TOKENS visibility hook. Silent truncation has been masking real
        # bugs in tasks that expect full JSON responses (gemini_json then
        # returns None, callers use `or {}`, and the empty result looks like
        # an empty model opinion rather than a truncated one). Gemini 2.5
        # thinking-mode reasons internally BEFORE emitting output, and that
        # reasoning is billed against the same maxOutputTokens budget — so
        # under-sized budgets get all reasoning, no output. Recording an
        # event surfaces it for /debug/recent-events without instrumenting
        # every individual caller. Best-effort: must never raise.
        try:
            candidates = response.get("candidates", []) if isinstance(response, dict) else []
            finish_reason = candidates[0].get("finishReason") if candidates else None
            if finish_reason == "MAX_TOKENS":
                usage = response.get("usageMetadata", {}) if isinstance(response, dict) else {}
                log.warning(
                    "[MODEL_ROUTER] task=%s tier=%s truncated at MAX_TOKENS "
                    "(budget=%d, thoughts=%s, output=%s, text_chars=%d)",
                    task, tier, max_tokens,
                    usage.get("thoughtsTokenCount"),
                    usage.get("candidatesTokenCount"),
                    len(text or ""),
                )
                try:
                    from app.observability import record_run_event, EventSeverity
                    record_run_event(
                        event_type="gemini_max_tokens_truncation",
                        severity=EventSeverity.WARNING,
                        subsystem="model_router.truncation",
                        message=f"Gemini response truncated at MAX_TOKENS for task={task}",
                        metadata={
                            "task": task,
                            "tier": tier,
                            "max_tokens_budget": max_tokens,
                            "thoughts_tokens": usage.get("thoughtsTokenCount"),
                            "output_tokens": usage.get("candidatesTokenCount"),
                            "total_tokens": usage.get("totalTokenCount"),
                            "output_text_chars": len(text or ""),
                        },
                    )
                except Exception:
                    pass
        except Exception:
            pass

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
    temperature: float = 0.1,
    disable_thinking: bool = False,
) -> Optional[dict]:
    """Gemini call expecting JSON response. Parses and returns dict.

    disable_thinking=True is passed through to gemini() — use for
    trivially-shaped JSON outputs (one decimal, one short dict, an
    enum) where thinking-mode overhead is pure waste. Defaults to
    False to preserve existing caller behaviour.
    """
    result = await gemini(
        prompt,
        task=task,
        max_tokens=max_tokens,
        temperature=temperature,
        disable_thinking=disable_thinking,
    )
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
