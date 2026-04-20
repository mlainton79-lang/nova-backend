"""
Tony's Codebase Storage and Retrieval.

Stores the Android and backend codebase in PostgreSQL so Tony can reference
it during conversation. When Matthew asks about code or Nova internals,
prompt_assembler pulls relevant summaries into the system prompt.

Two sources:
1. Android files pushed from the app via /api/v1/codebase/sync (frontend)
2. Backend files — read live from GitHub when needed (already handled by
   tony_agi_loop and tony_self_builder via GitHub API)

This module is the persistent store and the summary builder.
"""
import os
import ast
import psycopg2
from datetime import datetime
from typing import Dict, List, Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_codebase_table():
    """Create codebase storage table if needed."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_codebase (
                id SERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content TEXT,
                summary TEXT,
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (source, file_path)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_codebase_source
            ON tony_codebase(source)
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[CODEBASE] Table initialised")
    except Exception as e:
        print(f"[CODEBASE] Init failed: {e}")


def _summarise_kotlin(content: str, filename: str) -> str:
    """Extract class/function signatures from a Kotlin file."""
    lines = content.split("\n")
    summary_parts = [f"// {filename}"]
    for line in lines:
        stripped = line.strip()
        # Class declarations
        if stripped.startswith(("class ", "object ", "interface ", "enum class ")):
            summary_parts.append(stripped.rstrip("{").strip())
        # Function declarations at reasonable indentation
        elif (stripped.startswith(("fun ", "private fun ", "public fun ",
                                   "override fun ", "suspend fun "))):
            # Just the signature, not body
            sig = stripped.split("{")[0].strip().rstrip("=").strip()
            summary_parts.append(f"    {sig}")
        # Important property declarations
        elif stripped.startswith(("val BASE_URL", "const val ", "private val ")):
            if "=" in stripped:
                summary_parts.append(f"    {stripped.split('=')[0].strip()}")
    result = "\n".join(summary_parts)
    return result[:1500]  # Cap per-file summary


def _summarise_python(content: str, filename: str) -> str:
    """Extract function/class signatures + docstrings from a Python file."""
    try:
        tree = ast.parse(content)
        doc = ast.get_docstring(tree) or ""
        parts = [f"# {filename}"]
        if doc:
            parts.append(f'"""{doc[:150]}"""')
        for node in tree.body:  # Only top-level
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                fdoc = ast.get_docstring(node) or ""
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                args = ", ".join(a.arg for a in node.args.args)
                parts.append(f"{prefix} {node.name}({args}):  # {fdoc[:80]}")
            elif isinstance(node, ast.ClassDef):
                parts.append(f"class {node.name}:")
        return "\n".join(parts)[:1500]
    except Exception:
        return f"# {filename} (parse failed)"


def store_files(source: str, files: Dict[str, str]) -> Dict:
    """
    Store a batch of files from a source (frontend, backend, etc).
    Creates a summary for each and stores both content and summary.
    Returns counts.
    """
    stored = 0
    failed = 0
    try:
        conn = get_conn()
        cur = conn.cursor()
        for path, content in files.items():
            try:
                if path.endswith(".kt"):
                    summary = _summarise_kotlin(content, path)
                elif path.endswith(".py"):
                    summary = _summarise_python(content, path)
                else:
                    summary = f"# {path}\n{content[:500]}"

                cur.execute("""
                    INSERT INTO tony_codebase (source, file_path, content, summary, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (source, file_path)
                    DO UPDATE SET content = EXCLUDED.content,
                                  summary = EXCLUDED.summary,
                                  updated_at = NOW()
                """, (source, path, content[:50000], summary))
                stored += 1
            except Exception as e:
                print(f"[CODEBASE] Failed {path}: {e}")
                failed += 1
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[CODEBASE] Store failed: {e}")
        return {"ok": False, "error": str(e), "stored": stored, "failed": failed}

    return {"ok": True, "stored": stored, "failed": failed, "source": source}


def get_codebase_summary(max_chars: int = 2000) -> str:
    """
    Get a compact summary of the codebase for prompt injection.
    Returns summaries of all known files, prioritising the most recently updated.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT source, file_path, summary FROM tony_codebase
            ORDER BY updated_at DESC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return ""

        # Group by source
        by_source = {}
        for source, path, summary in rows:
            by_source.setdefault(source, []).append((path, summary))

        output = []
        for source, files in by_source.items():
            output.append(f"\n=== {source.upper()} CODEBASE ({len(files)} files) ===")
            for path, summary in files:
                output.append(summary or f"// {path}")

        result = "\n\n".join(output)
        return result[:max_chars]
    except Exception as e:
        print(f"[CODEBASE] Summary failed: {e}")
        return ""


def search_codebase(query: str, limit: int = 5) -> List[Dict]:
    """
    Search codebase for files/snippets matching the query.
    Used when Tony needs to look up specific code during chat.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Simple ILIKE search — full-text index could come later
        cur.execute("""
            SELECT source, file_path, summary, content
            FROM tony_codebase
            WHERE content ILIKE %s OR file_path ILIKE %s OR summary ILIKE %s
            ORDER BY updated_at DESC
            LIMIT %s
        """, (f"%{query}%", f"%{query}%", f"%{query}%", limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"source": r[0], "path": r[1], "summary": r[2], "content_preview": r[3][:500] if r[3] else ""}
            for r in rows
        ]
    except Exception as e:
        print(f"[CODEBASE] Search failed: {e}")
        return []


def get_codebase_stats() -> Dict:
    """Return stats about what's stored — for monitoring."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT source, COUNT(*), MAX(updated_at)
            FROM tony_codebase
            GROUP BY source
            ORDER BY source
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {
            "sources": [
                {"source": r[0], "file_count": r[1], "last_updated": str(r[2])[:16]}
                for r in rows
            ]
        }
    except Exception as e:
        return {"error": str(e)}
