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
    preconditions: tuple[str, ...]
    verification_requirements: tuple[str, ...]
    allowed_outputs: tuple[str, ...]


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
    preconditions=(
        "approved_pending_approval",
        "active_unexpired_unconsumed_grant",
    ),
    verification_requirements=("no_op_verified",),
    allowed_outputs=("completed", "not_resumed", "no_op_verified"),
)


APPROVED_CAPABILITY_MANIFESTS = MappingProxyType(
    {
        TEST_APPROVAL_RESUME_MANIFEST.capability_key: TEST_APPROVAL_RESUME_MANIFEST,
        TEST_APPROVED_NOOP_MANIFEST.capability_key: TEST_APPROVED_NOOP_MANIFEST,
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
    return manifest


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
        and "no_op_verified" in manifest.verification_requirements
    )
