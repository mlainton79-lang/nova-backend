import time
from fastapi import APIRouter, Depends
from app.schemas.chat import ChatRequest, ChatResponse
from app.core.security import verify_token
from app.core.logger import log_request
from app.core.injection_filter import check_injection
from app.core.instant_memory import extract_and_save_instant_memory
from app.core.memory import add_memory
from app.providers.openai_adapter import OpenAIAdapter
from app.providers.gemini_adapter import GeminiAdapter
from app.providers.claude_adapter import ClaudeAdapter

router = APIRouter()

def safe_system_prompt(req):
    try:
        from app.prompts.tony import build_system_prompt
        code_kw = ["code","function","file","class","bug","error","fix","kotlin","python","api","push","patch"]
        inc = any(k in req.message.lower() for k in code_kw)
        return build_system_prompt(context=req.context, document_text=req.document_text, document_base64=req.document_base64, document_name=req.document_name, document_mime=req.document_mime, include_codebase=inc)
    except Exception as e:
        print(f"[CHAT] system prompt failed: {e}")
        return "You are Tony, Matthew's personal AI assistant. Be direct, warm, and helpful. British English only."

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _=Depends(verify_token)):
    injected, reason = check_injection(request.message)
    if injected:
        log_request(provider=request.provider, message=request.message, reply="", ok=False, error=reason)
        return ChatResponse(ok=False, provider=request.provider, reply="I cannot process that message.", error=reason)

    provider_key = request.provider.lower().strip()
    if provider_key == "council":
        return ChatResponse(ok=True, provider="council", reply="Use the /council endpoint for Council mode.")

    system_prompt = safe_system_prompt(request)
    start = time.time()

    try:
        if provider_key == "claude":
            reply = await ClaudeAdapter().chat(request.message, request.history, system_prompt, image_base64=request.image_base64)
        elif provider_key == "gemini":
            reply = await GeminiAdapter().chat(request.message, request.history, system_prompt)
        elif provider_key == "openai":
            reply = await OpenAIAdapter().chat(request.message, request.history, system_prompt)
        else:
            return ChatResponse(ok=False, provider=provider_key, reply="", error=f"Unknown provider: {provider_key}")

        latency_ms = int((time.time() - start) * 1000)
        log_request(provider=provider_key, message=request.message, reply=reply[:500], latency_ms=latency_ms, ok=True)
        try:
            facts = await extract_and_save_instant_memory(request.message, reply)
            for fact in facts:
                add_memory("auto", fact)
        except Exception:
            pass
        return ChatResponse(ok=True, provider=provider_key, reply=reply, latency_ms=latency_ms)
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        log_request(provider=provider_key, message=request.message, reply="", latency_ms=latency_ms, ok=False, error=str(e))
        return ChatResponse(ok=False, provider=provider_key, reply="Tony is having trouble connecting right now. Please try again or switch provider.", error=str(e))
