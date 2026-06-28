#!/usr/bin/env python3
"""Structural checks for the disabled Tony Codex runner boundary v1."""

import ast
import os
import sys
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core import codex_runner, codex_tasks  # noqa: E402


class CodexRunnerBoundaryTests(unittest.TestCase):
    def _plan(self):
        return codex_tasks.mark_codex_task_ready(
            codex_tasks.create_codex_task_plan(
                "Add a backend-only local helper with tests",
                tool_or_area="nova-backend local helpers",
            )
        )

    def test_codex_runner_module_exists_and_default_mode_is_disabled(self):
        self.assertEqual(
            codex_runner.DEFAULT_RUNNER_MODE,
            codex_runner.CodexRunnerMode.DISABLED,
        )
        self.assertTrue(hasattr(codex_runner, "run_codex_task"))
        self.assertTrue(hasattr(codex_runner, "can_runner_execute_task"))
        self.assertTrue(hasattr(codex_runner, "build_disabled_runner_result"))

    def test_disabled_mode_accepts_valid_plan_but_refuses_execution(self):
        plan = self._plan()
        boundary = codex_runner.run_codex_task(plan)

        self.assertEqual(boundary.decision.task_id, plan.task_id)
        self.assertEqual(boundary.decision.mode, "disabled")
        self.assertFalse(boundary.decision.execution_allowed)
        self.assertEqual(boundary.decision.refusal_reason, "runner_disabled")
        self.assertFalse(boundary.decision.codex_execution_invoked)
        self.assertTrue(boundary.decision.safe_prompt_prepared)
        self.assertGreater(boundary.decision.safe_prompt_length, 0)
        self.assertFalse(boundary.task_result.codex_execution_invoked)
        self.assertFalse(boundary.task_result.external_apis_called)

    def test_disabled_mode_prepares_safe_prompt_summary_only(self):
        plan = self._plan()
        decision = codex_runner.can_runner_execute_task(plan)

        self.assertTrue(decision.safe_prompt_prepared)
        self.assertIn("Goal:", decision.safe_prompt_summary)
        self.assertLessEqual(len(decision.safe_prompt_summary), 160)
        self.assertNotIn("Secret-printing bans:", decision.safe_prompt_summary)
        self.assertNotIn("DATABASE_URL", decision.safe_prompt_summary)

    def test_prompt_only_mode_does_not_run_codex(self):
        plan = self._plan()
        boundary = codex_runner.run_codex_task(
            codex_runner.CodexRunnerRequest(
                plan=plan,
                mode=codex_runner.CodexRunnerMode.PROMPT_ONLY,
            )
        )

        self.assertEqual(boundary.decision.mode, "prompt_only")
        self.assertFalse(boundary.decision.execution_allowed)
        self.assertEqual(
            boundary.decision.refusal_reason,
            "prompt_only_does_not_execute",
        )
        self.assertFalse(boundary.task_result.codex_execution_invoked)

    def test_dry_run_mode_does_not_run_codex(self):
        plan = self._plan()
        boundary = codex_runner.run_codex_task(
            plan,
            mode=codex_runner.CodexRunnerMode.DRY_RUN,
        )

        self.assertEqual(boundary.decision.mode, "dry_run")
        self.assertFalse(boundary.decision.execution_allowed)
        self.assertEqual(boundary.decision.refusal_reason, "dry_run_does_not_execute")
        self.assertFalse(boundary.task_result.codex_execution_invoked)

    def test_future_modes_are_not_executable_yet(self):
        plan = self._plan()
        for mode in (
            codex_runner.CodexRunnerMode.FUTURE_LOCAL_CODEX_CLI,
            codex_runner.CodexRunnerMode.FUTURE_ISOLATED_WORKER,
        ):
            with self.subTest(mode=mode.value):
                boundary = codex_runner.run_codex_task(plan, mode=mode)
                self.assertFalse(boundary.decision.execution_allowed)
                self.assertEqual(
                    boundary.decision.refusal_reason,
                    "future_runner_mode_not_implemented",
                )
                self.assertFalse(boundary.task_result.codex_execution_invoked)

    def test_unknown_mode_fails_closed(self):
        plan = self._plan()
        boundary = codex_runner.run_codex_task(plan, mode="unexpected_live_runner")

        self.assertEqual(boundary.decision.mode, "unexpected_live_runner")
        self.assertFalse(boundary.decision.execution_allowed)
        self.assertEqual(boundary.decision.refusal_reason, "unknown_runner_mode")
        self.assertFalse(boundary.decision.safe_prompt_prepared)
        self.assertEqual(boundary.task_result.status, codex_tasks.CodexTaskStatus.FAILED_SAFE)

    def test_deployment_without_matthew_approval_fails_closed(self):
        plan = replace(
            self._plan(),
            can_deploy=True,
            requires_matthew_approval_before_deploy=False,
        )
        boundary = codex_runner.run_codex_task(plan)

        self.assertFalse(boundary.decision.execution_allowed)
        self.assertEqual(
            boundary.decision.refusal_reason,
            "deploy_without_matthew_approval_blocked",
        )
        self.assertEqual(boundary.task_result.status, codex_tasks.CodexTaskStatus.FAILED_SAFE)

    def test_sensitive_scopes_fail_closed(self):
        base = self._plan()
        dangerous_allowed_scopes = (
            "edit secret-bearing files",
            "modify Railway variable values",
            "read production database rows",
            "change approval bypass code",
            "disable safety gates",
            "touch Gmail OAuth sessions",
            "touch Vinted session data",
            "use browser session data",
            "implement payment transfer logic",
        )
        for scope in dangerous_allowed_scopes:
            with self.subTest(scope=scope):
                plan = replace(base, allowed_files_or_areas=(scope,))
                boundary = codex_runner.run_codex_task(plan)
                self.assertFalse(boundary.decision.execution_allowed)
                self.assertEqual(
                    boundary.decision.refusal_reason,
                    "codex_runner_plan_scope_blocked",
                )
                self.assertEqual(
                    boundary.task_result.status,
                    codex_tasks.CodexTaskStatus.FAILED_SAFE,
                )

    def test_runner_returns_codex_task_result_compatible_safe_metadata(self):
        plan = self._plan()
        result = codex_runner.build_disabled_runner_result(plan)

        self.assertIsInstance(result, codex_tasks.CodexTaskResult)
        self.assertEqual(result.task_id, plan.task_id)
        self.assertEqual(result.status, codex_tasks.CodexTaskStatus.READY_TO_REPORT)
        self.assertEqual(result.changed_files_summary, ())
        self.assertEqual(result.deployment_summary, "not_attempted")
        self.assertFalse(result.codex_execution_invoked)
        self.assertFalse(result.github_mutation_performed)
        self.assertFalse(result.railway_mutation_performed)
        self.assertFalse(result.secrets_exposed)

    def test_matthew_completion_report_works_with_runner_result(self):
        plan = self._plan()
        boundary = codex_runner.run_codex_task(plan)

        report = codex_tasks.build_matthew_completion_report(
            plan,
            boundary.task_result,
        )

        self.assertTrue(report.completed)
        self.assertEqual(report.status, codex_tasks.CodexTaskStatus.READY_TO_REPORT)
        self.assertIn("refused execution", report.final_report)
        self.assertEqual(report.deployment_summary, "not_attempted")

    def test_runner_does_not_import_execution_or_external_api_modules(self):
        with open(codex_runner.__file__, encoding="utf-8") as source_file:
            tree = ast.parse(source_file.read())

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")

        prohibited_imports = {
            "subprocess",
            "openai",
            "requests",
            "httpx",
            "app.core.approval_lock",
            "app.core.user_notifications",
            "app.core.push_notifications",
        }
        self.assertTrue(prohibited_imports.isdisjoint(imports))

    def test_runner_source_contains_no_git_railway_or_notification_calls(self):
        with open(codex_runner.__file__, encoding="utf-8") as source_file:
            source = source_file.read()

        prohibited = (
            "git push",
            "git commit",
            "railway up",
            "railway variables",
            "railway variable set",
            "create_pending_approval_once",
            "send_user_notification",
            "send_push",
            "Popen",
            "run(",
            "check_call",
            "check_output",
        )
        for item in prohibited:
            self.assertNotIn(item, source)

    def test_runner_does_not_expose_private_material(self):
        plan = self._plan()
        boundary = codex_runner.run_codex_task(plan)
        safe_text = " ".join(
            (
                boundary.decision.safe_prompt_summary,
                boundary.decision.refusal_reason or "",
                boundary.decision.safe_next_step,
                boundary.task_result.final_report,
            )
        ).lower()

        for private_shape in (
            "database_url",
            "authorization",
            "dev_token",
            "refresh token",
            "access token",
            "cookie=",
            "session=",
            "approval_challenge",
            "action_hash",
            "pending_id",
            "grant_id",
        ):
            self.assertNotIn(private_shape, safe_text)


if __name__ == "__main__":
    unittest.main()
