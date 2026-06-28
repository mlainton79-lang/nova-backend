#!/usr/bin/env python3
"""Prompt-only handoff rehearsal tests for Tony Codex tasks."""

import importlib.util
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core import codex_runner  # noqa: E402


def _load_tool_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


create_example_plan = _load_tool_module(
    "create_tony_codex_example_plan",
    REPO_ROOT / "tools" / "create_tony_codex_example_plan.py",
)
local_runner = _load_tool_module(
    "tony_codex_local_runner",
    REPO_ROOT / "tools" / "tony_codex_local_runner.py",
)


class TonyCodexHandoffRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.output_dir = REPO_ROOT / ".tony_codex"
        self.plan_path = self.output_dir / "example-plan.json"
        if self.plan_path.exists():
            self.plan_path.unlink()
        for path in self.output_dir.glob("codex-*-prompt.txt"):
            path.unlink()
        for path in self.output_dir.glob("codex-*-report.json"):
            path.unlink()

    def test_example_plan_script_exists(self):
        self.assertTrue((REPO_ROOT / "tools" / "create_tony_codex_example_plan.py").exists())

    def test_example_plan_written_and_has_safe_shape(self):
        plan, path = create_example_plan.write_example_plan()

        self.assertEqual(path, self.plan_path)
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["task_id"], plan.task_id)
        self.assertEqual(data["tool_or_area"], "nova-backend local helper rehearsal")
        self.assertEqual(data["status"], "planned")
        self.assertTrue(data["can_edit_code"])
        self.assertTrue(data["can_run_tests"])
        self.assertFalse(data["can_commit"])
        self.assertFalse(data["can_push_branch"])
        self.assertFalse(data["can_deploy"])
        self.assertTrue(data["requires_matthew_approval_before_deploy"])

        plan_text = json.dumps(data).lower()
        prohibited_plan_terms = (
            "railway variable",
            "production database row",
            "gmail",
            "vinted",
            "browser automation",
            "approval bypass",
            "payment",
            "order",
            "postage",
            "buyer message",
        )
        for term in prohibited_plan_terms:
            self.assertNotIn(term, plan_text)

    def test_generated_plan_loads_in_local_bridge(self):
        plan, path = create_example_plan.write_example_plan()

        loaded = local_runner.load_codex_task_plan(str(path))

        self.assertEqual(loaded.task_id, plan.task_id)
        self.assertEqual(loaded.user_goal, plan.user_goal)
        self.assertFalse(loaded.can_deploy)
        self.assertFalse(loaded.can_push_branch)

    def test_prompt_only_handoff_creates_prompt_and_report_without_subprocess(self):
        plan, path = create_example_plan.write_example_plan()
        argv = ["--plan", str(path), "--mode", "prompt-only", "--write-prompt"]

        with patch.object(
            local_runner.subprocess,
            "run",
            side_effect=AssertionError("prompt-only rehearsal must not use subprocess"),
        ), patch.object(
            local_runner,
            "run_local_codex_cli",
            side_effect=AssertionError("local-codex-cli must not be used"),
        ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            exit_code = local_runner.main(argv)

        self.assertEqual(exit_code, 0)
        output = json.loads(stdout.getvalue())
        report_path = REPO_ROOT / output["report_path"]
        prompt_path = self.output_dir / f"{plan.task_id}-prompt.txt"

        self.assertTrue(prompt_path.exists())
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["task_id"], plan.task_id)
        self.assertEqual(report["mode"], "prompt-only")
        self.assertFalse(report["execution_attempted"])
        self.assertFalse(report["execution_allowed"])
        self.assertFalse(report["secrets_exposed"])
        self.assertEqual(report["prompt_path"], f".tony_codex/{plan.task_id}-prompt.txt")

        prompt_text = prompt_path.read_text(encoding="utf-8")
        self.assertIn("Tony-managed Codex task", prompt_text)
        self.assertIn("can_deploy: False", prompt_text)

    def test_backend_runner_remains_disabled(self):
        self.assertEqual(
            codex_runner.DEFAULT_RUNNER_MODE,
            codex_runner.CodexRunnerMode.DISABLED,
        )

    def test_no_openai_api_github_or_railway_mutation_imports(self):
        for path in (
            REPO_ROOT / "tools" / "create_tony_codex_example_plan.py",
            REPO_ROOT / "tools" / "tony_codex_local_runner.py",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("import openai", source)
            self.assertNotIn("import requests", source)
            self.assertNotIn("import httpx", source)
            self.assertNotIn("railway up", source)
            self.assertNotIn('["git", "push"', source)
            self.assertNotIn("create_pending_approval_once", source)
            self.assertNotIn("send_user_notification", source)

    def test_no_backend_subprocess_import_added_by_rehearsal(self):
        codex_runner_source = Path(codex_runner.__file__).read_text(encoding="utf-8")

        self.assertNotIn("subprocess", codex_runner_source)


if __name__ == "__main__":
    unittest.main()
