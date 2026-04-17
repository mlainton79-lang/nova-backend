import os
import base64
import httpx
import psycopg2
from datetime import datetime, timedelta
from typing import List
import urllib.parse

GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")
GMAIL_REDIRECT_URI = os.environ.get("GMAIL_REDIRECT_URI", "https://web-production-be42b.up.railway.app/api/v1/gmail/auth/callback")

SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/userinfo.email"
]

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")

def init_gmail_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gmail_accounts (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                token_expiry TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[GMAIL] Table init failed: {e}")

def get_auth_url(state: str = "nova") -> str:
    params = {
        "client_id": GMAIL_CLIENT_ID,
        "redirect_uri": GMAIL_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GMAIL_CLIENT_ID,
                "client_secret": GMAIL_CLIENT_SECRET,
                "redirect_uri": GMAIL_REDIRECT_URI,
                "grant_type": "authorization_code"
            }
        )
        resp.raise_for_status()
        return resp.json()

async def refresh_access_token(email: str) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT access_token, refresh_token, token_expiry FROM gmail_accounts WHERE email = %s", (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise ValueError(f"No account found for {email}")
    access_tok, refresh_tok, expiry = row
    if expiry and datetime.utcnow() < expiry - timedelta(minutes=5):
        return access_tok
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={"refresh_token": refresh_tok, "client_id": GMAIL_CLIENT_ID, "client_secret": GMAIL_CLIENT_SECRET, "grant_type": "refresh_token"}
        )
        resp.raise_for_status()
        data = resp.json()
    new_access = data["access_token"]
    new_expiry = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE gmail_accounts SET access_token = %s, token_expiry = %s, updated_at = NOW() WHERE email = %s", (new_access, new_expiry, email))
    conn.commit()
    cur.close()
    conn.close()
    return new_access

async def get_user_email(access_token: str) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get("https://www.googleapis.com/oauth2/v1/userinfo", headers={"Authorization": f"Bearer {access_token}"})
        resp.raise_for_status()
        return resp.json()["email"]

def save_account(email: str, access_token: str, refresh_tok: str, expires_in: int):
    expiry = datetime.utcnow() + timedelta(seconds=expires_in)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO gmail_accounts (email, access_token, refresh_token, token_expiry)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (email) DO UPDATE SET
            access_token = EXCLUDED.access_token,
            refresh_token = EXCLUDED.refresh_token,
            token_expiry = EXCLUDED.token_expiry,
            updated_at = NOW()
    """, (email, access_token, refresh_tok, expiry))
    conn.commit()
    cur.close()
    conn.close()

def get_all_accounts() -> List[str]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT email FROM gmail_accounts ORDER BY created_at")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r[0] for r in rows]

async def list_emails(email: str, query: str = "", max_results: int = 20, label: str = "INBOX") -> list:
    token = await refresh_access_token(email)
    async with httpx.AsyncClient(timeout=30.0) as client:
        params = {"maxResults": max_results}
        if label:
            params["labelIds"] = [label]
        if query:
            params["q"] = query
        resp = await client.get("https://gmail.googleapis.com/gmail/v1/users/me/messages", headers={"Authorization": f"Bearer {token}"}, params=params)
        resp.raise_for_status()
        messages = resp.json().get("messages", [])
        results = []
        for msg in messages[:max_results]:
            detail = await client.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}", headers={"Authorization": f"Bearer {token}"}, params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date", "To"]})
            if detail.status_code == 200:
                d = detail.json()
                headers = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
                results.append({"id": msg["id"], "account": email, "subject": headers.get("Subject", "(no subject)"), "from": headers.get("From", ""), "to": headers.get("To", ""), "date": headers.get("Date", ""), "snippet": d.get("snippet", ""), "labels": d.get("labelIds", [])})
        return results

async def get_email_body(email: str, message_id: str) -> dict:
    token = await refresh_access_token(email)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}", headers={"Authorization": f"Bearer {token}"}, params={"format": "full"})
        resp.raise_for_status()
        data = resp.json()
        headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
        def extract_body(payload):
            if payload.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
            for part in payload.get("parts", []):
                if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                    return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            for part in payload.get("parts", []):
                r = extract_body(part)
                if r:
                    return r
            return data.get("snippet", "")
        return {"id": message_id, "account": email, "subject": headers.get("Subject", "(no subject)"), "from": headers.get("From", ""), "to": headers.get("To", ""), "date": headers.get("Date", ""), "body": extract_body(data.get("payload", {}))[:50000], "labels": data.get("labelIds", [])}

async def send_email(email: str, to: str, subject: str, body: str, reply_to_id: str = None) -> bool:
    token = await refresh_access_token(email)
    message_str = f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}"
    raw = base64.urlsafe_b64encode(message_str.encode()).decode()
    payload = {"raw": raw}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload)
        return resp.status_code == 200

async def trash_email(email: str, message_id: str) -> bool:
    token = await refresh_access_token(email)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/trash", headers={"Authorization": f"Bearer {token}"})
        return resp.status_code == 200

async def delete_email(email: str, message_id: str) -> bool:
    token = await refresh_access_token(email)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}", headers={"Authorization": f"Bearer {token}"})
        return resp.status_code == 204

async def search_all_accounts(query: str, max_per_account: int = 10) -> list:
    accounts = get_all_accounts()
    all_results = []
    for account in accounts:
        try:
            results = await list_emails(account, query=query, max_results=max_per_account, label="")
            all_results.extend(results)
        except Exception as e:
            print(f"[GMAIL] Search failed for {account}: {e}")
    return sorted(all_results, key=lambda x: x.get("date", ""), reverse=True)

async def get_morning_summary() -> str:
    accounts = get_all_accounts()
    if not accounts:
        return "No Gmail accounts connected."
    all_emails = []
    errors = []
    for account in accounts:
        try:
            # Try unread from last 3 days to be safe with timezone drift
            emails = await list_emails(account, query="is:unread newer_than:3d", max_results=20, label="")
            all_emails.extend(emails)
        except Exception as e:
            err_msg = f"{account}: {str(e)}"
            errors.append(err_msg)
            print(f"[GMAIL] Morning summary failed for {account}: {e}")
    if not all_emails:
        if errors:
            return f"Gmail error(s): {'; '.join(errors)}"
        return "No unread emails in the last 3 days across all accounts."
    lines = [f"📧 {len(all_emails)} unread email(s) across {len(accounts)} account(s):\n"]
    for e in all_emails[:15]:
        lines.append(f"• [{e['account']}] From: {e['from']} — {e['subject']}")
        if e.get("snippet"):
            lines.append(f"  {e['snippet'][:120]}")
    if errors:
        lines.append(f"\n⚠️ Errors on: {', '.join(errors)}")
    return "\n".join(lines)
