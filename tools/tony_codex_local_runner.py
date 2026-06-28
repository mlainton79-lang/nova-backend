#!/usr/bin/env python3
"""Local-only Tony Codex bridge.

This utility is for Matthew's local repo environment. It is not imported by
FastAPI, not run by Railway, and not automatic. Default mode is prompt-only:
prepare a sanitized Codex prompt from a CodexTaskPlan and write a safe report.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.codex_runner import (  # noqa: E402
    CodexRunnerMode,
    can_runner_execute_task,
)
from app.core.codex_tasks import (  # noqa: E402
    CodexTaskPlan,
    CodexTaskStatus,
    build_codex_prompt_from_task,
)


DEFAULT_MODE = "prompt-only"
SAFE_OUTPUT_DIR = REPO_ROOT / ".tony_codex"
ALLOW_EXECUTION_ENV = "TONY_CODEX_LOCAL_RUNNER_ALLOW_EXECUTION"
ALLOW_UNSANDBOXED_ENV = "TONY_CODEX_LOCAL_RUNNER_ALLOW_UNSANDBOXED_CODEX"

_DANGEROUS_TERMS = (
    "secret",
    "credential",
    "github push",
    "git push",
    "github mutation",
    "deployment",
    "deploy",
    "railway mutation",
    "railway variable",
    "environment variable",
    "production database",
    "production db",
    "approval bypass",
    "bypass approval",
    "disable safety",
    "safety gate",
    "disable urgent gate",
    "notification sending",
    "send notification",
    "gmail oauth",
    "oauth material",
    "gmail session",
    "gmail",
    "vinted",
    "vinted session",
    "oauth session",
    "browser session",
    "browser automation",
    "browser automation against real accounts",
    "payment",
    "order handling",
    "bank transfer",
    "buyer message",
    "post listing",
    "buy postage",
)

_BACKEND_LOCAL_MARKERS = (
    "backend",
    "nova-backend",
    "app/core",
    "tools",
    "local helper",
    "local tooling",
)

_PRIVATE_OUTPUT_PATTERNS = (
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
)

_TTY_ERROR_PATTERNS = (
    "stdin is not a terminal",
    "not a terminal",
    "requires a tty",
)

_ENVIRONMENT_BLOCK_PATTERNS = (
    "blocked by the execution environment",
    "bwrap: creating new namespace failed",
    "apply_patch cannot write",
    "no repo files were changed",
    "shell commands fail before execution",
    "cannot write inside",
)

_SAFE_CHILD_ENV_KEYS = (
    "PATH",
    "HOME",
    "USER",
    "SHELL",
    "TERM",
    "LANG",
    "LC_ALL",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "CODEX_HOME",
)

_SECRET_ENV_KEY_PARTS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "COOKIE",
    "SESSION",
    "DATABASE_URL",
    "AUTHORIZATION",
    "API_KEY",
    "ACCESS_KEY",
    "REFRESH",
)


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    raise ValueError("expected_list_or_string")


def _load_json(path: str | None) -> dict[str, Any]:
    if path:
        with open(path, encoding="utf-8") as source:
            return json.load(source)
    return json.load(sys.stdin)


def codex_task_plan_from_dict(data: dict[str, Any]) -> CodexTaskPlan:
    """Build a CodexTaskPlan from a safe JSON object."""
    try:
        status = CodexTaskStatus(data.get("status", CodexTaskStatus.PLANNED.value))
        return CodexTaskPlan(
            task_id=str(data["task_id"]),
            requested_by=str(data["requested_by"]),
            user_goal=str(data["user_goal"]),
            tool_or_area=str(data["tool_or_area"]),
            intended_change_summary=str(data["intended_change_summary"]),
            autonomy_scope=str(data["autonomy_scope"]),
            allowed_files_or_areas=_tuple(data.get("allowed_files_or_areas")),
            blocked_files_or_areas=_tuple(data.get("blocked_files_or_areas")),
            validation_requirements=_tuple(data.get("validation_requirements")),
            reporting_requirements=_tuple(data.get("reporting_requirements")),
            can_edit_code=bool(data.get("can_edit_code", False)),
            can_run_tests=bool(data.get("can_run_tests", False)),
            can_commit=bool(data.get("can_commit", False)),
            can_push_branch=bool(data.get("can_push_branch", False)),
            can_deploy=bool(data.get("can_deploy", False)),
            requires_matthew_approval_before_deploy=bool(
                data.get("requires_matthew_approval_before_deploy", True)
            ),
            status=status,
        )
    except KeyError as error:
        raise ValueError(f"missing_plan_field:{error.args[0]}") from error


def load_codex_task_plan(path: str | None = None) -> CodexTaskPlan:
    """Load a CodexTaskPlan from JSON file or stdin."""
    return codex_task_plan_from_dict(_load_json(path))


def _auth_header_from_env(auth_token_env: str) -> str:
    token = os.environ.get(auth_token_env, "").strip()
    if not token:
        raise ValueError("auth_token_env_not_set")
    return f"Bearer {token}"


def fetch_task_from_nova(base_url: str, auth_token_env: str) -> CodexTaskPlan:
    """Fetch one safe CodexTaskPlan from Nova without printing credentials."""
    url = base_url.rstrip("/") + "/api/v1/codex-tasks/next"
    request = urllib.request.Request(
        url,
        headers={"Authorization": _auth_header_from_env(auth_token_env)},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok") or not payload.get("found") or not payload.get("task"):
        raise ValueError("no_codex_task_available")
    return codex_task_plan_from_dict(payload["task"])


def post_report_to_nova(
    base_url: str,
    auth_token_env: str,
    task_id: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Post sanitized local-runner report metadata back to Nova."""
    safe_report = {
        "status": "ready_to_report",
        "changed_files_summary": report.get("changed_files_summary", ()),
        "tests_summary": report.get("tests_summary", ()),
        "deployment_summary": report.get("deployment_summary", "not_attempted"),
        "final_report": report.get("final_report", "Local prompt-only report prepared."),
        "codex_execution_invoked": bool(report.get("execution_attempted", False)),
        "external_apis_called": False,
        "github_mutation_performed": False,
        "railway_mutation_performed": False,
        "secrets_exposed": bool(report.get("secrets_exposed", False)),
    }
    body = json.dumps(safe_report).encode("utf-8")
    url = base_url.rstrip("/") + f"/api/v1/codex-tasks/{task_id}/report"
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": _auth_header_from_env(auth_token_env),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _plan_runtime_text(plan: CodexTaskPlan) -> str:
    return " ".join(
        (
            plan.user_goal,
            plan.tool_or_area,
            plan.intended_change_summary,
            plan.autonomy_scope,
            " ".join(plan.allowed_files_or_areas),
        )
    ).lower()


