#!/usr/bin/env python3
"""Tests for protected Codex task handoff endpoint handlers."""

import asyncio
import os
import sys
import unittest
from pathlib import Path

from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from app.api.v1.endpoints import codex_tasks  # noqa: E402
from app.core import codex_task_handoff  # noqa: E402


class CodexTaskEndpointTests(unittest.TestCase):
    def setUp(self):
        codex_task_handoff.reset_codex_handoff_store_for_tests()

    def test_endpoint_creates_pending_codex_task(self):
        response = asyncio.run(
            codex_tasks.create_codex_task_plan_endpoint(
                codex_tasks.CodexTaskPlanRequest(
                    user_goal="Add a harmless backend-only local helper with tests",
                    tool_or_area="nova-backend local helpers",
                )
            )
        )

        self.assertTrue(response["ok"])
        self.assertTrue(response["created"])
        self.assertTrue(response["task"]["task_id"].startswith("codex-"))
        self.assertEqual(response["task"]["handoff_status"], "pending")
        self.assertFalse(response["task"]["can_deploy"])
        self.assertFalse(response["task"]["can_push_branch"])

    def test_endpoint_next_returns_safe_plan(self):
        created = codex_task_handoff.create_pending_codex_task(
            user_goal="Add a harmless backend-only local helper with tests",
        )

        response = asyncio.run(codex_tasks.get_next_codex_task_endpoint())

        self.assertTrue(response["ok"])
        self.assertTrue(response["found"])
        self.assertEqual(response["task"]["task_id"], created["task_id"])
        self.assertEqual(response["task"]["handoff_status"], "fetched")

    def test_endpoint_accepts_sanitized_report(self):
        created = codex_task_handoff.create_pending_codex_task(
            user_goal="Add a harmless backend-only local helper with tests",
        )
        codex_task_handoff.get_next_pending_codex_task()

        response = asyncio.run(
            codex_tasks.report_codex_task_endpoint(
                created["task_id"],
                codex_tasks.CodexTaskReportRequest(
                    status="ready_to_report",
                    changed_files_summary=["app/core/example.py"],
                    tests_summary=["targeted unittest passed"],
                    deployment_summary="not_attempted",
                    final_report="Prompt-only handoff report received.",
                ),
            )
        )

        self.assertTrue(response["ok"])
        self.assertTrue(response["accepted"])
        self.assertEqual(response["report"]["task_id"], created["task_id"])
        self.assertFalse(response["report"]["external_apis_called"])
        self.assertFalse(response["report"]["github_mutation_performed"])
        self.assertFalse(response["report"]["railway_mutation_performed"])
        self.assertFalse(response["report"]["secrets_exposed"])

    def test_endpoint_rejects_unsafe_goal(self):
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                codex_tasks.create_codex_task_plan_endpoint(
                    codex_tasks.CodexTaskPlanRequest(
                        user_goal="Touch Gmail OAuth sessions",
                    )
                )
            )

        self.assertEqual(raised.exception.status_code, 400)

    def test_endpoint_rejects_unsafe_report(self):
        created = codex_task_handoff.create_pending_codex_task(
            user_goal="Add a harmless backend-only local helper with tests",
        )

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                codex_tasks.report_codex_task_endpoint(
                    created["task_id"],
                    codex_tasks.CodexTaskReportRequest(
                        final_report="Contains DATABASE_URL material",
                    ),
                )
            )

        self.assertEqual(raised.exception.status_code, 400)

    def test_endpoint_uses_existing_auth_dependency(self):
        source = Path(codex_tasks.__file__).read_text(encoding="utf-8")

        self.assertIn("verify_token", source)
        self.assertIn("Depends(verify_token)", source)

    def test_endpoint_source_contains_no_external_mutation_calls(self):
        source = Path(codex_tasks.__file__).read_text(encoding="utf-8")
        for text in (
            "subprocess",
            "openai",
            "requests",
            "httpx",
            "git push",
            "railway up",
            "create_pending_approval_once",
            "send_user_notification",
        ):
            self.assertNotIn(text, source)


if __name__ == "__main__":
    unittest.main()
