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
    "bypass approval",
    "without approval",
    "skip approval",
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
class GmailDraftProposalInput:
    """Non-persistent proposal input for a future Gmail draft approval."""

    to: tuple[str, ...] | str
    subject: str
    body: str
    cc: tuple[str, ...] | str | None = None
    bcc: tuple[str, ...] | str | None = None
    reply_to_message_id: str | None = None


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


@dataclass(frozen=True)
class GmailDraftApprovalPreview:
    """Sanitized, non-persistent preview for future Matthew approval review."""

    capability_key: str
    action_type: str
    task_type: str
    risk_level: str
    human_name: str
    user_visible_summary: str
    preview_fields: dict
    status: str
    warnings: tuple[str, ...]
    approval_created: bool = False
    notification_sent: bool = False
    external_action_performed: bool = False
    draft_created: bool = False
    approval_grant_consumed: bool = False


@dataclass(frozen=True)
class GmailDraftApprovalRequestPreview:
    """Future pending-approval payload shape, without inserting anything."""

    capability_key: str
    action_type: str
    task_type: str
    risk_level: str
    human_name: str
    step_summary: str
    ttl_minutes: int
    preview: GmailDraftApprovalPreview
    approval_required: bool
    status: str
    warnings: tuple[str, ...]
    approval_created: bool = False
    notification_sent: bool = False
    external_action_performed: bool = False
    draft_created: bool = False
    approval_grant_consumed: bool = False


@dataclass(frozen=True)
class GmailDraftApprovalPersistencePreview:
    """Disabled persistence package; validates insert shape without writing."""

    capability_key: str
    action_type: str
    task_type: str
    step_summary: str
    ttl_minutes: int
    request_preview_status: str
    persistence_status: str
    insert_parameters: dict
    warnings: tuple[str, ...]
    would_insert: bool = False
    approval_created: bool = False
    approval_inserted_into_database: bool = False
    notification_sent: bool = False
    external_action_performed: bool = False
    draft_created: bool = False
    approval_grant_consumed: bool = False


@dataclass(frozen=True)
class GmailDraftApprovalCreationPreview:
    """Disabled approval creation boundary; refuses before insert creation."""

    capability_key: str
    action_type: str
    task_type: str
    step_summary: str
    ttl_minutes: int
    creation_status: str
    refusal_reason: str
    verified_insert_parameters: dict
    warnings: tuple[str, ...]
    would_call_create_pending_approval_once: bool = False
    would_insert: bool = False
    approval_created: bool = False
    approval_inserted_into_database: bool = False
    notification_sent: bool = False
    external_action_performed: bool = False
    draft_created: bool = False
    approval_grant_consumed: bool = False


@dataclass(frozen=True)
class GmailDraftLiveApprovalGateReview:
    """End-to-end disabled gate review before future live approval creation."""

    capability_key: str
    action_type: str
    task_type: str
    gate_status: str
    refusal_reason: str
    live_creation_enabled: bool
    manifest_safe: bool
    preparation_chain_valid: bool
    verified_insert_parameters: dict
    warnings: tuple[str, ...]
    would_call_create_pending_approval_once: bool = False
    would_insert: bool = False
    approval_created: bool = False
    approval_inserted_into_database: bool = False
    notification_sent: bool = False
    external_action_performed: bool = False
    draft_created: bool = False
    approval_grant_consumed: bool = False


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


def _format_recipients(recipients: tuple[str, ...]) -> str:
    if len(recipients) == 1:
        return recipients[0]
    return ", ".join(recipients)


