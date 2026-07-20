#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def get_path(document: dict[str, Any], path: str) -> Any:
    value: Any = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(path)
        value = value[part]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare CannonLab physics fingerprints")
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("rules", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    rules = json.loads(args.rules.read_text(encoding="utf-8"))

    comparisons = []
    failures = []
    for rule in rules.get("metrics", []):
        path = rule["path"]
        tolerance = float(rule.get("absolute_tolerance", 0.0))
        required = bool(rule.get("required", True))
        try:
            expected = float(get_path(reference, path))
            actual = float(get_path(candidate, path))
        except (KeyError, TypeError, ValueError) as exc:
            result = {"path": path, "status": "MISSING", "required": required, "error": str(exc)}
            comparisons.append(result)
            if required:
                failures.append(f"{path}: missing required metric")
            continue

        delta = actual - expected
        passed = abs(delta) <= tolerance
        result = {
            "path": path,
            "status": "PASS" if passed else "FAIL",
            "reference": expected,
            "candidate": actual,
            "delta": delta,
            "absolute_tolerance": tolerance,
        }
        comparisons.append(result)
        if not passed:
            failures.append(f"{path}: delta {delta} exceeds ±{tolerance}")

    report = {
        "status": "PASS" if not failures else "FAIL",
        "reference": str(args.reference),
        "candidate": str(args.candidate),
        "rules": str(args.rules),
        "comparisons": comparisons,
        "failures": failures,
    }
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
