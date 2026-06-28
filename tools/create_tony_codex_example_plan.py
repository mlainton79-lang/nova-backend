#!/usr/bin/env python3
"""Create a local prompt-only Tony Codex rehearsal plan."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.codex_tasks import CodexTaskPlan, create_codex_task_plan  # noqa: E402


OUTPUT_DIR = REPO_ROOT / ".tony_codex"
EXAMPLE_PLAN_PATH = OUTPUT_DIR / "example-plan.json"

EXAMPLE_USER_GOAL = (
    "Add a harmless backend-only local helper that summarizes safe task metadata "
    "and includes focused unit tests."
)
EXAMPLE_TOOL_OR_AREA = "nova-backend local helper rehearsal"
EXAMPLE_ALLOWED_SCOPE = (
    "app/core local helper module for safe metadata only",
    "app/core focused unit tests for the helper",
    "tools local rehearsal scripts and tests",
)
EXAMPLE_BLOCKED_SCOPE = (
    "credential-bearing files",
    "live service configuration",
    "live data access",
    "external account state",
    "real account automation",
    "approval safety semantics",
    "financial or marketplace transaction flows",
)


def create_example_plan() -> CodexTaskPlan:
    """Build the safe local-only example Codex task plan."""
    return create_codex_task_plan(
        user_goal=EXAMPLE_USER_GOAL,
        requested_by="tony",
        tool_or_area=EXAMPLE_TOOL_OR_AREA,
        autonomy_scope="local_prompt_only_handoff_rehearsal",
        allowed_files_or_areas=EXAMPLE_ALLOWED_SCOPE,
        blocked_files_or_areas=EXAMPLE_BLOCKED_SCOPE,
        can_edit_code=True,
        can_run_tests=True,
        can_commit=False,
        can_push_branch=False,
        can_deploy=False,
        requires_matthew_approval_before_deploy=True,
    )


def plan_to_json_dict(plan: CodexTaskPlan) -> dict[str, Any]:
    """Serialize a CodexTaskPlan into the bridge's JSON input shape."""
    return {
        "task_id": plan.task_id,
        "requested_by": plan.requested_by,
        "user_goal": plan.user_goal,
        "tool_or_area": plan.tool_or_area,
        "intended_change_summary": plan.intended_change_summary,
        "autonomy_scope": plan.autonomy_scope,
        "allowed_files_or_areas": list(plan.allowed_files_or_areas),
        "blocked_files_or_areas": list(plan.blocked_files_or_areas),
        "validation_requirements": list(plan.validation_requirements),
        "reporting_requirements": list(plan.reporting_requirements),
        "can_edit_code": plan.can_edit_code,
        "can_run_tests": plan.can_run_tests,
        "can_commit": plan.can_commit,
        "can_push_branch": plan.can_push_branch,
        "can_deploy": plan.can_deploy,
        "requires_matthew_approval_before_deploy": (
            plan.requires_matthew_approval_before_deploy
        ),
        "status": plan.status.value,
    }


def write_example_plan(path: Path = EXAMPLE_PLAN_PATH) -> tuple[CodexTaskPlan, Path]:
    """Write the example plan JSON for the local bridge."""
    plan = create_example_plan()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as target:
        json.dump(plan_to_json_dict(plan), target, indent=2, sort_keys=True)
        target.write("\n")
    return plan, path


def safe_plan_metadata(plan: CodexTaskPlan, path: Path) -> dict[str, Any]:
    """Return only safe metadata for command-line output."""
    return {
        "plan_path": str(path.relative_to(REPO_ROOT)),
        "task_id": plan.task_id,
        "tool_or_area": plan.tool_or_area,
        "status": plan.status.value,
        "can_edit_code": plan.can_edit_code,
        "can_run_tests": plan.can_run_tests,
        "can_commit": plan.can_commit,
        "can_push_branch": plan.can_push_branch,
        "can_deploy": plan.can_deploy,
    }


def main() -> int:
    plan, path = write_example_plan()
    print(json.dumps(safe_plan_metadata(plan, path), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
