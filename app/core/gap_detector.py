"""
Capability Gap Detector.

When Matthew asks for something, this checks:
"Can Tony do this with his current capabilities?"

If no, it starts a background build.

Design philosophy:
- Err toward trying first. Tony shouldn't refuse things he might already be
  able to do.
- If it's truly a new capability, start building immediately. Don't ask
  permission — Matthew's instruction this session was "if he has overall
  autonomy he works it out himself".
- Be concrete: Tony tells Matthew exactly what he's going to build, in plain
  terms. Not "I'll build a capability for that" — "Give me 3 minutes, I'll
  build the Vinted posting integration and tell you when it's live."
"""
import os
import json
import psycopg2
import asyncio
from typing import Optional, Dict, List
from datetime import datetime


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_gap_tables():
    """Track capability build requests and their status."""
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_capability_requests (
                id SERIAL PRIMARY KEY,
                user_message TEXT NOT NULL,
                capability_name TEXT,
                capability_description TEXT,
                status TEXT DEFAULT 'pending',
                attempt_count INT DEFAULT 0,
                last_error TEXT,
                approach_log TEXT,
                started_at TIMESTAMP DEFAULT NOW(),
                completed_at TIMESTAMP,
                success BOOLEAN
            )
        """)

        # One-shot idempotent cleanup for the broken auto-built post_to_vinted
        # capability (hallucinated Vinted signing protocol, non-functional).
        # File + router wiring already removed in this commit; these UPDATEs
        # purge the associated DB rows so the registry and request history
        # reflect reality. Idempotent — on subsequent deploys the WHERE
        # clauses match zero rows and both statements no-op.
        cur.execute(
            "UPDATE capabilities SET status = 'removed' "
            "WHERE name = 'post_to_vinted' AND status != 'removed' RETURNING id"
        )
        cap_removed = cur.rowcount
        cur.execute(
            "UPDATE tony_capability_requests SET status = 'removed' "
            "WHERE capability_name = 'post_to_vinted' AND status != 'removed' "
            "RETURNING id"
        )
        req_removed = cur.rowcount
        print(
            f"[GAP_DETECTOR] post_to_vinted cleanup: "
            f"capabilities rows marked removed={cap_removed}, "
            f"request rows marked removed={req_removed}"
        )

        cur.close()
        conn.close()
        print("[GAP_DETECTOR] Tables initialised")
    except Exception as e:
        print(f"[GAP_DETECTOR] Init failed: {e}")


async def detect_capability_gap(user_message: str) -> Optional[Dict]:
    """
    Decide: is this a request for a new capability Tony doesn't have?

    Returns:
      None if no gap — Tony can handle it with existing tools
      Dict with capability_name, description, rationale if a gap exists

    Uses Gemini for speed. Returns None on any error (fail safe = don't
    interrupt chat).
    """
    # Get what Tony already can do
    try:
        from app.core.capabilities import get_capabilities
        existing = get_capabilities(status="active")
        existing_list = "\n".join(
            f"- {c.get('name', '')}: {c.get('description', '')[:80]}"
            for c in (existing or [])
        )
    except Exception:
        existing_list = "(capability registry unavailable)"

    prompt = f"""You are detecting whether Matthew is asking Tony (an AI assistant) to do something Tony can't do yet.

Tony's current capabilities:
{existing_list}

Tony can also: chat, search web, read Gmail, read calendar, push code to GitHub, deploy to Railway.

Matthew's message:
\"\"\"{user_message}\"\"\"

Analyse: is this asking for a NEW capability that would require building new code?

Examples of NEW capabilities:
- "Can you post to Vinted?" → YES, needs Vinted API integration
- "Pay my bill" → YES, needs payment integration
- "Order me a pizza" → YES, needs delivery service integration
- "Control my smart lights" → YES, needs smart home API

Examples that are NOT new capabilities (Tony can already do):
- "Write me a letter" → NO, chat is enough
- "What's the weather?" → NO, web search
- "Summarise this email" → NO, has Gmail + chat
- Casual chat, questions, opinions, recommendations → NO

