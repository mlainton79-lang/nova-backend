import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = ROOT.joinpath("app", "main.py")
CLEANUP_FN = "_one_time_ccj_cleanup_sync"


def _calls_cleanup(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            if child.func.id == CLEANUP_FN:
                return True
    return False


class MainStartupCleanupSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = MAIN_SOURCE.read_text(encoding="utf-8")
        self.module = ast.parse(self.source)

    def test_destructive_cleanup_remains_explicit_maintenance_only(self):
        cleanup_defs = [
            node
            for node in self.module.body
            if isinstance(node, ast.FunctionDef) and node.name == CLEANUP_FN
        ]
        self.assertEqual(len(cleanup_defs), 1)

        cleanup_source = ast.get_source_segment(self.source, cleanup_defs[0])
        self.assertIn("DELETE FROM tony_alerts", cleanup_source)
        self.assertIn("DELETE FROM tony_email_cache", cleanup_source)
        self.assertIn("DELETE FROM tony_email_queue", cleanup_source)
        self.assertIn("operator-triggered maintenance", cleanup_source.lower())
        self.assertIn("not called during application import or startup", cleanup_source)

    def test_module_import_does_not_run_destructive_cleanup(self):
        for node in self.module.body:
            if isinstance(node, ast.FunctionDef) and node.name == CLEANUP_FN:
                continue
            self.assertFalse(
                _calls_cleanup(node),
                f"{CLEANUP_FN} must not be called at module import/startup",
            )

    def test_fastapi_startup_event_does_not_run_destructive_cleanup(self):
        startup_events = [
            node
            for node in self.module.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "startup_event"
        ]
        self.assertEqual(len(startup_events), 1)
        self.assertFalse(
            _calls_cleanup(startup_events[0]),
            f"{CLEANUP_FN} must not be called by FastAPI startup_event()",
        )


if __name__ == "__main__":
    unittest.main()
