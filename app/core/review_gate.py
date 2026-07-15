"""Two-seat cross-review gate v1.

Enforces the core self-build safety rule: the model that implements a change
is never the model that reviews it. Claude implements -> Codex reviews, or
Codex implements -> Claude reviews. Never the same seat in both roles.

This module is deliberately non-executing: no Claude process, no Codex
process, no OpenAI or Anthropic API, no GitHub or Railway mutation, no
database, no approvals, and no notifications are imported or called here.
It prepares review specs and evaluates verdict text, nothing more.
"""
from dataclasses import dataclass
from enum import Enum

from app.core.codex_tasks import (
    CodexTaskPlan,
    SECRET_PRINTING_BANS,
)


class BuildSeat(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"


class ReviewGateStatus(str, Enum):
    REVIEW_PENDING = "review_pending"
    REVIEW_PASSED = "review_passed"
    REVIEW_FAILED = "review_failed"


SHIP_TOKEN = "VERDICT: SHIP"
DO_NOT_SHIP_TOKEN = "VERDICT: DO-NOT-SHIP"

_VERDICT_PROTOCOL_LINES = (
    "Verdict protocol:",
    f"- End your review with exactly one line: '{SHIP_TOKEN}' or "
    f"'{DO_NOT_SHIP_TOKEN}'.",
    "- If anything is ambiguous, unsafe, or untested, choose "
    f"'{DO_NOT_SHIP_TOKEN}'.",
    "- Never include both tokens.",
)

_BRANCH_ALLOWED_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
)

_COMMAND_SPEC_BANNED_MARKERS = (
    "dangerously",
    "--yolo",
    "database_url=",
    "authorization: bearer ",
)


def _clean_branch(base_branch: str) -> str:
    if not isinstance(base_branch, str) or not base_branch.strip():
        raise ValueError("base_branch_required")
    branch = base_branch.strip()
    if any(ch not in _BRANCH_ALLOWED_CHARS for ch in branch):
        raise ValueError("base_branch_invalid_characters")
    return branch


def _coerce_seat(seat: BuildSeat | str) -> BuildSeat:
    if isinstance(seat, BuildSeat):
        return seat
    try:
        return BuildSeat(str(seat).strip().lower())
    except ValueError as error:
        raise ValueError("unknown_build_seat") from error


def reviewer_for(implementer: BuildSeat | str) -> BuildSeat:
    """Return the opposite seat. The reviewer is never the implementer."""
    seat = _coerce_seat(implementer)
    if seat == BuildSeat.CLAUDE:
        return BuildSeat.CODEX
    return BuildSeat.CLAUDE


def assert_two_seat_rule(
    implementer: BuildSeat | str,
    reviewer: BuildSeat | str,
) -> None:
    """Fail closed if the same model holds both seats."""
    impl = _coerce_seat(implementer)
    rev = _coerce_seat(reviewer)
    if impl == rev:
        raise ValueError("same_seat_review_blocked")


@dataclass(frozen=True)
class CrossReviewSpec:
    """Non-executing description of one cross-model review."""

    task_id: str
    implementer_seat: str
    reviewer_seat: str
    base_branch: str
    review_prompt: str
    reviewer_command_template: str
    execution_allowed: bool
    review_invoked: bool


@dataclass(frozen=True)
class ReviewOutcome:
    """Fail-closed evaluation of one reviewer verdict."""

    task_id: str
    implementer_seat: str
    reviewer_seat: str
    status: ReviewGateStatus
    can_advance_to_tests: bool
    refusal_reason: str | None


def _build_review_prompt(
    plan: CodexTaskPlan,
    reviewer: BuildSeat,
    base_branch: str,
) -> str:
    lines = [
        f"Tony-managed cross-review ({reviewer.value} reviewing)",
        "",
        f"Task ID: {plan.task_id}",
        f"Goal under review: {plan.user_goal}",
        f"Tool or area: {plan.tool_or_area}",
        "",
        "Review the implementer's diff for this task only.",
        "Check: correctness, safety boundaries, secret handling, tests.",
        (
            f"Diff under review: run `git diff {base_branch}...HEAD` "
            "(read-only) to obtain the exact patch. Review the patch, "
            "not just current file contents."
        ),
        "",
        "Allowed scope:",
        *[f"- {item}" for item in plan.allowed_files_or_areas],
        "",
        "Blocked scope:",
        *[f"- {item}" for item in plan.blocked_files_or_areas],
        "",
        "Secret-printing bans:",
        *[f"- {item}" for item in SECRET_PRINTING_BANS],
        "",
        *_VERDICT_PROTOCOL_LINES,
    ]
    prompt = "\n".join(lines)
    lowered = prompt.lower()
    if any(term in lowered for term in ("database_url=", "authorization: bearer ")):
        raise ValueError("review_prompt_contains_private_material")
    return prompt


