#!/usr/bin/env python3
"""Tests for Tony direct Codex handoff metadata store."""

import ast
import importlib.util
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core import codex_runner, codex_task_handoff  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_RUNNER_PATH = REPO_ROOT / "tools" / "tony_codex_local_runner.py"


def _load_local_runner_parser():
    spec = importlib.util.spec_from_file_location(
        "tony_codex_local_runner_contract_test",
        LOCAL_RUNNER_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CodexTaskHandoffTests(unittest.TestCase):
    def setUp(self):
        codex_task_handoff.reset_codex_handoff_store_for_tests()

    def test_backend_can_create_safe_codex_task_metadata(self):
        task = codex_task_handoff.create_pending_codex_task(
            user_goal="Add a harmless backend-only local helper with tests",
            tool_or_area="nova-backend local helpers",
            allowed_files_or_areas=("app/core local helper",),
            blocked_files_or_areas=("live external services",),
        )

        self.assertTrue(task["task_id"].startswith("codex-"))
        self.assertEqual(task["requested_by"], "tony")
        self.assertEqual(task["handoff_status"], "pending")
        self.assertEqual(task["status"], "planned")
        self.assertEqual(task["tool_or_area"], "nova-backend local helpers")
        self.assertTrue(task["can_edit_code"])
        self.assertTrue(task["can_run_tests"])
        self.assertFalse(task["can_commit"])
        self.assertFalse(task["can_push_branch"])
        self.assertFalse(task["can_deploy"])

    def test_backend_next_task_response_returns_safe_plan_only(self):
        created = codex_task_handoff.create_pending_codex_task(
            user_goal="Add a harmless backend-only local helper with tests",
            tool_or_area="nova-backend local helpers",
        )

        fetched = codex_task_handoff.get_next_pending_codex_task()

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["task_id"], created["task_id"])
        self.assertEqual(fetched["requested_by"], "tony")
        self.assertEqual(fetched["handoff_status"], "fetched")
        self.assertEqual(fetched["status"], "ready_for_codex")
        for forbidden in (
            "pending_id",
            "approval_challenge",
            "action_hash",
            "grant_id",
            "token",
            "secret",
            "raw_output",
        ):
            self.assertNotIn(forbidden, fetched)

    def test_backend_next_task_payload_parses_in_local_runner(self):
        created = codex_task_handoff.create_pending_codex_task(
            user_goal="Add a harmless backend-only local helper with tests",
            tool_or_area="nova-backend local helpers",
        )
        fetched = codex_task_handoff.get_next_pending_codex_task()
        local_runner = _load_local_runner_parser()

        parsed = local_runner.codex_task_plan_from_dict(fetched)

        self.assertEqual(parsed.task_id, created["task_id"])
        self.assertEqual(parsed.requested_by, "tony")
        self.assertEqual(parsed.status.value, "ready_for_codex")

    def test_backend_report_ingestion_accepts_sanitized_report(self):
        created = codex_task_handoff.create_pending_codex_task(
            user_goal="Add a harmless backend-only local helper with tests",
        )
        codex_task_handoff.get_next_pending_codex_task()

        report = codex_task_handoff.ingest_codex_task_report(
            created["task_id"],
            {
                "status": "ready_to_report",
                "changed_files_summary": ["app/core/example.py"],
                "tests_summary": ["targeted unittest passed"],
                "deployment_summary": "not_attempted",
                "final_report": "Prompt-only handoff completed.",
                "codex_execution_invoked": False,
                "external_apis_called": False,
                "github_mutation_performed": False,
                "railway_mutation_performed": False,
                "secrets_exposed": False,
            },
        )

        self.assertEqual(report["task_id"], created["task_id"])
        self.assertEqual(report["status"], "ready_to_report")
        self.assertEqual(report["changed_files_summary"], ("app/core/example.py",))
        self.assertFalse(report["external_apis_called"])
        self.assertFalse(report["github_mutation_performed"])
        self.assertFalse(report["railway_mutation_performed"])
        self.assertFalse(report["secrets_exposed"])

    def test_backend_rejects_unsafe_task_goals_and_scopes(self):
        unsafe_inputs = (
            {"user_goal": "Modify Railway variables for deployment"},
            {"user_goal": "Read production database rows"},
            {"user_goal": "Touch Gmail OAuth sessions"},
            {"user_goal": "Use Vinted session state"},
            {"user_goal": "Run browser automation against a real account"},
            {"user_goal": "Implement payment transfer logic"},
            {"user_goal": "Change approval bypass handling"},
            {"user_goal": "Disable safety gate checks"},
            {"user_goal": "Send buyer message"},
            {"user_goal": "Post listing and buy postage"},
        )
        for kwargs in unsafe_inputs:
            with self.subTest(goal=kwargs["user_goal"]):
                with self.assertRaises(ValueError):
                    codex_task_handoff.create_pending_codex_task(**kwargs)

    def test_backend_rejects_push_and_deploy_permissions(self):
        with self.assertRaisesRegex(ValueError, "deploy_blocked"):
            codex_task_handoff.create_pending_codex_task(
                user_goal="Add a harmless helper",
                can_deploy=True,
            )
        with self.assertRaisesRegex(ValueError, "push_branch_blocked"):
            codex_task_handoff.create_pending_codex_task(
                user_goal="Add a harmless helper",
                can_push_branch=True,
            )

    def test_backend_rejects_private_report_material(self):
        created = codex_task_handoff.create_pending_codex_task(
            user_goal="Add a harmless backend-only local helper with tests",
        )

        with self.assertRaises(ValueError):
            codex_task_handoff.ingest_codex_task_report(
                created["task_id"],
                {
                    "status": "ready_to_report",
                    "deployment_summary": "not_attempted",
                    "final_report": "Contains DATABASE_URL material",
                },
            )

    def test_backend_does_not_import_execution_or_external_api_modules(self):
        with open(codex_task_handoff.__file__, encoding="utf-8") as source_file:
            tree = ast.parse(source_file.read())

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")

        prohibited = {
            "subprocess",
            "openai",
            "requests",
            "httpx",
            "app.core.approval_lock",
            "app.core.user_notifications",
            "app.core.push_notifications",
        }
        self.assertTrue(prohibited.isdisjoint(imports))

    def test_backend_source_contains_no_mutation_calls(self):
        source = Path(codex_task_handoff.__file__).read_text(encoding="utf-8")
        for text in (
            "git push",
            "git commit",
            "railway up",
            "railway variables",
            "create_pending_approval_once",
            "send_user_notification",
            "send_push",
            "Popen",
            "check_call",
            "check_output",
        ):
            self.assertNotIn(text, source)

    def test_backend_runner_remains_disabled(self):
        self.assertEqual(
            codex_runner.DEFAULT_RUNNER_MODE,
            codex_runner.CodexRunnerMode.DISABLED,
        )


if __name__ == "__main__":
    unittest.main()
