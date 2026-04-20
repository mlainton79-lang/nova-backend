"""
Tony's Email Agent.

Tony reads correspondence, drafts responses, and with approval — sends them.


For general email:
- Identifies emails needing responses
- Drafts appropriate replies
- Sends routine emails autonomously (newsletters, unsubscribes etc)
- Escalates important ones to Matthew

This makes Tony a genuine email agent, not just a drafter.
"""
import os
import base64
import psycopg2
import httpx
from datetime import datetime
from typing import Dict, List, Optional
from app.core.model_router import gemini, gemini_json

GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_email_agent_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_email_queue (
                id SERIAL PRIMARY KEY,
                account TEXT NOT NULL,
                to_address TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                draft_reason TEXT,
                approval_status TEXT DEFAULT 'pending',
                approved_at TIMESTAMP,
                sent_at TIMESTAMP,
                original_message_id TEXT,
                priority TEXT DEFAULT 'normal',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[EMAIL_AGENT] Tables initialised")
    except Exception as e:
        print(f"[EMAIL_AGENT] Init failed: {e}")


async def get_access_token(email: str) -> Optional[str]:
    """Get Gmail access token."""
    try:
        from app.core.gmail_service import refresh_access_token
        return await refresh_access_token(email)
    except Exception:
        return None


async def send_email_via_gmail(
    account: str,
    to: str,
    subject: str,
    body: str,
    reply_to_message_id: str = None
) -> bool:
    """Send an email via Gmail API."""
    token = await get_access_token(account)
    if not token:
        return False

    try:
        # Build email message
        message_parts = [
            f"To: {to}",
            f"From: {account}",
            f"Subject: {subject}",
            "Content-Type: text/plain; charset=utf-8",
            "MIME-Version: 1.0",
            "",
            body
        ]

        if reply_to_message_id:
            message_parts.insert(3, f"In-Reply-To: {reply_to_message_id}")
            message_parts.insert(4, f"References: {reply_to_message_id}")

        raw_message = "\n".join(message_parts)
        encoded = base64.urlsafe_b64encode(raw_message.encode()).decode()

        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": f"Bearer {token}"},
                json={"raw": encoded}
            )
            return r.status_code == 200

    except Exception as e:
        print(f"[EMAIL_AGENT] Send failed: {e}")
        return False


async def queue_email_for_approval(
    account: str,
    to: str,
    subject: str,
    body: str,
    reason: str,
    priority: str = "normal",
    original_message_id: str = None
) -> int:
    """Queue an email draft for Matthew's approval."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_email_queue
            (account, to_address, subject, body, draft_reason, priority, original_message_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (account, to, subject, body, reason, priority, original_message_id))
        queue_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        # Alert Matthew
        from app.core.proactive import create_alert
        create_alert(
            alert_type="email_ready_to_send",
            title=f"Email ready: {subject[:50]}",
            body=f"To: {to}\n{reason}\nTap to approve and send.",
            priority=priority,
            source="email_agent"
        )

        return queue_id
    except Exception as e:
        print(f"[EMAIL_AGENT] Queue failed: {e}")
        return -1


async def scan_for_actionable_emails() -> List[Dict]:
    """
    Scan all accounts for emails that need responses.
    Tony identifies and queues drafts.
    """
    actionable = []

    try:
        from app.core.gmail_service import search_all_accounts

        # No hardcoded topic search. Email scanning is driven by active cases
        # that Matthew has explicitly asked Tony to track.
        pass

    except Exception as e:
        print(f"[EMAIL_AGENT] Scan failed: {e}")

    return actionable


async def get_pending_approvals() -> List[Dict]:
    """Get emails queued for Matthew's approval."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, account, to_address, subject, body, draft_reason, priority, created_at
            FROM tony_email_queue
            WHERE approval_status = 'pending'
            ORDER BY priority DESC, created_at DESC
            LIMIT 10
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "id": r[0], "account": r[1], "to": r[2], "subject": r[3],
                "body": r[4], "reason": r[5], "priority": r[6],
                "created": str(r[7])
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[EMAIL_AGENT] Get pending failed: {e}")
        return []


async def approve_and_send(queue_id: int) -> bool:
    """Matthew approves — Tony sends."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT account, to_address, subject, body, original_message_id FROM tony_email_queue WHERE id = %s",
            (queue_id,)
        )
        row = cur.fetchone()
        if not row:
            return False

        account, to, subject, body, orig_id = row

        sent = await send_email_via_gmail(account, to, subject, body, orig_id)

        if sent:
            cur.execute(
                "UPDATE tony_email_queue SET approval_status = 'sent', sent_at = NOW() WHERE id = %s",
                (queue_id,)
            )
            conn.commit()

        cur.close()
        conn.close()
        return sent

    except Exception as e:
        print(f"[EMAIL_AGENT] Approve and send failed: {e}")
        return False
