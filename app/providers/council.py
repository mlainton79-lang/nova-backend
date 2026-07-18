import asyncio
import importlib
import os
import re
import time


def _provider_failure(exc: Exception, stage: str) -> dict:
    """Token-safe provider failure metadata for Council diagnostics."""
    msg = str(exc) or "(no message)"
    return {
        "stage": stage,
        "error_class": type(exc).__name__,
        "message": msg[:300],
    }


# ---------------------------------------------------------------------------
# Council membership (config-driven)
#
# COUNCIL_MEMBERS env var controls which seats exist, comma/space separated,
# e.g. COUNCIL_MEMBERS=claude,openai,gemini. Unknown names are ignored with a
# warning. Empty/unset falls back to DEFAULT_COUNCIL_MEMBERS. Membership is
# an operational dial — changing seats must never require a code change.
#
# DISABLED_AI_PROVIDERS (see app/core/model_router_smart.py) still applies on
# top of membership: a member listed there keeps its seat but sits dark, and
# is reported as such in the council_health envelope rather than silently
# vanishing.
# ---------------------------------------------------------------------------
_ADAPTER_REGISTRY = {
    "claude": ("app.providers.claude_adapter", "ClaudeAdapter", ("claude",)),
    "gemini": ("app.providers.gemini_adapter", "GeminiAdapter", ("gemini",)),
    "grok": ("app.providers.xai_adapter", "XAIAdapter", ("grok", "xai")),
    "openai": ("app.providers.openai_adapter", "OpenAIAdapter", ("openai",)),
    "deepseek": ("app.providers.deepseek_adapter", "DeepSeekAdapter", ("deepseek",)),
    "openrouter": ("app.providers.openrouter_adapter", "OpenRouterAdapter", ("openrouter",)),
    "groq": ("app.providers.groq_adapter", "GroqAdapter", ("groq",)),
    "mistral": ("app.providers.mistral_adapter", "MistralAdapter", ("mistral",)),
}

DEFAULT_COUNCIL_MEMBERS = ("claude", "openai", "gemini")

# Chair preference among healthy members. Claude produces the best synthesis
# so it chairs when available; otherwise the first healthy member in this
# order takes the seat (chair_reason: first_healthy_in_preference_order).
CHAIR_PREFERENCE = ["claude", "gemini", "groq", "mistral", "openrouter", "openai", "deepseek", "grok"]


def _parse_member_list(value: str) -> list:
    members = []
    for item in re.split(r"[\s,]+", value or ""):
        item = item.strip().lower()
        if not item:
            continue
        if item not in _ADAPTER_REGISTRY:
            print(f"[COUNCIL] ignoring unknown COUNCIL_MEMBERS entry: {item}")
            continue
        if item not in members:
            members.append(item)
    return members


def _council_members() -> list:
    """Resolve configured council membership, defaulting when unset/empty."""
    configured = _parse_member_list(os.environ.get("COUNCIL_MEMBERS", ""))
    return configured if configured else list(DEFAULT_COUNCIL_MEMBERS)


# ---------------------------------------------------------------------------
# Grounding contract (applies to every deliberation prompt)
#
# Council brains receive the same grounded system prompt as solo Tony (rota,
# memories, facts, retrieved context blocks). This contract exists because
# some providers ignore those blocks and confabulate personal specifics —
# observed live: Margot's age invented, sleeping arrangements invented, a
# care home invented in place of "I don't know". The deliberation layer must
# inherit the same epistemics as the voice layer.
# ---------------------------------------------------------------------------
GROUNDING_RULES = (
    "FAMILY AND PERSONAL FACTS: anything about Matthew's family, names, dates, "
    "ages, routines, or personal history must come from the memory/facts blocks "
    "in the system prompt. If a fact is not there, say you don't know or omit "
    "it — never infer, never invent, never 'correct' Matthew with unverified "
    "detail. Getting personal facts wrong is worse than admitting you don't know."
)

CHAIR_GROUNDING_FLAG = (
    "Flag any response that asserts personal or family specifics not present "
    "in the provided context — treat invented personal detail as the most "
    "serious kind of error."
)


