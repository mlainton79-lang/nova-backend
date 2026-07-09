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
import os
from typing import Optional, Dict, Iterable


# Providers excluded from auto-routing. Configure in Railway with either
# DISABLED_AI_PROVIDERS or SKIP_PROVIDERS, comma/space separated, e.g.
# DISABLED_AI_PROVIDERS=gemini.
#
# History: {"claude"} from 2026-04-21 (Anthropic account out of credits;
# every /v1/messages call returned HTTP 400 "credit balance is too low")
# until 2026-06-10, when credits were restored and Claude was verified
# working as Tony's voice provider. Note the skip only ever affected
# auto/smart routing — manual brain-picker selection builds its chain
# directly from the picked provider and bypasses this module.
#
def _parse_provider_list(value: str) -> set[str]:
    providers = set()
    for item in re.split(r"[\s,]+", value or ""):
        item = item.strip().lower()
        if item:
            providers.add(item)
    return providers


SKIP_PROVIDERS = (
    _parse_provider_list(os.environ.get("DISABLED_AI_PROVIDERS", ""))
    | _parse_provider_list(os.environ.get("SKIP_PROVIDERS", ""))
)


def is_provider_skipped(provider: Optional[str]) -> bool:
    return (provider or "").lower() in SKIP_PROVIDERS


def first_available_provider(candidates: Iterable[str]) -> Optional[str]:
    for provider in candidates:
        if provider and not is_provider_skipped(provider):
            return provider
    return None


def _apply_skip(choice: Dict) -> Dict:
    """If the primary provider is in SKIP_PROVIDERS, promote the first
    non-skipped fallback. Always prunes skipped providers from the
    fallbacks list so the caller never silently retries a dead one.
    Last-resort defaults to Gemini if every option is skipped."""
    primary = choice.get("provider", "").lower()
    raw_fallbacks = [f for f in choice.get("fallbacks", []) if isinstance(f, str)]
    pruned_fallbacks = [f for f in raw_fallbacks if f.lower() not in SKIP_PROVIDERS]

    if primary not in SKIP_PROVIDERS:
        choice["fallbacks"] = pruned_fallbacks
        return choice

    if pruned_fallbacks:
        replacement = pruned_fallbacks[0]
        rest = pruned_fallbacks[1:]
        return {
            "provider": replacement,
            "rationale": (
                f"{choice.get('rationale', '')} — "
                f"{primary} skipped (SKIP_PROVIDERS); promoted {replacement}"
            ),
            "fallbacks": rest,
        }

    replacement = first_available_provider(
        ["claude", "openai", "groq", "mistral", "openrouter", "deepseek", "xai"]
    )
    if replacement:
        return {
            "provider": replacement,
            "rationale": (
                f"{choice.get('rationale', '')} — "
                f"{primary} skipped and no configured fallbacks available; "
                f"defaulted to {replacement}"
            ),
            "fallbacks": [],
        }

    return {
        "provider": primary,
        "rationale": (
            f"{choice.get('rationale', '')} — "
            f"{primary} skipped but every fallback provider is also skipped"
        ),
        "fallbacks": [],
    }


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

    is_trivial = (
        length <= 3
        and not has_image
        and not has_document
        and not is_code
        and not is_creative
        and not is_reasoning
        and not is_sensitive
    )

    return {
        "is_greeting": is_greeting,
        "is_ack": is_ack,
        "is_trivial": is_trivial,
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
    is_streaming: bool = False,
) -> Dict:
    """
    Pick the best provider for this request, honouring SKIP_PROVIDERS
    so temporarily-unavailable providers (e.g. Claude when out of
    credits) get transparently replaced by the first usable fallback.
    Returns {provider, rationale, fallbacks}.

    is_streaming=True is set by callers that consume the result via the
    SSE streaming dispatcher (chat_stream._get_stream). Council mode is
    a 4-round non-streaming deliberation that doesn't fit SSE, so the
    streaming branch routes around it. P1.3 from the 2026-05-28 audit
    closes the "fake streaming Council" gap where the SSE wire used to
    label Gemini single-provider responses as Council.
    """
    raw = _choose_provider_raw(
        message,
        preferred=preferred,
        has_image=has_image,
        has_document=has_document,
        document_length=document_length,
        is_streaming=is_streaming,
    )
    return _apply_skip(raw)


def _choose_provider_raw(
    message: str,
    preferred: Optional[str] = None,
    has_image: bool = False,
    has_document: bool = False,
    document_length: int = 0,
    is_streaming: bool = False,
) -> Dict:
    """Routing logic before SKIP_PROVIDERS is applied. Kept as a
    separate function so the skip layer is easy to reason about and
    remove later."""
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

    # Simple greeting / acknowledgement / trivial ping → cheapest + fastest
    if classify["is_greeting"] or classify["is_ack"] or classify["is_trivial"]:
        return {
            "provider": "groq",
            "rationale": "trivial message — use fastest provider",
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
        if is_streaming:
            # Council's 4-round deliberation can't be SSE-streamed coherently.
            # In streaming context, fall back to Claude (best reasoning) +
            # configured fallbacks so the wire label matches the actual provider.
            return {
                "provider": "claude",
                "rationale": "complex reasoning (streaming) — Council not supported on SSE, using Claude",
                "fallbacks": ["gemini"],
            }
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
