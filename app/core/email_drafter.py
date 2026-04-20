"""
Tony's Proactive Email Drafting Engine.

Tony reads Matthew's inbox and prepares draft replies before being asked.
When an email needs a response, Tony drafts it using full context from
the world model, memory, and the email thread — then surfaces it as an alert.

Matthew sees: "Tony has drafted a reply. Review it."
Matthew can send it unchanged or edit it first.

Drafts are stored in the DB. The alert tells Matthew they exist.
"""
import os
import json
import re
import httpx
import psycopg2
from datetime import datetime, timedelta
from typing import List, Dict, Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BACKEND_URL = "https://web-production-be42b.up.railway.app"
DEV_TOKEN = os.environ.get("DEV_TOKEN", "nova-dev-token")

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_draft_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_email_drafts (
                id SERIAL PRIMARY KEY,
                account TEXT NOT NULL,
                original_message_id TEXT,
                original_from TEXT,
                original_subject TEXT,
                original_snippet TEXT,
                draft_to TEXT NOT NULL,
                draft_subject TEXT NOT NULL,
                draft_body TEXT NOT NULL,
                tony_reasoning TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW(),
                actioned_at TIMESTAMP,
                sent BOOLEAN DEFAULT FALSE
            )
        """)
        # Index to avoid duplicate drafts for the same message
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_drafts_message_id
            ON tony_email_drafts (original_message_id)
            WHERE original_message_id IS NOT NULL
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[EMAIL DRAFTER] Tables initialised")
    except Exception as e:
        print(f"[EMAIL DRAFTER] Init failed: {e}")


def get_pending_drafts() -> List[Dict]:
    """Get all drafts Tony has prepared that haven't been actioned yet."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, account, original_from, original_subject,
                   draft_to, draft_subject, draft_body, tony_reasoning,
                   status, created_at
            FROM tony_email_drafts
            WHERE status = 'pending'
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "id": r[0], "account": r[1], "from": r[2],
                "original_subject": r[3], "draft_to": r[4],
                "draft_subject": r[5], "draft_body": r[6],
                "reasoning": r[7], "status": r[8],
                "created_at": str(r[9])
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[EMAIL DRAFTER] Fetch failed: {e}")
        return []


def mark_draft_sent(draft_id: int):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_email_drafts
            SET status = 'sent', sent = TRUE, actioned_at = NOW()
            WHERE id = %s
        """, (draft_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[EMAIL DRAFTER] Mark sent failed: {e}")


def mark_draft_dismissed(draft_id: int):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_email_drafts
            SET status = 'dismissed', actioned_at = NOW()
            WHERE id = %s
        """, (draft_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[EMAIL DRAFTER] Dismiss failed: {e}")


def draft_already_exists(message_id: str) -> bool:
    """Prevent duplicate drafts for the same email."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM tony_email_drafts WHERE original_message_id = %s",
            (message_id,)
        )
        exists = cur.fetchone() is not None
        cur.close()
        conn.close()
        return exists
    except Exception:
        return False


def save_draft(account: str, message_id: str, from_addr: str, subject: str,
               snippet: str, draft_to: str, draft_subject: str,
               draft_body: str, reasoning: str) -> Optional[int]:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_email_drafts
            (account, original_message_id, original_from, original_subject,
             original_snippet, draft_to, draft_subject, draft_body, tony_reasoning)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (original_message_id) DO NOTHING
            RETURNING id
        """, (account, message_id, from_addr, subject, snippet[:500],
              draft_to, draft_subject, draft_body, reasoning))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        print(f"[EMAIL DRAFTER] Save failed: {e}")
        return None


async def _call_gemini(prompt: str, max_tokens: int = 2000) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3}
                }
            )
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[EMAIL DRAFTER] Gemini call failed: {e}")
        return None


async def _get_world_context() -> str:
    """Pull condensed world model for prompt context."""
    try:
        from app.core.world_model import get_world_model_summary
        return get_world_model_summary()
    except Exception:
        return "Matthew Lainton, Rotherham. Works at Sid Bailey Care Home. Wife Georgina, daughters Amelia (5) and Margot (9 months)."


