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

        # Human-approval staging queue for autonomous capability builds.
        # Populated by _background_build after stage-validation passes;
        # drained by POST /api/v1/builder/approve/{request_id} (pushes + deploys)
        # or POST /api/v1/builder/reject/{request_id} (deletes the row).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pending_capabilities (
                id                     SERIAL PRIMARY KEY,
                request_id             INT NOT NULL REFERENCES tony_capability_requests(id),
                capability_name        TEXT NOT NULL,
                capability_description TEXT NOT NULL,
                user_message           TEXT,
                filename               TEXT NOT NULL,
                module_name            TEXT NOT NULL,
                generated_code         TEXT NOT NULL,
                env_vars_needed        TEXT,
                providers_used         TEXT,
                validation_report      TEXT,
                status                 TEXT DEFAULT 'pending',
                created_at             TIMESTAMP DEFAULT NOW(),
                decided_at             TIMESTAMP,
                decision_notes         TEXT
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_capabilities_status
            ON pending_capabilities(status) WHERE status = 'pending'
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_capabilities_request
            ON pending_capabilities(request_id)
        """)

        # Abandoned-build cleanup: any 'building' row older than 1h has
        # outlived the asyncio task that could resume it (Railway restart
        # or process crash will kill in-memory tasks). Mark them abandoned
        # so the request log reflects reality. Idempotent — matches zero
        # rows on subsequent deploys.
        cur.execute("""
            UPDATE tony_capability_requests
            SET status = 'abandoned', completed_at = NOW()
            WHERE status = 'building'
              AND started_at < NOW() - INTERVAL '1 hour'
            RETURNING id
        """)
        abandoned = cur.rowcount
        if abandoned:
            print(f"[GAP_DETECTOR] Marked {abandoned} stuck 'building' row(s) as 'abandoned'")

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

        from app.core import gemini_client
        resp = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": 512, "temperature": 0.1},
            timeout=10.0,
            caller_context="gap_detector",
        )
        response = gemini_client.extract_text(resp)

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
    Stage-only background pipeline: generate + validate code, then insert
    a pending_capabilities row and fire a review alert. Does NOT push to
    GitHub or deploy. The human reviewer drains the queue via
    POST /api/v1/builder/approve/{request_id} or /reject/{request_id}.

    Retries up to 3 times on generation/validation failure with varied
    approach hints (same as before the approval gate landed).
    """
    MAX_ATTEMPTS = 3
    approaches_tried = []

    try:
        from app.core.capability_builder import build_capability_stage, extract_imports
    except Exception as e:
        _mark_failed(request_id, f"Builder import failed: {e}")
        return

    user_message = _get_user_message(request_id)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _update_attempt(request_id, attempt)
            print(f"[GAP_DETECTOR] Stage attempt {attempt} for {capability_name}")

            desc_for_attempt = description
            if attempt == 2:
                desc_for_attempt = f"{description} (prefer the simplest free approach; avoid paid APIs if possible)"
            elif attempt == 3:
                desc_for_attempt = f"{description} (fall back to browser automation / scraping if direct API unavailable)"

            result = await build_capability_stage(capability_name, desc_for_attempt)
            approaches_tried.append({
                "attempt": attempt,
                "description": desc_for_attempt,
                "success": result.get("ok", False),
                "steps": [s for s in result.get("steps", []) if not s.get("ok")],
            })

            if result.get("ok"):
                artifacts = result["artifacts"]
                pending_id = _insert_pending(
                    request_id=request_id,
                    capability_name=capability_name,
                    capability_description=desc_for_attempt,
                    user_message=user_message,
                    artifacts=artifacts,
                    validation_report=result.get("steps", []),
                )
                if pending_id <= 0:
                    # Insert failed — mark the request failed and move on.
                    _mark_failed(request_id, "pending_capabilities INSERT failed",
                                 approaches_tried)
                    return

                _mark_pending_review(request_id,
                                     approach_log={"approaches": approaches_tried})

                imports = extract_imports(artifacts["code"])
                _create_pending_alert(
                    capability_name=capability_name,
                    description=desc_for_attempt,
                    user_message=user_message,
                    request_id=request_id,
                    imports=imports,
                    env_vars=artifacts.get("env_vars", []) or [],
                    providers_used=artifacts.get("providers_used", []) or [],
                )
                print(f"[GAP_DETECTOR] Staged '{capability_name}' for review "
                      f"(request_id={request_id}, pending_id={pending_id})")
                return

        except Exception as e:
            approaches_tried.append({"attempt": attempt, "error": str(e)[:500]})
            print(f"[GAP_DETECTOR] Attempt {attempt} failed: {e}")

    # All attempts failed
    _mark_failed(request_id, "All staging attempts failed", approaches_tried)
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
            expires_hours=168,
        )
    except Exception:
        pass


