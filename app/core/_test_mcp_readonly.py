import asyncio
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class McpReadonlyTests(unittest.TestCase):
    def test_list_tools_exposes_only_nova_read_tools(self):
        from app.core.mcp_readonly import list_tools

        result = list_tools()
        names = [tool["name"] for tool in result["tools"]]

        self.assertEqual(names, [
            "nova.today_brief",
            "nova.daily_review",
            "nova.capability_cards",
            "nova.codebase_stats",
            "nova.daily_loop_quality",
            "nova.daily_surface_model_eval",
            "nova.failure_candidates",
        ])
        for name in names:
            self.assertTrue(name.startswith("nova."))
            self.assertNotIn("send", name)
            self.assertNotIn("delete", name)
            self.assertNotIn("approve", name)

    def test_failure_candidates_tool_has_bounded_input_schema(self):
        from app.core.mcp_readonly import list_tools

        tools = {tool["name"]: tool for tool in list_tools()["tools"]}
        schema = tools["nova.failure_candidates"]["inputSchema"]

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["minutes"]["maximum"], 1440)
        self.assertEqual(schema["properties"]["limit"]["maximum"], 100)

    def test_unknown_tool_returns_error_content(self):
        from app.core.mcp_readonly import call_tool

        result = asyncio.run(call_tool("nova.missing"))

        self.assertTrue(result["isError"])
        self.assertIn("Unknown tool", result["content"][0]["text"])

    def test_jsonrpc_tools_list_and_unknown_method(self):
        from app.core.mcp_readonly import handle_jsonrpc

        listed = asyncio.run(handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        }))
        missing = asyncio.run(handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/missing",
        }))

        self.assertEqual(listed["id"], 1)
        self.assertIn("tools", listed["result"])
        self.assertEqual(missing["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
