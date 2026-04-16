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
        from app.providers.xai_adapter import XAIAdapter
        adapters["grok"] = XAIAdapter()
    except Exception as e:
        print(f"[COUNCIL] grok init failed: {e}")
    try:
        from app.providers.openai_adapter import OpenAIAdapter
        adapters["openai"] = OpenAIAdapter()
    except Exception as e:
        print(f"[COUNCIL] openai init failed: {e}")
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
        from app.providers.groq_adapter import GroqAdapter
        adapters["groq"] = GroqAdapter()
    except Exception as e:
        print(f"[COUNCIL] groq init failed: {e}")
    try:
        from app.providers.mistral_adapter import MistralAdapter
        adapters["mistral"] = MistralAdapter()
    except Exception as e:
        print(f"[COUNCIL] mistral init failed: {e}")

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

    preferred_order = ["claude", "gemini", "grok", "openai", "deepseek", "openrouter", "groq", "mistral"]
    deciding = next((p for p in preferred_order if p in successes), list(successes.keys())[0])
    others = {n: r for n, r in successes.items() if n != deciding}
    round1_summary = "\n\n".join(f"{n.upper()} said: {r}" for n, r in successes.items())

    challenge_prompt = (
        f"You are chairing a debate between multiple AI systems to find the best answer for Matthew.\n\n"
        f"The question was: {message}\n\n"
        f"Here is what each AI said in Round 1:\n\n{round1_summary}\n\n"
        f"Having read all responses, identify in 2-3 sentences: "
        f"(1) what the best insight was across all responses, "
        f"(2) what the single most important thing is that ALL responses missed or got wrong. "
        f"Be specific and direct."
    )
    _, challenge, _ = await safe_call(deciding, adapters[deciding], challenge_prompt, history, system_prompt, timeout=30.0)
    if not challenge:
        challenge = "Consider whether the responses are missing important context, nuance, or practical detail."

    round2_tasks = []
    for n in others:
        if n in adapters:
            refine_prompt = (
                f"You are in a debate with other AI systems answering a question for Matthew.\n\n"
                f"The question was: {message}\n\n"
                f"What you said in Round 1: {successes[n]}\n\n"
                f"What the other AIs said:\n"
                + "\n".join(f"{k.upper()}: {v}" for k, v in successes.items() if k != n)
                + f"\n\nThe chair's challenge: {challenge}\n\n"
                f"Now give your BEST revised answer, directly addressing the challenge. "
                f"Be specific, concrete, and add something the others missed."
            )
            round2_tasks.append(safe_call(n, adapters[n], refine_prompt, history, system_prompt, timeout=50.0))

    round2_results = await asyncio.gather(*round2_tasks)
    refined = {n: r for n, r, e in round2_results if r is not None}

    evidence = f"ROUND 1 — Initial responses:\n\n{round1_summary}"
    evidence += f"\n\nCHAIR'S CHALLENGE:\n{challenge}"
    if refined:
        evidence += "\n\nROUND 2 — Refined responses:\n\n"
        evidence += "\n\n".join(f"{n.upper()} refined: {r}" for n, r in refined.items())

    final_prompt = (
        f"You have just chaired a debate between {len(successes)} AI systems to answer Matthew's question.\n\n"
        f"Matthew asked: {message}\n\n"
        f"The full debate:\n\n{evidence}\n\n"
        f"Now speak as Tony — Matthew's personal AI assistant, named after his late father. "
        f"Direct, warm, honest, British English. "
        f"Synthesise the absolute best answer from the debate. "
        f"Do not mention the debate, the other AIs, or that multiple sources were consulted. "
        f"Just give Matthew the best possible answer as Tony."
    )
    _, final_reply, _ = await safe_call(deciding, adapters[deciding], final_prompt, history, system_prompt, timeout=60.0)

    if not final_reply:
        final_reply = (refined.get(list(refined.keys())[0]) if refined else successes.get(deciding) or list(successes.values())[0])

    return {"ok": True, "provider": "council", "reply": final_reply, "failures": failures or None, "latency_ms": round((time.time() - start) * 1000), "debug": {"deciding_brain": deciding, "providers_used": list(successes.keys()), "providers_failed": list(failures.keys()), "round1": successes, "challenge": challenge, "round2_refined": refined} if debug else None}
