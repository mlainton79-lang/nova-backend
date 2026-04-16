import os
import httpx
from typing import List
from app.providers.base import ProviderAdapter
from app.schemas.chat import HistoryMessage
from app.utils.history import to_openai_history

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "qwen/qwen3-235b-a22b:free")

class OpenRouterAdapter(ProviderAdapter):
    async def chat(self, message: str, history: List[HistoryMessage], system_prompt: str) -> str:
        if not OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY is not set")
        messages = [{"role": "system", "content": system_prompt}]
        messages += to_openai_history(history)
        messages.append({"role": "user", "content": message})
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json", "HTTP-Referer": "https://nova.app", "X-Title": "Nova"},
                json={"model": OPENROUTER_MODEL, "messages": messages, "max_tokens": 4096}
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
