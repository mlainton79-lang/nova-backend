from typing import List

def to_claude_history(history) -> list:
    messages = []
    for h in history:
        role = h.role if hasattr(h, "role") else h.get("role", "user")
        content = h.content if hasattr(h, "content") else h.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})
    # Claude 4.6+ rejects requests ending with an assistant message
    # Strip any trailing assistant messages to avoid 400 errors
    while messages and messages[-1]["role"] == "assistant":
        messages.pop()
    return messages

def to_gemini_history(history) -> list:
    messages = []
    for h in history:
        role = h.role if hasattr(h, "role") else h.get("role", "user")
        content = h.content if hasattr(h, "content") else h.get("content", "")
        gemini_role = "model" if role == "assistant" else "user"
        messages.append({"role": gemini_role, "parts": [{"text": content}]})
    return messages

def to_openai_history(history) -> list:
    messages = []
    for h in history:
        role = h.role if hasattr(h, "role") else h.get("role", "user")
        content = h.content if hasattr(h, "content") else h.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})
    return messages
