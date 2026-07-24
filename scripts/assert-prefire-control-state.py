#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def fail(message: str) -> int:
    print(json.dumps({"status": "FAIL", "error": message}, indent=2))
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify CannonLab pre-fire control-state runtime evidence")
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--expected-before", required=True)
    parser.add_argument("--expected-after", required=True)
    args = parser.parse_args()

    summary_path = args.run_directory / "run-summary.json"
    causal_path = args.run_directory / "shot-001" / "causal-events.csv"
    if not summary_path.is_file() or not causal_path.is_file():
        return fail("run-summary.json or shot-001/causal-events.csv is missing")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    with causal_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    named = [row for row in rows if f"name={args.name}" in row.get("details", "")]
    applied = [row for row in named if row.get("event") == "CONTROL_STATE_APPLY"]
    verified = [row for row in named if row.get("event") == "CONTROL_STATE_VERIFY"]
    failures = [row for row in named if row.get("event") == "CONTROL_STATE_FAILURE"]
    volleys = [row for row in rows if row.get("event") == "VOLLEY_FIRE"]

    if summary.get("finish_reason") != "complete":
        return fail(f"run did not complete: {summary.get('finish_reason')}")
    if len(applied) != 1 or len(verified) != 1 or failures:
        return fail(
            f"expected one apply, one verify, zero failures; got "
            f"apply={len(applied)} verify={len(verified)} failures={len(failures)}"
        )
    if not volleys:
        return fail("no VOLLEY_FIRE event was recorded")

    apply = applied[0]
    verify = verified[0]
    if f"before={args.expected_before}" not in apply["details"]:
        return fail("apply event did not record the expected before state")
    if f"desired={args.expected_after}" not in apply["details"]:
        return fail("apply event did not record the expected desired state")
    if f"actual={args.expected_after}" not in verify["details"]:
        return fail("verify event did not record the expected settled state")

    apply_key = (int(apply["tick"]), int(apply["sequence"]))
    verify_key = (int(verify["tick"]), int(verify["sequence"]))
    volley_key = min((int(row["tick"]), int(row["sequence"])) for row in volleys)
    if not apply_key < verify_key < volley_key:
        return fail(
            f"event order is invalid: apply={apply_key} verify={verify_key} volley={volley_key}"
        )

    print(json.dumps({
        "status": "PASS",
        "scenario": summary.get("scenario"),
        "control_state": args.name,
        "apply": apply_key,
        "verify": verify_key,
        "first_volley": volley_key,
        "cannon_missing_blocks": summary["shots"][0]["cannon_missing_blocks"],
        "self_damage_blocks": summary["shots"][0]["self_damage_blocks"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
