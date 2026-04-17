"""
Case builder endpoints — ingest emails + attachments into RAG,
then query semantically for legal/complaint case building.
"""
import asyncio
from fastapi import APIRouter, Depends, BackgroundTasks
from app.core.security import verify_token
from app.core.rag import (
    init_rag_tables, ingest_email_to_case, search_case,
    get_case_by_name, list_cases, embed_text
)
from app.core.gmail_service import (
    get_all_accounts, refresh_access_token
)
import httpx, base64, json, os, psycopg2

router = APIRouter()


def db_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def fetch_full_email(account: str, message_id: str, token: str) -> dict:
    """Fetch complete email with full body and attachment metadata."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"format": "full"}
        )
        if resp.status_code != 200:
            return {}
        data = resp.json()
        headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}

        def extract_body_and_attachments(payload):
            body_text = ""
            attachments = []
            mime = payload.get("mimeType", "")
            body_data = payload.get("body", {}).get("data", "")
            if body_data:
                try:
                    decoded = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
                    if "text" in mime:
                        body_text += decoded
                except Exception:
                    pass
            filename = payload.get("filename", "")
            if filename and payload.get("body", {}).get("attachmentId"):
                attachments.append({"name": filename, "mimeType": mime,
                                    "attachmentId": payload["body"]["attachmentId"],
                                    "messageId": message_id})
            for part in payload.get("parts", []):
                sub_body, sub_att = extract_body_and_attachments(part)
                body_text += sub_body
                attachments.extend(sub_att)
            return body_text, attachments

        body, attachments = extract_body_and_attachments(data.get("payload", {}))
        if not body:
            body = data.get("snippet", "")

        return {
            "id": message_id,
            "account": account,
            "subject": headers.get("Subject", "(no subject)"),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
            "body": body[:100000],
            "attachments": attachments
        }


async def download_attachment(token: str, message_id: str, attachment_id: str,
                               filename: str, mime: str) -> dict:
    """Download attachment and extract text."""
    from app.core.rag import extract_pdf_text
    import zipfile, io, re
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/attachments/{attachment_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code != 200:
                return {"name": filename, "text": ""}
            raw = base64.urlsafe_b64decode(resp.json().get("data", "") + "==")

        text = ""
        if "pdf" in mime or filename.lower().endswith(".pdf"):
            text = extract_pdf_text(raw)
        elif "text" in mime or filename.lower().endswith(".txt"):
            text = raw.decode("utf-8", errors="replace")[:50000]
        elif filename.lower().endswith((".doc", ".docx")):
            try:
                z = zipfile.ZipFile(io.BytesIO(raw))
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
                text = " ".join(re.findall(r'<w:t[^>]*>(.*?)</w:t>', xml))[:50000]
            except Exception:
                pass
        return {"name": filename, "text": text}
    except Exception as e:
        print(f"[CASE] Attachment download failed {filename}: {e}")
        return {"name": filename, "text": ""}


async def run_ingestion(case_id: int, query: str):
    """Background task — fetch all emails matching query, ingest everything."""
    try:
        await _run_ingestion_inner(case_id, query)
    except BaseException as e:
        import traceback
        print(f"[CASE] FATAL in run_ingestion: {e}")
        traceback.print_exc()
        try:
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("UPDATE cases SET status=%s WHERE id=%s", (f"error: {str(e)[:100]}", case_id))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

async def _run_ingestion_inner(case_id: int, query: str):
    """Inner ingestion logic."""
    conn = None
    cur = None
    try:
        conn = db_conn()
        cur = conn.cursor()
    except Exception as e:
        print(f"[CASE] DB connection failed: {e}")
        return
    try:
        cur.execute("UPDATE cases SET status='ingesting', updated_at=NOW() WHERE id=%s", (case_id,))
        conn.commit()

        accounts = get_all_accounts()
        total_emails = 0
        total_chunks = 0

        for account in accounts:
            token = await refresh_access_token(account)
            page_token = None
            email_ids = []

            # Paginate through ALL matching emails
            async with httpx.AsyncClient(timeout=60.0) as client:
                while True:
                    params = {"maxResults": 50, "q": query}
                    if page_token:
                        params["pageToken"] = page_token
                    resp = await client.get(
                        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                        headers={"Authorization": f"Bearer {token}"},
                        params=params
                    )
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    msgs = data.get("messages", [])
                    email_ids.extend([m["id"] for m in msgs])
                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break

            print(f"[CASE] {account}: found {len(email_ids)} emails")

            # Fetch and ingest each email
            for email_id in email_ids:
                try:
                    email = await fetch_full_email(account, email_id, token)
                    if not email:
                        continue

                    # Download all attachments
                    att_texts = []
                    for att in email.get("attachments", []):
                        att_data = await download_attachment(
                            token, email_id,
                            att["attachmentId"], att["name"], att["mimeType"]
                        )
                        if att_data["text"]:
                            att_texts.append(att_data)

                    chunks = await ingest_email_to_case(
                        case_id=case_id,
                        email_id=email_id,
                        account=account,
                        sender=email.get("from", ""),
                        subject=email.get("subject", ""),
                        date=email.get("date", ""),
                        body=email.get("body", ""),
                        attachments=att_texts
                    )
                    total_chunks += chunks
                    total_emails += 1
                    # Small delay to avoid hammering Gmail API
                    await asyncio.sleep(0.1)
                except Exception as e:
                    print(f"[CASE] Failed to ingest {email_id}: {e}")

        cur.execute("""
            UPDATE cases SET status='ready', total_emails=%s, total_chunks=%s, updated_at=NOW()
            WHERE id=%s
        """, (total_emails, total_chunks, case_id))
        conn.commit()
        print(f"[CASE] Ingestion complete: {total_emails} emails, {total_chunks} chunks")
    except Exception as e:
        print(f"[CASE] Ingestion failed: {e}")
        import traceback
        traceback.print_exc()
        try:
            cur.execute("UPDATE cases SET status=%s, updated_at=NOW() WHERE id=%s", (f"error: {str(e)[:200]}", case_id))
            conn.commit()
        except Exception:
            pass
    finally:
        try:
            if cur: cur.close()
            if conn: conn.close()
        except Exception:
            pass


@router.post("/cases/build")
async def build_case(
    name: str,
    query: str,
    background_tasks: BackgroundTasks,
    _=Depends(verify_token)
):
    """
    Start building a case. Fetches ALL emails matching query across all accounts,
    ingests full bodies + attachments into RAG vector store.
    name: friendly name e.g. "Western Circle"
    query: Gmail search query e.g. "from:westerncircle" or "western circle loan"
    """
    init_rag_tables()
    conn = db_conn()
    cur = conn.cursor()
    # Check if case already exists
    cur.execute("SELECT id, status FROM cases WHERE LOWER(name) = LOWER(%s)", (name,))
    existing = cur.fetchone()
    if existing:
        cur.close()
        conn.close()
        return {"case_id": existing[0], "status": existing[1],
                "message": f"Case '{name}' already exists with status: {existing[1]}"}
    cur.execute(
        "INSERT INTO cases (name, query) VALUES (%s, %s) RETURNING id",
        (name, query)
    )
    case_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    background_tasks.add_task(run_ingestion, case_id, query)
    return {
        "case_id": case_id,
        "name": name,
        "query": query,
        "status": "ingesting",
        "message": f"Ingestion started. Tony is reading all emails matching '{query}' across all accounts including attachments. Check /cases/status/{case_id} for progress."
    }


@router.get("/cases/status/{case_id}")
async def case_status(case_id: int, _=Depends(verify_token)):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, query, status, total_emails, total_chunks, updated_at FROM cases WHERE id=%s", (case_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return {"error": "Case not found"}
    return {"id": row[0], "name": row[1], "query": row[2], "status": row[3],
            "total_emails": row[4], "total_chunks": row[5], "updated_at": str(row[6])}


@router.get("/cases")
async def get_cases(_=Depends(verify_token)):
    return {"cases": list_cases()}


@router.post("/cases/query")
async def query_case(
    case_id: int,
    question: str,
    top_k: int = 20,
    _=Depends(verify_token)
):
    """
    Semantic search within a case. Returns most relevant chunks for the question.
    Tony uses this to answer precise questions with exact quotes.
    """
    results = await search_case(case_id, question, top_k)
    return {"results": results, "count": len(results)}


@router.delete("/cases/{case_id}")
async def delete_case(case_id: int, _=Depends(verify_token)):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM cases WHERE id=%s", (case_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"deleted": True}


@router.get("/cases/test")
async def test_case_ingestion(_=Depends(verify_token)):
    """Test endpoint - diagnoses embedding and Gmail access."""
    import os, traceback
    results = {}
    # Test embedding
    try:
        from app.core.rag import embed_text, init_rag_tables
        init_rag_tables()
        vec = await embed_text("test Nova RAG pipeline")
        results["embedding"] = {"ok": bool(vec), "dims": len(vec) if vec else 0}
    except Exception as e:
        results["embedding"] = {"ok": False, "error": str(e), "trace": traceback.format_exc()[-500:]}
    # Test Gmail
    try:
        accounts = get_all_accounts()
        token = await refresh_access_token(accounts[0]) if accounts else None
        gmail_ok = False
        if token:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"maxResults": 1}
                )
                gmail_ok = r.status_code == 200
        results["gmail"] = {"ok": gmail_ok, "accounts": accounts}
    except Exception as e:
        results["gmail"] = {"ok": False, "error": str(e)}
    return results


@router.get("/cases/list-models")
async def list_gemini_models(_=Depends(verify_token)):
    """List available Gemini models to find correct embedding model name."""
    import os
    key = os.environ.get("GEMINI_API_KEY", "")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        )
        if resp.status_code != 200:
            return {"error": resp.status_code, "text": resp.text[:500]}
        models = resp.json().get("models", [])
        embedding_models = [
            m["name"] for m in models
            if "embed" in m["name"].lower() or "embed" in m.get("displayName","").lower()
        ]
        return {"embedding_models": embedding_models, "total_models": len(models)}


@router.get("/cases/search-preview")
async def search_preview(query: str, _=Depends(verify_token)):
    """Preview how many emails a query would match before building a case."""
    accounts = get_all_accounts()
    results = {}
    total = 0
    for account in accounts:
        try:
            token = await refresh_access_token(account)
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"q": query, "maxResults": 1}
                )
                data = resp.json()
                count = data.get("resultSizeEstimate", 0)
                sample = data.get("messages", [])
                results[account] = {"estimated_count": count, "has_results": len(sample) > 0}
                total += count
        except Exception as e:
            results[account] = {"error": str(e)}
    return {"query": query, "total_estimate": total, "per_account": results}


@router.post("/cases/reset-tables")
async def reset_tables(_=Depends(verify_token)):
    """Drop and recreate case_chunks table with correct vector dimensions."""
    try:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS case_chunks CASCADE")
        cur.execute("DROP TABLE IF EXISTS cases CASCADE")
        conn.commit()
        cur.close()
        conn.close()
        from app.core.rag import init_rag_tables
        init_rag_tables()
        return {"ok": True, "message": "Tables dropped and recreated with vector(3072)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
