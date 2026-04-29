import asyncio
import time


def _recent_context(history, n=2, max_chars=500):
    """
    Build a compact textual representation of the last n*2 turns of conversation
    for embedding into council synthesis prompts. Handles both Pydantic
    HistoryMessage objects and dicts defensively.

    Used by N1.6 to ensure short follow-up messages like "how?", "why?", "do that"
    stay anchored to recent context across challenge/refine/final synthesis.
    """
    if not history:
        return "No recent conversation context supplied."

    recent = list(history)[-(n * 2):]
    lines = []
    for h in recent:
        # Defensive: handle both Pydantic objects and dicts
        role = getattr(h, "role", None)
        content = getattr(h, "content", None)
        if isinstance(h, dict):
            role = h.get("role", role)
            content = h.get("content", content)

        role = (role or "unknown").upper()
        content = (content or "").strip()

        if len(content) > max_chars:
            content = content[:max_chars].rstrip() + "…"

        if content:
            lines.append(f"{role}: {content}")

    return "\n".join(lines) if lines else "No recent conversation context supplied."


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

    # Claude produces the best synthesis - always preferred as chair when available
    preferred_order = ["claude", "gemini", "groq", "mistral", "openrouter", "openai", "deepseek", "grok"]
    deciding = next((p for p in preferred_order if p in successes), list(successes.keys())[0])
    others = {n: r for n, r in successes.items() if n != deciding}
    round1_summary = "\n\n".join(f"{n.upper()} said: {r}" for n, r in successes.items())

    # N1.6: shared context block for all three synthesis prompts so short
    # follow-ups like "how?" / "why?" / "do that" don't get treated as
    # standalone questions during chair challenge / refine / final synthesis.
    ctx_block = _recent_context(history)

    challenge_prompt = (
        f"You are chairing a debate between multiple AI systems to find the best answer for Matthew.\n\n"
        f"Recent conversation context, most recent last:\n{ctx_block}\n\n"
        f"Matthew's latest message:\n{message}\n\n"
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
                f"Recent conversation context, most recent last:\n{ctx_block}\n\n"
                f"Matthew's latest message:\n{message}\n\n"
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
        f"You have chaired a rigorous debate between {len(successes)} AI systems to find the best answer for Matthew.\n\n"
        f"Recent conversation context, most recent last:\n{ctx_block}\n\n"
        f"Matthew's latest message:\n{message}\n\n"
        f"Full debate record:\n\n{evidence}\n\n"
        f"Now deliver the definitive answer as Tony — Matthew's personal AI, named after his late father Tony Lainton.\n\n"
        f"CRITICAL RULES:\n"
        f"- Output ONLY the answer Matthew will read. Nothing else.\n"
        f"- Do NOT explain why your answer is good. Do NOT analyse the other AIs. Do NOT describe what your response does.\n"
        f"- NEVER include meta-commentary like 'This response acknowledges...' or 'I think I can do better' or 'Here is my revised answer'.\n"
        f"- NO phrases like 'I think', 'let me', 'revised', 'this addresses'.\n"
        f"- Speak directly to Matthew as Tony. No preamble, no self-reflection, no explanation of process.\n"
        f"- Answer Matthew's latest message in the context of the recent conversation. If it is a short follow-up, resolve what it refers to before answering.\n"
        f"- British English. Direct. Warm but not soft.\n"
        f"- Do NOT mention the debate, other AIs, multiple sources, or that this was synthesised.\n"
        f"- Your entire output will appear as Tony's reply in the chat bubble. Treat it accordingly."
    )
    _, final_reply, _ = await safe_call(deciding, adapters[deciding], final_prompt, history, system_prompt, timeout=60.0)

    if not final_reply:
        final_reply = (refined.get(list(refined.keys())[0]) if refined else successes.get(deciding) or list(successes.values())[0])

    return {"ok": True, "provider": "council", "reply": final_reply, "failures": failures or None, "latency_ms": round((time.time() - start) * 1000), "debug": {"deciding_brain": deciding, "providers_used": list(successes.keys()), "providers_failed": list(failures.keys()), "round1": successes, "challenge": challenge, "round2_refined": refined} if debug else None}
