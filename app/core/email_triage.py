"""
Email triage — takes raw Gmail emails and applies LLM-based categorisation
and action suggestions. 

For each email:
  - urgency: urgent / normal / low / spam
  - category: personal / work / financial / legal / retail / admin / newsletter
  - needs_reply: True/False + suggested draft if True
  - summary: one sentence
  - action: what Matthew should do ('reply', 'pay', 'ignore', 'read', 'archive')

Results are cached so the same emails aren't re-triaged on every check.
"""
import os
import json
import hashlib
import psycopg2
import httpx
from typing import List, Dict, Optional
from datetime import datetime


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_triage_tables():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_email_triage (
                email_hash TEXT PRIMARY KEY,
                message_id TEXT,
                account TEXT,
                sender TEXT,
                subject TEXT,
                urgency TEXT,
                category TEXT,
                needs_reply BOOLEAN DEFAULT FALSE,
                reply_draft TEXT,
                summary TEXT,
                action TEXT,
                raw_triage JSONB,
                triaged_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_triage_urgency
            ON tony_email_triage(urgency, triaged_at DESC)
        """)
        cur.close()
        conn.close()
        print("[TRIAGE] Tables initialised")
    except Exception as e:
        print(f"[TRIAGE] Init failed: {e}")


def _hash_email(email: Dict) -> str:
    """Stable hash for dedup. Uses message_id or subject+sender."""
    key = email.get("message_id") or f"{email.get('from','')}|{email.get('subject','')}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


async def _triage_with_gemini(email: Dict) -> Dict:
    """Run a single email through Gemini for categorisation + action suggestion."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"urgency": "normal", "category": "unknown", "needs_reply": False,
                "summary": email.get("subject", ""), "action": "read"}

    sender = email.get("from", "")
    subject = email.get("subject", "")
    body = email.get("body", email.get("snippet", ""))[:2000]

    prompt = f"""Triage this email for Matthew. Matthew works nights at a care home (3-on/3-off).
He has multiple Gmail accounts and gets a mix of personal, work, financial, legal, retail, and admin emails.

From: {sender}
Subject: {subject}

Body (truncated):
{body}

Return STRICT JSON:
{{
  "urgency": "urgent" | "normal" | "low" | "spam",
  "category": "personal" | "work" | "financial" | "legal" | "retail" | "admin" | "newsletter" | "spam",
  "needs_reply": true | false,
  "reply_draft": "short draft reply if needs_reply=true, else empty",
  "summary": "one-sentence description of what this email is about",
  "action": "reply" | "pay" | "ignore" | "read" | "archive" | "delete"
}}

Rules:
- URGENT = requires action within 24h (time-sensitive, from a real person, legal deadline, family emergency)
- NORMAL = should look at this week
- LOW = informational, no action needed
- SPAM = marketing, newsletters, unsolicited
- reply_draft should be short (2-3 sentences), friendly British English, in Matthew's voice (direct, warm, not formal)
- If it's clearly automated notification (order confirmation, delivery update), needs_reply=false

Respond with JSON only, no prose:"""

    try:
        from app.core import gemini_client
        resp = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": 800, "temperature": 0.2},
            timeout=20.0,
            caller_context="email_triage",
        )
        response = gemini_client.extract_text(resp)

        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first < 0 or last < 0:
            return {"urgency": "normal", "category": "unknown", "needs_reply": False,
                    "summary": subject, "action": "read"}
        result = json.loads(cleaned[first:last+1])

        # Sanitise
        return {
            "urgency": result.get("urgency", "normal"),
            "category": result.get("category", "unknown"),
            "needs_reply": bool(result.get("needs_reply", False)),
            "reply_draft": str(result.get("reply_draft", ""))[:2000],
            "summary": str(result.get("summary", subject))[:300],
            "action": result.get("action", "read"),
        }
    except Exception as e:
        print(f"[TRIAGE] Gemini error: {e}")
        return {"urgency": "normal", "category": "unknown", "needs_reply": False,
                "summary": subject, "action": "read"}


