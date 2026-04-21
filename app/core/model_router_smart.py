"""
Smart Model Router — picks the right provider for each request.

Tony has 7 providers (gemini, claude, groq, mistral, openrouter, deepseek, xai).
Matthew currently has to pick one or use Council. Smart routing picks
automatically based on what the request looks like.

Classification signals:
  - Message length + complexity
  - Code-related keywords
  - Document uploaded (long context needed)
  - Time-sensitivity (greeting = fast)
  - Image present (vision-capable model needed)
  - Council-mode keywords (complex / consequential)

Optimises for:
  - Cost: use groq (near-free) for simple messages
  - Quality: use claude for reasoning-heavy
  - Speed: use flash models for urgent context
  - Reliability: fallback chains if a provider is rate-limited
"""
import re
from typing import Optional, Dict


# Provider characteristics (rough)
PROVIDER_META = {
    "groq":        {"cost_relative": 1, "speed": 10, "reasoning": 6, "max_tokens": 8000},
    "deepseek":    {"cost_relative": 2, "speed": 7,  "reasoning": 8, "max_tokens": 64000},
    "gemini":      {"cost_relative": 3, "speed": 8,  "reasoning": 8, "max_tokens": 1000000},
    "mistral":     {"cost_relative": 4, "speed": 7,  "reasoning": 7, "max_tokens": 32000},
    "openrouter":  {"cost_relative": 5, "speed": 6,  "reasoning": 8, "max_tokens": 128000},
    "openai":      {"cost_relative": 8, "speed": 6,  "reasoning": 9, "max_tokens": 128000},
    "claude":      {"cost_relative": 9, "speed": 5,  "reasoning": 10, "max_tokens": 200000},
    "xai":         {"cost_relative": 6, "speed": 6,  "reasoning": 8, "max_tokens": 128000},
}


def classify_request(
    message: str,
    has_image: bool = False,
    has_document: bool = False,
    document_length: int = 0,
) -> Dict:
    """Return a classification of what the request needs."""
    if not message:
        message = ""

    msg_lower = message.lower().strip()
    length = len(message.split())

    # Short casual messages
    is_greeting = length <= 5 and any(
        msg_lower.startswith(g) for g in
        ["hi", "hey", "hello", "morning", "alright", "yo"]
    )

    # Simple acknowledgements
    is_ack = msg_lower in ("ok", "thanks", "cheers", "ta", "yeah", "nope", "sound")

    # Code request
    is_code = bool(re.search(
        r"\b(code|function|bug|error|fix|python|kotlin|javascript|typescript|"
        r"rust|go lang|debug|api|endpoint|database|sql|stack trace)\b",
        msg_lower
    ))

    # Creative writing
    is_creative = bool(re.search(
        r"\b(write|draft|story|poem|caption|bio|creative|letter|email to)\b",
        msg_lower
    ))

    # Deep reasoning
    is_reasoning = bool(re.search(
        r"\b(analyse|analyze|explain why|reason through|compare|evaluate|"
        r"decide between|pros and cons|tradeoff|what should i)\b",
        msg_lower
    ))

    # Needs big context
    needs_big_context = has_document and document_length > 8000

    # Medical/emotional — better with reasoning
    is_sensitive = bool(re.search(
        r"\b(dad|mum|struggling|overwhelmed|cant cope|crying|hurt|scared)\b",
        msg_lower
    ))

    return {
        "is_greeting": is_greeting,
        "is_ack": is_ack,
        "is_code": is_code,
        "is_creative": is_creative,
        "is_reasoning": is_reasoning,
        "has_image": has_image,
        "has_document": has_document,
        "needs_big_context": needs_big_context,
        "is_sensitive": is_sensitive,
        "length": length,
    }


def choose_provider(
    message: str,
    preferred: Optional[str] = None,
    has_image: bool = False,
    has_document: bool = False,
    document_length: int = 0,
) -> Dict:
    """
    Pick the best provider for this request.
    Returns {provider, rationale, fallbacks}.
    """
    # If user explicitly picked one, respect that
    if preferred and preferred.lower() not in ("auto", "smart", ""):
        return {
            "provider": preferred,
            "rationale": "user-specified",
            "fallbacks": [],
        }

    classify = classify_request(
        message, has_image=has_image,
        has_document=has_document, document_length=document_length,
    )

    # Vision-capable models
    if has_image:
        return {
            "provider": "gemini",
            "rationale": "image present — Gemini for vision",
            "fallbacks": ["claude", "openai"],
        }

    # Long document
    if classify["needs_big_context"]:
        return {
            "provider": "gemini",
            "rationale": "long document — Gemini 1M context",
            "fallbacks": ["claude", "openrouter"],
        }

    # Simple greeting or acknowledgement → cheapest + fastest
    if classify["is_greeting"] or classify["is_ack"]:
        return {
            "provider": "groq",
            "rationale": "greeting/ack — use fastest provider",
            "fallbacks": ["gemini", "mistral"],
        }

    # Code → Claude (best reasoning)
    if classify["is_code"]:
        return {
            "provider": "claude",
            "rationale": "code request — Claude for reasoning quality",
            "fallbacks": ["deepseek", "gemini"],
        }

    # Sensitive topics → Claude (best at nuance)
    if classify["is_sensitive"]:
        return {
            "provider": "claude",
            "rationale": "sensitive topic — Claude for careful handling",
            "fallbacks": ["gemini"],
        }

    # Creative → Claude (better tone)
    if classify["is_creative"]:
        return {
            "provider": "claude",
            "rationale": "creative writing — Claude for voice",
            "fallbacks": ["gemini"],
        }

    # Deep reasoning → Council mode (multi-brain)
    if classify["is_reasoning"] and classify["length"] > 6:
        return {
            "provider": "council",
            "rationale": "complex reasoning — Council mode",
            "fallbacks": ["claude", "gemini"],
        }

    # Default: Gemini Flash — balanced cost/quality for medium queries
    return {
        "provider": "gemini",
        "rationale": "medium query — Gemini Flash balanced",
        "fallbacks": ["groq", "claude"],
    }


def explain_routing(message: str, has_image: bool = False,
                    has_document: bool = False) -> str:
    """Human-readable explanation of why a provider was chosen."""
    choice = choose_provider(
        message, has_image=has_image,
        has_document=has_document
    )
    return f"{choice['provider']}: {choice['rationale']}"
