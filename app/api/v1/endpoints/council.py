import os
import httpx
from fastapi import APIRouter, Depends
from app.schemas.chat import ChatRequest, CouncilResponse
from app.providers.council import run_council
from app.prompts.tony import build_system_prompt
from app.core.security import verify_token
from app.core.logger import log_request
from app.core.injection_filter import check_injection
from app.core.instant_memory import extract_and_save_instant_memory
from app.core.memory import add_memory
from app.core.code_tools import run_code_review, generate_and_apply_fix
from app.core.auto_push import process_auto_push

router = APIRouter()

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
ANTHROPIC_VISION_MODEL = os.environ.get("ANTHROPIC_VISION_MODEL", ANTHROPIC_MODEL)

CODE_KEYWORDS = [
    "code", "function", "file", "class", "method", "bug", "error", "fix",
    "refactor", "kotlin", "python", "mainactivity", "backend", "endpoint",
    "api", "build", "gradle", "def ", "fun ", "kit", "py", "import",
    "extract_and_save", "instant_memory", "summarise", "council", "chat.py",
    "memory.py", "tony.py", "router", "adapter", "provider"
]

REVIEW_TRIGGERS = [
    "review your code", "review the code", "check your code",
    "what's wrong with your code", "find issues", "audit the code",
    "code review", "review yourself", "check yourself"
]

FIX_TRIGGERS = [
    "fix it", "apply the fix", "apply it", "make the fix",
    "go ahead", "do it", "apply", "fix the issue", "fix the problem"
]


async def handle_vision_claude(image_base64: str, message: str, system_prompt: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": ANTHROPIC_VISION_MODEL,
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
        print(f"[VISION] Council: Claude failed ({claude_err}), trying Gemini")
        return await handle_vision_gemini(image_base64, message, system_prompt)


def format_review_response(issues: list) -> str:
    if not issues:
        return "I reviewed the codebase and found no significant issues. Everything looks solid."

    lines = [f"I've reviewed the codebase. Found {len(issues)} issues:\n"]
    for i, issue in enumerate(issues, 1):
        priority = issue.get("priority", "medium").upper()
        auto = " — I can fix this automatically" if issue.get("auto_fixable") else " — needs careful review"
        lines.append(f"**{i}. [{priority}] {issue.get('title')}**")
        lines.append(f"File: `{issue.get('file')}` ")
        lines.append(f"{issue.get('problem')} ")
        lines.append(f"Fix: {issue.get('fix')}{auto}\n")

    critical = [i for i in issues if i.get("priority") == "critical"]
    if critical:
        lines.append(f"The {len(critical)} critical issue(s) need addressing first. Which do you want me to fix?")
    else:
        lines.append("Which of these do you want me to fix first?")

    return "\n".join(lines)


@router.post("/council", response_model=CouncilResponse)
async def council(req: ChatRequest, _=Depends(verify_token)):
    injected, reason = check_injection(req.message)
    if injected:
        log_request(provider="council", message=req.message, reply="", ok=False, error=reason)
        return CouncilResponse(ok=False, provider="council", reply="I can't process that message.", error=reason)

    msg_lower = req.message.lower().strip()

    if any(trigger in msg_lower for trigger in REVIEW_TRIGGERS):
        try:
            issues = await run_code_review()
            reply = format_review_response(issues)
            log_request(provider="council", message=req.message, reply=reply, ok=True)
            return CouncilResponse(ok=True, provider="council", reply=reply)
        except Exception as e:
            return CouncilResponse(ok=False, provider="council", reply=f"Review failed: {str(e)}")

    include_codebase = any(kw in msg_lower for kw in CODE_KEYWORDS)

    system_prompt = build_system_prompt(
        context=req.context,
        document_text=req.document_text,
        document_base64=req.document_base64,
        document_name=req.document_name,
        document_mime=req.document_mime,
        include_codebase=include_codebase
    )

    if req.image_base64:
        try:
            vision_reply = await handle_vision(req.image_base64, req.message, system_prompt)
            try:
                facts = await extract_and_save_instant_memory(req.message, vision_reply)
                for fact in facts:
                    add_memory("auto", fact)
            except Exception as e:
                print(f"[MEMORY] vision extraction failed for council: {type(e).__name__}: {str(e)}")
            log_request(provider="council", message=req.message, reply=vision_reply, ok=True)
            return CouncilResponse(ok=True, provider="council", reply=vision_reply)
        except Exception as e:
            return CouncilResponse(ok=False, provider="council", reply="Council couldn't analyse the image right now.", error=str(e))

    result = await run_council(req.message, req.history, system_prompt, debug=req.debug or False)
    reply = result.get("reply", "")

    reply, push_results = await process_auto_push(reply)
    if push_results:
        print(f"[AUTO_PUSH] Council: {len(push_results)} push(es) attempted: {push_results}")
    result["reply"] = reply

    try:
        facts = await extract_and_save_instant_memory(req.message, reply)
        for fact in facts:
            add_memory("auto", fact)
    except Exception as e:
        print(f"[MEMORY] council extraction failed: {type(e).__name__}: {str(e)}")

    log_request(provider=result.get("provider", "council"), message=req.message, reply=reply, deciding_brain=result.get("provider"))
    return result
