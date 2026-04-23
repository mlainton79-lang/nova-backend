import os
import httpx
from typing import List
from app.providers.base import ProviderAdapter
from app.schemas.chat import HistoryMessage
from app.utils.history import to_openai_history
from app.core.config import OPENAI_API_KEY
from app.core.secrets_redact import redact

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")

class OpenAIAdapter(ProviderAdapter):
    async def chat(self, message: str, history: List[HistoryMessage], system_prompt: str) -> str:
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set")

        messages = [{"role": "system", "content": system_prompt}]
        messages += to_openai_history(history)
        messages.append({"role": "user", "content": message})

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": OPENAI_MODEL,
                    "messages": messages,
                    "max_tokens": 4096
                }
            )
            if response.status_code >= 400:
                raise RuntimeError(f"OpenAI {response.status_code}: {redact(response.text)[:500]}")
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
