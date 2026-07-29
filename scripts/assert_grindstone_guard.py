#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import evaluate_private_stack_evidence as evaluator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = evaluator.read_rows(args.evidence)
    finding = evaluator.grindstone_xp(rows)
    attempts = finding.get("evidence", {}).get("attempts", [])
    passed = (
        finding.get("status") == "rejected"
        and len(attempts) == 3
        and all(attempt.get("xp_gain") == 0.0 for attempt in attempts)
        and all(attempt.get("item_persisted") is True for attempt in attempts)
        and all(attempt.get("cancelled_result_click") is True for attempt in attempts)
    )
    report = {
        "status": "GUARD_PASS" if passed else "GUARD_FAIL",
        "finding": finding,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())