import os
import asyncio
import base64
import httpx
import psycopg2
from datetime import datetime, timedelta
from typing import List, Optional
import urllib.parse

from app.observability import EVENT_TYPES, EventSeverity, record_run_event

GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")
GMAIL_REDIRECT_URI = os.environ.get("GMAIL_REDIRECT_URI", "https://web-production-be42b.up.railway.app/api/v1/gmail/auth/callback")

SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/calendar",
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

async def refresh_access_token(email: str) -> Optional[str]:
    """Return a valid access token for `email`, refreshing via Google OAuth if
    needed. Returns None on any failure (no account row, revoked refresh
    token, network error, DB error) and logs a WARNING event so callers and
    `/api/v1/status` see the account in a "needs re-auth" state.

    Previously this raised on revoked refresh tokens (Google returns 400/401
    on a stale grant), which propagated uncaught through `list_emails`,
    `send_email`, etc. and surfaced as HTTP 500 from any Gmail-touching
    endpoint. Closing that gap is P0.2 from the 2026-05-28 working-state
    audit (nova-docs/ops/evidence/2026-05-28/WORKING_STATE_AUDIT_*.md).
    """
    try:
        conn = get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT access_token, refresh_token, token_expiry FROM gmail_accounts WHERE email = %s",
                    (email,),
                )
                row = cur.fetchone()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if not row:
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.WARNING,
                subsystem="gmail.refresh",
                message=f"refresh_access_token: no gmail_accounts row for {email}",
                metadata={"email": email},
            )
            return None
        access_tok, refresh_tok, expiry = row
        if expiry and datetime.utcnow() < expiry - timedelta(minutes=5):
            return access_tok

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={"refresh_token": refresh_tok, "client_id": GMAIL_CLIENT_ID, "client_secret": GMAIL_CLIENT_SECRET, "grant_type": "refresh_token"}
                )
        except httpx.TimeoutException as e:
            record_run_event(
                event_type=EVENT_TYPES["PROVIDER_TIMEOUT"],
                severity=EventSeverity.WARNING,
                subsystem="gmail.refresh",
                message="refresh_access_token: Google token endpoint timeout",
                error_class=type(e).__name__,
                error_message=str(e),
                metadata={"email": email},
            )
            return None

        if resp.status_code != 200:
            # Google returns 400 invalid_grant on a revoked / expired refresh
            # token. Body may include a short error code; don't echo any
            # token-shaped values into the event metadata.
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.WARNING,
                subsystem="gmail.refresh",
                message=f"refresh_access_token: Google returned {resp.status_code} (account needs re-auth)",
                metadata={"email": email, "status": resp.status_code},
            )
            return None

        data = resp.json()
        new_access = data.get("access_token")
        if not new_access:
            record_run_event(
                event_type=EVENT_TYPES["PROVIDER_ERROR"],
                severity=EventSeverity.ERROR,
                subsystem="gmail.refresh",
                message="refresh_access_token: response missing access_token field",
                metadata={"email": email},
            )
            return None

        new_expiry = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))
        try:
            conn = get_conn()
            try:
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE gmail_accounts SET access_token = %s, token_expiry = %s, updated_at = NOW() WHERE email = %s",
                        (new_access, new_expiry, email),
                    )
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            # The new token is valid in-memory; persistence failure is non-
            # fatal for this call (we'll just re-mint on the next read) but
            # worth recording.
            record_run_event(
                event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
                severity=EventSeverity.WARNING,
                subsystem="gmail.refresh",
                message="refresh_access_token: DB update failed; returning new token unpersisted",
                error_class=type(e).__name__,
                error_message=str(e),
                metadata={"email": email},
            )
        return new_access
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
            severity=EventSeverity.ERROR,
            subsystem="gmail.refresh",
            message="refresh_access_token failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"email": email},
        )
        return None

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
    if not token:
        return []
    async with httpx.AsyncClient(timeout=8.0) as client:
        params = {"maxResults": min(max_results, 10)}
        if label:
            params["labelIds"] = [label]
        if query:
            params["q"] = query
        resp = await client.get("https://gmail.googleapis.com/gmail/v1/users/me/messages", headers={"Authorization": f"Bearer {token}"}, params=params)
        resp.raise_for_status()
        messages = resp.json().get("messages", [])[:min(max_results, 10)]
        if not messages:
            return []

        # Parallel per-message detail fetch. Previously a serial loop that could
        # take up to N × httpx-timeout seconds in the worst case (10 × 8s = 80s);
        # `get_morning_summary` then ran this across 4 accounts inside an outer
        # 15s wait_for cap, so a single slow account blew the budget and the
        # entire Gmail context block came back empty. Parallel inner fan-out
        # bounds per-account work by the slowest single GET (~8s), not the sum.
        async def _fetch_detail(msg):
            try:
                return await client.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date", "To"]},
                )
            except Exception:
                return None

        details = await asyncio.gather(*[_fetch_detail(m) for m in messages])

        results = []
        for msg, detail in zip(messages, details):
            if detail is None or detail.status_code != 200:
                continue
            d = detail.json()
            headers = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
            results.append({"id": msg["id"], "account": email, "subject": headers.get("Subject", "(no subject)"), "from": headers.get("From", ""), "to": headers.get("To", ""), "date": headers.get("Date", ""), "snippet": d.get("snippet", ""), "labels": d.get("labelIds", [])})
        return results

