"""
Voice transcription correction endpoint.
Fixes speech-to-text errors intelligently using context.
Fast — uses Gemini Flash with minimal tokens.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token
import httpx, os

router = APIRouter()

class TranscriptionRequest(BaseModel):
    text: str

@router.post("/voice/correct")
async def correct_transcription(req: TranscriptionRequest, _=Depends(verify_token)):
    """
    Correct common speech-to-text errors intelligently.
    Returns corrected text. Fast — designed to run before every voice message.
    """
    if not req.text or len(req.text.strip()) < 2:
        return {"corrected": req.text, "changed": False}

    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    if not GEMINI_API_KEY:
        return {"corrected": req.text, "changed": False}

    prompt = f"""Fix speech-to-text transcription errors in this text. 

Rules:
- Fix obvious voice recognition mistakes (wrong homophones, missing apostrophes, misspellings)
- Preserve meaning exactly — do not rephrase or add words
- Fix capitalisation of proper nouns (names, places)
- If the text is already correct, return it unchanged
- Return ONLY the corrected text, nothing else

Text: {req.text}"""

    try:
        from app.core import gemini_client
        resp = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": 200, "temperature": 0.1},
            timeout=5.0,
            caller_context="transcription.correct",
        )
        corrected = gemini_client.extract_text(resp).strip()
        if corrected:
            # Sanity check — if Gemini returns something wildly different, use original
            if len(corrected) > len(req.text) * 2 or len(corrected) < len(req.text) * 0.5:
                return {"corrected": req.text, "changed": False}
            changed = corrected.lower() != req.text.lower()
            return {"corrected": corrected, "changed": changed}
    except Exception as e:
        print(f"[TRANSCRIPTION] Correction failed: {e}")

    return {"corrected": req.text, "changed": False}
