"""
Document Memory — semantic search over every document Matthew has shown Tony.

Workflow:
  1. Matthew uploads a PDF/image/Word doc
  2. Tony extracts text (existing vision/doc readers)
  3. document_memory.ingest() chunks, embeds, stores
  4. Later, Matthew asks 'find that letter about...' → search() returns chunks

This is long-term, queryable document context. Unlike living memory (summary)
or facts (atomic triples), this keeps the source material searchable.
"""
import os
import json
import hashlib
import psycopg2
from datetime import datetime
from typing import List, Dict, Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_document_memory_tables():
    """Create tables + pgvector extension if not exists."""
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_documents (
                id SERIAL PRIMARY KEY,
                doc_name TEXT,
                doc_type TEXT,
                doc_hash TEXT UNIQUE,
                full_text TEXT,
                word_count INT,
                source TEXT DEFAULT 'upload',
                uploaded_at TIMESTAMP DEFAULT NOW(),
                last_referenced TIMESTAMP,
                reference_count INT DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_document_chunks (
                id SERIAL PRIMARY KEY,
                document_id INT REFERENCES tony_documents(id) ON DELETE CASCADE,
                chunk_index INT,
                chunk_text TEXT,
                embedding vector(768),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc
            ON tony_document_chunks(document_id)
        """)
        cur.close()
        conn.close()
        print("[DOC_MEMORY] Tables initialised")
    except Exception as e:
        print(f"[DOC_MEMORY] Init failed: {e}")


def _chunk_text(text: str, max_words: int = 200, overlap: int = 30) -> List[str]:
    """Split text into overlapping word-windows."""
    words = text.split()
    if len(words) <= max_words:
        return [text]
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + max_words])
        chunks.append(chunk)
        i += max_words - overlap
    return chunks


async def _embed(text: str) -> Optional[List[float]]:
    """Get embedding for a chunk. Uses Gemini's text-embedding-004."""
    import httpx
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={api_key}",
                json={
                    "model": "models/text-embedding-004",
                    "content": {"parts": [{"text": text[:8000]}]},
                    "taskType": "RETRIEVAL_DOCUMENT",
                }
            )
            r.raise_for_status()
            return r.json()["embedding"]["values"]
    except Exception as e:
        print(f"[DOC_MEMORY] Embed failed: {e}")
        return None


def _doc_hash(text: str, name: str = "") -> str:
    """Dedup hash from text + name."""
    return hashlib.sha256((name + "||" + text[:5000]).encode()).hexdigest()[:32]


async def ingest_document(
    full_text: str,
    doc_name: str = "",
    doc_type: str = "unknown",
    source: str = "upload",
) -> Dict:
    """
    Ingest a full document: chunk, embed, save. Idempotent via doc_hash.
    Returns {ok, document_id, chunks_count}.
    """
    if not full_text or len(full_text.strip()) < 50:
        return {"ok": False, "error": "Document too short to be worth indexing"}

    h = _doc_hash(full_text, doc_name)

    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()

        # Check if already ingested
        cur.execute("SELECT id FROM tony_documents WHERE doc_hash = %s", (h,))
        existing = cur.fetchone()
        if existing:
            cur.close()
            conn.close()
            return {"ok": True, "document_id": existing[0],
                    "note": "already ingested"}

        cur.execute("""
            INSERT INTO tony_documents
                (doc_name, doc_type, doc_hash, full_text, word_count, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (doc_name[:200], doc_type[:50], h, full_text,
              len(full_text.split()), source))
        doc_id = cur.fetchone()[0]

        # Chunk + embed + save chunks
        chunks = _chunk_text(full_text)
        saved = 0
        for i, chunk in enumerate(chunks):
            emb = await _embed(chunk)
            if emb:
                cur.execute("""
                    INSERT INTO tony_document_chunks
                        (document_id, chunk_index, chunk_text, embedding)
                    VALUES (%s, %s, %s, CAST(%s AS vector))
                """, (doc_id, i, chunk, str(emb)))
                saved += 1
            else:
                # Save without embedding — still text-searchable
                cur.execute("""
                    INSERT INTO tony_document_chunks
                        (document_id, chunk_index, chunk_text)
                    VALUES (%s, %s, %s)
                """, (doc_id, i, chunk))

        cur.close()
        conn.close()
        return {"ok": True, "document_id": doc_id, "chunks_total": len(chunks),
                "chunks_embedded": saved}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def search_documents(query: str, top_k: int = 5) -> List[Dict]:
    """
    Semantic search over all ingested document chunks.
    Returns ranked chunks with their parent document metadata.
    """
    query_emb = await _embed(query)

    try:
        conn = get_conn()
        cur = conn.cursor()

        if query_emb:
            # Vector search
            cur.execute("""
                SELECT c.id, c.chunk_text, d.doc_name, d.doc_type, d.uploaded_at,
                       1 - (c.embedding <=> CAST(%s AS vector)) AS similarity
                FROM tony_document_chunks c
                JOIN tony_documents d ON d.id = c.document_id
                WHERE c.embedding IS NOT NULL
                ORDER BY c.embedding <=> CAST(%s AS vector)
                LIMIT %s
            """, (str(query_emb), str(query_emb), top_k))
        else:
            # Fallback: keyword search
            cur.execute("""
                SELECT c.id, c.chunk_text, d.doc_name, d.doc_type, d.uploaded_at,
                       0.5 AS similarity
                FROM tony_document_chunks c
                JOIN tony_documents d ON d.id = c.document_id
                WHERE c.chunk_text ILIKE %s
                ORDER BY d.uploaded_at DESC
                LIMIT %s
            """, (f"%{query[:100]}%", top_k))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        return [
            {
                "chunk_id": r[0],
                "text": r[1],
                "doc_name": r[2],
                "doc_type": r[3],
                "uploaded_at": str(r[4]),
                "similarity": float(r[5]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[DOC_MEMORY] Search failed: {e}")
        return []


def list_documents(limit: int = 20) -> List[Dict]:
    """List all ingested documents."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, doc_name, doc_type, word_count, uploaded_at, reference_count
            FROM tony_documents
            ORDER BY uploaded_at DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"id": r[0], "name": r[1], "type": r[2], "word_count": r[3],
             "uploaded_at": str(r[4]), "references": r[5]}
            for r in rows
        ]
    except Exception:
        return []


def delete_document(doc_id: int) -> bool:
    """Delete a document and its chunks."""
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("DELETE FROM tony_documents WHERE id = %s", (doc_id,))
        cur.close()
        conn.close()
        return True
    except Exception:
        return False