async def get_email_body(email: str, message_id: str) -> dict:
    token = await refresh_access_token(email)
    if not token:
        return {}
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
    if not token:
        return False

    # N1.email-draft-A: thread replies into the original conversation.
    # Set In-Reply-To + References headers and pass Gmail threadId on the
    # send body. Best-effort: any failure to fetch the original metadata
    # falls through to a non-threaded send rather than blocking the user.
    in_reply_to_header = ""
    references_header = ""
    thread_id = None
    if reply_to_id:
        try:
            async with httpx.AsyncClient(timeout=10.0) as meta_client:
                meta_resp = await meta_client.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{reply_to_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"format": "metadata", "metadataHeaders": ["Message-Id", "References"]},
                )
                if meta_resp.status_code == 200:
                    meta = meta_resp.json()
                    thread_id = meta.get("threadId")
                    headers_list = meta.get("payload", {}).get("headers", [])
                    msg_id_value = next(
                        (h["value"] for h in headers_list if h.get("name", "").lower() == "message-id"),
                        None,
                    )
                    refs_value = next(
                        (h["value"] for h in headers_list if h.get("name", "").lower() == "references"),
                        "",
                    )
                    if msg_id_value:
                        in_reply_to_header = f"In-Reply-To: {msg_id_value}\r\n"
                        references_header = f"References: {(refs_value + ' ' + msg_id_value).strip()}\r\n"
        except Exception as e:
            print(f"[GMAIL] Threading metadata fetch failed for {reply_to_id}: {e}")

    message_str = (
        f"To: {to}\r\n"
        f"Subject: {subject}\r\n"
        f"{in_reply_to_header}"
        f"{references_header}"
        f"\r\n{body}"
    )
    raw = base64.urlsafe_b64encode(message_str.encode()).decode()
    payload = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        body_text = (resp.text or "")[:500]
        parsed = None
        try:
            parsed = resp.json() if resp.status_code == 200 else None
        except Exception:
            parsed = None
        msg_id = (parsed or {}).get("id")
        thread_id = (parsed or {}).get("threadId")

        # Verification read — does Gmail confirm this message in this mailbox?
        verify_status = None
        verify_error = None
        label_ids = []
        if resp.status_code == 200 and msg_id:
            try:
                verify_resp = await client.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"format": "metadata"},
                )
                verify_status = verify_resp.status_code
                if verify_resp.status_code == 200:
                    label_ids = verify_resp.json().get("labelIds", [])
            except Exception as e:
                verify_error = type(e).__name__

        # Profile read — what mailbox does this token actually authenticate as?
        # Directly settles the token/account mismatch hypothesis (where the
        # `account` arg may not match the token's real mailbox).
        profile_email = None
        profile_error = None
        try:
            prof_resp = await client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                headers={"Authorization": f"Bearer {token}"},
            )
            if prof_resp.status_code == 200:
                profile_email = prof_resp.json().get("emailAddress")
            else:
                profile_error = f"http_{prof_resp.status_code}"
        except Exception as e:
            profile_error = type(e).__name__

        # Tighter success contract: status 200 AND a parseable Gmail Message
        # id present. A 200 with no id (or unparseable JSON) is treated as
        # failure rather than silently swallowed.
        success = resp.status_code == 200 and bool(msg_id)
        try:
            record_run_event(
                event_type="gmail_send_observed",
                severity=EventSeverity.INFO if success else EventSeverity.WARNING,
                subsystem="gmail.send",
                message=(
                    f"send to={to} account={email} mailbox={profile_email} "
                    f"status={resp.status_code} id={msg_id} thread={thread_id} "
                    f"labels={label_ids} success={success}"
                ),
                metadata={
                    "account": email,
                    "mailbox_resolved": profile_email,
                    "to": to,
                    "status_code": resp.status_code,
                    "returned_id": msg_id,
                    "returned_thread_id": thread_id,
                    "verified_labels": label_ids,
                    "verification_status_code": verify_status,
                    "verification_error_class": verify_error,
                    "profile_error_class": profile_error,
                    "response_text_preview": body_text,
                },
            )
        except Exception:
            pass
        return success

async def trash_email(email: str, message_id: str) -> bool:
    token = await refresh_access_token(email)
    if not token:
        return False
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/trash", headers={"Authorization": f"Bearer {token}"})
        return resp.status_code == 200

async def delete_email(email: str, message_id: str) -> bool:
    token = await refresh_access_token(email)
    if not token:
        return False
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}", headers={"Authorization": f"Bearer {token}"})
        return resp.status_code == 204

async def build_smart_query(raw_query: str) -> str:
    """Convert natural language to Gmail search operators where possible."""
    import re
    q = raw_query
    # If message contains an email address, use from: operator
    email_match = re.search(r'[\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,}', q)
    if email_match:
        return f"from:{email_match.group()}"
    # If contains "from X" or "emails from X" extract the name
    from_match = re.search(r'(?:from|by)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', q)
    if from_match:
        name = from_match.group(1)
        return f'from:"{name}"'
    return q

