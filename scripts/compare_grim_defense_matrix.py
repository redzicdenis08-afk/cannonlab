#!/usr/bin/env python3
"""Compare compact PhaseLab vehicle verdicts across baseline and Grim stacks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def family_counts(verdict: dict[str, Any]) -> dict[str, tuple[int, int]]:
    raw = verdict.get("by_family") or {}
    result: dict[str, tuple[int, int]] = {}
    if not isinstance(raw, dict):
        return result
    for name, value in raw.items():
        if not isinstance(value, dict):
            continue
        successes = int(value.get("successes") or 0)
        attempts = int(value.get("attempts") or 0)
        result[str(name)] = (successes, attempts)
    return result


def compare(baseline: dict[str, Any], protected: dict[str, Any]) -> dict[str, Any]:
    base_families = family_counts(baseline)
    protected_families = family_counts(protected)
    names = sorted(set(base_families) | set(protected_families))
    rows = []
    for name in names:
        base_success, base_attempts = base_families.get(name, (0, 0))
        guard_success, guard_attempts = protected_families.get(name, (0, 0))
        if base_attempts == 0 or guard_attempts == 0:
            status = "INCONCLUSIVE"
        elif base_success > 0 and guard_success == 0:
            status = "BLOCKED"
        elif base_success > 0 and guard_success > 0:
            status = "REGRESSION"
        elif base_success == 0 and guard_success == 0:
            status = "BASELINE_REJECTED"
        else:
            status = "ANOMALOUS"
        rows.append({
            "family": name,
            "baseline": {"successes": base_success, "attempts": base_attempts},
            "protected": {"successes": guard_success, "attempts": guard_attempts},
            "status": status,
        })
    return {
        "baseline_stack": baseline.get("stack_id"),
        "protected_stack": protected.get("stack_id"),
        "protected_version": protected.get("grim_version"),
        "families": rows,
        "blocked": sum(row["status"] == "BLOCKED" for row in rows),
        "regressions": sum(row["status"] == "REGRESSION" for row in rows),
        "inconclusive": sum(row["status"] == "INCONCLUSIVE" for row in rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("protected", nargs="+", type=Path)
    parser.add_argument("--strict", action="store_true", help="fail if any protected stack still accepts a baseline-success family")
    args = parser.parse_args()

    baseline = load(args.baseline)
    reports = [compare(baseline, load(path)) for path in args.protected]
    print(json.dumps(reports, indent=2, sort_keys=True))
    if args.strict and any(report["regressions"] for report in reports):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
