import unittest
from pathlib import Path


class BriefingRouteSourceTests(unittest.TestCase):
    def test_today_now_and_resume_routes_share_today_brief(self):
        source = Path(__file__).with_name("briefing.py").read_text(encoding="utf-8")

        self.assertIn('@router.get("/briefing/today")', source)
        self.assertIn('@router.get("/briefing/now")', source)
        self.assertIn('@router.get("/briefing/resume")', source)
        self.assertEqual(source.count("return await get_today_brief()"), 3)


if __name__ == "__main__":
    unittest.main()
