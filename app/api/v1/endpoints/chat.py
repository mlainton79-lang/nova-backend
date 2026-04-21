"""
Non-streaming chat endpoint.
Matches the streaming endpoint's behaviour — same prompt_assembler,
same post-response tasks, same file handling.
"""
import asyncio
import time
from fastapi import APIRouter, Depends
from app.schemas.chat import ChatRequest, ChatResponse
from app.core.security import verify_token
from app.core.logger import log_request
from app.core.injection_filter import check_injection
from app.providers.openai_adapter import OpenAIAdapter
from app.providers.gemini_adapter import GeminiAdapter
from app.providers.claude_adapter import ClaudeAdapter
from app.providers.groq_adapter import GroqAdapter
from app.providers.mistral_adapter import MistralAdapter
from app.providers.openrouter_adapter import OpenRouterAdapter

router = APIRouter()


async def _build_full_prompt(req: ChatRequest) -> str:
    """Use the same prompt_assembler as chat_stream for consistency."""
    try:
        from app.core.prompt_assembler import build_prompt
        code_kw = ["code", "function", "file", "class", "bug", "error", "fix",
                   "kotlin", "python", "api", "push", "patch", "nova", "build"]
        inc_codebase = any(k in req.message.lower() for k in code_kw)
        return await build_prompt(
            context=req.context,
            location=getattr(req, "location", None),
            document_text=req.document_text,
            document_base64=req.document_base64,
            document_name=req.document_name,
            document_mime=req.document_mime,
            include_codebase=inc_codebase,
            user_message=req.message,
            image_present=bool(req.image_base64)
        )
    except Exception as e:
        print(f"[CHAT] prompt_assembler failed, using fallback: {e}")
        return (
            "You are Tony, Matthew Lainton's personal AI assistant. "
            "British English only. Direct and warm."
        )


async def _post_response_tasks(message: str, reply: str, provider: str):
    """Same post-response work as chat_stream — fires concurrently."""
    async def _instant_memory():
        try:
            from app.core.instant_memory import extract_and_save_instant_memory
            from app.core.memory import add_memory
            facts = await extract_and_save_instant_memory(message, reply)
            for fact in facts:
                add_memory("auto", fact)
        except Exception as e:
            print(f"[CHAT POST] Memory: {e}")

    async def _living_memory():
        try:
            from app.core.living_memory import update_from_conversation
            await update_from_conversation(message, reply)
        except Exception:
            pass

    async def _world_model():
        try:
            from app.core.world_model import update_world_model
            await update_world_model(message, reply)
        except Exception:
            pass

    async def _episodic():
        try:
            from app.core.episodic_memory import process_conversation_for_episode
            await process_conversation_for_episode(message, reply)
        except Exception:
            pass

    async def _learning():
        try:
            from app.core.learning import log_conversation, analyse_conversation_for_learning
            await log_conversation(message, reply, provider)
            await analyse_conversation_for_learning(message, reply, provider)
        except Exception:
            pass

    async def _goals():
        try:
            from app.core.goal_detector import detect_and_create_goal
            await detect_and_create_goal(message, reply)
        except Exception:
            pass

    async def _self_eval():
        try:
            from app.core.self_eval import evaluate_response
            await evaluate_response(message, reply, provider)
        except Exception:
            pass

    async def _fact_extraction():
        try:
            from app.core.fact_extractor import process_conversation_turn
            await process_conversation_turn(message, reply)
        except Exception:
            pass

    async def _fabrication_check():
        try:
            from app.core.fabrication_detector import check_and_log
            await check_and_log(message, reply)
        except Exception:
            pass

    await asyncio.gather(
        _instant_memory(), _living_memory(), _world_model(),
        _episodic(), _learning(), _goals(), _self_eval(),
        _fact_extraction(), _fabrication_check(),
        return_exceptions=True
    )


