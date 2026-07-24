#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().with_name("legacy-cannon-architecture.py")
    spec = importlib.util.spec_from_file_location("legacy_cannon_architecture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


architecture = load_module()


def translated(blocks, delta):
    return {
        (point[0] + delta[0], point[1] + delta[1], point[2] + delta[2]): token
        for point, token in blocks.items()
    }


def basic_machine():
    return {
        (0, 0, 0): "dispenser:2",
        (0, 1, 0): "dispenser:2",
        (1, 0, 0): "repeater:4",
        (2, 0, 0): "redstone_wire",
        (0, 2, 0): "sticky_piston:5",
        (0, 3, 0): "redstone_block",
        (1, 1, 0): "stone_button:1",
    }


def test_canonicalization_ignores_volatile_states():
    assert architecture.canonical_token(93, 4) == architecture.canonical_token(94, 4)
    assert architecture.canonical_token(55, 0) == architecture.canonical_token(55, 15)
    assert architecture.canonical_token(23, 2) == architecture.canonical_token(23, 10)
    assert architecture.canonical_token(75, 3) == architecture.canonical_token(76, 3)


def test_translation_safe_modules_and_motifs():
    first = architecture.analyze_blocks("first", basic_machine())
    second = architecture.analyze_blocks("second", translated(basic_machine(), (100, 20, -30)))
    assert first["bank_context_modules"][0]["signature"] == second["bank_context_modules"][0]["signature"]
    comparison = architecture.compare_sources([first, second])
    pair = comparison["pairwise_similarity"][0]
    assert pair["motif_weighted_jaccard"] == 1.0, pair
    assert pair["shared_exact_bank_context_count"] == 1, pair
    assert comparison["summary"]["motifs_present_in_all_sources"] > 0, comparison


def test_changed_timing_metadata_changes_overlap():
    first = architecture.analyze_blocks("first", basic_machine())
    changed = basic_machine()
    changed[(1, 0, 0)] = "repeater:8"
    second = architecture.analyze_blocks("changed", changed)
    comparison = architecture.compare_sources([first, second])
    pair = comparison["pairwise_similarity"][0]
    assert pair["motif_weighted_jaccard"] < 1.0, pair
    assert pair["shared_exact_bank_context_count"] == 0, pair


def test_repeated_slice_family_detection():
    blocks = {}
    for x in (0, 4, 8):
        blocks[(x, 0, 0)] = "dispenser:2"
        blocks[(x, 1, 0)] = "repeater:4"
        blocks[(x, 2, 0)] = "redstone_wire"
    families = architecture.slice_families(blocks)
    x_family = next(row for row in families if row["axis"] == "x")
    assert x_family["instances"] == 3, x_family
    assert x_family["regular_spacing"] is True, x_family
    assert x_family["spacing"] == 4, x_family


def test_dispenser_orientation_separates_banks():
    blocks = {
        (0, 0, 0): "dispenser:2",
        (1, 0, 0): "dispenser:2",
        (2, 0, 0): "dispenser:3",
    }
    banks = architecture.dispenser_banks(blocks)
    assert len(banks) == 2, banks
    assert sorted(row["dispenser_count"] for row in banks) == [1, 2], banks


def main() -> int:
    tests = [
        test_canonicalization_ignores_volatile_states,
        test_translation_safe_modules_and_motifs,
        test_changed_timing_metadata_changes_overlap,
        test_repeated_slice_family_detection,
        test_dispenser_orientation_separates_banks,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} legacy architecture regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
