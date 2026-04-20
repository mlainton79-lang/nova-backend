"""
Tony's AGI Loop — The Continuous Self-Improvement Engine.

Every 6 hours Tony:
1. Takes a live inventory of what he actually has
2. Reads the build log for recent failures
3. Checks self-eval scores for genuine quality gaps
4. Decides what to fix or build based on real evidence
5. Builds it
6. Moves to the next real gap

The decision is grounded in what Tony actually is right now —
not a static priority list written months ago.
"""
import os
import ast
import asyncio
import base64
import httpx
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.core.model_router import gemini_json

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "mlainton79-lang/nova-backend")


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


# ── Live codebase inventory ──────────────────────────────────────────────────

async def _list_github_dir(path: str) -> List[str]:
    """List files in a GitHub directory."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
                headers={"Authorization": f"token {GITHUB_TOKEN}"}
            )
            if r.status_code == 200:
                return [f["name"] for f in r.json() if f["type"] == "file"]
    except Exception as e:
        print(f"[AGI_LOOP] Dir list failed {path}: {e}")
    return []


async def _read_github_file(path: str, max_chars: int = 3000) -> str:
    """Read a file from GitHub, truncated."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
                headers={"Authorization": f"token {GITHUB_TOKEN}"}
            )
            if r.status_code == 200:
                content = base64.b64decode(r.json()["content"]).decode()
                return content[:max_chars]
    except Exception:
        pass
    return ""


def _extract_module_summary(content: str, filename: str) -> str:
    """Extract docstring + function/class names from a Python file."""
    try:
        tree = ast.parse(content)
        # Module docstring
        docstring = ast.get_docstring(tree) or ""
        # Top-level functions and classes
        names = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    doc = ast.get_docstring(node) or ""
                    names.append(f"  def {node.name}(): {doc[:80]}")
                else:
                    names.append(f"  class {node.name}")
        summary = f"{filename}: {docstring[:120]}\n" + "\n".join(names[:12])
        return summary
    except Exception:
        return f"{filename}: (could not parse)"


async def get_live_inventory() -> Dict:
    """
    Read what Tony actually has right now — directly from GitHub.
    Returns a structured inventory of endpoints and core modules with summaries.
    """
    print("[AGI_LOOP] Reading live codebase inventory...")

    # List what exists
    endpoint_files = await _list_github_dir("app/api/v1/endpoints")
    core_files = await _list_github_dir("app/core")

    endpoint_names = [f.replace(".py", "") for f in endpoint_files if f.endswith(".py") and f != "__init__.py"]
    core_names = [f.replace(".py", "") for f in core_files if f.endswith(".py") and f != "__init__.py"]

    # Read summaries for core modules (functions + docstrings, not full content)
    core_summaries = []
    for filename in sorted(core_names):
        content = await _read_github_file(f"app/core/{filename}.py", max_chars=4000)
        if content:
            summary = _extract_module_summary(content, filename)
            core_summaries.append(summary)

    # Read router to see what's actually wired
    router_content = await _read_github_file("app/api/v1/router.py", max_chars=5000)

    return {
        "endpoints": endpoint_names,
        "core_modules": core_names,
        "core_summaries": core_summaries,
        "router_snapshot": router_content,
        "endpoint_count": len(endpoint_names),
        "core_count": len(core_names),
    }


# ── DB state ─────────────────────────────────────────────────────────────────

