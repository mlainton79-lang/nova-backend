"""
Transcript formatter — Option 1C "client as source of truth".

Takes a chat-session JSON posted by the Android client (same shape as
ChatHistoryStore.StoredChat on the Kotlin side) and renders a
human-readable Markdown transcript. No DB access, no LLM calls, no
network. Pure formatting + secret scrubbing.

Two known content gaps under Option 1C that this formatter handles
defensively:
  - Council per-skipped-brain error strings: Android doesn't capture
    them today, so skipped brains get a placeholder. Future-proof: if
    a turn's debugData ever includes a `failures` object, the real
    error strings are used automatically.
  - Dynamic system prompt + memory context per turn: Android doesn't
    store these at all. The transcript is silent on them.

Secret scrubbing: defence in depth. Runs on input (before any field
is formatted) AND output (the emitted Markdown string), so even if
the formatter itself ever interpolated something leaky, the final
response is re-scrubbed.
"""
import json
import re
from datetime import datetime
from typing import Any, List

from app.core.secrets_redact import redact

# Graceful dateutil handling. If the package is installed (transitively
# via some other dep), we use it as an extra locale-variant fallback.
# If not installed, the module still imports and the fallback chain
# just skips that layer. python-dateutil is NOT currently in
# requirements.txt — flag for explicit addition if you want the layer
# actually active in production.
try:
    from dateutil import parser as _dateutil_parser  # type: ignore
except ImportError:
    _dateutil_parser = None


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

# Brains the Council loop may attempt. Used for "skipped" detection:
# any brain in this set that is not in round1 or round2 of a given
# Council turn is rendered as SKIPPED.
BRAIN_UNIVERSE = {
    "claude", "grok", "openai", "deepseek", "openrouter",
    "gemini", "groq", "mistral",
}

# Cosmetic display names for the Markdown bullets.
BRAIN_DISPLAY = {
    "claude":     "Claude",
    "deepseek":   "DeepSeek",
    "gemini":     "Gemini",
    "grok":       "Grok",
    "groq":       "Groq",
    "mistral":    "Mistral",
    "openai":     "OpenAI",
    "openrouter": "OpenRouter",
}

# Env var names whose values should be redacted if they appear anywhere
# in the incoming payload or the final Markdown output.
_SCRUB_ENV_NAMES = [
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "GROQ_API_KEY",      "MISTRAL_API_KEY", "XAI_API_KEY",
    "DEEPSEEK_API_KEY",  "OPENROUTER_API_KEY",
    "DATABASE_URL",      "GITHUB_TOKEN",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
    "DEV_TOKEN",
]

# Pattern: one of the named env vars followed by = or :, then a quoted
# or bare value. Captures only the value — the name is preserved so the
# scrub is visible rather than opaque.
_ENV_VALUE_PATTERN = re.compile(
    r"(" + "|".join(re.escape(n) for n in _SCRUB_ENV_NAMES) + r")\s*[:=]\s*"
    r"(?:\"([^\"]+)\"|'([^']+)'|([^\s,}'\"]+))"
)

# Generic Bearer-token pattern. Matches `Bearer <token>` where the
# token is 20+ URL-safe-ish chars. Safer than trying to enumerate
# every vendor's token shape.
_BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}")


# ──────────────────────────────────────────────────────────────────────
# Scrubber (three-layer defence)
# ──────────────────────────────────────────────────────────────────────

def _scrub_string(s: str) -> str:
    """Three layers:
      1. app.core.secrets_redact.redact() — AIza / sk-ant / sk- / ?key= patterns
      2. NAME=value / NAME:value for our known env var names
      3. Bearer <token>
    """
    if not s:
        return s
    out = redact(s)
    out = _ENV_VALUE_PATTERN.sub(lambda m: f"{m.group(1)}=[REDACTED]", out)
    out = _BEARER_PATTERN.sub("Bearer [REDACTED]", out)
    return out


