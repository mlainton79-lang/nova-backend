#!/usr/bin/env python3
"""Run Nova's local, non-DB Python tests.

The repo has two test styles:
- pytest-style files (plain test functions / monkeypatch fixtures)
- direct unittest/script files named _test_*.py

DB integration tests remain opt-in via --include-db because they require a
real DATABASE_URL and mutate test rows before cleaning up.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DB_REQUIRED = {
    Path("app/observability/_test_events.py"),
    Path("app/selling/_test_drafts.py"),
    Path("app/selling/_test_jobs.py"),
}


def _test_files() -> list[Path]:
    files = []
    for base in (ROOT / "app", ROOT / "tools"):
        files.extend(base.rglob("_test_*.py"))
        files.extend(base.rglob("test_*.py"))
    return sorted({p.relative_to(ROOT) for p in files})


def _uses_pytest(path: Path) -> bool:
    text = (ROOT / path).read_text(errors="ignore")
    return (
        "import pytest" in text
        or "from pytest" in text
        or "monkeypatch" in text
        or 'if __name__ == "__main__"' not in text
    )


def _run(cmd: list[str]) -> int:
    print("\n$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-db",
        action="store_true",
        help="also run DB integration tests; requires DATABASE_URL",
    )
    args = parser.parse_args()

    files = _test_files()
    if not args.include_db:
        files = [p for p in files if p not in DB_REQUIRED]
    elif not os.environ.get("DATABASE_URL"):
        print("ERROR: --include-db requires DATABASE_URL", file=sys.stderr)
        return 2

    pytest_files = [p for p in files if _uses_pytest(p) or p.name.startswith("test_")]
    direct_files = [p for p in files if p not in pytest_files]

    failures = 0
    if pytest_files:
        failures += int(_run([sys.executable, "-m", "pytest", *map(str, pytest_files)]) != 0)

    for path in direct_files:
        failures += int(_run([sys.executable, str(path)]) != 0)

    print(
        f"\nSUMMARY: pytest_files={len(pytest_files)} "
        f"direct_files={len(direct_files)} failures={failures}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
