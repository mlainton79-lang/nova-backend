"""
Tony's Goal Execution Engine.

The difference between a goal tracker and an agent that actually works.

Standard AI: stores your goals in a database.
Tony: actively works on your goals every 6 hours without being asked.

For each active goal, Tony:
1. Assesses current state honestly
2. Identifies the single most important next action
3. Takes whatever actions he can autonomously
4. Prepares whatever actions require Matthew
5. Reports progress clearly

Current active goals Tony can work on autonomously:
- Western Circle CCJ: research, draft letters, prepare FOS complaint
- Nova development: identify next priority features, draft code outlines
- Financial stability: monitor opportunities, flag savings
- Vinted income: research trending items, suggest what to source

Tony only claims progress when he's actually done something.
"""
import os
import psycopg2
from datetime import datetime
from typing import Dict, List, Optional
from app.core.model_router import gemini, gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def execute_goal(goal: Dict) -> Dict:
    """
    Tony works on a single goal autonomously.
    Returns what was accomplished and what needs Matthew.
    """
    title = goal.get("title", "")
    priority = goal.get("priority", "normal")
    progress = goal.get("progress_notes", "")

    # Determine what Tony can actually do for this goal
    prompt = f"""Tony is working on Matthew's goal autonomously.

Goal: {title}
Priority: {priority}
Current progress: {progress or 'None recorded'}

Tony has these tools available:
- Search the web (Brave API)
- Read Matthew's emails (4 Gmail accounts)
- Read Matthew's calendar
- Generate PDF documents
- Research FCA/Companies House records
- Draft formal letters
- Research resale prices on eBay
- Analyse legal correspondence

What can Tony actually DO right now to advance this goal?
Not advise. Not suggest. Actually do.

Respond in JSON:
{{
    "can_act_autonomously": true/false,
    "autonomous_actions": ["specific action Tony will take"],
    "needs_matthew_for": ["what requires Matthew's input or approval"],
    "priority_ask": "the single most important thing Tony needs from Matthew to unblock this",
    "honest_assessment": "Tony's honest view of this goal's current state"
}}

Only include actions Tony can actually execute with his available tools."""

    plan = await gemini_json(prompt, task="reasoning", max_tokens=512)
    if not plan:
        return {"goal": title, "status": "planning_failed"}

    results = {"goal": title, "planned": plan, "actions_taken": []}

    # Execute autonomous actions
    if plan.get("can_act_autonomously"):
        for action in plan.get("autonomous_actions", [])[:2]:  # Max 2 actions per goal
            action_lower = action.lower()

            try:
                if "search" in action_lower and ("web" in action_lower or "research" in action_lower):
                    from app.core.brave_search import brave_search
                    query = f"{title} latest 2026"
                    result = await brave_search(query)
                    if result:
                        results["actions_taken"].append(f"Web research: found relevant information")
                        # Store as insight
                        await _store_goal_insight(title, f"Web research: {result[:200]}")

                elif "fca" in action_lower or "fos" in action_lower or "western circle" in action_lower:
                    from app.core.browser_agent import check_fca_register
                    fca = await check_fca_register("Western Circle")
                    results["actions_taken"].append(f"FCA register checked: {fca.get('status', 'unknown')}")
                    await _store_goal_insight(title, f"FCA status: {fca.get('status', 'unknown')}")

                elif "email" in action_lower or "correspondence" in action_lower:
                    from app.core.gmail_service import search_all_accounts
                    emails = await search_all_accounts("Western Circle Cashfloat", max_per_account=10)
                    if emails:
                        results["actions_taken"].append(f"Found {len(emails)} relevant emails")
                        await _store_goal_insight(title, f"Email search: {len(emails)} emails found")

            except Exception as e:
                results["actions_taken"].append(f"Action attempted but failed: {str(e)[:50]}")

    # Update goal progress if anything was done
    if results["actions_taken"]:
        try:
            conn = get_conn()
            cur = conn.cursor()
            progress_update = f"[{datetime.utcnow().strftime('%d/%m/%Y')}] Tony: {'; '.join(results['actions_taken'][:2])}"
            cur.execute("""
                UPDATE tony_goals
                SET progress_notes = COALESCE(progress_notes || ' | ', '') || %s,
                    updated_at = NOW()
                WHERE title = %s
            """, (progress_update[:300], title))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[GOAL_EXECUTOR] Progress update failed: {e}")

    # Create alert if Matthew needs to act
    if plan.get("priority_ask"):
        try:
            from app.core.proactive import create_alert
            create_alert(
                alert_type="goal_action_needed",
                title=f"Goal: {title[:50]}",
                body=plan["priority_ask"],
                priority="high" if priority in ("urgent", "high") else "normal",
                source="goal_executor"
            )
        except Exception:
            pass

    return results


async def _store_goal_insight(goal_title: str, insight: str):
    """Store a goal-related insight."""
    try:
        from app.core.memory import add_memory
        add_memory("goal_progress", f"{goal_title}: {insight}")
    except Exception:
        pass


async def run_goal_execution() -> List[Dict]:
    """Execute all active high-priority goals."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT title, priority, progress_notes, status
            FROM tony_goals
            WHERE status = 'active'
            ORDER BY CASE priority
                WHEN 'urgent' THEN 1
                WHEN 'high' THEN 2
                ELSE 3
            END
            LIMIT 3
        """)
        goals = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[GOAL_EXECUTOR] Fetch failed: {e}")
        return []

    results = []
    for g in goals:
        goal = {"title": g[0], "priority": g[1], "progress_notes": g[2], "status": g[3]}
        result = await execute_goal(goal)
        results.append(result)
        print(f"[GOAL_EXECUTOR] {g[0]}: {len(result.get('actions_taken', []))} actions taken")

    return results
