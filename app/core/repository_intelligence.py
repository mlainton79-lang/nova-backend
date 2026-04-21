"""
Repository Intelligence — Tony understands his own code's HISTORY.

Article's point: 'Repository intelligence — AI that understands not just
lines of code but the history, relationships, and context behind them.'

Tony has codebase_sync which produces AST summaries. But that's a snapshot.
Real repo intelligence includes:
  - When each file changed
  - Commit messages explaining why
  - Which files change together (coupling)
  - Which files are 'hot' (frequently modified)
  - Bug-fix patterns (did fixing X cause Y to break repeatedly?)

This adds a layer on top of codebase_sync: git log ingestion + pattern 
analysis. Tony can answer 'what did I change recently in the auth system?'
or 'why did I add the outcome tracker?'
"""
import os
import subprocess
import psycopg2
from datetime import datetime
from typing import Dict, List, Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_repo_intel_tables():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_commit_log (
                id SERIAL PRIMARY KEY,
                sha TEXT UNIQUE,
                author TEXT,
                committed_at TIMESTAMP,
                subject TEXT,
                body TEXT,
                files_changed JSONB,
                insertions INT,
                deletions INT,
                ingested_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_commits_date
            ON tony_commit_log(committed_at DESC)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_file_changes (
                id SERIAL PRIMARY KEY,
                commit_sha TEXT,
                file_path TEXT,
                change_type TEXT,
                insertions INT DEFAULT 0,
                deletions INT DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_changes_path
            ON tony_file_changes(file_path)
        """)
        cur.close()
        conn.close()
        print("[REPO_INTEL] Tables initialised")
    except Exception as e:
        print(f"[REPO_INTEL] Init failed: {e}")


def _run_git(args: List[str]) -> str:
    """Run git command in the nova-backend dir."""
    try:
        repo_dir = os.environ.get("REPO_DIR", "/root/nova-backend")
        result = subprocess.run(
            ["git"] + args, cwd=repo_dir, capture_output=True,
            text=True, timeout=15
        )
        return result.stdout
    except Exception as e:
        print(f"[REPO_INTEL] git {args[0]} failed: {e}")
        return ""


def ingest_recent_commits(count: int = 50) -> Dict:
    """
    Parse last N git commits + file changes into the DB.
    Idempotent — skips already-ingested shas.
    """
    # Get commit metadata
    log = _run_git([
        "log", f"-{count}", "--pretty=format:%H||%an||%aI||%s||%b%n--COMMIT--"
    ])
    if not log:
        return {"ok": False, "error": "git log returned nothing"}

    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()

        commits = log.split("--COMMIT--\n")
        ingested = 0
        skipped = 0

        for raw in commits:
            raw = raw.strip()
            if not raw or "||" not in raw:
                continue
            parts = raw.split("||", 4)
            if len(parts) < 5:
                continue
            sha, author, committed_at, subject, body = parts

            # Check if already ingested
            cur.execute("SELECT 1 FROM tony_commit_log WHERE sha = %s", (sha,))
            if cur.fetchone():
                skipped += 1
                continue

            # Get files changed for this commit
            files_output = _run_git([
                "show", "--numstat", "--format=", sha
            ])
            files_changed = []
            total_insertions = 0
            total_deletions = 0
            for line in files_output.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) == 3:
                    ins = int(parts[0]) if parts[0].isdigit() else 0
                    dels = int(parts[1]) if parts[1].isdigit() else 0
                    path = parts[2]
                    files_changed.append({
                        "path": path, "ins": ins, "dels": dels
                    })
                    total_insertions += ins
                    total_deletions += dels

            import json
            cur.execute("""
                INSERT INTO tony_commit_log
                    (sha, author, committed_at, subject, body,
                     files_changed, insertions, deletions)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sha) DO NOTHING
            """, (
                sha, author[:100], committed_at[:30],
                subject[:500], body[:2000],
                json.dumps(files_changed),
                total_insertions, total_deletions,
            ))

            # Per-file records for coupling analysis
            for f in files_changed:
                cur.execute("""
                    INSERT INTO tony_file_changes
                        (commit_sha, file_path, change_type, insertions, deletions)
                    VALUES (%s, %s, %s, %s, %s)
                """, (sha, f["path"][:500], "modified", f["ins"], f["dels"]))

            ingested += 1

        cur.close()
        conn.close()
        return {"ok": True, "ingested": ingested, "skipped": skipped}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def recent_changes(days: int = 7) -> List[Dict]:
    """What's changed recently?"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT sha, committed_at, subject, insertions, deletions, files_changed
            FROM tony_commit_log
            WHERE committed_at > NOW() - INTERVAL '1 day' * %s
            ORDER BY committed_at DESC
            LIMIT 50
        """, (days,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"sha": r[0][:7], "when": str(r[1]), "subject": r[2],
             "changes": f"+{r[3]}/-{r[4]}",
             "files_count": len(r[5]) if r[5] else 0}
            for r in rows
        ]
    except Exception:
        return []


def hot_files(days: int = 14, top_n: int = 10) -> List[Dict]:
    """Files that changed most often recently."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT fc.file_path, COUNT(*) AS change_count,
                   SUM(fc.insertions) AS total_ins,
                   SUM(fc.deletions) AS total_dels,
                   MAX(cl.committed_at) AS last_changed
            FROM tony_file_changes fc
            JOIN tony_commit_log cl ON cl.sha = fc.commit_sha
            WHERE cl.committed_at > NOW() - INTERVAL '1 day' * %s
            GROUP BY fc.file_path
            ORDER BY change_count DESC, total_ins + total_dels DESC
            LIMIT %s
        """, (days, top_n))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"path": r[0], "changes": r[1],
             "insertions": r[2], "deletions": r[3],
             "last_changed": str(r[4])}
            for r in rows
        ]
    except Exception:
        return []


def file_history(file_path: str, limit: int = 10) -> List[Dict]:
    """History of a specific file."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT cl.sha, cl.committed_at, cl.subject, cl.body,
                   fc.insertions, fc.deletions
            FROM tony_file_changes fc
            JOIN tony_commit_log cl ON cl.sha = fc.commit_sha
            WHERE fc.file_path = %s
            ORDER BY cl.committed_at DESC
            LIMIT %s
        """, (file_path, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"sha": r[0][:7], "when": str(r[1]), "subject": r[2],
             "body": (r[3] or "")[:500],
             "changes": f"+{r[4]}/-{r[5]}"}
            for r in rows
        ]
    except Exception:
        return []


def search_commits(query: str, limit: int = 10) -> List[Dict]:
    """Search commit messages for a topic."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT sha, committed_at, subject, body
            FROM tony_commit_log
            WHERE subject ILIKE %s OR body ILIKE %s
            ORDER BY committed_at DESC
            LIMIT %s
        """, (f"%{query}%", f"%{query}%", limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"sha": r[0][:7], "when": str(r[1]),
             "subject": r[2], "body": (r[3] or "")[:500]}
            for r in rows
        ]
    except Exception:
        return []
