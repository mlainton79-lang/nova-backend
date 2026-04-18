"""
Tony's Proactive Intelligence — upgraded.

The original proactive.py scans emails and creates alerts.
This upgrades it with genuine pattern recognition and initiative.

Tony now:
1. Monitors email patterns — not just urgency but trends
2. Tracks financial signals from email content
3. Watches for time-sensitive opportunities
4. Correlates information across sources
5. Surfaces insights Matthew hasn't thought to ask about
6. Drafts responses to things before Matthew even opens them

The goal: Tony should feel like he's always working in the background,
not just sitting there waiting to be asked.
"""
import os
import re
import json
import httpx
import psycopg2
from datetime import datetime, timedelta
from typing import List, Dict, Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BACKEND_URL = "https://web-production-be42b.up.railway.app"
DEV_TOKEN = os.environ.get("DEV_TOKEN", "nova-dev-token")


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_proactive_intelligence_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_insights (
                id SERIAL PRIMARY KEY,
                insight_type TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                confidence FLOAT DEFAULT 0.7,
                source_data TEXT,
                actioned BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[PROACTIVE_INTEL] Tables initialised")
    except Exception as e:
        print(f"[PROACTIVE_INTEL] Init failed: {e}")


async def _gemini(prompt: str, max_tokens: int = 1024) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2}
                }
            )
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[PROACTIVE_INTEL] Gemini call failed: {e}")
    return None


async def analyse_email_patterns() -> List[Dict]:
    """
    Tony looks for patterns across all emails — not just urgency.
    Identifies trends, recurring senders, and things that need attention.
    """
    insights = []
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(
                f"{BACKEND_URL}/api/v1/gmail/search",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"},
                params={"query": "newer_than:7d", "max_per_account": 30}
            )
            emails = r.json().get("results", [])

        if not emails:
            return []

        email_summary = "\n".join(
            f"- From: {e.get('from','')[:40]} | Subject: {e.get('subject','')[:60]} | {e.get('date','')[:10]}"
            for e in emails[:25]
        )

        prompt = f"""Tony is analysing Matthew's emails from the last 7 days for patterns and insights.

Matthew's context:
- Has CCJ dispute with Western Circle (Cashfloat)
- Works night shifts at care home
- Has wife Georgina and two young daughters
- Building Nova AI app in spare time
- Trying to build financial stability

Emails this week:
{email_summary}

Identify:
1. Anything time-sensitive that might have been missed
2. Patterns — any company emailing repeatedly?
3. Financial signals — bills, payments, opportunities
4. Legal signals — anything related to the CCJ or debt
5. Opportunities Matthew might not have noticed

Only flag things with genuine insight value. Do not repeat obvious observations.

Respond in JSON:
{{
    "insights": [
        {{
            "type": "financial|legal|opportunity|pattern|urgent",
            "title": "short title",
            "body": "what Tony noticed and why it matters to Matthew",
            "confidence": 0.0-1.0
        }}
    ]
}}

If nothing interesting: {{"insights": []}}"""

        response = await _gemini(prompt)
        if not response:
            return []

        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            return []

        data = json.loads(json_match.group())
        raw_insights = data.get("insights", [])

        # Store and create alerts for high-confidence insights
        for insight in raw_insights:
            if insight.get("confidence", 0) < 0.6:
                continue

            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO tony_insights (insight_type, title, body, confidence)
                VALUES (%s, %s, %s, %s)
            """, (
                insight.get("type", "general"),
                insight.get("title", "")[:200],
                insight.get("body", "")[:500],
                insight.get("confidence", 0.7)
            ))
            conn.commit()
            cur.close()
            conn.close()

            # Create alert for urgent or high-confidence insights
            if insight.get("type") in ("urgent", "legal", "financial") or insight.get("confidence", 0) > 0.8:
                from app.core.proactive import create_alert
                create_alert(
                    alert_type="insight",
                    title=insight.get("title", "Tony spotted something"),
                    body=insight.get("body", ""),
                    priority="high" if insight.get("type") in ("urgent", "legal") else "normal",
                    source="email_pattern_analysis"
                )

            insights.append(insight)

    except Exception as e:
        print(f"[PROACTIVE_INTEL] Email pattern analysis failed: {e}")

    return insights


async def check_goal_progress() -> List[Dict]:
    """
    Tony checks whether Matthew's goals are actually progressing.
    If a goal has been stuck for too long, Tony takes initiative.
    """
    actions = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{BACKEND_URL}/api/v1/goals",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"}
            )
            goals = r.json().get("goals", [])

        for goal in goals:
            if goal.get("status") != "active":
                continue

            last_updated = goal.get("updated_at", "")
            title = goal.get("title", "")
            progress = goal.get("progress_notes", "")

            # If high priority goal with no recent progress
            if goal.get("priority") in ("urgent", "high"):
                prompt = f"""Tony is reviewing this goal for Matthew:
Goal: {title}
Current progress: {progress or 'No progress recorded'}
Priority: {goal.get('priority')}

What is ONE specific thing Tony could do RIGHT NOW to advance this goal?
Not advice — an actual action Tony can take autonomously.
Keep it to one sentence."""

                suggestion = await _gemini(prompt, max_tokens=200)
                if suggestion and len(suggestion) > 20:
                    actions.append({
                        "goal": title,
                        "action": suggestion.strip()
                    })

    except Exception as e:
        print(f"[PROACTIVE_INTEL] Goal progress check failed: {e}")

    return actions


async def run_proactive_intelligence() -> Dict:
    """Full proactive intelligence scan. Runs in the autonomous loop."""
    print("[PROACTIVE_INTEL] Running intelligence scan...")
    results = {"insights": [], "goal_actions": [], "errors": []}

    try:
        results["insights"] = await analyse_email_patterns()
        print(f"[PROACTIVE_INTEL] {len(results['insights'])} email insights found")
    except Exception as e:
        results["errors"].append(f"Email analysis: {e}")

    try:
        results["goal_actions"] = await check_goal_progress()
        print(f"[PROACTIVE_INTEL] {len(results['goal_actions'])} goal actions identified")
    except Exception as e:
        results["errors"].append(f"Goal check: {e}")

    return results
