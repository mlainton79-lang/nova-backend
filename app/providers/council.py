import asyncio, time
from app.providers.claude_adapter import ClaudeAdapter
from app.providers.openai_adapter import OpenAIAdapter
from app.providers.gemini_adapter import GeminiAdapter

async def run_council(message, history, system_prompt, debug=False):
    start = time.time()
    adapters = {"claude": ClaudeAdapter(), "openai": OpenAIAdapter(), "gemini": GeminiAdapter()}

    async def safe_call(name, adapter, msg, hist):
        try:
            result = await asyncio.wait_for(adapter.chat(msg, hist, system_prompt), timeout=45.0)
            return name, result, None
        except Exception as e:
            return name, None, str(e)

    round1 = await asyncio.gather(*[safe_call(n, a, message, history) for n, a in adapters.items()])
    successes = {n: r for n, r, e in round1 if r}
    failures = {n: e for n, r, e in round1 if not r}

    if not successes:
        return {"ok": False, "provider": "council", "reply": "All providers are currently unavailable.", "failures": failures, "latency_ms": round((time.time()-start)*1000), "error": "All providers failed"}

    if len(successes) == 1:
        return {"ok": True, "provider": "council", "reply": list(successes.values())[0], "failures": failures or None, "latency_ms": round((time.time()-start)*1000)}

    preferred = ["gemini", "openai", "claude"]
    deciding = next((p for p in preferred if p in successes), list(successes.keys())[0])
    others = {n: r for n, r in successes.items() if n != deciding}
    other_text = chr(10).join(f"{n.upper()}: {r}" for n, r in others.items())

    challenge_prompt = f"Reviewing: {message}" + chr(10) + f"Your response: {successes[deciding]}" + chr(10) + f"Others: {other_text}" + chr(10) + "Identify the key weakness. One sharp challenge."
    _, challenge, _ = await safe_call(deciding, adapters[deciding], challenge_prompt, [])
    if not challenge:
        challenge = "Refine your response with additional important details."

    round2 = await asyncio.gather(*[safe_call(n, adapters[n], f"Question: {message}" + chr(10) + f"Challenge: {challenge}" + chr(10) + "Provide an improved response.", []) for n in others if n in adapters])
    refined = {n: r for n, r, e in round2 if r}

    evidence = "ROUND 1:" + chr(10) + chr(10).join(f"{n.upper()}: {r}" for n, r in successes.items())
    evidence += chr(10) + chr(10) + f"CHALLENGE: {challenge}"
    if refined:
        evidence += chr(10) + chr(10) + "ROUND 2:" + chr(10) + chr(10).join(f"{n.upper()}: {r}" for n, r in refined.items())

    final_prompt = f"Question: {message}" + chr(10) + chr(10) + evidence + chr(10) + chr(10) + "Produce the single best answer. Speak as Tony. Do not mention multiple sources."
    _, final_reply, _ = await safe_call(deciding, adapters[deciding], final_prompt, [])
    if not final_reply:
        final_reply = successes.get(deciding) or list(successes.values())[0]

    return {"ok": True, "provider": "council", "reply": final_reply, "debug": {"deciding_brain": deciding, "round1": successes, "challenge": challenge, "round2_refined": refined} if debug else None, "failures": failures or None, "latency_ms": round((time.time()-start)*1000)}
