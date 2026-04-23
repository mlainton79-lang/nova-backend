"""
Daily Review — synthesises what happened today from all Tony's signals.

Pulls:
- Conversations (chat count, topics via fact extraction)
- Alerts created today
- Emails triaged today
- Receipts logged today
- Tasks completed today
- Goals progressed today
- Builds Tony shipped today

Then: Gemini synthesises a short reflection Tony can hand to Matthew at end of day.
Not a dashboard. A conversational summary.
"""
import os
import httpx
import psycopg2
from datetime import datetime, date, timedelta
from typing import Dict, List


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def _today_bounds():
    today = date.today()
    return today, today + timedelta(days=1)


async def gather_daily_signals() -> Dict:
    """Collect everything that happened today. Each query isolated."""
    signals = {"date": str(date.today())}

    try:
        conn = get_conn()
        cur = conn.cursor()

        # Chat count today
        try:
            cur.execute("""
                SELECT COUNT(*) FROM tony_request_log
                WHERE created_at::date = CURRENT_DATE
                  AND ok = TRUE
            """)
            signals["chat_count"] = cur.fetchone()[0]
        except Exception as e:
            signals["chat_count"] = None
            signals["chat_error"] = str(e)[:80]

        # Alerts created today (not by Tony himself)
        try:
            cur.execute("""
                SELECT title, body, priority FROM tony_alerts
                WHERE created_at::date = CURRENT_DATE
                  AND source != 'tony_push'
                ORDER BY CASE priority WHEN 'urgent' THEN 1
                                       WHEN 'high' THEN 2 ELSE 3 END
                LIMIT 10
            """)
            signals["alerts"] = [
                {"title": r[0], "body": (r[1] or "")[:150], "priority": r[2]}
                for r in cur.fetchall()
            ]
        except Exception:
            signals["alerts"] = []

        # Emails triaged today
        try:
            cur.execute("""
                SELECT urgency, COUNT(*) FROM tony_email_triage
                WHERE triaged_at::date = CURRENT_DATE
                GROUP BY urgency
            """)
            signals["emails_by_urgency"] = dict(cur.fetchall())
        except Exception:
            signals["emails_by_urgency"] = {}

        # Receipts logged today
        try:
            cur.execute("""
                SELECT COUNT(*), COALESCE(SUM(total), 0)
                FROM tony_expenses
                WHERE purchase_date = CURRENT_DATE
                   OR extracted_at::date = CURRENT_DATE
            """)
            count, total = cur.fetchone()
            signals["receipts"] = {"count": count, "total": float(total)}
        except Exception:
            signals["receipts"] = {"count": 0, "total": 0.0}

        # Facts extracted today
        try:
            cur.execute("""
                SELECT subject, predicate, object FROM tony_facts
                WHERE created_at::date = CURRENT_DATE
                  AND superseded_by IS NULL
                ORDER BY created_at DESC LIMIT 10
            """)
            signals["new_facts"] = [
                {"subject": r[0], "predicate": r[1], "object": r[2][:100]}
                for r in cur.fetchall()
            ]
        except Exception:
            signals["new_facts"] = []

        # Documents ingested today
        try:
            cur.execute("""
                SELECT doc_name, doc_type FROM tony_documents
                WHERE uploaded_at::date = CURRENT_DATE
                ORDER BY uploaded_at DESC LIMIT 5
            """)
            signals["docs"] = [
                {"name": r[0], "type": r[1]} for r in cur.fetchall()
            ]
        except Exception:
            signals["docs"] = []

        # Tony's own work today (capabilities built, tasks completed)
        try:
            cur.execute("""
                SELECT task_type, status FROM tony_task_queue
                WHERE (completed_at::date = CURRENT_DATE
                    OR created_at::date = CURRENT_DATE)
                  AND status IN ('completed','failed')
                ORDER BY created_at DESC LIMIT 5
            """)
            signals["tony_tasks"] = [
                {"type": r[0], "status": r[1]} for r in cur.fetchall()
            ]
        except Exception:
            signals["tony_tasks"] = []

        # Goal progress
        try:
            cur.execute("""
                SELECT title, status FROM tony_goals
                WHERE updated_at::date = CURRENT_DATE
                ORDER BY updated_at DESC LIMIT 5
            """)
            signals["goals_touched"] = [
                {"title": r[0], "status": r[1]} for r in cur.fetchall()
            ]
        except Exception:
            signals["goals_touched"] = []

        # Fabrications caught (if any)
        try:
            cur.execute("""
                SELECT COUNT(*) FROM tony_suspected_fabrications
                WHERE created_at::date = CURRENT_DATE
            """)
            signals["fabrications_flagged"] = cur.fetchone()[0]
        except Exception:
            signals["fabrications_flagged"] = 0

        cur.close()
        conn.close()
    except Exception as e:
        signals["gather_error"] = str(e)[:100]

    return signals


