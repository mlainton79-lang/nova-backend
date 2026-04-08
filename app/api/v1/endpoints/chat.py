import time
from fastapi import APIRouter, Depends
from app.schemas.chat import ChatRequest, ChatResponse
from app.core.security import verify_token
from app.prompts.tony import build_system_prompt
from app.providers.openai_adapter import OpenAIAdapter
from app.providers.gemini_adapter import GeminiAdapter
from app.providers.claude_adapter import ClaudeAdapter

router = APIRouter()

PROVIDERS = {
    "openai": OpenAIAdapter(),
    "gemini": GeminiAdapter(),
    "claude": ClaudeAdapter(),
}

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _=Depends(verify_token)):
    provider_key = request.provider.lower().strip()

    if provider_key == "council":
        return ChatResponse(
            ok=True,
            provider="council",
            reply="Council mode is coming in the next update. For now, choose OpenAI, Gemini, or Claude individually."
        )

    adapter = PROVIDERS.get(provider_key)
    if not adapter:
        return ChatResponse(
            ok=False,
            provider=provider_key,
            reply="",
            error=f"Unknown provider: {provider_key}. Use openai, gemini, or claude."
        )

    system_prompt = build_system_prompt(request.context)

    start = time.time()
    try:
        reply = await adapter.chat(request.message, request.history, system_prompt)
        latency_ms = int((time.time() - start) * 1000)
        return ChatResponse(ok=True, provider=provider_key, reply=reply, latency_ms=latency_ms)
    except Exception as e:
        return ChatResponse(
            ok=False,
            provider=provider_key,
            reply="Tony is having trouble connecting right now. Please try again or switch provider.",
            error=str(e)
        )
