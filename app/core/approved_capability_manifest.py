"""Capability Manifest v1 for explicitly safe approved runners.

This is intentionally separate from the general database-backed capability
registry. It is an immutable, code-owned allowlist for the approved-task
runner boundary. Adding a real capability here requires an explicit design
review of scope, preconditions, verification, and external-effect policy.
"""
from dataclasses import dataclass
from types import MappingProxyType

from app.core.approval_lock import (
    TEST_APPROVED_NOOP_ACTION_TYPE,
    TEST_APPROVED_NOOP_CAPABILITY_KEY,
    TEST_APPROVAL_RESUME_ACTION_TYPE,
    TEST_APPROVAL_RESUME_CAPABILITY_KEY,
)


@dataclass(frozen=True)
class ApprovedCapabilityManifest:
    """Static policy for one approved task-runner capability."""

    capability_key: str
    action_type: str
    task_type: str
    human_name: str
    description: str
    risk_level: str
    approval_required: bool
    external_action_allowed: bool
    notification_allowed: bool
    runner_type: str
    implementation_status: str
    enabled: bool
    current_runner_connected: bool
    preconditions: tuple[str, ...]
    verification_requirements: tuple[str, ...]
    allowed_outputs: tuple[str, ...]
    approval_snapshot_required_fields: tuple[str, ...] = ()
    scope_boundary: tuple[str, ...] = ()
    out_of_scope_operations: tuple[str, ...] = ()
    fail_closed_if: tuple[str, ...] = ()


TEST_APPROVAL_RESUME_MANIFEST = ApprovedCapabilityManifest(
    capability_key=TEST_APPROVAL_RESUME_CAPABILITY_KEY,
    action_type=TEST_APPROVAL_RESUME_ACTION_TYPE,
    task_type="harmless_approval_resume_test",
    human_name="Harmless approval-resume test",
    description="Consumes one approved test grant and reports a verified no-op.",
    risk_level="test_only",
    approval_required=True,
    external_action_allowed=False,
    notification_allowed=False,
    runner_type="no_op_approved_runner",
    implementation_status="connected",
    enabled=True,
    current_runner_connected=True,
    preconditions=(
        "approved_pending_approval",
        "active_unexpired_unconsumed_grant",
    ),
    verification_requirements=("no_op_verified",),
    allowed_outputs=("completed", "not_resumed", "no_op_verified"),
)

TEST_APPROVED_NOOP_MANIFEST = ApprovedCapabilityManifest(
    capability_key=TEST_APPROVED_NOOP_CAPABILITY_KEY,
    action_type=TEST_APPROVED_NOOP_ACTION_TYPE,
    task_type="harmless_approved_noop_test",
    human_name="Harmless approved no-op test",
    description="Consumes one approved no-op grant and reports a verified no-op.",
    risk_level="test_only",
    approval_required=True,
    external_action_allowed=False,
    notification_allowed=False,
    runner_type="no_op_approved_runner",
    implementation_status="connected",
    enabled=True,
    current_runner_connected=True,
    preconditions=(
        "approved_pending_approval",
        "active_unexpired_unconsumed_grant",
    ),
    verification_requirements=("no_op_verified",),
    allowed_outputs=("completed", "not_resumed", "no_op_verified"),
)

