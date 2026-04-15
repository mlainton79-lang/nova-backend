import time, os, json, httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.schemas.chat import ChatRequest
from app.core.security import verify_token
from app.prompts.tony import build_system_prompt
from app.core.injection_filter import check_injection
from app.core.logger import log_request

router = APIRouter()

async def gemini_stream(message, history, system_prompt):
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    contents = []
    for h in history:
        role = h.role if hasattr(h, "role") else h.get("role", "user")
        content = h.content if hasattr(h, "content") else h.get("content", "")
        gemini_role = "model" if role == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": content}]})
    contents.append({"role": "user", "parts": [{"text": message}]})
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 65536}
    }
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
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

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, _=Depends(verify_token)):
    provider_key = request.provider.lower().strip()
    injected, reason = check_injection(request.message)
    if injected:
        async def err():
            yield f"data: {json.dumps({'type':'error','text':'Blocked.'})}\n\n"
            yield f"data: {json.dumps({'type':'done'})}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")
    sp = build_system_prompt(
        context=request.context,
        document_text=request.document_text,
        document_base64=request.document_base64,
        document_name=request.document_name,
        document_mime=request.document_mime,
        include_codebase=False
    )
    start = time.time()
    async def gen():
        parts = []
        try:
            async for chunk in gemini_stream(request.message, request.history, sp):
                parts.append(chunk)
                yield f"data: {json.dumps({'type':'chunk','text':chunk})}\n\n"
            full = "".join(parts)
            log_request(provider=provider_key, message=request.message, reply=full[:500], latency_ms=int((time.time()-start)*1000), ok=True)
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','text':str(e)})}\n\n"
            log_request(provider=provider_key, message=request.message, reply="", latency_ms=int((time.time()-start)*1000), ok=False, error=str(e))
        yield f"data: {json.dumps({'type':'done'})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