def _get_cached_triage(email_hash: str) -> Optional[Dict]:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT urgency, category, needs_reply, reply_draft, summary, action
            FROM tony_email_triage WHERE email_hash = %s
        """, (email_hash,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return {"urgency": row[0], "category": row[1], "needs_reply": row[2],
                "reply_draft": row[3], "summary": row[4], "action": row[5]}
    except Exception:
        return None


def _save_triage(email: Dict, triage: Dict):
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_email_triage
              (email_hash, message_id, account, sender, subject,
               urgency, category, needs_reply, reply_draft, summary, action, raw_triage)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (email_hash) DO UPDATE SET
              urgency = EXCLUDED.urgency,
              category = EXCLUDED.category,
              needs_reply = EXCLUDED.needs_reply,
              reply_draft = EXCLUDED.reply_draft,
              summary = EXCLUDED.summary,
              action = EXCLUDED.action,
              triaged_at = NOW()
        """, (
            _hash_email(email),
            email.get("message_id", ""),
            email.get("account", ""),
            email.get("from", ""),
            email.get("subject", ""),
            triage["urgency"], triage["category"], triage["needs_reply"],
            triage.get("reply_draft", ""), triage["summary"], triage["action"],
            json.dumps(triage),
        ))
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[TRIAGE] Save failed: {e}")


async def triage_emails(emails: List[Dict], use_cache: bool = True) -> List[Dict]:
    """Triage a batch. Returns emails enriched with triage fields."""
    results = []
    for email in emails:
        h = _hash_email(email)
        cached = _get_cached_triage(h) if use_cache else None
        if cached:
            triage = cached
        else:
            triage = await _triage_with_gemini(email)
            _save_triage(email, triage)
        results.append({**email, "triage": triage, "email_hash": h})
    return results


async def get_smart_digest() -> Dict:
    """
    Full morning-style email digest with LLM triage.
    Returns categorised lists + drafted replies ready for approval.
    """
    from app.core.gmail_service import get_all_accounts, list_emails
    accounts = get_all_accounts()
    if not accounts:
        return {"ok": False, "error": "No Gmail accounts connected"}

    all_emails = []
    for account in accounts:
        try:
            emails = await list_emails(
                account, query="is:unread newer_than:3d",
                max_results=20, label=""
            )
            all_emails.extend(emails)
        except Exception as e:
            print(f"[TRIAGE] List failed for {account}: {e}")

    if not all_emails:
        return {"ok": True, "count": 0, "digest": "All caught up — no unread in last 3 days."}

    triaged = await triage_emails(all_emails, use_cache=True)

    by_urgency = {"urgent": [], "normal": [], "low": [], "spam": []}
    needs_reply = []

    for e in triaged:
        t = e["triage"]
        by_urgency[t["urgency"]].append(e)
        if t["needs_reply"]:
            needs_reply.append(e)

    # Build a human-readable digest
    lines = []
    if by_urgency["urgent"]:
        lines.append(f"**URGENT ({len(by_urgency['urgent'])})**")
        for e in by_urgency["urgent"][:5]:
            sender = e.get("from", "").split("<")[0].strip() or "Unknown"
            lines.append(f"• {sender}: {e['triage']['summary']}")

    if needs_reply:
        lines.append(f"\n**{len(needs_reply)} need a reply**")
        for e in needs_reply[:5]:
            sender = e.get("from", "").split("<")[0].strip() or "Unknown"
            lines.append(f"• {sender} — {e['triage']['summary']}")

    if by_urgency["normal"]:
        lines.append(f"\n**Normal priority ({len(by_urgency['normal'])})** — look when you can")

    if by_urgency["low"] or by_urgency["spam"]:
        skipped = len(by_urgency["low"]) + len(by_urgency["spam"])
        lines.append(f"\n{skipped} low-priority / newsletters — safe to archive")

    return {
        "ok": True,
        "count": len(all_emails),
        "urgent_count": len(by_urgency["urgent"]),
        "needs_reply_count": len(needs_reply),
        "digest": "\n".join(lines),
        "by_urgency": {k: len(v) for k, v in by_urgency.items()},
        "triaged_emails": triaged[:30],  # include full detail for UI
    }
