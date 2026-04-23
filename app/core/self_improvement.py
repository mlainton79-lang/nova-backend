"""
Tony's self-improvement loop.

Runs after eval runs. If tests failed, analyses the failures and PROPOSES
prompt/rule changes. Does NOT apply them automatically — queues them for
Matthew's review.

This is the feedback loop that makes Tony better over time without
needing Matthew to manually debug every regression.
"""
import os
import json
import httpx
import psycopg2
from typing import List, Dict


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_self_improvement_tables():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_improvement_proposals (
                id SERIAL PRIMARY KEY,
                trigger_eval_run_id INT,
                failure_pattern TEXT,
                proposed_change TEXT,
                proposed_rule TEXT,
                evidence JSONB,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW(),
                applied_at TIMESTAMP,
                dismissed_at TIMESTAMP
            )
        """)
        cur.close()
        conn.close()
        print("[SELF_IMPROVEMENT] Tables initialised")
    except Exception as e:
        print(f"[SELF_IMPROVEMENT] Init failed: {e}")


async def analyse_eval_failures(eval_run_id: int) -> List[Dict]:
    """
    Pull the latest eval run, find failed tests, analyse patterns, propose fixes.
    Returns list of proposal dicts.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT summary FROM tony_eval_runs WHERE id = %s
        """, (eval_run_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return []

        summary = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        results = summary.get("results", [])
        failures = [r for r in results if not r.get("passed")]
        if not failures:
            return []

        # Group by category
        by_cat = {}
        for f in failures:
            cat = f.get("category", "misc")
            by_cat.setdefault(cat, []).append(f)

        proposals = []
        for cat, items in by_cat.items():
            proposal = await _propose_fix_for_category(cat, items)
            if proposal:
                proposals.append(proposal)

        # Save proposals
        if proposals:
            _save_proposals(eval_run_id, proposals)

        return proposals
    except Exception as e:
        print(f"[SELF_IMPROVEMENT] Analyse failed: {e}")
        return []


async def _propose_fix_for_category(category: str, failures: List[Dict]) -> Dict:
    """Use Gemini to propose a prompt/rule fix for a cluster of failures."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None

    failures_summary = "\n".join(
        f"- Test {f['id']}: {'; '.join(f.get('failures', []))} | Response: {f.get('reply','')[:300]}"
        for f in failures[:8]
    )

    prompt = f"""Tony (an AI assistant) just failed {len(failures)} tests in category '{category}'.
Here are the failures:

{failures_summary}

Propose ONE specific change to Tony's behaviour rules or system prompt that would fix this
class of failure. Be concrete — don't say 'be more careful', say 'add rule X to section Y'.

Return STRICT JSON:
{{
  "failure_pattern": "short description of what's going wrong",
  "proposed_change": "specific change to make — what file, what section, what exact text to add",
  "proposed_rule": "a one-sentence rule for Tony's identity section (if applicable, else empty)",
  "confidence": 0.0-1.0
}}

Respond with JSON only:"""

    try:
        from app.core import gemini_client
        resp = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": 800, "temperature": 0.2},
            timeout=20.0,
            caller_context="self_improvement",
        )
        response = gemini_client.extract_text(resp)

        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first < 0:
            return None
        data = json.loads(cleaned[first:last+1])
        return {
            "category": category,
            "failure_pattern": data.get("failure_pattern", "")[:300],
            "proposed_change": data.get("proposed_change", "")[:1500],
            "proposed_rule": data.get("proposed_rule", "")[:500],
            "confidence": float(data.get("confidence", 0.5)),
            "evidence": {"failures": [{"id": f["id"], "failures": f.get("failures", [])}
                                       for f in failures]},
        }
    except Exception as e:
        print(f"[SELF_IMPROVEMENT] Propose failed: {e}")
        return None


def _save_proposals(eval_run_id: int, proposals: List[Dict]):
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for p in proposals:
            cur.execute("""
                INSERT INTO tony_improvement_proposals
                    (trigger_eval_run_id, failure_pattern, proposed_change,
                     proposed_rule, evidence)
                VALUES (%s, %s, %s, %s, %s)
            """, (eval_run_id, p["failure_pattern"], p["proposed_change"],
                  p["proposed_rule"], json.dumps(p.get("evidence", {}))))
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[SELF_IMPROVEMENT] Save failed: {e}")


def list_pending_proposals(limit: int = 10) -> List[Dict]:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, trigger_eval_run_id, failure_pattern, proposed_change,
                   proposed_rule, status, created_at
            FROM tony_improvement_proposals
            WHERE status = 'pending'
            ORDER BY created_at DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"id": r[0], "eval_run_id": r[1], "pattern": r[2],
             "change": r[3], "rule": r[4], "status": r[5],
             "created_at": str(r[6])}
            for r in rows
        ]
    except Exception:
        return []


def mark_proposal(proposal_id: int, status: str):
    """status: 'applied' or 'dismissed'"""
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        col = "applied_at" if status == "applied" else "dismissed_at"
        cur.execute(f"""
            UPDATE tony_improvement_proposals
            SET status = %s, {col} = NOW()
            WHERE id = %s
        """, (status, proposal_id))
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[SELF_IMPROVEMENT] Mark failed: {e}")
        return False
