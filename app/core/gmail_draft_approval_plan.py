"""Disabled approval planning for future Gmail draft creation.

This module builds one side-effect-free plan that preserves the exact reviewed
Gmail draft fields and the singular future pending-approval insert shape.
"""
from dataclasses import dataclass
from typing import Any

from app.core.approved_capability_manifest import (
    GMAIL_CREATE_DRAFT_ACTION_TYPE,
    GMAIL_CREATE_DRAFT_CAPABILITY_KEY,
    get_capability_manifest,
)
from app.core.gmail_draft_snapshot import (
    GmailDraftProposalInput,
    as_nonempty_string,
    build_gmail_create_draft_approval_snapshot,
    contains_prohibited_text,
    format_recipients,
    is_approval_snapshot_shape,
    validate_gmail_draft_snapshot,
)


BASE_WARNINGS = (
    "draft_only",
    "not_sent",
    "no_attachments",
    "no_delete_archive_forward",
    "gmail_not_connected_yet",
    "approval_not_created_yet",
)


@dataclass(frozen=True)
class GmailDraftApprovalRequestPlan:
    """Consolidated disabled plan for the future approval insertion boundary."""

    validated_snapshot: dict
    preview_fields: dict
    capability_key: str
    action_type: str
    task_type: str
    risk_level: str
    human_name: str
    user_visible_summary: str
    step_summary: str
    ttl_minutes: int
    verified_insert_parameters: dict
    approval_required: bool
    live_creation_enabled: bool
    gate_status: str
    refusal_reason: str
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
    """Compatibility view of the consolidated approval request plan."""

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
    """Compatibility view for disabled insert-parameter validation."""

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
    """Compatibility view for the disabled approval-creation boundary."""

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
    """Compatibility view of the disabled live approval gate."""

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


def is_gmail_create_draft_live_approval_enabled() -> bool:
    """Feature gate placeholder; disabled by default and fail-closed."""
    return False


def verify_gmail_create_draft_insert_parameters(insert_parameters: dict) -> dict:
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

    step_summary = as_nonempty_string(insert_parameters.get("step_summary"))
    if step_summary is None or contains_prohibited_text(step_summary):
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


def _snapshot_from_input(
    proposal_or_snapshot: GmailDraftProposalInput | dict[str, Any],
) -> dict:
    if isinstance(proposal_or_snapshot, dict) and is_approval_snapshot_shape(
        proposal_or_snapshot
    ):
        snapshot = dict(proposal_or_snapshot)
        validate_gmail_draft_snapshot(snapshot)
        return snapshot
    return build_gmail_create_draft_approval_snapshot(proposal_or_snapshot)


def _manifest_is_disabled_safe(manifest) -> bool:
    return (
        manifest.capability_key == GMAIL_CREATE_DRAFT_CAPABILITY_KEY
        and manifest.action_type == GMAIL_CREATE_DRAFT_ACTION_TYPE
        and manifest.implementation_status == "design_only"
        and not manifest.enabled
        and not manifest.external_action_allowed
        and not manifest.current_runner_connected
    )