def _scrub_deep(obj: Any) -> Any:
    """Recursively scrub every string in a nested dict/list structure."""
    if isinstance(obj, str):
        return _scrub_string(obj)
    if isinstance(obj, dict):
        return {k: _scrub_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_deep(x) for x in obj]
    return obj


# ──────────────────────────────────────────────────────────────────────
# Date parsing
# ──────────────────────────────────────────────────────────────────────

def _parse_time_to_hhmm(s: str) -> str:
    """Extract HH:MM from Android's stored timestamp.

      Primary:    strptime '%d %b %Y, %H:%M'  (e.g. '23 Apr 2026, 22:15')
      Fallback 1: dateutil.parser.parse (if installed)
      Fallback 2: return the original string verbatim
    """
    if not s:
        return "unknown"
    try:
        return datetime.strptime(s, "%d %b %Y, %H:%M").strftime("%H:%M")
    except ValueError:
        pass
    if _dateutil_parser is not None:
        try:
            return _dateutil_parser.parse(s).strftime("%H:%M")
        except (ValueError, TypeError, OverflowError):
            pass
    return s


# ──────────────────────────────────────────────────────────────────────
# Per-turn rendering
# ──────────────────────────────────────────────────────────────────────

def _is_council_message(msg: dict) -> bool:
    """True if this tony-message is a Council deliberation output."""
    if msg.get("role") != "tony":
        return False
    if (msg.get("provider") or "").strip().lower() == "council":
        return True
    # Safety net: if debugData decodes to something with a decidingBrain,
    # treat as Council regardless of provider label.
    dd = msg.get("debugData") or ""
    if dd:
        try:
            parsed = json.loads(dd)
            if isinstance(parsed, dict) and "decidingBrain" in parsed:
                return True
        except json.JSONDecodeError:
            pass
    return False


def _render_user_block(msg: dict) -> List[str]:
    t = _parse_time_to_hhmm(msg.get("createdAt") or "")
    return [
        f"**[User, {t}]**",
        msg.get("text") or "",
        "",
    ]


def _render_simple_tony_block(msg: dict) -> List[str]:
    t = _parse_time_to_hhmm(msg.get("createdAt") or "")
    provider = (msg.get("provider") or "").strip()
    header = f"**[Tony via {provider}, {t}]**" if provider else f"**[Tony, {t}]**"
    return [
        header,
        msg.get("text") or "",
        "",
    ]


def _render_council_block(msg: dict) -> List[str]:
    """Render the full Council deliberation + synthesis."""
    dd_raw = msg.get("debugData") or ""
    lines: List[str] = []

    try:
        debug = json.loads(dd_raw) if dd_raw else {}
        if not isinstance(debug, dict):
            debug = {}
    except json.JSONDecodeError:
        # Can't parse the debug JSON: render synthesis alone with a note.
        lines.append("**[Council deliberation]**")
        lines.append("[debug data could not be parsed]")
        lines.append("")
        t = _parse_time_to_hhmm(msg.get("createdAt") or "")
        lines.append(f"**[Synthesis by Tony, {t}]**")
        lines.append(msg.get("text") or "")
        lines.append("")
        return lines

    deciding = (debug.get("decidingBrain") or "").lower().strip()
    round1 = debug.get("round1") or {}
    round2 = debug.get("round2") or {}
    challenge = debug.get("challenge") or ""
    # Future-proof: real failures dict if Android ever persists it.
    failures = debug.get("failures") or {}
    if not isinstance(round1, dict):
        round1 = {}
    if not isinstance(round2, dict):
        round2 = {}
    if not isinstance(failures, dict):
        failures = {}

    lines.append("**[Council deliberation]**")

    # Round 1 + skipped brains appended underneath
    if round1:
        lines.append("*Round 1:*")
        for name, output in round1.items():
            key = (name or "").lower()
            display = BRAIN_DISPLAY.get(key, f"Unknown brain ({name})")
            if key and key == deciding:
                display = f"{display} (chair)"
            lines.append(f"- {display}: {output}")

        appeared = {k.lower() for k in round1.keys()} | {k.lower() for k in round2.keys()}
        for brain in sorted(BRAIN_UNIVERSE - appeared):
            display = BRAIN_DISPLAY.get(brain, brain)
            err = failures.get(brain) or failures.get(brain.upper()) or ""
            if err:
                lines.append(f"- {display}: SKIPPED — {err}")
            else:
                lines.append(
                    f"- {display}: SKIPPED — "
                    "(error details not captured by client at turn time)"
                )
        lines.append("")

    # Chair's critique between rounds
    if challenge:
        lines.append("*Chair's challenge:*")
        lines.append(challenge)
        lines.append("")

    # Round 2 (refinement)
    if round2:
        lines.append("*Round 2 (refinement):*")
        for name, output in round2.items():
            key = (name or "").lower()
            display = BRAIN_DISPLAY.get(key, f"Unknown brain ({name})")
            lines.append(f"- {display}: {output}")
        lines.append("")

    # Final synthesis
    t = _parse_time_to_hhmm(msg.get("createdAt") or "")
    chair_display = BRAIN_DISPLAY.get(deciding) or (deciding.title() if deciding else "Tony")
    lines.append(f"**[Synthesis by {chair_display}, {t}]**")
    lines.append(msg.get("text") or "")
    lines.append("")
    return lines


