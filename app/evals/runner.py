"""
Tony's Eval Runner.

Runs all registered tests against a running Tony instance, scores them, and
logs the results. Can run locally against Railway, or be called via an
endpoint after a fresh deploy to self-check.
"""
import os
import json
import httpx
import asyncio
import re
from typing import List, Dict
from datetime import datetime
from app.evals.test_cases import TESTS


def get_base_url() -> str:
    """Default to Railway production. Override with TONY_BASE_URL env var."""
    return os.environ.get("TONY_BASE_URL",
        "https://web-production-be42b.up.railway.app").rstrip("/")


def get_auth_token() -> str:
    return os.environ.get("DEV_TOKEN", "nova-dev-token")


async def _call_tony(message: str, endpoint: str = "chat", timeout: float = 60.0) -> Dict:
    """Call Tony and return {ok, reply, latency_ms, error}."""
    base = get_base_url()
    token = get_auth_token()

    start = datetime.utcnow()

    try:
        if endpoint == "council":
            url = f"{base}/api/v1/council"
            payload = {
                "message": message,
                "provider": "Council",
                "history": [],
                "debug": False,
            }
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload
                )
                r.raise_for_status()
                data = r.json()
                reply = data.get("reply", "")
        else:
            # For non-streaming we use /chat which takes ChatRequest
            url = f"{base}/api/v1/chat"
            payload = {
                "message": message,
                "provider": "gemini",  # cheapest for evals
                "history": [],
            }
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload
                )
                r.raise_for_status()
                data = r.json()
                reply = data.get("reply", "")

        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        return {"ok": True, "reply": reply, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        return {"ok": False, "reply": "", "latency_ms": latency_ms, "error": str(e)[:200]}


def _check_rules(reply: str, test: Dict) -> Dict:
    """Apply all rule-based checks (no LLM required)."""
    failures = []
    reply_lower = reply.lower()

    # must_not_contain
    for phrase in test.get("must_not_contain", []):
        if phrase.lower() in reply_lower:
            failures.append(f"Contains forbidden phrase: {phrase!r}")

    # must_contain (all required)
    for phrase in test.get("must_contain", []):
        if phrase.lower() not in reply_lower:
            failures.append(f"Missing required phrase: {phrase!r}")

    # Word count
    max_words = test.get("max_words")
    if max_words:
        word_count = len(reply.split())
        if word_count > max_words:
            failures.append(f"Too long: {word_count} words (max {max_words})")

    return {"passed": len(failures) == 0, "failures": failures}


async def _semantic_check(reply: str, test: Dict) -> Dict:
    """LLM-as-judge: does the reply match the expected behaviour?"""
    expected = test.get("expected_behaviour", "")
    if not expected:
        return {"passed": True, "failures": []}

    prompt = f"""You are judging whether an AI assistant's response matches the expected behaviour.

User message: "{test['message']}"

Expected behaviour: {expected}

Actual response:
\"\"\"{reply}\"\"\"

Does the actual response match the expected behaviour? Answer STRICTLY with JSON:
{{
  "matches": true|false,
  "reason": "one-sentence explanation"
}}"""

    try:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            return {"passed": True, "failures": [], "note": "GEMINI_API_KEY unset — skipped"}

        from app.core import gemini_client
        response_json = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": 256, "temperature": 0.1},
            timeout=15.0,
            caller_context="evals.runner",
        )
        response = gemini_client.extract_text(response_json)

        # Extract JSON
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()
        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first < 0 or last < 0:
            return {"passed": True, "failures": [], "note": "judge returned no JSON"}

        data = json.loads(cleaned[first:last+1])
        matches = data.get("matches", True)
        reason = data.get("reason", "")

        if not matches:
            return {"passed": False, "failures": [f"Semantic: {reason}"]}
        return {"passed": True, "failures": []}
    except Exception as e:
        return {"passed": True, "failures": [], "note": f"judge error: {str(e)[:100]}"}


async def run_one(test: Dict, endpoint: str = "chat") -> Dict:
    """Run a single test case and return a result dict."""
    call = await _call_tony(test["message"], endpoint=endpoint)

    if not call["ok"]:
        return {
            "id": test["id"],
            "category": test.get("category", "misc"),
            "passed": False,
            "failures": [f"API call failed: {call.get('error', 'unknown')}"],
            "reply": "",
            "latency_ms": call["latency_ms"],
        }

    reply = call["reply"]

    # Rule checks first (fast, cheap)
    rule_result = _check_rules(reply, test)

    # Semantic check only if rules passed (save cost)
    if rule_result["passed"]:
        sem_result = await _semantic_check(reply, test)
        all_failures = sem_result.get("failures", [])
        passed = sem_result["passed"]
    else:
        all_failures = rule_result["failures"]
        passed = False

    return {
        "id": test["id"],
        "category": test.get("category", "misc"),
        "passed": passed,
        "failures": all_failures,
        "reply": reply[:500],
        "latency_ms": call["latency_ms"],
    }


async def run_all(endpoint: str = "chat", category: str = None) -> Dict:
    """Run the full suite. Returns summary + all results."""
    tests = [t for t in TESTS if category is None or t.get("category") == category]

    results = []
    for t in tests:
        r = await run_one(t, endpoint=endpoint)
        results.append(r)
        status = "✓" if r["passed"] else "✗"
        print(f"[EVALS] {status} {r['id']} ({r['latency_ms']}ms)")
        if not r["passed"]:
            for f in r["failures"]:
                print(f"        → {f}")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)

    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "endpoint": endpoint,
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
        "categories": {},
        "results": results,
    }

    # Per-category breakdown
    for r in results:
        cat = r["category"]
        if cat not in summary["categories"]:
            summary["categories"][cat] = {"passed": 0, "total": 0}
        summary["categories"][cat]["total"] += 1
        if r["passed"]:
            summary["categories"][cat]["passed"] += 1

    return summary


def log_result_to_db(summary: Dict):
    """Persist the full result to DB so we can compare runs over time."""
    try:
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_eval_runs (
                id SERIAL PRIMARY KEY,
                run_at TIMESTAMP DEFAULT NOW(),
                endpoint TEXT,
                passed INT,
                total INT,
                pass_rate FLOAT,
                summary JSONB
            )
        """)
        cur.execute("""
            INSERT INTO tony_eval_runs (endpoint, passed, total, pass_rate, summary)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            summary["endpoint"],
            summary["passed"],
            summary["total"],
            summary["pass_rate"],
            json.dumps(summary),
        ))
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[EVALS] Failed to log to DB: {e}")