def _build_challenge_prompt(ctx_block, message, round1_summary):
    return (
        f"You are chairing a debate between multiple AI systems to find the best answer for Matthew.\n\n"
        f"{GROUNDING_RULES}\n\n"
        f"Recent conversation context, most recent last:\n{ctx_block}\n\n"
        f"Matthew's latest message:\n{message}\n\n"
        f"Here is what each AI said in Round 1:\n\n{round1_summary}\n\n"
        f"Having read all responses, identify in 2-3 sentences: "
        f"(1) what the best insight was across all responses, "
        f"(2) what the single most important thing is that ALL responses missed or got wrong. "
        f"{CHAIR_GROUNDING_FLAG} "
        f"Be specific and direct."
    )


def _build_refine_prompt(name, ctx_block, message, successes, challenge):
    return (
        f"You are in a debate with other AI systems answering a question for Matthew.\n\n"
        f"{GROUNDING_RULES}\n\n"
        f"Recent conversation context, most recent last:\n{ctx_block}\n\n"
        f"Matthew's latest message:\n{message}\n\n"
        f"What you said in Round 1: {successes[name]}\n\n"
        f"What the other AIs said:\n"
        + "\n".join(f"{k.upper()}: {v}" for k, v in successes.items() if k != name)
        + f"\n\nThe chair's challenge: {challenge}\n\n"
        f"Now give your BEST revised answer, directly addressing the challenge. "
        f"Be specific, concrete, and add something the others missed."
    )


def _build_final_prompt(n_successes, ctx_block, message, evidence):
    return (
        f"You have chaired a rigorous debate between {n_successes} AI systems to find the best answer for Matthew.\n\n"
        f"{GROUNDING_RULES}\n\n"
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
        f"- If your system prompt contains [GMAIL], [GMAIL SEARCH], [CASE DOCUMENTS], [CASE: ...], [WEB SEARCH], [BANKING], or similar bracketed context blocks, those are Tony's live retrieved data — speak from them directly. Do NOT deny having access to data that is already in your context. Quote and summarise from it as your own current observation.\n"
        f"- INVERSE: if Matthew asks about live retrieved data and the system prompt does NOT contain the relevant bracketed context block, ignore any specific emails, documents, searches, dates, names, amounts, or subjects claimed in the debate record. Those are unverified — a Round 1 / Round 2 provider invented them. Refuse plainly: 'I can't see your [X] in this context right now.' Do not pass invented specifics through to the final answer.\n"
        f"- The same applies to personal and family facts: if a specific name, age, date, or life detail in the debate record is not backed by the system prompt's memory/facts blocks, drop it rather than repeat it.\n"
        f"- Your entire output will appear as Tony's reply in the chat bubble. Treat it accordingly.\n"
    )


