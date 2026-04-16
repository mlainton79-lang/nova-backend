import os
import httpx
from typing import List, Optional
from app.providers.base import ProviderAdapter
from app.schemas.chat import HistoryMessage
from app.utils.history import to_gemini_history
from app.core.config import GEMINI_API_KEY

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

class GeminiAdapter(ProviderAdapter):
    async def chat(
        self,
        message: str,
        history: List[HistoryMessage],
        system_prompt: str,
        image_base64: Optional[str] = None,
        image_mime: str = "image/jpeg"
    ) -> str:
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set")

        gemini_history = to_gemini_history(history)

        # Build user parts — text only or text + image
        if image_base64:
            user_parts = [
                {
                    "inline_data": {
                        "mime_type": image_mime,
                        "data": image_base64
                    }
                },
                {"text": message}
            ]
        else:
            user_parts = [{"text": message}]

        gemini_history.append({"role": "user", "parts": user_parts})

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                json={
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": gemini_history,
                    "generationConfig": {"maxOutputTokens": 8192}
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
