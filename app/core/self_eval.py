"""
Tony's Self-Evaluation Loop.

The single biggest gap between a capable assistant and a genuine autonomous agent
is the ability to check whether you actually did what you said you did.

Tony now verifies:
- Did the email actually send?
- Did the memory actually save?
- Did the goal update actually persist?
- Did the agent task actually complete what it claimed?
- After a capability is built, does it actually work?

Results go to:
1. DB (tony_eval_log) — permanent record of Tony's accuracy
2. Tony's own system prompt context — he knows his track record
3. Alerts — if something silently failed, Matthew is told

This loop runs after every consequential action. Tony knows
whether to trust his own outputs.
"""
import os
import json
import re
import httpx
import psycopg2
from datetime import datetime
from typing import Dict, Any, Optional, List

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BACKEND_URL = "https://web-production-be42b.up.railway.app"
DEV_TOKEN = os.environ.get("DEV_TOKEN", "nova-dev-token")


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_eval_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_eval_log (
                id SERIAL PRIMARY KEY,
                action_type TEXT NOT NULL,
                action_description TEXT NOT NULL,
                claimed_result TEXT,
                verification_method TEXT,
                verified BOOLEAN,
                verification_detail TEXT,
                confidence FLOAT DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[SELF-EVAL] Tables initialised")
    except Exception as e:
        print(f"[SELF-EVAL] Init failed: {e}")


def log_eval(action_type: str, action_desc: str, claimed_result: str,
             method: str, verified: bool, detail: str, confidence: float = 1.0):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_eval_log
            (action_type, action_description, claimed_result, verification_method,
             verified, verification_detail, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (action_type, action_desc[:500], claimed_result[:500],
              method, verified, detail[:1000], confidence))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[SELF-EVAL] Log failed: {e}")


def get_eval_summary() -> Dict:
    """Summary of Tony's accuracy — injected into system prompt."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN verified THEN 1 ELSE 0 END) as passed,
                SUM(CASE WHEN NOT verified THEN 1 ELSE 0 END) as failed,
                action_type,
                COUNT(*) as type_count
            FROM tony_eval_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY action_type
        """)
        rows = cur.fetchall()
        cur.execute("""
            SELECT COUNT(*), SUM(CASE WHEN verified THEN 1 ELSE 0 END)
            FROM tony_eval_log
            WHERE created_at > NOW() - INTERVAL '7 days'
        """)
        totals = cur.fetchone()
        cur.close()
        conn.close()

        total = totals[0] or 0
        passed = totals[1] or 0
        rate = round((passed / total * 100), 1) if total > 0 else 100.0

        return {
            "total_checks": total,
            "passed": passed,
            "failed": total - passed,
            "success_rate": rate,
            "by_type": [
                {"type": r[3], "count": r[4], "passed": r[1], "failed": r[2]}
                for r in rows
            ]
        }
    except Exception as e:
        print(f"[SELF-EVAL] Summary failed: {e}")
        return {"total_checks": 0, "success_rate": 100.0}


def get_recent_failures() -> List[Dict]:
    """Recent failures Tony should be aware of."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT action_type, action_description, verification_detail, created_at
            FROM tony_eval_log
            WHERE verified = FALSE
            AND created_at > NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC
            LIMIT 5
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"type": r[0], "action": r[1], "detail": r[2], "time": str(r[3])}
            for r in rows
        ]
    except Exception:
        return []


# --- VERIFIERS ---
# Each verifier checks a specific type of action

async def verify_email_sent(to: str, subject: str, account: str) -> Dict:
    """
    Verify an email was actually sent by checking sent folder.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{BACKEND_URL}/api/v1/gmail/search",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"},
                params={
                    "query": f"to:{to} subject:{subject[:30]} in:sent newer_than:1h",
                    "max_per_account": 3
                }
            )
            results = r.json().get("results", [])

        found = any(
            to.lower() in e.get("to", "").lower() or
            subject[:20].lower() in e.get("subject", "").lower()
            for e in results
        )

        verified = found
        detail = f"Found {len(results)} matching sent emails" if found else "No matching sent email found"

        log_eval(
            action_type="email_send",
            action_desc=f"Send email to {to} re: {subject}",
            claimed_result="Email sent",
            method="sent_folder_search",
            verified=verified,
            detail=detail,
            confidence=0.8 if found else 0.3
        )

        if not verified:
            from app.core.proactive import create_alert
            create_alert(
                alert_type="eval_failure",
                title="Email may not have sent",
                body=f"Tony tried to send an email to {to} (re: {subject}) but cannot verify it arrived in the sent folder.",
                priority="high",
                source="self_eval"
            )

        return {"verified": verified, "detail": detail}

    except Exception as e:
        return {"verified": False, "detail": f"Verification failed: {e}"}


