#!/usr/bin/env python3
"""Compare a declared runtime profile with field observations.

This tool deliberately separates matches, mismatches, and unknowns so a public
Sakura run can never be mislabeled as proven ExtremeCraft parity.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

TOKEN = re.compile(r"([^.[\]]+)|\[(\d+)\]")


def load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"Expected mapping in {path}")
    return value


def get_path(root: Any, path: str) -> tuple[bool, Any]:
    value = root
    for match in TOKEN.finditer(path):
        key, index = match.groups()
        if key is not None:
            if not isinstance(value, dict) or key not in value:
                return False, None
            value = value[key]
        else:
            position = int(index)
            if not isinstance(value, list) or position >= len(value):
                return False, None
            value = value[position]
    return True, value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", type=Path)
    parser.add_argument("observations", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--require-no-mismatch", action="store_true")
    args = parser.parse_args()

    profile = load(args.profile)
    observations = load(args.observations)
    facts = observations.get("facts", [])
    if not isinstance(facts, list):
        raise SystemExit("observations.facts must be a list")

    matched: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, dict):
            raise SystemExit("Each observations.facts entry must be a mapping")
        fact_id = str(fact.get("id", "unnamed"))
        path = str(fact.get("profile-path", ""))
        found, actual = get_path(profile, path)
        row = {
            "id": fact_id,
            "path": path,
            "expected": fact.get("value"),
            "actual": actual,
            "evidence": fact.get("evidence", "unknown"),
            "confidence": fact.get("confidence", "unknown"),
        }
        if not found:
            unsupported.append(row)
        elif actual == fact.get("value"):
            matched.append(row)
        else:
            mismatched.append(row)

    unknowns = observations.get("unknowns", [])
    if not isinstance(unknowns, list):
        raise SystemExit("observations.unknowns must be a list")
    profile_unknowns = profile.get("unknowns", [])
    report = {
        "schema_version": 1,
        "profile_id": profile.get("id", "unknown"),
        "server": observations.get("server", "unknown"),
        "observed_at": observations.get("observed-at", "unknown"),
        "matched_count": len(matched),
        "mismatched_count": len(mismatched),
        "unsupported_count": len(unsupported),
        "open_probe_count": len(unknowns),
        "parity_status": "candidate" if not mismatched else "mismatch",
        "matched": matched,
        "mismatched": mismatched,
        "unsupported": unsupported,
        "open_probes": unknowns,
        "profile_unknowns": profile_unknowns,
        "warning": "A candidate status is not live parity proof. Unknown private settings remain unknown.",
    }
    text = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text, end="")
    if args.require_no_mismatch and (mismatched or unsupported):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
