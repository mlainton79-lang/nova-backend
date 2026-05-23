"""Nova observability — operational event recording for Nerve-1A.

Other code calls record_run_event() instead of `except: pass` so that
failures Tony's organs experience become visible at /api/v1/status.
"""

from app.observability.events import record_run_event
from app.observability.event_types import EventSeverity, EVENT_TYPES

__all__ = ["record_run_event", "EventSeverity", "EVENT_TYPES"]
