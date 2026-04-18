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

    # Pre-processing: all context gathered with unified 5s budget
    import asyncio as _pre_asyncio
    import time as _ctime
    _cstart = _ctime.time()
    def _cleft(): return max(0, 5.0 - (_ctime.time() - _cstart))

    search_results = ""
    case_context = ""
    gmail_context = ""

    # Web search
    try:
        from app.core.brave_search import should_search, brave_search
        if should_search(req.message) and _cleft() > 1.0:
            search_results = await _pre_asyncio.wait_for(brave_search(req.message), timeout=1.5)
    except Exception:
        pass

    # Case RAG
    try:
        from app.core.rag import list_cases, search_case
        case_kw = ["case", "western circle", "westerncircle", "complaint", "legal",
                   "what did they say", "timeline", "evidence", "claim", "dispute", "ccj"]
        if any(k in req.message.lower() for k in case_kw) and _cleft() > 1.5:
            all_cases = list_cases()
            ready = [c for c in all_cases if c["status"] == "ready"]
            if ready:
                target = ready[0]
                for c in ready:
                    if c["name"].lower() in req.message.lower():
                        target = c; break
                results = await _pre_asyncio.wait_for(
                    search_case(target["id"], req.message, top_k=5), timeout=2.0)
                if results:
                    lines = [f"[CASE: {target['name']} — answer only from these excerpts]"]
                    for r in results:
                        lines.append(f"[{r['date'][:16]}] {r['sender'][:40]} — {r['subject'][:50]}")
                        lines.append(r["content"][:200])
                        lines.append("---")
                    case_context = "\n".join(lines)
    except Exception:
        pass

    # Gmail
    try:
        msg_lower = req.message.lower()
        email_kw = ["email", "gmail", "inbox", "unread", "message", "mail", "from ",
                    "subject", "sent me", "wrote to", "morning", "look up", "find",
                    "search", "emails from", "victoria", "adler"]
        if any(k in msg_lower for k in email_kw) and _cleft() > 1.0:
            from app.core.gmail_service import get_morning_summary, search_all_accounts
            search_triggers = ["from ", "find", "search", "look for", "anything from",
                              "emails from", "show me", "look up", "victoria", "adler"]

            async def _gc():
                if any(t in msg_lower for t in search_triggers):
                    results = await search_all_accounts(req.message, max_per_account=8)
                    if results:
                        lines = ["[GMAIL SEARCH]"]
                        for e in results[:8]:
                            sender = e.get("from","").split("<")[0].strip()
                            lines.append(f"• {sender} — {e['subject']} ({e['date'][:16]})")
                            if e.get("snippet"):
                                lines.append(f"  {e['snippet'][:100]}")
                        return "\n".join(lines)
                else:
                    s = await get_morning_summary()
                    return f"[GMAIL]\n{s}" if s else ""
                return ""
            gmail_context = await _pre_asyncio.wait_for(_gc(), timeout=min(2.0, _cleft()))
    except Exception:
        pass


    import asyncio as _asyncio
    loop = _asyncio.get_event_loop()
    system_prompt = await loop.run_in_executor(None, lambda: safe_system_prompt(req, search_results))
    for ctx in [case_context, gmail_context]:
        if ctx:
            system_prompt += "\n\n" + ctx

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
