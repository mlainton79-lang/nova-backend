import os
import httpx
from typing import List
from app.providers.base import ProviderAdapter
from app.schemas.chat import HistoryMessage
from app.utils.history import to_openai_history
from app.core.secrets_redact import redact

XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
XAI_MODEL = os.environ.get("XAI_MODEL", "grok-4")

class XAIAdapter(ProviderAdapter):
    async def chat(self, message: str, history: List[HistoryMessage], system_prompt: str) -> str:
        if not XAI_API_KEY:
            raise ValueError("XAI_API_KEY is not set")
        messages = [{"role": "system", "content": system_prompt}]
        messages += to_openai_history(history)
        messages.append({"role": "user", "content": message})
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
                json={"model": XAI_MODEL, "messages": messages, "max_tokens": 4096}
            )
            if response.status_code >= 400:
                raise RuntimeError(f"xAI {response.status_code}: {redact(response.text)[:500]}")
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
