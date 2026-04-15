import time
import os
import httpx
from fastapi import APIRouter, Depends
from app.schemas.chat import ChatRequest, ChatResponse
from app.core.security import verify_token
from app.prompts.tony import build_system_prompt
from app.providers.openai_adapter import OpenAIAdapter
from app.providers.gemini_adapter import GeminiAdapter
from app.providers.claude_adapter import ClaudeAdapter
from app.core.logger import log_request
from app.core.injection_filter import check_injection
from app.core.instant_memory import extract_and_save_instant_memory
from app.core.memory import add_memory
from app.core.auto_push import process_auto_push

router = APIRouter()

PROVIDERS = {
    "openai": OpenAIAdapter(),
    "gemini": GeminiAdapter(),
    "claude": ClaudeAdapter(),
}

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")


async def handle_vision_claude(image_base64: str, message: str, system_prompt: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    vision_model = os.environ.get("ANTHROPIC_VISION_MODEL", ANTHROPIC_MODEL)
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": vision_model,
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_base64,
                        },
                    },
                    {"type": "text", "text": message},
                ],
            }
        ],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


async def handle_vision_gemini(image_base64: str, message: str, system_prompt: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_base64
                        }
                    },
                    {"text": message}
                ]
            }
        ],
        "generationConfig": {"maxOutputTokens": 2048}
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=body, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("Gemini vision returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = " ".join(p.get("text", "") for p in parts if "text" in p).strip()
        if not text:
            raise ValueError("Gemini vision returned empty text")
        return text


async def handle_vision(image_base64: str, message: str, system_prompt: str) -> str:
    try:
        return await handle_vision_claude(image_base64, message, system_prompt)
    except Exception as claude_err:
        print(f"[VISION] Claude failed ({claude_err}), trying Gemini")
        return await handle_vision_gemini(image_base64, message, system_prompt)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _=Depends(verify_token)):
    provider_key = request.provider.lower().strip()

    injected, reason = check_injection(request.message)
    if injected:
        log_request(provider=provider_key, message=request.message, reply="", ok=False, error=reason)
        return ChatResponse(ok=False, provider=provider_key, reply="I can't process that message.", error=reason)

    if provider_key == "council":
        return ChatResponse(ok=True, provider="council", reply="Please use the Council endpoint for Council mode.")

    adapter = PROVIDERS.get(provider_key)
    if not adapter:
        return ChatResponse(ok=False, provider=provider_key, reply="", error=f"Unknown provider: {provider_key}. Use openai, gemini, or claude.")

    code_keywords = ["code", "function", "file", "class", "method", "bug", "error", "fix",
                     "refactor", "kotlin", "python", "mainactivity", "backend", "endpoint",
                     "api", "build", "gradle", "def ", "fun ", "kit", "py", "import",
                     "extract_and_save", "instant_memory", "summarise", "council", "chat.py",
                     "memory.py", "tony.py", "router", "adapter", "provider"]
    include_codebase = any(kw in request.message.lower() for kw in code_keywords)

    system_prompt = build_system_prompt(
        context=request.context,
        document_text=request.document_text,
        document_base64=request.document_base64,
        document_name=request.document_name,
        document_mime=request.document_mime,
        include_codebase=include_codebase
    )

    start = time.time()
    try:
        if request.image_base64:
            reply = await handle_vision(request.image_base64, request.message, system_prompt)
        else:
            reply = await adapter.chat(request.message, request.history, system_prompt)

        latency_ms = int((time.time() - start) * 1000)

        reply, push_results = await process_auto_push(reply)
        if push_results:
            print(f"[AUTO_PUSH] {len(push_results)} push(es) attempted: {push_results}")

        try:
            facts = await extract_and_save_instant_memory(request.message, reply)
            for fact in facts:
                add_memory("auto", fact)
        except Exception as e:
            print(f"[MEMORY] extraction failed for {provider_key}: {type(e).__name__}: {str(e)}")

        log_request(provider=provider_key, message=request.message, reply=reply, latency_ms=latency_ms, ok=True)
        return ChatResponse(ok=True, provider=provider_key, reply=reply, latency_ms=latency_ms)

    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        log_request(provider=provider_key, message=request.message, reply="", latency_ms=latency_ms, ok=False, error=str(e))
        return ChatResponse(ok=False, provider=provider_key, reply="Tony is having trouble connecting right now. Please try again or switch provider.", error=str(e))
