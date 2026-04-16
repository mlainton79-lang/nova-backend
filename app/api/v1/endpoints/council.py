import os, httpx
from fastapi import APIRouter, Depends
from app.schemas.chat import ChatRequest, CouncilResponse
from app.providers.council import run_council
from app.core.security import verify_token
from app.core.logger import log_request
from app.core.injection_filter import check_injection
from app.core.instant_memory import extract_and_save_instant_memory
from app.core.memory import add_memory
from app.core.auto_push import process_auto_push

router = APIRouter()

def safe_system_prompt(req, search_results=""):
    try:
        from app.prompts.tony import build_system_prompt
        code_kw = ["code","function","file","class","bug","error","fix","kotlin","python","api","push","patch"]
        inc = any(k in req.message.lower() for k in code_kw)
        sp = build_system_prompt(context=req.context, document_text=req.document_text, document_base64=req.document_base64, document_name=req.document_name, document_mime=req.document_mime, include_codebase=inc)
        if search_results:
            sp += f"\n\n{search_results}"
        return sp
    except Exception:
        return "You are Tony, a personal AI assistant. British English only. Be direct and warm."

@router.post("/council", response_model=CouncilResponse)
async def council(req: ChatRequest, _=Depends(verify_token)):
    injected, reason = check_injection(req.message)
    if injected:
        log_request(provider="council", message=req.message, reply="", ok=False, error=reason)
        return CouncilResponse(ok=False, provider="council", reply="I cannot process that message.", error=reason)

    # Auto search before Council deliberation
    search_results = ""
    try:
        from app.core.brave_search import should_search, brave_search
        if should_search(req.message):
            search_results = await brave_search(req.message)
            if search_results:
                print(f"[COUNCIL] Search results injected for: {req.message[:50]}")
    except Exception as e:
        print(f"[COUNCIL] search failed: {e}")

    system_prompt = safe_system_prompt(req, search_results)
    result = await run_council(req.message, req.history, system_prompt, debug=req.debug or False)
    reply = result.get("reply", "")
    try:
        reply, push_results = await process_auto_push(reply)
        result["reply"] = reply
    except Exception: pass
    try:
        facts = await extract_and_save_instant_memory(req.message, reply)
        for fact in facts: add_memory("auto", fact)
    except Exception: pass
    log_request(provider=result.get("provider", "council"), message=req.message, reply=reply, deciding_brain=result.get("provider"))
    return result
