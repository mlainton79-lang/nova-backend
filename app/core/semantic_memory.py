"""
Tony's Semantic Memory System.

Replaces flat recency-based memory with vector similarity search.
When Tony needs context, he retrieves the memories most RELEVANT
to the current conversation — not just the most recent ones.

This is the difference between:
- "Here are the last 100 things Matthew told me"
- "Here are the 10 most relevant things I know about this topic"

Uses the same Gemini embedding infrastructure as the RAG system.
3072-dimensional vectors, hnsw index for fast search.
"""
import os
import asyncio
import psycopg2
import httpx
from typing import List, Optional, Dict
from datetime import datetime

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_semantic_memory_tables():
    """Create semantic memory table with vector index."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Enable pgvector
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

        # Create semantic memories table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS semantic_memories (
                id SERIAL PRIMARY KEY,
                category TEXT NOT NULL DEFAULT 'general',
                text TEXT NOT NULL,
                embedding vector(768),
                importance FLOAT DEFAULT 1.0,
                access_count INTEGER DEFAULT 0,
                last_accessed TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # hnsw index for fast similarity search
        cur.execute("""
            CREATE INDEX IF NOT EXISTS semantic_memories_embedding_idx
            ON semantic_memories USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)

        conn.commit()
        cur.close()
        conn.close()
        print("[SEMANTIC_MEMORY] Tables initialised")
    except Exception as e:
        print(f"[SEMANTIC_MEMORY] Init failed: {e}")


async def _embed(text: str) -> Optional[List[float]]:
    """Get embedding using Gemini. 768 dimensions for memories (faster than 3072)."""
    if not GEMINI_API_KEY or not text.strip():
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={GEMINI_API_KEY}",
                json={
                    "model": "models/gemini-embedding-001",
                    "content": {"parts": [{"text": text[:2000]}]},
                    "taskType": "RETRIEVAL_DOCUMENT",
                    "outputDimensionality": 768
                }
            )
            if r.status_code == 200:
                values = r.json().get("embedding", {}).get("values")
                if values:
                    return values
    except Exception as e:
        print(f"[SEMANTIC_MEMORY] Embed failed: {e}")
    return None


async def add_semantic_memory(category: str, text: str, importance: float = 1.0) -> bool:
    """Add a memory with its embedding for semantic search."""
    if not text.strip():
        return False

    # Check for near-duplicate before embedding
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM semantic_memories WHERE text = %s LIMIT 1",
            (text[:1000],)
        )
        if cur.fetchone():
            cur.close()
            conn.close()
            return False  # Exact duplicate
        cur.close()
        conn.close()
    except Exception:
        pass

    embedding = await _embed(text)

    try:
        conn = get_conn()
        cur = conn.cursor()

        if embedding:
            cur.execute("""
                INSERT INTO semantic_memories (category, text, embedding, importance)
                VALUES (%s, %s, CAST(%s AS vector), %s)
            """, (category, text[:2000], str(embedding), importance))
        else:
            # Store without embedding — still useful, just won't be semantically searched
            cur.execute("""
                INSERT INTO semantic_memories (category, text, importance)
                VALUES (%s, %s, %s)
            """, (category, text[:2000], importance))

        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[SEMANTIC_MEMORY] Add failed: {e}")
        return False


async def search_memories(query: str, top_k: int = 10, category: str = None) -> List[Dict]:
    """
    Find the most relevant memories for a given query.
    Returns memories ranked by semantic similarity.
    """
    query_embedding = await _embed(query)

    try:
        conn = get_conn()
        cur = conn.cursor()

        if query_embedding:
            # Vector similarity search
            if category:
                cur.execute("""
                    SELECT id, category, text, importance, created_at,
                           1 - (embedding <=> CAST(%s AS vector)) as similarity
                    FROM semantic_memories
                    WHERE embedding IS NOT NULL AND category = %s
                    ORDER BY embedding <=> CAST(%s AS vector)
                    LIMIT %s
                """, (str(query_embedding), category, str(query_embedding), top_k))
            else:
                cur.execute("""
                    SELECT id, category, text, importance, created_at,
                           1 - (embedding <=> CAST(%s AS vector)) as similarity
                    FROM semantic_memories
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(%s AS vector)
                    LIMIT %s
                """, (str(query_embedding), str(query_embedding), top_k))
        else:
            # Fallback: recency-based
            cur.execute("""
                SELECT id, category, text, importance, created_at, 1.0 as similarity
                FROM semantic_memories
                ORDER BY created_at DESC
                LIMIT %s
            """, (top_k,))

        rows = cur.fetchall()

        # Update access counts
        if rows:
            ids = [r[0] for r in rows]
            cur.execute("""
                UPDATE semantic_memories
                SET access_count = access_count + 1, last_accessed = NOW()
                WHERE id = ANY(%s)
            """, (ids,))
            conn.commit()

        cur.close()
        conn.close()

        return [
            {
                "id": r[0], "category": r[1], "text": r[2],
                "importance": r[3], "created_at": str(r[4]),
                "similarity": float(r[5])
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[SEMANTIC_MEMORY] Search failed: {e}")
        return []


async def format_semantic_memory_block(query: str) -> str:
    """
    Get the most relevant memories for the current conversation.
    This replaces the flat recency-based memory injection.
    """
    try:
        memories = await search_memories(query, top_k=15)
        if not memories:
            return ""

        # Filter to similarity > 0.3 — below that it's not relevant enough
        relevant = [m for m in memories if m["similarity"] > 0.3]
        if not relevant:
            # Fall back to top results regardless of threshold
            relevant = memories[:8]

        lines = ["TONY'S RELEVANT MEMORIES:"]
        for m in relevant:
            lines.append(f"- [{m['category']}] {m['text']}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[SEMANTIC_MEMORY] Format failed: {e}")
        return ""


async def migrate_existing_memories():
    """
    One-time migration: embed all existing memories from the memories table.
    Runs at startup if semantic_memories is empty.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Check if already migrated
        cur.execute("SELECT COUNT(*) FROM semantic_memories")
        count = cur.fetchone()[0]
        if count > 0:
            cur.close()
            conn.close()
            print(f"[SEMANTIC_MEMORY] Already has {count} memories, skipping migration")
            return

        # Fetch all existing memories
        cur.execute("SELECT category, text FROM memories ORDER BY created_at DESC LIMIT 500")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            print("[SEMANTIC_MEMORY] No existing memories to migrate")
            return

        print(f"[SEMANTIC_MEMORY] Migrating {len(rows)} memories...")
        success = 0
        for category, text in rows:
            if await add_semantic_memory(category, text):
                success += 1
            await asyncio.sleep(0.1)  # Rate limit embedding API

        print(f"[SEMANTIC_MEMORY] Migrated {success}/{len(rows)} memories")
    except Exception as e:
        print(f"[SEMANTIC_MEMORY] Migration failed: {e}")
