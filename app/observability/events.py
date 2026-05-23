"""record_run_event — write one row to run_events. MUST NEVER raise."""

import json
import os
import sys
from typing import Optional, Union

import psycopg2

from app.observability.event_types import EventSeverity


_DEFAULT_SOURCE_SERVICE = os.environ.get("RAILWAY_SERVICE_NAME", "web")
_VALID_SEVERITIES = frozenset({"debug", "info", "warning", "error", "critical"})


def record_run_event(
    event_type: str,
    severity: Union[EventSeverity, str],
    subsystem: str,
    message: str,
    *,
    run_id: Optional[str] = None,
    source_service: Optional[str] = None,
    capability: Optional[str] = None,
    status: Optional[str] = None,
    error_class: Optional[str] = None,
    error_message: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Optional[int]:
    """Record one operational event into run_events.

    MUST NEVER raise. If recording fails (DB down, missing DATABASE_URL,
    malformed input), logs to stderr and returns None.

    Returns the inserted run_events.id on success, None on any failure.
    """
    try:
        if isinstance(severity, EventSeverity):
            severity_str = severity.value
        else:
            severity_str = str(severity).lower()

        if severity_str not in _VALID_SEVERITIES:
            print(
                f"[observability] WARN: invalid severity {severity_str!r}, "
                f"coercing to 'error' for event_type={event_type!r}",
                file=sys.stderr,
            )
            severity_str = "error"

        if metadata is not None:
            try:
                metadata_json = json.dumps(metadata, default=str)
            except (TypeError, ValueError) as e:
                print(
                    f"[observability] WARN: metadata not JSON-serializable "
                    f"({e}), dropping for event_type={event_type!r}",
                    file=sys.stderr,
                )
                metadata_json = "{}"
        else:
            metadata_json = "{}"

        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            print(
                f"[observability] WARN: DATABASE_URL not set, "
                f"dropping event_type={event_type!r} subsystem={subsystem!r}",
                file=sys.stderr,
            )
            return None

        conn = psycopg2.connect(db_url, connect_timeout=5, sslmode="require")
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO run_events (
                        run_id, source_service, event_type, severity,
                        subsystem, capability, status, message,
                        error_class, error_message, metadata_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id;
                    """,
                    (
                        run_id,
                        source_service or _DEFAULT_SOURCE_SERVICE,
                        event_type,
                        severity_str,
                        subsystem,
                        capability,
                        status,
                        message,
                        error_class,
                        error_message,
                        metadata_json,
                    ),
                )
                row = cur.fetchone()
                return int(row[0]) if row else None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    except Exception as e:
        print(
            f"[observability] ERROR: record_run_event itself failed "
            f"({type(e).__name__}: {e}) for event_type={event_type!r} "
            f"subsystem={subsystem!r}",
            file=sys.stderr,
        )
        return None