async def _ingest_document_if_present(
    document_text: str, document_name: str, document_mime: str
):
    """Auto-ingest documents into long-term memory for later semantic search."""
    try:
        if not document_text or len(document_text.strip()) < 100:
            return
        from app.core.document_memory import ingest_document
        # Infer doc_type from mime/name
        doc_type = "unknown"
        if document_mime:
            if "pdf" in document_mime.lower(): doc_type = "pdf"
            elif "image" in document_mime.lower(): doc_type = "image"
            elif "word" in document_mime.lower() or "docx" in (document_name or "").lower(): doc_type = "docx"
            elif "text" in document_mime.lower(): doc_type = "text"
        await ingest_document(
            full_text=document_text,
            doc_name=document_name or "uploaded document",
            doc_type=doc_type,
            source="chat_upload",
        )
    except Exception as e:
        print(f"[DOC_AUTO_INGEST] Failed: {e}")


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _=Depends(verify_token)):
    start = time.time()

    # Retroactive outcome tracking: does this incoming message score the
    # last reply Tony gave? (corrective / clarification / acknowledgement)
    try:
        from app.core.outcome_tracker import record_outcome
        if request.history and len(request.history) >= 2:
            # Last assistant reply is history[-1] (if assistant), user question
            # was history[-2]
            last = request.history[-1]
            prev_user = request.history[-2] if len(request.history) >= 2 else None
            if (last.role == "assistant" and prev_user and prev_user.role == "user"):
                # Fire and forget — record asynchronously
                import asyncio
                asyncio.create_task(asyncio.to_thread(
                    record_outcome,
                    message_id=None,
                    user_message=prev_user.content,
                    assistant_reply=last.content,
                    provider=request.provider,
                    next_user_message=request.message,
                    delay_seconds=None,
                ))
    except Exception as e:
        print(f"[OUTCOMES] Pre-track failed: {e}")

    injected, reason = check_injection(request.message)
    if injected:
        log_request(provider=request.provider, message=request.message,
                    reply="", ok=False, error=reason)
        return ChatResponse(
            ok=False, provider=request.provider,
            reply="I cannot process that message.", error=reason
        )

    provider_key = request.provider.lower().strip()
    if provider_key == "council":
        return ChatResponse(
            ok=True, provider="council",
            reply="Use the /council endpoint for Council mode."
        )

    system_prompt = await _build_full_prompt(request)

    adapters = {
        "claude": ClaudeAdapter,
        "gemini": GeminiAdapter,
        "openai": OpenAIAdapter,
        "groq": GroqAdapter,
        "mistral": MistralAdapter,
        "openrouter": OpenRouterAdapter,
    }
    adapter_cls = adapters.get(provider_key)
    if not adapter_cls:
        return ChatResponse(
            ok=False, provider=provider_key,
            reply="", error=f"Unknown provider: {provider_key}"
        )

    try:
        adapter = adapter_cls()
        if provider_key == "claude":
            reply = await adapter.chat(
                request.message, request.history, system_prompt,
                image_base64=request.image_base64
            )
        else:
            reply = await adapter.chat(
                request.message, request.history, system_prompt
            )

        # Inline self-correction — verifier checks for fabrication, banned content,
        # voice violations. Only calls LLM if heuristics flag real risk (keeps latency low).
        try:
            from app.core.response_verifier import verify_and_correct
            verify_result = await verify_and_correct(request.message, reply)
            if verify_result.get("correction_applied"):
                print(f"[VERIFIER] Corrected reply — risks: {verify_result['risks']}")
                reply = verify_result["reply"]
        except Exception as e:
            print(f"[VERIFIER] Skipped due to error: {e}")

        latency_ms = int((time.time() - start) * 1000)
        log_request(
            provider=provider_key, message=request.message,
            reply=reply[:500], latency_ms=latency_ms, ok=True
        )

        # Fire post-response tasks without blocking the response
        asyncio.create_task(_post_response_tasks(request.message, reply, provider_key))

        # Extract canvas-worthy artifacts (code, tables, lists, email drafts)
        try:
            from app.core.artifact_extractor import extract_artifacts
            artifacts = extract_artifacts(reply, request.message)
        except Exception:
            artifacts = []

        resp = ChatResponse(
            ok=True, provider=provider_key, reply=reply, latency_ms=latency_ms
        )
        # ChatResponse is a Pydantic model — add artifacts via model_dump + construct
        resp_dict = resp.model_dump()
        if artifacts:
            resp_dict["artifacts"] = artifacts
        # Return as dict so artifacts pass through (backward compatible — field ignored by older clients)
        from fastapi.responses import JSONResponse
        return JSONResponse(content=resp_dict)

    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        log_request(
            provider=provider_key, message=request.message,
            reply="", latency_ms=latency_ms, ok=False, error=str(e)
        )
        return ChatResponse(
            ok=False, provider=provider_key,
            reply="Tony is having trouble connecting right now. Please try again or switch provider.",
            error=str(e)
        )
