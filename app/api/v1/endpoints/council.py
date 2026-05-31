"""
Tony's Council endpoint.

Multi-brain deliberation: all providers answer, chair challenges, providers refine,
chair synthesises the definitive response as Tony.

Council is inherently synchronous in its rounds — can't stream because round 2
depends on all round 1 responses. Android shows a "Tony is thinking..." state.
"""
import asyncio
import time

from fastapi import APIRouter, Depends
from app.schemas.chat import ChatRequest, CouncilResponse
from app.providers.council import run_council
from app.core.security import verify_token
from app.core.logger import log_request
from app.core.injection_filter import check_injection

router = APIRouter()


async def _gather_council_context(req: ChatRequest) -> dict:
    """Gather all context concurrently — same pattern as chat_stream."""
    msg_lower = req.message.lower()

    async def _web():
        try:
            from app.core.brave_search import should_search, brave_search
            if should_search(req.message):
                return await asyncio.wait_for(brave_search(req.message), timeout=3.0)
        except Exception as e:
            print(f"[COUNCIL] Web search: {e}")
        return ""

    async def _case():
        case_kw = ["case", "complaint", "legal",
                   "timeline", "evidence", "claim", "dispute", ]
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
                search_case(target["id"], req.message, top_k=5), timeout=3.0
            )
            if results:
                lines = [f"[CASE: {target['name']}]"]
                for r in results:
                    lines.append(f"[{r['date'][:16]}] {r['sender'][:40]} — {r['subject'][:50]}")
                    lines.append(r["content"][:200])
                    lines.append("---")
                return "\n".join(lines)
        except Exception as e:
            print(f"[COUNCIL] Case search: {e}")
        return ""

    async def _gmail():
        # Per-account literal "last N emails in <account>" dispatch — runs
        # before the keyword/search filters because the cross-account unread
        # digest (the else branch below) can't answer account-specific asks.
        # Falls through to None on no-match or unresolved account.
        try:
            from app.core.gmail_service import fetch_per_account_literal
            literal = await fetch_per_account_literal(req.message)
            if literal:
                return literal
        except Exception as e:
            print(f"[COUNCIL] Per-account literal: {e}")

        email_kw = ["email", "gmail", "inbox", "unread", "from ", "subject",
                    "sent me", "wrote", "look up", "find", "any emails"]
        if not any(k in msg_lower for k in email_kw):
            return ""
        try:
            from app.core.gmail_service import get_morning_summary, search_all_accounts
            search_triggers = ["from ", "find", "search", "look for", "anything from",
                               "emails from", "show me", "look up"]
            if any(t in msg_lower for t in search_triggers):
                results = await asyncio.wait_for(
                    # N1.gmail-fix-A: 15s — search_all_accounts also fans out to 4 accounts
                    search_all_accounts(req.message, max_per_account=8), timeout=15.0
                )
                if results:
                    lines = ["[GMAIL SEARCH]"]
                    for e in results[:8]:
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
            # Capture the exception class — empty `str(e)` (e.g. asyncio.TimeoutError)
            # would otherwise produce a useless `[COUNCIL] Gmail: ` print and hide
            # the actual failure mode. Also surface to tony_run_events so the next
            # auditor can find this without log scraping.
            err_class = type(e).__name__
            err_msg = str(e) or "(no message)"
            print(f"[COUNCIL] Gmail: {err_class}: {err_msg}")
            try:
                from app.observability import record_run_event, EventSeverity
                record_run_event(
                    event_type="council_gmail_context_failed",
                    severity=EventSeverity.WARNING,
                    subsystem="council.context.gmail",
                    message=f"_gather_council_context.gmail failed: {err_class}",
                    error_class=err_class,
                    error_message=err_msg[:300],
                )
            except Exception:
                pass
        return ""

    async def _reasoning():
        if req.image_base64:
            return ""
        try:
            from app.core.reasoning import needs_deep_reasoning, reason_through, emotional_check
            parts = []
            if needs_deep_reasoning(req.message):
                thought = await asyncio.wait_for(
                    reason_through(req.message), timeout=8.0
                )
                if thought:
                    parts.append(f"[CHAIN OF THOUGHT]\n{thought}")
            emotion = await asyncio.wait_for(emotional_check(req.message), timeout=3.0)
            if emotion:
                parts.append(f"[EMOTIONAL CONTEXT]: {emotion}")
            return "\n".join(parts)
        except Exception as e:
            print(f"[COUNCIL] Reasoning: {e}")
        return ""

    results = await asyncio.gather(
        _web(), _case(), _gmail(), _reasoning(),
        return_exceptions=True
    )

    def safe(r, default=""):
        return r if not isinstance(r, Exception) else default

    return {
        "web": safe(results[0]),
        "case": safe(results[1]),
        "gmail": safe(results[2]),
        "reasoning": safe(results[3]),
    }


