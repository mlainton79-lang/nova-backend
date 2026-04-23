"""
Tony's Proactive Intelligence Engine.

Tony doesn't wait to be asked. He monitors Matthew's world
and initiates contact when something needs attention.

This is the difference between an assistant and an agent.

Monitors:
- Emails — new important ones flagged immediately
- Legal deadlines (if any cases tracked), complaints, response windows
- World model changes — anything that crossed a threshold
- Goals — progress or blockers
- Opportunities — things Tony spotted that could help

Tony decides what's urgent enough to surface.
He doesn't spam. He uses judgment.
"""
import os
import json
import httpx
import asyncio
import psycopg2
from datetime import datetime, timedelta
from typing import List, Dict

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BACKEND_URL = "https://web-production-be42b.up.railway.app"
DEV_TOKEN = os.environ.get("DEV_TOKEN", "nova-dev-token")

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_proactive_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_alerts (
                id SERIAL PRIMARY KEY,
                alert_type TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                priority TEXT DEFAULT 'normal',
                source TEXT,
                read BOOLEAN DEFAULT FALSE,
                actioned BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP
            )
        """)
        # Caller-controlled dedup key. Callers whose titles are LLM-generated
        # (and therefore vary run-to-run for the same underlying event) pass
        # a stable key so repeated creations collapse onto the existing
        # unread alert instead of producing near-duplicates.
        cur.execute(
            "ALTER TABLE tony_alerts ADD COLUMN IF NOT EXISTS dedup_key TEXT"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_dedup_key "
            "ON tony_alerts(dedup_key) WHERE read = FALSE"
        )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_monitoring (
                id SERIAL PRIMARY KEY,
                monitor_type TEXT NOT NULL,
                config JSONB NOT NULL,
                last_checked TIMESTAMP,
                last_result TEXT,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[PROACTIVE] Tables initialised")
    except Exception as e:
        print(f"[PROACTIVE] Init failed: {e}")


def _is_topic_banned(text: str) -> bool:
    """Check if any banned topic appears in this text. Used to suppress alert creation."""
    if not text:
        return False
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT topic FROM tony_topic_bans
            WHERE active = TRUE AND expires_at > NOW()
        """)
        bans = [row[0].lower() for row in cur.fetchall()]
        cur.close()
        conn.close()
        tl = text.lower()
        for ban in bans:
            if ban in tl:
                return True
        return False
    except Exception:
        return False


def create_alert(alert_type: str, title: str, body: str,
                  priority: str = "normal", source: str = None,
                  expires_hours: int = 48,
                  dedup_hours: int = 24,
                  dedup_key: str = None):
    """
    Tony creates an alert for Matthew.

    Deduplicates within dedup_hours. If dedup_key is provided, matches on
    it — use this when titles are LLM-generated or otherwise unstable for
    the same underlying event (e.g. "Nova App Build Failure" vs "Nova App
    Build Failures" vs "Nova App Build Failed (10 times)" — all the same
    signal). If dedup_key is omitted, matches on exact title (original
    behaviour, fine for callers whose titles are stable per-entity, e.g.
    email_monitor's per-sender titles).
    """
    # BAN CHECK: suppress alert if content matches any active topic ban
    combined = f"{title} {body} {source or ''}"
    if _is_topic_banned(combined):
        print(f"[PROACTIVE] Alert suppressed by topic ban: {title[:60]}")
        return None

    import asyncio
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Dedup check — existing unread alert within window that matches
        # by (dedup_key when provided) or (exact title otherwise).
        if dedup_key:
            cur.execute("""
                SELECT id FROM tony_alerts
                WHERE dedup_key = %s
                AND created_at > NOW() - INTERVAL '%s hours'
                AND read = FALSE
                LIMIT 1
            """, (dedup_key, dedup_hours))
        else:
            cur.execute("""
                SELECT id FROM tony_alerts
                WHERE title = %s
                AND created_at > NOW() - INTERVAL '%s hours'
                AND read = FALSE
                LIMIT 1
            """, (title, dedup_hours))
        existing = cur.fetchone()
        if existing:
            cur.close()
            conn.close()
            return existing[0]  # Return existing alert id, don't create duplicate

        expires = datetime.utcnow() + timedelta(hours=expires_hours)
        cur.execute("""
            INSERT INTO tony_alerts (alert_type, title, body, priority, source, expires_at, dedup_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (alert_type, title, body, priority, source, expires, dedup_key))
        alert_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        print(f"[PROACTIVE] Alert created: {title}")

        # Push notification for genuinely new urgent alerts only
        # Skip if source is 'tony_push' (means the alert was itself created by a push fallback) —
        # belt and braces against recursive loops
        if priority in ("urgent", "high") and source != "tony_push":
            try:
                from app.core.push_notifications import tony_notify
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(tony_notify(f"{title}: {body[:100]}", priority))
            except Exception:
                pass

        return alert_id
    except Exception as e:
        print(f"[PROACTIVE] Alert creation failed: {e}")
        return None


def get_unread_alerts() -> List[Dict]:
    """Get all unread alerts for Matthew."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, alert_type, title, body, priority, source, created_at
            FROM tony_alerts
            WHERE read = FALSE
            AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY
                CASE priority
                    WHEN 'urgent' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'normal' THEN 3
                    WHEN 'low' THEN 4
                END,
                created_at DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "id": r[0], "type": r[1], "title": r[2],
                "body": r[3], "priority": r[4], "source": r[5],
                "time": str(r[6])
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[PROACTIVE] Alert fetch failed: {e}")
        return []


def mark_alert_read(alert_id: int):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE tony_alerts SET read = TRUE WHERE id = %s", (alert_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[PROACTIVE] Mark read failed: {e}")


