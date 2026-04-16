import time, os, json, httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.schemas.chat import ChatRequest
from app.core.security import verify_token
from app.core.injection_filter import check_injection
from app.core.logger import log_request
from app.core.instant_memory import extract_and_save_instant_memory
from app.core.memory import add_memory

router = APIRouter()

def safe_system_prompt(request):
    try:
        from app.prompts.tony import build_system_prompt
        code_kw = ["code","function","file","class","bug","error","fix","kotlin","python","api","push","patch"]
        inc = any(k in request.message.lower() for k in code_kw)
        return build_system_prompt(context=request.context, document_text=request.document_text, document_base64=request.document_base64, document_name=request.document_name, document_mime=request.document_mime, include_codebase=inc)
    except Exception:
        return "You are Tony, Matthew's personal AI assistant. Be direct, warm, and helpful. British English only."

async def gemini_stream(message, history, system_prompt):
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    contents = []
    for h in history:
        role = h.role if hasattr(h, "role") else h.get("role", "user")
        content = h.content if hasattr(h, "content") else h.get("content", "")
        contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]})
    contents.append({"role": "user", "parts": [{"text": message}]})
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(url, json={"system_instruction": {"parts": [{"text": system_prompt}]}, "contents": contents, "generationConfig": {"maxOutputTokens": 65536}}, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            yield "[No response]"
            return
        parts = candidates[0].get("content", {}).get("parts", [])
        full = " ".join(p.get("text", "") for p in parts if "text" in p).strip()
        words = full.split()
        buf = []
        for w in words:
            buf.append(w)
            if len(buf) >= 4:
                yield " ".join(buf) + " "
                buf = []
        if buf:
            yield " ".join(buf)

async def claude_stream(message, history, system_prompt, image_base64=None, image_mime="image/jpeg"):
    from app.core.config import ANTHROPIC_API_KEY
    model = os.environ.get("ANTHROPIC_VISION_MODEL" if image_base64 else "ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    from app.utils.history import to_claude_history
    messages = to_claude_history(history)
    if image_base64:
        user_content = [{"type": "image", "source": {"type": "base64", "media_type": image_mime, "data": image_base64}}, {"type": "text", "text": message}]
    else:
        user_content = message
    messages.append({"role": "user", "content": user_content})
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}, json={"model": model, "max_tokens": 4096, "system": system_prompt, "messages": messages})
        response.raise_for_status()
        data = response.json()
        full = data["content"][0]["text"].strip()
        words = full.split()
        buf = []
        for w in words:
            buf.append(w)
            if len(buf) >= 4:
                yield " ".join(buf) + " "
                buf = []
        if buf:
            yield " ".join(buf)

async def openai_stream(message, history, system_prompt):
    from app.core.config import OPENAI_API_KEY
    from app.utils.history import to_openai_history
    messages = [{"role": "system", "content": system_prompt}] + to_openai_history(history) + [{"role": "user", "content": message}]
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}, json={"model": "gpt-4o", "messages": messages, "max_tokens": 4096})
        response.raise_for_status()
        data = response.json()
        full = data["choices"][0]["message"]["content"].strip()
        words = full.split()
        buf = []
        for w in words:
            buf.append(w)
            if len(buf) >= 4:
                yield " ".join(buf) + " "
                buf = []
        if buf:
            yield " ".join(buf)

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, _=Depends(verify_token)):
    provider_key = request.provider.lower().strip()
    injected, reason = check_injection(request.message)
    if injected:
        async def err():
            yield "data: " + json.dumps({"type": "error", "text": "Blocked."}) + "\n\n"
            yield "data: " + json.dumps({"type": "done"}) + "\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")
    sp = safe_system_prompt(request)
    start = time.time()
    async def gen():
        parts = []
        try:
            if provider_key == "claude":
                stream_fn = claude_stream(request.message, request.history, sp, image_base64=request.image_base64)
            elif provider_key == "openai":
                stream_fn = openai_stream(request.message, request.history, sp)
            else:
                stream_fn = gemini_stream(request.message, request.history, sp)
            async for chunk in stream_fn:
                parts.append(chunk)
                yield "data: " + json.dumps({"type": "chunk", "text": chunk}) + "\n\n"
            full = "".join(parts)
            log_request(provider=provider_key, message=request.message, reply=full[:500], latency_ms=int((time.time()-start)*1000), ok=True)
            try:
                facts = await extract_and_save_instant_memory(request.message, full)
                for fact in facts:
                    add_memory("auto", fact)
            except Exception:
                pass
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "text": str(e)}) + "\n\n"
            log_request(provider=provider_key, message=request.message, reply="", latency_ms=int((time.time()-start)*1000), ok=False, error=str(e))
        yield "data: " + json.dumps({"type": "done"}) + "\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
