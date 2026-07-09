import unittest
from pathlib import Path


class WorkflowStateStartupSourceTests(unittest.TestCase):
    def test_workflow_state_init_is_registered(self):
        source = Path(__file__).parents[1].joinpath("router.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"app.core.workflow_state"', source)
        self.assertIn('"init_workflow_state_table"', source)
        self.assertIn('"Workflow state"', source)


if __name__ == "__main__":
    unittest.main()
