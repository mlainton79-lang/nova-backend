import httpx
from typing import List
from app.providers.base import ProviderAdapter
from app.schemas.chat import HistoryMessage
from app.utils.history import to_openai_history
from app.core.config import OPENAI_API_KEY

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
                    "model": "gpt-4o-mini",
                    "messages": messages,
                    "max_tokens": 1000
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
