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
from app.core.secrets_redact import redact

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
           f"{GEMINI_MODEL}:streamGenerateContent?alt=sse")

    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST", url,
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": contents,
                "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.7}
            },
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": GEMINI_API_KEY,
            }
        ) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise RuntimeError(f"Gemini {response.status_code}: {redact(body.decode('utf-8', 'replace'))[:500]}")
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
            if response.status_code >= 400:
                body = await response.aread()
                raise RuntimeError(f"Claude {response.status_code}: {redact(body.decode('utf-8', 'replace'))[:500]}")
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
    model = os.environ.get("OPENAI_MODEL", "gpt-5.4")
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
            if response.status_code >= 400:
                body = await response.aread()
                raise RuntimeError(f"OpenAI {response.status_code}: {redact(body.decode('utf-8', 'replace'))[:500]}")
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
            if response.status_code >= 400:
                body = await response.aread()
                raise RuntimeError(f"Groq {response.status_code}: {redact(body.decode('utf-8', 'replace'))[:500]}")
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
            if response.status_code >= 400:
                body = await response.aread()
                raise RuntimeError(f"Mistral {response.status_code}: {redact(body.decode('utf-8', 'replace'))[:500]}")
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
            if response.status_code >= 400:
                body = await response.aread()
                raise RuntimeError(f"OpenRouter {response.status_code}: {redact(body.decode('utf-8', 'replace'))[:500]}")
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


