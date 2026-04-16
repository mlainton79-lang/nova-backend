import os
import httpx
from typing import List
from app.providers.base import ProviderAdapter
from app.schemas.chat import HistoryMessage
from app.utils.history import to_openai_history

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")

class MistralAdapter(ProviderAdapter):
    async def chat(self, message: str, history: List[HistoryMessage], system_prompt: str) -> str:
        if not MISTRAL_API_KEY:
            raise ValueError("MISTRAL_API_KEY is not set")
        messages = [{"role": "system", "content": system_prompt}]
        messages += to_openai_history(history)
        messages.append({"role": "user", "content": message})
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
                json={"model": MISTRAL_MODEL, "messages": messages, "max_tokens": 4096}
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