def build_gmail_create_draft_approval_request_plan(
    proposal_or_snapshot: GmailDraftProposalInput | dict[str, Any],
    ttl_minutes: int = 10,
) -> GmailDraftApprovalRequestPlan:
    """Build the one disabled approval request plan; never insert or notify."""
    if not isinstance(ttl_minutes, int) or ttl_minutes < 1 or ttl_minutes > 60:
        raise ValueError("ttl_minutes_out_of_range")

    manifest = get_capability_manifest(GMAIL_CREATE_DRAFT_CAPABILITY_KEY)
    if manifest is None:
        raise ValueError("gmail_create_draft_manifest_missing")
    if not _manifest_is_disabled_safe(manifest):
        raise ValueError("gmail_create_draft_manifest_not_disabled_safe")

    snapshot = _snapshot_from_input(proposal_or_snapshot)
    preview_fields = {
        "to": snapshot["to"],
        "cc": snapshot["cc"],
        "bcc": snapshot["bcc"],
        "subject": snapshot["subject"],
        "body": snapshot["body"],
        "reply_to_message_id": snapshot["reply_to_message_id"],
    }
    step_summary = (
        f"Review Gmail draft to {format_recipients(snapshot['to'])} with subject "
        f"'{snapshot['subject']}'"
    )
    verified_insert_parameters = verify_gmail_create_draft_insert_parameters(
        {
            "capability_key": manifest.capability_key,
            "action_type": manifest.action_type,
            "step_summary": step_summary,
            "ttl_minutes": ttl_minutes,
        }
    )
    live_creation_enabled = is_gmail_create_draft_live_approval_enabled()
    if live_creation_enabled:
        raise ValueError("gmail_live_approval_creation_not_available")

    return GmailDraftApprovalRequestPlan(
        validated_snapshot=snapshot,
        preview_fields=preview_fields,
        capability_key=manifest.capability_key,
        action_type=manifest.action_type,
        task_type=manifest.task_type,
        risk_level=snapshot["risk_level"],
        human_name=manifest.human_name,
        user_visible_summary=snapshot["user_visible_summary"],
        step_summary=verified_insert_parameters["step_summary"],
        ttl_minutes=verified_insert_parameters["ttl_minutes"],
        verified_insert_parameters=verified_insert_parameters,
        approval_required=manifest.approval_required,
        live_creation_enabled=False,
        gate_status="disabled_refused",
        refusal_reason="gmail_live_approval_creation_disabled",
        warnings=BASE_WARNINGS
        + (
            "request_preview_only",
            "persistence_disabled_preview_only",
            "creation_disabled_before_insert",
            "live_approval_gate_disabled",
        ),
    )


def _preview_from_plan(plan: GmailDraftApprovalRequestPlan) -> GmailDraftApprovalPreview:
    return GmailDraftApprovalPreview(
        capability_key=plan.capability_key,
        action_type=plan.action_type,
        task_type=plan.task_type,
        risk_level=plan.risk_level,
        human_name=plan.human_name,
        user_visible_summary=plan.user_visible_summary,
        preview_fields=plan.preview_fields,
        status="preview_only",
        warnings=BASE_WARNINGS,
    )


def prepare_gmail_create_draft_approval_preview(
    proposal_or_snapshot: GmailDraftProposalInput | dict[str, Any],
) -> GmailDraftApprovalPreview:
    plan = build_gmail_create_draft_approval_request_plan(proposal_or_snapshot)
    return _preview_from_plan(plan)


