"""Approved Task Runner Adapter v1.

This is the deliberately small execution boundary after Approval Resume
Contract v1. It is not a task engine: it contains no queueing, dispatch,
notifications, external integrations, or browser automation.

Lifecycle for the current harmless harness:
request approval -> mark-only approval + grant mint/reuse -> explicit safe
resume endpoint -> consume once -> no-op runner result.

Future approved runners can adopt this result shape only after they have their
own explicit capability boundary, risk controls, and verification contract.
"""
from dataclasses import dataclass

from app.core.approval_lock import (
    TEST_APPROVAL_RESUME_CAPABILITY_KEY,
    consume_test_approval_resume_grant,
)


HARMLESS_RESUME_TASK_TYPE = "harmless_approval_resume_test"
HARMLESS_RESUME_COMPLETED_MESSAGE = "Harmless resume test task completed."
HARMLESS_RESUME_NOT_RESUMED_MESSAGE = (
    "No approved unconsumed resume test grant was available."
)


@dataclass(frozen=True)
class ApprovedTaskRunnerResult:
    """Safe internal outcome from an explicitly invoked approved runner."""

    task_type: str
    resumed: bool
    safe_status: str
    safe_message: str
    external_action_performed: bool = False
    notification_sent: bool = False


def run_harmless_test_approval_resume() -> ApprovedTaskRunnerResult:
    """Consume only the harmless test grant and return a no-op result.

    The capability is fixed by the approval contract wrapper rather than
    supplied by a request. This adapter intentionally performs no work after
    consumption; it establishes the result boundary future safe runners will
    implement without making real-world actions available today.
    """
    resumed = consume_test_approval_resume_grant()
    if resumed:
        return ApprovedTaskRunnerResult(
            task_type=HARMLESS_RESUME_TASK_TYPE,
            resumed=True,
            safe_status="completed",
            safe_message=HARMLESS_RESUME_COMPLETED_MESSAGE,
        )

    return ApprovedTaskRunnerResult(
        task_type=HARMLESS_RESUME_TASK_TYPE,
        resumed=False,
        safe_status="not_resumed",
        safe_message=HARMLESS_RESUME_NOT_RESUMED_MESSAGE,
    )
