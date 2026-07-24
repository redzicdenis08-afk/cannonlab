#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cannon-ratio-audit.py"
spec = importlib.util.spec_from_file_location("cannon_ratio_audit", SCRIPT)
if spec is None or spec.loader is None:
    raise RuntimeError(f"unable to import {SCRIPT}")
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)


def profile_path(name: str) -> Path:
    return ROOT / "profiles" / "ratios" / name


def test_public_07_profile() -> None:
    report = audit.load_profile(profile_path("public-0.7-384-osrb-1-above-barrel.json"))
    assert report["status"] == "WARN", report
    stack = report["stack_accounting"]
    assert stack["base_stack_amount"] == 384, stack
    assert stack["nominal_match"] is True, stack
    assert stack["restack_payload_amount"] == 9, stack
    assert stack["base_stack_entries"] == ["sand", "hybrid sand 1", "hybrid sand 2"], stack
    assert "fractional_timing_is_ordering_evidence_until_runtime_traced" in report["warnings"], report
    assert report["truth_boundary"]["runtime_physics_confirmed"] is False, report


def test_public_12_profile_preserves_uncertainty() -> None:
    report = audit.load_profile(profile_path("public-1.2-384-4os-derived.json"))
    assert report["status"] == "WARN", report
    sand = next(row for row in report["entries"] if row["normalized_name"] == "sand")
    hybrid = next(row for row in report["entries"] if row["normalized_name"] == "hybrid sand")
    assert sand["timing"]["raw"] == "10+", sand
    assert sand["timing"]["open_high"] is True, sand
    assert hybrid["timing"]["raw"] == "4-8", hybrid
    assert hybrid["timing"]["minimum"] == 4.0, hybrid
    assert hybrid["timing"]["maximum"] == 8.0, hybrid
    assert report["stack_accounting"]["base_stack_amount"] == 382, report
    assert "open_ended_timing_requires_runtime_resolution" in report["warnings"], report


def test_power_labels_do_not_count_as_payload() -> None:
    entries, _ = audit.parse_ratio_text(
        "Sand Power Amount: - Tick: 0\n"
        "sand Amount: 384 Tick: 8\n"
        "Hammer Power Amount: - Tick: 4\n"
        "hammer Amount: 400 Tick: 8\n"
    )
    stack = audit.stack_accounting(entries, 384)
    assert stack["base_stack_amount"] == 384, stack
    powers = [row for row in entries if row["primary_role"] == "power"]
    assert len(powers) == 2, powers
    assert all(row["tags"] == ["power"] for row in powers), powers


def test_missing_power_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "bad.json"
        path.write_text(
            json.dumps(
                {
                    "id": "bad-no-power",
                    "nominal_stack": 1,
                    "ratio_text": (
                        "sand Amount: 1 Tick: 1\n"
                        "hammer Amount: 1 Tick: 2\n"
                    ),
                }
            ),
            encoding="utf-8",
        )
        report = audit.load_profile(path)
        assert report["status"] == "FAIL", report
        assert "missing_power_entry" in report["failures"], report


def test_invalid_timing_rejects() -> None:
    try:
        audit.parse_timing("8ish")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid timing token unexpectedly parsed")


def test_profile_comparison_is_structural_only() -> None:
    reference = audit.load_profile(profile_path("public-0.7-384-osrb-1-above-barrel.json"))
    candidate = audit.load_profile(profile_path("public-1.2-384-4os-derived.json"))
    comparison = audit.compare_reports(reference, candidate)
    assert comparison["changed_entry_count"] > 0, comparison
    assert comparison["base_stack_delta"] == -2, comparison


def main() -> None:
    tests = [
        test_public_07_profile,
        test_public_12_profile_preserves_uncertainty,
        test_power_labels_do_not_count_as_payload,
        test_missing_power_fails_closed,
        test_invalid_timing_rejects,
        test_profile_comparison_is_structural_only,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")


if __name__ == "__main__":
    main()
