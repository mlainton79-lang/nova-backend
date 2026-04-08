from pydantic import BaseModel
from typing import List, Optional

class HistoryMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    provider: str
    message: str
    history: List[HistoryMessage] = []
    context: Optional[str] = None

class ChatResponse(BaseModel):
    ok: bool
    provider: str
    reply: str
    latency_ms: Optional[int] = None
    error: Optional[str] = None
