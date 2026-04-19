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
import httpx
import re
import json
from typing import Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Models
GEMINI_PRO = "gemini-2.5-pro"
GEMINI_FLASH = "gemini-2.5-flash"


def choose_model(task: str) -> str:
    """Choose the right Gemini model for a given task type."""
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
    model: str = None,
    max_tokens: int = 2048,
    temperature: float = 0.2,
    system: str = None
) -> Optional[str]:
    """
    Unified Gemini call with automatic model selection.
    Use this everywhere instead of raw httpx calls to Gemini.
    """
    if not GEMINI_API_KEY:
        return None

    selected_model = model or choose_model(task)

    contents = []
    if system:
        contents.append({"role": "user", "parts": [{"text": f"[SYSTEM]: {system}"}]})
        contents.append({"role": "model", "parts": [{"text": "Understood."}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": contents,
                    "generationConfig": {
                        "maxOutputTokens": max_tokens,
                        "temperature": temperature
                    }
                }
            )
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            else:
                # Fall back to Flash if Pro fails
                if selected_model == GEMINI_PRO:
                    r2 = await client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_FLASH}:generateContent?key={GEMINI_API_KEY}",
                        json={
                            "contents": contents,
                            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature}
                        }
                    )
                    if r2.status_code == 200:
                        return r2.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[MODEL_ROUTER] {selected_model} failed: {e}")

    return None


async def gemini_json(
    prompt: str,
    task: str = "general",
    model: str = None,
    max_tokens: int = 2048,
    temperature: float = 0.1
) -> Optional[dict]:
    """Gemini call expecting JSON response. Parses and returns dict."""
    result = await gemini(prompt, task=task, model=model, max_tokens=max_tokens, temperature=temperature)
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
