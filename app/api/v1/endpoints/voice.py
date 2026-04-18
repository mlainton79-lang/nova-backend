"""
Tony's voice endpoints.
Tony speaks his responses via Azure TTS (natural British male voice).
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token
from app.core.voice import tony_speak, tony_speak_chunked

router = APIRouter()


class SpeakRequest(BaseModel):
    text: str
    voice: str = "en-GB-RyanNeural"


@router.post("/voice/speak")
async def speak(req: SpeakRequest, _=Depends(verify_token)):
    """
    Convert text to Tony's voice. Returns base64 MP3.
    Android app decodes and plays directly.
    """
    audio_b64 = await tony_speak(req.text, req.voice)
    if not audio_b64:
        return {"ok": False, "error": "Voice synthesis failed"}
    return {
        "ok": True,
        "audio_base64": audio_b64,
        "format": "mp3",
        "voice": req.voice
    }


@router.post("/voice/speak-chunked")
async def speak_chunked(req: SpeakRequest, _=Depends(verify_token)):
    """Convert long text to multiple audio chunks for sequential playback."""
    chunks = await tony_speak_chunked(req.text)
    return {
        "ok": bool(chunks),
        "chunks": chunks,
        "count": len(chunks),
        "format": "mp3"
    }


@router.get("/voice/test")
async def voice_test(_=Depends(verify_token)):
    """Test Tony's voice."""
    audio = await tony_speak("Hello Matthew. Tony here. Voice is working.")
    return {
        "ok": bool(audio),
        "audio_base64": audio,
        "format": "mp3"
    }


@router.get("/voice/status")
async def voice_status(_=Depends(verify_token)):
    """Show which TTS provider is active."""
    import os
    elevenlabs = bool(os.environ.get("ELEVENLABS_API_KEY"))
    azure = bool(os.environ.get("AZURE_SPEECH_KEY"))
    google = bool(os.environ.get("GOOGLE_TTS_KEY"))
    active = "elevenlabs" if elevenlabs else "azure" if azure else "google" if google else "gtts"
    return {
        "elevenlabs_configured": elevenlabs,
        "elevenlabs_voice_id": os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9"),
        "azure_configured": azure,
        "google_configured": google,
        "active": active
    }
