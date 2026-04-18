"""
Tony's WhatsApp Integration via Twilio.

Tony proactively messages Matthew on WhatsApp when something
important needs his attention — without Matthew having to open the app.

This is the difference between an assistant that waits
and one that actually reaches out.

Setup required:
- Twilio account (free trial: $15 credit)
- TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN in Railway env
- TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886" (Twilio sandbox number)
- MATTHEW_WHATSAPP = "whatsapp:+447735589035"

Cost: ~£0.05 per message on paid tier, free on sandbox for testing.
"""
import os
import httpx
import base64
from typing import Optional

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
MATTHEW_WHATSAPP = os.environ.get("MATTHEW_WHATSAPP", "whatsapp:+447735589035")


def is_configured() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN)


async def send_whatsapp(message: str, to: str = None) -> bool:
    """Send a WhatsApp message to Matthew via Twilio."""
    if not is_configured():
        print("[WHATSAPP] Twilio not configured — add TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN to Railway")
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
                    "Body": message[:1600]  # WhatsApp message limit
                }
            )

            if r.status_code in (200, 201):
                print(f"[WHATSAPP] Message sent: {message[:50]}...")
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
    Used for high-priority proactive alerts.
    """
    prefix = "⚠️ *URGENT* — " if priority in ("urgent", "high") else "📱 *Tony* — "
    message = f"{prefix}{subject}\n\n{body}"
    return await send_whatsapp(message)


async def check_and_notify_urgent_alerts():
    """
    Check for unread urgent alerts and send WhatsApp notifications.
    Runs as part of proactive scan — only sends for genuinely urgent items.
    Prevents spam by tracking what's already been sent.
    """
    if not is_configured():
        return

    try:
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()

        # Get urgent unread alerts not yet sent via WhatsApp
        cur.execute("""
            SELECT id, title, body, priority
            FROM tony_alerts
            WHERE read = FALSE
            AND priority IN ('urgent', 'high')
            AND (expires_at IS NULL OR expires_at > NOW())
            AND created_at > NOW() - INTERVAL '1 hour'
            AND source != 'whatsapp_sent'
            ORDER BY created_at DESC
            LIMIT 3
        """)
        alerts = cur.fetchall()

        sent_count = 0
        for alert_id, title, body, priority in alerts:
            success = await tony_whatsapp_notify(title, body[:300], priority)
            if success:
                # Mark as whatsapp-notified by updating source
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