def get_db_state() -> Dict:
    """Pull relevant DB metrics: failures, eval scores, build history."""
    state = {
        "recent_failures": 0,
        "avg_eval_score": 0.0,
        "low_score_topics": [],
        "recent_build_log": [],
        "last_build_succeeded": None,
        "failed_build_reasons": [],
    }
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Eval failures in last 24h
        try:
            cur.execute("""
                SELECT COUNT(*) FROM tony_eval_log
                WHERE success = FALSE AND created_at > NOW() - INTERVAL '24 hours'
            """)
            state["recent_failures"] = cur.fetchone()[0] or 0
        except Exception:
            pass

        # Average conversation score last 7 days
        try:
            cur.execute("""
                SELECT AVG(score), MIN(score) FROM tony_learning_log
                WHERE created_at > NOW() - INTERVAL '7 days' AND score IS NOT NULL
            """)
            row = cur.fetchone()
            if row and row[0]:
                state["avg_eval_score"] = round(float(row[0]), 1)
        except Exception:
            pass

        # Low-scoring conversation topics
        try:
            cur.execute("""
                SELECT lesson FROM tony_learning_log
                WHERE score < 7 AND created_at > NOW() - INTERVAL '7 days'
                ORDER BY score ASC LIMIT 5
            """)
            state["low_score_topics"] = [r[0] for r in cur.fetchall() if r[0]]
        except Exception:
            pass

        # Recent build log — last 10 entries
        try:
            cur.execute("""
                SELECT stage, content, success, created_at
                FROM tony_build_log
                ORDER BY created_at DESC LIMIT 10
            """)
            rows = cur.fetchall()
            state["recent_build_log"] = [
                {"stage": r[0], "content": r[1][:150], "success": r[2],
                 "at": str(r[3])[:16]}
                for r in rows
            ]
            # Extract failure reasons
            state["failed_build_reasons"] = [
                r[1][:150] for r in rows if not r[2]
            ]
            # Last success
            successes = [r for r in rows if r[2] and r[0] == "build_start"]
            if successes:
                state["last_build_succeeded"] = str(successes[0][3])[:16]
        except Exception:
            pass

        # Self-eval summary
        try:
            cur.execute("""
                SELECT stage, content FROM think_sessions
                WHERE stage IN ('agi_build_success', 'autonomous_build_success')
                ORDER BY id DESC LIMIT 5
            """)
            state["recent_successful_builds"] = [r[1][:100] for r in cur.fetchall()]
        except Exception:
            state["recent_successful_builds"] = []

        cur.close()
        conn.close()
    except Exception as e:
        print(f"[AGI_LOOP] DB state failed: {e}")

    return state


# ── Decision ─────────────────────────────────────────────────────────────────

async def decide_what_to_build(inventory: Dict, db_state: Dict) -> Optional[Dict]:
    """
    Tony decides what to build or fix next.

    The decision is grounded entirely in what Tony actually has right now
    and what the evidence shows is genuinely broken or missing.
    """

    # Build the full picture for Gemini
    endpoints_list = "\n".join(f"  - {e}" for e in inventory["endpoints"])
    core_list = "\n".join(f"  - {m}" for m in inventory["core_modules"])
    core_detail = "\n\n".join(inventory["core_summaries"][:40])  # All modules summarised

    build_log_str = "\n".join(
        f"  [{r['at']}] {r['stage']}: {'OK' if r['success'] else 'FAIL'} — {r['content']}"
        for r in db_state["recent_build_log"]
    )

    failed_reasons = "\n".join(f"  - {r}" for r in db_state["failed_build_reasons"]) or "  none"
    low_scores = "\n".join(f"  - {t}" for t in db_state["low_score_topics"]) or "  none"
    recent_builds = "\n".join(f"  - {b}" for b in db_state.get("recent_successful_builds", [])) or "  none"

    prompt = f"""You are Tony's decision engine. Tony is deciding what single thing to build or fix next.

TONY'S LIVE CODEBASE — what actually exists right now:

Endpoints ({inventory['endpoint_count']}):
{endpoints_list}

Core modules ({inventory['core_count']}):
{core_list}

WHAT EACH CORE MODULE DOES (functions + docstrings):
{core_detail}

EVIDENCE FROM DB:
Recent failures (last 24h): {db_state['recent_failures']}
Average eval score (last 7 days): {db_state['avg_eval_score']}/10
Low-scoring conversation topics:
{low_scores}

Recent build log:
{build_log_str}

Recent failed build reasons:
{failed_reasons}

Recent successful autonomous builds:
{recent_builds}

INSTRUCTIONS:
Look at what Tony actually has. Do not suggest building something that already exists.
Do not suggest rebuilding something that was recently built successfully.
Base the decision on real evidence: what's failing, what's scoring low, what's genuinely missing.

Priority order:
1. Fix something that is provably broken right now (build log failures, eval failures)
2. Improve something that scores badly (low eval topics)
3. Build something genuinely missing that would help Matthew today

Matthew's context: Night shifts at care home, building Nova, two young daughters, income from selling.

What is the single most valuable thing Tony should build or fix right now?
Do not invent something that sounds good. Base it on the evidence above.

Respond in JSON:
{{
    "capability_name": "short name",
    "capability_description": "precise description — what file, what function, what it should do",
    "why_now": "specific evidence from above that justifies this — quote the failure or low score",
    "is_fix": true/false,
    "target_file": "app/api/v1/endpoints/X.py or null if new",
    "impact": "concrete change for Matthew",
    "test_endpoint": "/api/v1/endpoint or null",
    "priority_score": 1-10
}}"""

    result = await gemini_json(prompt, task="reasoning", max_tokens=1024)
    if result:
        print(f"[AGI_LOOP] Decision: {result.get('capability_name')} (score {result.get('priority_score')})")
        print(f"[AGI_LOOP] Why: {result.get('why_now', '')[:120]}")
    return result


