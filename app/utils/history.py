from typing import List
from app.schemas.chat import HistoryMessage

def to_openai_history(history: List[HistoryMessage]) -> list:
    return [{"role": m.role, "content": m.content} for m in history[-20:]]

def to_gemini_history(history: List[HistoryMessage]) -> list:
    result = []
    for m in history[-20:]:
        role = "model" if m.role == "assistant" else "user"
        result.append({"role": role, "parts": [{"text": m.content}]})
    return result

def to_claude_history(history: List[HistoryMessage]) -> list:
    return [{"role": m.role, "content": m.content} for m in history[-20:]]
