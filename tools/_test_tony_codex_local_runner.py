#!/usr/bin/env python3
"""Tests for the local-only Tony Codex bridge."""

import ast
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core import codex_runner, codex_tasks  # noqa: E402

RUNNER_PATH = REPO_ROOT / "tools" / "tony_codex_local_runner.py"
spec = importlib.util.spec_from_file_location("tony_codex_local_runner", RUNNER_PATH)
tony_codex_local_runner = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(tony_codex_local_runner)


class TonyCodexLocalRunnerTests(unittest.TestCase):
    def _plan(self):
        return codex_tasks.mark_codex_task_ready(
            codex_tasks.create_codex_task_plan(
                "Add a backend-only helper with focused tests",
                tool_or_area="nova-backend local tooling",
                can_deploy=False,
                can_push_branch=False,
            )
        )

    def _write_plan_json(self, plan):
        data = {
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
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        with handle:
            json.dump(data, handle)
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def _plan_json_dict(self, plan):
        return json.loads(Path(self._write_plan_json(plan)).read_text(encoding="utf-8"))

    class _FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def test_prompt_only_is_default_mode(self):
        parser = tony_codex_local_runner.build_parser()
        args = parser.parse_args([])

        self.assertEqual(args.mode, "prompt-only")

    def test_local_bridge_can_load_codex_task_plan(self):
        plan = self._plan()
        path = self._write_plan_json(plan)

        loaded = tony_codex_local_runner.load_codex_task_plan(path)

        self.assertEqual(loaded.task_id, plan.task_id)
        self.assertEqual(loaded.user_goal, plan.user_goal)
        self.assertEqual(loaded.status, codex_tasks.CodexTaskStatus.READY_FOR_CODEX)

    def test_prompt_only_generates_safe_prompt_without_subprocess(self):
        plan = self._plan()
        with patch.object(
            tony_codex_local_runner.subprocess,
            "run",
            side_effect=AssertionError("subprocess must not run in prompt-only"),
        ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            report = tony_codex_local_runner.run_prompt_only(plan, write_prompt=False)

        self.assertIn("Tony-managed Codex task", stdout.getvalue())
        self.assertFalse(report["execution_attempted"])
        self.assertFalse(report["execution_allowed"])
        self.assertEqual(report["tests_summary"], ("prompt_generated",))
        self.assertFalse(report["secrets_exposed"])

    def test_dry_run_does_not_invoke_subprocess(self):
        plan = self._plan()
        with patch.object(
            tony_codex_local_runner.subprocess,
            "run",
            side_effect=AssertionError("subprocess must not run in dry-run"),
        ):
            report = tony_codex_local_runner.run_dry_run(plan)

        self.assertFalse(report["execution_attempted"])
        self.assertFalse(report["execution_allowed"])
        self.assertEqual(report["tests_summary"], ("dry_run_no_execution",))

    def test_local_codex_cli_refuses_without_env_var(self):
        plan = self._plan()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            tony_codex_local_runner.subprocess,
            "run",
            side_effect=AssertionError("Codex must not run without env flag"),
        ):
            report = tony_codex_local_runner.run_local_codex_cli(
                plan,
                confirm_execution=True,
                allow_dirty=True,
                allow_main_branch=True,
                codex_bin="codex",
            )

        self.assertFalse(report["execution_attempted"])
        self.assertIn("execution_env_not_enabled", report["final_report"])

    def test_local_codex_cli_refuses_without_confirmation_flag(self):
        plan = self._plan()
        with patch.dict(
            os.environ,
            {tony_codex_local_runner.ALLOW_EXECUTION_ENV: "1"},
            clear=True,
        ), patch.object(
            tony_codex_local_runner.subprocess,
            "run",
            side_effect=AssertionError("Codex must not run without CLI confirmation"),
        ):
            report = tony_codex_local_runner.run_local_codex_cli(
                plan,
                confirm_execution=False,
                allow_dirty=True,
                allow_main_branch=True,
                codex_bin="codex",
            )

        self.assertFalse(report["execution_attempted"])
        self.assertIn("missing_explicit_local_execution_flag", report["final_report"])

    def test_local_codex_cli_refuses_when_can_deploy_true(self):
        plan = replace(self._plan(), can_deploy=True)
        with patch.dict(
            os.environ,
            {tony_codex_local_runner.ALLOW_EXECUTION_ENV: "1"},
            clear=True,
        ):
            report = tony_codex_local_runner.run_local_codex_cli(
                plan,
                confirm_execution=True,
                allow_dirty=True,
                allow_main_branch=True,
                codex_bin="codex",
            )

        self.assertFalse(report["execution_attempted"])
        self.assertIn("task_can_deploy_blocked", report["final_report"])

    def test_local_codex_cli_refuses_when_can_push_branch_true(self):
        plan = replace(self._plan(), can_push_branch=True)
        with patch.dict(
            os.environ,
            {tony_codex_local_runner.ALLOW_EXECUTION_ENV: "1"},
            clear=True,
        ):
            report = tony_codex_local_runner.run_local_codex_cli(
                plan,
                confirm_execution=True,
                allow_dirty=True,
                allow_main_branch=True,
                codex_bin="codex",
            )

        self.assertFalse(report["execution_attempted"])
        self.assertIn("task_can_push_branch_blocked", report["final_report"])

    def test_local_codex_cli_refuses_when_can_commit_true(self):
        plan = replace(self._plan(), can_commit=True)
        with patch.dict(
            os.environ,
            {tony_codex_local_runner.ALLOW_EXECUTION_ENV: "1"},
            clear=True,
        ):
            report = tony_codex_local_runner.run_local_codex_cli(
                plan,
                confirm_execution=True,
                allow_dirty=True,
                allow_main_branch=True,
                codex_bin="codex",
            )

        self.assertFalse(report["execution_attempted"])
        self.assertIn("task_can_commit_blocked", report["final_report"])

    def test_local_codex_cli_refuses_when_can_run_tests_false(self):
        plan = replace(self._plan(), can_run_tests=False)
        with patch.dict(
            os.environ,
            {tony_codex_local_runner.ALLOW_EXECUTION_ENV: "1"},
            clear=True,
        ):
            report = tony_codex_local_runner.run_local_codex_cli(
                plan,
                confirm_execution=True,
                allow_dirty=True,
                allow_main_branch=True,
                codex_bin="codex",
            )

        self.assertFalse(report["execution_attempted"])
        self.assertIn("task_cannot_run_tests", report["final_report"])

    def test_local_codex_cli_refuses_dangerous_scope(self):
        plan = replace(
            self._plan(),
            allowed_files_or_areas=("touch Gmail OAuth sessions",),
        )
        with patch.dict(
            os.environ,
            {tony_codex_local_runner.ALLOW_EXECUTION_ENV: "1"},
            clear=True,
        ):
            report = tony_codex_local_runner.run_local_codex_cli(
                plan,
                confirm_execution=True,
                allow_dirty=True,
                allow_main_branch=True,
                codex_bin="codex",
            )

        self.assertFalse(report["execution_attempted"])
        self.assertIn("dangerous_scope:gmail oauth", report["final_report"])

    def test_local_codex_cli_refuses_main_branch_by_default(self):
        plan = self._plan()
        with patch.dict(
            os.environ,
            {tony_codex_local_runner.ALLOW_EXECUTION_ENV: "1"},
            clear=True,
        ), patch.object(tony_codex_local_runner, "current_branch", return_value="main"), patch.object(
            tony_codex_local_runner,
            "working_tree_is_clean",
            return_value=True,
        ), patch.object(
            tony_codex_local_runner.subprocess,
            "run",
            side_effect=AssertionError("Codex must not run on main by default"),
        ):
            report = tony_codex_local_runner.run_local_codex_cli(
                plan,
                confirm_execution=True,
                allow_dirty=True,
                allow_main_branch=False,
                codex_bin="codex",
            )

        self.assertFalse(report["execution_attempted"])
        self.assertIn("main_branch_refused", report["final_report"])

    def test_local_codex_cli_refuses_master_branch_by_default(self):
        plan = self._plan()
        with patch.dict(
            os.environ,
            {tony_codex_local_runner.ALLOW_EXECUTION_ENV: "1"},
            clear=True,
        ), patch.object(tony_codex_local_runner, "current_branch", return_value="master"), patch.object(
            tony_codex_local_runner,
            "working_tree_is_clean",
            return_value=True,
        ), patch.object(
            tony_codex_local_runner.subprocess,
            "run",
            side_effect=AssertionError("Codex must not run on master by default"),
        ):
            report = tony_codex_local_runner.run_local_codex_cli(
                plan,
                confirm_execution=True,
                allow_dirty=True,
                allow_main_branch=False,
                codex_bin="codex",
            )

        self.assertFalse(report["execution_attempted"])
        self.assertIn("master_branch_refused", report["final_report"])

    def test_local_codex_cli_refuses_dirty_tree_by_default(self):
        plan = self._plan()
        with patch.dict(
            os.environ,
            {tony_codex_local_runner.ALLOW_EXECUTION_ENV: "1"},
            clear=True,
        ), patch.object(tony_codex_local_runner, "current_branch", return_value="feature"), patch.object(
            tony_codex_local_runner,
            "working_tree_is_clean",
            return_value=False,
        ), patch.object(
            tony_codex_local_runner.subprocess,
            "run",
            side_effect=AssertionError("Codex must not run on dirty tree by default"),
        ):
            report = tony_codex_local_runner.run_local_codex_cli(
                plan,
                confirm_execution=True,
                allow_dirty=False,
                allow_main_branch=True,
                codex_bin="codex",
            )

        self.assertFalse(report["execution_attempted"])
        self.assertIn("dirty_tree_refused", report["final_report"])

    def test_local_codex_cli_refuses_non_backend_local_scope(self):
        plan = replace(
            self._plan(),
            user_goal="Add a harmless note helper",
            tool_or_area="general desktop helper",
            intended_change_summary="Prepare a local note helper",
            allowed_files_or_areas=("notes only",),
        )
        with patch.dict(
            os.environ,
            {tony_codex_local_runner.ALLOW_EXECUTION_ENV: "1"},
            clear=True,
        ):
            report = tony_codex_local_runner.run_local_codex_cli(
                plan,
                confirm_execution=True,
                allow_dirty=True,
                allow_main_branch=True,
                codex_bin="codex",
            )

        self.assertFalse(report["execution_attempted"])
        self.assertIn("not_backend_local_scope", report["final_report"])

    def test_refusal_report_is_written_by_cli_main(self):
        plan = self._plan()
        plan_path = self._write_plan_json(plan)
        report_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        report_file.close()
        self.addCleanup(lambda: os.path.exists(report_file.name) and os.unlink(report_file.name))

        with patch.dict(os.environ, {}, clear=True), patch.object(
            tony_codex_local_runner.subprocess,
            "run",
            side_effect=AssertionError("Codex must not run for refused task"),
        ), patch("sys.stdout", new_callable=io.StringIO):
            exit_code = tony_codex_local_runner.main(
                [
                    "--plan",
                    plan_path,
                    "--mode",
                    "local-codex-cli",
                    "--report",
                    report_file.name,
                ]
            )

        report = json.loads(Path(report_file.name).read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["mode"], "local-codex-cli")
        self.assertFalse(report["execution_attempted"])
        self.assertFalse(report["execution_allowed"])
        self.assertIn("execution_env_not_enabled", report["final_report"])

    def test_local_codex_cli_allowed_path_is_mocked_only(self):
        plan = self._plan()
        calls = []

        def fake_codex_run(args, input, cwd, text, capture_output, check):
            calls.append(
                {
                    "args": args,
                    "input_present": bool(input),
                    "cwd": str(cwd),
                    "text": text,
                    "capture_output": capture_output,
                    "check": check,
                }
            )
            return tony_codex_local_runner.subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="safe mocked codex output",
                stderr="",
            )

        with patch.dict(
            os.environ,
            {tony_codex_local_runner.ALLOW_EXECUTION_ENV: "1"},
            clear=True,
        ), patch.object(tony_codex_local_runner, "current_branch", return_value="feature/codex-task"), patch.object(
            tony_codex_local_runner,
            "working_tree_is_clean",
            return_value=True,
        ), patch.object(
            tony_codex_local_runner,
            "changed_files_summary",
            return_value=("tools/example.py",),
        ), patch.object(
            tony_codex_local_runner.subprocess,
            "run",
            side_effect=fake_codex_run,
        ):
            report = tony_codex_local_runner.run_local_codex_cli(
                plan,
                confirm_execution=True,
                allow_dirty=False,
                allow_main_branch=False,
                codex_bin="codex",
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["args"], ["codex"])
        self.assertTrue(calls[0]["input_present"])
        self.assertTrue(calls[0]["capture_output"])
        self.assertFalse(calls[0]["check"])
        self.assertTrue(report["execution_attempted"])
        self.assertTrue(report["execution_allowed"])
        self.assertEqual(report["return_code"], 0)
        self.assertEqual(report["deployment_summary"], "not_attempted")
        self.assertFalse(report["secrets_exposed"])
        self.assertEqual(report["changed_files_summary"], ("tools/example.py",))

    def test_report_json_is_sanitized(self):
        plan = self._plan()
        report = tony_codex_local_runner.build_report(
            plan=plan,
            mode="dry-run",
            execution_attempted=False,
            execution_allowed=False,
            final_report="DATABASE_URL material must not appear",
        )

        encoded = json.dumps(report).lower()
        self.assertIn("[redacted unsafe output]", encoded)
        self.assertNotIn("database_url material", encoded)
        self.assertFalse(report["secrets_exposed"])

    def test_local_runner_can_fetch_mocked_plan_without_printing_token(self):
        plan = self._plan()
        payload = {"ok": True, "found": True, "task": self._plan_json_dict(plan)}
        captured_requests = []

        def fake_urlopen(request, timeout):
            captured_requests.append(request)
            return self._FakeResponse(payload)

        with patch.dict(os.environ, {"DEV_TOKEN": "test-token-value"}, clear=True), patch.object(
            tony_codex_local_runner.urllib.request,
            "urlopen",
            side_effect=fake_urlopen,
        ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            fetched = tony_codex_local_runner.fetch_task_from_nova(
                "https://nova.example",
                "DEV_TOKEN",
            )

        self.assertEqual(fetched.task_id, plan.task_id)
        self.assertEqual(captured_requests[0].full_url, "https://nova.example/api/v1/codex-tasks/next")
        self.assertEqual(stdout.getvalue(), "")

    def test_local_runner_can_post_mocked_sanitized_report(self):
        plan = self._plan()
        captured_bodies = []

        def fake_urlopen(request, timeout):
            captured_bodies.append(json.loads(request.data.decode("utf-8")))
            return self._FakeResponse({"ok": True, "accepted": True})

        report = tony_codex_local_runner.build_report(
            plan=plan,
            mode="prompt-only",
            execution_attempted=False,
            execution_allowed=False,
            final_report="Prompt-only report prepared.",
            tests_summary=("prompt_generated",),
        )
        with patch.dict(os.environ, {"DEV_TOKEN": "test-token-value"}, clear=True), patch.object(
            tony_codex_local_runner.urllib.request,
            "urlopen",
            side_effect=fake_urlopen,
        ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            response = tony_codex_local_runner.post_report_to_nova(
                "https://nova.example",
                "DEV_TOKEN",
                plan.task_id,
                report,
            )

        self.assertTrue(response["ok"])
        self.assertEqual(captured_bodies[0]["status"], "ready_to_report")
        self.assertFalse(captured_bodies[0]["codex_execution_invoked"])
        self.assertFalse(captured_bodies[0]["external_apis_called"])
        self.assertFalse(captured_bodies[0]["github_mutation_performed"])
        self.assertFalse(captured_bodies[0]["railway_mutation_performed"])
        self.assertEqual(stdout.getvalue(), "")

    def test_fetch_prompt_only_report_to_nova_uses_mocked_network_and_no_codex(self):
        plan = self._plan()
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            if request.get_method() == "GET":
                return self._FakeResponse(
                    {"ok": True, "found": True, "task": self._plan_json_dict(plan)}
                )
            return self._FakeResponse({"ok": True, "accepted": True})

        args = tony_codex_local_runner.build_parser().parse_args(
            [
                "--fetch-from-nova",
                "--report-to-nova",
                "--nova-base-url",
                "https://nova.example",
                "--mode",
                "prompt-only",
                "--write-prompt",
            ]
        )
        with patch.dict(os.environ, {"DEV_TOKEN": "test-token-value"}, clear=True), patch.object(
            tony_codex_local_runner.urllib.request,
            "urlopen",
            side_effect=fake_urlopen,
        ), patch.object(
            tony_codex_local_runner.subprocess,
            "run",
            side_effect=AssertionError("Codex must not run in prompt-only"),
        ):
            report = tony_codex_local_runner.run_bridge(args)

        self.assertEqual(len(calls), 2)
        self.assertTrue(report["nova_report_posted"])
        self.assertFalse(report["execution_attempted"])
        self.assertEqual(report["mode"], "prompt-only")

    def test_backend_runner_remains_disabled_by_default(self):
        self.assertEqual(
            codex_runner.DEFAULT_RUNNER_MODE,
            codex_runner.CodexRunnerMode.DISABLED,
        )

    def test_subprocess_is_limited_to_local_tool_not_backend_runner(self):
        with open(codex_runner.__file__, encoding="utf-8") as source_file:
            backend_source = source_file.read()
        with open(RUNNER_PATH, encoding="utf-8") as source_file:
            local_source = source_file.read()

        self.assertNotIn("subprocess", backend_source)
        self.assertIn("import subprocess", local_source)

    def test_local_runner_imports_no_openai_http_or_railway_modules(self):
        with open(RUNNER_PATH, encoding="utf-8") as source_file:
            tree = ast.parse(source_file.read())

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")

        self.assertTrue({"openai", "requests", "httpx", "railway"}.isdisjoint(imports))


if __name__ == "__main__":
    unittest.main()
