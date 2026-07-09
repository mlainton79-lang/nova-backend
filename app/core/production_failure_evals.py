"""Turn operational failure events into reviewed eval-case candidates."""

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import psycopg2


_VALID_SEVERITIES = ("warning", "error", "critical")
_MAX_LIMIT = 100
_MAX_MINUTES = 24 * 60

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SECRETISH_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|[A-Za-z0-9_-]{32,}|ya29\.[A-Za-z0-9_-]+)\b"
)


def _redact_text(value: Any, max_len: int = 300) -> str:
    text = str(value or "")
    text = _EMAIL_RE.sub("[redacted-email]", text)
    text = _SECRETISH_RE.sub("[redacted-token]", text)
    return text[:max_len]


def _safe_slug(value: Any, fallback: str = "unknown") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return slug[:48] or fallback


def normalise_failure_event(row: Dict[str, Any]) -> Dict[str, Any]:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    safe_metadata = {
        _safe_slug(key, "field"): _redact_text(value, 160)
        for key, value in list(metadata.items())[:12]
    }

    return {
        "id": row.get("id"),
        "created_at": (
            row.get("created_at").isoformat()
            if hasattr(row.get("created_at"), "isoformat") else row.get("created_at")
        ),
        "source_service": _redact_text(row.get("source_service"), 80),
        "event_type": _redact_text(row.get("event_type"), 120),
        "severity": _redact_text(row.get("severity"), 20).lower(),
        "subsystem": _redact_text(row.get("subsystem"), 120),
        "capability": _redact_text(row.get("capability"), 120),
        "status": _redact_text(row.get("status"), 80),
        "message": _redact_text(row.get("message"), 300),
        "error_class": _redact_text(row.get("error_class"), 120),
        "error_message": _redact_text(row.get("error_message"), 300),
        "metadata": safe_metadata,
    }


def build_eval_candidate_from_event(event: Dict[str, Any]) -> Dict[str, Any]:
    safe = normalise_failure_event(event)
    subsystem = safe["subsystem"] or "unknown"
    event_type = safe["event_type"] or "unknown"
    event_id = safe["id"] or "latest"
    category = f"production_failure.{_safe_slug(subsystem)}"

    evidence = "; ".join(
        part for part in [
            f"severity={safe['severity']}",
            f"subsystem={subsystem}",
            f"event_type={event_type}",
            f"status={safe['status']}" if safe["status"] else "",
            f"error={safe['error_class']}" if safe["error_class"] else "",
            safe["error_message"] if safe["error_message"] else safe["message"],
        ] if part
    )

    return {
        "id": f"prod.{_safe_slug(subsystem)}.{_safe_slug(event_type)}.{event_id}",
        "category": category,
        "source_event_id": event_id,
        "created_at": safe["created_at"],
        "severity": safe["severity"],
        "evidence": evidence[:700],
        "proposed_test": {
            "message": (
                f"Production signal: {subsystem} reported {event_type}. "
                "What should Nova do next?"
            ),
            "must_not_contain": [
                "all caught up",
                "everything is fine",
                "nothing to do",
            ],
            "expected_behaviour": (
                "Acknowledge the production failure signal, name the affected "
                "subsystem, avoid claiming success, and give a concrete next "
                "diagnostic or recovery action."
            ),
            "max_words": 160,
            "category": category,
        },
        "safe_event": safe,
        "review_required": True,
    }


def build_eval_candidates(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    candidates: List[Dict[str, Any]] = []
    for event in events:
        candidate = build_eval_candidate_from_event(event)
        dedupe_key = (
            candidate["proposed_test"]["category"],
            candidate["safe_event"]["event_type"],
            candidate["safe_event"]["error_class"],
            candidate["safe_event"]["error_message"],
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidates.append(candidate)
    return candidates


def _get_conn():
    return psycopg2.connect(
        os.environ["DATABASE_URL"], sslmode="require", connect_timeout=10
    )


def recent_failure_events(minutes: int = 24 * 60, limit: int = 25) -> Dict[str, Any]:
    minutes = max(1, min(int(minutes), _MAX_MINUTES))
    limit = max(1, min(int(limit), _MAX_LIMIT))
    sql = """
        SELECT id, source_service, event_type, severity, subsystem,
               capability, status, message, error_class, error_message,
               metadata_json, created_at
        FROM run_events
        WHERE created_at > NOW() - (%s || ' minutes')::interval
          AND severity = ANY(%s)
        ORDER BY created_at DESC
        LIMIT %s
    """
    try:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (str(minutes), list(_VALID_SEVERITIES), limit))
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:
        return {
            "ok": False,
            "error": "query_failed",
            "details": _redact_text(exc, 200),
            "minutes": minutes,
            "limit": limit,
        }

    events = [
        {
            "id": row[0],
            "source_service": row[1],
            "event_type": row[2],
            "severity": row[3],
            "subsystem": row[4],
            "capability": row[5],
            "status": row[6],
            "message": row[7],
            "error_class": row[8],
            "error_message": row[9],
            "metadata": row[10],
            "created_at": row[11],
        }
        for row in rows
    ]
    candidates = build_eval_candidates(events)
    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "minutes": minutes,
        "events_checked": len(events),
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
