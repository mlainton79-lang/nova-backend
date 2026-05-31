"""Debug endpoint: query the run_events table directly.

Read-only window into tony's operational event log so the operator can pull
recent failures from outside the Railway dashboard. Specifically built so the
P1.4 observability backfill (subsystem='memory.*' / 'chat.artifacts' /
'gmail.refresh' / 'selling.*') can be smoke-verified without raw DB access.

Auth-gated via verify_token (DEV_TOKEN bearer). The metadata_json blob is
returned verbatim — per AGENTS.md, the existing record_run_event call sites
take care to never persist secret values; metadata typically carries
ordinals, lengths, status codes, and emails (the only PII-shaped value).
"""

import json
import os
from typing import Optional

import psycopg2
from fastapi import APIRouter, Depends, Query

from app.core.security import verify_token
from app.observability import EVENT_TYPES, EventSeverity, record_run_event

router = APIRouter()

_VALID_SEVERITIES = frozenset({"debug", "info", "warning", "error", "critical"})
_MAX_MINUTES = 24 * 60
_MAX_LIMIT = 500


def _get_conn():
    return psycopg2.connect(
        os.environ["DATABASE_URL"], sslmode="require", connect_timeout=10
    )


@router.get("/debug/recent-events")
async def recent_events(
    minutes: int = Query(30, ge=1, le=_MAX_MINUTES),
    subsystem: Optional[str] = Query(None, description="Exact subsystem match (e.g. 'memory.living')"),
    subsystem_prefix: Optional[str] = Query(None, description="LIKE prefix match (e.g. 'memory.')"),
    severity: Optional[str] = Query(None, description="One of debug|info|warning|error|critical"),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    _=Depends(verify_token),
):
    """Return recent run_events rows.

    Default behaviour: last 30 minutes, all subsystems, all severities, max 50 rows.

    Filters:
      - minutes:          1-1440 (24h max)
      - subsystem:        exact match
      - subsystem_prefix: LIKE 'prefix%' (useful for the memory.* fan-out)
      - severity:         one of debug|info|warning|error|critical
      - limit:            1-500
    """
    if severity is not None and severity.lower() not in _VALID_SEVERITIES:
        return {"ok": False, "error": f"severity must be one of {sorted(_VALID_SEVERITIES)}"}

    where_clauses = ["created_at > NOW() - INTERVAL %s"]
    params: list = [f"{int(minutes)} minutes"]

    if subsystem is not None:
        where_clauses.append("subsystem = %s")
        params.append(subsystem)
    if subsystem_prefix is not None:
        where_clauses.append("subsystem LIKE %s")
        params.append(f"{subsystem_prefix}%")
    if severity is not None:
        where_clauses.append("severity = %s")
        params.append(severity.lower())

    sql = (
        "SELECT id, source_service, event_type, severity, subsystem, "
        "capability, status, message, error_class, error_message, "
        "metadata_json, created_at "
        "FROM run_events "
        f"WHERE {' AND '.join(where_clauses)} "
        "ORDER BY created_at DESC "
        "LIMIT %s"
    )
    params.append(int(limit))

    try:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_READ_FAILED"],
            severity=EventSeverity.WARNING,
            subsystem="debug.events",
            message="recent_events query failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"minutes": minutes, "subsystem": subsystem, "subsystem_prefix": subsystem_prefix, "severity": severity, "limit": limit},
        )
        return {"ok": False, "error": "query failed; see selling.drafts logs"}

    events = []
    for r in rows:
        (eid, source_service, event_type, sev, subsys, capability,
         status, message, error_class, error_message, metadata_json, created_at) = r
        # metadata_json comes back as either a dict (psycopg2 native JSONB decode)
        # or a str depending on driver version — normalise to dict.
        if isinstance(metadata_json, str):
            try:
                metadata_json = json.loads(metadata_json)
            except Exception:
                metadata_json = {"_unparsed": metadata_json}
        events.append({
            "id": eid,
            "source_service": source_service,
            "event_type": event_type,
            "severity": sev,
            "subsystem": subsys,
            "capability": capability,
            "status": status,
            "message": message,
            "error_class": error_class,
            "error_message": error_message,
            "metadata": metadata_json,
            "created_at": created_at.isoformat() if created_at else None,
        })

    return {
        "ok": True,
        "count": len(events),
        "filters": {
            "minutes": minutes,
            "subsystem": subsystem,
            "subsystem_prefix": subsystem_prefix,
            "severity": severity,
            "limit": limit,
        },
        "events": events,
    }


