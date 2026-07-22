#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_PROBES: dict[str, dict[str, Any]] = {
    "single-dispenser-fuse": {
        "minimum_samples": 10,
        "sample_fields": ["activation_tick", "first_entity_tick", "first_fuse", "explosion_tick"],
    },
    "dispenser-launch-spread": {
        "minimum_samples": 20,
        "sample_fields": ["spawn", "velocity"],
    },
    "water-flow": {
        "minimum_samples": 8,
        "sample_fields": ["flow_state", "positions"],
    },
    "falling-block-parity": {
        "minimum_samples": 10,
        "sample_fields": ["spawn_tick", "block_state", "positions", "outcome"],
    },
    "high-speed-survival": {
        "minimum_samples": 10,
        "sample_fields": ["requested_velocity", "observed_velocity", "outcome"],
    },
    "durable-blocks-regen": {
        "minimum_samples": 10,
        "sample_fields": ["material", "explosion_tick", "damage", "replacement_tick"],
    },
    "redstone-timing": {
        "minimum_samples": 10,
        "sample_fields": ["configured_delay", "activation_tick"],
    },
    "chunk-paste-limits": {
        "minimum_samples": 6,
        "sample_fields": ["dispensers", "block_entities", "offset_x", "offset_z", "paste_result"],
    },
}


def files_at(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.json"))


def validate_file(path: Path) -> tuple[str | None, dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, {}, [f"invalid JSON: {exc}"]
    if not isinstance(payload, dict):
        return None, {}, ["root must be an object"]

    probe = payload.get("probe")
    if not isinstance(probe, str) or not probe:
        errors.append("probe is required")
        probe = None
    elif probe not in REQUIRED_PROBES:
        errors.append(f"unknown probe {probe!r}")

    for field in ("server", "captured_at", "client_version", "paste_origin", "chunk_origin_confirmed", "samples"):
        if field not in payload:
            errors.append(f"missing {field}")
    if payload.get("server") != "ExtremeCraft Cannoning":
        errors.append("server must be exactly 'ExtremeCraft Cannoning'")
    if payload.get("chunk_origin_confirmed") is not True:
        errors.append("chunk_origin_confirmed must be true")
    samples = payload.get("samples")
    if not isinstance(samples, list):
        errors.append("samples must be an array")
        samples = []

    if probe in REQUIRED_PROBES:
        rules = REQUIRED_PROBES[probe]
        minimum = int(rules["minimum_samples"])
        if len(samples) < minimum:
            errors.append(f"samples={len(samples)} below required {minimum}")
        required_fields = list(rules["sample_fields"])
        for index, sample in enumerate(samples):
            if not isinstance(sample, dict):
                errors.append(f"sample {index + 1} must be an object")
                continue
            missing = [field for field in required_fields if field not in sample]
            if missing:
                errors.append(f"sample {index + 1} missing {', '.join(missing)}")

    return probe, payload, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an ExtremeCraft black-box calibration evidence pack")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    evidence_files = files_at(args.evidence)
    reports: list[dict[str, Any]] = []
    valid_probes: set[str] = set()
    for path in evidence_files:
        probe, payload, errors = validate_file(path)
        valid = probe is not None and not errors
        if valid:
            valid_probes.add(probe)
        reports.append({
            "file": str(path),
            "probe": probe,
            "samples": len(payload.get("samples", [])) if isinstance(payload.get("samples"), list) else 0,
            "valid": valid,
            "errors": errors,
        })

    missing = sorted(set(REQUIRED_PROBES) - valid_probes)
    invalid_files = [report for report in reports if not report["valid"]]
    status = "PASS" if not missing and not invalid_files else "INCOMPLETE"
    report = {
        "status": status,
        "ec_calibrated": status == "PASS",
        "required_probe_count": len(REQUIRED_PROBES),
        "valid_probe_count": len(valid_probes),
        "valid_probes": sorted(valid_probes),
        "missing_probes": missing,
        "invalid_file_count": len(invalid_files),
        "files": reports,
        "truth_boundary": "PASS validates evidence completeness and shape; it does not independently verify that the observations were measured correctly.",
    }
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
