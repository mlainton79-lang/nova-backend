"""Disabled Gmail draft runner skeleton.

This module defines the future ``gmail.create_draft`` runner boundary without
connecting Gmail. It imports no Gmail, Google, OAuth, HTTP, browser, approval,
notification, database, or grant-consumption code.
"""
from dataclasses import dataclass
from typing import Any

from app.core.approved_capability_manifest import (
    GMAIL_CREATE_DRAFT_ACTION_TYPE,
    GMAIL_CREATE_DRAFT_CAPABILITY_KEY,
    get_capability_manifest,
)


_OPTIONAL_SNAPSHOT_FIELDS = ("cc", "bcc", "reply_to_message_id")
_REQUIRED_SNAPSHOT_FIELDS = (
    "to",
    "subject",
    "body",
    "user_visible_summary",
    "risk_level",
    "capability_key",
    "action_type",
)
_ALLOWED_SNAPSHOT_FIELDS = _REQUIRED_SNAPSHOT_FIELDS + _OPTIONAL_SNAPSHOT_FIELDS
_PROHIBITED_OPERATION_TERMS = (
    "send",
    "sent",
    "delete",
    "archive",
    "forward",
    "broad inbox",
    "broad_inbox",
    "inbox read",
    "read inbox",
    "attachment",
    "attach",
    "modify existing draft",
    "modify_existing_draft",
)
_PROHIBITED_PRIVATE_TERMS = (
    "token",
    "secret",
    "authorization",
    "oauth",
    "refresh_token",
    "access_token",
    "gmail_payload",
    "raw_gmail",
)


@dataclass(frozen=True)
class GmailDraftApprovedSnapshot:
    """Future approved snapshot shape for Gmail draft creation."""

    to: tuple[str, ...]
    cc: tuple[str, ...]
    bcc: tuple[str, ...]
    subject: str
    body: str
    reply_to_message_id: str | None
    user_visible_summary: str
    risk_level: str
    capability_key: str
    action_type: str


@dataclass(frozen=True)
class GmailDraftRunnerResult:
    """Safe result from the disabled Gmail draft runner skeleton."""

    capability_key: str
    action_type: str
    task_type: str
    status: str
    message: str
    manifest_connected: bool = False
    external_action_performed: bool = False
    notification_sent: bool = False
    draft_created: bool = False
    approval_grant_consumed: bool = False
    verification_status: str = "not_run"


def _as_nonempty_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _as_recipient_tuple(value: Any) -> tuple[str, ...] | None:
    if isinstance(value, str):
        item = value.strip()
        return (item,) if item else None
    if isinstance(value, (list, tuple)):
        recipients = []
        for item in value:
            text = _as_nonempty_string(item)
            if text is None:
                return None
            recipients.append(text)
        return tuple(recipients) if recipients else None
    return None


