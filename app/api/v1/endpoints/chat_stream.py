import time, os, json, asyncio, httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.schemas.chat import ChatRequest
from app.core.security import verify_token
from app.core.injection_filter import check_injection
from app.core.logger import log_request
from app.core.instant_memory import extract_and_save_instant_memory
from app.core.memory import add_memory

router = APIRouter()

def safe_system_prompt(request, search_results=""):
    try:
        from app.prompts.tony import build_system_prompt
        code_kw = ["code","function","file","class","bug","error","fix","kotlin","python","api","push","patch"]
        inc = any(k in request.message.lower() for k in code_kw)
        sp = build_system_prompt(
            context=request.context,
            document_text=request.document_text,
            document_base64=request.document_base64,
            document_name=request.document_name,
            document_mime=request.document_mime,
            include_codebase=inc
        )
        if search_results:
            sp += f"\n\n{search_results}"
        return sp
    except Exception as e:
        print(f"[CHAT_STREAM] System prompt failed: {e}")
        return "You are Tony, Matthew's personal AI assistant. Be direct, warm, and helpful. British English only."


def _word_stream(full_text: str):
    """Yield chunks of ~4 words for smooth streaming."""
    words = full_text.split()
    buf = []
    for w in words:
        buf.append(w)
        if len(buf) >= 4:
            yield " ".join(buf) + " "
            buf = []
    if buf:
        yield " ".join(buf)


async def gemini_stream(message, history, system_prompt, image_base64=None, image_mime="image/jpeg"):
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    contents = []
    for h in history:
        role = h.role if hasattr(h, "role") else h.get("role", "user")
        content = h.content if hasattr(h, "content") else h.get("content", "")
        contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]})

    if image_base64:
        user_parts = [
            {"inline_data": {"mime_type": image_mime, "data": image_base64}},
            {"text": message}
        ]
    else:
        user_parts = [{"text": message}]

    contents.append({"role": "user", "parts": user_parts})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            url,
            json={"system_instruction": {"parts": [{"text": system_prompt}]}, "contents": contents, "generationConfig": {"maxOutputTokens": 65536}},
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            yield "[No response]"
            return
        parts = candidates[0].get("content", {}).get("parts", [])
        full = " ".join(p.get("text", "") for p in parts if "text" in p).strip()
        for chunk in _word_stream(full):
            yield chunk


async def claude_stream(message, history, system_prompt, image_base64=None, image_mime="image/jpeg"):
    from app.core.config import ANTHROPIC_API_KEY
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    from app.utils.history import to_claude_history
    messages = to_claude_history(history)
    if image_base64:
        user_content = [
            {"type": "image", "source": {"type": "base64", "media_type": image_mime, "data": image_base64}},
            {"type": "text", "text": message}
        ]
    else:
        user_content = message
    messages.append({"role": "user", "content": user_content})
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={"model": model, "max_tokens": 4096, "system": system_prompt, "messages": messages}
        )
        response.raise_for_status()
        data = response.json()
        full = data["content"][0]["text"].strip()
        for chunk in _word_stream(full):
            yield chunk


async def groq_stream(message, history, system_prompt):
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-4-scout-17b-16e-instruct")
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set")
    from app.utils.history import to_openai_history
    messages = [{"role": "system", "content": system_prompt}]
    messages += to_openai_history(history)
    messages.append({"role": "user", "content": message})
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": GROQ_MODEL, "messages": messages, "max_tokens": 4096}
        )
        response.raise_for_status()
        data = response.json()
        full = data["choices"][0]["message"]["content"].strip()
        for chunk in _word_stream(full):
            yield chunk


async def mistral_stream(message, history, system_prompt):
    MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
    MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
    if not MISTRAL_API_KEY:
        raise ValueError("MISTRAL_API_KEY not set")
    from app.utils.history import to_openai_history
    messages = [{"role": "system", "content": system_prompt}]
    messages += to_openai_history(history)
    messages.append({"role": "user", "content": message})
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
            json={"model": MISTRAL_MODEL, "messages": messages, "max_tokens": 4096}
        )
        response.raise_for_status()
        data = response.json()
        full = data["choices"][0]["message"]["content"].strip()
        for chunk in _word_stream(full):
            yield chunk


