import unittest
from pathlib import Path


class DailyLoopEvalRouteSourceTests(unittest.TestCase):
    def test_daily_loop_eval_route_is_secured(self):
        source = Path(__file__).with_name("evals.py").read_text(encoding="utf-8")

        self.assertIn('@router.get("/evals/daily-loop")', source)
        self.assertIn("async def daily_loop_quality(_=Depends(verify_token))", source)
        self.assertIn("combine_daily_loop_quality", source)


if __name__ == "__main__":
    unittest.main()
