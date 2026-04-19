"""
Tony's WhatsApp Integration via Twilio.

Tony proactively messages Matthew on WhatsApp when something
important needs his attention — without Matthew having to open the app.

Rate limited: max 3 messages per day. Deduplication by content hash.
No spam. Ever.
"""
import os
import httpx
import base64
import hashlib
from typing import Optional

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
MATTHEW_WHATSAPP = os.environ.get("MATTHEW_WHATSAPP", "whatsapp:+447735589035")

DAILY_CAP = 3  # Max WhatsApp messages per day, full stop


def is_configured() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN)


def _get_conn():
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def _ensure_table():
    """Create whatsapp send log table if it doesn't exist."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_whatsapp_log (
                id SERIAL PRIMARY KEY,
                content_hash TEXT NOT NULL,
                message_preview TEXT,
                sent_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[WHATSAPP] Table init failed: {e}")


def _already_sent_today(content_hash: str) -> bool:
    """Check if this exact message was already sent today."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM tony_whatsapp_log
            WHERE content_hash = %s
            AND sent_at > NOW() - INTERVAL '24 hours'
            LIMIT 1
        """, (content_hash,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result is not None
    except Exception:
        return False


def _daily_send_count() -> int:
    """How many messages sent in the last 24 hours."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM tony_whatsapp_log
            WHERE sent_at > NOW() - INTERVAL '24 hours'
        """)
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception:
        return 999  # Fail safe — assume cap hit


def _log_sent(content_hash: str, preview: str):
    """Record that a message was sent."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tony_whatsapp_log (content_hash, message_preview) VALUES (%s, %s)",
            (content_hash, preview[:100])
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[WHATSAPP] Log failed: {e}")


async def send_whatsapp(message: str, to: str = None) -> bool:
    """Send a WhatsApp message to Matthew via Twilio."""
    if not is_configured():
        print("[WHATSAPP] Twilio not configured — skipping")
        return False

    _ensure_table()

    # Deduplication — same content in last 24h = skip
    content_hash = hashlib.md5(message.encode()).hexdigest()
    if _already_sent_today(content_hash):
        print(f"[WHATSAPP] Duplicate — already sent this message today, skipping")
        return False

    # Daily cap
    count = _daily_send_count()
    if count >= DAILY_CAP:
        print(f"[WHATSAPP] Daily cap of {DAILY_CAP} reached ({count} sent) — skipping")
        return False

    recipient = to or MATTHEW_WHATSAPP
    if not recipient.startswith("whatsapp:"):
        recipient = f"whatsapp:{recipient}"

    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
        auth = base64.b64encode(f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()).decode()

        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                url,
                headers={"Authorization": f"Basic {auth}"},
                data={
                    "From": TWILIO_FROM,
                    "To": recipient,
                    "Body": message[:1600]
                }
            )

            if r.status_code in (200, 201):
                _log_sent(content_hash, message[:100])
                print(f"[WHATSAPP] Sent ({count + 1}/{DAILY_CAP} today): {message[:50]}...")
                return True
            else:
                print(f"[WHATSAPP] Send failed: {r.status_code} — {r.text[:200]}")
                return False

    except Exception as e:
        print(f"[WHATSAPP] Error: {e}")
        return False


async def tony_whatsapp_notify(subject: str, body: str, priority: str = "normal") -> bool:
    """
    Tony sends Matthew a WhatsApp notification.
    Used for high-priority proactive alerts only.
    """
    # Clean format — no emoji doubling, no markdown that breaks in WhatsApp
    if priority in ("urgent", "high"):
        message = f"Tony - {subject}\n\n{body}"
    else:
        message = f"Tony - {subject}\n\n{body}"
    return await send_whatsapp(message)


async def check_and_notify_urgent_alerts():
    """
    Check for unread urgent alerts and send WhatsApp notifications.
    Hard limits: max 3/day, no duplicates, only genuinely new alerts.
    """
    if not is_configured():
        return

    _ensure_table()

    # Check cap before doing any DB work
    if _daily_send_count() >= DAILY_CAP:
        print(f"[WHATSAPP] Daily cap reached — skipping alert notifications")
        return

    try:
        conn = _get_conn()
        cur = conn.cursor()

        # Only alerts from last 6h (one loop cycle), not already whatsapp-notified
        cur.execute("""
            SELECT id, title, body, priority
            FROM tony_alerts
            WHERE read = FALSE
            AND priority IN ('urgent', 'high')
            AND (expires_at IS NULL OR expires_at > NOW())
            AND created_at > NOW() - INTERVAL '6 hours'
            AND (source IS NULL OR source != 'whatsapp_sent')
            ORDER BY created_at DESC
            LIMIT 2
        """)
        alerts = cur.fetchall()

        sent_count = 0
        for alert_id, title, body, priority in alerts:
            if _daily_send_count() >= DAILY_CAP:
                break
            success = await tony_whatsapp_notify(title, body[:300], priority)
            if success:
                cur.execute(
                    "UPDATE tony_alerts SET source = 'whatsapp_sent' WHERE id = %s",
                    (alert_id,)
                )
                sent_count += 1

        conn.commit()
        cur.close()
        conn.close()

        if sent_count:
            print(f"[WHATSAPP] Sent {sent_count} urgent notifications")

    except Exception as e:
        print(f"[WHATSAPP] Alert notification failed: {e}")
