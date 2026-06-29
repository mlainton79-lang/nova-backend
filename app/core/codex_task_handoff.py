"""Safe in-memory Tony Codex task handoff surface.

This module stores only sanitized Codex task metadata for a local runner to
fetch and report back. It does not execute Codex, call external APIs, mutate
GitHub or Railway, create approvals, send notifications, or touch databases.
"""
from __future__ import annotations

from dataclasses import replace
from threading import RLock
from time import time
from typing import Any

from app.core.codex_tasks import (
    CodexTaskPlan,
    CodexTaskResult,
    CodexTaskStatus,
    create_codex_task_plan,
)


_HANDOFF_LOCK = RLock()
_TASKS: dict[str, dict[str, Any]] = {}
_TASK_ORDER: list[str] = []

_BLOCKED_HANDOFF_TERMS = (
    "secret",
    "credential",
    "railway variable",
    "environment variable",
    "production database",
    "production db",
    "approval bypass",
    "bypass approval",
    "disable safety",
    "safety gate",
    "gmail oauth",
    "gmail session",
    "vinted session",
    "oauth session",
    "browser session",
    "browser automation",
    "real account",
    "payment",
    "bank transfer",
    "buyer message",
    "post listing",
    "buy postage",
)

_PRIVATE_REPORT_PATTERNS = (
    "database_url",
    "authorization",
    "dev_token",
    "refresh_token",
    "access_token",
    "github_token",
    "railway_token",
    "cookie=",
    "session=",
    "approval_challenge",
    "action_hash",
    "pending_id",
    "grant_id",
    "oauth",
    "raw gmail payload",
    "vinted account",
    "browser session",
)


def _clean_text(value: Any, field_name: str, max_chars: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}_required")
    text = " ".join(value.strip().split())
    lowered = text.lower()
    if any(term in lowered for term in _PRIVATE_REPORT_PATTERNS):
        raise ValueError(f"{field_name}_contains_private_material")
    return text[:max_chars]


def _clean_tuple(
    value: Any,
    field_name: str,
    max_items: int = 20,
    max_chars: int = 220,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name}_must_be_list")
    cleaned = tuple(_clean_text(item, field_name, max_chars=max_chars) for item in value)
    return cleaned[:max_items]


def _assert_safe_scope_text(*parts: Any) -> None:
    text = " ".join(
        str(part)
        for part in parts
        if part is not None
    ).lower()
    if any(term in text for term in _BLOCKED_HANDOFF_TERMS):
        raise ValueError("codex_handoff_scope_blocked")


def plan_to_safe_dict(plan: CodexTaskPlan) -> dict[str, Any]:
    """Return the safe JSON shape a local runner may fetch."""
    return {
        "task_id": plan.task_id,
        "requested_by": plan.requested_by,
        "status": plan.status.value,
        "user_goal": plan.user_goal,
        "tool_or_area": plan.tool_or_area,
        "intended_change_summary": plan.intended_change_summary,
        "autonomy_scope": plan.autonomy_scope,
        "allowed_files_or_areas": tuple(plan.allowed_files_or_areas),
        "blocked_files_or_areas": tuple(plan.blocked_files_or_areas),
        "validation_requirements": tuple(plan.validation_requirements),
        "reporting_requirements": tuple(plan.reporting_requirements),
        "can_edit_code": plan.can_edit_code,
        "can_run_tests": plan.can_run_tests,
        "can_commit": plan.can_commit,
        "can_push_branch": plan.can_push_branch,
        "can_deploy": plan.can_deploy,
        "requires_matthew_approval_before_deploy": (
            plan.requires_matthew_approval_before_deploy
        ),
    }


def _record_for_plan(plan: CodexTaskPlan, status: str) -> dict[str, Any]:
    now = int(time())
    return {
        "plan": plan,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "report": None,
    }


def create_pending_codex_task(
    user_goal: str,
    tool_or_area: str = "nova-backend",
    allowed_files_or_areas: tuple[str, ...] | None = None,
    blocked_files_or_areas: tuple[str, ...] | None = None,
    can_edit_code: bool = True,
    can_run_tests: bool = True,
    can_commit: bool = False,
    can_push_branch: bool = False,
    can_deploy: bool = False,
    requires_matthew_approval_before_deploy: bool = True,
) -> dict[str, Any]:
    """Create one pending safe Codex handoff task."""
    if can_deploy:
        raise ValueError("codex_handoff_deploy_blocked")
    if can_push_branch:
        raise ValueError("codex_handoff_push_branch_blocked")
    _assert_safe_scope_text(
        user_goal,
        tool_or_area,
        " ".join(allowed_files_or_areas or ()),
        " ".join(blocked_files_or_areas or ()),
    )

    plan = create_codex_task_plan(
        user_goal=user_goal,
        requested_by="tony",
        tool_or_area=tool_or_area,
        autonomy_scope="direct_local_codex_handoff",
        allowed_files_or_areas=allowed_files_or_areas,
        blocked_files_or_areas=blocked_files_or_areas,
        can_edit_code=can_edit_code,
        can_run_tests=can_run_tests,
        can_commit=can_commit,
        can_push_branch=can_push_branch,
        can_deploy=can_deploy,
        requires_matthew_approval_before_deploy=requires_matthew_approval_before_deploy,
    )

    with _HANDOFF_LOCK:
        if plan.task_id not in _TASKS:
            _TASK_ORDER.append(plan.task_id)
        _TASKS[plan.task_id] = _record_for_plan(plan, "pending")

    return safe_task_metadata(plan, "pending")


