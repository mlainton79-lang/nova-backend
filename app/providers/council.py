import asyncio
import time
from app.providers.claude_adapter import ClaudeAdapter
from app.providers.openai_adapter import OpenAIAdapter
from app.providers.gemini_adapter import GeminiAdapter


def classify_question(message: str) -> str:
    lower = message.lower()
    technical = ["code", "script", "function", "error", "bug", "program", "build", "deploy",
                 "sql", "python", "kotlin", "api", "step by step", "how do i", "install"]
    current_events = ["news", "today", "weather", "latest", "current", "happening", "uk",
                      "price", "score", "result", "election", "market"]
    if any(w in lower for w in technical):
        return "gemini"
    if any(w in lower for w in current_events):
        return "gemini"
    return "gemini"


async def run_council(message, history, system_prompt, debug=False):
    start = time.time()

    claude = ClaudeAdapter()
    openai = OpenAIAdapter()
    gemini = GeminiAdapter()

    adapters = {
        "claude": claude,
        "openai": openai,
        "gemini": gemini
    }

    async def safe_call(name, adapter, msg, hist):
        try:
            result = await asyncio.wait_for(
                adapter.chat(msg, hist, system_prompt),
                timeout=45.0
            )
            return name, result, None
        except Exception as e:
            return name, None, str(e)

    def build_history_context(hist):
        if not hist:
            return ""
        lines = ["CONVERSATION HISTORY:"]
        for h in hist:
            if hasattr(h, 'role'):
                role = h.role
                content = h.content
            else:
                role = h.get("role", "user")
                content = h.get("content", "")
            label = "Matthew" if role == "user" else "Tony"
            lines.append(f"{label}: {content}")
        return "\n".join(lines) + "\n\n"

    history_context = build_history_context(history)

    round1_results = await asyncio.gather(*[
        safe_call(name, adapter, message, history)
        for name, adapter in adapters.items()
    ])

    successes = {}
    failures = {}
    for name, reply, error in round1_results:
        if reply:
            successes[name] = reply
        else:
            failures[name] = error

    if not successes:
        latency_ms = round((time.time() - start) * 1000)
        return {"ok": False, "provider": "council", "reply": "All providers are currently unavailable. Please try again shortly.",
                "failures": failures, "latency_ms": latency_ms,
                "error": "All providers failed"}

    if len(successes) == 1:
        latency_ms = round((time.time() - start) * 1000)
        reply = list(successes.values())[0]
        return {"ok": True, "provider": "council", "reply": reply,
                "failures": failures if failures else None,
                "latency_ms": latency_ms}

    preferred_order = ["gemini", "openai", "claude"]
    deciding_brain = next((p for p in preferred_order if p in successes), list(successes.keys())[0])

    deciding_adapter = adapters[deciding_brain]
    other_names = [n for n in successes if n != deciding_brain]
    other_responses = "\n\n".join([f"{n.upper()}: {successes[n]}" for n in other_names if n in successes])

    challenge_prompt = (
        f"{history_context}"
        f"You are reviewing responses to this question: \"{message}\"\n\n"
        f"Your initial response was:\n{successes.get(deciding_brain, '')}\n\n"
        f"The other providers responded:\n{other_responses}\n\n"
        f"Identify the most important gap, conflict, or weakness. "
        f"Write one sharp challenge to improve the final answer. Be direct. No preamble."
    )

    _, challenge, _ = await safe_call(deciding_brain, deciding_adapter, challenge_prompt, [])

    if not challenge:
        challenge = "Please refine your response with any additional important details."

    round3_prompt = (
        f"{history_context}"
        f"Original question: \"{message}\"\n\n"
        f"Challenge from the deciding brain: {challenge}\n\n"
        f"Provide an improved response addressing this challenge directly."
    )

    round3_results = await asyncio.gather(*[
        safe_call(name, adapters[name], round3_prompt, [])
        for name in other_names if name in adapters
    ])

    refined = {}
    for name, reply, error in round3_results:
        if reply:
            refined[name] = reply

    all_evidence = ["ROUND 1 RESPONSES:"]
    for name, resp in successes.items():
        all_evidence.append(f"{name.upper()}: {resp}")
    all_evidence.append(f"\nCHALLENGE RAISED: {challenge}")
    if refined:
        all_evidence.append("\nROUND 2 REFINED RESPONSES:")
        for name, resp in refined.items():
            all_evidence.append(f"{name.upper()}: {resp}")

    evidence_block = "\n\n".join(all_evidence)

    final_prompt = (
        f"{history_context}"
        f"Question: \"{message}\"\n\n"
        f"{evidence_block}\n\n"
        f"You are the deciding brain. Using all of the above and the full conversation history, "
        f"produce the single best possible answer. Speak in your own voice as Tony. "
        f"Do not mention that multiple sources were consulted."
    )

    _, final_reply, _ = await safe_call(deciding_brain, deciding_adapter, final_prompt, [])

    if not final_reply:
        final_reply = successes.get(deciding_brain) or list(successes.values())[0]

    latency_ms = round((time.time() - start) * 1000)

    debug_data = {
        "deciding_brain": deciding_brain,
        "round1": successes,
        "challenge": challenge,
        "round2_refined": refined
    } if debug else None

    return {
        "ok": True,
        "provider": "council",
        "reply": final_reply,
        "debug": debug_data,
        "failures": failures if failures else None,
        "latency_ms": latency_ms
    }
