"""Snapshot validation and building for future Gmail draft approvals.

This module is intentionally side-effect free. It imports no Gmail, Google,
OAuth, HTTP, browser, approval, notification, database, or grant code.
"""
from dataclasses import dataclass
from typing import Any

from app.core.approved_capability_manifest import (
    GMAIL_CREATE_DRAFT_ACTION_TYPE,
    GMAIL_CREATE_DRAFT_CAPABILITY_KEY,
)


OPTIONAL_SNAPSHOT_FIELDS = ("cc", "bcc", "reply_to_message_id")
REQUIRED_SNAPSHOT_FIELDS = (
    "to",
    "subject",
    "body",
    "user_visible_summary",
    "risk_level",
    "capability_key",
    "action_type",
)
ALLOWED_SNAPSHOT_FIELDS = REQUIRED_SNAPSHOT_FIELDS + OPTIONAL_SNAPSHOT_FIELDS
PROHIBITED_OPERATION_TERMS = (
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
    "bypass approval",
    "without approval",
    "skip approval",
)
PROHIBITED_PRIVATE_TERMS = (
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
class GmailDraftProposalInput:
    """Non-persistent proposal input for a future Gmail draft approval."""

    to: tuple[str, ...] | str
    subject: str
    body: str
    cc: tuple[str, ...] | str | None = None
    bcc: tuple[str, ...] | str | None = None
    reply_to_message_id: str | None = None


def as_nonempty_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def as_recipient_tuple(value: Any) -> tuple[str, ...] | None:
    if isinstance(value, str):
        item = value.strip()
        return (item,) if item else None
    if isinstance(value, (list, tuple)):
        recipients = []
        for item in value:
            text = as_nonempty_string(item)
            if text is None:
                return None
            recipients.append(text)
        return tuple(recipients) if recipients else None
    return None


def as_optional_recipient_tuple(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if isinstance(value, str) and not value.strip():
        return ()
    if isinstance(value, (list, tuple)) and not value:
        return ()
    return as_recipient_tuple(value)


def contains_prohibited_text(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            contains_prohibited_text(key) or contains_prohibited_text(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(contains_prohibited_text(item) for item in value)
    if not isinstance(value, str):
        return False

    normalized = value.lower()
    return any(term in normalized for term in PROHIBITED_OPERATION_TERMS) or any(
        term in normalized for term in PROHIBITED_PRIVATE_TERMS
    )


def validate_gmail_draft_snapshot(
    snapshot: dict[str, Any],
) -> GmailDraftApprovedSnapshot:
    """Validate the future Gmail draft approval snapshot without side effects."""
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot_must_be_mapping")

    field_names = set(snapshot)
    allowed = set(ALLOWED_SNAPSHOT_FIELDS)
    missing = set(REQUIRED_SNAPSHOT_FIELDS) - field_names
    if missing:
        raise ValueError("snapshot_missing_required_fields")
    if field_names - allowed:
        raise ValueError("snapshot_contains_unsupported_fields")

    if snapshot.get("capability_key") != GMAIL_CREATE_DRAFT_CAPABILITY_KEY:
        raise ValueError("snapshot_capability_mismatch")
    if snapshot.get("action_type") != GMAIL_CREATE_DRAFT_ACTION_TYPE:
        raise ValueError("snapshot_action_type_mismatch")
    if contains_prohibited_text(snapshot):
        raise ValueError("snapshot_contains_prohibited_behavior_or_private_data")

    to = as_recipient_tuple(snapshot.get("to"))
    if to is None:
        raise ValueError("snapshot_missing_recipient")

    cc = as_optional_recipient_tuple(snapshot.get("cc"))
    bcc = as_optional_recipient_tuple(snapshot.get("bcc"))
    if cc is None or bcc is None:
        raise ValueError("snapshot_invalid_optional_recipient")

    subject = as_nonempty_string(snapshot.get("subject"))
    body = as_nonempty_string(snapshot.get("body"))
    user_visible_summary = as_nonempty_string(snapshot.get("user_visible_summary"))
    risk_level = as_nonempty_string(snapshot.get("risk_level"))
    if subject is None:
        raise ValueError("snapshot_missing_subject")
    if body is None:
        raise ValueError("snapshot_missing_body")
    if user_visible_summary is None or risk_level is None:
        raise ValueError("snapshot_missing_required_fields")

    reply_to_message_id = snapshot.get("reply_to_message_id")
    if reply_to_message_id is not None:
        reply_to_message_id = as_nonempty_string(reply_to_message_id)
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


def format_recipients(recipients: tuple[str, ...]) -> str:
    if len(recipients) == 1:
        return recipients[0]
    return ", ".join(recipients)


def as_proposal_mapping(proposal: GmailDraftProposalInput | dict[str, Any]) -> dict:
    if isinstance(proposal, GmailDraftProposalInput):
        return {
            "to": proposal.to,
            "cc": proposal.cc,
            "bcc": proposal.bcc,
            "subject": proposal.subject,
            "body": proposal.body,
            "reply_to_message_id": proposal.reply_to_message_id,
        }
    if isinstance(proposal, dict):
        return dict(proposal)
    raise ValueError("proposal_must_be_mapping_or_input")


def build_gmail_create_draft_approval_snapshot(
    proposal: GmailDraftProposalInput | dict[str, Any],
) -> dict:
    """Build a non-executing approval snapshot for future Gmail draft creation."""
    proposal_data = as_proposal_mapping(proposal)
    unsupported = set(proposal_data) - set(OPTIONAL_SNAPSHOT_FIELDS) - {
        "to",
        "subject",
        "body",
    }
    if unsupported:
        raise ValueError("proposal_contains_unsupported_fields")

    to = as_recipient_tuple(proposal_data.get("to"))
    if to is None:
        raise ValueError("proposal_missing_recipient")

    subject = as_nonempty_string(proposal_data.get("subject"))
    body = as_nonempty_string(proposal_data.get("body"))
    if subject is None:
        raise ValueError("proposal_missing_subject")
    if body is None:
        raise ValueError("proposal_missing_body")

    cc = as_optional_recipient_tuple(proposal_data.get("cc"))
    bcc = as_optional_recipient_tuple(proposal_data.get("bcc"))
    if cc is None or bcc is None:
        raise ValueError("proposal_invalid_optional_recipient")

    reply_to_message_id = proposal_data.get("reply_to_message_id")
    if reply_to_message_id is not None:
        reply_to_message_id = as_nonempty_string(reply_to_message_id)
        if reply_to_message_id is None:
            raise ValueError("proposal_invalid_reply_to_message_id")

    summary = (
        f"Create a Gmail draft to {format_recipients(to)} with subject "
        f"'{subject}' for Matthew to review before any delivery decision."
    )
    snapshot = {
        "to": to,
        "cc": cc,
        "bcc": bcc,
        "subject": subject,
        "body": body,
        "reply_to_message_id": reply_to_message_id,
        "user_visible_summary": summary,
        "risk_level": "low_external_write",
        "capability_key": GMAIL_CREATE_DRAFT_CAPABILITY_KEY,
        "action_type": GMAIL_CREATE_DRAFT_ACTION_TYPE,
    }
    validate_gmail_draft_snapshot(snapshot)
    return snapshot


def is_approval_snapshot_shape(candidate: dict[str, Any]) -> bool:
    return set(candidate) == set(ALLOWED_SNAPSHOT_FIELDS)