def _dangerous_scope_reason(plan: CodexTaskPlan) -> str | None:
    text = _plan_runtime_text(plan)
    for term in _DANGEROUS_TERMS:
        if term in text:
            return f"dangerous_scope:{term}"
    return None


def _backend_local_scope_reason(plan: CodexTaskPlan) -> str | None:
    text = _plan_runtime_text(plan)
    if not any(marker in text for marker in _BACKEND_LOCAL_MARKERS):
        return "not_backend_local_scope"
    return None


def _run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def current_branch() -> str:
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def working_tree_is_clean() -> bool:
    result = _run_git(["status", "--porcelain"])
    return result.returncode == 0 and result.stdout.strip() == ""


def changed_files_summary() -> tuple[str, ...]:
    result = _run_git(["status", "--short", "--untracked-files=all"])
    if result.returncode != 0:
        return ()
    changed: list[str] = []
    seen: set[str] = set()
    for raw_line in result.stdout.splitlines():
        path = _changed_path_from_git_status_line(raw_line)
        if not path or _ignored_changed_path(path) or path in seen:
            continue
        changed.append(path)
        seen.add(path)
    return tuple(changed)


def _changed_path_from_git_status_line(line: str) -> str | None:
    if len(line) < 4:
        return None
    path = line[3:].strip()
    if " -> " in path:
        path = path.rsplit(" -> ", 1)[1].strip()
    return path.strip('"') or None


