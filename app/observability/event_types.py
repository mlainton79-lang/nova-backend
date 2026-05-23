"""Event severity and common event-type constants."""

from enum import Enum


class EventSeverity(str, Enum):
    """Matches the CHECK constraint on run_events.severity."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


EVENT_TYPES = {
    "MEMORY_WRITE_FAILED": "memory_write_failed",
    "MEMORY_READ_FAILED": "memory_read_failed",
    "MEMORY_CONSOLIDATION_FAILED": "memory_consolidation_failed",
    "PROVIDER_ERROR": "provider_error",
    "PROVIDER_TIMEOUT": "provider_timeout",
    "PROVIDER_RATE_LIMITED": "provider_rate_limited",
    "CAPABILITY_UNAVAILABLE": "capability_unavailable",
    "CAPABILITY_DEGRADED": "capability_degraded",
    "CAPABILITY_RECOVERED": "capability_recovered",
    "WORKER_STARTED": "worker_started",
    "WORKER_COMPLETED": "worker_completed",
    "WORKER_FAILED": "worker_failed",
    "WORKER_INIT_FAILED": "worker_init_failed",
    "RECORDER_DB_UNAVAILABLE": "recorder_db_unavailable",
    "RECORDER_WRITE_FAILED": "recorder_write_failed",
}
