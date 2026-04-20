"""
Tony's streaming chat endpoint.

Real SSE streaming for Gemini/Claude/Groq/Mistral/OpenRouter/OpenAI.
All context gathered concurrently. Post-response tasks fired as background tasks.
"""
import time
import os
import json
import asyncio
import httpx

from fastapi import APIRouter, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatRequest
from app.core.security import verify_token
from app.core.injection_filter import check_injection
from app.core.logger import log_request

router = APIRouter()

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")


# ── Real streaming generators ─────────────────────────────────────────────────

async def gemini_stream(message: str, history: list, system_prompt: str,
                        image_base64: str = None, image_mime: str = "image/jpeg"):
    """Real SSE streaming from Gemini."""
    contents = []
    for h in history:
        role = h.role if hasattr(h, "role") else h.get("role", "user")
        content = h.content if hasattr(h, "content") else h.get("content", "")
        contents.append({"role": "model" if role == "assistant" else "user",
                         "parts": [{"text": content}]})

    user_parts = []
    if image_base64:
        user_parts.append({"inline_data": {"mime_type": image_mime, "data": image_base64}})
    user_parts.append({"text": message})
    contents.append({"role": "user", "parts": user_parts})

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:streamGenerateContent?alt=sse&key={GEMINI_API_KEY}")

    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST", url,
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": contents,
                "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.7}
            },
            headers={"Content-Type": "application/json"}
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                    for part in (data.get("candidates", [{}])[0]
                                 .get("content", {}).get("parts", [])):
                        text = part.get("text", "")
                        if text:
                            yield text
                except Exception:
                    continue


async def claude_stream(message: str, history: list, system_prompt: str,
                        image_base64: str = None, image_mime: str = "image/jpeg"):
    """Real SSE streaming from Claude."""
    from app.utils.history import to_claude_history
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    messages = to_claude_history(history)

    if image_base64:
        user_content = [
            {"type": "image", "source": {"type": "base64",
             "media_type": image_mime, "data": image_base64}},
            {"type": "text", "text": message}
        ]
    else:
        user_content = message
    messages.append({"role": "user", "content": user_content})

    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST", "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": model, "max_tokens": 8192,
                "system": system_prompt, "messages": messages,
                "stream": True
            }
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                    if data.get("type") == "content_block_delta":
                        text = data.get("delta", {}).get("text", "")
                        if text:
                            yield text
                except Exception:
                    continue


async def openai_stream(message: str, history: list, system_prompt: str):
    """Real SSE streaming from OpenAI."""
    from app.utils.history import to_openai_history
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    messages = [{"role": "system", "content": system_prompt}]
    messages += to_openai_history(history)
    messages.append({"role": "user", "content": message})

    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST", "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": model, "messages": messages,
                  "max_tokens": 8192, "stream": True}
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                    text = (data.get("choices", [{}])[0]
                            .get("delta", {}).get("content", ""))
                    if text:
                        yield text
                except Exception:
                    continue


async def groq_stream(message: str, history: list, system_prompt: str):
    """Real SSE streaming from Groq."""
    from app.utils.history import to_openai_history
    model = os.environ.get("GROQ_MODEL", "llama-4-scout-17b-16e-instruct")
    messages = [{"role": "system", "content": system_prompt}]
    messages += to_openai_history(history)
    messages.append({"role": "user", "content": message})

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST", "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": model, "messages": messages,
                  "max_tokens": 8192, "stream": True}
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                    text = (data.get("choices", [{}])[0]
                            .get("delta", {}).get("content", ""))
                    if text:
                        yield text
                except Exception:
                    continue


async def mistral_stream(message: str, history: list, system_prompt: str):
    """Real SSE streaming from Mistral."""
    from app.utils.history import to_openai_history
    model = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
    messages = [{"role": "system", "content": system_prompt}]
    messages += to_openai_history(history)
    messages.append({"role": "user", "content": message})

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST", "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {MISTRAL_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": model, "messages": messages,
                  "max_tokens": 8192, "stream": True}
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                    text = (data.get("choices", [{}])[0]
                            .get("delta", {}).get("content", ""))
                    if text:
                        yield text
                except Exception:
                    continue


