from pydantic import BaseModel
from typing import List, Optional

class HistoryMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    provider: str = "gemini"
    message: str
    history: List[HistoryMessage] = []
    context: Optional[str] = None          # Location + calendar from device
    location: Optional[str] = None         # "lat,lng" if sent separately
    document_text: Optional[str] = None
    document_base64: Optional[str] = None
    document_name: Optional[str] = None
    document_mime: Optional[str] = None
    image_base64: Optional[str] = None
    debug: Optional[bool] = False

class ChatResponse(BaseModel):
    ok: bool
    provider: str
    reply: str
    latency_ms: Optional[int] = None
    error: Optional[str] = None

class CouncilResponse(BaseModel):
    ok: bool
    provider: str
    reply: str
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    failures: Optional[dict] = None
    debug: Optional[dict] = None
