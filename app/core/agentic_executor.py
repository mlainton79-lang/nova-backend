"""
Agentic Executor — PLAN → ACT → OBSERVE → RE-PLAN loop.

Takes a complex goal, breaks into sub-steps, executes each, observes results,
refines remaining steps, repeats until done or failed.

Available tools (Tony's existing capabilities):
  - web_search: Brave search the internet
  - doc_search: Semantic search Matthew's uploaded documents  
  - fact_lookup: Query the fact store
  - memory_search: Semantic memory search
  - email_triage: Check recent important emails
  - expense_summary: Query spending data
  - diary_read: Read recent diary entries
  - send_message: Draft a message (doesn't send automatically)

Each step produces an observation that informs the next step. Max 8 steps 
before forced termination. Budget-aware.
"""
import os
import json
import httpx
from typing import Dict, List, Optional


AVAILABLE_TOOLS = {
    "web_search": "Search the web via Brave. Input: query string. Returns: top 5 results.",
    "doc_search": "Semantic search Matthew's uploaded documents. Input: query. Returns: relevant chunks.",
    "fact_lookup": "Look up facts about Matthew or family. Input: subject (e.g. 'Matthew', 'Amelia'). Returns: known facts.",
    "memory_search": "Search Tony's semantic memory. Input: query. Returns: relevant memories.",
    "email_triage": "Check recent triaged emails. Input: none. Returns: urgent/unread summary.",
    "expense_summary": "Get spending data. Input: days (int). Returns: total + by-category breakdown.",
    "diary_read": "Read recent diary entries. Input: days (int). Returns: observations, mood, followups.",
    "draft_message": "Draft a reply message in Matthew's voice. Input: recipient, purpose, context. Returns: draft.",
    "unified_search": "Search across ALL memory sources at once (facts, semantic, docs, diary). Best when unsure which source has the info.",
    "think": "Internal reasoning step. Input: thought. Returns: clarified view (no external side-effects).",
    "finish": "Signal goal completed. Input: final summary. Returns: none.",
}


PLANNER_PROMPT = """You are Tony's Planner for a multi-step goal. Break down the goal into clear sub-steps using only the tools available.

Goal: {goal}

Available tools:
{tools}

Return STRICT JSON array of steps:
[
  {{"step": 1, "tool": "tool_name", "input": "specific input", "why": "one-line rationale"}},
  ...
]

Rules:
- Max 6 initial steps. You can re-plan later.
- Each step MUST use a tool from the list.
- Be concrete — not 'research stuff' but 'web_search "best UK savings rates 2026"'
- Final step should usually be 'finish' with a summary.
- Don't fabricate. If you need info to plan, include a step to gather it first.

Output the JSON array only:"""


REPLANNER_PROMPT = """You're continuing a goal. The plan ran some steps and you've seen the results. Decide what to do next.

Original goal: {goal}

Plan so far:
{plan_so_far}

Results so far:
{results}

Based on what we now know, output the NEXT step to take. Or, if the goal is achieved, output a 'finish' step.

Return STRICT JSON for ONE step:
{{"step": N, "tool": "tool_name", "input": "...", "why": "..."}}

Rules:
- Don't repeat a tool+input combination already tried
- If blocked (tool keeps failing), try a different approach or finish with partial result
- If more than 8 total steps run, finish with what you have

Output the JSON for the next step:"""


async def _call_planner_llm(prompt: str, max_tokens: int = 1500) -> Optional[str]:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2}
                }
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            # Budget log
            try:
                from app.core.budget_guard import log_api_call
                log_api_call("gemini-2.5-flash", "agentic_executor",
                             tokens=max_tokens, source="agentic_executor")
            except Exception:
                pass
            return text
    except Exception as e:
        print(f"[AGENTIC] Planner LLM failed: {e}")
        return None


def _extract_json(text: str) -> Optional[str]:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        t = "\n".join(lines).strip()
    return t


