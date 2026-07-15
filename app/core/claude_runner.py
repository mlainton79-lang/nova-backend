"""Disabled Tony Claude Code runner boundary v1.

The runner boundary accepts a CodexTaskPlan (the seat-neutral self-build
mission envelope) and returns safe metadata for a future headless Claude
Code run (claude -p). It does not execute Claude Code, start processes,
run shell commands, call APIs, mutate git, change Railway, create
approvals, send notifications, or touch databases.

It mirrors app/core/codex_runner.py exactly so the two seats stay
structurally identical and share one blocked-terms source of truth.
"""
from dataclasses import dataclass
from enum import Enum

from app.core.codex_runner import BLOCKED_PLAN_TERMS
from app.core.codex_tasks import (
    CodexTaskPlan,
    CodexTaskResult,
    CodexTaskStatus,
    build_codex_prompt_from_task,
)


class ClaudeRunnerMode(str, Enum):
    DISABLED = "disabled"
    PROMPT_ONLY = "prompt_only"
    DRY_RUN = "dry_run"
    FUTURE_LOCAL_CLAUDE_CLI = "future_local_claude_cli"
    FUTURE_ISOLATED_WORKER = "future_isolated_worker"


DEFAULT_RUNNER_MODE = ClaudeRunnerMode.DISABLED

_HEADLESS_CONSTRAINT_LINES = (
    "",
    "Headless Claude Code execution constraints (future runs only):",
    "- Invoke only as: claude -p with an explicit --allowedTools list.",
    '- Use --permission-mode dontAsk or acceptEdits; never skip permissions.',
    "- Always cap runs with --max-turns and --max-budget-usd.",
    "- Authenticate future automation with an API key, not an interactive login.",
)


@dataclass(frozen=True)
class ClaudeRunnerRequest:
    """Safe request to the disabled runner boundary."""

    plan: CodexTaskPlan
    mode: ClaudeRunnerMode | str = DEFAULT_RUNNER_MODE


@dataclass(frozen=True)
class ClaudeRunnerDecision:
    """Execution decision for one Claude Code task plan."""

    task_id: str
    mode: str
    execution_allowed: bool
    refusal_reason: str | None
    claude_execution_invoked: bool
    safe_prompt_prepared: bool
    safe_prompt_length: int
    safe_prompt_summary: str
    can_edit_code: bool
    can_run_tests: bool
    can_commit: bool
    can_push_branch: bool
    can_deploy: bool
    requires_matthew_approval_before_deploy: bool
    safe_next_step: str


@dataclass(frozen=True)
class ClaudeRunnerBoundaryResult:
    """Pair the runner decision with CodexTaskResult-compatible metadata."""

    decision: ClaudeRunnerDecision
    task_result: CodexTaskResult


def _coerce_mode(mode: ClaudeRunnerMode | str) -> ClaudeRunnerMode | None:
    if isinstance(mode, ClaudeRunnerMode):
        return mode
    try:
        return ClaudeRunnerMode(str(mode))
    except ValueError:
        return None


def _plan_text(plan: CodexTaskPlan) -> str:
    fields = (
        plan.task_id,
        plan.requested_by,
        plan.user_goal,
        plan.tool_or_area,
        plan.intended_change_summary,
        plan.autonomy_scope,
        " ".join(plan.allowed_files_or_areas),
        " ".join(plan.validation_requirements),
        " ".join(plan.reporting_requirements),
    )
    return " ".join(fields).lower()


def _validate_plan_for_runner(plan: CodexTaskPlan) -> None:
    if not isinstance(plan, CodexTaskPlan):
        raise ValueError("codex_task_plan_required")
    if plan.can_deploy and not plan.requires_matthew_approval_before_deploy:
        raise ValueError("deploy_without_matthew_approval_blocked")
    text = _plan_text(plan)
    if any(term in text for term in BLOCKED_PLAN_TERMS):
        raise ValueError("claude_runner_plan_scope_blocked")


def build_claude_prompt_from_task(plan: CodexTaskPlan) -> str:
    """Build sanitized instructions for a future headless claude -p run."""
    base_prompt = build_codex_prompt_from_task(plan)
    first_line, _, rest = base_prompt.partition("\n")
    if first_line != "Tony-managed Codex task":
        raise ValueError("unexpected_base_prompt_header")
    prompt = "\n".join(
        (
            "Tony-managed Claude Code task (headless claude -p)",
            rest,
            *_HEADLESS_CONSTRAINT_LINES,
        )
    )
    lowered = prompt.lower()
    if any(term in lowered for term in ("database_url=", "authorization: bearer ")):
        raise ValueError("claude_prompt_contains_private_material")
    return prompt