async def _try_stream_first_chunk(provider: str, message: str, history: list,
                                   system_prompt: str, image_base64: str = None):
    """Start a provider stream and pull its first chunk so the caller can
    decide whether to commit to this provider or fall back to the next.

    Returns (iterator, first_chunk). Any pre-first-chunk failure surfaces
    as a raised exception:
      - StopAsyncIteration: provider exited cleanly with zero chunks
      - Any other Exception: network error, HTTP 4xx/5xx (via f78e7a8
        RuntimeError wrapper), JSON parse, timeout from an outer
        asyncio.wait_for, cancellation, etc.

    On failure we close the underlying async generator so httpx releases
    its connection immediately rather than waiting for GC.
    """
    stream = _get_stream(provider, message, history, system_prompt,
                         image_base64=image_base64)
    iterator = stream.__aiter__()
    try:
        first_chunk = await iterator.__anext__()
    except BaseException:
        try:
            await stream.aclose()
        except Exception:
            pass
        raise
    return iterator, first_chunk


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
        case_kw = ["case", "complaint", "legal",
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
                    # N1.gmail-fix-A: 15s — search_all_accounts also fans out to 4 accounts
                    search_all_accounts(request.message, max_per_account=5), timeout=15.0
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
                # N1.gmail-fix-A: 15s timeout — get_morning_summary fans out to all
                # connected accounts (4 in current production), each requiring an OAuth
                # refresh + Gmail API call. 4s was too tight after re-auth re-enabled
                # the full account set. Caused silent timeout fallback making Tony say
                # "Gmail's not working" when Gmail was healthy.
                summary = await asyncio.wait_for(get_morning_summary(), timeout=15.0)
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
                     "fos complaint", "legal action",
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

    async def _fact_extraction():
        try:
            from app.core.fact_extractor import process_conversation_turn
            await process_conversation_turn(message, reply)
        except Exception as e:
            print(f"[POST] Fact extraction: {e}")

    async def _fabrication_check():
        try:
            from app.core.fabrication_detector import check_and_log
            await check_and_log(message, reply)
        except Exception as e:
            print(f"[POST] Fabrication check: {e}")

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

    # Smart model routing — pick a primary provider AND a fallback chain
    # when the client asked for 'auto' / 'smart' / empty. Manual provider
    # picks (provider=gemini/claude/etc.) get chain=[that one] with no
    # fallback: if the user named a provider, surface that provider's
    # failure — don't silently swap. Only auto mode gets the graceful
    # fallback behaviour.
    is_auto_mode = provider_key in ("auto", "smart", "")
    chain = [provider_key]  # default for manual mode

    if is_auto_mode:
        try:
            from app.core.model_router_smart import choose_provider
            has_image = bool(getattr(request, "image_base64", None))
            has_doc = bool(request.document_text or request.document_base64)
            doc_len = len(request.document_text or "") if request.document_text else 0
            choice = choose_provider(
                request.message,
                preferred=None,
                has_image=has_image,
                has_document=has_doc,
                document_length=doc_len,
            )
            primary = choice["provider"]
            fallbacks = choice.get("fallbacks", []) or []
            # Ordered-unique chain: primary then fallbacks, dedup preserving
            # order. SKIP_PROVIDERS has already been applied by
            # model_router_smart._apply_skip so no extra filter needed here.
            seen = set()
            chain = [p for p in [primary] + list(fallbacks)
                     if p and not (p in seen or seen.add(p))]
            provider_key = primary  # preserved for failure-path log_request
            print(f"[SMART_ROUTER] chain={chain}: {choice['rationale']}")
        except Exception as e:
            print(f"[SMART_ROUTER] Failed (using gemini-only): {e}")
            chain = ["gemini"]
            provider_key = "gemini"

    # N1.email-draft-A.fix: Pending Action Router runs FIRST so a numeric
    # reply to "which email?" resolves to the chosen candidate before regex
    # dispatch or LLM gets a look at the message.
    try:
        from app.core.command_parser import _check_pending_action
        pending_response = await _check_pending_action(request.message)
        if pending_response:
            log_request(provider="pending_action", message=request.message,
                        reply=pending_response, ok=True)
            async def _pending_stream():
                yield "data: " + json.dumps({"type": "chunk", "text": pending_response}) + "\n\n"
                yield "data: " + json.dumps({"type": "done"}) + "\n\n"
            return StreamingResponse(_pending_stream(), media_type="text/event-stream")
    except Exception as e:
        print(f"[CHAT_STREAM] Pending action check: {e}")

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

    # Capability gap detection — if Matthew wants something Tony doesn't have yet,
    # start building it in the background and acknowledge immediately
    try:
        from app.core.gap_detector import detect_capability_gap, start_autonomous_build
        gap = await detect_capability_gap(request.message)
        if gap and gap.get("capability_name"):
            request_id = await start_autonomous_build(
                gap["capability_name"], gap["description"], request.message
            )
            if request_id > 0:
                ack = (
                    f"Not something I can do yet, but I'll build it now. "
                    f"Going to work on: {gap['description']}. "
                    f"Give me a few minutes — I'll tell you when it's live. "
                    f"Carry on, ask me something else if you want."
                )
                log_request(provider="gap_detector", message=request.message,
                            reply=ack, ok=True)
                async def _gap_stream():
                    yield "data: " + json.dumps({"type": "chunk", "text": ack}) + "\n\n"
                    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                return StreamingResponse(_gap_stream(), media_type="text/event-stream")
            elif request_id == -2:
                # N1.5-A: gap_detector refused — capability builder is in safe mode.
                # Be honest with Matthew rather than implying a build is happening.
                refusal = (
                    "That sounds like something I'd need to build. "
                    "Self-build is locked off for now, so I won't spin the builder up. "
                    "Tell me the end result you want and I'll work around it with what I already have."
                )
                log_request(provider="gap_detector", message=request.message,
                            reply=refusal, ok=True)
                async def _refused_stream():
                    yield "data: " + json.dumps({"type": "chunk", "text": refusal}) + "\n\n"
                    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                return StreamingResponse(_refused_stream(), media_type="text/event-stream")
    except Exception as e:
        print(f"[CHAT_STREAM] Gap detection: {e}")

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
            from app.core.prompt_assembler import build_prompt, _wants_codebase
            inc_codebase = _wants_codebase(request.message)
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
    # Budget for pre-first-chunk time across the entire fallback chain.
    # Per-provider httpx timeouts are long (300s) so a generation can run
    # freely once content starts flowing — this 30s cap only governs how
    # long we'll wait cycling through dead providers before surfacing the
    # error. 30s is enough for 2-3 realistic attempts even with slow
    # providers and keeps the UX snappy when a chain is genuinely stuck.
    CHAIN_FIRST_CHUNK_BUDGET = 30.0

    async def gen():
        parts = []
        actual_provider = None
        try:
            if not chain:
                raise RuntimeError("empty provider chain")

            iterator = None
            first_chunk = None
            errors = []
            chain_start = time.time()

            for i, candidate in enumerate(chain):
                elapsed = time.time() - chain_start
                remaining = CHAIN_FIRST_CHUNK_BUDGET - elapsed
                if remaining <= 0:
                    errors.append(
                        f"<budget {CHAIN_FIRST_CHUNK_BUDGET:.0f}s exhausted "
                        f"before trying {candidate}>"
                    )
                    raise RuntimeError(
                        f"chain exhausted budget after attempts: {errors}"
                    )

                try:
                    iterator, first_chunk = await asyncio.wait_for(
                        _try_stream_first_chunk(
                            candidate, request.message, request.history, sp,
                            request.image_base64,
                        ),
                        timeout=remaining,
                    )
                    actual_provider = candidate
                    break
                except StopAsyncIteration:
                    err = f"{candidate}: produced no chunks"
                    errors.append(err)
                    if is_auto_mode and i < len(chain) - 1:
                        print(f"[CHAT_STREAM] auto: {candidate} produced no chunks, trying {chain[i+1]}")
                        continue
                    raise RuntimeError(err)
                except asyncio.TimeoutError:
                    err = f"{candidate}: first-chunk timeout"
                    errors.append(err)
                    if is_auto_mode and i < len(chain) - 1:
                        print(f"[CHAT_STREAM] auto: {candidate} timed out (first-chunk), trying {chain[i+1]}")
                        continue
                    raise RuntimeError(err)
                except Exception as e:
                    err = f"{candidate}: {type(e).__name__}: {redact(str(e))[:300]}"
                    errors.append(err)
                    if is_auto_mode and i < len(chain) - 1:
                        print(f"[CHAT_STREAM] auto: {candidate} failed ({err}), trying {chain[i+1]}")
                        continue
                    raise

            # First-chunk commitment point: we now have a working provider.
            # Emit the provider event with whoever actually succeeded (not
            # necessarily the primary the router picked) and flush the
            # first chunk we already pulled.
            yield "data: " + json.dumps({"type": "provider", "name": actual_provider}) + "\n\n"
            if first_chunk:
                parts.append(first_chunk)
                yield "data: " + json.dumps({"type": "chunk", "text": first_chunk}) + "\n\n"

            async for chunk in iterator:
                if chunk:
                    parts.append(chunk)
                    yield "data: " + json.dumps({"type": "chunk", "text": chunk}) + "\n\n"

            full = "".join(parts)
            latency = int((time.time() - start) * 1000)
            log_request(provider=actual_provider, message=request.message,
                        reply=full[:500], latency_ms=latency, ok=True)

            # Fire post-response tasks without blocking. Use actual_provider
            # so telemetry (learning, self-eval, outcome tracking) reflects
            # who actually produced the reply, not the router's first pick.
            asyncio.create_task(_post_response_tasks(request.message, full, actual_provider))

            # Auto-ingest document OR image content to long-term memory
            async def _ingest_doc():
                try:
                    from app.core.document_memory import ingest_document
                    doc_text = request.document_text or ""
                    
                    # Case 1: Direct document text
                    if doc_text and len(doc_text.strip()) >= 100:
                        doc_type = "unknown"
                        mime = (request.document_mime or "").lower()
                        if "pdf" in mime: doc_type = "pdf"
                        elif "image" in mime: doc_type = "image"
                        elif "word" in mime or "docx" in (request.document_name or "").lower(): doc_type = "docx"
                        elif "text" in mime: doc_type = "text"
                        await ingest_document(
                            full_text=doc_text,
                            doc_name=request.document_name or "uploaded document",
                            doc_type=doc_type,
                            source="chat_stream_upload",
                        )
                        return
                    
                    # Case 2: Image uploaded — reply contains extracted content
                    if request.image_base64 and full and len(full.strip()) >= 100:
                        user_lower = (request.message or "").lower()
                        reading_intent = any(p in user_lower for p in [
                            "what's this", "whats this", "what does this", "read this",
                            "what's it say", "whats it say", "describe", "translate",
                            "transcribe", "what is this", "whats in the", "what is in"
                        ])
                        if reading_intent:
                            from datetime import datetime
                            doc_text = f"User asked: {request.message}\n\nExtracted content:\n{full}"
                            await ingest_document(
                                full_text=doc_text,
                                doc_name=f"Image captured {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
                                doc_type="image",
                                source="vision_extraction",
                            )
                except Exception as e:
                    print(f"[DOC_AUTO_INGEST] Failed: {e}")
            asyncio.create_task(_ingest_doc())

        except Exception as e:
            safe_error = redact(str(e))
            print(f"[CHAT_STREAM] Stream error ({provider_key}): {safe_error}")
            yield "data: " + json.dumps({"type": "error", "text": safe_error}) + "\n\n"
            log_request(provider=provider_key, message=request.message,
                        reply="", latency_ms=int((time.time() - start) * 1000),
                        ok=False, error=safe_error)

        yield "data: " + json.dumps({"type": "done"}) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
