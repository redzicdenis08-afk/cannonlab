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


architecture = load(
    "legacy_cannon_architecture_global_tests",
    "legacy-cannon-architecture.py",
)
rotation = load(
    "legacy_cannon_rotation_compare_global_tests",
    "legacy-cannon-rotation-compare.py",
)
global_align = load(
    "legacy_cannon_global_align_tests",
    "legacy-cannon-global-align.py",
)


def machine():
    return {
        (0, 0, 0): "dispenser:2",
        (0, 1, 0): "dispenser:2",
        (1, 0, 0): "repeater:4",
        (2, 0, 1): "redstone_wire",
        (0, 2, 1): "sticky_piston:5",
        (-1, 3, 0): "redstone_block",
        (1, 1, -1): "stone_button:1",
        (3, 0, 1): "observer:2",
        (4, 0, 1): "comparator:1",
    }


def transform(blocks, turns, delta):
    output = {}
    for point, token in blocks.items():
        rotated = global_align.rotate_y(point, turns)
        output[
            (
                rotated[0] + delta[0],
                rotated[1] + delta[1],
                rotated[2] + delta[2],
            )
        ] = token
    return output


def place(blocks, delta):
    return {
        (
            point[0] + delta[0],
            point[1] + delta[1],
            point[2] + delta[2],
        ): token
        for point, token in blocks.items()
    }


def rotation_source(source_id, blocks):
    motifs, metadata = rotation.structural_motifs(architecture, blocks)
    contexts = rotation.structural_bank_contexts(architecture, blocks)
    return {
        "source_id": source_id,
        "structural_motif_counts": dict(motifs),
        "structural_motif_metadata": metadata,
        "structural_bank_contexts": contexts,
    }


def test_one_global_rotation_and_translation_reaches_exact_match() -> None:
    first = machine()
    second = transform(first, 1, (100, 20, -30))
    report = global_align.align_pair(architecture, first, second)
    best = report["best"]
    assert best["turns"] == 3, best
    assert best["translation"] == [30, -20, 100], best
    assert best["exact_kind_jaccard"] == 1.0, best
    assert best["first_exact_coverage"] == 1.0, best
    assert best["second_exact_coverage"] == 1.0, best
    assert report["confidence"] == "static-high", report


def test_local_motif_bag_cannot_fake_global_alignment() -> None:
    motif = {
        (0, 0, 0): "dispenser:2",
        (1, 0, 0): "repeater:4",
        (1, 0, 1): "redstone_wire",
        (0, 1, 0): "observer:2",
    }
    first = {**place(motif, (0, 0, 0)), **place(motif, (20, 0, 0))}
    second = {**place(motif, (0, 0, 0)), **place(motif, (40, 0, 0))}

    local = rotation.compare_sources(
        [rotation_source("first", first), rotation_source("second", second)]
    )["pairwise_similarity"][0]
    assert local["y_rotation_structural_motif_jaccard"] == 1.0, local

    global_report = global_align.align_pair(architecture, first, second)
    assert global_report["best"]["exact_kind_jaccard"] == 0.333333, global_report
    assert global_report["best"]["first_exact_coverage"] == 0.5, global_report
    assert global_report["best"]["second_exact_coverage"] == 0.5, global_report


def test_reflection_is_not_promoted_to_exact_alignment() -> None:
    first = machine()
    mirrored = {(-point[0], point[1], point[2]): token for point, token in first.items()}
    report = global_align.align_pair(architecture, first, mirrored)
    assert report["best"]["exact_kind_jaccard"] < 0.8, report
    assert report["best"]["exact_kind_overlap_count"] < len(first), report


def test_attachment_reduces_full_structure_score_without_hiding_core() -> None:
    first = machine()
    second = transform(first, 2, (50, 5, 70))
    second[(1000, 5, 1000)] = "observer:1"
    second[(1001, 5, 1000)] = "redstone_wire"
    report = global_align.align_pair(architecture, first, second)
    best = report["best"]
    assert best["exact_kind_overlap_count"] == len(first), best
    assert best["first_exact_coverage"] == 1.0, best
    assert best["second_exact_coverage"] == round(len(first) / (len(first) + 2), 6), best
    assert best["exact_kind_jaccard"] == round(len(first) / (len(first) + 2), 6), best


def test_candidate_budget_stays_bounded_on_repeated_panels() -> None:
    first = {}
    for x in range(20):
        for y in range(20):
            first[(x, y, 0)] = "dispenser:2"
    second = transform(first, 1, (500, 0, 500))
    report = global_align.align_pair(
        architecture,
        first,
        second,
        max_candidates_per_rotation=16,
        max_pairs_per_signature=256,
    )
    assert all(row["candidate_count"] <= 16 for row in report["candidate_summary"]), report
    assert report["best"]["exact_kind_jaccard"] == 1.0, report


def main() -> int:
    tests = [
        test_one_global_rotation_and_translation_reaches_exact_match,
        test_local_motif_bag_cannot_fake_global_alignment,
        test_reflection_is_not_promoted_to_exact_alignment,
        test_attachment_reduces_full_structure_score_without_hiding_core,
        test_candidate_budget_stays_bounded_on_repeated_panels,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} global legacy alignment regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
