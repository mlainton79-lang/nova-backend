import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class CaptureTests(unittest.TestCase):
    def test_capture_note_saves_low_risk_text_to_semantic_memory(self):
        from app.core import capture

        calls = []

        async def fake_add_semantic_memory(category, text, importance=1.0):
            calls.append((category, text, importance))
            return True

        fake_semantic = types.ModuleType("app.core.semantic_memory")
        fake_semantic.add_semantic_memory = fake_add_semantic_memory

        with mock.patch.dict(sys.modules, {"app.core.semantic_memory": fake_semantic}):
            result = asyncio.run(capture.capture_note(
                "  Remember that the blue folder is for nursery forms.  ",
                category="daily_capture",
            ))

        self.assertTrue(result["ok"])
        self.assertTrue(result["saved"])
        self.assertEqual(result["status"], "saved")
        self.assertEqual(
            calls,
            [("daily_capture", "Remember that the blue folder is for nursery forms.", 1.0)],
        )

    def test_capture_note_rejects_empty_long_and_secretish_text(self):
        from app.core.capture import capture_note

        self.assertEqual(asyncio.run(capture_note(""))["status"], "empty")
        self.assertEqual(asyncio.run(capture_note("x" * 2001))["status"], "too_long")
        self.assertEqual(
            asyncio.run(capture_note("my api key is abc123"))["status"],
            "rejected_sensitive",
        )

    def test_capture_note_reports_store_errors_without_raising(self):
        from app.core import capture

        async def fake_add_semantic_memory(*_args, **_kwargs):
            raise RuntimeError("database unavailable")

        fake_semantic = types.ModuleType("app.core.semantic_memory")
        fake_semantic.add_semantic_memory = fake_add_semantic_memory

        with mock.patch.dict(sys.modules, {"app.core.semantic_memory": fake_semantic}):
            result = asyncio.run(capture.capture_note("Buy printer paper"))

        self.assertFalse(result["ok"])
        self.assertFalse(result["saved"])
        self.assertEqual(result["status"], "error")
        self.assertIn("RuntimeError", result["error"])


if __name__ == "__main__":
    unittest.main()
