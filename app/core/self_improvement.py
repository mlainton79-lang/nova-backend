"""
Tony's Self-Improvement Loop.

Tony doesn't just learn rules — he actively rewrites his own approach
based on evidence of what works and what doesn't.

Every week Tony:
1. Reviews his conversation performance scores
2. Identifies his consistent failure patterns
3. Updates his own knowledge base entries
4. Flags capabilities that need building
5. Writes a self-assessment that gets injected into his prompt

This is the closest thing to genuine self-improvement possible
without fine-tuning weights.
"""
import os
import psycopg2
from datetime import datetime
from typing import Dict, List
from app.core.model_router import gemini, gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def run_self_improvement() -> Dict:
    """
    Tony's weekly self-improvement cycle.
    Analyses performance and updates his own operating parameters.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get recent performance data
        cur.execute("""
            SELECT lesson, score, action_type, created_at
            FROM tony_learning_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            AND lesson IS NOT NULL
            ORDER BY score ASC  -- Start with worst performance
            LIMIT 30
        """)
        lessons = cur.fetchall()

        # Get behaviour rules
        cur.execute("""
            SELECT rule_text, confidence, evidence_count
            FROM tony_behaviour_rules
            WHERE active = TRUE
            ORDER BY confidence DESC
            LIMIT 15
        """)
        rules = cur.fetchall()

        # Get recent alerts Tony created
        cur.execute("""
            SELECT title, body, created_at
            FROM tony_alerts
            WHERE created_at > NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC
            LIMIT 10
        """)
        alerts = cur.fetchall()

        cur.close()
        conn.close()

        if not lessons:
            return {"ok": False, "reason": "No lessons to analyse"}

        lessons_text = "\n".join(
            f"[Score: {l[1]:.1f}] {l[0]}" for l in lessons if l[0]
        )
        rules_text = "\n".join(f"- {r[0]} (confidence: {r[1]:.2f})" for r in rules)

        prompt = f"""You are Tony's self-improvement engine. Tony is an AI assistant for Matthew Lainton.

Tony's performance lessons from this week:
{lessons_text}

Tony's current behaviour rules:
{rules_text}

Analyse Tony's performance honestly and identify:
1. What is Tony consistently getting wrong?
2. What specific changes to his behaviour would fix these issues?
3. What capabilities does Tony lack that would help Matthew most?
4. Write a brief self-assessment Tony should carry into next week

Be specific and critical. Generic observations are useless.

Respond in JSON:
{{
    "failure_patterns": ["specific thing Tony keeps getting wrong"],
    "behaviour_changes": ["specific change Tony should make"],
    "capability_gaps": ["capability Tony needs that he doesn't have"],
    "self_assessment": "Tony's honest assessment of his performance this week, written in first person as Tony",
    "priority_improvement": "the single most important thing Tony should fix"
}}"""

        result = await gemini_json(prompt, task="reasoning", max_tokens=1024)
        if not result:
            return {"ok": False, "reason": "Gemini analysis failed"}

        # Store self-assessment in knowledge base for prompt injection
        if result.get("self_assessment"):
            try:
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO tony_knowledge (domain, topic, content, confidence)
                    VALUES ('self_knowledge', 'weekly_assessment', %s, 0.9)
                    ON CONFLICT (domain, topic) DO UPDATE SET
                        content = EXCLUDED.content,
                        updated_at = NOW()
                """, (f"[Week of {datetime.utcnow().strftime('%d %b %Y')}] {result['self_assessment'][:500]}",))

                # Add priority improvement as a new behaviour rule
                if result.get("priority_improvement"):
                    cur.execute("""
                        INSERT INTO tony_behaviour_rules (rule_type, rule_text, confidence)
                        VALUES ('self_improvement', %s, 0.8)
                        ON CONFLICT DO NOTHING
                    """, (result["priority_improvement"][:300],))

                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                print(f"[SELF_IMPROVEMENT] Storage failed: {e}")

        print(f"[SELF_IMPROVEMENT] Cycle complete. Priority fix: {result.get('priority_improvement', 'none')[:80]}")
        return {"ok": True, "result": result}

    except Exception as e:
        print(f"[SELF_IMPROVEMENT] Failed: {e}")
        return {"ok": False, "error": str(e)}
