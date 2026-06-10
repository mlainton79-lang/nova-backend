"""
Conversation history management.
Handles format conversion and smart context window truncation.
"""
from typing import List


MAX_HISTORY_CHARS = 40000  # ~10k tokens — generous but bounded


def _truncate_history(messages: list) -> list:
    """
    Smart truncation: keep the most recent messages that fit within budget.
    Always keeps at least the last 4 exchanges regardless of length.
    """
    if not messages:
        return messages

    # Always keep last 8 messages minimum
    if len(messages) <= 8:
        return messages

    # Count chars from most recent backwards
    total = 0
    cutoff = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        content = msg.get("content", "") or ""
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        total += len(str(content))
        if total > MAX_HISTORY_CHARS and i < len(messages) - 8:
            cutoff = i + 1
            break

    return messages[cutoff:]


def to_claude_history(history) -> list:
    messages = []
    for h in history:
        role = h.role if hasattr(h, "role") else h.get("role", "user")
        content = h.content if hasattr(h, "content") else h.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})
    # NOTE: do NOT strip a trailing assistant message here. The Anthropic
    # Messages API accepts histories ending with an assistant turn, and the
    # frontend deliberately sends history ending with Tony's last reply
    # (the new user message is appended separately by each caller). A
    # previous trailing-pop here deleted Tony's most recent reply from
    # every request, making each response re-answer the previous message.
    return _truncate_history(messages)


def to_gemini_history(history) -> list:
    messages = []
    for h in history:
        role = h.role if hasattr(h, "role") else h.get("role", "user")
        content = h.content if hasattr(h, "content") else h.get("content", "")
        gemini_role = "model" if role == "assistant" else "user"
        messages.append({"role": gemini_role, "parts": [{"text": content}]})
    return _truncate_history(messages)


def to_openai_history(history) -> list:
    messages = []
    for h in history:
        role = h.role if hasattr(h, "role") else h.get("role", "user")
        content = h.content if hasattr(h, "content") else h.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})
    return _truncate_history(messages)
