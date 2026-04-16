import asyncio
import time

async def run_council(message, history, system_prompt, debug=False):
    start = time.time()
    adapters = {}

    try:
        from app.providers.claude_adapter import ClaudeAdapter
        adapters["claude"] = ClaudeAdapter()
    except Exception as e:
        print(f"[COUNCIL] claude init failed: {e}")
    try:
        from app.providers.gemini_adapter import GeminiAdapter
        adapters["gemini"] = GeminiAdapter()
    except Exception as e:
        print(f"[COUNCIL] gemini init failed: {e}")
    try:
        from app.providers.openai_adapter import OpenAIAdapter
        adapters["openai"] = OpenAIAdapter()
    except Exception as e:
        print(f"[COUNCIL] openai init failed: {e}")
    try:
        from app.providers.groq_adapter import GroqAdapter
        adapters["groq"] = GroqAdapter()
    except Exception as e:
        print(f"[COUNCIL] groq init failed: {e}")
    try:
        from app.providers.mistral_adapter import MistralAdapter
        adapters["mistral"] = MistralAdapter()
    except Exception as e:
        print(f"[COUNCIL] mistral init failed: {e}")
    try:
        from app.providers.deepseek_adapter import DeepSeekAdapter
        adapters["deepseek"] = DeepSeekAdapter()
    except Exception as e:
        print(f"[COUNCIL] deepseek init failed: {e}")
    try:
        from app.providers.openrouter_adapter import OpenRouterAdapter
        adapters["openrouter"] = OpenRouterAdapter()
    except Exception as e:
        print(f"[COUNCIL] openrouter init failed: {e}")
    try:
        from app.providers.xai_adapter import XAIAdapter
        adapters["grok"] = XAIAdapter()
    except Exception as e:
        print(f"[COUNCIL] grok init failed: {e}")

    if not adapters:
        return {"ok": False, "provider": "council", "reply": "No AI providers are currently available. Please try again shortly.", "failures": {}, "latency_ms": round((time.time() - start) * 1000)}

    async def safe_call(name, adapter, msg, hist, sp, timeout=50.0):
        try:
            result = await asyncio.wait_for(adapter.chat(msg, hist, sp), timeout=timeout)
            return name, result, None
        except Exception as e:
            print(f"[COUNCIL] {name} failed: {e}")
            return name, None, str(e)

    round1_tasks = [safe_call(n, a, message, history, system_prompt) for n, a in adapters.items()]
    round1_results = await asyncio.gather(*round1_tasks)
    successes = {n: r for n, r, e in round1_results if r is not None}
    failures = {n: e for n, r, e in round1_results if r is None}
    print(f"[COUNCIL] Round 1 — {len(successes)} succeeded, {len(failures)} failed")

    if not successes:
        return {"ok": False, "provider": "council", "reply": "All AI providers are currently busy. Please try again in a moment.", "failures": failures, "latency_ms": round((time.time() - start) * 1000), "error": "All providers failed"}

    if len(successes) == 1:
        name, reply = list(successes.items())[0]
        return {"ok": True, "provider": "council", "reply": reply, "failures": failures or None, "latency_ms": round((time.time() - start) * 1000), "debug": {"deciding_brain": name, "round1": successes, "note": "Only one provider available"} if debug else None}

    preferred_order = ["gemini", "claude", "grok", "openai", "deepseek", "openrouter", "groq", "mistral"]
    deciding = next((p for p in preferred_order if p in successes), list(successes.keys())[0])
    others = {n: r for n, r in successes.items() if n != deciding}
    other_text = "\n".join(f"{n.upper()}: {r}" for n, r in others.items())

    challenge_prompt = f"Question asked: {message}\n\nYour initial response: {successes[deciding]}\n\nOther AI responses:\n{other_text}\n\nIn one sentence, identify the single most important thing missing or wrong in your response."
    _, challenge, _ = await safe_call(deciding, adapters[deciding], challenge_prompt, [], system_prompt, timeout=30.0)
    if not challenge:
        challenge = "Consider whether there are important nuances or details missing from your response."

    round2_tasks = [safe_call(n, adapters[n], f"Original question: {message}\n\nChallenge raised: {challenge}\n\nProvide an improved response addressing this challenge.", [], system_prompt, timeout=50.0) for n in others if n in adapters]
    round2_results = await asyncio.gather(*round2_tasks)
    refined = {n: r for n, r, e in round2_results if r is not None}

    evidence = "ROUND 1 RESPONSES:\n\n" + "\n\n".join(f"{n.upper()}: {r}" for n, r in successes.items())
    evidence += f"\n\nCHALLENGE IDENTIFIED: {challenge}"
    if refined:
        evidence += "\n\nROUND 2 REFINED RESPONSES:\n\n" + "\n\n".join(f"{n.upper()}: {r}" for n, r in refined.items())

    final_prompt = f"Question: {message}\n\n{evidence}\n\nYou are Tony, Matthew's personal AI assistant. Using all the above responses and refinements, produce the single best answer. Speak directly as Tony. Do not mention that multiple AIs were consulted. Be direct, warm, and British."
    _, final_reply, _ = await safe_call(deciding, adapters[deciding], final_prompt, [], system_prompt, timeout=60.0)

    if not final_reply:
        final_reply = (refined.get(list(refined.keys())[0]) if refined else successes.get(deciding) or list(successes.values())[0])

    return {"ok": True, "provider": "council", "reply": final_reply, "failures": failures or None, "latency_ms": round((time.time() - start) * 1000), "debug": {"deciding_brain": deciding, "providers_used": list(successes.keys()), "providers_failed": list(failures.keys()), "round1": successes, "challenge": challenge, "round2_refined": refined} if debug else None}