GMAIL_CREATE_DRAFT_CAPABILITY_KEY = "gmail.create_draft"
GMAIL_CREATE_DRAFT_ACTION_TYPE = "gmail_create_draft"
GMAIL_CREATE_DRAFT_MANIFEST = ApprovedCapabilityManifest(
    capability_key=GMAIL_CREATE_DRAFT_CAPABILITY_KEY,
    action_type=GMAIL_CREATE_DRAFT_ACTION_TYPE,
    task_type="approved_gmail_draft_creation",
    human_name="Create Gmail draft",
    description=(
        "Create a reviewable Gmail draft after Matthew approves the exact "
        "recipient, subject, and body."
    ),
    risk_level="low_external_write",
    approval_required=True,
    external_action_allowed=False,
    notification_allowed=False,
    runner_type="gmail_draft_runner",
    implementation_status="design_only",
    enabled=False,
    current_runner_connected=False,
    preconditions=(
        "registered_manifest_exists",
        "capability_enabled_and_connected_before_execution",
        "approval_approved_unexpired_unconsumed",
        "approved_snapshot_capability_key_matches_gmail_create_draft",
        "approved_snapshot_action_type_matches_gmail_create_draft",
        "recipient_list_explicit_and_user_visible",
        "subject_and_body_explicit_and_user_visible",
        "no_send_flag_present",
        "no_attachment_instruction_present",
        "no_delete_archive_forward_send_operation_present",
    ),
    verification_requirements=(
        "gmail_api_returned_draft_created_success",
        "created_object_is_draft_not_sent_message",
        "recipient_subject_body_match_approved_snapshot",
        "safe_result_reports_only_sanitized_metadata",
        "failure_not_reported_completed_without_verified_draft_creation",
    ),
    allowed_outputs=(
        "design_only_not_connected",
        "not_run",
        "refused",
        "draft_created_verified",
    ),
    approval_snapshot_required_fields=(
        "to",
        "cc",
        "bcc",
        "subject",
        "body",
        "reply_to_message_id",
        "user_visible_summary",
        "risk_level",
        "capability_key",
        "action_type",
    ),
    scope_boundary=(
        "create_gmail_draft_only",
        "reviewable_draft_after_exact_approval",
        "optional_reply_to_message_id_only_from_safe_prior_flow",
    ),
    out_of_scope_operations=(
        "send",
        "delete",
        "archive",
        "forward",
        "broad_inbox_read",
        "attachments",
        "modify_existing_draft",
    ),
    fail_closed_if=(
        "manifest_missing",
        "manifest_design_only_or_not_connected",
        "approval_missing_expired_rejected_consumed_or_mismatched",
        "approved_snapshot_missing_required_fields",
        "snapshot_includes_send_delete_archive_forward_attachment_or_broad_read",
        "draft_creation_verification_failed",
        "secret_token_raw_gmail_payload_exposure_risk",
    ),
)


APPROVED_CAPABILITY_MANIFESTS = MappingProxyType(
    {
        TEST_APPROVAL_RESUME_MANIFEST.capability_key: TEST_APPROVAL_RESUME_MANIFEST,
        TEST_APPROVED_NOOP_MANIFEST.capability_key: TEST_APPROVED_NOOP_MANIFEST,
        GMAIL_CREATE_DRAFT_MANIFEST.capability_key: GMAIL_CREATE_DRAFT_MANIFEST,
    }
)


def get_capability_manifest(capability_key: str) -> ApprovedCapabilityManifest | None:
    """Return one registered runner manifest without creating or mutating state."""
    return APPROVED_CAPABILITY_MANIFESTS.get(capability_key)


def get_approved_capability_manifest(
    capability_key: str,
) -> ApprovedCapabilityManifest | None:
    """Backward-compatible name for the code-owned approved manifest lookup."""
    return get_capability_manifest(capability_key)


def is_capability_registered(capability_key: str) -> bool:
    """Return whether a capability is in the code-owned runner allowlist."""
    return capability_key in APPROVED_CAPABILITY_MANIFESTS


def assert_capability_can_use_runner(
    capability_key: str,
    runner_type: str,
) -> ApprovedCapabilityManifest:
    """Return a manifest only when the capability is registered for this runner.

    This fail-closed helper is intentionally small and data-free: it exposes no
    pending IDs, grants, action hashes, approval challenges, rows, or secrets.
    """
    manifest = get_capability_manifest(capability_key)
    if manifest is None:
        raise ValueError("capability_not_registered")
    if manifest.runner_type != runner_type:
        raise ValueError("capability_runner_mismatch")
    if not manifest.enabled or not manifest.current_runner_connected:
        raise ValueError("capability_not_connected")
    return manifest


def list_design_only_capabilities() -> tuple[str, ...]:
    """Return registered capability keys that are documented but not executable."""
    return tuple(
        sorted(
            capability_key
            for capability_key, manifest in APPROVED_CAPABILITY_MANIFESTS.items()
            if manifest.implementation_status == "design_only"
            or not manifest.enabled
            or not manifest.current_runner_connected
        )
    )


def list_safe_test_capabilities() -> tuple[str, ...]:
    """Return only registered test capability keys safe for internal checks."""
    return tuple(
        sorted(
            capability_key
            for capability_key, manifest in APPROVED_CAPABILITY_MANIFESTS.items()
            if is_safe_noop_runner_manifest(manifest)
        )
    )


def is_safe_noop_runner_manifest(manifest: ApprovedCapabilityManifest) -> bool:
    """Fail closed unless the manifest permits only the current no-op shape."""
    return (
        manifest.risk_level == "test_only"
        and manifest.approval_required
        and not manifest.external_action_allowed
        and not manifest.notification_allowed
        and manifest.runner_type == "no_op_approved_runner"
        and manifest.implementation_status == "connected"
        and manifest.enabled
        and manifest.current_runner_connected
        and "no_op_verified" in manifest.verification_requirements
    )