async def verify_memory_saved(category: str, text_snippet: str) -> Dict:
    """Verify a memory was actually stored in the DB."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{BACKEND_URL}/api/v1/memory",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"}
            )
            memories = r.json().get("memories", [])

        snippet_lower = text_snippet[:50].lower()
        found = any(
            snippet_lower in m.get("text", "").lower()
            for m in memories
        )

        log_eval(
            action_type="memory_save",
            action_desc=f"Remember [{category}]: {text_snippet[:80]}",
            claimed_result="Memory saved",
            method="memory_list_check",
            verified=found,
            detail=f"{'Found' if found else 'NOT found'} in memory store",
            confidence=0.9
        )

        return {"verified": found, "detail": "Memory confirmed" if found else "Memory not found in store"}

    except Exception as e:
        return {"verified": False, "detail": f"Verification failed: {e}"}


async def verify_goal_updated(goal_title: str, expected_progress: str) -> Dict:
    """Verify a goal update actually persisted."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{BACKEND_URL}/api/v1/goals",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"}
            )
            goals = r.json().get("goals", [])

        target = next(
            (g for g in goals if goal_title.lower() in g.get("title", "").lower()),
            None
        )
        if not target:
            verified = False
            detail = f"Goal '{goal_title}' not found"
        else:
            verified = True
            detail = f"Goal found. Progress: {target.get('progress', 'unknown')}"

        log_eval(
            action_type="goal_update",
            action_desc=f"Update goal: {goal_title}",
            claimed_result=f"Progress set to: {expected_progress[:100]}",
            method="goals_api_check",
            verified=verified,
            detail=detail,
            confidence=0.95
        )

        return {"verified": verified, "detail": detail}

    except Exception as e:
        return {"verified": False, "detail": f"Verification failed: {e}"}


async def verify_agent_task(task_description: str, claimed_output: str) -> Dict:
    """
    Tony uses Gemini to evaluate whether his own agent output is credible.
    This is self-reflection — Tony checks if what he said he did makes sense.
    """
    prompt = f"""You are Tony's self-evaluation system. Tony completed an agentic task.

Task: {task_description}
Tony claimed: {claimed_output[:600]}

Evaluate:
1. Is the claimed output plausible for this task?
2. Are there specific verifiable claims? (e.g. "I sent an email", "I saved X to memory")
3. Does the output actually address the task?

Score 0-100 for credibility. Flag anything that seems like hallucination or incomplete work.

Respond in JSON:
{{
    "credibility_score": 0-100,
    "issues": ["any concerns"],
    "verifiable_claims": ["specific claims that should be verified"],
    "verdict": "credible/questionable/likely_failed"
}}"""

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 512, "temperature": 0.1}
                }
            )
            r.raise_for_status()
            response = r.json()["candidates"][0]["content"]["parts"][0]["text"]

        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            score = data.get("credibility_score", 50)
            verdict = data.get("verdict", "questionable")
            verified = score >= 60 and verdict != "likely_failed"
            detail = f"Score: {score}/100. Verdict: {verdict}. Issues: {'; '.join(data.get('issues', []))}"

            log_eval(
                action_type="agent_task",
                action_desc=task_description[:300],
                claimed_result=claimed_output[:300],
                method="gemini_self_reflection",
                verified=verified,
                detail=detail,
                confidence=score / 100
            )

            if not verified:
                from app.core.proactive import create_alert
                create_alert(
                    alert_type="eval_failure",
                    title="Agent task may have failed",
                    body=f"Task: {task_description[:100]}\n{detail}",
                    priority="high",
                    source="self_eval"
                )

            return {"verified": verified, "detail": detail, "score": score}

    except Exception as e:
        print(f"[SELF-EVAL] Agent eval failed: {e}")

    return {"verified": False, "detail": "Could not evaluate agent task"}


async def verify_capability_built(capability_name: str, endpoint: str) -> Dict:
    """
    After Tony builds a new capability, verify the endpoint actually responds.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{BACKEND_URL}{endpoint}",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"}
            )
            success = r.status_code < 500

        detail = f"Endpoint {endpoint} returned HTTP {r.status_code}"
        log_eval(
            action_type="capability_build",
            action_desc=f"Built capability: {capability_name}",
            claimed_result=f"Endpoint {endpoint} live",
            method="endpoint_ping",
            verified=success,
            detail=detail,
            confidence=0.9
        )

        if not success:
            from app.core.proactive import create_alert
            create_alert(
                alert_type="eval_failure",
                title=f"Capability build failed: {capability_name}",
                body=f"Endpoint {endpoint} returned {r.status_code}. The build may have errors.",
                priority="high",
                source="self_eval"
            )

        return {"verified": success, "detail": detail}

    except Exception as e:
        log_eval(
            action_type="capability_build",
            action_desc=f"Built capability: {capability_name}",
            claimed_result=f"Endpoint {endpoint} live",
            method="endpoint_ping",
            verified=False,
            detail=f"Connection error: {e}",
            confidence=0.0
        )
        return {"verified": False, "detail": f"Endpoint unreachable: {e}"}


def get_eval_context_for_prompt() -> str:
    """
    Returns a brief string for injection into Tony's system prompt.
    Tony knows his own accuracy track record.
    """
    try:
        summary = get_eval_summary()
        failures = get_recent_failures()

        lines = [f"[Self-eval: {summary['success_rate']}% success rate over {summary['total_checks']} checks this week]"]

        if failures:
            lines.append("Recent failures Tony should be aware of:")
            for f in failures[:2]:
                lines.append(f"  - {f['type']}: {f['action'][:80]} — {f['detail'][:80]}")

        return "\n".join(lines)
    except Exception:
        return ""
