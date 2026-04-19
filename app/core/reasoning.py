"""
Tony's Reasoning Engine.

The difference between answering and thinking.

Without this: Matthew asks → Tony generates text → done.
With this:    Matthew asks → Tony thinks through the problem →
              critiques his own thinking → then responds.

This is chain-of-thought reasoning with self-critique.
It makes Tony significantly better at:
- Complex problems that need multiple steps
- Decisions where the obvious answer is wrong
- Legal/financial questions where nuance matters
- Anything where getting it wrong has real consequences

Not used for every message — only when the question warrants it.
Quick questions get quick answers. Hard questions get real thought.
"""
import os
import re
import json
import httpx
from typing import Optional, Dict

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def _needs_deep_reasoning(message: str) -> bool:
    """Decide if this message warrants chain-of-thought reasoning."""
    msg = message.lower()

    # Questions that need careful thought
    deep_indicators = [
        "should i", "what should", "what would you", "advice",
        "help me decide", "what do you think", "is it worth",
        "how do i", "best way to", "what's the best",
        "legal", "court", "ccj", "fca", "complaint", "debt",
        "financial", "mortgage", "money", "invest",
        "plan", "strategy", "approach",
        "worried", "not sure", "confused", "don't know what",
        "georgina", "amelia", "margot",  # family matters
    ]

    # Quick questions that don't need deep reasoning
    quick_indicators = [
        "what time", "what's the weather", "remind me",
        "thanks", "ok", "good", "hi", "hello",
        "what is", "define", "who is",
    ]

    if any(q in msg for q in quick_indicators):
        return False

    return any(d in msg for d in deep_indicators) or len(message) > 100


async def reason_before_responding(
    message: str,
    system_context: str,
    history_summary: str = ""
) -> Optional[str]:
    """
    Tony thinks through a problem before answering.
    Returns reasoning context to prepend to the actual generation.
    """
    if not GEMINI_API_KEY:
        return None

    if not _needs_deep_reasoning(message):
        return None

    prompt = f"""You are Tony's reasoning engine. Before Tony responds to Matthew, think through this carefully.

Matthew's question/message: {message}

Context about Matthew:
{system_context[:1000]}

{f"Recent conversation: {history_summary[:500]}" if history_summary else ""}

Think through this step by step:
1. What is Matthew actually asking for? (not just the surface question)
2. What does Matthew probably already know or have tried?
3. What are the 2-3 most important things to address?
4. What's the risk of getting this wrong?
5. What would genuinely help Matthew here?

Then: Is there an obvious answer that is actually WRONG? What's the non-obvious insight?

Keep reasoning concise. This is internal thinking, not the response.
Format: brief numbered steps, no waffle."""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 512, "temperature": 0.1}
                }
            )
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[REASONING] Failed: {e}")

    return None


async def self_critique(
    message: str,
    draft_response: str
) -> Optional[str]:
    """
    Tony critiques his own draft response before sending.
    Only for high-stakes responses.
    Returns improved response or None if draft is fine.
    """
    if not GEMINI_API_KEY:
        return None

    # Only critique substantial responses to important questions
    if len(draft_response) < 100 or not _needs_deep_reasoning(message):
        return None

    prompt = f"""You are Tony's self-critique system. Tony drafted this response. Is it actually good?

Matthew asked: {message[:300]}
Tony's draft: {draft_response[:600]}

Check:
1. Did Tony actually answer what was asked?
2. Is anything factually wrong or misleading?
3. Is Tony being too vague where specifics are needed?
4. Did Tony miss something important?
5. Is the tone right — direct, warm, British?

If the draft is good → respond: GOOD
If it needs improvement → respond: IMPROVE: [the improved version]

Be ruthless. Tony should only send his best work."""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 800, "temperature": 0.1}
                }
            )
            if r.status_code == 200:
                result = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                if result.startswith("IMPROVE:"):
                    return result[8:].strip()
    except Exception as e:
        print(f"[REASONING] Self-critique failed: {e}")

    return None
