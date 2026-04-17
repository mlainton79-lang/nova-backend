"""
RAG (Retrieval Augmented Generation) pipeline for Nova.
Handles chunking, embedding, storage and retrieval of case documents.
Uses pgvector for similarity search and Gemini for free embeddings.
"""
import os
import json
import base64
import httpx
import psycopg2
from typing import List, Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
EMBEDDING_MODEL = "text-embedding-004"
CHUNK_SIZE = 800        # tokens approx — characters / 4
CHUNK_OVERLAP = 100


def get_conn():
    conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
    try:
        from pgvector.psycopg2 import register_vector
        register_vector(conn)
    except Exception:
        pass  # pgvector registration optional — falls back to JSON embedding strings
    return conn


def init_rag_tables():
    """Create pgvector extension and case document tables."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Enable pgvector
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        # Case index — one row per case
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                query TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                total_emails INT DEFAULT 0,
                total_chunks INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # Document chunks with embeddings
        cur.execute("""
            CREATE TABLE IF NOT EXISTS case_chunks (
                id SERIAL PRIMARY KEY,
                case_id INT REFERENCES cases(id) ON DELETE CASCADE,
                email_id TEXT,
                account TEXT,
                sender TEXT,
                subject TEXT,
                email_date TEXT,
                chunk_index INT,
                source_type TEXT DEFAULT 'email_body',
                attachment_name TEXT,
                content TEXT NOT NULL,
                embedding vector(768),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        # ivfflat index requires data to exist first — create separately, ignore if fails
        try:
            cur.execute("""
                CREATE INDEX IF NOT EXISTS case_chunks_embedding_idx
                ON case_chunks USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 50)
            """)
            conn.commit()
        except Exception as idx_err:
            print(f"[RAG] Index creation skipped (will retry after data inserted): {idx_err}")
            conn.rollback()
        cur.close()
        conn.close()
        print("[RAG] Tables initialised")
    except Exception as e:
        print(f"[RAG] Table init failed: {e}")
        try:
            conn.rollback()
            cur.close()
            conn.close()
        except Exception:
            pass


async def embed_text(text: str) -> Optional[List[float]]:
    """Get embedding vector from Gemini free tier. Tries multiple models."""
    if not text.strip():
        return None
    models_to_try = ["gemini-embedding-exp-03-07", "text-embedding-004", "models/embedding-001"]
    async with httpx.AsyncClient(timeout=30.0) as client:
        for model in models_to_try:
            try:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model.lstrip("models/")}:embedContent?key={GEMINI_API_KEY}",
                    json={"model": f"models/{model}", "content": {"parts": [{"text": text[:8000]}]}}
                )
                if resp.status_code == 200:
                    values = resp.json().get("embedding", {}).get("values")
                    if values:
                        return values
                    print(f"[RAG] Embed {model}: 200 but no values. Response: {resp.text[:200]}")
                else:
                    print(f"[RAG] Embed {model}: {resp.status_code} — {resp.text[:200]}")
            except Exception as e:
                print(f"[RAG] Embed {model} exception: {e}")
    return None