def safe_task_metadata(plan: CodexTaskPlan, handoff_status: str) -> dict[str, Any]:
    """Return safe metadata for API responses."""
    safe = plan_to_safe_dict(plan)
    safe["handoff_status"] = handoff_status
    return safe


def get_next_pending_codex_task() -> dict[str, Any] | None:
    """Return and mark the next pending task as fetched."""
    with _HANDOFF_LOCK:
        for task_id in _TASK_ORDER:
            record = _TASKS.get(task_id)
            if not record or record["status"] != "pending":
                continue
            record["status"] = "fetched"
            record["updated_at"] = int(time())
            plan = replace(record["plan"], status=CodexTaskStatus.READY_FOR_CODEX)
            record["plan"] = plan
            return safe_task_metadata(plan, "fetched")
    return None


def ingest_codex_task_report(task_id: str, report: dict[str, Any]) -> dict[str, Any]:
    """Accept sanitized local-runner report metadata for a fetched task."""
    safe_task_id = _clean_text(task_id, "task_id", max_chars=120)
    changed_files = _clean_tuple(report.get("changed_files_summary"), "changed_files_summary")
    tests = _clean_tuple(report.get("tests_summary"), "tests_summary")
    deployment = _clean_text(
        str(report.get("deployment_summary", "not_attempted")),
        "deployment_summary",
        max_chars=120,
    )
    final_report = _clean_text(
        str(report.get("final_report", "Local Codex handoff report received.")),
        "final_report",
        max_chars=500,
    )
    status_value = str(report.get("status", CodexTaskStatus.READY_TO_REPORT.value))
    status = CodexTaskStatus(status_value)

    result = CodexTaskResult(
        task_id=safe_task_id,
        status=status,
        changed_files_summary=changed_files,
        tests_summary=tests,
        deployment_summary=deployment,
        final_report=final_report,
        codex_execution_invoked=bool(report.get("codex_execution_invoked", False)),
        external_apis_called=bool(report.get("external_apis_called", False)),
        github_mutation_performed=bool(report.get("github_mutation_performed", False)),
        railway_mutation_performed=bool(report.get("railway_mutation_performed", False)),
        secrets_exposed=bool(report.get("secrets_exposed", False)),
    )
    if (
        result.external_apis_called
        or result.github_mutation_performed
        or result.railway_mutation_performed
        or result.secrets_exposed
    ):
        raise ValueError("unsafe_codex_report_metadata")

    safe_report = {
        "task_id": result.task_id,
        "status": result.status.value,
        "changed_files_summary": result.changed_files_summary,
        "tests_summary": result.tests_summary,
        "deployment_summary": result.deployment_summary,
        "final_report": result.final_report,
        "codex_execution_invoked": result.codex_execution_invoked,
        "external_apis_called": False,
        "github_mutation_performed": False,
        "railway_mutation_performed": False,
        "secrets_exposed": False,
    }

    with _HANDOFF_LOCK:
        record = _TASKS.get(safe_task_id)
        if not record:
            raise ValueError("codex_task_not_found")
        record["status"] = "reported"
        record["updated_at"] = int(time())
        record["report"] = safe_report

    return safe_report


def build_codex_handoff_display_report(task_id: str) -> dict[str, Any]:
    """Summarise one handoff record for Matthew using safe metadata only."""
    safe_task_id = _clean_text(task_id, "task_id", max_chars=120)

    with _HANDOFF_LOCK:
        record = _TASKS.get(safe_task_id)
        if not record:
            raise ValueError("codex_task_not_found")
        plan = record["plan"]
        handoff_status = record["status"]
        report = record.get("report") or {}

    report_status = str(report.get("status", ""))
    current_state = report_status or plan.status.value
    changed_files = _clean_tuple(
        report.get("changed_files_summary"),
        "changed_files_summary",
    )
    validation_notes = _clean_tuple(report.get("tests_summary"), "tests_summary")
    final_summary = str(
        report.get("final_report")
        or plan.intended_change_summary
        or "No final Codex handoff summary has been reported yet."
    )
    matthew_review_needed = (
        handoff_status != "reported"
        or current_state != CodexTaskStatus.READY_TO_REPORT.value
        or not plan.can_commit
        or not plan.can_push_branch
        or not plan.can_deploy
        or plan.requires_matthew_approval_before_deploy
    )

    return {
        "task_id": plan.task_id,
        "requester": plan.requested_by,
        "area": plan.tool_or_area,
        "current_state": current_state,
        "handoff_status": handoff_status,
        "changed_files": changed_files,
        "validation_notes": validation_notes,
        "final_summary": _clean_text(final_summary, "final_summary", max_chars=500),
        "matthew_review_needed_before_later_action": matthew_review_needed,
    }


def list_recent_codex_handoff_display_reports(
    limit: int = 10,
) -> tuple[dict[str, Any], ...]:
    """Return recent safe handoff display reports, newest updated first."""
    if not isinstance(limit, int):
        raise ValueError("limit_must_be_int")
    safe_limit = max(1, min(limit, 25))

    with _HANDOFF_LOCK:
        recent_task_ids = tuple(
            task_id
            for task_id, _record in sorted(
                _TASKS.items(),
                key=lambda item: (item[1].get("updated_at", 0), item[0]),
                reverse=True,
            )
        )[:safe_limit]

    return tuple(
        build_codex_handoff_display_report(task_id)
        for task_id in recent_task_ids
    )


def reset_codex_handoff_store_for_tests() -> None:
    """Clear in-memory handoff state for tests only."""
    with _HANDOFF_LOCK:
        _TASKS.clear()
        _TASK_ORDER.clear()
