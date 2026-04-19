"""
Tony's Strategic Advisor Engine.

Tony thinks long-term about Matthew's life, not just immediate tasks.

Every week Tony produces a strategic assessment:
- Where is Matthew financially in 3 months vs 6 months?
- What's the most important thing to focus on?
- What risks are building that Matthew hasn't noticed?
- What opportunities are time-sensitive?
- What should Matthew do THIS week to make the biggest difference?

This is Tony being a genuine advisor, not a task manager.
The output goes into Tony's living memory and system prompt.
"""
import os
import psycopg2
from datetime import datetime
from typing import Dict
from app.core.model_router import gemini, gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def produce_weekly_strategy() -> Dict:
    """
    Tony's weekly strategic assessment of Matthew's life.
    Uses everything he knows to produce actionable priorities.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Gather full picture
        cur.execute("SELECT section, content FROM tony_living_memory WHERE content IS NOT NULL")
        living_memory = dict(cur.fetchall())

        cur.execute("""
            SELECT title, priority, progress_notes
            FROM tony_goals WHERE status = 'active'
            ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END
        """)
        goals = cur.fetchall()

        cur.execute("""
            SELECT title, body FROM tony_alerts
            WHERE read = FALSE AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC LIMIT 5
        """)
        alerts = cur.fetchall()

        cur.execute("""
            SELECT insight_type, title, body FROM tony_insights
            WHERE created_at > NOW() - INTERVAL '7 days'
            ORDER BY confidence DESC LIMIT 5
        """)
        insights = cur.fetchall()

        cur.close()
        conn.close()

        # Build context
        context_parts = []
        for section in ["LIFE_SUMMARY", "FINANCIAL", "LEGAL", "CURRENT_FOCUS", "OPEN_LOOPS"]:
            if section in living_memory and living_memory[section]:
                context_parts.append(f"{section}: {living_memory[section][:200]}")

        goals_text = "\n".join(f"- [{g[1]}] {g[0]}" for g in goals)
        alerts_text = "\n".join(f"- {a[0]}: {a[1][:100]}" for a in alerts)
        insights_text = "\n".join(f"- [{i[0]}] {i[1]}: {i[2][:100]}" for i in insights)

        prompt = f"""Tony is producing his weekly strategic assessment for Matthew.

Matthew's situation:
{chr(10).join(context_parts)}

Active goals:
{goals_text or 'None'}

Recent alerts:
{alerts_text or 'None'}

Recent insights:
{insights_text or 'None'}

Today's date: {datetime.utcnow().strftime('%A %d %B %Y')}

Produce a strategic assessment. Think like a trusted advisor who genuinely cares about Matthew's wellbeing and success.

Consider:
1. Financial trajectory — where is Matthew heading? Is it improving?
2. Legal situation — Western Circle CCJ — what's the most important next step?
3. Income — is the Vinted/eBay side showing promise? What would double it?
4. Nova/Tony — how is this project progressing toward its potential?
5. Family — anything coming up that needs preparation?
6. Risks — what's building in the background that Matthew hasn't noticed?
7. This week's priority — one thing that would make the biggest difference

Be specific, honest, and direct. Not generic advice — advice for Matthew specifically.

Respond in JSON:
{{
    "financial_trajectory": "assessment",
    "legal_priority": "most important legal action this week",
    "income_assessment": "Vinted/eBay progress and what would improve it",
    "nova_progress": "honest assessment of where Tony/Nova is",
    "family_upcoming": "anything family-related that needs attention",
    "hidden_risks": ["risks building that Matthew may not have noticed"],
    "this_week_priority": "THE single most important thing Matthew should do this week",
    "tony_commitment": "what Tony commits to doing autonomously this week"
}}"""

        assessment = await gemini_json(prompt, task="reasoning", max_tokens=1500)

        if assessment:
            # Store in living memory
            try:
                conn = get_conn()
                cur = conn.cursor()
                summary = f"[Week of {datetime.utcnow().strftime('%d %b %Y')}] Priority: {assessment.get('this_week_priority', '')}. Tony commits: {assessment.get('tony_commitment', '')}"
                cur.execute("""
                    INSERT INTO tony_living_memory (section, content)
                    VALUES ('WEEKLY_STRATEGY', %s)
                    ON CONFLICT (section) DO UPDATE SET
                        content = EXCLUDED.content, updated_at = NOW()
                """, (summary[:1000],))
                conn.commit()
                cur.close()
                conn.close()
            except Exception:
                pass

            # Create alert with priority
            if assessment.get("this_week_priority"):
                from app.core.proactive import create_alert
                create_alert(
                    alert_type="weekly_strategy",
                    title="Tony's weekly priority for you",
                    body=assessment["this_week_priority"],
                    priority="high",
                    source="strategic_advisor"
                )

            print(f"[STRATEGY] Weekly assessment complete. Priority: {assessment.get('this_week_priority', '')[:60]}")

        return assessment or {}

    except Exception as e:
        print(f"[STRATEGY] Weekly strategy failed: {e}")
        return {}


async def run_strategic_advisor() -> Dict:
    """Run strategic advisor — weekly cadence."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Check when last run
        cur.execute("""
            SELECT created_at FROM tony_alerts
            WHERE source = 'strategic_advisor'
            ORDER BY created_at DESC LIMIT 1
        """)
        last_run = cur.fetchone()
        cur.close()
        conn.close()

        # Run weekly (every 7 days)
        if last_run:
            from datetime import timedelta
            if datetime.utcnow() - last_run[0].replace(tzinfo=None) < timedelta(days=6):
                print("[STRATEGY] Not yet time for weekly assessment")
                return {}

    except Exception:
        pass

    return await produce_weekly_strategy()