def chunk_text(text: str, source_label: str = "") -> List[str]:
    """Split text into overlapping chunks."""
    if not text:
        return []
    chars_per_chunk = CHUNK_SIZE * 4
    overlap = CHUNK_OVERLAP * 4
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chars_per_chunk, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using basic parsing."""
    try:
        import re
        text = pdf_bytes.decode("latin-1", errors="replace")
        # Extract text between BT/ET markers (basic PDF text extraction)
        parts = re.findall(r'BT\s*(.*?)\s*ET', text, re.DOTALL)
        extracted = []
        for part in parts:
            strings = re.findall(r'\((.*?)\)', part)
            extracted.extend(strings)
        result = " ".join(extracted)
        if len(result) < 100:
            # Fallback: grab readable ASCII runs
            result = " ".join(re.findall(r'[A-Za-z0-9 .,!?;:\-\'\"£$%\n]{10,}', text))
        return result[:50000]
    except Exception as e:
        print(f"[RAG] PDF extract failed: {e}")
        return ""


async def extract_attachment_text(part: dict, token: str, account: str) -> tuple[str, str]:
    """Download and extract text from an email attachment. Returns (text, filename)."""
    filename = part.get("filename", "attachment")
    mime = part.get("mimeType", "")
    body = part.get("body", {})
    attachment_id = body.get("attachmentId")
    if not attachment_id:
        return "", filename
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/placeholder/attachments/{attachment_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code != 200:
                return "", filename
            data = resp.json().get("data", "")
            raw = base64.urlsafe_b64decode(data + "==")
        if "pdf" in mime or filename.lower().endswith(".pdf"):
            return extract_pdf_text(raw), filename
        elif "text" in mime or filename.lower().endswith(".txt"):
            return raw.decode("utf-8", errors="replace")[:50000], filename
        elif "word" in mime or filename.lower().endswith((".doc", ".docx")):
            # Basic docx text extraction
            import zipfile, io, re
            try:
                z = zipfile.ZipFile(io.BytesIO(raw))
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
                text = " ".join(re.findall(r'<w:t[^>]*>(.*?)</w:t>', xml))
                return text[:50000], filename
            except Exception:
                return "", filename
        return "", filename
    except Exception as e:
        print(f"[RAG] Attachment extract failed for {filename}: {e}")
        return "", filename


async def ingest_email_to_case(case_id: int, email_id: str, account: str,
                                sender: str, subject: str, date: str,
                                body: str, attachments: List[dict] = None):
    """Chunk and embed a full email body + attachments into the case."""
    conn = get_conn()
    cur = conn.cursor()
    inserted = 0
    try:
        # Chunk and embed body
        body_chunks = chunk_text(body)
        for i, chunk in enumerate(body_chunks):
            vec = await embed_text(chunk)
            if vec:
                cur.execute("""
                    INSERT INTO case_chunks
                    (case_id, email_id, account, sender, subject, email_date,
                     chunk_index, source_type, content, embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'email_body',%s,%s::vector)
                """, (case_id, email_id, account, sender, subject, date, i,
                      chunk, json.dumps(vec)))
                inserted += 1

        # Process attachments
        if attachments:
            for att in attachments:
                att_text, att_name = att.get("text", ""), att.get("name", "")
                if not att_text:
                    continue
                att_chunks = chunk_text(att_text)
                for i, chunk in enumerate(att_chunks):
                    vec = await embed_text(chunk)
                    if vec:
                        cur.execute("""
                            INSERT INTO case_chunks
                            (case_id, email_id, account, sender, subject, email_date,
                             chunk_index, source_type, attachment_name, content, embedding)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,'attachment',%s,%s,%s::vector)
                        """, (case_id, email_id, account, sender, subject, date, i,
                              att_name, chunk, json.dumps(vec)))
                        inserted += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[RAG] Ingest failed for {email_id}: {e}")
    finally:
        cur.close()
        conn.close()
    return inserted


async def search_case(case_id: int, query: str, top_k: int = 20) -> List[dict]:
    """Semantic search within a case — returns most relevant chunks."""
    vec = await embed_text(query)
    if not vec:
        return []
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT content, sender, subject, email_date, source_type, attachment_name,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM case_chunks
            WHERE case_id = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (json.dumps(vec), case_id, json.dumps(vec), top_k))
        rows = cur.fetchall()
        return [
            {
                "content": r[0], "sender": r[1], "subject": r[2],
                "date": r[3], "source_type": r[4], "attachment": r[5],
                "similarity": float(r[6])
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[RAG] Search failed: {e}")
        return []
    finally:
        cur.close()
        conn.close()


def get_case_by_name(name: str) -> Optional[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, query, status, total_emails, total_chunks FROM cases WHERE LOWER(name) = LOWER(%s)", (name,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return {"id": row[0], "name": row[1], "query": row[2], "status": row[3],
                "total_emails": row[4], "total_chunks": row[5]}
    return None


def list_cases() -> List[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, query, status, total_emails, total_chunks, created_at FROM cases ORDER BY created_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "name": r[1], "query": r[2], "status": r[3],
             "total_emails": r[4], "total_chunks": r[5], "created_at": str(r[6])} for r in rows]