def _safe_prompt_summary(prompt: str) -> str:
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    first_goal = next((line for line in lines if line.startswith("Goal: ")), "")
    return first_goal[:160] if first_goal else "safe_claude_prompt_prepared"


def can_claude_runner_execute_task(
    plan: CodexTaskPlan,
    mode: ClaudeRunnerMode | str = DEFAULT_RUNNER_MODE,
) -> ClaudeRunnerDecision:
    """Return a fail-closed execution decision without running Claude Code."""
    coerced_mode = _coerce_mode(mode)
    prompt = ""
    safe_prompt_prepared = False
    safe_prompt_summary = ""

    try:
        if coerced_mode is None:
            raise ValueError("unknown_runner_mode")
        _validate_plan_for_runner(plan)
        prompt = build_claude_prompt_from_task(plan)
        safe_prompt_prepared = True
        safe_prompt_summary = _safe_prompt_summary(prompt)
        if coerced_mode == ClaudeRunnerMode.DISABLED:
            refusal_reason = "runner_disabled"
            safe_next_step = "Keep task ready until a future mission explicitly enables execution."
        elif coerced_mode == ClaudeRunnerMode.PROMPT_ONLY:
            refusal_reason = "prompt_only_does_not_execute"
            safe_next_step = "Use the prepared prompt manually; do not execute from backend."
        elif coerced_mode == ClaudeRunnerMode.DRY_RUN:
            refusal_reason = "dry_run_does_not_execute"
            safe_next_step = "Review simulated readiness metadata only."
        elif coerced_mode in (
            ClaudeRunnerMode.FUTURE_LOCAL_CLAUDE_CLI,
            ClaudeRunnerMode.FUTURE_ISOLATED_WORKER,
        ):
            refusal_reason = "future_runner_mode_not_implemented"
            safe_next_step = "Add a separate reviewed runner implementation before execution."
        else:
            refusal_reason = "unknown_runner_mode"
            safe_next_step = "Use a known disabled runner mode."
    except ValueError as error:
        refusal_reason = str(error)
        safe_next_step = "Fail closed and revise the Claude Code task plan."

    mode_value = coerced_mode.value if coerced_mode is not None else str(mode)
    return ClaudeRunnerDecision(
        task_id=plan.task_id if isinstance(plan, CodexTaskPlan) else "invalid_plan",
        mode=mode_value,
        execution_allowed=False,
        refusal_reason=refusal_reason,
        claude_execution_invoked=False,
        safe_prompt_prepared=safe_prompt_prepared,
        safe_prompt_length=len(prompt) if safe_prompt_prepared else 0,
        safe_prompt_summary=safe_prompt_summary,
        can_edit_code=bool(getattr(plan, "can_edit_code", False)),
        can_run_tests=bool(getattr(plan, "can_run_tests", False)),
        can_commit=bool(getattr(plan, "can_commit", False)),
        can_push_branch=bool(getattr(plan, "can_push_branch", False)),
        can_deploy=bool(getattr(plan, "can_deploy", False)),
        requires_matthew_approval_before_deploy=bool(
            getattr(plan, "requires_matthew_approval_before_deploy", True)
        ),
        safe_next_step=safe_next_step,
    )


def build_disabled_claude_runner_result(
    plan: CodexTaskPlan,
    mode: ClaudeRunnerMode | str = DEFAULT_RUNNER_MODE,
) -> CodexTaskResult:
    """Build CodexTaskResult-compatible metadata for a refused run."""
    decision = can_claude_runner_execute_task(plan, mode)
    return CodexTaskResult(
        task_id=decision.task_id,
        status=CodexTaskStatus.READY_TO_REPORT
        if decision.safe_prompt_prepared
        else CodexTaskStatus.FAILED_SAFE,
        changed_files_summary=(),
        tests_summary=("claude_runner_execution_not_invoked",),
        deployment_summary="not_attempted",
        final_report=(
            f"Claude runner mode {decision.mode} refused execution: "
            f"{decision.refusal_reason}."
        ),
        codex_execution_invoked=False,
        external_apis_called=False,
        github_mutation_performed=False,
        railway_mutation_performed=False,
        secrets_exposed=False,
    )


def run_claude_task(
    request: ClaudeRunnerRequest | CodexTaskPlan,
    mode: ClaudeRunnerMode | str = DEFAULT_RUNNER_MODE,
) -> ClaudeRunnerBoundaryResult:
    """Submit a plan to the disabled boundary and return safe metadata."""
    if isinstance(request, ClaudeRunnerRequest):
        plan = request.plan
        resolved_mode = request.mode
    else:
        plan = request
        resolved_mode = mode

    decision = can_claude_runner_execute_task(plan, resolved_mode)
    result = build_disabled_claude_runner_result(plan, resolved_mode)
    return ClaudeRunnerBoundaryResult(decision=decision, task_result=result)