# Imports that deserve extra attention when they appear in autonomously-
# generated code. Shown front-and-centre in the review alert body so the
# approver can spot surprising capability at a glance.
_NOTABLE_IMPORTS = {
    "subprocess", "socket", "ctypes", "shutil", "os", "sys",
    "builtins", "importlib", "pickle", "marshal", "eval", "exec",
}


def _create_pending_alert(capability_name: str, description: str,
                          user_message: str, request_id: int,
                          imports: list, env_vars: list,
                          providers_used: list):
    try:
        from app.core.proactive import create_alert
        notable = [i for i in imports if i in _NOTABLE_IMPORTS]
        imports_line = f"Imports: {', '.join(imports) if imports else '(none)'}"
        if notable:
            imports_line += f"\n⚠ Notable: {', '.join(notable)}"
        body = (
            f"{description}\n\n"
            f"Original message: \"{(user_message or '')[:240]}\"\n\n"
            f"Code generated and validated. Waiting on your approval "
            f"before anything touches production.\n\n"
            f"Review:  GET  /api/v1/builder/pending\n"
            f"Approve: POST /api/v1/builder/approve/{request_id}\n"
            f"Reject:  POST /api/v1/builder/reject/{request_id}\n\n"
            f"{imports_line}\n"
            f"Providers used: {', '.join(providers_used) or '(none)'}\n"
            f"Env vars required: {', '.join(env_vars) or 'none'}"
        )
        create_alert(
            alert_type="capability_pending_review",
            title=f"Review pending: Tony wants to build '{capability_name}'",
            body=body,
            priority="high",
            source="builder_pending",
            expires_hours=168,
            dedup_key=f"pending_build:{capability_name}",
        )
    except Exception as e:
        print(f"[GAP_DETECTOR] Alert creation failed: {e}")


def _insert_pending(request_id: int, capability_name: str,
                    capability_description: str, user_message: str,
                    artifacts: dict, validation_report: list) -> int:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pending_capabilities
                (request_id, capability_name, capability_description, user_message,
                 filename, module_name, generated_code, env_vars_needed,
                 providers_used, validation_report, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            RETURNING id
        """, (
            request_id, capability_name, capability_description, user_message,
            artifacts["filename"], artifacts["module_name"], artifacts["code"],
            json.dumps(artifacts.get("env_vars", []) or []),
            json.dumps(artifacts.get("providers_used", []) or []),
            json.dumps(validation_report or []),
        ))
        pending_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return pending_id
    except Exception as e:
        print(f"[GAP_DETECTOR] _insert_pending failed: {e}")
        return -1


def _get_user_message(request_id: int) -> str:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT user_message FROM tony_capability_requests WHERE id = %s",
            (request_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else ""
    except Exception:
        return ""


def _mark_pending_review(request_id: int, approach_log: dict = None):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_capability_requests
            SET status = 'pending_review',
                approach_log = %s
            WHERE id = %s
        """, (json.dumps(approach_log or {}), request_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[GAP_DETECTOR] _mark_pending_review failed: {e}")


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