Respond ONLY with valid JSON:
{{
  "is_gap": true|false,
  "capability_name": "short_snake_case_name" or null,
  "description": "one sentence describing what needs building" or null,
  "rationale": "why this is / isn't a gap"
}}"""

    try:
        import httpx
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            return None

        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 512, "temperature": 0.1}
                }
            )
            r.raise_for_status()
            response = r.json()["candidates"][0]["content"]["parts"][0]["text"]

        # Log what Gemini actually said — for debugging
        print(f"[GAP_DETECTOR] Raw response: {response[:500]}")

        # Strip markdown fences if present
        cleaned = response.strip()
        if cleaned.startswith("```"):
            # Remove opening ```json or ``` and closing ```
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        # Try to find the JSON object — from first { to last }
        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first < 0 or last < 0 or last <= first:
            print(f"[GAP_DETECTOR] No JSON object found in response")
            return None

        json_text = cleaned[first:last+1]
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as je:
            print(f"[GAP_DETECTOR] JSON parse failed: {je}")
            return None

        print(f"[GAP_DETECTOR] Parsed: is_gap={data.get('is_gap')}, name={data.get('capability_name')}")

        if not data.get("is_gap"):
            return None

        if not data.get("capability_name") or not data.get("description"):
            print(f"[GAP_DETECTOR] Gap detected but name/description missing — skipping")
            return None

        return {
            "capability_name": data.get("capability_name"),
            "description": data.get("description"),
            "rationale": data.get("rationale", "")
        }
    except Exception as e:
        print(f"[GAP_DETECTOR] Detection failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


async def start_autonomous_build(capability_name: str, description: str, user_message: str) -> int:
    """
    Kick off a capability build in the background. Returns a request_id.
    Tony will work on this between conversations.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_capability_requests
                (user_message, capability_name, capability_description, status)
            VALUES (%s, %s, %s, 'building')
            RETURNING id
        """, (user_message, capability_name, description))
        request_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        # Fire off the builder in the background — don't await
        asyncio.create_task(_background_build(request_id, capability_name, description))

        return request_id
    except Exception as e:
        print(f"[GAP_DETECTOR] Failed to start build: {e}")
        return -1


async def _background_build(request_id: int, capability_name: str, description: str):
    """
    Runs the full build pipeline in background, retrying with different
    approaches if needed.
    """
    MAX_ATTEMPTS = 3
    approaches_tried = []

    try:
        from app.core.capability_builder import build_capability
    except Exception as e:
        _mark_failed(request_id, f"Builder import failed: {e}")
        return

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _update_attempt(request_id, attempt)
            print(f"[GAP_DETECTOR] Build attempt {attempt} for {capability_name}")

            # On retries, vary the approach
            desc_for_attempt = description
            if attempt == 2:
                desc_for_attempt = f"{description} (prefer the simplest free approach; avoid paid APIs if possible)"
            elif attempt == 3:
                desc_for_attempt = f"{description} (fall back to browser automation / scraping if direct API unavailable)"

            report = await build_capability(capability_name, desc_for_attempt)
            approaches_tried.append({
                "attempt": attempt,
                "description": desc_for_attempt,
                "success": report.get("success", False),
                "steps": [s for s in report.get("steps", []) if not s.get("ok")]
            })

            if report.get("success"):
                _mark_success(request_id, report, approaches_tried)

                # Create alert for Matthew
                try:
                    from app.core.proactive import create_alert
                    create_alert(
                        alert_type="capability_built",
                        title=f"Built: {capability_name}",
                        body=f"{description}\n\nReady in ~60 seconds once Railway deploys. {report.get('note', '')}",
                        priority="high",
                        source="gap_detector",
                        expires_hours=72
                    )
                except Exception:
                    pass

                return

        except Exception as e:
            approaches_tried.append({
                "attempt": attempt,
                "error": str(e)[:500]
            })
            print(f"[GAP_DETECTOR] Attempt {attempt} failed: {e}")

    # All attempts failed
    _mark_failed(request_id, "All approaches failed", approaches_tried)
    try:
        from app.core.proactive import create_alert
        summary = "\n".join(
            f"Attempt {a.get('attempt')}: {a.get('error', 'failed')}"
            for a in approaches_tried
        )
        create_alert(
            alert_type="capability_build_failed",
            title=f"Couldn't build: {capability_name}",
            body=f"Tried {MAX_ATTEMPTS} approaches.\n\n{summary}\n\nLet me know if you want to talk through it.",
            priority="normal",
            source="gap_detector",
            expires_hours=168
        )
    except Exception:
        pass


def _update_attempt(request_id: int, attempt: int):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE tony_capability_requests SET attempt_count = %s WHERE id = %s",
            (attempt, request_id)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


def _mark_success(request_id: int, report: Dict, approaches: List):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_capability_requests
            SET status = 'built', completed_at = NOW(), success = TRUE,
                approach_log = %s
            WHERE id = %s
        """, (json.dumps({"final_report": report, "approaches": approaches}), request_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


def _mark_failed(request_id: int, error: str, approaches: List = None):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_capability_requests
            SET status = 'failed', completed_at = NOW(), success = FALSE,
                last_error = %s, approach_log = %s
            WHERE id = %s
        """, (error[:2000], json.dumps(approaches or []), request_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


async def get_active_builds() -> List[Dict]:
    """Get list of capabilities currently being built. Useful for status checks."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, capability_name, capability_description, status,
                   attempt_count, started_at
            FROM tony_capability_requests
            WHERE status = 'building'
            ORDER BY started_at DESC
            LIMIT 5
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "id": r[0], "name": r[1], "description": r[2],
                "status": r[3], "attempts": r[4], "started": str(r[5])
            }
            for r in rows
        ]
    except Exception:
        return []
