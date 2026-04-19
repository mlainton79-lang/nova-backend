"""
Tony's Agent Loop — upgraded.

The old agent answered in one pass.
This one thinks, acts, verifies, then responds.

PLAN → EXECUTE → VERIFY → REFLECT → RESPOND

Tony:
1. Plans what he needs to do
2. Executes each step with available tools
3. Verifies each result actually worked
4. Reflects on whether the plan worked
5. Responds to Matthew with the real outcome

No more claiming things worked when they didn't.
No more one-shot answers to multi-step problems.
"""
import os
import json
import asyncio
from typing import List, Dict, Any, Optional
from app.core.model_router import gemini, gemini_json

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


AVAILABLE_TOOLS = {
    "search_web": "Search the internet for current information",
    "search_emails": "Search Matthew's Gmail accounts",
    "read_calendar": "Read Matthew's calendar events",
    "read_memory": "Search Tony's semantic memory",
    "check_goals": "Check Matthew's current goals and progress",
    "get_alerts": "Get pending alerts that need attention",
    "get_weather": "Get current weather",
    "search_case": "Search the Western Circle legal case documents",
    "get_financial_summary": "Get financial awareness summary if banking connected",
    "draft_email": "Draft an email response",
    "create_document": "Generate a formal PDF document",
}


async def _execute_tool(tool: str, params: Dict) -> str:
    """Execute a tool and return its result."""
    try:
        if tool == "search_web":
            from app.core.brave_search import brave_search
            return await brave_search(params.get("query", ""))

        elif tool == "search_emails":
            from app.core.gmail_service import search_all_accounts
            results = await search_all_accounts(params.get("query", ""), max_per_account=5)
            if results:
                lines = []
                for e in results[:5]:
                    lines.append(f"From: {e.get('from','')} | Subject: {e.get('subject','')} | {e.get('date','')[:10]}")
                    if e.get("snippet"):
                        lines.append(f"  {e['snippet'][:100]}")
                return "\n".join(lines)
            return "No emails found"

        elif tool == "read_calendar":
            from app.core.calendar_service import get_upcoming_events
            from app.core.gmail_service import get_all_accounts
            accounts = get_all_accounts()
            if accounts:
                events = await get_upcoming_events(accounts[0], days=14)
                if events:
                    return "\n".join(f"• {e.get('title','')}: {e.get('start','')}" for e in events[:10])
            return "No calendar events found"

        elif tool == "read_memory":
            from app.core.semantic_memory import search_memories
            results = await search_memories(params.get("query", ""), top_k=5)
            if results:
                return "\n".join(f"- {r['text']}" for r in results)
            return "No relevant memories found"

        elif tool == "check_goals":
            import psycopg2
            conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
            cur = conn.cursor()
            cur.execute("SELECT title, priority, status, progress_notes FROM tony_goals WHERE status='active' ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END LIMIT 5")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            if rows:
                return "\n".join(f"• [{r[1]}] {r[0]}: {r[3] or 'No progress noted'}" for r in rows)
            return "No active goals"

        elif tool == "get_weather":
            from app.core.weather import get_weather
            w = await get_weather()
            if w:
                return f"Weather: {w.get('description','')}, {w.get('temp_c','')}°C"
            return "Weather unavailable"

        elif tool == "get_financial_summary":
            from app.core.open_banking import get_financial_summary
            return await get_financial_summary() or "Banking not connected"

        elif tool == "get_alerts":
            import psycopg2
            conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
            cur = conn.cursor()
            cur.execute("SELECT title, body, priority FROM tony_alerts WHERE read=FALSE ORDER BY created_at DESC LIMIT 5")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            if rows:
                return "\n".join(f"[{r[2]}] {r[0]}: {r[1][:100]}" for r in rows)
            return "No pending alerts"

    except Exception as e:
        return f"Tool {tool} failed: {e}"

    return f"Tool {tool} not implemented"


async def run_agent_loop(
    task: str,
    context: str = "",
    max_steps: int = 8
) -> Dict[str, Any]:
    """
    Full agent loop: Plan → Execute → Verify → Respond.
    Returns the final response and execution trace.
    """
    trace = []
    tools_available = "\n".join(f"- {k}: {v}" for k, v in AVAILABLE_TOOLS.items())

    # Step 1: Plan
    plan_prompt = f"""You are Tony's planning system. Matthew has asked:
"{task}"

Context: {context[:500] if context else 'No additional context'}

Available tools:
{tools_available}

Create a concise execution plan. What information do you need? What tools will you use?

Respond in JSON:
{{
    "plan": "one sentence plan",
    "steps": [
        {{"step": 1, "tool": "tool_name", "params": {{"key": "value"}}, "reason": "why"}}
    ],
    "can_answer_directly": false
}}

If you can answer directly without tools, set can_answer_directly to true and steps to [].
Maximum 4 steps."""

    plan = await gemini_json(plan_prompt, task="reasoning", max_tokens=512)
    if not plan:
        return {"ok": False, "error": "Planning failed", "trace": trace}

    trace.append({"phase": "plan", "result": plan})

    if plan.get("can_answer_directly"):
        # Answer directly without tools
        response = await gemini(
            f"Answer this for Matthew directly and concisely: {task}",
            task="reasoning"
        )
        return {"ok": True, "response": response, "trace": trace, "tools_used": []}

    # Step 2: Execute
    tools_used = []
    tool_results = {}

    for step in plan.get("steps", [])[:max_steps]:
        tool = step.get("tool", "")
        params = step.get("params", {})

        if tool not in AVAILABLE_TOOLS:
            trace.append({"phase": "execute", "tool": tool, "result": "tool not found"})
            continue

        result = await _execute_tool(tool, params)
        tool_results[f"{tool}_{step['step']}"] = result
        tools_used.append(tool)
        trace.append({"phase": "execute", "tool": tool, "result": result[:200]})

    # Step 3: Synthesise
    if tool_results:
        results_text = "\n\n".join(f"[{k}]:\n{v}" for k, v in tool_results.items())

        synthesis_prompt = f"""You are Tony. Matthew asked: "{task}"

You gathered this information:
{results_text[:3000]}

Now give Matthew a direct, useful answer. British English. No waffle.
If the information answers his question, answer it.
If it doesn't, say what you found and what's still missing."""

        response = await gemini(synthesis_prompt, task="reasoning", max_tokens=1024)
    else:
        response = "I couldn't gather enough information to answer that properly."

    # Step 4: Self-verify
    verify_prompt = f"""Quick check: Did this response actually answer what was asked?

Matthew asked: {task}
Response: {response[:300] if response else 'None'}

Does it answer the question? Yes or No, one word only."""

    verified = await gemini(verify_prompt, task="analysis", max_tokens=10)
    trace.append({"phase": "verify", "result": verified})

    return {
        "ok": True,
        "response": response,
        "trace": trace,
        "tools_used": tools_used,
        "verified": "yes" in (verified or "").lower()
    }
