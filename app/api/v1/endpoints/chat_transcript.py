"""
Chat transcript formatter endpoint.

Option 1C: Android is the source of truth. Android POSTs a single
StoredChat-shaped JSON session here; the backend returns a Markdown
transcript suitable for sharing via Android's Intent.EXTRA_TEXT.

No DB access. No LLM calls. Pure formatting + secret scrubbing.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict

from app.core.security import verify_token
from app.core.transcript_formatter import format_chat_transcript

router = APIRouter()


class TranscriptMessage(BaseModel):
    # Unknown fields pass through without rejection — Android's ChatEntry
    # may grow new fields in future.
    model_config = ConfigDict(extra="ignore")

    role: Optional[str] = None
    text: Optional[str] = None
    createdAt: Optional[str] = None
    provider: Optional[str] = None
    debugData: Optional[str] = None


class TranscriptRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[str] = None
    title: Optional[str] = None
    chatNumber: Optional[int] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    messages: Optional[List[TranscriptMessage]] = None
    pinned: Optional[bool] = None


@router.post("/chat/transcript/format", response_class=PlainTextResponse)
async def format_transcript(request: Request, _=Depends(verify_token)):
    """Return a Markdown transcript of the posted chat session.

    Response is raw Markdown (text/markdown) so Android can read the
    body straight into Intent.EXTRA_TEXT with no JSON parse step.

    Error surface:
      - Malformed JSON           → 400 plain text
      - Wrong root shape         → 400 plain text
      - Pydantic validation fail → 400 plain text
      - Formatter exception      → 200 with a stub markdown body noting the error
                                   (formatter is contractually never-500)
    """
    # Manual JSON parse so we can honour the "400 on malformed JSON" spec
    # rather than FastAPI's default 422.
    try:
        raw = await request.json()
    except Exception as e:
        return PlainTextResponse(
            content=f"invalid JSON — {type(e).__name__}: {e}",
            status_code=400,
            media_type="text/plain; charset=utf-8",
        )
    if not isinstance(raw, dict):
        return PlainTextResponse(
            content="expected a JSON object as the chat session envelope",
            status_code=400,
            media_type="text/plain; charset=utf-8",
        )

    # Pydantic validation with extra='ignore' — unknown fields are dropped,
    # missing fields default to None, wrong types raise.
    try:
        validated = TranscriptRequest.model_validate(raw)
    except Exception as e:
        return PlainTextResponse(
            content=f"invalid chat envelope — {type(e).__name__}: {e}",
            status_code=400,
            media_type="text/plain; charset=utf-8",
        )

    # Formatter call. It's designed to never raise, but belt-and-braces:
    # a formatter crash returns a 200 with an error stub rather than 500.
    try:
        payload = validated.model_dump(exclude_none=True)
        markdown = format_chat_transcript(payload)
        return PlainTextResponse(
            content=markdown,
            media_type="text/markdown; charset=utf-8",
        )
    except Exception as e:
        return PlainTextResponse(
            content=(
                "# Chat transcript — (formatter error)\n\n"
                f"Error: {type(e).__name__}: {e}\n"
            ),
            status_code=200,
            media_type="text/markdown; charset=utf-8",
        )