async def openrouter_stream(message: str, history: list, system_prompt: str):
    """Real SSE streaming from OpenRouter."""
    from app.utils.history import to_openai_history
    model = os.environ.get("OPENROUTER_MODEL", "openrouter/auto")
    messages = [{"role": "system", "content": system_prompt}]
    messages += to_openai_history(history)
    messages.append({"role": "user", "content": message})

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST", "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://nova.app",
                "X-Title": "Nova"
            },
            json={"model": model, "messages": messages,
                  "max_tokens": 8192, "stream": True}
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                    text = (data.get("choices", [{}])[0]
                            .get("delta", {}).get("content", ""))
                    if text:
                        yield text
                except Exception:
                    continue


def _get_stream(provider: str, message: str, history: list,
                system_prompt: str, image_base64: str = None):
    """Route to the correct real streaming generator."""
    if provider == "claude":
        return claude_stream(message, history, system_prompt, image_base64=image_base64)
    elif provider == "openai":
        return openai_stream(message, history, system_prompt)
    elif provider == "groq":
        return groq_stream(message, history, system_prompt)
    elif provider == "mistral":
        return mistral_stream(message, history, system_prompt)
    elif provider == "openrouter":
        return openrouter_stream(message, history, system_prompt)
    else:
        return gemini_stream(message, history, system_prompt, image_base64=image_base64)


# ── Context gathering (all concurrent) ───────────────────────────────────────

