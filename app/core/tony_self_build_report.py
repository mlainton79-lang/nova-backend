"""Safe Tony self-build rehearsal report helper.

This module turns local Codex runner metadata into a small backend-only report
shape Tony can reason over. It is deliberately pure and metadata-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


_PRIVATE_TERMS = (
    "authorization",
    "bearer ",
    "dev_token",
    "database_url",
    "credential",
    "cookie=",
    "session=",
    "oauth",
    "refresh_token",
    "access_token",
    "github_token",
    "railway_token",
    "approval_challenge",
    "action_hash",
    "pending_id",
    "grant_id",
    "raw notification",
    "raw payload",
    "gmail payload",
    "vinted account",
    "browser session",
)

_UNSAFE_PATH_PARTS = (
    "..",
    "~",
    ".env",
    ".envrc",
    ".bashrc",
    ".zshrc",
    ".profile",
)

_MUTATION_FLAGS = (
    "external_apis_called",
    "github_mutation_performed",
    "railway_mutation_performed",
    "secrets_exposed",
)


@dataclass(frozen=True)
class TonySelfBuildRehearsalReport:
    """Safe summary of a local unsandboxed phone rehearsal."""

    status: str
    completed: bool
    changed_files_summary: tuple[str, ...]
    tests_summary: tuple[str, ...]
    deployment_summary: str
    unsandboxed_requested: bool
    unsandboxed_allowed: bool
    unsandboxed_used: bool
    changed_files_validated: bool
    needs_attention: tuple[str, ...]
    final_report: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "completed": self.completed,
            "changed_files_summary": self.changed_files_summary,
            "tests_summary": self.tests_summary,
            "deployment_summary": self.deployment_summary,
            "unsandboxed_requested": self.unsandboxed_requested,
            "unsandboxed_allowed": self.unsandboxed_allowed,
            "unsandboxed_used": self.unsandboxed_used,
            "changed_files_validated": self.changed_files_validated,
            "needs_attention": self.needs_attention,
            "final_report": self.final_report,
        }


def _clean_text(value: Any, field_name: str, max_chars: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}_required")
    text = " ".join(value.strip().split())
    lowered = text.lower()
    if any(term in lowered for term in _PRIVATE_TERMS):
        raise ValueError(f"{field_name}_contains_private_material")
    return text[:max_chars]


def _clean_tuple(
    values: Iterable[Any] | None,
    field_name: str,
    max_items: int = 30,
    max_chars: int = 220,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise ValueError(f"{field_name}_must_be_list")
    cleaned = tuple(_clean_text(item, field_name, max_chars=max_chars) for item in values)
    return cleaned[:max_items]


def _clean_changed_files(values: Iterable[Any] | None) -> tuple[str, ...]:
    files = _clean_tuple(values, "changed_files_summary")
    for path in files:
        lowered = path.lower()
        if path.startswith("/") or any(part in lowered for part in _UNSAFE_PATH_PARTS):
            raise ValueError("changed_files_summary_contains_unsafe_path")
        if not path.startswith("app/core/"):
            raise ValueError("changed_files_summary_outside_backend_core_scope")
    return files


def build_unsandboxed_phone_rehearsal_report(
    local_runner_report: dict[str, Any],
) -> TonySelfBuildRehearsalReport:
    """Build safe Tony-facing metadata for an unsandboxed phone rehearsal."""
    if not isinstance(local_runner_report, dict):
        raise ValueError("local_runner_report_required")
    for flag in _MUTATION_FLAGS:
        if bool(local_runner_report.get(flag, False)):
            raise ValueError("unsafe_self_build_report_metadata")

    changed_files = _clean_changed_files(
        local_runner_report.get("changed_files_summary"),
    )
    tests = _clean_tuple(local_runner_report.get("tests_summary"), "tests_summary")
    deployment_summary = _clean_text(
        str(local_runner_report.get("deployment_summary", "not_attempted")),
        "deployment_summary",
        max_chars=120,
    )
    source_report = local_runner_report.get("final_report", "Local rehearsal reported.")
    _clean_text(str(source_report), "final_report", max_chars=500)

    unsandboxed_requested = bool(local_runner_report.get("codex_unsandboxed_requested"))
    unsandboxed_allowed = bool(local_runner_report.get("codex_unsandboxed_allowed"))
    unsandboxed_used = bool(local_runner_report.get("codex_unsandboxed_used"))
    changed_files_validated = bool(changed_files) and not bool(
        local_runner_report.get("unsafe_changed_files_detected", False)
    )
    completed = bool(local_runner_report.get("codex_task_completed_successfully"))

    needs_attention = []
    if deployment_summary != "not_attempted":
        needs_attention.append("Deployment metadata was not the expected not_attempted state.")
    if not unsandboxed_requested:
        needs_attention.append("Unsandboxed phone rehearsal was not requested.")
    elif not unsandboxed_allowed:
        needs_attention.append("Unsandboxed phone rehearsal was refused by local guards.")
    elif not unsandboxed_used:
        needs_attention.append("Unsandboxed phone rehearsal did not run.")
    if not changed_files:
        needs_attention.append("No changed files were reported.")
    elif not changed_files_validated:
        needs_attention.append("Changed files were reported but failed safety validation.")
    if not completed:
        needs_attention.append("Local Codex task did not report successful completion.")

    status = "completed" if completed and not needs_attention else "needs_attention"
    final_report = (
        "Unsandboxed phone rehearsal completed with safe app/core changed-file "
        "metadata."
        if status == "completed"
        else "Unsandboxed phone rehearsal needs Matthew review before being treated as complete."
    )

    return TonySelfBuildRehearsalReport(
        status=status,
        completed=completed and status == "completed",
        changed_files_summary=changed_files,
        tests_summary=tests,
        deployment_summary=deployment_summary,
        unsandboxed_requested=unsandboxed_requested,
        unsandboxed_allowed=unsandboxed_allowed,
        unsandboxed_used=unsandboxed_used,
        changed_files_validated=changed_files_validated,
        needs_attention=tuple(needs_attention),
        final_report=final_report,
    )
