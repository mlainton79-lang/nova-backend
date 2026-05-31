"""
retrieval_guard.py — anti-fabrication structural guard for retrieval intents.

Layer 2 of the Bug 2 fabrication-guard fix (commit pair started at 7081453;
Layer 1 is prompt-side in tony.py + providers/council.py). When a chat
message asks about live-retrieved data (Gmail, cases, web search) but the
corresponding context block came back empty (fetch timeout, integration
failure, keyword miss), this guard short-circuits the deliberation pipeline
with a deterministic refusal — preventing fabricating providers (Mistral
and OpenRouter especially per project_council_fabrication.md) from inventing
plausible fake data before the chair ever sees it.

Used by both `/council` and `/chat/stream` endpoints after their respective
`_gather_*_context` step + system-prompt context-append loop.

Behaviour:
- check_retrieval_guard(message, ctx) returns None if no short-circuit is
  needed (no intent match, intent matched but ctx populated, or kill-switch
  disabled).
- Returns dict {deterministic_reply, intent_key, label, ctx_keys_present}
  when the message matches a retrieval intent AND ctx[intent_key] is empty.
- Honors the RETRIEVAL_FABRICATION_GUARD_ENABLED env var (default true).
  Setting to "false"/"0"/"no"/"off" disables — clean production rollback
  without code revert.

Codex review 2026-05-31 calibration:
- Bare `\\bcase\\b` REMOVED — would false-positive on "phone case", "in case",
  "case-sensitive", "what's the case for", etc. Case patterns now require
  document/legal framing.
- Gmail patterns require retrieval framing ("what's in", "last N", "from",
  "any/new/unread") — must NOT match action-shaped phrasing like "draft an
  email to X" or "remind me to email Y".
- Per-intent refusal text names the integration AND gives a concrete next
  step, so users aren't left guessing what to type next.
"""
import os
import re
from typing import Dict, List, Optional, Tuple


# (regex, ctx_key the context-gather would have populated, user-facing label)
_RETRIEVAL_INTENTS: List[Tuple[re.Pattern, str, str]] = [
    (
        re.compile(
            r"what'?s?\s+in\s+(my\s+)?(inbox|gmail)"
            r"|((my|the)\s+)?inbox\b"
            r"|last\s+\d+\s+emails?\b"
            r"|emails?\s+from\b"
            r"|(any|new|unread)\s+emails?\b"
            r"|emails?\s+about\b"
            r"|read\s+(my\s+)?(emails?|inbox|gmail)"
            r"|scan\s+(my\s+)?(emails?|inbox|gmail)"
            r"|(my\s+)?gmail\s+(today|this\s+week|unread)",
            re.IGNORECASE,
        ),
        "gmail",
        "Gmail inbox",
    ),
    (
        re.compile(
            r"case\s+(documents?|files?|notes?|history|timeline|evidence)"
            r"|((my|the)\s+)?(legal|court|complaint|claim)\s+(documents?|papers?|letters?|notes?|file)"
            r"|search\s+(my\s+)?case\b",
            re.IGNORECASE,
        ),
        "case",
        "case documents",
    ),
    (
        re.compile(
            r"web\s+search"
            r"|search\s+(the\s+)?(web|internet|google)"
            r"|google\s+(this|that|for)\b"
            r"|look\s+(this|that)\s+up\s+(online|on\s+the\s+web)",
            re.IGNORECASE,
        ),
        "web",
        "web search results",
    ),
]


def _is_enabled() -> bool:
    """Read the RETRIEVAL_FABRICATION_GUARD_ENABLED kill switch. Default true.

    Setting this env var to false/0/no/off in Railway disables the guard
    without requiring a code revert — useful if a false-positive surfaces
    in production and we need to roll back to letting Council answer.
    """
    v = os.environ.get("RETRIEVAL_FABRICATION_GUARD_ENABLED", "true").strip().lower()
    return v not in ("false", "0", "no", "off")


def _refusal_for(intent_key: str, label: str) -> str:
    """Per-intent deterministic refusal text. Each names the integration
    and gives a concrete worked example of what to type next, so the user
    isn't left guessing how to phrase a query that WILL fetch data."""
    if intent_key == "gmail":
        return (
            "I can't see your Gmail inbox in this context right now. The fetch "
            "may have timed out or the message may not have triggered it. Try "
            "again with a sender, keyword, or account, for example: "
            "'search Gmail for Barclays' or 'emails from Pharmacy2U this week'."
        )
    if intent_key == "case":
        return (
            "I can't see your case documents in this context right now. Tell "
            "me which case (Western Circle, CQC, etc.) and a specific term to "
            "search for, e.g. 'Western Circle: anything about the CCJ'."
        )
    if intent_key == "web":
        return (
            "I haven't run a web search for this question. Ask me to search "
            "explicitly, e.g. 'search the web for X'."
        )
    return f"I can't see your {label} in this context right now."


def check_retrieval_guard(message: str, ctx: Dict) -> Optional[Dict]:
    """Decide whether the message must short-circuit to a deterministic refusal.

    Args:
        message: the raw user message (req.message / request.message).
        ctx: the gathered-context dict (output of _gather_council_context for
             /council, or _gather_context for /chat/stream). Keys we care
             about: 'gmail', 'case', 'web'. Falsy values (empty string, None,
             [], etc.) combined with a matching intent regex trigger the
             short-circuit.

    Returns:
        None if no short-circuit is needed.
        Dict with keys:
          - deterministic_reply: ready-to-send refusal text (str)
          - intent_key: 'gmail' / 'case' / 'web'
          - label: user-facing data label (e.g. 'Gmail inbox')
          - ctx_keys_present: list of ctx keys that ARE populated (diagnostic)
        when the guard fires.
    """
    if not _is_enabled():
        return None
    if not message:
        return None
    ctx = ctx or {}
    for pattern, key, label in _RETRIEVAL_INTENTS:
        if not pattern.search(message):
            continue
        if ctx.get(key):
            # Block IS populated — Council/chat path will use it. No guard.
            return None
        # Intent matched + context block empty → fabrication risk. Refuse.
        return {
            "deterministic_reply": _refusal_for(key, label),
            "intent_key": key,
            "label": label,
            "ctx_keys_present": [k for k, v in ctx.items() if v],
        }
    return None
