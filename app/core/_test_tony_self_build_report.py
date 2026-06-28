#!/usr/bin/env python3
"""Tests for safe Tony self-build rehearsal reporting."""

import ast
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core import tony_self_build_report  # noqa: E402


class TonySelfBuildReportTests(unittest.TestCase):
    def _safe_runner_report(self):
        return {
            "changed_files_summary": (
                "app/core/tony_self_build_report.py",
                "app/core/_test_tony_self_build_report.py",
            ),
            "tests_summary": (
                "python -m unittest app.core._test_tony_self_build_report passed",
            ),
            "deployment_summary": "not_attempted",
            "codex_unsandboxed_requested": True,
            "codex_unsandboxed_allowed": True,
            "codex_unsandboxed_used": True,
            "unsafe_changed_files_detected": False,
            "codex_task_completed_successfully": True,
            "external_apis_called": False,
            "github_mutation_performed": False,
            "railway_mutation_performed": False,
            "secrets_exposed": False,
            "final_report": "Local rehearsal completed with safe summaries.",
        }

    def test_completed_unsandboxed_phone_rehearsal_report_is_safe(self):
        report = tony_self_build_report.build_unsandboxed_phone_rehearsal_report(
            self._safe_runner_report()
        )

        self.assertEqual(report.status, "completed")
        self.assertTrue(report.completed)
        self.assertTrue(report.unsandboxed_requested)
        self.assertTrue(report.unsandboxed_allowed)
        self.assertTrue(report.unsandboxed_used)
        self.assertTrue(report.changed_files_validated)
        self.assertEqual(report.deployment_summary, "not_attempted")
        self.assertEqual(report.needs_attention, ())
        self.assertEqual(
            report.changed_files_summary,
            (
                "app/core/tony_self_build_report.py",
                "app/core/_test_tony_self_build_report.py",
            ),
        )

    def test_report_dict_uses_safe_metadata_only(self):
        data = tony_self_build_report.build_unsandboxed_phone_rehearsal_report(
            self._safe_runner_report()
        ).as_dict()

        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["deployment_summary"], "not_attempted")
        self.assertNotIn("stdout", data)
        self.assertNotIn("stderr", data)
        self.assertNotIn("authorization", str(data).lower())

    def test_refused_unsandboxed_rehearsal_needs_attention(self):
        runner_report = self._safe_runner_report()
        runner_report["codex_unsandboxed_allowed"] = False
        runner_report["codex_unsandboxed_used"] = False
        runner_report["codex_task_completed_successfully"] = False

        report = tony_self_build_report.build_unsandboxed_phone_rehearsal_report(
            runner_report
        )

        self.assertEqual(report.status, "needs_attention")
        self.assertFalse(report.completed)
        self.assertIn("refused", " ".join(report.needs_attention))

    def test_rejects_changed_files_outside_app_core(self):
        runner_report = self._safe_runner_report()
        runner_report["changed_files_summary"] = ("tools/tony_codex_local_runner.py",)

        with self.assertRaisesRegex(ValueError, "outside_backend_core_scope"):
            tony_self_build_report.build_unsandboxed_phone_rehearsal_report(
                runner_report
            )

    def test_rejects_unsafe_changed_file_paths(self):
        runner_report = self._safe_runner_report()
        runner_report["changed_files_summary"] = ("app/core/../secret.py",)

        with self.assertRaisesRegex(ValueError, "unsafe_path"):
            tony_self_build_report.build_unsandboxed_phone_rehearsal_report(
                runner_report
            )

    def test_rejects_private_material_in_report_fields(self):
        runner_report = self._safe_runner_report()
        runner_report["final_report"] = "Contains DATABASE_URL material"

        with self.assertRaisesRegex(ValueError, "private_material"):
            tony_self_build_report.build_unsandboxed_phone_rehearsal_report(
                runner_report
            )

    def test_rejects_external_mutation_flags(self):
        for flag in (
            "external_apis_called",
            "github_mutation_performed",
            "railway_mutation_performed",
            "secrets_exposed",
        ):
            with self.subTest(flag=flag):
                runner_report = self._safe_runner_report()
                runner_report[flag] = True
                with self.assertRaisesRegex(ValueError, "unsafe_self_build"):
                    tony_self_build_report.build_unsandboxed_phone_rehearsal_report(
                        runner_report
                    )

    def test_helper_imports_no_execution_or_external_api_modules(self):
        with open(tony_self_build_report.__file__, encoding="utf-8") as source_file:
            tree = ast.parse(source_file.read())

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")

        self.assertEqual(imports, {"__future__", "dataclasses", "typing"})

    def test_helper_source_contains_no_mutation_calls(self):
        source = Path(tony_self_build_report.__file__).read_text(encoding="utf-8")
        for text in (
            "subprocess",
            "os.system",
            "httpx",
            "requests",
            "railway up",
            "railway variables",
            "git push",
            "git commit",
            "create_pending_approval_once",
            "send_user_notification",
            "send_push",
        ):
            self.assertNotIn(text, source)


if __name__ == "__main__":
    unittest.main()