# ── Main loop ─────────────────────────────────────────────────────────────────

async def run_agi_improvement_cycle() -> Dict:
    """
    Tony's full AGI self-improvement cycle.
    Runs every 6 hours as part of the autonomous loop.
    """
    print("[AGI_LOOP] Starting improvement cycle...")

    # Step 1: Read what actually exists
    inventory = await get_live_inventory()
    print(f"[AGI_LOOP] Live inventory: {inventory['core_count']} core modules, {inventory['endpoint_count']} endpoints")

    # Step 2: Read what the DB evidence says
    db_state = get_db_state()
    print(f"[AGI_LOOP] DB state: {db_state['recent_failures']} failures, avg score {db_state['avg_eval_score']}")

    # Step 3: Make a grounded decision
    decision = await decide_what_to_build(inventory, db_state)

    if not decision:
        print("[AGI_LOOP] Could not reach a decision")
        return {"ok": False, "reason": "decision_failed"}

    capability = decision.get("capability_name", "")
    description = decision.get("capability_description", "")
    priority = decision.get("priority_score", 0)

    if not capability or not description:
        print("[AGI_LOOP] Invalid decision — missing name or description")
        return {"ok": False, "reason": "invalid_decision"}

    # Don't build low-priority things — save the Railway deploy
    if priority < 6:
        print(f"[AGI_LOOP] Priority {priority}/10 too low — skipping this cycle")
        return {"ok": True, "reason": "priority_too_low", "skipped": capability}

    # Protected modules — never rebuild these, they are maintained manually
    PROTECTED = [
        "proactive_alerts", "proactive alerts", "chat_stream", "chat stream",
        "council", "router", "main", "prompt_assembler", "whatsapp",
        "security", "logger", "config"
    ]
    cap_lower = capability.lower()
    if any(p in cap_lower for p in PROTECTED):
        print(f"[AGI_LOOP] {capability} is a protected module — skipping autonomous rebuild")
        return {"ok": True, "reason": "protected_module", "skipped": capability}

    print(f"[AGI_LOOP] Building: {capability}")
    print(f"[AGI_LOOP] Why now: {decision.get('why_now', '')[:120]}")

    # Step 4: Build it
    from app.core.tony_self_builder import tony_build_capability
    result = await tony_build_capability(
        capability,
        description,
        test_endpoint=decision.get("test_endpoint")
    )

    result["decision"] = decision
    result["inventory_at_build"] = {
        "core_count": inventory["core_count"],
        "endpoint_count": inventory["endpoint_count"],
    }

    # Step 5: Log outcome
    try:
        conn = get_conn()
        cur = conn.cursor()
        stage = "agi_build_success" if result.get("success") else "agi_build_failed"
        cur.execute(
            "INSERT INTO think_sessions (stage, content) VALUES (%s, %s)",
            (stage, f"{capability}: {decision.get('impact', '')[:200]}")
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass

    if result.get("success"):
        print(f"[AGI_LOOP] ✓ Built: {capability}")
    else:
        print(f"[AGI_LOOP] ✗ Failed: {capability}")

    return result