async def _needs_reply(email: Dict) -> Optional[Dict]:
    """
    Tony decides whether this email needs a reply, and if so, drafts one.
    Returns draft dict or None if no reply needed.
    """
    from_addr = email.get("from", "")
    subject = email.get("subject", "No subject")
    snippet = email.get("snippet", "")
    account = email.get("account", "")
    message_id = email.get("id", "")

    # Skip our own sent emails, newsletters, automated alerts
    skip_patterns = [
        "noreply", "no-reply", "donotreply", "notifications@",
        "updates@", "newsletter", "unsubscribe", "automated"
    ]
    from_lower = from_addr.lower()
    if any(p in from_lower for p in skip_patterns):
        return None

    # Skip if already have a draft for this
    if message_id and draft_already_exists(message_id):
        return None

    world_context = await _get_world_context()

    prompt = f"""You are Tony, Matthew Lainton's personal AI assistant.

Matthew's context:
{world_context}

An email has arrived. Decide if Matthew needs to reply to it.

Email details:
Account: {account}
From: {from_addr}
Subject: {subject}
Preview: {snippet}

Rules for deciding:
- Legal letters, court notices, payment demands → ALWAYS needs reply
- Questions addressed to Matthew → needs reply
- Important personal or work matters → needs reply
- Newsletters, automated alerts, promotions → NO reply needed
- Receipts, confirmations → NO reply needed
- If ambiguous, err toward replying

Respond in JSON only:
{{
    "needs_reply": true/false,
    "reasoning": "why Tony decided this",
    "urgency": "urgent/normal/low",
    "draft_subject": "Re: {subject}",
    "draft_body": "Full email body Tony has drafted for Matthew. British English. Professional but direct. Sign off as Matthew Lainton. Leave [YOUR NAME] placeholder if Tony cannot determine who to address. If this is a legal matter, be firm but measured.",
    "send_from": "{account}"
}}

If needs_reply is false, omit draft fields."""

    response = await _call_gemini(prompt, max_tokens=1500)
    if not response:
        return None

    try:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            return None
        data = json.loads(json_match.group())
        if not data.get("needs_reply"):
            return None
        return {
            "account": account,
            "message_id": message_id,
            "from": from_addr,
            "subject": subject,
            "snippet": snippet,
            "draft_to": from_addr,
            "draft_subject": data.get("draft_subject", f"Re: {subject}"),
            "draft_body": data.get("draft_body", ""),
            "reasoning": data.get("reasoning", ""),
            "urgency": data.get("urgency", "normal")
        }
    except Exception as e:
        print(f"[EMAIL DRAFTER] Parse failed: {e}")
        return None


async def scan_and_draft_replies() -> Dict:
    """
    Tony's main proactive email drafting scan.
    Fetches recent inbox, identifies emails needing replies, drafts them,
    stores in DB, and creates alerts for Matthew.
    """
    print("[EMAIL DRAFTER] Starting proactive email draft scan...")
    results = {"drafts_created": 0, "emails_checked": 0, "errors": []}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(
                f"{BACKEND_URL}/api/v1/gmail/search",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"},
                params={"query": "is:unread newer_than:2d", "max_per_account": 10}
            )
            emails = r.json().get("results", [])
    except Exception as e:
        print(f"[EMAIL DRAFTER] Email fetch failed: {e}")
        return results

    results["emails_checked"] = len(emails)

    for email in emails:
        try:
            draft = await _needs_reply(email)
            if not draft:
                continue

            draft_id = save_draft(
                account=draft["account"],
                message_id=draft["message_id"],
                from_addr=draft["from"],
                subject=draft["subject"],
                snippet=draft["snippet"],
                draft_to=draft["draft_to"],
                draft_subject=draft["draft_subject"],
                draft_body=draft["draft_body"],
                reasoning=draft["reasoning"]
            )

            if draft_id:
                results["drafts_created"] += 1
                # Create an alert so Matthew knows
                from app.core.proactive import create_alert
                create_alert(
                    alert_type="email_draft",
                    title=f"Draft ready: {draft['subject'][:60]}",
                    body=f"From: {draft['from']}\nTony has drafted a reply. Say 'show my drafts' to review.",
                    priority=draft["urgency"] if draft["urgency"] in ("urgent", "high") else "normal",
                    source=draft["account"],
                    expires_hours=72
                )
                print(f"[EMAIL DRAFTER] Draft created for: {draft['subject']}")

        except Exception as e:
            results["errors"].append(str(e))
            print(f"[EMAIL DRAFTER] Draft error for {email.get('subject','?')}: {e}")

    print(f"[EMAIL DRAFTER] Done. {results['drafts_created']} drafts created from {results['emails_checked']} emails.")
    return results
