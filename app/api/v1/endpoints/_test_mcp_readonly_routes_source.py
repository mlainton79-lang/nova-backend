import unittest
from pathlib import Path


class McpReadonlyRouteSourceTests(unittest.TestCase):
    def test_mcp_readonly_routes_are_secured_and_registered(self):
        endpoint_source = Path(__file__).with_name("mcp_readonly.py").read_text(
            encoding="utf-8"
        )
        router_source = Path(__file__).parents[1].joinpath("router.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('@router.get("/mcp/read-only/tools")', endpoint_source)
        self.assertIn('@router.post("/mcp/read-only")', endpoint_source)
        self.assertIn("Depends(verify_token)", endpoint_source)
        self.assertIn("from app.api.v1.endpoints import mcp_readonly", router_source)
        self.assertIn(
            'router.include_router(mcp_readonly.router, tags=["mcp_readonly"])',
            router_source,
        )


if __name__ == "__main__":
    unittest.main()