async def _gather_context(request: ChatRequest) -> dict:
    """Gather all context concurrently — total latency = slowest single fetch."""
    msg_lower = request.message.lower()

    async def _web_search():
        try:
            from app.core.brave_search import should_search, brave_search
            if should_search(request.message):
                return await asyncio.wait_for(brave_search(request.message), timeout=3.0)
        except Exception as e:
            print(f"[CHAT_STREAM] Web search: {e}")
        return ""

    async def _case_search():
        case_kw = ["case", "western circle", "westerncircle", "complaint", "legal",
                   "timeline", "evidence", "claim", "dispute", "ccj"]
        if not any(k in msg_lower for k in case_kw):
            return ""
        try:
            from app.core.rag import list_cases, search_case
            all_cases = list_cases()
            ready = [c for c in all_cases if c["status"] == "ready"]
            if not ready:
                return ""
            target = next((c for c in ready if c["name"].lower() in msg_lower), ready[0])
            results = await asyncio.wait_for(
                search_case(target["id"], request.message, top_k=3), timeout=3.0
            )
            if results:
                lines = [f"[CASE: {target['name']}]"]
                for r in results:
                    lines.append(f"[{r['date'][:16]}] {r['sender'][:40]} — {r['subject'][:50]}")
                    lines.append(r["content"][:200])
                    lines.append("---")
                return "\n".join(lines)
        except Exception as e:
            print(f"[CHAT_STREAM] Case search: {e}")
        return ""

    async def _gmail_search():
        email_kw = ["email", "gmail", "inbox", "unread", "message", "mail",
                    "from ", "subject", "sent me", "wrote", "morning",
                    "look up", "find", "search", "any emails"]
        if not any(k in msg_lower for k in email_kw):
            return ""
        try:
            from app.core.gmail_service import get_morning_summary, search_all_accounts
            search_triggers = ["from ", "find", "search", "look for", "anything from",
                               "emails from", "show me", "look up", "any emails", "have i got"]
            if any(t in msg_lower for t in search_triggers):
                results = await asyncio.wait_for(
                    search_all_accounts(request.message, max_per_account=5), timeout=4.0
                )
                if results:
                    lines = ["[GMAIL SEARCH]"]
                    for e in results[:5]:
                        sender = e.get("from", "").split("<")[0].strip()
                        lines.append(f"• {sender} — {e['subject']} ({e['date'][:16]})")
                        if e.get("snippet"):
                            lines.append(f"  {e['snippet'][:100]}")
                    return "\n".join(lines)
            else:
                summary = await asyncio.wait_for(get_morning_summary(), timeout=4.0)
                return f"[GMAIL]\n{summary}" if summary else ""
        except Exception as e:
            print(f"[CHAT_STREAM] Gmail: {e}")
        return ""

    async def _calendar():
        cal_kw = ["calendar", "schedule", "today", "appointment", "meeting",
                  "what have i got", "what's on", "diary", "shift"]
        if not any(k in msg_lower for k in cal_kw):
            return ""
        try:
            from app.core.calendar_service import get_todays_schedule
            from app.core.gmail_service import get_all_accounts
            accounts = get_all_accounts()
            if accounts:
                cal = await asyncio.wait_for(get_todays_schedule(accounts[0]), timeout=3.0)
                if cal and "Nothing" not in cal:
                    return f"[CALENDAR]\n{cal}"
        except Exception as e:
            print(f"[CHAT_STREAM] Calendar: {e}")
        return ""

    async def _ei():
        try:
            from app.core.emotional_intelligence import tony_read_context
            from datetime import datetime
            return await asyncio.wait_for(
                tony_read_context(request.message, datetime.utcnow().hour), timeout=3.0
            )
        except Exception:
            pass
        return {"adjustment": ""}

    async def _reasoning():
        if request.image_base64:
            return ""
        try:
            from app.core.reasoning import needs_deep_reasoning, reason_through, emotional_check
            parts = []
            if needs_deep_reasoning(request.message):
                thought = await asyncio.wait_for(reason_through(request.message), timeout=8.0)
                if thought:
                    parts.append(f"[CHAIN OF THOUGHT]\n{thought}")
            emotion = await asyncio.wait_for(emotional_check(request.message), timeout=3.0)
            if emotion:
                parts.append(f"[EMOTIONAL CONTEXT]: {emotion}")
            return "\n".join(parts)
        except Exception as e:
            print(f"[CHAT_STREAM] Reasoning: {e}")
        return ""

    async def _causal():
        """Causal reasoning for life/financial/legal decisions."""
        if request.image_base64:
            return ""
        causal_kw = ["should i", "what happens if", "if i do", "what would happen",
                     "consequences", "worth it", "risk of", "what if i",
                     "western circle", "fos complaint", "ccj", "legal action",
                     "financial", "sell the", "quit", "leave"]
        msg_lower = request.message.lower()
        if not any(k in msg_lower for k in causal_kw):
            return ""
        try:
            from app.core.causal_reasoning import causal_analysis
            result = await asyncio.wait_for(
                causal_analysis(request.message), timeout=10.0
            )
            if result and result.get("recommendation"):
                parts = []
                if result.get("root_causes"):
                    parts.append("Root causes: " + "; ".join(result["root_causes"][:2]))
                if result.get("recommendation"):
                    parts.append(f"Causal recommendation: {result['recommendation']}")
                if result.get("reasoning"):
                    parts.append(f"Why: {result['reasoning'][:200]}")
                return "[CAUSAL ANALYSIS]\n" + "\n".join(parts)
        except Exception as e:
            print(f"[CHAT_STREAM] Causal: {e}")
        return ""

    async def _deep_research():
        """Deep research for explicit research requests."""
        if request.image_base64:
            return ""
        research_kw = ["research", "find out about", "look into", "investigate",
                       "what do you know about", "tell me everything about",
                       "deep dive", "thorough", "comprehensive"]
        msg_lower = request.message.lower()
        if not any(k in msg_lower for k in research_kw):
            return ""
        # Only fire for messages long enough to be real research requests
        if len(request.message) < 30:
            return ""
        try:
            from app.core.research import tony_deep_research
            topic = request.message.replace("research", "").replace("look into", "").strip()
            result = await asyncio.wait_for(
                tony_deep_research(topic, depth=2), timeout=15.0
            )
            findings = result.get("findings", "")
            if findings and len(findings) > 100:
                return f"[DEEP RESEARCH: {result.get('sources_read', 0)} sources]\n{findings[:1500]}"
        except Exception as e:
            print(f"[CHAT_STREAM] Deep research: {e}")
        return ""

    results = await asyncio.gather(
        _web_search(), _case_search(), _gmail_search(),
        _calendar(), _ei(), _reasoning(), _causal(), _deep_research(),
        return_exceptions=True
    )

    def safe(r, default=""):
        return r if not isinstance(r, Exception) else default

    return {
        "web": safe(results[0]),
        "case": safe(results[1]),
        "gmail": safe(results[2]),
        "calendar": safe(results[3]),
        "ei": safe(results[4], {"adjustment": ""}),
        "reasoning": safe(results[5]),
        "causal": safe(results[6]),
        "research": safe(results[7]),
    }


