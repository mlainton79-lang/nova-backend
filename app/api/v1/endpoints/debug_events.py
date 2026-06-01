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
