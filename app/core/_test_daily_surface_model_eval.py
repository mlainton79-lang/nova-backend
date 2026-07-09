import asyncio
import os
import unittest
from unittest.mock import patch


class DailySurfaceModelEvalTests(unittest.TestCase):
    def test_prompt_includes_surface_rubric_and_payload(self):
        from app.core.daily_surface_model_eval import build_daily_surface_judge_prompt

        prompt = build_daily_surface_judge_prompt(
            "today_brief",
            {"briefing": "Start here", "next_actions": [{"title": "Reply"}]},
        )

        self.assertIn("Surface: today_brief", prompt)
        self.assertIn("Gives concrete next actions", prompt)
        self.assertIn('"briefing": "Start here"', prompt)
        self.assertIn("Return STRICT JSON only", prompt)

    def test_extract_json_object_accepts_fenced_json(self):
        from app.core.daily_surface_model_eval import _extract_json_object

        parsed = _extract_json_object("""```json
{"score": 0.9, "passed": true, "reasons": ["clear"]}
```""")

        self.assertEqual(parsed["score"], 0.9)
        self.assertTrue(parsed["passed"])

    def test_heuristic_today_brief_scores_expected_surface(self):
        from app.core.daily_surface_model_eval import heuristic_daily_surface_score

        result = heuristic_daily_surface_score("today_brief", {
            "briefing": "You have three useful things to do.",
            "next_actions": [{"title": "Approve safe item"}],
            "health_flags": [],
            "email_attention": {"urgent": []},
            "approval_cards": [],
        })

        self.assertEqual(result["surface"], "today_brief")
        self.assertEqual(result["judge"], "heuristic")
        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 1.0)

    def test_heuristic_daily_review_fails_weak_surface(self):
        from app.core.daily_surface_model_eval import heuristic_daily_surface_score

        result = heuristic_daily_surface_score("daily_review", {
            "review": "",
            "follow_up_actions": [],
            "signals": {},
        })

        self.assertFalse(result["passed"])
        self.assertLess(result["score"], 0.8)
        self.assertIn("Missing or weak checks", result["reasons"][0])

    def test_judge_uses_heuristic_without_model_key(self):
        from app.core.daily_surface_model_eval import judge_daily_surface

        env = dict(os.environ)
        env.pop("GEMINI_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            result = asyncio.run(judge_daily_surface("today_brief", {
                "briefing": "Start.",
                "next_actions": [{"title": "Do one thing"}],
                "health_flags": [],
                "email_attention": {},
                "approval_cards": [],
            }))

        self.assertEqual(result["judge"], "heuristic")
        self.assertTrue(result["passed"])

    def test_combine_daily_surface_model_evals(self):
        from app.core.daily_surface_model_eval import combine_daily_surface_model_evals

        result = combine_daily_surface_model_evals([
            {"surface": "today_brief", "score": 1.0, "passed": True},
            {"surface": "daily_review", "score": 0.5, "passed": False},
        ])

        self.assertEqual(result["score"], 0.75)
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(len(result["surfaces"]), 2)


if __name__ == "__main__":
    unittest.main()
