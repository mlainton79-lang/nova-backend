import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class SummariseTests(unittest.TestCase):
    def test_fallback_summary_keeps_first_sentences(self):
        from app.core.summarise import summarise_text

        text = "First point matters. Second point matters too. Third point can wait."
        with mock.patch.dict(os.environ, {}, clear=True):
            result = asyncio.run(summarise_text(text, max_sentences=2))

        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "fallback")
        self.assertEqual(result["summary"], "First point matters. Second point matters too.")

    def test_empty_text_is_rejected_without_exception(self):
        from app.core.summarise import summarise_text

        result = asyncio.run(summarise_text("   "))

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "text is required")


if __name__ == "__main__":
    unittest.main()