async def search_all_accounts(query: str, max_per_account: int = 10, label: str = "") -> list:
    smart_query = await build_smart_query(query)
    # For exact email address searches, limit results to speed up response
    import re as _re
    if _re.search(r'[\w.+\-]+@[\w.\-]+', smart_query):
        max_per_account = min(max_per_account, 5)
    accounts = get_all_accounts()
    all_results = []
    for account in accounts:
        try:
            results = await list_emails(account, query=smart_query, max_results=max_per_account, label=label)
            all_results.extend(results)
        except Exception as e:
            print(f"[GMAIL] Search failed for {account}: {e}")
    return sorted(all_results, key=lambda x: x.get("date", ""), reverse=True)

async def deep_search_account(email: str, query: str, max_results: int = 200) -> list:
    """Paginated search - fetches ALL matching emails up to max_results. For case building etc."""
    token = await refresh_access_token(email)
    if not token:
        return []
    all_messages = []
    page_token = None
    async with httpx.AsyncClient(timeout=60.0) as client:
        while len(all_messages) < max_results:
            params = {"maxResults": min(50, max_results - len(all_messages)), "q": query}
            if page_token:
                params["pageToken"] = page_token
            resp = await client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers={"Authorization": f"Bearer {token}"},
                params=params
            )
            resp.raise_for_status()
            data = resp.json()
            messages = data.get("messages", [])
            if not messages:
                break
            all_messages.extend(messages)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        results = []
        for msg in all_messages:
            detail = await client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                headers={"Authorization": f"Bearer {token}"},
                params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date", "To"]}
            )
            if detail.status_code == 200:
                d = detail.json()
                headers = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
                results.append({
                    "id": msg["id"],
                    "account": email,
                    "subject": headers.get("Subject", "(no subject)"),
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "date": headers.get("Date", ""),
                    "snippet": d.get("snippet", ""),
                    "labels": d.get("labelIds", [])
                })
        return results

async def deep_search_all_accounts(query: str, max_per_account: int = 200) -> list:
    """Search all accounts with pagination - for legal/case building scenarios."""
    accounts = get_all_accounts()
    all_results = []
    for account in accounts:
        try:
            results = await deep_search_account(account, query, max_per_account)
            all_results.extend(results)
        except Exception as e:
            print(f"[GMAIL] Deep search failed for {account}: {e}")
    return sorted(all_results, key=lambda x: x.get("date", ""), reverse=True)

async def get_morning_summary() -> str:
    """Fan out to all connected accounts IN PARALLEL and aggregate unread.

    Previously serial (`for account in accounts: await list_emails(...)`),
    which totalled ~4× per-account time and routinely blew the caller's
    15s outer wait_for cap — leaving the Council's [GMAIL] block silently
    empty and inviting provider fabrication. Parallel via asyncio.gather:
    total runtime is now bounded by the slowest account, not the sum.
    Each per-account failure is captured independently and surfaced as an
    error line in the returned summary; one bad account no longer poisons
    the rest.
    """
    accounts = get_all_accounts()
    if not accounts:
        return "No Gmail accounts connected."

    async def _fetch_one(account: str):
        # Per-account 8s cap. Outer caller wraps the whole gather() in 15s
        # wait_for; without this inner bound, one slow account (stalled OAuth
        # refresh, slow Gmail API for that mailbox) would hold the gather past
        # 15s and the [GMAIL] block would come back empty for every account.
        # 8s lines up with list_emails's httpx client timeout — a healthy
        # account completes well inside it.
        try:
            emails = await asyncio.wait_for(
                list_emails(account, query="is:unread newer_than:3d", max_results=20, label=""),
                timeout=8.0,
            )
            return account, emails, None
        except asyncio.TimeoutError:
            err = "TimeoutError: per-account 8s cap exceeded"
            print(f"[GMAIL] Morning summary failed for {account}: {err}")
            return account, [], err
        except Exception as e:
            err = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            print(f"[GMAIL] Morning summary failed for {account}: {err}")
            return account, [], err

    results = await asyncio.gather(*[_fetch_one(a) for a in accounts])

    all_emails = []
    errors = []
    for account, emails, err in results:
        all_emails.extend(emails)
        if err:
            errors.append(f"{account}: {err}")

    if not all_emails:
        if errors:
            return f"Gmail error(s): {'; '.join(errors)}"
        return "No unread emails in the last 3 days across all accounts."
    lines = [f"📧 {len(all_emails)} unread email(s) across {len(accounts)} account(s):\n"]
    for e in all_emails[:15]:
        sender = e.get("from", "").split("<")[0].strip() or e.get("from", "Unknown")
        subject = e.get("subject", "(no subject)")
        account_short = e["account"].split("@")[0]
        lines.append(f"• [{account_short}] {sender} — {subject}")
    if errors:
        lines.append(f"\n⚠️ Errors on: {', '.join(errors)}")
    return "\n".join(lines)
