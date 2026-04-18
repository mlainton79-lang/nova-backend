"""
Tony's voice endpoints.
Tony speaks his responses.
"""
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from app.core.security import verify_token
from app.core.voice import tony_speak, tony_speak_chunked
import base64

router = APIRouter()

@router.post("/voice/speak")
async def speak(text: str, voice: str = "en-GB-Neural2-B", _=Depends(verify_token)):
    """
    Convert text to Tony's voice. Returns base64 MP3.
    The Android app decodes and plays this directly.
    """
    audio_b64 = await tony_speak(text, voice)
    if not audio_b64:
        return {"ok": False, "error": "Voice synthesis failed"}
    return {
        "ok": True,
        "audio_base64": audio_b64,
        "format": "mp3",
        "voice": voice
    }

@router.post("/voice/speak-chunked")
async def speak_chunked(text: str, _=Depends(verify_token)):
    """Convert long text to multiple audio chunks for sequential playback."""
    chunks = await tony_speak_chunked(text)
    return {
        "ok": bool(chunks),
        "chunks": chunks,
        "count": len(chunks),
        "format": "mp3"
    }

@router.get("/voice/test")
async def voice_test(_=Depends(verify_token)):
    """Test Tony's voice."""
    test_text = "Hello Matthew. Tony here. Voice is working."
    audio = await tony_speak(test_text)
    return {
        "ok": bool(audio),
        "audio_base64": audio,
        "format": "mp3",
        "note": "Decode base64 and play as MP3"
    }

@router.get("/voice/voices")
async def list_voices(_=Depends(verify_token)):
    """Available voices."""
    return {
        "voices": [
            {"id": "en-GB-Neural2-B", "description": "British male, neural (best quality, needs Google TTS key)"},
            {"id": "en-GB-Neural2-D", "description": "British male alternative, neural"},
            {"id": "en-GB-Standard-B", "description": "British male, standard"},
            {"id": "gtts-fallback", "description": "Free fallback voice (gTTS)"},
        ],
        "current": "Neural2-B with gTTS fallback",
        "google_tts_configured": bool(__import__('os').environ.get("GOOGLE_TTS_KEY"))
    }
