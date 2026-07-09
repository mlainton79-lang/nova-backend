import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class MemoryQualityTests(unittest.TestCase):
    def test_score_retrieval_result_passes_when_expected_text_is_found(self):
        from app.core.memory_quality import score_retrieval_result

        result = score_retrieval_result(
            "The blue folder is for nursery forms.",
            [{"id": 7, "text": "The blue folder is for nursery forms."}],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["matched"], {"rank": 1, "id": 7})
        self.assertEqual(result["status"], "pass")

    def test_score_retrieval_result_fails_when_missing(self):
        from app.core.memory_quality import score_retrieval_result

        result = score_retrieval_result("printer paper", [{"text": "milk"}])

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "not_found")

    def test_capture_retrieval_eval_uses_capture_and_search(self):
        from app.core import memory_quality

        async def fake_capture_note(text, category="capture"):
            return {"ok": True, "saved": True, "category": category}

        async def fake_search_memories(query, top_k=5, category=None):
            return [{"id": 1, "text": "The blue folder is for nursery forms."}]

        fake_capture = types.ModuleType("app.core.capture")
        fake_capture.capture_note = fake_capture_note
        fake_semantic = types.ModuleType("app.core.semantic_memory")
        fake_semantic.search_memories = fake_search_memories

        with mock.patch.dict(sys.modules, {
            "app.core.capture": fake_capture,
            "app.core.semantic_memory": fake_semantic,
        }):
            result = asyncio.run(memory_quality.run_capture_retrieval_eval())

        self.assertTrue(result["ok"])
        self.assertEqual(result["capture"]["category"], "daily_capture")
        self.assertEqual(result["score"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
