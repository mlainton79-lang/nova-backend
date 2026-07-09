import unittest
from pathlib import Path


class CaptureRouteSourceTests(unittest.TestCase):
    def test_capture_note_route_is_secured_and_registered(self):
        endpoint_source = Path(__file__).with_name("capture.py").read_text(
            encoding="utf-8"
        )
        router_source = Path(__file__).parents[1].joinpath("router.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('@router.post("/capture/note")', endpoint_source)
        self.assertIn("Depends(verify_token)", endpoint_source)
        self.assertIn("from app.api.v1.endpoints import capture", router_source)
        self.assertIn('router.include_router(capture.router, tags=["capture"])', router_source)


if __name__ == "__main__":
    unittest.main()