def _as_proposal_mapping(proposal: GmailDraftProposalInput | dict[str, Any]) -> dict:
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
    """Build a non-executing approval snapshot for future Gmail draft creation.

    The returned dictionary is not stored, not sent, not routed, and not run.
    It is the exact future approval package shape that Matthew would review.
    """
    proposal_data = _as_proposal_mapping(proposal)
    unsupported = set(proposal_data) - set(_OPTIONAL_SNAPSHOT_FIELDS) - {
        "to",
        "subject",
        "body",
    }
    if unsupported:
        raise ValueError("proposal_contains_unsupported_fields")

    to = _as_recipient_tuple(proposal_data.get("to"))
    if to is None:
        raise ValueError("proposal_missing_recipient")

    subject = _as_nonempty_string(proposal_data.get("subject"))
    body = _as_nonempty_string(proposal_data.get("body"))
    if subject is None:
        raise ValueError("proposal_missing_subject")
    if body is None:
        raise ValueError("proposal_missing_body")

    cc = _as_optional_recipient_tuple(proposal_data.get("cc"))
    bcc = _as_optional_recipient_tuple(proposal_data.get("bcc"))
    if cc is None or bcc is None:
        raise ValueError("proposal_invalid_optional_recipient")

    reply_to_message_id = proposal_data.get("reply_to_message_id")
    if reply_to_message_id is not None:
        reply_to_message_id = _as_nonempty_string(reply_to_message_id)
        if reply_to_message_id is None:
            raise ValueError("proposal_invalid_reply_to_message_id")

    summary = (
        f"Create a Gmail draft to {_format_recipients(to)} with subject "
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


def _is_approval_snapshot_shape(candidate: dict[str, Any]) -> bool:
    return set(candidate) == set(_ALLOWED_SNAPSHOT_FIELDS)


def prepare_gmail_create_draft_approval_preview(
    proposal_or_snapshot: GmailDraftProposalInput | dict[str, Any],
) -> GmailDraftApprovalPreview:
    """Prepare a sanitized preview only; do not create approval or execute."""
    if isinstance(proposal_or_snapshot, dict) and _is_approval_snapshot_shape(
        proposal_or_snapshot
    ):
        snapshot = dict(proposal_or_snapshot)
        validate_gmail_draft_snapshot(snapshot)
    else:
        snapshot = build_gmail_create_draft_approval_snapshot(proposal_or_snapshot)

    manifest = get_capability_manifest(GMAIL_CREATE_DRAFT_CAPABILITY_KEY)
    if manifest is None:
        raise ValueError("gmail_create_draft_manifest_missing")

    preview_fields = {
        "to": snapshot["to"],
        "cc": snapshot["cc"],
        "bcc": snapshot["bcc"],
        "subject": snapshot["subject"],
        "body": snapshot["body"],
        "reply_to_message_id": snapshot["reply_to_message_id"],
    }
    warnings = (
        "draft_only",
        "not_sent",
        "no_attachments",
        "no_delete_archive_forward",
        "gmail_not_connected_yet",
        "approval_not_created_yet",
    )
    return GmailDraftApprovalPreview(
        capability_key=manifest.capability_key,
        action_type=manifest.action_type,
        task_type=manifest.task_type,
        risk_level=snapshot["risk_level"],
        human_name=manifest.human_name,
        user_visible_summary=snapshot["user_visible_summary"],
        preview_fields=preview_fields,
        status="preview_only",
        warnings=warnings,
    )


def prepare_gmail_create_draft_approval_request_preview(
    proposal_or_snapshot_or_preview: (
        GmailDraftProposalInput | dict[str, Any] | GmailDraftApprovalPreview
    ),
    ttl_minutes: int = 10,
) -> GmailDraftApprovalRequestPreview:
    """Build a disabled future pending-approval payload preview only."""
    if not isinstance(ttl_minutes, int) or ttl_minutes < 1 or ttl_minutes > 60:
        raise ValueError("ttl_minutes_out_of_range")

    if isinstance(proposal_or_snapshot_or_preview, GmailDraftApprovalPreview):
        preview = proposal_or_snapshot_or_preview
    else:
        preview = prepare_gmail_create_draft_approval_preview(
            proposal_or_snapshot_or_preview
        )

    manifest = get_capability_manifest(GMAIL_CREATE_DRAFT_CAPABILITY_KEY)
    if manifest is None:
        raise ValueError("gmail_create_draft_manifest_missing")
    if preview.capability_key != GMAIL_CREATE_DRAFT_CAPABILITY_KEY:
        raise ValueError("preview_capability_mismatch")
    if preview.action_type != GMAIL_CREATE_DRAFT_ACTION_TYPE:
        raise ValueError("preview_action_type_mismatch")

    recipients = preview.preview_fields["to"]
    subject = preview.preview_fields["subject"]
    step_summary = (
        f"Review Gmail draft to {_format_recipients(recipients)} with subject "
        f"'{subject}'"
    )
    warnings = preview.warnings + ("request_preview_only",)
    return GmailDraftApprovalRequestPreview(
        capability_key=manifest.capability_key,
        action_type=manifest.action_type,
        task_type=manifest.task_type,
        risk_level=preview.risk_level,
        human_name=manifest.human_name,
        step_summary=step_summary,
        ttl_minutes=ttl_minutes,
        preview=preview,
        approval_required=manifest.approval_required,
        status="request_preview_only",
        warnings=warnings,
    )


def prepare_disabled_gmail_create_draft_pending_approval_insert(
    proposal_or_snapshot_or_preview: (
        GmailDraftProposalInput
        | dict[str, Any]
        | GmailDraftApprovalPreview
        | GmailDraftApprovalRequestPreview
    ),
    ttl_minutes: int = 10,
) -> GmailDraftApprovalPersistencePreview:
    """Return safe future insert parameters only; never insert or notify."""
    if isinstance(proposal_or_snapshot_or_preview, GmailDraftApprovalRequestPreview):
        request_preview = proposal_or_snapshot_or_preview
    else:
        request_preview = prepare_gmail_create_draft_approval_request_preview(
            proposal_or_snapshot_or_preview,
            ttl_minutes=ttl_minutes,
        )

    if request_preview.capability_key != GMAIL_CREATE_DRAFT_CAPABILITY_KEY:
        raise ValueError("request_preview_capability_mismatch")
    if request_preview.action_type != GMAIL_CREATE_DRAFT_ACTION_TYPE:
        raise ValueError("request_preview_action_type_mismatch")
    if request_preview.status != "request_preview_only":
        raise ValueError("request_preview_status_not_preview_only")
    if not request_preview.approval_required:
        raise ValueError("request_preview_missing_approval_requirement")

    insert_parameters = {
        "capability_key": request_preview.capability_key,
        "action_type": request_preview.action_type,
        "step_summary": request_preview.step_summary,
        "ttl_minutes": request_preview.ttl_minutes,
    }
    return GmailDraftApprovalPersistencePreview(
        capability_key=request_preview.capability_key,
        action_type=request_preview.action_type,
        task_type=request_preview.task_type,
        step_summary=request_preview.step_summary,
        ttl_minutes=request_preview.ttl_minutes,
        request_preview_status=request_preview.status,
        persistence_status="disabled_preview_only",
        insert_parameters=insert_parameters,
        warnings=request_preview.warnings + ("persistence_disabled_preview_only",),
    )


def _verify_disabled_gmail_insert_parameters(insert_parameters: dict) -> dict:
    expected_fields = {
        "capability_key",
        "action_type",
        "step_summary",
        "ttl_minutes",
    }
    if not isinstance(insert_parameters, dict):
        raise ValueError("insert_parameters_must_be_mapping")
    if set(insert_parameters) != expected_fields:
        raise ValueError("insert_parameters_shape_mismatch")
    if insert_parameters["capability_key"] != GMAIL_CREATE_DRAFT_CAPABILITY_KEY:
        raise ValueError("insert_parameters_capability_mismatch")
    if insert_parameters["action_type"] != GMAIL_CREATE_DRAFT_ACTION_TYPE:
        raise ValueError("insert_parameters_action_type_mismatch")

    step_summary = _as_nonempty_string(insert_parameters.get("step_summary"))
    if step_summary is None or _contains_prohibited_text(step_summary):
        raise ValueError("insert_parameters_step_summary_unsafe")

    ttl_minutes = insert_parameters.get("ttl_minutes")
    if not isinstance(ttl_minutes, int) or ttl_minutes < 1 or ttl_minutes > 60:
        raise ValueError("insert_parameters_ttl_unsafe")

    return {
        "capability_key": GMAIL_CREATE_DRAFT_CAPABILITY_KEY,
        "action_type": GMAIL_CREATE_DRAFT_ACTION_TYPE,
        "step_summary": step_summary,
        "ttl_minutes": ttl_minutes,
    }


def prepare_disabled_gmail_create_draft_approval_creation(
    proposal_or_snapshot_or_preview: (
        GmailDraftProposalInput
        | dict[str, Any]
        | GmailDraftApprovalPreview
        | GmailDraftApprovalRequestPreview
        | GmailDraftApprovalPersistencePreview
    ),
    ttl_minutes: int = 10,
) -> GmailDraftApprovalCreationPreview:
    """Validate creation inputs and refuse before pending approval creation."""
    if isinstance(proposal_or_snapshot_or_preview, GmailDraftApprovalPersistencePreview):
        persistence_preview = proposal_or_snapshot_or_preview
    else:
        persistence_preview = (
            prepare_disabled_gmail_create_draft_pending_approval_insert(
                proposal_or_snapshot_or_preview,
                ttl_minutes=ttl_minutes,
            )
        )

    if persistence_preview.capability_key != GMAIL_CREATE_DRAFT_CAPABILITY_KEY:
        raise ValueError("persistence_preview_capability_mismatch")
    if persistence_preview.action_type != GMAIL_CREATE_DRAFT_ACTION_TYPE:
        raise ValueError("persistence_preview_action_type_mismatch")
    if persistence_preview.persistence_status != "disabled_preview_only":
        raise ValueError("persistence_preview_status_not_disabled")
    if persistence_preview.would_insert:
        raise ValueError("persistence_preview_would_insert")
    if persistence_preview.approval_created:
        raise ValueError("persistence_preview_approval_created")
    if persistence_preview.approval_inserted_into_database:
        raise ValueError("persistence_preview_inserted")

    verified_insert_parameters = _verify_disabled_gmail_insert_parameters(
        persistence_preview.insert_parameters
    )
    return GmailDraftApprovalCreationPreview(
        capability_key=GMAIL_CREATE_DRAFT_CAPABILITY_KEY,
        action_type=GMAIL_CREATE_DRAFT_ACTION_TYPE,
        task_type=persistence_preview.task_type,
        step_summary=verified_insert_parameters["step_summary"],
        ttl_minutes=verified_insert_parameters["ttl_minutes"],
        creation_status="disabled_before_insert",
        refusal_reason="gmail_create_draft_approval_creation_disabled",
        verified_insert_parameters=verified_insert_parameters,
        warnings=persistence_preview.warnings + ("creation_disabled_before_insert",),
    )


def is_gmail_create_draft_live_approval_enabled() -> bool:
    """Feature gate placeholder; disabled by default and fail-closed."""
    return False


def review_disabled_gmail_create_draft_live_approval_gate(
    proposal_or_snapshot_or_preview: (
        GmailDraftProposalInput
        | dict[str, Any]
        | GmailDraftApprovalPreview
        | GmailDraftApprovalRequestPreview
        | GmailDraftApprovalPersistencePreview
        | GmailDraftApprovalCreationPreview
    ),
    ttl_minutes: int = 10,
) -> GmailDraftLiveApprovalGateReview:
    """Review every disabled Gmail draft approval boundary and refuse live insert."""
    manifest = get_capability_manifest(GMAIL_CREATE_DRAFT_CAPABILITY_KEY)
    if manifest is None:
        raise ValueError("gmail_create_draft_manifest_missing")

    manifest_safe = (
        manifest.capability_key == GMAIL_CREATE_DRAFT_CAPABILITY_KEY
        and manifest.action_type == GMAIL_CREATE_DRAFT_ACTION_TYPE
        and manifest.implementation_status == "design_only"
        and not manifest.enabled
        and not manifest.external_action_allowed
        and not manifest.current_runner_connected
    )
    if not manifest_safe:
        raise ValueError("gmail_create_draft_manifest_not_disabled_safe")

    if isinstance(proposal_or_snapshot_or_preview, GmailDraftApprovalCreationPreview):
        creation_preview = proposal_or_snapshot_or_preview
    else:
        creation_preview = prepare_disabled_gmail_create_draft_approval_creation(
            proposal_or_snapshot_or_preview,
            ttl_minutes=ttl_minutes,
        )

    if creation_preview.capability_key != GMAIL_CREATE_DRAFT_CAPABILITY_KEY:
        raise ValueError("creation_preview_capability_mismatch")
    if creation_preview.action_type != GMAIL_CREATE_DRAFT_ACTION_TYPE:
        raise ValueError("creation_preview_action_type_mismatch")
    if creation_preview.creation_status != "disabled_before_insert":
        raise ValueError("creation_preview_status_not_disabled")
    if creation_preview.would_call_create_pending_approval_once:
        raise ValueError("creation_preview_would_call_create_pending_approval_once")
    if creation_preview.would_insert:
        raise ValueError("creation_preview_would_insert")
    if creation_preview.approval_created:
        raise ValueError("creation_preview_approval_created")
    if creation_preview.approval_inserted_into_database:
        raise ValueError("creation_preview_inserted")
    if creation_preview.notification_sent:
        raise ValueError("creation_preview_notification_sent")
    if creation_preview.external_action_performed or creation_preview.draft_created:
        raise ValueError("creation_preview_external_action")
    if creation_preview.approval_grant_consumed:
        raise ValueError("creation_preview_grant_consumed")

    verified_insert_parameters = _verify_disabled_gmail_insert_parameters(
        creation_preview.verified_insert_parameters
    )
    live_creation_enabled = is_gmail_create_draft_live_approval_enabled()
    if live_creation_enabled:
        raise ValueError("gmail_live_approval_creation_not_available")

    return GmailDraftLiveApprovalGateReview(
        capability_key=manifest.capability_key,
        action_type=manifest.action_type,
        task_type=manifest.task_type,
        gate_status="disabled_refused",
        refusal_reason="gmail_live_approval_creation_disabled",
        live_creation_enabled=False,
        manifest_safe=manifest_safe,
        preparation_chain_valid=True,
        verified_insert_parameters=verified_insert_parameters,
        warnings=creation_preview.warnings + ("live_approval_gate_disabled",),
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
