#!/usr/bin/env python3
"""Promote reviewed production-failure eval candidates into static cases.

Input can be either:
- the full /api/v1/evals/failure-candidates response, or
- a list of candidate objects from that response.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "app" / "evals" / "production_failure_cases.json"

REQUIRED_FIELDS = ("id", "message", "expected_behaviour", "category")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("candidates", [])
    else:
        items = payload
    if not isinstance(items, list):
        raise ValueError("input must be a candidate list or an object with candidates")
    return [item for item in items if isinstance(item, dict)]


def _case_from_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    proposed = candidate.get("proposed_test")
    if not isinstance(proposed, dict):
        raise ValueError(f"candidate {candidate.get('id')!r} has no proposed_test")

    case = dict(proposed)
    case["id"] = str(candidate.get("id") or proposed.get("id") or "").strip()
    if "source_event_id" in candidate:
        case["source_event_id"] = candidate["source_event_id"]
    if "evidence" in candidate:
        case["production_evidence"] = str(candidate["evidence"])[:700]

    missing = [field for field in REQUIRED_FIELDS if not case.get(field)]
    if missing:
        raise ValueError(f"candidate {candidate.get('id')!r} missing fields: {', '.join(missing)}")
    return case


def promote_candidates(
    candidates: Iterable[Dict[str, Any]],
    existing_cases: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {
        str(case["id"]): dict(case)
        for case in existing_cases
        if isinstance(case, dict) and case.get("id")
    }
    for candidate in candidates:
        case = _case_from_candidate(candidate)
        by_id[case["id"]] = case
    return [by_id[key] for key in sorted(by_id)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = _load_json(args.input_json)
    candidates = _candidate_items(payload)
    existing = _load_json(args.output) if args.output.exists() else []
    if not isinstance(existing, list):
        raise ValueError(f"{args.output} must contain a JSON list")

    promoted = promote_candidates(candidates, existing)
    args.output.write_text(
        json.dumps(promoted, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(f"promoted_cases={len(promoted)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
