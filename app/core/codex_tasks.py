"""Tony-managed Codex task workflow foundation v1.

This module models self-build work as a safe internal mission envelope. It is
deliberately non-executing: no Codex process, no OpenAI API, no GitHub or
Railway mutation, no database, no approvals, no notifications, and no external
integrations are imported or called here.
"""
from dataclasses import dataclass, replace
from enum import Enum
from hashlib import sha256
from typing import Iterable


class CodexTaskStatus(str, Enum):
    REQUESTED = "requested"
    PLANNED = "planned"
    READY_FOR_CODEX = "ready_for_codex"
    RUNNING_CODEX = "running_codex"
    CODEX_COMPLETED = "codex_completed"
    TESTS_RUNNING = "tests_running"
    TESTS_PASSED = "tests_passed"
    TESTS_FAILED = "tests_failed"
    READY_TO_REPORT = "ready_to_report"
    REPORTED_TO_MATTHEW = "reported_to_matthew"
    FAILED_SAFE = "failed_safe"


DEFAULT_ALLOWED_FILES_OR_AREAS = (
    "app/core",
    "app/api/v1/endpoints only when explicitly requested",
    "app/selling only when task scope is selling preparation",
    "tests colocated with changed modules",
    "docs or comments only when needed to clarify safety contracts",
)

DEFAULT_BLOCKED_FILES_OR_AREAS = (
    "secret-bearing files or shell startup files",
    "Railway variable configuration",
    "production database rows",
    "approval bypass or mark-only approval semantics",
    "payment, banking transfer, or order-handling logic",
    "Gmail OAuth sessions, payloads, send/delete runners, or refresh material",
    "Vinted account sessions, browser state, buyer messaging, posting, orders, or payments",
    "browser automation against real accounts",
    "Android code unless the mission explicitly allows Android work",
    "deployment automation unless Matthew approved deploy scope",
)

DEFAULT_VALIDATION_REQUIREMENTS = (
    "git diff --check",
    "python -m py_compile on changed Python files",
    "python -m compileall -q app",
    "targeted unittest checks for changed safety boundaries",
    "pytest only if available",
)

SECRET_PRINTING_BANS = (
    "Do not print DEV_TOKEN, Authorization headers, Railway variable values, DATABASE_URL, credentials, cookies, sessions, OAuth material, private payloads, Gmail payloads, Vinted account data, browser session data, approval challenges, action hashes, pending approval identifiers, grant identifiers, OpenAI credentials, GitHub credentials, Railway credentials, or raw notification payloads.",
)

_SENSITIVE_TERMS = (
    "dev_token",
    "authorization:",
    "database_url",
    "oauth token",
    "refresh token",
    "access token",
    "github token",
    "railway token",
    "cookie=",
    "session=",
    "approval_challenge",
    "action_hash",
    "pending_id",
    "grant_id",
    "raw gmail payload",
    "vinted account data",
    "browser session data",
)

_DANGEROUS_SCOPE_TERMS = (
    "approval bypass",
    "bypass approval",
    "disable safety",
    "disable urgent gate",
    "print secret",
    "railway variable",
    "production database row",
    "payment transfer",
    "bank transfer",
    "vinted session",
    "gmail oauth",
    "browser automation against real accounts",
)


@dataclass(frozen=True)
class CodexTaskRequest:
    """Safe request Tony can form before a self-build task is executed."""

    requested_by: str
    user_goal: str
    tool_or_area: str
    autonomy_scope: str = "self_build_planning_only"


@dataclass(frozen=True)
class CodexTaskPlan:
    """Non-executing Codex mission plan with explicit safe boundaries."""

    task_id: str
    requested_by: str
    user_goal: str
    tool_or_area: str
    intended_change_summary: str
    autonomy_scope: str
    allowed_files_or_areas: tuple[str, ...]
    blocked_files_or_areas: tuple[str, ...]
    validation_requirements: tuple[str, ...]
    reporting_requirements: tuple[str, ...]
    can_edit_code: bool
    can_run_tests: bool
    can_commit: bool
    can_push_branch: bool
    can_deploy: bool
    requires_matthew_approval_before_deploy: bool
    status: CodexTaskStatus


@dataclass(frozen=True)
class CodexTaskResult:
    """Safe result metadata from a future Codex execution boundary."""

    task_id: str
    status: CodexTaskStatus
    changed_files_summary: tuple[str, ...] = ()
    tests_summary: tuple[str, ...] = ()
    deployment_summary: str = "not_attempted"
    final_report: str = ""
    codex_execution_invoked: bool = False
    external_apis_called: bool = False
    github_mutation_performed: bool = False
    railway_mutation_performed: bool = False
    secrets_exposed: bool = False


