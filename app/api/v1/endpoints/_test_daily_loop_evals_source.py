import unittest
from pathlib import Path


class DailyLoopEvalRouteSourceTests(unittest.TestCase):
    def test_daily_loop_eval_route_is_secured(self):
        source = Path(__file__).with_name("evals.py").read_text(encoding="utf-8")

        self.assertIn('@router.get("/evals/daily-loop")', source)
        self.assertIn("async def daily_loop_quality(_=Depends(verify_token))", source)
        self.assertIn("combine_daily_loop_quality", source)

    def test_memory_retrieval_eval_route_is_secured(self):
        source = Path(__file__).with_name("evals.py").read_text(encoding="utf-8")

        self.assertIn('@router.get("/evals/memory-retrieval")', source)
        self.assertIn("async def memory_retrieval_quality(_=Depends(verify_token))", source)
        self.assertIn("run_capture_retrieval_eval", source)

    def test_daily_surface_model_eval_route_is_secured(self):
        source = Path(__file__).with_name("evals.py").read_text(encoding="utf-8")

        self.assertIn('@router.get("/evals/daily-surface-model")', source)
        self.assertIn("async def daily_surface_model_quality(_=Depends(verify_token))", source)
        self.assertIn("run_daily_surface_model_eval", source)

    def test_failure_candidate_eval_route_is_secured(self):
        source = Path(__file__).with_name("evals.py").read_text(encoding="utf-8")

        self.assertIn('@router.get("/evals/failure-candidates")', source)
        self.assertIn("async def production_failure_eval_candidates(", source)
        self.assertIn("_=Depends(verify_token)", source)
        self.assertIn("recent_failure_events", source)


if __name__ == "__main__":
    unittest.main()
