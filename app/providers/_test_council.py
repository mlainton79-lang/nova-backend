import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class CouncilProviderTests(unittest.TestCase):
    def test_provider_failure_keeps_class_for_empty_message_exceptions(self):
        from app.providers.council import _provider_failure

        failure = _provider_failure(TimeoutError(), "chat")

        self.assertEqual(failure["stage"], "chat")
        self.assertEqual(failure["error_class"], "TimeoutError")
        self.assertEqual(failure["message"], "(no message)")

    def test_provider_failure_truncates_message(self):
        from app.providers.council import _provider_failure

        failure = _provider_failure(RuntimeError("x" * 500), "init")

        self.assertEqual(failure["stage"], "init")
        self.assertEqual(failure["error_class"], "RuntimeError")
        self.assertEqual(len(failure["message"]), 300)


if __name__ == "__main__":
    unittest.main()