def prepare_gmail_create_draft_approval_request_preview(
    proposal_or_snapshot_or_preview: (
        GmailDraftProposalInput | dict[str, Any] | GmailDraftApprovalPreview
    ),
    ttl_minutes: int = 10,
) -> GmailDraftApprovalRequestPreview:
    if isinstance(proposal_or_snapshot_or_preview, GmailDraftApprovalPreview):
        preview = proposal_or_snapshot_or_preview
        if preview.capability_key != GMAIL_CREATE_DRAFT_CAPABILITY_KEY:
            raise ValueError("preview_capability_mismatch")
        if preview.action_type != GMAIL_CREATE_DRAFT_ACTION_TYPE:
            raise ValueError("preview_action_type_mismatch")
        plan = build_gmail_create_draft_approval_request_plan(
            {
                "to": preview.preview_fields["to"],
                "cc": preview.preview_fields["cc"],
                "bcc": preview.preview_fields["bcc"],
                "subject": preview.preview_fields["subject"],
                "body": preview.preview_fields["body"],
                "reply_to_message_id": preview.preview_fields["reply_to_message_id"],
            },
            ttl_minutes=ttl_minutes,
        )
    else:
        plan = build_gmail_create_draft_approval_request_plan(
            proposal_or_snapshot_or_preview,
            ttl_minutes=ttl_minutes,
        )
        preview = _preview_from_plan(plan)

    return GmailDraftApprovalRequestPreview(
        capability_key=plan.capability_key,
        action_type=plan.action_type,
        task_type=plan.task_type,
        risk_level=plan.risk_level,
        human_name=plan.human_name,
        step_summary=plan.step_summary,
        ttl_minutes=plan.ttl_minutes,
        preview=preview,
        approval_required=plan.approval_required,
        status="request_preview_only",
        warnings=BASE_WARNINGS + ("request_preview_only",),
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
    if isinstance(proposal_or_snapshot_or_preview, GmailDraftApprovalRequestPreview):
        request_preview = proposal_or_snapshot_or_preview
        if request_preview.capability_key != GMAIL_CREATE_DRAFT_CAPABILITY_KEY:
            raise ValueError("request_preview_capability_mismatch")
        if request_preview.action_type != GMAIL_CREATE_DRAFT_ACTION_TYPE:
            raise ValueError("request_preview_action_type_mismatch")
        if request_preview.status != "request_preview_only":
            raise ValueError("request_preview_status_not_preview_only")
        if not request_preview.approval_required:
            raise ValueError("request_preview_missing_approval_requirement")
        insert_parameters = verify_gmail_create_draft_insert_parameters(
            {
                "capability_key": request_preview.capability_key,
                "action_type": request_preview.action_type,
                "step_summary": request_preview.step_summary,
                "ttl_minutes": request_preview.ttl_minutes,
            }
        )
        warnings = request_preview.warnings + ("persistence_disabled_preview_only",)
        task_type = request_preview.task_type
        status = request_preview.status
    else:
        plan = build_gmail_create_draft_approval_request_plan(
            proposal_or_snapshot_or_preview,
            ttl_minutes=ttl_minutes,
        )
        insert_parameters = plan.verified_insert_parameters
        warnings = BASE_WARNINGS + (
            "request_preview_only",
            "persistence_disabled_preview_only",
        )
        task_type = plan.task_type
        status = "request_preview_only"

    return GmailDraftApprovalPersistencePreview(
        capability_key=insert_parameters["capability_key"],
        action_type=insert_parameters["action_type"],
        task_type=task_type,
        step_summary=insert_parameters["step_summary"],
        ttl_minutes=insert_parameters["ttl_minutes"],
        request_preview_status=status,
        persistence_status="disabled_preview_only",
        insert_parameters=insert_parameters,
        warnings=warnings,
    )


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
    if isinstance(proposal_or_snapshot_or_preview, GmailDraftApprovalPersistencePreview):
        persistence_preview = proposal_or_snapshot_or_preview
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
    else:
        persistence_preview = prepare_disabled_gmail_create_draft_pending_approval_insert(
            proposal_or_snapshot_or_preview,
            ttl_minutes=ttl_minutes,
        )

    verified_insert_parameters = verify_gmail_create_draft_insert_parameters(
        persistence_preview.insert_parameters
    )
    return GmailDraftApprovalCreationPreview(
        capability_key=verified_insert_parameters["capability_key"],
        action_type=verified_insert_parameters["action_type"],
        task_type=persistence_preview.task_type,
        step_summary=verified_insert_parameters["step_summary"],
        ttl_minutes=verified_insert_parameters["ttl_minutes"],
        creation_status="disabled_before_insert",
        refusal_reason="gmail_create_draft_approval_creation_disabled",
        verified_insert_parameters=verified_insert_parameters,
        warnings=persistence_preview.warnings + ("creation_disabled_before_insert",),
    )


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
    manifest = get_capability_manifest(GMAIL_CREATE_DRAFT_CAPABILITY_KEY)
    if manifest is None:
        raise ValueError("gmail_create_draft_manifest_missing")
    manifest_safe = _manifest_is_disabled_safe(manifest)
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

    verified_insert_parameters = verify_gmail_create_draft_insert_parameters(
        creation_preview.verified_insert_parameters
    )
    if is_gmail_create_draft_live_approval_enabled():
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