async def tony_scan_emails_for_urgency() -> List[Dict]:
    """
    Tony scans recent emails and identifies anything urgent.
    Uses his own judgment — not just keywords, but understanding context.
    """
    urgent_alerts = []
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Get recent unread emails
            r = await client.get(
                f"{BACKEND_URL}/api/v1/gmail/morning",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"}
            )
            summary = r.json().get("summary", "")

        if not summary or "No unread" in summary:
            return []

        # Tony uses his judgment to identify what's urgent
        prompt = f"""You are Tony. You've scanned Matthew's emails and found:

{summary}

Matthew's context:
- Works nights at a care home
- Has two young daughters
- Is building Nova app late at night

Identify any emails that are URGENT or need Matthew's attention soon.
Think about: legal letters, payment demands, court notices, work issues, family matters, deadlines.

Respond in JSON only:
{{
    "urgent_items": [
        {{
            "title": "short alert title",
            "body": "what Matthew needs to know and why it matters",
            "priority": "urgent/high/normal",
            "source": "sender or account"
        }}
    ]
}}

If nothing is urgent, return: {{"urgent_items": []}}"""

        async with httpx.AsyncClient(timeout=20.0) as client:
            from app.core import gemini_client
            resp = await gemini_client.generate_content(
                tier="flash",
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                generation_config={"maxOutputTokens": 1024, "temperature": 0.2},
                timeout=20.0,
                caller_context="proactive",
            )
            response = gemini_client.extract_text(resp)

            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                for item in data.get("urgent_items", []):
                    # LLM-generated titles and sources vary slightly run-to-run
                    # for the same underlying event (temperature=0.2, shifting
                    # Gmail summary). Pass a stable dedup_key so repeated scans
                    # of the same urgent-email signal collapse onto one alert.
                    src = item.get("source", "Gmail")
                    # Normalise source for dedup: case-insensitive, stripped of
                    # common noise like parentheses so "Railway (mlainton79)"
                    # and "mlainton79 (Railway)" collapse.
                    src_normalised = (src or "").lower()
                    for ch in "()[]":
                        src_normalised = src_normalised.replace(ch, "")
                    src_normalised = " ".join(sorted(src_normalised.split()))
                    alert_id = create_alert(
                        alert_type="email",
                        title=item.get("title", "Email alert"),
                        body=item.get("body", ""),
                        priority=item.get("priority", "normal"),
                        source=src,
                        dedup_key=f"email_scan:{src_normalised}",
                    )
                    if alert_id:
                        urgent_alerts.append(item)

    except Exception as e:
        print(f"[PROACTIVE] Email scan failed: {e}")

    return urgent_alerts


async def tony_check_legal_deadlines():
    """
    Tony monitors any active tracked cases and legal deadlines.
    Flags anything approaching.
    """
    try:
        from app.core.world_model import get_world_model
        model = get_world_model("LEGAL")

        legal = model.get("LEGAL", {})
        for key, data in legal.items():
            value = data.get("value", {})
            if isinstance(value, dict):
                # Check for any deadline mentions
                tony_next = value.get("tony_next_action", "")
                status = value.get("status", "")

                if "pending" in status.lower() or "in progress" in status.lower():
                    # Check if we haven't alerted about this recently
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT id FROM tony_alerts
                        WHERE source = %s
                        AND created_at > NOW() - INTERVAL '7 days'
                        LIMIT 1
                    """, (key,))
                    recent = cur.fetchone()
                    cur.close()
                    conn.close()

                    if not recent and tony_next:
                        create_alert(
                            alert_type="legal",
                            title=f"Legal: {key.replace('_', ' ').title()}",
                            body=f"Status: {status}\nNext action: {tony_next}",
                            priority="high",
                            source=key,
                            expires_hours=168  # 1 week
                        )
    except Exception as e:
        print(f"[PROACTIVE] Legal check failed: {e}")


async def run_proactive_scan():
    """
    Tony's proactive intelligence scan.
    Run on the cron loop — Tony checks everything and creates alerts.
    """
    print("[PROACTIVE] Running proactive scan...")
    results = {"alerts_created": 0, "scans": []}

    # Scan emails
    try:
        email_alerts = await tony_scan_emails_for_urgency()
        results["scans"].append(f"Email scan: {len(email_alerts)} urgent items")
        results["alerts_created"] += len(email_alerts)
    except Exception as e:
        results["scans"].append(f"Email scan failed: {e}")

    # Check legal deadlines
    try:
        await tony_check_legal_deadlines()
        results["scans"].append("Legal deadline check complete")
    except Exception as e:
        results["scans"].append(f"Legal check failed: {e}")

    print(f"[PROACTIVE] Scan complete. {results['alerts_created']} new alerts created.")
    return results