async def _post_response_tasks(message: str, reply: str):
    """Fire and forget — all post-response work concurrent."""
    async def _memory():
        try:
            from app.core.instant_memory import extract_and_save_instant_memory
            from app.core.memory import add_memory
            facts = await extract_and_save_instant_memory(message, reply)
            for fact in facts:
                add_memory("auto", fact)
        except Exception as e:
            print(f"[COUNCIL POST] Memory: {e}")

    async def _living():
        try:
            from app.core.living_memory import update_from_conversation
            await update_from_conversation(message, reply)
        except Exception as e:
            print(f"[COUNCIL POST] Living memory: {e}")

    async def _world():
        try:
            from app.core.world_model import update_world_model
            await update_world_model(message, reply)
        except Exception as e:
            print(f"[COUNCIL POST] World model: {e}")

    async def _learning():
        try:
            from app.core.learning import log_conversation
            await log_conversation(message, reply, "council")
        except Exception as e:
            print(f"[COUNCIL POST] Learning: {e}")

    async def _goals():
        try:
            from app.core.goal_detector import detect_and_create_goal
            await detect_and_create_goal(message, reply)
        except Exception as e:
            print(f"[COUNCIL POST] Goals: {e}")

    async def _self_eval():
        try:
            from app.core.self_eval import evaluate_response
            await evaluate_response(message, reply, "council")
        except Exception as e:
            print(f"[COUNCIL POST] Self-eval: {e}")

    async def _fact_extraction():
        try:
            from app.core.fact_extractor import process_conversation_turn
            await process_conversation_turn(message, reply)
        except Exception as e:
            print(f"[COUNCIL POST] Fact extraction: {e}")

    async def _fabrication_check():
        try:
            from app.core.fabrication_detector import check_and_log
            await check_and_log(message, reply)
        except Exception as e:
            print(f"[COUNCIL POST] Fabrication: {e}")

    await asyncio.gather(
        _memory(), _living(), _world(), _learning(), _goals(), _self_eval(),
        _fact_extraction(), _fabrication_check(),
        return_exceptions=True
    )


