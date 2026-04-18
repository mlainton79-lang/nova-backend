"""
Tony's Push Notification System - FCM V1 API.

Uses Firebase Cloud Messaging HTTP v1 API (current standard).
Requires a service account JSON key from Firebase project settings.

Setup:
1. Firebase console → Project Settings → Service accounts
2. Generate new private key → download JSON
3. Add contents as FIREBASE_SERVICE_ACCOUNT env var in Railway (paste entire JSON as string)
4. Add FIREBASE_PROJECT_ID env var (e.g. nova-f83e3)
"""
import os
import json
import httpx
import psycopg2
from datetime import datetime
from typing import Optional

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "nova-f83e3")
FIREBASE_SERVICE_ACCOUNT = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")

def get_firebase_credentials():
    """Get Firebase service account - from env var or DB."""
    sa = FIREBASE_SERVICE_ACCOUNT
    if sa:
        return sa
    # Try DB
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT value FROM tony_config WHERE key = 'firebase_service_account' LIMIT 1")
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return row[0]
    except Exception:
        pass
    return ""

def init_config_table():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_config (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[CONFIG] Init failed: {e}")

def store_config(key: str, value: str):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_config (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """, (key, value))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[CONFIG] Store failed: {e}")
        return False

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
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM push_tokens WHERE platform = %s", (platform,))
        cur.execute("INSERT INTO push_tokens (token, platform) VALUES (%s, %s)", (token, platform))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[PUSH] Token saved for {platform}")
    except Exception as e:
        print(f"[PUSH] Token save failed: {e}")


def get_push_token() -> Optional[str]:
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


async def get_fcm_access_token() -> Optional[str]:
    """Get OAuth2 access token for FCM V1 API using service account."""
    creds = get_firebase_credentials()
    if not creds:
        return None
    try:
        import time, base64, hashlib, hmac
        sa = json.loads(creds)
        
        # Build JWT for service account auth
        now = int(time.time())
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        
        payload = base64.urlsafe_b64encode(json.dumps({
            "iss": sa["client_email"],
            "scope": "https://www.googleapis.com/auth/firebase.messaging",
            "aud": "https://oauth2.googleapis.com/token",
            "iat": now,
            "exp": now + 3600
        }).encode()).rstrip(b"=").decode()
        
        signing_input = f"{header}.{payload}"
        
        # Sign with private key using cryptography library
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.backends import default_backend
            
            private_key = serialization.load_pem_private_key(
                sa["private_key"].encode(),
                password=None,
                backend=default_backend()
            )
            signature = private_key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
            sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
            jwt_token = f"{signing_input}.{sig_b64}"
        except ImportError:
            print("[PUSH] cryptography library not installed - cannot sign JWT")
            return None
        
        # Exchange JWT for access token
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": jwt_token
                }
            )
            if r.status_code == 200:
                return r.json().get("access_token")
    except Exception as e:
        print(f"[PUSH] Access token failed: {e}")
    return None


async def send_push(title: str, body: str, data: dict = None) -> bool:
    """Send FCM V1 push notification."""
    token = get_push_token()
    
    if FIREBASE_PROJECT_ID and FIREBASE_SERVICE_ACCOUNT and token:
        try:
            access_token = await get_fcm_access_token()
            if access_token:
                message = {
                    "message": {
                        "token": token,
                        "notification": {"title": title, "body": body},
                        "data": {k: str(v) for k, v in (data or {}).items()},
                        "android": {
                            "priority": "high",
                            "notification": {"sound": "default"}
                        }
                    }
                }
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(
                        f"https://fcm.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/messages:send",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json"
                        },
                        json=message
                    )
                    if r.status_code == 200:
                        print(f"[PUSH] Sent: {title}")
                        return True
                    else:
                        print(f"[PUSH] FCM V1 failed: {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"[PUSH] Send error: {e}")
    
    # Fallback: store as alert
    try:
        from app.core.proactive import create_alert
        create_alert(alert_type="notification", title=title, body=body,
                    priority="high", source="tony_push")
        return True
    except Exception as e:
        print(f"[PUSH] Alert fallback failed: {e}")
        return False


async def tony_notify(message: str, priority: str = "normal"):
    """Tony sends Matthew a notification."""
    title = "Tony" if priority == "normal" else "⚠️ Tony — Urgent"
    return await send_push(title, message)