def _build_council_health(members, successes, failures, disabled, chair=None):
    """Per-request health envelope: which seats exist, who answered, who sat dark and why."""
    dark = []
    for name in members:
        if name in successes:
            continue
        if name in disabled:
            dark.append({"name": name, "error_class": "DisabledViaEnv"})
        elif name in failures:
            dark.append({"name": name, "error_class": failures[name].get("error_class", "Unknown")})
        else:
            dark.append({"name": name, "error_class": "Unknown"})
    return {
        "seats": len(members),
        "responded": sum(1 for m in members if m in successes),
        "chair": chair,
        "dark": dark,
    }


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
    init_failures = {}
    disabled = []

    try:
        from app.core.model_router_smart import is_provider_skipped
    except Exception:
        def is_provider_skipped(_provider):
            return False

    members = _council_members()

    for name in members:
        module_path, class_name, skip_aliases = _ADAPTER_REGISTRY[name]
        if any(is_provider_skipped(alias) for alias in skip_aliases):
            disabled.append(name)
            print(f"[COUNCIL] {name} seat dark: listed in DISABLED_AI_PROVIDERS")
            continue
        try:
            module = importlib.import_module(module_path)
            adapters[name] = getattr(module, class_name)()
        except Exception as e:
            init_failures[name] = _provider_failure(e, "init")
            print(f"[COUNCIL] {name} init failed: {type(e).__name__}: {str(e) or '(no message)'}")

    if not adapters:
        return {
            "ok": False,
            "provider": "council",
            "reply": "No AI providers are currently available. Please try again shortly.",
            "failures": init_failures,
            "council_health": _build_council_health(members, {}, init_failures, disabled),
            "latency_ms": round((time.time() - start) * 1000),
        }

    async def safe_call(name, adapter, msg, hist, sp, timeout=50.0):
        try:
            result = await asyncio.wait_for(adapter.chat(msg, hist, sp), timeout=timeout)
            return name, result, None
        except Exception as e:
            failure = _provider_failure(e, "chat")
            print(f"[COUNCIL] {name} failed: {failure['error_class']}: {failure['message']}")
            return name, None, failure

    round1_tasks = [safe_call(n, a, message, history, system_prompt) for n, a in adapters.items()]
    round1_results = await asyncio.gather(*round1_tasks)
    successes = {n: r for n, r, e in round1_results if r is not None}
    failures = {**init_failures, **{n: e for n, r, e in round1_results if r is None}}
    print(f"[COUNCIL] Round 1 — {len(successes)} succeeded, {len(failures)} failed, {len(disabled)} disabled")

    if not successes:
        return {
            "ok": False,
            "provider": "council",
            "reply": "All AI providers are currently busy. Please try again in a moment.",
            "failures": failures,
            "council_health": _build_council_health(members, successes, failures, disabled),
            "latency_ms": round((time.time() - start) * 1000),
            "error": "All providers failed",
        }

    if len(successes) == 1:
        name, reply = list(successes.items())[0]
        return {
            "ok": True,
            "provider": "council",
            "reply": reply,
            "failures": failures or None,
            "council_health": _build_council_health(members, successes, failures, disabled, chair=name),
            "latency_ms": round((time.time() - start) * 1000),
            "debug": {"deciding_brain": name, "chair_reason": "only_seat_responding", "round1": successes, "note": "Only one provider available"} if debug else None,
        }

    deciding = next((p for p in CHAIR_PREFERENCE if p in successes), list(successes.keys())[0])
    others = {n: r for n, r in successes.items() if n != deciding}
    round1_summary = "\n\n".join(f"{n.upper()} said: {r}" for n, r in successes.items())

    # N1.6: shared context block for all three synthesis prompts so short
    # follow-ups like "how?" / "why?" / "do that" don't get treated as
    # standalone questions during chair challenge / refine / final synthesis.
    ctx_block = _recent_context(history)

    challenge_prompt = _build_challenge_prompt(ctx_block, message, round1_summary)
    _, challenge, _ = await safe_call(deciding, adapters[deciding], challenge_prompt, history, system_prompt, timeout=30.0)
    if not challenge:
        challenge = "Consider whether the responses are missing important context, nuance, or practical detail."

    round2_tasks = []
    for n in others:
        if n in adapters:
            refine_prompt = _build_refine_prompt(n, ctx_block, message, successes, challenge)
            round2_tasks.append(safe_call(n, adapters[n], refine_prompt, history, system_prompt, timeout=50.0))

    round2_results = await asyncio.gather(*round2_tasks)
    refined = {n: r for n, r, e in round2_results if r is not None}

    evidence = f"ROUND 1 — Initial responses:\n\n{round1_summary}"
    evidence += f"\n\nCHAIR'S CHALLENGE:\n{challenge}"
    if refined:
        evidence += "\n\nROUND 2 — Refined responses:\n\n"
        evidence += "\n\n".join(f"{n.upper()} refined: {r}" for n, r in refined.items())

    final_prompt = _build_final_prompt(len(successes), ctx_block, message, evidence)
    _, final_reply, _ = await safe_call(deciding, adapters[deciding], final_prompt, history, system_prompt, timeout=60.0)

    if not final_reply:
        final_reply = (refined.get(list(refined.keys())[0]) if refined else successes.get(deciding) or list(successes.values())[0])

    return {
        "ok": True,
        "provider": "council",
        "reply": final_reply,
        "failures": failures or None,
        "council_health": _build_council_health(members, successes, failures, disabled, chair=deciding),
        "latency_ms": round((time.time() - start) * 1000),
        "debug": {
            "deciding_brain": deciding,
            "chair_reason": "first_healthy_in_preference_order",
            "providers_used": list(successes.keys()),
            "providers_failed": list(failures.keys()),
            "providers_disabled": disabled,
            "round1": successes,
            "challenge": challenge,
            "round2_refined": refined,
        } if debug else None,
    }
