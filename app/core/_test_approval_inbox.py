#!/usr/bin/env python3
"""Structural tests for the read-only approval inbox."""

import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
import asyncio
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.modules.setdefault("psycopg2", MagicMock())

from fastapi import FastAPI
import httpx

from app.api.v1.endpoints.approvals import router as approvals_router  # noqa: E402
from app.core.security import verify_token  # noqa: E402
from app.core import approval_lock  # noqa: E402


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.cursor_instance = _Cursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


class ApprovalInboxTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(approvals_router, prefix="/api/v1")

    def _request(self, method: str, path: str):
        async def _run():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path)

        return asyncio.run(_run())

    def test_endpoint_is_protected(self):
        response = self._request("GET", "/api/v1/approvals/pending")
        self.assertEqual(response.status_code, 422)

    def test_helper_sanitizes_and_binds_limit(self):
        now = datetime.now(timezone.utc)
        rows = [
            (
                uuid.uuid4(),
                "capability.send_email",
                {
                    "step_summary": "Send the reviewed email",
                    "request_body": {"token": "secret-value", "content": "body"},
                    "headers": {"Authorization": "Bearer x"},
                    "nested": [{"api_key": "abc123"}],
                },
                now,
                now + timedelta(minutes=10),
                "awaiting",
            )
        ]
        connection = _Connection(rows)

        with patch.object(approval_lock, "_connect", return_value=connection):
            pending = approval_lock.list_active_pending_approvals(limit=999)

        self.assertEqual(len(connection.cursor_instance.statements), 1)
        _, params = connection.cursor_instance.statements[0]
        self.assertEqual(params, (20,))
        self.assertEqual(len(pending), 1)
        self.assertNotIn("approval_challenge", pending[0])
        self.assertNotIn("action_hash", pending[0])
        self.assertEqual(pending[0]["pending_id"], str(rows[0][0]))
        self.assertEqual(pending[0]["status"], "awaiting")
        self.assertEqual(
            pending[0]["action_snapshot"]["request_body"],
            "[REDACTED]",
        )
        self.assertEqual(
            pending[0]["action_snapshot"]["headers"],
            "[REDACTED]",
        )
        self.assertEqual(
            pending[0]["action_snapshot"]["nested"][0]["api_key"],
            "[REDACTED]",
        )

    def test_endpoint_returns_sanitized_items(self):
        now = datetime.now(timezone.utc)
        pending_rows = [
            {
                "pending_id": str(uuid.uuid4()),
                "capability_key": "capability.send_email",
                "action_snapshot": {"step_summary": "Approve send", "request_body": "[REDACTED]"},
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
                "status": "awaiting",
            }
        ]
        self.app.dependency_overrides[verify_token] = lambda: True
        with patch(
            "app.api.v1.endpoints.approvals.list_active_pending_approvals",
            return_value=pending_rows,
        ):
            response = self._request("GET", "/api/v1/approvals/pending")
        self.app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["pending_approvals"], pending_rows)


if __name__ == "__main__":
    unittest.main()
