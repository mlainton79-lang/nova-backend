"""
Tony's Push Notification System.

Tony reaches Matthew without being asked.
Uses Firebase Cloud Messaging (FCM) - free tier.

Setup needed:
- FIREBASE_SERVER_KEY env var in Railway
- FCM device token stored when app starts

Until Firebase is configured, Tony stores notifications
in the alerts table and surfaces them on next open.
"""
import os
import httpx
import psycopg2
from datetime import datetime
from typing import Optional

FIREBASE_SERVER_KEY = os.environ.get("FIREBASE_SERVER_KEY", "")
BACKEND_URL = "https://web-production-be42b.up.railway.app"

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_push_table():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS push_tokens (
                id SERIAL PRIMARY KEY,
                token TEXT NOT NULL,
                platform TEXT DEFAULT 'android',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[PUSH] Init failed: {e}")


def save_push_token(token: str, platform: str = "android"):
    """Save or update the FCM device token."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Keep only latest token
        cur.execute("DELETE FROM push_tokens WHERE platform = %s", (platform,))
        cur.execute(
            "INSERT INTO push_tokens (token, platform) VALUES (%s, %s)",
            (token, platform)
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"[PUSH] Token saved for {platform}")
    except Exception as e:
        print(f"[PUSH] Token save failed: {e}")


def get_push_token() -> Optional[str]:
    """Get the current FCM device token."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT token FROM push_tokens ORDER BY updated_at DESC LIMIT 1")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


async def send_push(title: str, body: str, data: dict = None) -> bool:
    """
    Send a push notification to Matthew's phone.
    Falls back to storing in alerts if FCM not configured.
    """
    token = get_push_token()

    # If FCM is configured and we have a token, send real push
    if FIREBASE_SERVER_KEY and token:
        try:
            payload = {
                "to": token,
                "notification": {
                    "title": title,
                    "body": body,
                    "sound": "default"
                },
                "data": data or {},
                "priority": "high"
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    "https://fcm.googleapis.com/fcm/send",
                    headers={
                        "Authorization": f"key={FIREBASE_SERVER_KEY}",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )
                if r.status_code == 200:
                    print(f"[PUSH] Sent: {title}")
                    return True
                else:
                    print(f"[PUSH] FCM failed: {r.status_code}")
        except Exception as e:
            print(f"[PUSH] Send failed: {e}")

    # Fallback: store as alert (shown when app opens)
    try:
        from app.core.proactive import create_alert
        create_alert(
            alert_type="notification",
            title=title,
            body=body,
            priority="high",
            source="tony_push"
        )
        return True
    except Exception as e:
        print(f"[PUSH] Alert fallback failed: {e}")
        return False


async def tony_notify(message: str, priority: str = "normal"):
    """Tony sends Matthew a notification. Simple interface."""
    title = "Tony" if priority == "normal" else "⚠️ Tony — Urgent"
    return await send_push(title, message)