# ── Post-response background tasks ────────────────────────────────────────────

async def _post_response_tasks(message: str, reply: str, provider: str):
    """Fire and forget — runs after streaming completes."""
    tasks = []

    async def _memory():
        try:
            from app.core.instant_memory import extract_and_save_instant_memory
            from app.core.memory import add_memory
            facts = await extract_and_save_instant_memory(message, reply)
            for fact in facts:
                add_memory("auto", fact)
        except Exception as e:
            print(f"[POST] Memory: {e}")

    async def _living_memory():
        try:
            from app.core.living_memory import update_from_conversation
            await update_from_conversation(message, reply)
        except Exception as e:
            print(f"[POST] Living memory: {e}")

    async def _world_model():
        try:
            from app.core.world_model import update_world_model
            await update_world_model(message, reply)
        except Exception as e:
            print(f"[POST] World model: {e}")

    async def _episodic():
        try:
            from app.core.episodic_memory import process_conversation_for_episode
            await process_conversation_for_episode(message, reply)
        except Exception as e:
            print(f"[POST] Episodic: {e}")

    async def _learning():
        try:
            from app.core.learning import log_conversation, analyse_conversation_for_learning
            await log_conversation(message, reply, provider)
            await analyse_conversation_for_learning(message, reply, provider)
        except Exception as e:
            print(f"[POST] Learning: {e}")

    async def _patterns():
        try:
            from app.core.pattern_recognition import analyse_message_for_patterns
            from datetime import datetime
            now = datetime.utcnow()
            await analyse_message_for_patterns(message, now.hour, now.weekday())
        except Exception as e:
            print(f"[POST] Patterns: {e}")

    async def _goals():
        try:
            from app.core.goal_detector import detect_and_create_goal
            await detect_and_create_goal(message, reply)
        except Exception as e:
            print(f"[POST] Goals: {e}")

    async def _self_eval():
        try:
            from app.core.self_eval import evaluate_response
            await evaluate_response(message, reply, provider)
        except Exception as e:
            print(f"[POST] Self-eval: {e}")

    await asyncio.gather(
        _memory(), _living_memory(), _world_model(), _episodic(),
        _learning(), _patterns(), _goals(), _self_eval(),
        return_exceptions=True
    )


