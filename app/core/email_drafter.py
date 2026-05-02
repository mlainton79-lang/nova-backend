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


def get_draft_for_send(draft_id: int) -> Optional[Dict]:
    """
    Fetch all fields needed by the send endpoint, including the
    original_message_id trust anchor for threading. Only returns
    pending drafts (sent/dismissed return None).
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, account, original_message_id, original_from,
                   original_subject, draft_to, draft_subject, draft_body,
                   tony_reasoning, status
            FROM tony_email_drafts
            WHERE id = %s AND status = 'pending'
        """, (draft_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0],
            "account": row[1],
            "original_message_id": row[2],
            "original_from": row[3],
            "original_subject": row[4],
            "draft_to": row[5],
            "draft_subject": row[6],
            "draft_body": row[7],
            "reasoning": row[8],
            "status": row[9],
        }
    except Exception as e:
        print(f"[EMAIL DRAFTER] get_draft_for_send failed: {e}")
        return None


def update_draft_fields(draft_id: int, draft_subject: str, draft_body: str) -> bool:
    """
    Persist the final approved subject/body to the draft row before marking
    sent. Audit row reflects what was actually sent, not what was originally
    drafted.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_email_drafts
            SET draft_subject = %s, draft_body = %s
            WHERE id = %s
        """, (draft_subject, draft_body, draft_id))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[EMAIL DRAFTER] update_draft_fields failed: {e}")
        return False


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
        from app.core import gemini_client
        resp = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": max_tokens, "temperature": 0.3},
            timeout=25.0,
            caller_context="email_drafter",
        )
        return gemini_client.extract_text(resp)
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


async def draft_single_reply(query: str, instruction: Optional[str] = None) -> Dict:
    """
    Chat-driven on-demand drafting. Find email by query, draft reply, persist.

    Bypasses the autonomous _needs_reply classifier — Matthew explicitly asked,
    no needs-reply check required.

    Args:
        query: search terms ("Pharmacy2U", "CQC inspection", "Western Circle")
        instruction: optional Matthew-provided guidance ("say delivery time works")

    Returns:
        On success: {"ok": True, "draft_id": int, "matched_email": {...},
                     "draft_subject": str, "draft_body": str}
        On no match: {"ok": False, "error": "no_match", "query": str}
        On multiple matches: {"ok": False, "error": "multiple_matches",
                              "candidates": [{id, from, subject, snippet, account}, ...]}
        On other failure: {"ok": False, "error": "search_failed"|"draft_failed",
                           "details": str}
    """
    from app.core.gmail_service import search_all_accounts, get_email_body

    try:
        matches = await search_all_accounts(query, max_per_account=5)
    except Exception as e:
        return {"ok": False, "error": "search_failed", "details": str(e)}

    if not matches:
        return {"ok": False, "error": "no_match", "query": query}

    if len(matches) > 1:
        # Sort by date desc, take top 5
        sorted_matches = sorted(matches, key=lambda m: m.get("date", ""), reverse=True)[:5]
        candidates = [
            {
                "id": m.get("id"),
                "from": m.get("from", ""),
                "subject": m.get("subject", ""),
                "snippet": m.get("snippet", "")[:200],
                "account": m.get("account", ""),
            }
            for m in sorted_matches
        ]
        return {"ok": False, "error": "multiple_matches", "candidates": candidates}

    # Exactly one match — fetch full body and draft.
    email_meta = matches[0]
    account = email_meta.get("account", "")
    message_id = email_meta.get("id", "")
    from_addr = email_meta.get("from", "")
    subject = email_meta.get("subject", "")
    snippet = email_meta.get("snippet", "")

    try:
        full = await get_email_body(account, message_id)
        body_text = (full.get("body", "") or snippet)[:4000]
    except Exception as e:
        print(f"[EMAIL DRAFTER] body fetch failed for {message_id}: {e}")
        body_text = snippet

    world_context = await _get_world_context()
    instruction_block = (
        f"\n\nMatthew's specific instruction for this reply: {instruction}"
        if instruction else ""
    )

    prompt = f"""You are Tony, Matthew Lainton's personal AI assistant.

Matthew's context:
{world_context}

Matthew has explicitly asked you to draft a reply to this email.{instruction_block}

Email details:
Account: {account}
From: {from_addr}
Subject: {subject}
Full body:
{body_text}

Respond in JSON only:
{{
    "draft_subject": "Re: {subject}",
    "draft_body": "Full email body Tony has drafted for Matthew. British English. Professional but direct. Sign off as Matthew Lainton. Honour Matthew's instruction above. If this is a legal matter, be firm but measured."
}}"""

    response = await _call_gemini(prompt, max_tokens=2000)
    if not response:
        return {"ok": False, "error": "draft_failed", "details": "Gemini returned no response"}

    try:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            return {"ok": False, "error": "draft_failed", "details": "no JSON in Gemini response"}
        data = json.loads(json_match.group())
    except Exception as e:
        return {"ok": False, "error": "draft_failed", "details": f"JSON parse failed: {e}"}

    draft_subject = data.get("draft_subject") or f"Re: {subject}"
    draft_body = data.get("draft_body") or ""

    if not draft_body.strip():
        return {"ok": False, "error": "draft_failed", "details": "empty draft body"}

    reasoning = (
        f"On-demand draft requested by Matthew via chat. Query: '{query}'."
        + (f" Instruction: {instruction}" if instruction else "")
    )

    draft_id = save_draft(
        account=account,
        message_id=message_id,
        from_addr=from_addr,
        subject=subject,
        snippet=snippet,
        draft_to=from_addr,
        draft_subject=draft_subject,
        draft_body=draft_body,
        reasoning=reasoning,
    )

    if not draft_id:
        # save_draft returned None — ON CONFLICT (already drafted for this msg)
        return {
            "ok": False,
            "error": "draft_failed",
            "details": "Draft already exists for this email — open Email Drafts to see it.",
        }

    return {
        "ok": True,
        "draft_id": draft_id,
        "matched_email": {
            "id": message_id,
            "from": from_addr,
            "subject": subject,
            "account": account,
        },
        "draft_subject": draft_subject,
        "draft_body": draft_body,
    }
