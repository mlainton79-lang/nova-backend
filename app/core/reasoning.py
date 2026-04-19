"""
Tony's Reasoning Engine.

For complex questions, Tony thinks before answering.
This produces significantly better responses on hard problems.

Chain of thought process:
1. UNDERSTAND: What is Matthew actually asking? What's the real question?
2. CONTEXT: What do I know that's relevant?
3. ANALYSE: What are the key factors?
4. CONSIDER: What are the different approaches?
5. DECIDE: What's the best answer given Matthew's situation?
6. RESPOND: Clear, direct, actionable

Used for:
- Legal questions (Western Circle, FOS, CCJ)
- Financial decisions
- Technical decisions about Nova
- Life decisions Matthew is thinking through
- Complex planning

NOT used for:
- Simple factual questions
- Casual conversation
- Quick lookups
"""
import os
from typing import Optional
from app.core.model_router import gemini, gemini_json

COMPLEX_TRIGGERS = [
    "should i", "what should", "help me decide", "what do you think",
    "is it worth", "would you recommend", "what's the best",
    "how should i", "advice", "what would happen", "if i",
    "legal", "fos", "ccj", "court", "western circle", "complaint",
    "financial", "money", "debt", "afford", "invest", "buy", "sell",
    "nova", "build", "architecture", "design", "approach",
    "worried", "not sure", "confused", "don't know what"
]


def needs_deep_reasoning(message: str) -> bool:
    """Determine if this message needs chain-of-thought reasoning."""
    msg_lower = message.lower()
    return any(trigger in msg_lower for trigger in COMPLEX_TRIGGERS)


async def reason_through(message: str, context: str = "") -> Optional[str]:
    """
    Tony thinks through a complex question before answering.
    Returns the reasoning chain to prepend to the response context.
    """
    prompt = f"""You are Tony's internal reasoning system. Think through this question carefully before answering.

Matthew asked: {message}

Context available:
{context[:800]}

Think through this step by step:
1. What is Matthew really asking? (not just the surface question)
2. What context is most relevant here?
3. What are the key considerations?
4. What options does Matthew have?
5. Given his specific situation, what is the best path?

Be specific to Matthew's situation. Reference his actual circumstances.
Think like someone who genuinely knows him and cares about the outcome.

Reasoning (internal — not shown to Matthew):"""

    return await gemini(prompt, task="reasoning", max_tokens=600, temperature=0.2)


async def emotional_check(message: str) -> Optional[str]:
    """
    Detect emotional subtext in what Matthew says.
    Tony responds to how Matthew is feeling, not just what he asks.
    """
    stress_signals = [
        "tired", "exhausted", "can't sleep", "stressed", "worried",
        "don't know", "struggling", "overwhelmed", "hate", "fed up",
        "can't cope", "sick of", "awful", "terrible", "nightmare"
    ]
    
    msg_lower = message.lower()
    has_stress = any(s in msg_lower for s in stress_signals)
    
    if not has_stress:
        return None
    
    prompt = f"""Matthew said: "{message}"

He seems to be under emotional stress. In one sentence, what is he really feeling?
What should Tony acknowledge before answering the practical question?

Keep it to one sentence. Just what Tony should notice."""

    return await gemini(prompt, task="analysis", max_tokens=80, temperature=0.3)