@dataclass(frozen=True)
class CodexTaskReport:
    """Matthew-facing completion report assembled from safe metadata only."""

    task_id: str
    status: CodexTaskStatus
    completed: bool
    summary: str
    changed_files_summary: tuple[str, ...]
    tests_summary: tuple[str, ...]
    deployment_summary: str
    final_report: str
    needs_attention: tuple[str, ...]


def _as_clean_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}_required")
    text = " ".join(value.strip().split())
    lowered = text.lower()
    if any(term in lowered for term in _SENSITIVE_TERMS):
        raise ValueError(f"{field_name}_contains_sensitive_reference")
    return text


def _as_tuple(values: Iterable[str] | None, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if values is None:
        return fallback
    cleaned = tuple(_as_clean_text(str(item), "scope_item") for item in values)
    return cleaned if cleaned else fallback


def _task_id_from(goal: str, tool_or_area: str) -> str:
    digest = sha256(f"{tool_or_area}\n{goal}".encode("utf-8")).hexdigest()[:16]
    return f"codex-{digest}"


def _summarise_goal(goal: str, tool_or_area: str) -> str:
    clipped = goal[:220].rstrip()
    return f"Prepare a safe Codex implementation plan for {tool_or_area}: {clipped}"


def create_codex_task_plan(
    user_goal: str,
    requested_by: str = "tony",
    tool_or_area: str = "nova-backend",
    autonomy_scope: str = "self_build_planning_only",
    allowed_files_or_areas: Iterable[str] | None = None,
    blocked_files_or_areas: Iterable[str] | None = None,
    can_edit_code: bool = True,
    can_run_tests: bool = True,
    can_commit: bool = False,
    can_push_branch: bool = False,
    can_deploy: bool = False,
    requires_matthew_approval_before_deploy: bool = True,
) -> CodexTaskPlan:
    """Create a non-executing self-build task plan for future Codex work."""
    goal = _as_clean_text(user_goal, "user_goal")
    requester = _as_clean_text(requested_by, "requested_by")
    area = _as_clean_text(tool_or_area, "tool_or_area")
    scope = _as_clean_text(autonomy_scope, "autonomy_scope")

    lowered_scope = " ".join(
        (
            goal,
            area,
            scope,
            " ".join(allowed_files_or_areas or ()),
            " ".join(blocked_files_or_areas or ()),
        )
    ).lower()
    if any(term in lowered_scope for term in _DANGEROUS_SCOPE_TERMS):
        raise ValueError("codex_task_scope_requires_explicit_unlock")

    if can_deploy and not requires_matthew_approval_before_deploy:
        raise ValueError("deploy_without_matthew_approval_blocked")

    return CodexTaskPlan(
        task_id=_task_id_from(goal, area),
        requested_by=requester,
        user_goal=goal,
        tool_or_area=area,
        intended_change_summary=_summarise_goal(goal, area),
        autonomy_scope=scope,
        allowed_files_or_areas=_as_tuple(
            allowed_files_or_areas,
            DEFAULT_ALLOWED_FILES_OR_AREAS,
        ),
        blocked_files_or_areas=_as_tuple(
            blocked_files_or_areas,
            DEFAULT_BLOCKED_FILES_OR_AREAS,
        ),
        validation_requirements=DEFAULT_VALIDATION_REQUIREMENTS,
        reporting_requirements=(
            "Report changed files only by safe path summary.",
            "Report validation commands and pass/fail state.",
            "Report deployment status only as safe metadata.",
            "Report unresolved risks or follow-up work plainly.",
        ),
        can_edit_code=bool(can_edit_code),
        can_run_tests=bool(can_run_tests),
        can_commit=bool(can_commit),
        can_push_branch=bool(can_push_branch),
        can_deploy=bool(can_deploy),
        requires_matthew_approval_before_deploy=bool(
            requires_matthew_approval_before_deploy
        ),
        status=CodexTaskStatus.PLANNED,
    )


def mark_codex_task_ready(plan: CodexTaskPlan) -> CodexTaskPlan:
    """Mark a validated plan ready for a future Codex runner."""
    if not isinstance(plan, CodexTaskPlan):
        raise ValueError("codex_task_plan_required")
    if plan.can_deploy and not plan.requires_matthew_approval_before_deploy:
        raise ValueError("deploy_without_matthew_approval_blocked")
    return replace(plan, status=CodexTaskStatus.READY_FOR_CODEX)


def build_codex_prompt_from_task(plan: CodexTaskPlan) -> str:
    """Build sanitized implementation instructions for a future Codex run."""
    if not isinstance(plan, CodexTaskPlan):
        raise ValueError("codex_task_plan_required")

    lines = [
        "Tony-managed Codex task",
        "",
        f"Task ID: {plan.task_id}",
        f"Goal: {plan.user_goal}",
        f"Tool or area: {plan.tool_or_area}",
        f"Intended change: {plan.intended_change_summary}",
        f"Autonomy scope: {plan.autonomy_scope}",
        "",
        "Allowed scope:",
        *[f"- {item}" for item in plan.allowed_files_or_areas],
        "",
        "Blocked scope:",
        *[f"- {item}" for item in plan.blocked_files_or_areas],
        "",
        "Permissions for this mission:",
        f"- can_edit_code: {plan.can_edit_code}",
        f"- can_run_tests: {plan.can_run_tests}",
        f"- can_commit: {plan.can_commit}",
        f"- can_push_branch: {plan.can_push_branch}",
        f"- can_deploy: {plan.can_deploy}",
        "- requires_matthew_approval_before_deploy: "
        f"{plan.requires_matthew_approval_before_deploy}",
        "",
        "Validation requirements:",
        *[f"- {item}" for item in plan.validation_requirements],
        "",
        "Reporting requirements:",
        *[f"- {item}" for item in plan.reporting_requirements],
        "",
        "Secret-printing bans:",
        *[f"- {item}" for item in SECRET_PRINTING_BANS],
        "",
        "Do not run external services or deploy unless the mission explicitly permits it.",
    ]
    prompt = "\n".join(lines)
    lowered = prompt.lower()
    if any(term in lowered for term in ("database_url=", "authorization: bearer ")):
        raise ValueError("codex_prompt_contains_private_material")
    return prompt


def summarise_codex_task_result(result: CodexTaskResult) -> dict:
    """Return sanitized result metadata for Tony to reason over."""
    if not isinstance(result, CodexTaskResult):
        raise ValueError("codex_task_result_required")
    if (
        result.codex_execution_invoked
        or result.external_apis_called
        or result.github_mutation_performed
        or result.railway_mutation_performed
        or result.secrets_exposed
    ):
        status = CodexTaskStatus.FAILED_SAFE
    else:
        status = result.status
    return {
        "task_id": _as_clean_text(result.task_id, "task_id"),
        "status": status.value,
        "changed_files_summary": tuple(
            _as_clean_text(item, "changed_file_summary")
            for item in result.changed_files_summary
        ),
        "tests_summary": tuple(
            _as_clean_text(item, "tests_summary") for item in result.tests_summary
        ),
        "deployment_summary": _as_clean_text(
            result.deployment_summary,
            "deployment_summary",
        ),
        "codex_execution_invoked": False,
        "external_apis_called": False,
        "github_mutation_performed": False,
        "railway_mutation_performed": False,
        "secrets_exposed": False,
    }


def build_matthew_completion_report(
    plan: CodexTaskPlan,
    result: CodexTaskResult,
) -> CodexTaskReport:
    """Build a safe Matthew-facing completion report from task metadata."""
    if not isinstance(plan, CodexTaskPlan):
        raise ValueError("codex_task_plan_required")
    summary = summarise_codex_task_result(result)
    status = CodexTaskStatus(summary["status"])
    tests = summary["tests_summary"]
    completed = status in {
        CodexTaskStatus.TESTS_PASSED,
        CodexTaskStatus.READY_TO_REPORT,
        CodexTaskStatus.REPORTED_TO_MATTHEW,
    }
    needs_attention = ()
    if status == CodexTaskStatus.TESTS_FAILED:
        needs_attention = ("Tests failed; Matthew should not treat the task as complete.",)
    elif status == CodexTaskStatus.FAILED_SAFE:
        needs_attention = ("Task failed closed because unsafe result metadata was detected.",)
    elif not completed:
        needs_attention = ("Task has not reached a completed reporting state yet.",)

    final_report = result.final_report.strip() if result.final_report.strip() else (
        f"Tony prepared the Codex task for {plan.tool_or_area}. "
        f"Status: {status.value}."
    )
    _as_clean_text(final_report, "final_report")

    return CodexTaskReport(
        task_id=summary["task_id"],
        status=status,
        completed=completed,
        summary=plan.intended_change_summary,
        changed_files_summary=summary["changed_files_summary"],
        tests_summary=tests,
        deployment_summary=summary["deployment_summary"],
        final_report=final_report,
        needs_attention=needs_attention,
    )