def _as_optional_recipient_tuple(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if isinstance(value, str) and not value.strip():
        return ()
    if isinstance(value, (list, tuple)) and not value:
        return ()
    return _as_recipient_tuple(value)


def _contains_prohibited_text(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            _contains_prohibited_text(key) or _contains_prohibited_text(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(_contains_prohibited_text(item) for item in value)
    if not isinstance(value, str):
        return False

    normalized = value.lower()
    return any(term in normalized for term in _PROHIBITED_OPERATION_TERMS) or any(
        term in normalized for term in _PROHIBITED_PRIVATE_TERMS
    )


def validate_gmail_draft_snapshot(
    snapshot: dict[str, Any],
) -> GmailDraftApprovedSnapshot:
    """Validate the future Gmail draft approval snapshot without side effects."""
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot_must_be_mapping")

    field_names = set(snapshot)
    allowed = set(_ALLOWED_SNAPSHOT_FIELDS)
    missing = set(_REQUIRED_SNAPSHOT_FIELDS) - field_names
    if missing:
        raise ValueError("snapshot_missing_required_fields")
    if field_names - allowed:
        raise ValueError("snapshot_contains_unsupported_fields")

    if snapshot.get("capability_key") != GMAIL_CREATE_DRAFT_CAPABILITY_KEY:
        raise ValueError("snapshot_capability_mismatch")
    if snapshot.get("action_type") != GMAIL_CREATE_DRAFT_ACTION_TYPE:
        raise ValueError("snapshot_action_type_mismatch")
    if _contains_prohibited_text(snapshot):
        raise ValueError("snapshot_contains_prohibited_behavior_or_private_data")

    to = _as_recipient_tuple(snapshot.get("to"))
    if to is None:
        raise ValueError("snapshot_missing_recipient")

    cc = _as_optional_recipient_tuple(snapshot.get("cc"))
    bcc = _as_optional_recipient_tuple(snapshot.get("bcc"))
    if cc is None or bcc is None:
        raise ValueError("snapshot_invalid_optional_recipient")

    subject = _as_nonempty_string(snapshot.get("subject"))
    body = _as_nonempty_string(snapshot.get("body"))
    user_visible_summary = _as_nonempty_string(snapshot.get("user_visible_summary"))
    risk_level = _as_nonempty_string(snapshot.get("risk_level"))
    if subject is None:
        raise ValueError("snapshot_missing_subject")
    if body is None:
        raise ValueError("snapshot_missing_body")
    if user_visible_summary is None or risk_level is None:
        raise ValueError("snapshot_missing_required_fields")

    reply_to_message_id = snapshot.get("reply_to_message_id")
    if reply_to_message_id is not None:
        reply_to_message_id = _as_nonempty_string(reply_to_message_id)
        if reply_to_message_id is None:
            raise ValueError("snapshot_invalid_reply_to_message_id")

    return GmailDraftApprovedSnapshot(
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        body=body,
        reply_to_message_id=reply_to_message_id,
        user_visible_summary=user_visible_summary,
        risk_level=risk_level,
        capability_key=GMAIL_CREATE_DRAFT_CAPABILITY_KEY,
        action_type=GMAIL_CREATE_DRAFT_ACTION_TYPE,
    )


def run_disabled_gmail_create_draft(
    snapshot: dict[str, Any],
) -> GmailDraftRunnerResult:
    """Validate the snapshot and refuse execution while Gmail is not connected."""
    manifest = get_capability_manifest(GMAIL_CREATE_DRAFT_CAPABILITY_KEY)
    if manifest is None:
        return GmailDraftRunnerResult(
            capability_key=GMAIL_CREATE_DRAFT_CAPABILITY_KEY,
            action_type=GMAIL_CREATE_DRAFT_ACTION_TYPE,
            task_type="approved_gmail_draft_creation",
            status="refused",
            message="Gmail draft capability manifest is missing.",
            verification_status="manifest_missing",
        )

    try:
        validate_gmail_draft_snapshot(snapshot)
    except ValueError:
        return GmailDraftRunnerResult(
            capability_key=manifest.capability_key,
            action_type=manifest.action_type,
            task_type=manifest.task_type,
            status="refused",
            message="Gmail draft snapshot failed validation.",
            verification_status="snapshot_validation_failed",
        )

    if (
        manifest.implementation_status == "design_only"
        or not manifest.enabled
        or not manifest.current_runner_connected
    ):
        return GmailDraftRunnerResult(
            capability_key=manifest.capability_key,
            action_type=manifest.action_type,
            task_type=manifest.task_type,
            status="not_connected",
            message="Gmail draft runner is design-only and not connected.",
            manifest_connected=False,
            verification_status="not_run",
        )

    return GmailDraftRunnerResult(
        capability_key=manifest.capability_key,
        action_type=manifest.action_type,
        task_type=manifest.task_type,
        status="refused",
        message="Gmail draft runner has no executable implementation in v1.",
        manifest_connected=True,
        verification_status="runner_not_implemented",
    )