@router.post("/council", response_model=CouncilResponse)
async def council(req: ChatRequest, _=Depends(verify_token)):
    start = time.time()

    # N1.email-draft-A.fix: Pending Action Router runs FIRST so a numeric
    # reply to "which email?" resolves to the chosen candidate before regex
    # dispatch or Council deliberation gets a look at the message.
    try:
        from app.core.command_parser import _check_pending_action
        pending_response = await _check_pending_action(req.message)
        if pending_response:
            log_request(provider="pending_action", message=req.message,
                        reply=pending_response, ok=True,
                        task_type="pending_action", history=req.history)
            return CouncilResponse(
                ok=True, provider="council", reply=pending_response,
                latency_ms=int((time.time() - start) * 1000)
            )
    except Exception as e:
        print(f"[COUNCIL] Pending action check: {e}")

    # Check for action commands first — don't waste Council on things we can do directly
    try:
        from app.core.command_parser import detect_command, execute_command
        cmd = detect_command(req.message)
        if cmd:
            reply = await execute_command(cmd)
            if reply:
                log_request(provider="council", message=req.message, reply=reply,
                            ok=True, task_type="command", history=req.history)
                return CouncilResponse(
                    ok=True, provider="council", reply=reply,
                    latency_ms=int((time.time() - start) * 1000)
                )
    except Exception as e:
        print(f"[COUNCIL] Command detection: {e}")

    # Capability gap detection — does Matthew want something Tony doesn't have?
    # If so, kick off the build in background and tell him to carry on.
    try:
        from app.core.gap_detector import detect_capability_gap, start_autonomous_build
        gap = await detect_capability_gap(req.message)
        if gap and gap.get("capability_name"):
            request_id = await start_autonomous_build(
                gap["capability_name"],
                gap["description"],
                req.message
            )
            if request_id > 0:
                reply = (
                    f"Not something I can do yet, but I'll build it now. "
                    f"Going to work on: {gap['description']}. "
                    f"Give me a few minutes — I'll tell you when it's live. "
                    f"Carry on, ask me something else if you want."
                )
                log_request(provider="council", message=req.message, reply=reply,
                            ok=True, task_type="gap_detector", history=req.history)
                return CouncilResponse(
                    ok=True, provider="council", reply=reply,
                    latency_ms=int((time.time() - start) * 1000)
                )
            elif request_id == -2:
                # N1.5-A: gap_detector refused — capability builder is in safe mode.
                # Be honest with Matthew rather than implying a build is happening.
                refusal = (
                    "That sounds like something I'd need to build. "
                    "Self-build is locked off for now, so I won't spin the builder up. "
                    "Tell me the end result you want and I'll work around it with what I already have."
                )
                log_request(provider="council", message=req.message, reply=refusal,
                            ok=True, task_type="gap_detector", history=req.history)
                return CouncilResponse(
                    ok=True, provider="council", reply=refusal,
                    latency_ms=int((time.time() - start) * 1000)
                )
    except Exception as e:
        print(f"[COUNCIL] Gap detection: {e}")

    # Topic ban detection — same as chat_stream
    try:
        from app.core.topic_bans import detect_topic_ban, store_ban, check_and_clear_if_user_raises_topic
        banned_topic = detect_topic_ban(req.message)
        if banned_topic:
            store_ban(None, banned_topic, req.message[:200])
            print(f"[COUNCIL] Ban stored for topic: {banned_topic}")
        check_and_clear_if_user_raises_topic(req.message, None)
    except Exception as e:
        print(f"[COUNCIL] Topic ban detection: {e}")

    injected, reason = check_injection(req.message)
    if injected:
        log_request(provider="council", message=req.message, reply="",
                    ok=False, error=reason,
                    task_type="injection_blocked", history=req.history)
        return CouncilResponse(
            ok=False, provider="council",
            reply="I cannot process that message.", error=reason
        )

    # Gather all context concurrently
    ctx = await _gather_council_context(req)

    # Build system prompt
    if req.image_base64:
        system_prompt = (
            "You are Tony, Matthew Lainton's personal AI assistant. "
            "British English. Direct and warm."
        )
    else:
        try:
            from app.core.prompt_assembler import build_prompt, _wants_codebase
            inc_codebase = _wants_codebase(req.message)
            system_prompt = await build_prompt(
                context=req.context,
                location=req.location if hasattr(req, "location") else None,
                document_text=req.document_text,
                document_base64=req.document_base64,
                document_name=req.document_name,
                document_mime=req.document_mime,
                include_codebase=inc_codebase,
                user_message=req.message,
                image_present=False
            )
        except Exception as e:
            print(f"[COUNCIL] Prompt assembler: {e}")
            system_prompt = (
                "You are Tony, Matthew Lainton's personal AI. "
                "British English. Direct, warm, honest."
            )

    # Append gathered context
    for key, label in [("web", "WEB SEARCH"), ("case", "CASE DOCUMENTS"), ("gmail", "GMAIL")]:
        if ctx.get(key):
            system_prompt += f"\n\n[{label}]\n{ctx[key]}"

    if ctx.get("reasoning"):
        system_prompt += (
            f"\n\n[TONY'S REASONING — use to inform response, don't repeat verbatim]\n"
            f"{ctx['reasoning'][:800]}"
        )

    # Layer-2 fabrication guard — short-circuit retrieval-shaped queries
    # whose context block came back empty. Stops fabricating providers
    # (Mistral / OpenRouter) from inventing plausible fake data before
    # the chair ever sees the question. See app/core/retrieval_guard.py
    # and project_council_fabrication.md for the failure-mode history.
    try:
        from app.core.retrieval_guard import check_retrieval_guard
        guard = check_retrieval_guard(req.message, ctx)
    except Exception as e:
        print(f"[COUNCIL] Retrieval guard import/exec failed: {e}")
        guard = None
    if guard:
        deterministic = guard["deterministic_reply"]
        try:
            from app.observability import record_run_event, EventSeverity
            record_run_event(
                event_type="council_short_circuited_empty_context",
                severity=EventSeverity.INFO,
                subsystem="council.guard.fabrication",
                message=(
                    f"short-circuited intent={guard['intent_key']} "
                    f"empty {guard['label']}"
                ),
                metadata={
                    "intent_key": guard["intent_key"],
                    "label": guard["label"],
                    "message_len": len(req.message),
                    "ctx_keys_present": guard["ctx_keys_present"],
                    "endpoint": "council",
                },
            )
        except Exception:
            pass
        log_request(
            provider="retrieval_guard",
            message=req.message,
            reply=deterministic,
            ok=True,
            task_type="guard",
            history=req.history,
        )
        return CouncilResponse(
            ok=True,
            provider="council",
            reply=deterministic,
            latency_ms=int((time.time() - start) * 1000),
        )

    # Vision preprocessing for Council — describe image then inject
    message_for_council = req.message
    if req.image_base64:
        try:
            from app.core.vision import tony_see
            description = await tony_see(
                req.image_base64,
                prompt=f"Describe this image in detail: {req.message}",
                mime_type="image/jpeg"
            )
            if description:
                message_for_council = (
                    f"{req.message}\n\n[Image Tony can see: {description}]"
                )
        except Exception as e:
            print(f"[COUNCIL] Vision: {e}")

    # Filter conversation history through active topic bans.
    # Previous Tony responses may contain banned content that would otherwise
    # poison the new response via conversation history.
    filtered_history = req.history
    try:
        from app.core.prompt_assembler import _get_active_bans, _has_banned_topic
        active_bans = _get_active_bans()
        if active_bans and req.history:
            filtered_history = []
            for h in req.history:
                content = h.get("content", "") if isinstance(h, dict) else str(h)
                # Skip history entries that mention banned topics
                if _has_banned_topic(content, active_bans):
                    continue
                filtered_history.append(h)
            if len(filtered_history) < len(req.history):
                print(f"[COUNCIL] Filtered {len(req.history) - len(filtered_history)} history entries containing banned topics")
    except Exception as e:
        print(f"[COUNCIL] History ban filter: {e}")

    # Run council — inherently multi-round, can't stream
    result = await run_council(
        message_for_council, filtered_history, system_prompt, debug=req.debug or False
    )

    reply = result.get("reply", "")

    # Auto-push code changes if Tony suggested any
    try:
        from app.core.auto_push import process_auto_push
        reply, _ = await process_auto_push(reply)
        result["reply"] = reply
    except Exception:
        pass

    # Inline self-correction
    try:
        from app.core.response_verifier import verify_and_correct
        verify_result = await verify_and_correct(req.message, reply)
        if verify_result.get("correction_applied"):
            print(f"[VERIFIER council] Corrected — risks: {verify_result['risks']}")
            reply = verify_result["reply"]
            result["reply"] = reply
    except Exception as e:
        print(f"[VERIFIER council] Skipped: {e}")

    # Fire post-response tasks without blocking
    asyncio.create_task(_post_response_tasks(req.message, reply))

    latency = int((time.time() - start) * 1000)
    log_request(
        provider=result.get("provider", "council"),
        message=req.message,
        reply=reply,
        latency_ms=latency,
        ok=result.get("ok", True),
        deciding_brain=result.get("provider"),
        full_context=system_prompt,
        task_type="council",
        history=filtered_history,
        metadata={
            "image_present": bool(getattr(req, "image_base64", None)),
            "deciding_brain": result.get("provider"),
            "providers_failed": list((result.get("failures") or {}).keys()),
        },
    )

    return result
