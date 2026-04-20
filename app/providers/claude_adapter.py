import os
import httpx
from typing import List
from app.providers.base import ProviderAdapter
from app.schemas.chat import HistoryMessage
from app.utils.history import to_claude_history
from app.core.config import ANTHROPIC_API_KEY

CLAUDE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
CLAUDE_VISION_MODEL = os.environ.get("ANTHROPIC_VISION_MODEL", "claude-sonnet-4-6")

class ClaudeAdapter(ProviderAdapter):
    async def chat(
        self,
        message: str,
        history: List[HistoryMessage],
        system_prompt: str,
        image_base64: str = None,
        image_mime: str = "image/jpeg"
    ) -> str:
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set")

        messages = to_claude_history(history)

        if image_base64:
            user_content = [
                {"type": "image", "source": {"type": "base64", "media_type": image_mime, "data": image_base64}},
                {"type": "text", "text": message}
            ]
            model = CLAUDE_VISION_MODEL
        else:
            user_content = message
            model = CLAUDE_MODEL

        messages.append({"role": "user", "content": user_content})

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "max_tokens": 4096,
                    "system": system_prompt,
                    "messages": messages
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"].strip()
