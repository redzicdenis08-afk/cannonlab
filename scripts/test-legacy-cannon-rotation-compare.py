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


architecture = load("legacy_cannon_architecture", "legacy-cannon-architecture.py")
rotation = load("legacy_cannon_rotation_compare", "legacy-cannon-rotation-compare.py")


def machine():
    return {
        (0, 0, 0): "dispenser:2",
        (0, 1, 0): "dispenser:2",
        (1, 0, 0): "repeater:4",
        (2, 0, 1): "redstone_wire",
        (0, 2, 1): "sticky_piston:5",
        (-1, 3, 0): "redstone_block",
        (1, 1, -1): "stone_button:1",
    }


def rotate_machine(blocks, turns, delta=(0, 0, 0)):
    output = {}
    for point, token in blocks.items():
        x, y, z = rotation.rotate_y(point, turns)
        kind = architecture.token_kind(token)
        changed = {
            "dispenser": "dispenser:5",
            "repeater": "repeater:11",
            "sticky_piston": "sticky_piston:2",
            "stone_button": "stone_button:4",
        }.get(kind, token)
        output[(x + delta[0], y + delta[1], z + delta[2])] = changed
    return output


def source(source_id, blocks):
    motifs, metadata = rotation.structural_motifs(architecture, blocks)
    contexts = rotation.structural_bank_contexts(architecture, blocks)
    return {
        "source_id": source_id,
        "structural_motif_counts": dict(motifs),
        "structural_motif_metadata": metadata,
        "structural_bank_contexts": contexts,
    }


def test_rotation_and_translation_match():
    first = source("first", machine())
    second = source("second", rotate_machine(machine(), 1, (100, 20, -30)))
    comparison = rotation.compare_sources([first, second])
    pair = comparison["pairwise_similarity"][0]
    assert pair["y_rotation_structural_motif_jaccard"] == 1.0, pair
    assert pair["shared_y_rotation_bank_context_count"] == 1, pair


def test_directional_metadata_is_explicitly_discarded():
    first = [((0, 0, 0), "dispenser"), ((1, 0, 0), "repeater")]
    second = [((0, 0, 0), "dispenser"), ((0, 0, 1), "repeater")]
    assert rotation.rotation_invariant_signature(first) == rotation.rotation_invariant_signature(second)


def test_reflection_not_accepted_for_chiral_tokens():
    rows = [
        ((0, 0, 0), "dispenser"),
        ((1, 0, 0), "repeater"),
        ((0, 0, 1), "piston"),
        ((2, 0, 1), "redstone_wire"),
    ]
    mirrored = [((-point[0], point[1], point[2]), kind) for point, kind in rows]
    assert rotation.rotation_invariant_signature(rows) != rotation.rotation_invariant_signature(mirrored)


def main() -> int:
    tests = [
        test_rotation_and_translation_match,
        test_directional_metadata_is_explicitly_discarded,
        test_reflection_not_accepted_for_chiral_tokens,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} legacy rotation regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
