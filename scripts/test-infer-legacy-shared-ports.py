#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load(name: str, filename: str):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ports = load("infer_legacy_shared_ports_test", "infer-legacy-shared-ports.py")


def example(classification, inside, outside, first_token=None, second_token=None):
    return {
        "classification": classification,
        "inside": list(inside),
        "outside": list(outside),
        "first_token": first_token,
        "second_token": second_token,
    }


def assembly_report(examples, residual=None):
    residual = residual or {"first_only_nonair": 4, "second_only_nonair": 4}
    return {
        "status": "PASS",
        "classification": "LEGACY_SHARED_STATIC_ASSEMBLY_CLOSURE_ONLY",
        "transform": {"degrees": 270, "translation": [-649, 0, 357]},
        "assemblies": [
            {
                "assembly_id": "ASSEMBLY-002",
                "review_classification": "NEAR_CLOSED_STATIC_REVIEW_CANDIDATE",
                "functional_count": 273,
                "support_count": 265,
                "ec160": {"legal_offset_count": 256, "dispenser_count": 118},
                "residual_boundary_edge_counts": residual,
                "boundary_examples": examples,
            }
        ],
    }


def paired_examples():
    rows = []
    for y in (0, 4):
        rows.extend([
            example("first_only_nonair", (3, y, 6), (2, y, 6), first_token="legacy-49:0"),
            example("first_only_nonair", (3, y + 1, 6), (2, y + 1, 6), first_token="redstone_wire"),
            example("second_only_nonair", (3, y, 6), (3, y, 7), second_token="legacy-49:0"),
            example("second_only_nonair", (3, y + 1, 6), (3, y + 1, 7), second_token="repeater:13"),
        ])
    return rows


def test_pairs_two_variant_boundary_ports() -> None:
    report = ports.build_report(assembly_report(paired_examples()))
    assert report["status"] == "PASS", report
    assert report["summary"]["reviewed_assembly_count"] == 1, report
    assert report["summary"]["paired_port_hypothesis_count"] == 2, report
    assert report["summary"]["unpaired_boundary_group_count"] == 0, report
    row = report["assemblies"][0]
    assert len(row["first_boundary_groups"]) == 2, row
    assert len(row["second_boundary_groups"]) == 2, row
    assert all(pair["first_face"] == "west" for pair in row["paired_port_hypotheses"]), row
    assert all(pair["second_face"] == "south" for pair in row["paired_port_hypotheses"]), row
    assert all(pair["promotion_eligible"] is False for pair in row["paired_port_hypotheses"]), row


def test_unpaired_group_is_preserved() -> None:
    rows = paired_examples()
    rows.append(
        example("first_only_nonair", (3, 8, 6), (2, 8, 6), first_token="redstone_wire")
    )
    report = ports.build_report(
        assembly_report(
            rows,
            {"first_only_nonair": 5, "second_only_nonair": 4},
        )
    )
    assert report["summary"]["paired_port_hypothesis_count"] == 2, report
    assert report["summary"]["unpaired_boundary_group_count"] == 1, report


def test_truncated_examples_fail_closed() -> None:
    try:
        ports.build_report(assembly_report(paired_examples()[:-1]))
    except ports.PortInferenceError as exc:
        assert "truncated" in str(exc), exc
    else:
        raise AssertionError("truncated boundary evidence must fail")


def test_non_reviewed_assembly_is_ignored() -> None:
    payload = assembly_report([],{})
    payload["assemblies"][0]["review_classification"] = "OPEN_STATIC_ASSEMBLY"
    payload["assemblies"][0]["residual_boundary_edge_counts"] = {}
    report = ports.build_report(payload)
    assert report["summary"]["reviewed_assembly_count"] == 0, report
    assert report["summary"]["paired_port_hypothesis_count"] == 0, report


def main() -> int:
    tests = [
        test_pairs_two_variant_boundary_ports,
        test_unpaired_group_is_preserved,
        test_truncated_examples_fail_closed,
        test_non_reviewed_assembly_is_ignored,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} variant port inference regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
