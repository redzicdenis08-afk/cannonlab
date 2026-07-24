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


base = load("shared_assembly_review_base", "test-legacy-shared-assembly-audit.py")


def test_small_clean_delta_is_review_candidate_not_promotion() -> None:
    common = {(x, 0, 0): (55, 0) for x in range(16)}
    first = {**common, (16, 0, 0): (49, 0)}
    second = dict(common)
    report = base.run(first, second, (17, 1, 1), minimum=8)
    row = report["assemblies"][0]
    assert row["status"] == "OPEN_SHARED_ASSEMBLY", row
    assert row["review_classification"] == "NEAR_CLOSED_STATIC_REVIEW_CANDIDATE", row
    assert row["residual_unique_outside_position_count"] == 1, row
    assert row["boundary_examples"][0]["classification"] == "first_only_nonair", row
    assert row["boundary_examples"][0]["first_token"] == "legacy-49:0", row
    assert row["promotion_eligible"] is False, row


def test_metadata_conflict_blocks_near_closed_review() -> None:
    common = {(x, 0, 0): (55, 0) for x in range(16)}
    first = {**common, (16, 0, 0): (93, 1)}
    second = {**common, (16, 0, 0): (93, 5)}
    report = base.run(first, second, (17, 1, 1), minimum=8)
    row = report["assemblies"][0]
    assert row["review_classification"] == "OPEN_STATIC_ASSEMBLY", row
    assert row["residual_boundary_edge_counts"]["shared_conflicting_functional"] == 1, row
    assert row["boundary_examples"][0]["classification"] == "shared_conflicting_functional", row


def test_boundary_limit_blocks_review_classification() -> None:
    common = {(x, 0, 0): (55, 0) for x in range(16)}
    first = dict(common)
    second = dict(common)
    for x in range(16):
        first[(x, 1, 0)] = (49, 0)
    report = base.run(first, second, (16, 2, 1), minimum=8)
    row = report["assemblies"][0]
    assert row["residual_unique_outside_position_count"] == 16, row
    assert row["review_classification"] == "NEAR_CLOSED_STATIC_REVIEW_CANDIDATE", row

    with_limit_15 = base.assembly.build_report(
        "first",
        _write_temp(first, (16, 2, 1), "first"),
        "second",
        _write_temp(second, (16, 2, 1), "second"),
        turns=0,
        translation=(0, 0, 0),
        minimum_functional_count=8,
        chunk_limit=160,
        max_shared_support_nodes=1000,
        near_closed_boundary_limit=15,
    )
    assert with_limit_15["assemblies"][0]["review_classification"] == "OPEN_STATIC_ASSEMBLY"


_TEMP_ROOTS = []


def _write_temp(values, dimensions, name):
    import tempfile
    root = tempfile.TemporaryDirectory()
    _TEMP_ROOTS.append(root)
    path = Path(root.name) / f"{name}.schematic"
    base.write_legacy(path, dimensions, values)
    return path


def main() -> int:
    tests = [
        test_small_clean_delta_is_review_candidate_not_promotion,
        test_metadata_conflict_blocks_near_closed_review,
        test_boundary_limit_blocks_review_classification,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} near-closed assembly review regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