async def _execute_tool(tool: str, input_val) -> Dict:
    """Execute a tool and return {ok, result, error}."""
    try:
        if tool == "web_search":
            from app.core.brave_search import brave_search
            results = await brave_search(str(input_val), max_results=5)
            return {"ok": True, "result": results}

        elif tool == "doc_search":
            from app.core.document_memory import search_documents
            results = await search_documents(str(input_val), top_k=3)
            return {"ok": True, "result": results}

        elif tool == "fact_lookup":
            from app.core.fact_extractor import get_facts_about
            results = get_facts_about(str(input_val))
            return {"ok": True, "result": results}

        elif tool == "memory_search":
            from app.core.semantic_memory import search_memories
            results = await search_memories(str(input_val), top_k=5)
            # Return just text
            texts = [m.get("text", "") if isinstance(m, dict) else str(m)
                     for m in results]
            return {"ok": True, "result": texts}

        elif tool == "email_triage":
            from app.core.email_triage import get_smart_digest
            result = await get_smart_digest()
            return {"ok": True, "result": result}

        elif tool == "expense_summary":
            from app.core.receipt_extractor import get_expense_summary
            days = int(input_val) if isinstance(input_val, (int, str)) and str(input_val).isdigit() else 30
            return {"ok": True, "result": get_expense_summary(days=days)}

        elif tool == "diary_read":
            from app.core.tony_diary import get_recent_diary
            days = int(input_val) if isinstance(input_val, (int, str)) and str(input_val).isdigit() else 7
            return {"ok": True, "result": get_recent_diary(days)}

        elif tool == "draft_message":
            # Input could be a dict or string context
            ctx = input_val if isinstance(input_val, dict) else {"purpose": str(input_val)}
            # Simple draft via LLM
            prompt = f"""Draft a short message (2-3 sentences max) in Matthew's voice:
Context: {ctx}
British English, contractions, no pet names, direct. Output just the message."""
            api_key = os.environ.get("GEMINI_API_KEY", "")
            if not api_key:
                return {"ok": False, "error": "No Gemini key"}
            model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                    json={
                        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                        "generationConfig": {"maxOutputTokens": 300, "temperature": 0.4}
                    }
                )
                r.raise_for_status()
                draft = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                return {"ok": True, "result": {"draft": draft}}

        elif tool == "unified_search":
            from app.core.unified_retrieval import unified_search
            results = await unified_search(str(input_val), top_k=8)
            return {"ok": True, "result": results}

        elif tool == "think":
            # Internal reasoning only — no side effects. Just records the thought.
            return {"ok": True, "result": {"thought": str(input_val)}}

        elif tool == "finish":
            return {"ok": True, "result": {"final_summary": str(input_val),
                                            "terminated": True}}

        else:
            return {"ok": False, "error": f"Unknown tool: {tool}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def run_agentic_goal(goal: str, max_steps: int = 8) -> Dict:
    """
    Full PLAN → ACT → OBSERVE → RE-PLAN loop.
    Returns the trace of all steps and final outcome.
    """
    # Budget check
    try:
        from app.core.budget_guard import is_autonomous_allowed
        if not is_autonomous_allowed():
            return {"ok": False, "error": "Budget guard: autonomous work frozen"}
    except Exception:
        pass

    trace = []
    tools_str = "\n".join(f"  {k}: {v}" for k, v in AVAILABLE_TOOLS.items())

    # INITIAL PLAN
    plan_response = await _call_planner_llm(
        PLANNER_PROMPT.format(goal=goal, tools=tools_str)
    )
    if not plan_response:
        return {"ok": False, "error": "Initial plan generation failed", "trace": trace}

    try:
        extracted = _extract_json(plan_response)
        # Find array
        first = extracted.find("[")
        last = extracted.rfind("]")
        if first < 0:
            return {"ok": False, "error": "Could not parse plan JSON", "trace": trace}
        initial_plan = json.loads(extracted[first:last+1])
    except Exception as e:
        return {"ok": False, "error": f"Plan parse failed: {e}", "trace": trace}

    # Execute initial plan
    for step_def in initial_plan[:max_steps]:
        step_num = len(trace) + 1
        if step_num > max_steps:
            break

        tool = step_def.get("tool", "")
        input_val = step_def.get("input", "")
        why = step_def.get("why", "")

        print(f"[AGENTIC] Step {step_num}: {tool}({str(input_val)[:80]})")

        result = await _execute_tool(tool, input_val)
        trace.append({
            "step": step_num,
            "tool": tool,
            "input": str(input_val)[:500],
            "why": why,
            "ok": result.get("ok"),
            "result": result.get("result") if result.get("ok") else None,
            "error": result.get("error"),
        })

        # If finish was called, stop
        if tool == "finish":
            break
        # If tool failed twice with same input, bail
        if not result.get("ok"):
            failures = [t for t in trace if not t["ok"]]
            if len(failures) >= 3:
                trace.append({"step": len(trace) + 1, "tool": "abort",
                              "why": "too many failures", "ok": False})
                break

    # RE-PLAN loop — keep going until finish or max_steps
    while len(trace) < max_steps:
        last_step = trace[-1]
        if last_step.get("tool") in ("finish", "abort"):
            break

        # Ask the planner what's next
        replan_response = await _call_planner_llm(REPLANNER_PROMPT.format(
            goal=goal,
            plan_so_far="\n".join(f"{t['step']}. {t['tool']}({t['input'][:80]}) — {t['why']}"
                                   for t in trace),
            results="\n".join(f"{t['step']}. ok={t['ok']}: {str(t.get('result', t.get('error')))[:300]}"
                              for t in trace[-5:]),
        ))
        if not replan_response:
            break

        try:
            extracted = _extract_json(replan_response)
            first = extracted.find("{")
            last = extracted.rfind("}")
            if first < 0:
                break
            next_step = json.loads(extracted[first:last+1])
        except Exception:
            break

        tool = next_step.get("tool", "")
        input_val = next_step.get("input", "")
        why = next_step.get("why", "")

        print(f"[AGENTIC] Re-plan step {len(trace)+1}: {tool}({str(input_val)[:80]})")

        result = await _execute_tool(tool, input_val)
        trace.append({
            "step": len(trace) + 1,
            "tool": tool,
            "input": str(input_val)[:500],
            "why": why,
            "ok": result.get("ok"),
            "result": result.get("result") if result.get("ok") else None,
            "error": result.get("error"),
        })

        if tool == "finish":
            break

    # Extract final summary
    finish_step = next((t for t in reversed(trace) if t["tool"] == "finish"), None)
    final_summary = (
        finish_step["result"].get("final_summary")
        if finish_step and isinstance(finish_step.get("result"), dict)
        else f"Completed {len(trace)} steps. See trace."
    )

    return {
        "ok": True,
        "goal": goal,
        "steps_taken": len(trace),
        "final_summary": final_summary,
        "trace": trace,
    }
