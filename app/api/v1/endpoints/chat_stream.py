import time, os, json, httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.schemas.chat import ChatRequest
from app.core.security import verify_token
from app.prompts.tony import build_system_prompt
from app.core.injection_filter import check_injection
from app.core.logger import log_request

router = APIRouter()

def get_gemini_tools():
    from app.providers.gemini_adapter import GEMINI_TOOL_DECLARATIONS
    return GEMINI_TOOL_DECLARATIONS

def get_gemini_history(history):
    from app.utils.history import to_gemini_history
    return to_gemini_history(history)

async def execute_tool(tool_name, tool_args):
    from app.core.tool_registry import execute_tool as _execute_tool
    return await _execute_tool(tool_name, tool_args)

async def gemini_stream_with_tools(message, history, system_prompt):
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    gemini_history = get_gemini_history(history)
    gemini_history.append({"role": "user", "parts": [{"text": message}]})
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": gemini_history,
        "tools": get_gemini_tools(),
        "generationConfig": {"maxOutputTokens": 65536}
    }
    async with httpx.AsyncClient(timeout=300.0) as client:
        for attempt in range(3):
            try:
                response = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                if response.status_code == 503:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                break
            except httpx.HTTPStatusError:
                if attempt == 2:
                    raise
        data = response.json()
        for iteration in range(10):
            candidates = data.get("candidates", [])
            if not candidates:
                yield "[No response]"
                return
            parts = candidates[0].get("content", {}).get("parts", [])
            fcalls = [p for p in parts if "functionCall" in p]
            if not fcalls:
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
                return
            gemini_history.append({"role": "model", "parts": parts})
            fparts = []
            for fp in fcalls:
                fc = fp["functionCall"]
                yield f"[Reading {fc['name']}...] "
                r = await execute_tool(fc["name"], fc.get("args", {}))
                fparts.append({"functionResponse": {"name": fc["name"], "response": {"result": r}}})
            gemini_history.append({"role": "user", "parts": fparts})
            payload["contents"] = gemini_history
            r2 = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            r2.raise_for_status()
            data = r2.json()

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, _=Depends(verify_token)):
    provider_key = request.provider.lower().strip()
    injected, reason = check_injection(request.message)
    if injected:
        async def err():
            yield f"data: {json.dumps({'type':'error','text':'Blocked.'})}\n\n"
            yield f"data: {json.dumps({'type':'done'})}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")
    code_kw = ["code","function","file","class","method","bug","error","fix","refactor","kotlin","python","mainactivity","backend","endpoint","api","build","gradle","def","fun","kit","py","import"]
    inc_code = any(k in request.message.lower() for k in code_kw)
    sp = build_system_prompt(
        context=request.context,
        document_text=request.document_text,
        document_base64=request.document_base64,
        document_name=request.document_name,
        document_mime=request.document_mime,
        include_codebase=inc_code
    )
    start = time.time()
    async def gen():
        parts = []
        try:
            if provider_key == "gemini":
                async for chunk in gemini_stream_with_tools(request.message, request.history, sp):
                    parts.append(chunk)
                    yield f"data: {json.dumps({'type':'chunk','text':chunk})}\n\n"
            else:
                from app.providers.openai_adapter import OpenAIAdapter
                from app.providers.claude_adapter import ClaudeAdapter
                adapters = {"openai": OpenAIAdapter(), "claude": ClaudeAdapter()}
                a = adapters.get(provider_key)
                if a:
                    reply = await a.chat(request.message, request.history, sp)
                    parts.append(reply)
                    yield f"data: {json.dumps({'type':'chunk','text':reply})}\n\n"
                else:
                    yield f"data: {json.dumps({'type':'error','text':'Unknown provider'})}\n\n"
            full = "".join(parts)
            try:
                from app.core.instant_memory import extract_and_save_instant_memory
                from app.core.memory import add_memory
                facts = await extract_and_save_instant_memory(request.message, full)
                for fact in facts:
                    add_memory("auto", fact)
            except Exception:
                pass
            log_request(provider=provider_key, message=request.message, reply=full[:500], latency_ms=int((time.time()-start)*1000), ok=True)
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','text':str(e)})}\n\n"
            log_request(provider=provider_key, message=request.message, reply="", latency_ms=int((time.time()-start)*1000), ok=False, error=str(e))
        yield f"data: {json.dumps({'type':'done'})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
