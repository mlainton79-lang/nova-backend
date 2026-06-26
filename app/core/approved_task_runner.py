"""Approved Task Runner Adapter and Capability Runner Interface v1.

This is the deliberately small execution boundary after Approval Resume
Contract v1. It is not a task engine: it contains no queueing, dispatch,
notifications, external integrations, or browser automation.

Lifecycle for the current harmless harness:
request approval -> mark-only approval + grant mint/reuse -> explicit safe
resume endpoint -> consume once -> no-op runner result.

Each public wrapper below fixes one harmless capability and its consume-once
function. There is deliberately no request-selectable registry or dispatcher.
Future approved runners can adopt this interface only after they have their
own explicit capability boundary, risk controls, and verification contract.
"""
from collections.abc import Callable
from dataclasses import dataclass

from app.core.approval_lock import (
    TEST_APPROVED_NOOP_CAPABILITY_KEY,
    TEST_APPROVAL_RESUME_CAPABILITY_KEY,
    consume_test_approved_noop_grant,
    consume_test_approval_resume_grant,
)


HARMLESS_RESUME_TASK_TYPE = "harmless_approval_resume_test"
HARMLESS_RESUME_COMPLETED_MESSAGE = "Harmless resume test task completed."
HARMLESS_RESUME_NOT_RESUMED_MESSAGE = (
    "No approved unconsumed resume test grant was available."
)
HARMLESS_NOOP_TASK_TYPE = "harmless_approved_noop_test"
HARMLESS_NOOP_COMPLETED_MESSAGE = "Harmless approved no-op task completed."
HARMLESS_NOOP_NOT_RESUMED_MESSAGE = (
    "No approved unconsumed no-op test grant was available."
)


@dataclass(frozen=True)
class ApprovedTaskRunnerResult:
    """Safe internal outcome from an explicitly invoked approved runner."""

    capability_key: str
    task_type: str
    resumed: bool
    safe_status: str
    safe_message: str
    verification_status: str
    external_action_performed: bool = False
    notification_sent: bool = False


@dataclass(frozen=True)
class _NoOpApprovedCapabilityRunner:
    """Internal interface for one explicitly-bound no-op capability.

    ``consume_once`` is supplied only by a capability-specific internal
    wrapper. This class neither accepts request data nor performs work after
    consumption, so it cannot dispatch a real-world action.
    """
    capability_key: str
    task_type: str
    completed_message: str
    not_resumed_message: str
    consume_once: Callable[[], bool]

    def run(self) -> ApprovedTaskRunnerResult:
        """Consume one eligible grant and return a verified no-op outcome."""
        resumed = self.consume_once()
        if resumed:
            return ApprovedTaskRunnerResult(
                capability_key=self.capability_key,
                task_type=self.task_type,
                resumed=True,
                safe_status="completed",
                safe_message=self.completed_message,
                verification_status="no_op_verified",
            )

        return ApprovedTaskRunnerResult(
            capability_key=self.capability_key,
            task_type=self.task_type,
            resumed=False,
            safe_status="not_resumed",
            safe_message=self.not_resumed_message,
            verification_status="not_run",
        )


def run_harmless_test_approval_resume() -> ApprovedTaskRunnerResult:
    """Run only the original harmless approval-resume capability."""
    return _NoOpApprovedCapabilityRunner(
        capability_key=TEST_APPROVAL_RESUME_CAPABILITY_KEY,
        task_type=HARMLESS_RESUME_TASK_TYPE,
        completed_message=HARMLESS_RESUME_COMPLETED_MESSAGE,
        not_resumed_message=HARMLESS_RESUME_NOT_RESUMED_MESSAGE,
        consume_once=consume_test_approval_resume_grant,
    ).run()


def run_harmless_test_approved_noop() -> ApprovedTaskRunnerResult:
    """Run only the second harmless approved no-op capability."""
    return _NoOpApprovedCapabilityRunner(
        capability_key=TEST_APPROVED_NOOP_CAPABILITY_KEY,
        task_type=HARMLESS_NOOP_TASK_TYPE,
        completed_message=HARMLESS_NOOP_COMPLETED_MESSAGE,
        not_resumed_message=HARMLESS_NOOP_NOT_RESUMED_MESSAGE,
        consume_once=consume_test_approved_noop_grant,
    ).run()
