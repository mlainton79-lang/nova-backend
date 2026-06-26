#!/usr/bin/env python3
"""Structural checks for Approved Task Runner Adapter v1."""

import ast
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.modules.setdefault("psycopg2", MagicMock())

from app.core import approved_task_runner  # noqa: E402
from app.core import approval_lock  # noqa: E402


class ApprovedTaskRunnerTests(unittest.TestCase):
    def test_runner_is_fixed_to_harmless_test_contract(self):
        consume = MagicMock(return_value=True)
        with patch.object(
            approved_task_runner,
            "consume_test_approval_resume_grant",
            consume,
        ):
            result = approved_task_runner.run_harmless_test_approval_resume()

        consume.assert_called_once_with()
        self.assertEqual(
            approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
            "test.approval_resume",
        )
        self.assertEqual(
            result.task_type,
            approved_task_runner.HARMLESS_RESUME_TASK_TYPE,
        )
        self.assertTrue(result.resumed)
        self.assertEqual(result.safe_status, "completed")
        self.assertEqual(
            result.safe_message,
            approved_task_runner.HARMLESS_RESUME_COMPLETED_MESSAGE,
        )
        self.assertFalse(result.external_action_performed)
        self.assertFalse(result.notification_sent)

    def test_runner_returns_not_resumed_without_eligible_grant(self):
        consume = MagicMock(return_value=False)
        with patch.object(
            approved_task_runner,
            "consume_test_approval_resume_grant",
            consume,
        ):
            result = approved_task_runner.run_harmless_test_approval_resume()

        consume.assert_called_once_with()
        self.assertFalse(result.resumed)
        self.assertEqual(result.safe_status, "not_resumed")
        self.assertEqual(
            result.safe_message,
            approved_task_runner.HARMLESS_RESUME_NOT_RESUMED_MESSAGE,
        )
        self.assertFalse(result.external_action_performed)
        self.assertFalse(result.notification_sent)

    def test_second_consume_cannot_produce_second_completed_result(self):
        consume = MagicMock(side_effect=[True, False])
        with patch.object(
            approved_task_runner,
            "consume_test_approval_resume_grant",
            consume,
        ):
            first = approved_task_runner.run_harmless_test_approval_resume()
            second = approved_task_runner.run_harmless_test_approval_resume()

        self.assertTrue(first.resumed)
        self.assertFalse(second.resumed)
        self.assertEqual(second.safe_status, "not_resumed")
        self.assertEqual(consume.call_count, 2)

    def test_runner_module_has_no_external_or_notification_dependencies(self):
        with open(approved_task_runner.__file__, encoding="utf-8") as source_file:
            source = source_file.read()

        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)

        prohibited = {
            "httpx",
            "requests",
            "selenium",
            "playwright",
            "app.core.user_notifications",
            "app.core.push_notifications",
            "app.core.gmail_service",
            "app.core.ebay_oauth",
        }
        self.assertTrue(prohibited.isdisjoint(imports))


if __name__ == "__main__":
    unittest.main()
