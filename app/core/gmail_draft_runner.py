"""Disabled Gmail draft runner skeleton.

The approval-preparation code lives in side-effect-free snapshot and planning
modules. This module remains the future runner boundary and compatibility
surface; it imports no Gmail, Google, OAuth, HTTP, browser, approval,
notification, database, or grant-consumption code.
"""
from dataclasses import dataclass
from typing import Any

from app.core.approved_capability_manifest import (
    GMAIL_CREATE_DRAFT_ACTION_TYPE,
    GMAIL_CREATE_DRAFT_CAPABILITY_KEY,
    get_capability_manifest,
)
from app.core.gmail_draft_approval_plan import (
    GmailDraftApprovalCreationPreview,
    GmailDraftApprovalPersistencePreview,
    GmailDraftApprovalPreview,
    GmailDraftApprovalRequestPlan,
    GmailDraftApprovalRequestPreview,
    GmailDraftLiveApprovalGateReview,
    build_gmail_create_draft_approval_request_plan,
    is_gmail_create_draft_live_approval_enabled,
    prepare_disabled_gmail_create_draft_approval_creation,
    prepare_disabled_gmail_create_draft_pending_approval_insert,
    prepare_gmail_create_draft_approval_preview,
    prepare_gmail_create_draft_approval_request_preview,
    review_disabled_gmail_create_draft_live_approval_gate,
)
from app.core.gmail_draft_snapshot import (
    GmailDraftApprovedSnapshot,
    GmailDraftProposalInput,
    build_gmail_create_draft_approval_snapshot,
    validate_gmail_draft_snapshot,
)


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