def _reviewer_command_template(reviewer: BuildSeat, base_branch: str) -> str:
    if reviewer == BuildSeat.CODEX:
        # codex-cli 0.143.0 rejects `[PROMPT]` when combined with `--base`
        # (clap parser bug: "the argument '--base <BRANCH>' cannot be used
        # with '[PROMPT]'"). We therefore emit --base only and rely on the
        # default review body. The verdict-protocol prompt CANNOT be
        # injected until a wrapper exists on the reviewer side, so a codex
        # review that omits an explicit `VERDICT: SHIP` line correctly
        # fails the gate closed via parse_review_verdict.
        template = f"codex review --base {base_branch}"
    else:
        template = (
            'claude -p "{review_prompt}" '
            '--allowedTools "Read,Grep,Glob,Bash(git diff:*)" '
            "--permission-mode dontAsk "
            "--max-turns 20 "
            "--output-format json"
        )
    lowered = template.lower()
    if any(marker in lowered for marker in _COMMAND_SPEC_BANNED_MARKERS):
        raise ValueError("reviewer_command_template_unsafe")
    return template


def build_cross_review_spec(
    plan: CodexTaskPlan,
    implementer: BuildSeat | str,
    base_branch: str = "main",
) -> CrossReviewSpec:
    """Prepare a non-executing cross-review spec for one task plan."""
    if not isinstance(plan, CodexTaskPlan):
        raise ValueError("codex_task_plan_required")
    impl = _coerce_seat(implementer)
    reviewer = reviewer_for(impl)
    assert_two_seat_rule(impl, reviewer)
    branch = _clean_branch(base_branch)
    prompt = _build_review_prompt(plan, reviewer, branch)
    template = _reviewer_command_template(reviewer, branch)
    return CrossReviewSpec(
        task_id=plan.task_id,
        implementer_seat=impl.value,
        reviewer_seat=reviewer.value,
        base_branch=branch,
        review_prompt=prompt,
        reviewer_command_template=template,
        execution_allowed=False,
        review_invoked=False,
    )


def parse_review_verdict(raw_verdict_text: str | None) -> ReviewGateStatus:
    """Map reviewer output to a gate status. Ambiguity fails closed.

    A line is a verdict only when its whitespace-collapsed, upper-cased
    form equals a token exactly. Substring hits like "VERDICT: SHIPPING"
    or "not VERDICT: SHIP" therefore do not count. If both tokens appear
    on their own lines, or neither does, the gate fails closed.
    """
    if not isinstance(raw_verdict_text, str) or not raw_verdict_text.strip():
        return ReviewGateStatus.REVIEW_FAILED
    has_ship = False
    has_do_not_ship = False
    for line in raw_verdict_text.splitlines():
        normalised = " ".join(line.split()).upper()
        if normalised == SHIP_TOKEN:
            has_ship = True
        elif normalised == DO_NOT_SHIP_TOKEN:
            has_do_not_ship = True
    if has_ship and has_do_not_ship:
        return ReviewGateStatus.REVIEW_FAILED
    if has_ship:
        return ReviewGateStatus.REVIEW_PASSED
    return ReviewGateStatus.REVIEW_FAILED


def evaluate_review_outcome(
    spec: CrossReviewSpec,
    raw_verdict_text: str | None,
) -> ReviewOutcome:
    """Evaluate a verdict against the two-seat rule, failing closed."""
    if not isinstance(spec, CrossReviewSpec):
        raise ValueError("cross_review_spec_required")

    refusal_reason: str | None = None
    try:
        assert_two_seat_rule(spec.implementer_seat, spec.reviewer_seat)
        status = parse_review_verdict(raw_verdict_text)
        if status != ReviewGateStatus.REVIEW_PASSED:
            refusal_reason = "reviewer_verdict_not_ship"
    except ValueError as error:
        status = ReviewGateStatus.REVIEW_FAILED
        refusal_reason = str(error)

    can_advance = status == ReviewGateStatus.REVIEW_PASSED
    return ReviewOutcome(
        task_id=spec.task_id,
        implementer_seat=spec.implementer_seat,
        reviewer_seat=spec.reviewer_seat,
        status=status,
        can_advance_to_tests=can_advance,
        refusal_reason=refusal_reason,
    )
