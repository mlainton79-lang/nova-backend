import os
import httpx
from typing import List, Optional
from app.providers.base import ProviderAdapter
from app.schemas.chat import HistoryMessage
from app.utils.history import to_gemini_history
from app.core.config import GEMINI_API_KEY
from app.core.secrets_redact import redact
from app.core.model_router_smart import is_provider_skipped

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
        if is_provider_skipped("gemini"):
            raise RuntimeError("Gemini provider is disabled by DISABLED_AI_PROVIDERS")
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

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                headers={"x-goog-api-key": GEMINI_API_KEY},
                json={
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": gemini_history,
                    "generationConfig": {"maxOutputTokens": 8192}
                }
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Gemini {response.status_code}: {redact(response.text)[:500]}")
            data = response.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError, TypeError, AttributeError) as e:
                keys = list(data.keys())[:5] if isinstance(data, dict) else []
                raise ValueError(
                    "provider response shape change: missing or invalid "
                    f"candidates[0].content.parts[0].text; got keys={keys}"
                ) from e