# ──────────────────────────────────────────────────────────────────────
# Top-level
# ──────────────────────────────────────────────────────────────────────

def format_chat_transcript(chat: dict) -> str:
    """Render a StoredChat-shaped dict as a Markdown transcript.

    Invariants:
      - Scrubs secrets on input AND output.
      - Never raises — always produces a valid Markdown string.
      - Empty / missing fields render a best-effort placeholder.
    """
    try:
        chat = _scrub_deep(chat) if isinstance(chat, dict) else {}
    except Exception:
        # Scrubbing itself should never fail, but if it does we'd rather
        # ship a slightly-less-scrubbed transcript than crash the endpoint.
        if not isinstance(chat, dict):
            chat = {}

    title = chat.get("title") or chat.get("id") or "Untitled"
    exported = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    messages = chat.get("messages")
    if not isinstance(messages, list):
        messages = []

    header = [
        f"# Chat transcript — {title}",
        f"# Exported: {exported}",
        "",
    ]

    if not messages:
        header.append("(no turns)")
        return _scrub_string("\n".join(header) + "\n")

    body: List[str] = []
    turn_num = 0
    i = 0
    n = len(messages)

    while i < n:
        msg = messages[i]
        if not isinstance(msg, dict):
            i += 1
            continue
        role = (msg.get("role") or "").lower()

        if role == "user":
            turn_num += 1
            # Look one ahead for the paired tony reply.
            next_tony = None
            if i + 1 < n:
                nxt = messages[i + 1]
                if isinstance(nxt, dict) and (nxt.get("role") or "").lower() == "tony":
                    next_tony = nxt
            is_council = bool(next_tony and _is_council_message(next_tony))

            body.append(f"## Turn {turn_num} — Council" if is_council else f"## Turn {turn_num}")
            body.extend(_render_user_block(msg))

            if next_tony is None:
                body.append("*(no tony reply recorded)*")
                body.append("")
                i += 1
            else:
                if is_council:
                    body.extend(_render_council_block(next_tony))
                else:
                    body.extend(_render_simple_tony_block(next_tony))
                i += 2

        elif role == "tony":
            # Orphan tony message (no preceding user) — rare but possible.
            turn_num += 1
            is_council = _is_council_message(msg)
            body.append(f"## Turn {turn_num} — Council" if is_council else f"## Turn {turn_num}")
            body.append("*(no user message recorded)*")
            body.append("")
            if is_council:
                body.extend(_render_council_block(msg))
            else:
                body.extend(_render_simple_tony_block(msg))
            i += 1

        else:
            # Unknown role — skip gracefully.
            i += 1

    full = "\n".join(header + body).rstrip() + "\n"
    return _scrub_string(full)