def _ignored_changed_path(path: str) -> bool:
    raw = path.strip()
    normalized = raw.lstrip("./")
    lowered = normalized.lower()
    parts = lowered.split("/")
    return (
        raw.lower().startswith(".git/")
        or raw.lower().startswith(".tony_codex/")
        or lowered.startswith("git/")
        or lowered.startswith("tony_codex/")
        or "__pycache__" in parts
        or "pycache" in parts
        or lowered.endswith(".pyc")
    )


def build_codex_child_env() -> dict[str, str]:
    """Return a minimal environment for the child Codex process."""
    child_env: dict[str, str] = {}
    for key in _SAFE_CHILD_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None:
            child_env[key] = value
    return {
        key: value
        for key, value in child_env.items()
        if not any(part in key.upper() for part in _SECRET_ENV_KEY_PARTS)
    }


def _changed_file_allowed(path: str, allowed_scopes: tuple[str, ...]) -> bool:
    normalized_path = path.strip().lstrip("./").lower()
    scope_text = " ".join(allowed_scopes).lower()
    if normalized_path.startswith("app/core/"):
        return "app/core" in scope_text or "backend" in scope_text or "nova-backend" in scope_text
    if normalized_path.startswith("tools/"):
        return "tools" in scope_text or "local tooling" in scope_text
    return any(
        normalized_path.startswith(scope.strip().rstrip("/").lower() + "/")
        or normalized_path == scope.strip().lower()
        for scope in allowed_scopes
        if "/" in scope
    )


def unsafe_changed_files(
    changed_files: tuple[str, ...],
    allowed_scopes: tuple[str, ...],
) -> tuple[str, ...]:
    """Return changed files outside the task's allowed file areas."""
    return tuple(
        path
        for path in changed_files
        if not _changed_file_allowed(path, allowed_scopes)
    )


def _safe_text(value: str, max_chars: int = 500) -> str:
    text = " ".join(str(value).split())
    lowered = text.lower()
    if any(pattern in lowered for pattern in _PRIVATE_OUTPUT_PATTERNS):
        return "[redacted unsafe output]"
    return text[:max_chars]


def _report_path(task_id: str) -> Path:
    safe_task_id = "".join(ch for ch in task_id if ch.isalnum() or ch in "-_")
    if not safe_task_id:
        safe_task_id = "codex-task"
    SAFE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return SAFE_OUTPUT_DIR / f"{safe_task_id}-report.json"


def _prompt_path(task_id: str) -> Path:
    safe_task_id = "".join(ch for ch in task_id if ch.isalnum() or ch in "-_")
    if not safe_task_id:
        safe_task_id = "codex-task"
    SAFE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return SAFE_OUTPUT_DIR / f"{safe_task_id}-prompt.txt"