# ── Main endpoint ─────────────────────────────────────────────────────────────

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, _=Depends(verify_token)):
    start = time.time()
    provider_key = request.provider.lower().strip()

    # Command parser — handle action commands instantly
    try:
        from app.core.command_parser import detect_command, execute_command
        cmd = detect_command(request.message)
        if cmd:
            result_text = await execute_command(cmd)
            if result_text:
                log_request(provider="command", message=request.message,
                            reply=result_text, ok=True)
                async def _cmd_stream():
                    yield "data: " + json.dumps({"type": "chunk", "text": result_text}) + "\n\n"
                    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                return StreamingResponse(_cmd_stream(), media_type="text/event-stream")
    except Exception as e:
        print(f"[CHAT_STREAM] Command parse: {e}")

    # Injection check
    # Topic ban detection — check if Matthew is asking to drop a topic
    try:
        from app.core.topic_bans import detect_topic_ban, store_ban, check_and_clear_if_user_raises_topic
        banned_topic = detect_topic_ban(request.message)
        if banned_topic:
            store_ban(None, banned_topic, request.message[:200])
            print(f"[CHAT_STREAM] Ban stored for topic: {banned_topic}")
        # Also: if Matthew brings up a previously banned topic, clear that ban
        check_and_clear_if_user_raises_topic(request.message, None)
    except Exception as e:
        print(f"[CHAT_STREAM] Topic ban detection: {e}")

    injected, reason = check_injection(request.message)
    if injected:
        async def _blocked():
            yield "data: " + json.dumps({"type": "error", "text": "Blocked."}) + "\n\n"
            yield "data: " + json.dumps({"type": "done"}) + "\n\n"
        return StreamingResponse(_blocked(), media_type="text/event-stream")

    # Gather all context concurrently
    ctx = await _gather_context(request)

    # Build system prompt
    if request.image_base64:
        sp = ("You are Tony, Matthew Lainton's personal AI assistant. "
              "British English. Direct and warm. "
              "Describe what you see and answer the question concisely.")
    else:
        try:
            from app.core.prompt_assembler import build_prompt
            code_kw = ["code", "function", "file", "class", "bug", "error", "fix",
                       "kotlin", "python", "api", "push", "patch", "build", "nova"]
            inc_codebase = any(k in request.message.lower() for k in code_kw)
            sp = await build_prompt(
                context=request.context,
                document_text=request.document_text,
                document_base64=request.document_base64,
                document_name=request.document_name,
                document_mime=request.document_mime,
                include_codebase=inc_codebase,
                user_message=request.message,
                image_present=False
            )
        except Exception as e:
            print(f"[CHAT_STREAM] Prompt assembler: {e}")
            sp = ("You are Tony, Matthew Lainton's personal AI assistant. "
                  "British English. Direct, warm, honest.")

    # Append gathered context to prompt
    for key, label in [("web", "WEB SEARCH"), ("case", "CASE DOCUMENTS"),
                       ("gmail", "GMAIL"), ("calendar", "CALENDAR"),
                       ("causal", "CAUSAL ANALYSIS"), ("research", "DEEP RESEARCH")]:
        if ctx.get(key):
            sp += f"\n\n[{label}]\n{ctx[key]}"

    ei = ctx.get("ei", {})
    if isinstance(ei, dict) and ei.get("adjustment"):
        sp += f"\n\n[RESPONSE ADJUSTMENT]: {ei['adjustment']}"

    if ctx.get("reasoning"):
        sp += (f"\n\n[TONY'S REASONING — use to inform response, "
               f"don't repeat verbatim]\n{ctx['reasoning'][:800]}")

    # Stream response
    async def gen():
        parts = []
        try:
            stream_fn = _get_stream(
                provider_key, request.message, request.history, sp,
                image_base64=request.image_base64
            )
            async for chunk in stream_fn:
                if chunk:
                    parts.append(chunk)
                    yield "data: " + json.dumps({"type": "chunk", "text": chunk}) + "\n\n"

            full = "".join(parts)
            latency = int((time.time() - start) * 1000)
            log_request(provider=provider_key, message=request.message,
                        reply=full[:500], latency_ms=latency, ok=True)

            # Fire post-response tasks without blocking
            asyncio.create_task(_post_response_tasks(request.message, full, provider_key))

        except Exception as e:
            print(f"[CHAT_STREAM] Stream error ({provider_key}): {e}")
            yield "data: " + json.dumps({"type": "error", "text": str(e)}) + "\n\n"
            log_request(provider=provider_key, message=request.message,
                        reply="", latency_ms=int((time.time() - start) * 1000),
                        ok=False, error=str(e))

        yield "data: " + json.dumps({"type": "done"}) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
