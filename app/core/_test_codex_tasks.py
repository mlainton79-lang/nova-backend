#!/usr/bin/env python3
"""Structural checks for Tony-managed Codex task workflow v1."""

import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core import codex_tasks  # noqa: E402


class CodexTaskWorkflowTests(unittest.TestCase):
    def test_tony_can_create_codex_task_plan_from_user_goal(self):
        plan = codex_tasks.create_codex_task_plan(
            "Add a small internal helper for safe capability reporting",
            tool_or_area="nova-backend capabilities",
        )

        self.assertTrue(plan.task_id.startswith("codex-"))
        self.assertEqual(plan.requested_by, "tony")
        self.assertEqual(plan.status, codex_tasks.CodexTaskStatus.PLANNED)
        self.assertIn("capability reporting", plan.user_goal)
        self.assertIn("nova-backend capabilities", plan.tool_or_area)
        self.assertTrue(plan.can_edit_code)
        self.assertTrue(plan.can_run_tests)
        self.assertFalse(plan.can_commit)
        self.assertFalse(plan.can_push_branch)
        self.assertFalse(plan.can_deploy)
        self.assertTrue(plan.requires_matthew_approval_before_deploy)

    def test_task_plan_includes_allowed_and_blocked_scope(self):
        plan = codex_tasks.create_codex_task_plan(
            "Improve a local backend-only status helper",
            allowed_files_or_areas=("app/core/status_helper.py", "app/core/_test_status_helper.py"),
            blocked_files_or_areas=("Android code", "production database access"),
        )

        self.assertIn("app/core/status_helper.py", plan.allowed_files_or_areas)
        self.assertIn("Android code", plan.blocked_files_or_areas)
        self.assertIn("production database access", plan.blocked_files_or_areas)

    def test_mark_codex_task_ready_is_non_executing_status_change(self):
        plan = codex_tasks.create_codex_task_plan("Add tests for local helper")
        ready = codex_tasks.mark_codex_task_ready(plan)

        self.assertEqual(plan.status, codex_tasks.CodexTaskStatus.PLANNED)
        self.assertEqual(ready.status, codex_tasks.CodexTaskStatus.READY_FOR_CODEX)
        self.assertEqual(ready.task_id, plan.task_id)

    def test_generated_codex_prompt_includes_validation_and_safety_requirements(self):
        plan = codex_tasks.mark_codex_task_ready(
            codex_tasks.create_codex_task_plan(
                "Add a backend-only test helper",
                can_commit=False,
                can_deploy=False,
            )
        )
        prompt = codex_tasks.build_codex_prompt_from_task(plan)

        self.assertIn("Goal: Add a backend-only test helper", prompt)
        self.assertIn("Allowed scope:", prompt)
        self.assertIn("Blocked scope:", prompt)
        self.assertIn("Validation requirements:", prompt)
        self.assertIn("git diff --check", prompt)
        self.assertIn("python -m compileall -q app", prompt)
        self.assertIn("Reporting requirements:", prompt)
        self.assertIn("Secret-printing bans:", prompt)
        self.assertIn("can_deploy: False", prompt)
        self.assertIn("requires_matthew_approval_before_deploy: True", prompt)

    def test_generated_codex_prompt_does_not_include_private_values(self):
        plan = codex_tasks.create_codex_task_plan("Add safe local tests")
        prompt = codex_tasks.build_codex_prompt_from_task(plan).lower()

        for private_value_shape in (
            "database_url=",
            "authorization: bearer ",
            "sk-",
            "github_pat_",
            "refresh_token=",
            "cookie=",
            "session=",
        ):
            self.assertNotIn(private_value_shape, prompt)

    def test_sensitive_user_goal_is_rejected_before_prompt_generation(self):
        with self.assertRaisesRegex(ValueError, "user_goal_contains_sensitive_reference"):
            codex_tasks.create_codex_task_plan(
                "Use DATABASE_URL to inspect production database rows"
            )

    def test_dangerous_scope_is_blocked(self):
        for goal in (
            "Disable safety gates around approval bypass",
            "Modify Railway variables for production",
            "Touch Gmail OAuth session handling",
            "Run browser automation against real accounts",
        ):
            with self.subTest(goal=goal):
                with self.assertRaisesRegex(
                    ValueError,
                    "codex_task_scope_requires_explicit_unlock|user_goal_contains_sensitive_reference",
                ):
                    codex_tasks.create_codex_task_plan(goal)

    def test_production_deploy_without_permission_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "deploy_without_matthew_approval_blocked"):
            codex_tasks.create_codex_task_plan(
                "Add a harmless local helper",
                can_deploy=True,
                requires_matthew_approval_before_deploy=False,
            )

    def test_result_summary_is_sanitized_and_non_executing(self):
        result = codex_tasks.CodexTaskResult(
            task_id="codex-safe123",
            status=codex_tasks.CodexTaskStatus.TESTS_PASSED,
            changed_files_summary=("app/core/example.py", "app/core/_test_example.py"),
            tests_summary=("targeted unittest passed",),
            deployment_summary="not_attempted",
        )
        summary = codex_tasks.summarise_codex_task_result(result)

        self.assertEqual(summary["status"], "tests_passed")
        self.assertFalse(summary["codex_execution_invoked"])
        self.assertFalse(summary["external_apis_called"])
        self.assertFalse(summary["github_mutation_performed"])
        self.assertFalse(summary["railway_mutation_performed"])
        self.assertFalse(summary["secrets_exposed"])
        self.assertEqual(summary["deployment_summary"], "not_attempted")

    def test_unsafe_result_metadata_fails_closed(self):
        result = codex_tasks.CodexTaskResult(
            task_id="codex-safe123",
            status=codex_tasks.CodexTaskStatus.TESTS_PASSED,
            external_apis_called=True,
        )

        summary = codex_tasks.summarise_codex_task_result(result)

        self.assertEqual(summary["status"], "failed_safe")
        self.assertFalse(summary["external_apis_called"])

    def test_completion_report_is_suitable_for_matthew(self):
        plan = codex_tasks.create_codex_task_plan("Add a backend-only helper")
        result = codex_tasks.CodexTaskResult(
            task_id=plan.task_id,
            status=codex_tasks.CodexTaskStatus.TESTS_PASSED,
            changed_files_summary=("app/core/codex_tasks.py",),
            tests_summary=("targeted unittest passed", "compileall passed"),
            deployment_summary="not_attempted",
            final_report="Backend-only helper completed; tests passed.",
        )

        report = codex_tasks.build_matthew_completion_report(plan, result)

        self.assertTrue(report.completed)
        self.assertEqual(report.status, codex_tasks.CodexTaskStatus.TESTS_PASSED)
        self.assertIn("Backend-only helper completed", report.final_report)
        self.assertEqual(report.needs_attention, ())
        self.assertIn("app/core/codex_tasks.py", report.changed_files_summary)

    def test_failed_task_report_mentions_attention_needed(self):
        plan = codex_tasks.create_codex_task_plan("Add a backend-only helper")
        result = codex_tasks.CodexTaskResult(
            task_id=plan.task_id,
            status=codex_tasks.CodexTaskStatus.TESTS_FAILED,
            tests_summary=("targeted unittest failed",),
            deployment_summary="not_attempted",
        )

        report = codex_tasks.build_matthew_completion_report(plan, result)

        self.assertFalse(report.completed)
        self.assertIn("Tests failed", report.needs_attention[0])

    def test_codex_execution_is_not_invoked_by_module(self):
        with open(codex_tasks.__file__, encoding="utf-8") as source_file:
            source = source_file.read()

        forbidden_calls = (
            "subprocess",
            "os.system",
            "openai",
            "railway up",
            "railway variables",
            "railway variable set",
            "git push",
            "create_pending_approval_once",
            "send_user_notification",
        )
        for forbidden in forbidden_calls:
            self.assertNotIn(forbidden, source)

    def test_no_external_apis_or_mutation_imports_are_introduced(self):
        with open(codex_tasks.__file__, encoding="utf-8") as source_file:
            tree = ast.parse(source_file.read())

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")

        self.assertEqual(
            sorted(imports),
            ["dataclasses", "enum", "hashlib", "typing"],
        )

    def test_policy_blocks_secret_railway_env_and_approval_bypass_modification(self):
        blocked_goals = (
            "Print secret material during tests",
            "Modify Railway variable configuration",
            "Change approval bypass logic",
        )
        for goal in blocked_goals:
            with self.subTest(goal=goal):
                with self.assertRaises(ValueError):
                    codex_tasks.create_codex_task_plan(goal)


if __name__ == "__main__":
    unittest.main()