def build_report(
    plan: CodexTaskPlan,
    mode: str,
    execution_attempted: bool,
    execution_allowed: bool,
    final_report: str,
    return_code: int | None = None,
    changed_files: tuple[str, ...] = (),
    tests_summary: tuple[str, ...] = (),
    prompt_path: str | None = None,
    codex_process_started: bool = False,
    codex_process_exit_success: bool = False,
    codex_completed_successfully: bool = False,
    codex_task_completed_successfully: bool = False,
    codex_environment_blocked: bool = False,
    codex_requires_tty: bool = False,
    codex_unsandboxed_requested: bool = False,
    codex_unsandboxed_allowed: bool = False,
    codex_unsandboxed_used: bool = False,
    unsafe_changed_files_detected: bool = False,
) -> dict[str, Any]:
    return {
        "task_id": plan.task_id,
        "mode": mode,
        "execution_attempted": execution_attempted,
        "execution_allowed": execution_allowed,
        "return_code": return_code,
        "changed_files_summary": changed_files,
        "tests_summary": tests_summary,
        "deployment_summary": "not_attempted",
        "secrets_exposed": False,
        "prompt_path": prompt_path,
        "codex_process_started": codex_process_started,
        "codex_process_exit_success": codex_process_exit_success,
        "codex_completed_successfully": codex_completed_successfully,
        "codex_task_completed_successfully": codex_task_completed_successfully,
        "codex_environment_blocked": codex_environment_blocked,
        "codex_requires_tty": codex_requires_tty,
        "codex_unsandboxed_requested": codex_unsandboxed_requested,
        "codex_unsandboxed_allowed": codex_unsandboxed_allowed,
        "codex_unsandboxed_used": codex_unsandboxed_used,
        "unsafe_changed_files_detected": unsafe_changed_files_detected,
        "final_report": _safe_text(final_report),
    }


def write_report(report: dict[str, Any], task_id: str) -> Path:
    path = _report_path(task_id)
    with open(path, "w", encoding="utf-8") as target:
        json.dump(report, target, indent=2, sort_keys=True)
        target.write("\n")
    return path


def validate_local_execution_guards(
    plan: CodexTaskPlan,
    confirm_execution: bool,
    allow_dirty: bool,
    allow_main_branch: bool,
) -> str | None:
    if os.environ.get(ALLOW_EXECUTION_ENV) != "1":
        return "execution_env_not_enabled"
    if not confirm_execution:
        return "missing_explicit_local_execution_flag"
    if not plan.can_edit_code:
        return "task_cannot_edit_code"
    if not plan.can_run_tests:
        return "task_cannot_run_tests"
    if plan.can_commit:
        return "task_can_commit_blocked"
    if plan.can_deploy:
        return "task_can_deploy_blocked"
    if plan.can_push_branch:
        return "task_can_push_branch_blocked"
    dangerous_reason = _dangerous_scope_reason(plan)
    if dangerous_reason:
        return dangerous_reason
    backend_scope_reason = _backend_local_scope_reason(plan)
    if backend_scope_reason:
        return backend_scope_reason
    branch = current_branch()
    if branch in ("main", "master") and not allow_main_branch:
        return f"{branch}_branch_refused"
    if not working_tree_is_clean() and not allow_dirty:
        return "dirty_tree_refused"
    return None


def validate_unsandboxed_codex_guards(
    plan: CodexTaskPlan,
    confirm_unsandboxed: bool,
) -> str | None:
    """Validate the extra guards for unsandboxed phone/proot Codex execution."""
    if os.environ.get(ALLOW_UNSANDBOXED_ENV) != "1":
        return "unsandboxed_env_not_enabled"
    if not confirm_unsandboxed:
        return "missing_explicit_unsandboxed_flag"
    if not plan.requires_matthew_approval_before_deploy:
        return "deploy_approval_requirement_missing"
    return None


def build_codex_exec_command(
    codex_bin: str,
    use_unsandboxed: bool,
) -> list[str]:
    """Return the supported non-interactive Codex exec command shape."""
    if use_unsandboxed:
        return [
            codex_bin,
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "-",
        ]
    return [
        codex_bin,
        "exec",
        "--sandbox",
        "workspace-write",
        "-",
    ]


def run_prompt_only(plan: CodexTaskPlan, write_prompt: bool) -> dict[str, Any]:
    decision = can_runner_execute_task(plan, CodexRunnerMode.PROMPT_ONLY)
    prompt = build_codex_prompt_from_task(plan)
    prompt_file = None
    if write_prompt:
        prompt_path = _prompt_path(plan.task_id)
        with open(prompt_path, "w", encoding="utf-8") as target:
            target.write(prompt)
            target.write("\n")
        prompt_file = str(prompt_path.relative_to(REPO_ROOT))
    else:
        print(prompt)
    return build_report(
        plan=plan,
        mode=DEFAULT_MODE,
        execution_attempted=False,
        execution_allowed=False,
        final_report=f"Prompt-only bridge prepared safe prompt; runner refused: {decision.refusal_reason}.",
        tests_summary=("prompt_generated",),
        prompt_path=prompt_file,
    )