async def openrouter_stream(message, history, system_prompt):
    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openrouter/auto")
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not set")
    from app.utils.history import to_openai_history
    messages = [{"role": "system", "content": system_prompt}]
    messages += to_openai_history(history)
    messages.append({"role": "user", "content": message})
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://nova.app",
                "X-Title": "Nova"
            },
            json={"model": OPENROUTER_MODEL, "messages": messages, "max_tokens": 4096}
        )
        response.raise_for_status()
        data = response.json()
        full = data["choices"][0]["message"]["content"].strip()
        for chunk in _word_stream(full):
            yield chunk


async def openai_stream(message, history, system_prompt):
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set")
    from app.utils.history import to_openai_history
    messages = [{"role": "system", "content": system_prompt}] + to_openai_history(history) + [{"role": "user", "content": message}]
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o", "messages": messages, "max_tokens": 4096}
        )
        response.raise_for_status()
        data = response.json()
        full = data["choices"][0]["message"]["content"].strip()
        for chunk in _word_stream(full):
            yield chunk


def _get_stream_fn(provider_key: str, message: str, history, system_prompt: str, image_base64=None):
    """Route provider key to the correct stream function."""
    if provider_key == "claude":
        return claude_stream(message, history, system_prompt, image_base64=image_base64)
    elif provider_key == "openai":
        return openai_stream(message, history, system_prompt)
    elif provider_key == "groq":
        return groq_stream(message, history, system_prompt)
    elif provider_key == "mistral":
        return mistral_stream(message, history, system_prompt)
    elif provider_key == "openrouter":
        return openrouter_stream(message, history, system_prompt)
    else:
        # Default: Gemini (handles gemini, deepseek, xai, unknown)
        return gemini_stream(message, history, system_prompt, image_base64=image_base64)


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, _=Depends(verify_token)):
    provider_key = request.provider.lower().strip()

    injected, reason = check_injection(request.message)
    if injected:
        async def err():
            yield "data: " + json.dumps({"type": "error", "text": "Blocked."}) + "\n\n"
            yield "data: " + json.dumps({"type": "done"}) + "\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    search_results = ""
    case_context = ""
    gmail_context = ""
    calendar_context = ""

    import time as _time
    _preprocess_start = _time.time()

    def _time_left():
        return max(0, 5.0 - (_time.time() - _preprocess_start))

    # 1. Web search (1.5s budget)
    try:
        from app.core.brave_search import should_search, brave_search
        if should_search(request.message) and _time_left() > 1.0:
            search_results = await asyncio.wait_for(
                brave_search(request.message), timeout=1.5
            )
    except Exception as e:
        print(f"[CHAT_STREAM] Web search failed: {e}")

    # 2. Case RAG search (2s budget)
    try:
        from app.core.rag import list_cases, search_case
        case_kw = ["case", "western circle", "westerncircle", "complaint", "legal",
                   "what did they say", "timeline", "evidence", "claim", "dispute", "ccj"]
        if any(k in request.message.lower() for k in case_kw) and _time_left() > 1.5:
            all_cases = list_cases()
            ready_cases = [c for c in all_cases if c["status"] == "ready"]
            if ready_cases:
                target = ready_cases[0]
                for c in ready_cases:
                    if c["name"].lower() in request.message.lower():
                        target = c
                        break
                results = await asyncio.wait_for(
                    search_case(target["id"], request.message, top_k=3),
                    timeout=2.0
                )
                if results:
                    lines = [f"[CASE: {target['name']} — answer only from these excerpts]"]
                    for r in results:
                        lines.append(f"[{r['date'][:16]}] {r['sender'][:40]} — {r['subject'][:50]}")
                        lines.append(r["content"][:150])
                        lines.append("---")
                    case_context = "\n".join(lines)
    except Exception as e:
        print(f"[CHAT_STREAM] Case search failed: {e}")

    # 3. Gmail search (2s budget)
    try:
        msg_lower = request.message.lower()
        email_kw = ["email", "gmail", "inbox", "unread", "message", "mail", "from ",
                    "subject", "sent me", "wrote to", "morning", "summary",
                    "look up", "find", "search", "emails from"]
        if any(k in msg_lower for k in email_kw) and _time_left() > 1.0:
            from app.core.gmail_service import get_morning_summary, search_all_accounts
            search_triggers = ["from ", "find", "search", "look for", "anything from",
                               "emails from", "show me", "look up", "any emails", "have i got"]

            async def _gmail_fetch():
                if any(t in msg_lower for t in search_triggers):
                    results = await search_all_accounts(request.message, max_per_account=5)
                    if results:
                        lines = ["[GMAIL SEARCH]"]
                        for e in results[:5]:
                            sender = e.get("from", "").split("<")[0].strip()
                            lines.append(f"• {sender} — {e['subject']} ({e['date'][:16]})")
                            if e.get("snippet"):
                                lines.append(f"  {e['snippet'][:80]}")
                        return "\n".join(lines)
                else:
                    summary = await get_morning_summary()
                    return f"[GMAIL]\n{summary}" if summary else ""
                return ""

            gmail_context = await asyncio.wait_for(
                _gmail_fetch(), timeout=min(2.0, _time_left())
            )
    except Exception as e:
        print(f"[CHAT_STREAM] Gmail fetch failed: {e}")

    # 4. Calendar (1s budget)
    try:
        cal_kw = ["calendar", "schedule", "today", "appointment", "meeting",
                  "what have i got", "what's on", "diary"]
        if any(k in request.message.lower() for k in cal_kw) and _time_left() > 0.5:
            from app.core.calendar_service import get_todays_schedule
            from app.core.gmail_service import get_all_accounts
            accounts = get_all_accounts()
            if accounts:
                cal = await asyncio.wait_for(
                    get_todays_schedule(accounts[0]), timeout=1.0
                )
                if cal and "Nothing" not in cal:
                    calendar_context = f"[CALENDAR]\n{cal}"
    except Exception as e:
        print(f"[CHAT_STREAM] Calendar fetch failed: {e}")

    sp = safe_system_prompt(request, search_results)
    if case_context:
        sp += f"\n\n{case_context}"
    if gmail_context:
        sp += f"\n\n{gmail_context}"
    if calendar_context:
        sp += f"\n\n{calendar_context}"

    start = time.time()

    async def gen():
        parts = []
        try:
            stream_fn = _get_stream_fn(
                provider_key, request.message, request.history, sp,
                image_base64=request.image_base64
            )
            async for chunk in stream_fn:
                parts.append(chunk)
                yield "data: " + json.dumps({"type": "chunk", "text": chunk}) + "\n\n"

            full = "".join(parts)
            log_request(
                provider=provider_key, message=request.message,
                reply=full[:500], latency_ms=int((time.time() - start) * 1000), ok=True
            )
            try:
                facts = await extract_and_save_instant_memory(request.message, full)
                for fact in facts:
                    add_memory("auto", fact)
            except Exception as e:
                print(f"[CHAT_STREAM] Memory extraction failed: {e}")

            try:
                from app.core.world_model import tony_reflect_and_update
                asyncio.create_task(tony_reflect_and_update(
                    f"Matthew: {request.message}\nTony: {full[:1000]}"
                ))
            except Exception as e:
                print(f"[CHAT_STREAM] World model update failed: {e}")

            try:
                from app.core.episodic_memory import process_conversation_for_episode
                asyncio.create_task(process_conversation_for_episode(request.message, full))
            except Exception as e:
                print(f"[CHAT_STREAM] Episodic memory failed: {e}")

        except Exception as e:
            print(f"[CHAT_STREAM] Stream error ({provider_key}): {e}")
            yield "data: " + json.dumps({"type": "error", "text": str(e)}) + "\n\n"
            log_request(
                provider=provider_key, message=request.message,
                reply="", latency_ms=int((time.time() - start) * 1000),
                ok=False, error=str(e)
            )

        yield "data: " + json.dumps({"type": "done"}) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
