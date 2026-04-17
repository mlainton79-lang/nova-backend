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

    # Case RAG injection
    case_context = ""
    try:
        from app.core.rag import list_cases, search_case
        case_kw = ["case", "western circle", "westerncircle", "complaint", "legal", "build a case",
                   "emails about", "what did they say", "what have they said",
                   "timeline", "evidence", "prove", "claim", "dispute"]
        if any(k in req.message.lower() for k in case_kw):
            all_cases = list_cases()
            ready_cases = [c for c in all_cases if c["status"] == "ready"]
            if ready_cases:
                target_case = ready_cases[0]
                for c in ready_cases:
                    if c["name"].lower() in req.message.lower():
                        target_case = c
                        break
                results = await search_case(target_case["id"], req.message, top_k=20)
                if results:
                    lines = [f"[CASE: {target_case['name']} — {target_case['total_emails']} emails ingested. Answer ONLY from this data, do not speculate.]"]
                    lines.append("Most relevant excerpts:")
                    for r in results:
                        src = f"[{r['date'][:16]}] {r['sender']} — {r['subject']}"
                        if r.get("attachment"):
                            src += f" (attachment: {r['attachment']})"
                        lines.append(f"SOURCE: {src}")
                        lines.append(r["content"])
                        lines.append("---")
                    case_context = "\n".join(lines)
    except Exception as e:
        print(f"[COUNCIL] case context failed: {e}")

    # Gmail context injection
    gmail_context = ""
    try:
        msg_lower = req.message.lower()
        email_kw = ["email", "gmail", "inbox", "unread", "message", "mail", "from ", "subject", "sent me", "wrote to", "morning", "summary"]
        if any(k in msg_lower for k in email_kw):
            from app.core.gmail_service import get_morning_summary, search_all_accounts
            search_triggers = ["from ", "about ", "subject", "find", "search", "look for", "anything from", "emails from", "sent", "show me", "any ", "have i", "all emails", "everything from"]
            if any(t in msg_lower for t in search_triggers):
                results = await search_all_accounts(req.message, max_per_account=10)
                if results:
                    lines = ["[GMAIL SEARCH RESULTS]"]
                    for e in results[:10]:
                        sender = e.get("from","").split("<")[0].strip() or e.get("from","")
                        lines.append(f"• [{e['account']}] From: {sender} — {e['subject']} ({e['date']})")
                        if e.get("snippet"):
                            lines.append(f"  {e['snippet'][:150]}")
                    gmail_context = "\n".join(lines)
            else:
                summary = await get_morning_summary()
                if summary:
                    gmail_context = "[GMAIL SUMMARY]\n" + summary
    except Exception as e:
        print(f"[COUNCIL] gmail context failed: {e}")

    system_prompt = safe_system_prompt(req, search_results)
    if case_context:
        system_prompt += "\n\n" + case_context
    if gmail_context:
        system_prompt += "\n\n" + gmail_context

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