def run_dry_run(plan: CodexTaskPlan) -> dict[str, Any]:
    decision = can_runner_execute_task(plan, CodexRunnerMode.DRY_RUN)
    return build_report(
        plan=plan,
        mode="dry-run",
        execution_attempted=False,
        execution_allowed=False,
        final_report=f"Dry run validated plan; runner refused execution: {decision.refusal_reason}.",
        tests_summary=("dry_run_no_execution",),
    )


def run_local_codex_cli(
    plan: CodexTaskPlan,
    confirm_execution: bool,
    allow_dirty: bool,
    allow_main_branch: bool,
    codex_bin: str,
    confirm_unsandboxed: bool = False,
) -> dict[str, Any]:
    unsandboxed_requested = (
        confirm_unsandboxed or os.environ.get(ALLOW_UNSANDBOXED_ENV) == "1"
    )
    refusal = validate_local_execution_guards(
        plan=plan,
        confirm_execution=confirm_execution,
        allow_dirty=allow_dirty,
        allow_main_branch=allow_main_branch,
    )
    if refusal:
        return build_report(
            plan=plan,
            mode="local-codex-cli",
            execution_attempted=False,
            execution_allowed=False,
            final_report=f"Local Codex CLI refused before execution: {refusal}.",
            tests_summary=("local_codex_cli_refused",),
            codex_unsandboxed_requested=unsandboxed_requested,
        )
    if unsandboxed_requested:
        unsandboxed_refusal = validate_unsandboxed_codex_guards(
            plan=plan,
            confirm_unsandboxed=confirm_unsandboxed,
        )
        if unsandboxed_refusal:
            return build_report(
                plan=plan,
                mode="local-codex-cli",
                execution_attempted=False,
                execution_allowed=False,
                final_report=(
                    "Local Codex CLI refused unsandboxed fallback before execution: "
                    f"{unsandboxed_refusal}."
                ),
                tests_summary=("local_codex_cli_refused",),
                codex_unsandboxed_requested=True,
            )

    prompt = build_codex_prompt_from_task(plan)
    command = build_codex_exec_command(
        codex_bin=codex_bin,
        use_unsandboxed=unsandboxed_requested,
    )
    result = subprocess.run(
        command,
        input=prompt,
        cwd=REPO_ROOT,
        env=build_codex_child_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    stdout_summary = _safe_text(result.stdout)
    stderr_summary = _safe_text(result.stderr)
    combined_output = f"{result.stdout}\n{result.stderr}".lower()
    codex_requires_tty = any(pattern in combined_output for pattern in _TTY_ERROR_PATTERNS)
    codex_environment_blocked = any(
        pattern in combined_output for pattern in _ENVIRONMENT_BLOCK_PATTERNS
    )
    changed_files = changed_files_summary()
    unsafe_files = unsafe_changed_files(changed_files, plan.allowed_files_or_areas)
    unsafe_files_detected = bool(unsafe_files)
    no_edit_changes = plan.can_edit_code and not changed_files
    codex_process_exit_success = result.returncode == 0
    codex_completed_successfully = (
        codex_process_exit_success
        and not codex_requires_tty
        and not codex_environment_blocked
    )
    codex_task_completed_successfully = (
        codex_completed_successfully
        and not no_edit_changes
        and not unsafe_files_detected
    )
    status_summary = (
        "codex_cli_requires_tty"
        if codex_requires_tty
        else "codex_environment_blocked"
        if codex_environment_blocked
        else "codex_failed"
        if not codex_process_exit_success
        else "unsafe_changed_files_detected"
        if unsafe_files_detected
        else "codex_no_files_changed"
        if no_edit_changes
        else "codex_completed_successfully"
        if codex_task_completed_successfully
        else "codex_failed"
    )
    return build_report(
        plan=plan,
        mode="local-codex-cli",
        execution_attempted=True,
        execution_allowed=True,
        return_code=result.returncode,
        final_report=(
            f"Local Codex CLI status={status_summary} return_code={result.returncode}. "
            f"stdout_summary={stdout_summary} stderr_summary={stderr_summary}"
        ),
        changed_files=changed_files,
        tests_summary=("local_codex_cli_invoked",),
        codex_process_started=True,
        codex_process_exit_success=codex_process_exit_success,
        codex_completed_successfully=codex_completed_successfully,
        codex_task_completed_successfully=codex_task_completed_successfully,
        codex_environment_blocked=codex_environment_blocked,
        codex_requires_tty=codex_requires_tty,
        codex_unsandboxed_requested=unsandboxed_requested,
        codex_unsandboxed_allowed=unsandboxed_requested,
        codex_unsandboxed_used=unsandboxed_requested,
        unsafe_changed_files_detected=unsafe_files_detected,
    )


def run_bridge(args: argparse.Namespace) -> dict[str, Any]:
    if args.fetch_from_nova:
        plan = fetch_task_from_nova(args.nova_base_url, args.auth_token_env)
    else:
        plan = load_codex_task_plan(args.plan)
    if args.mode == "prompt-only":
        report = run_prompt_only(plan, write_prompt=args.write_prompt)
    elif args.mode == "dry-run":
        report = run_dry_run(plan)
    elif args.mode == "local-codex-cli":
        report = run_local_codex_cli(
            plan=plan,
            confirm_execution=args.i_understand_local_code_execution,
            confirm_unsandboxed=args.i_understand_unsandboxed_local_codex,
            allow_dirty=args.allow_dirty,
            allow_main_branch=args.allow_main_branch,
            codex_bin=args.codex_bin,
        )
    else:
        report = build_report(
            plan=plan,
            mode=args.mode,
            execution_attempted=False,
            execution_allowed=False,
            final_report="Unknown mode refused before execution.",
            tests_summary=("unknown_mode_refused",),
        )

    if args.report_to_nova:
        post_response = post_report_to_nova(
            args.nova_base_url,
            args.auth_token_env,
            plan.task_id,
            report,
        )
        report["nova_report_posted"] = bool(post_response.get("ok"))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tony local Codex bridge")
    parser.add_argument("--plan", help="Path to CodexTaskPlan JSON. Reads stdin if omitted.")
    parser.add_argument(
        "--mode",
        choices=("prompt-only", "dry-run", "local-codex-cli"),
        default=DEFAULT_MODE,
    )
    parser.add_argument(
        "--write-prompt",
        action="store_true",
        help="Write prompt under .tony_codex instead of printing it.",
    )
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--allow-main-branch", action="store_true")
    parser.add_argument("--i-understand-local-code-execution", action="store_true")
    parser.add_argument("--i-understand-unsandboxed-local-codex", action="store_true")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--fetch-from-nova", action="store_true")
    parser.add_argument("--report-to-nova", action="store_true")
    parser.add_argument(
        "--nova-base-url",
        default="https://web-production-be42b.up.railway.app",
    )
    parser.add_argument("--auth-token-env", default="DEV_TOKEN")
    parser.add_argument(
        "--report",
        help="Optional report output path. Defaults to .tony_codex/<task_id>-report.json.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = run_bridge(args)
    report_path = Path(args.report) if args.report else _report_path(report["task_id"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as target:
        json.dump(report, target, indent=2, sort_keys=True)
        target.write("\n")
    print(json.dumps({"ok": True, "report_path": str(report_path)}, sort_keys=True))
    return 0 if not report["execution_allowed"] or report.get("return_code") in (0, None) else 1


if __name__ == "__main__":
    raise SystemExit(main())