@router.get("/debug/run-strategic-advisor")
async def debug_run_strategic_advisor(_=Depends(verify_token)):
    """ONE-SHOT diagnostic — TEMPORARY, removable after the strategic_advisor
    silent-output root cause is identified.

    Runs the full produce_weekly_strategy flow against live prod data and
    reports each stage's outcome: SELECTs, prompt build, raw Gemini call,
    parse attempt, and the actual run_strategic_advisor() wrapper return.
    Captures the raw Gemini text (first 800 + last 400 chars) so we can see
    EXACTLY what the model emits — the missing piece the worker_log doesn't
    capture.

    REMOVE after diagnosis (alongside the strategic_advisor fix commit).
    """
    import time
    import re as _re
    import json as _json
    from datetime import datetime
    from app.core import strategic_advisor as sa
    from app.core.model_router import gemini

    result: dict = {"stages": {}}

    # Stage 1: mirror produce_weekly_strategy's four SELECTs
    try:
        conn = sa.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT section, content FROM tony_living_memory WHERE content IS NOT NULL")
        living_memory = dict(cur.fetchall())
        cur.execute(
            "SELECT title, priority, progress_notes FROM tony_goals WHERE status = 'active' "
            "ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END"
        )
        goals = cur.fetchall()
        cur.execute(
            "SELECT title, body FROM tony_alerts WHERE read = FALSE "
            "AND created_at > NOW() - INTERVAL '7 days' ORDER BY created_at DESC LIMIT 5"
        )
        alerts = cur.fetchall()
        cur.execute(
            "SELECT insight_type, title, body FROM tony_insights "
            "WHERE created_at > NOW() - INTERVAL '7 days' ORDER BY confidence DESC LIMIT 5"
        )
        insights = cur.fetchall()
        cur.close(); conn.close()
        result["stages"]["selects"] = {
            "ok": True,
            "living_memory_rows": len(living_memory),
            "goals": len(goals),
            "alerts": len(alerts),
            "insights": len(insights),
        }
    except Exception as e:
        result["stages"]["selects"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return result

    # Stage 2: build the exact prompt produce_weekly_strategy would build
    context_parts = []
    for section in ["LIFE_SUMMARY", "FINANCIAL", "LEGAL", "CURRENT_FOCUS", "OPEN_LOOPS"]:
        if section in living_memory and living_memory[section]:
            context_parts.append(f"{section}: {living_memory[section][:200]}")
    goals_text = "\n".join(f"- [{g[1]}] {g[0]}" for g in goals)
    alerts_text = "\n".join(f"- {a[0]}: {a[1][:100]}" for a in alerts)
    insights_text = "\n".join(f"- [{i[0]}] {i[1]}: {i[2][:100]}" for i in insights)

    prompt = f"""Tony is producing his weekly strategic assessment for Matthew.

Matthew's situation:
{chr(10).join(context_parts)}

Active goals:
{goals_text or 'None'}

Recent alerts:
{alerts_text or 'None'}

Recent insights:
{insights_text or 'None'}

Today's date: {datetime.utcnow().strftime('%A %d %B %Y')}

Produce a strategic assessment. Think like a trusted advisor who genuinely cares about Matthew's wellbeing and success.

Consider:
1. Financial trajectory — where is Matthew heading? Is it improving?
2. Any active legal or financial matters — what's the most important next step?
3. Income — is the Vinted/eBay side showing promise? What would double it?
4. Nova/Tony — how is this project progressing toward its potential?
5. Family — anything coming up that needs preparation?
6. Risks — what's building in the background that Matthew hasn't noticed?
7. This week's priority — one thing that would make the biggest difference

Be specific, honest, and direct. Not generic advice — advice for Matthew specifically.

Respond in JSON:
{{
    "financial_trajectory": "assessment",
    "legal_priority": "most important legal action this week",
    "income_assessment": "Vinted/eBay progress and what would improve it",
    "nova_progress": "honest assessment of where Tony/Nova is",
    "family_upcoming": "anything family-related that needs attention",
    "hidden_risks": ["risks building that Matthew may not have noticed"],
    "this_week_priority": "THE single most important thing Matthew should do this week",
    "tony_commitment": "what Tony commits to doing autonomously this week"
}}"""

    result["stages"]["prompt"] = {"chars": len(prompt), "context_sections": len(context_parts)}

    # Stage 3: raw Gemini call — exact same args as produce_weekly_strategy
    start = time.time()
    try:
        raw_text = await gemini(prompt, task="reasoning", max_tokens=1500)
        elapsed = round(time.time() - start, 2)
        result["stages"]["gemini_raw"] = {
            "elapsed_s": elapsed,
            "is_none": raw_text is None,
            "text_chars": len(raw_text) if raw_text else 0,
            "text_first_800": (raw_text or "")[:800],
            "text_last_400": (raw_text or "")[-400:] if raw_text and len(raw_text) > 400 else "",
        }
    except Exception as e:
        result["stages"]["gemini_raw"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return result

    # Stage 4: locally simulate the gemini_json parser on the captured text
    if raw_text:
        try:
            cleaned = _re.sub(r'```json|```', '', raw_text).strip()
            parsed = _json.loads(cleaned)
            result["stages"]["parse"] = {
                "ok": True, "path": "primary_strip_fences",
                "keys": list(parsed.keys()) if isinstance(parsed, dict) else None,
            }
        except Exception as e_primary:
            match = _re.search(r'\{.*\}', raw_text, _re.DOTALL)
            if match:
                try:
                    parsed = _json.loads(match.group())
                    result["stages"]["parse"] = {
                        "ok": True, "path": "fallback_regex",
                        "primary_error": f"{type(e_primary).__name__}: {e_primary}",
                        "keys": list(parsed.keys()) if isinstance(parsed, dict) else None,
                    }
                except Exception as e_fallback:
                    result["stages"]["parse"] = {
                        "ok": False, "path": "both_failed",
                        "primary_error": f"{type(e_primary).__name__}: {e_primary}",
                        "fallback_error": f"{type(e_fallback).__name__}: {e_fallback}",
                    }
            else:
                result["stages"]["parse"] = {
                    "ok": False, "path": "no_brace_match",
                    "primary_error": f"{type(e_primary).__name__}: {e_primary}",
                }
    else:
        result["stages"]["parse"] = {"ok": False, "skipped": "raw_text was None/empty"}

    # Stage 5: also call run_strategic_advisor end-to-end to confirm what
    # the production cron's actual wrapper returns (catches gate-firing,
    # alert-creation failures, etc.)
    try:
        rsa_start = time.time()
        from app.core.strategic_advisor import run_strategic_advisor
        rsa_result = await run_strategic_advisor()
        result["stages"]["run_strategic_advisor"] = {
            "elapsed_s": round(time.time() - rsa_start, 2),
            "result_is_falsy": not rsa_result,
            "result_keys": list(rsa_result.keys()) if isinstance(rsa_result, dict) and rsa_result else None,
        }
    except Exception as e:
        result["stages"]["run_strategic_advisor"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    result["ok"] = True
    return result


@router.get("/debug/event-counts")
async def event_counts(
    minutes: int = Query(60, ge=1, le=_MAX_MINUTES),
    _=Depends(verify_token),
):
    """Roll-up by (subsystem, severity) over the last N minutes. Quick triage
    view — see which subsystems are loudest without paging through individual
    rows."""
    try:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT subsystem, severity, COUNT(*) AS n,
                           MAX(created_at) AS last_seen
                    FROM run_events
                    WHERE created_at > NOW() - (%s || ' minutes')::interval
                    GROUP BY subsystem, severity
                    ORDER BY n DESC, subsystem ASC
                    """,
                    (str(int(minutes)),),
                )
                rows = cur.fetchall()
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_READ_FAILED"],
            severity=EventSeverity.WARNING,
            subsystem="debug.events",
            message="event_counts query failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"minutes": minutes},
        )
        return {"ok": False, "error": "query failed"}

    counts = [
        {
            "subsystem": subsystem,
            "severity": severity,
            "n": int(n),
            "last_seen": last_seen.isoformat() if last_seen else None,
        }
        for subsystem, severity, n, last_seen in rows
    ]
    return {
        "ok": True,
        "minutes": minutes,
        "groups": len(counts),
        "counts": counts,
    }
