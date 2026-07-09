#!/usr/bin/env python3
"""Focused CI gate for Nova's Capture / Resume / Review contracts."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

TEST_MODULES = [
    "app.core._test_capture",
    "app.api.v1.endpoints._test_capture_routes_source",
    "app.core._test_command_parser_daily_review",
    "app.core._test_today_brief",
    "app.core._test_daily_review",
    "app.core._test_approval_display",
    "app.core._test_email_triage_lists",
    "app.api.v1.endpoints._test_briefing_routes_source",
    "app.core._test_daily_loop_quality",
    "app.api.v1.endpoints._test_daily_loop_evals_source",
    "app.core._test_memory_quality",
    "app.core._test_workflow_state",
    "app.api.v1.endpoints._test_workflow_state_startup_source",
    "app.core._test_mcp_readonly",
    "app.api.v1.endpoints._test_mcp_readonly_routes_source",
    "app.core._test_daily_surface_model_eval",
    "app.core._test_production_failure_evals",
]


def main() -> int:
    cmd = [sys.executable, "-m", "unittest", *TEST_MODULES]
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
