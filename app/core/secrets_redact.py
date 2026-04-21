import re

_PATTERNS = [
    # Google API keys (start with AIza, 39 chars total)
    (re.compile(r"AIza[A-Za-z0-9_\-]{35}"), "AIza***REDACTED***"),
    # Anthropic keys (check before generic sk- to preserve prefix)
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "sk-ant-***REDACTED***"),
    # OpenAI keys (covers both legacy sk-... and sk-proj-...)
    (re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}"), "sk-***REDACTED***"),
    # Generic Google-style URL query "?key=" / "&key="
    (re.compile(r"([?&]key=)[^&\s'\"]+"), r"\1***REDACTED***"),
]


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out