async def synthesise_review(signals: Dict) -> str:
    """Turn signals into a conversational end-of-day review in Tony's voice."""
    api_key = os.environ.get("GEMINI_API_KEY", "")

    # Build a fact list for the LLM
    facts = []
    if signals.get("chat_count"):
        facts.append(f"Conversations today: {signals['chat_count']}")

    alerts = signals.get("alerts", [])
    urgent = [a for a in alerts if a["priority"] == "urgent"]
    if urgent:
        facts.append(f"Urgent alerts: {len(urgent)}")
        for a in urgent[:3]:
            facts.append(f"  - {a['title']}: {a['body'][:80]}")

    emails = signals.get("emails_by_urgency", {})
    if emails:
        urgent_count = emails.get("urgent", 0)
        normal_count = emails.get("normal", 0)
        if urgent_count or normal_count:
            facts.append(f"Emails triaged: {urgent_count} urgent, {normal_count} normal")

    receipts = signals.get("receipts", {})
    if receipts.get("count", 0) > 0:
        facts.append(f"Receipts logged: {receipts['count']} (£{receipts['total']:.2f})")

    new_facts = signals.get("new_facts", [])
    if new_facts:
        facts.append(f"Remembered: {len(new_facts)} new facts about you")
        for f in new_facts[:3]:
            facts.append(f"  - {f['subject']} / {f['predicate']} / {f['object']}")

    docs = signals.get("docs", [])
    if docs:
        facts.append(f"Documents indexed: {[d['name'] for d in docs]}")

    tony_tasks = signals.get("tony_tasks", [])
    if tony_tasks:
        completed = [t for t in tony_tasks if t["status"] == "completed"]
        if completed:
            facts.append(f"Tony completed: {len(completed)} background tasks")

    if signals.get("fabrications_flagged", 0) > 0:
        facts.append(f"Fabrication-check caught: {signals['fabrications_flagged']}")

    facts_text = "\n".join(facts) if facts else "Quiet day."

    if not api_key or facts_text == "Quiet day.":
        return _fallback_review(signals)

    prompt = f"""Write Matthew's end-of-day review. Speak AS Tony — direct, short, British English.

Rules:
- Not a corporate summary. Personal.
- Lead with the important thing if there was one. If not, a natural summary.
- Don't list everything. Pick what matters.
- If it was a quiet day, say so. Don't pad.
- Don't celebrate routine days. Don't over-praise.
- Don't end with 'let me know if you need anything' or similar filler.
- 2-4 short sentences max.

Today's data:
{facts_text}

Write the review:"""

    try:
        from app.core import gemini_client
        response = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": 300, "temperature": 0.4},
            timeout=15.0,
            caller_context="daily_review",
        )
        return gemini_client.extract_text(response).strip()
    except Exception as e:
        print(f"[DAILY_REVIEW] LLM synthesis failed: {e}")
        return _fallback_review(signals)


def _fallback_review(signals: Dict) -> str:
    """Simple bullet-free summary when LLM unavailable."""
    parts = []
    alerts = signals.get("alerts", [])
    urgent = [a for a in alerts if a["priority"] == "urgent"]
    if urgent:
        parts.append(f"{len(urgent)} urgent alerts today.")
    if signals.get("receipts", {}).get("count"):
        c = signals["receipts"]["count"]
        t = signals["receipts"]["total"]
        parts.append(f"Logged {c} receipt(s), £{t:.2f}.")
    emails = signals.get("emails_by_urgency", {})
    if emails.get("urgent"):
        parts.append(f"{emails['urgent']} urgent emails.")
    if not parts:
        return "Quiet one today."
    return " ".join(parts)


async def get_daily_review() -> Dict:
    signals = await gather_daily_signals()
    review = await synthesise_review(signals)
    return {"ok": True, "review": review, "signals": signals}
