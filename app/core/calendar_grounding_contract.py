"""Calendar grounding contract v1.

Pure local guard for calendar-style answers. It does not fetch calendar data,
read memory, touch the database, or call an external service. Callers pass the
requested time range, fetched calendar event records, and any candidate factual
schedule items they intend to state.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Mapping, Optional, Sequence, Tuple


ALLOWED = "allowed"
UNAVAILABLE = "unavailable"
REJECTED = "rejected"

NO_FETCHED_EVENT_RECORDS = "no_fetched_event_records"
NO_EVENTS_IN_REQUESTED_RANGE = "no_events_in_requested_range"
FETCHED_RECORDS_AVAILABLE = "fetched_records_available"
INVALID_REQUESTED_RANGE = "invalid_requested_range"
MALFORMED_FETCHED_EVENT_RECORD = "malformed_fetched_event_record"
MEMORY_ONLY_EVENT_CLAIM = "memory_only_event_claim"
UNBACKED_EVENT_CLAIM = "unbacked_event_claim"
STALE_EVENT_CLAIM = "stale_event_claim"


@dataclass(frozen=True)
class RejectedCalendarClaim:
    """A candidate factual schedule item that must not be stated."""

    index: int
    reason: str
    claim: Mapping[str, Any]


@dataclass(frozen=True)
class CalendarGroundingDecision:
    """Decision returned by evaluate_calendar_grounding."""

    status: str
    allowed: bool
    reason: str
    factual_schedule_allowed: bool
    backed_event_count: int = 0
    rejected_claims: Tuple[RejectedCalendarClaim, ...] = ()


@dataclass(frozen=True)
class _FetchedEvent:
    event_id: str
    title: str
    start: datetime
    raw: Mapping[str, Any]


def _decision(
    status: str,
    reason: str,
    *,
    backed_event_count: int = 0,
    rejected_claims: Sequence[RejectedCalendarClaim] = (),
) -> CalendarGroundingDecision:
    allowed = status == ALLOWED
    return CalendarGroundingDecision(
        status=status,
        allowed=allowed,
        reason=reason,
        factual_schedule_allowed=allowed,
        backed_event_count=backed_event_count,
        rejected_claims=tuple(rejected_claims),
    )


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.replace(tzinfo=None)


def _event_start(record: Mapping[str, Any]) -> Optional[datetime]:
    start = record.get("start")
    if isinstance(start, Mapping):
        start = start.get("dateTime") or start.get("date")
    return _parse_datetime(start)


def _event_title(record: Mapping[str, Any]) -> str:
    title = record.get("title")
    if title is None:
        title = record.get("summary")
    return str(title or "").strip().lower()


def _event_id(record: Mapping[str, Any]) -> str:
    return str(record.get("event_id") or record.get("id") or "").strip()


def _event_in_range(event: _FetchedEvent, start: datetime, end: datetime) -> bool:
    return start <= event.start < end


def _claim_source(claim: Mapping[str, Any]) -> str:
    return str(claim.get("source") or claim.get("grounding_source") or "").strip().lower()


def _claim_matches_event(
    claim: Mapping[str, Any],
    fetched_events: Sequence[_FetchedEvent],
) -> Optional[_FetchedEvent]:
    claim_id = _event_id(claim)
    if claim_id:
        for event in fetched_events:
            if event.event_id and event.event_id == claim_id:
                return event
        return None

    claim_start = _event_start(claim)
    claim_title = _event_title(claim)
    if not claim_start or not claim_title:
        return None

    for event in fetched_events:
        if event.title == claim_title and event.start == claim_start:
            return event
    return None


def _claim_conflicts_with_event(
    claim: Mapping[str, Any],
    event: _FetchedEvent,
) -> bool:
    claim_title = _event_title(claim)
    claim_start = _event_start(claim)
    if claim_title and claim_title != event.title:
        return True
    if claim_start and claim_start != event.start:
        return True
    return False


def evaluate_calendar_grounding(
    requested_start: Any,
    requested_end: Any,
    fetched_events: Optional[Sequence[Mapping[str, Any]]],
    candidate_items: Optional[Sequence[Mapping[str, Any]]] = None,
) -> CalendarGroundingDecision:
    """Decide whether factual calendar schedule items may be stated.

    `fetched_events is None` means no calendar fetch result is available and
    factual schedule claims must be unavailable. An empty list means the fetch
    completed and found no events in the requested range.
    """
    range_start = _parse_datetime(requested_start)
    range_end = _parse_datetime(requested_end)
    if not range_start or not range_end or range_start >= range_end:
        return _decision(REJECTED, INVALID_REQUESTED_RANGE)

    if fetched_events is None:
        return _decision(UNAVAILABLE, NO_FETCHED_EVENT_RECORDS)

    parsed_events = []
    for record in fetched_events:
        if not isinstance(record, Mapping):
            return _decision(REJECTED, MALFORMED_FETCHED_EVENT_RECORD)
        start = _event_start(record)
        if not start:
            return _decision(REJECTED, MALFORMED_FETCHED_EVENT_RECORD)
        parsed_events.append(
            _FetchedEvent(
                event_id=_event_id(record),
                title=_event_title(record),
                start=start,
                raw=record,
            )
        )

    rejected = []
    backed_count = 0
    for index, claim in enumerate(candidate_items or ()):
        if not isinstance(claim, Mapping):
            return _decision(REJECTED, UNBACKED_EVENT_CLAIM)
        if _claim_source(claim) in ("memory", "memory_only", "tony_memory"):
            rejected.append(RejectedCalendarClaim(index, MEMORY_ONLY_EVENT_CLAIM, claim))
            continue

        matched = _claim_matches_event(claim, parsed_events)
        if not matched:
            rejected.append(RejectedCalendarClaim(index, UNBACKED_EVENT_CLAIM, claim))
            continue
        if _claim_conflicts_with_event(claim, matched):
            rejected.append(RejectedCalendarClaim(index, UNBACKED_EVENT_CLAIM, claim))
            continue
        if not _event_in_range(matched, range_start, range_end):
            rejected.append(RejectedCalendarClaim(index, STALE_EVENT_CLAIM, claim))
            continue
        backed_count += 1

    if rejected:
        return _decision(REJECTED, rejected[0].reason, rejected_claims=rejected)

    events_in_range = [
        event for event in parsed_events if _event_in_range(event, range_start, range_end)
    ]
    if candidate_items:
        return _decision(ALLOWED, FETCHED_RECORDS_AVAILABLE, backed_event_count=backed_count)
    if not events_in_range:
        return _decision(ALLOWED, NO_EVENTS_IN_REQUESTED_RANGE, backed_event_count=0)
    return _decision(
        ALLOWED,
        FETCHED_RECORDS_AVAILABLE,
        backed_event_count=len(events_in_range),
    )
