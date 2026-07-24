#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable


class GlobalAlignmentError(ValueError):
    pass


NEIGHBOURS = (
    (1, 0, 0),
    (-1, 0, 0),
    (0, 1, 0),
    (0, -1, 0),
    (0, 0, 1),
    (0, 0, -1),
)


def load_architecture() -> Any:
    script = Path(__file__).resolve().with_name("legacy-cannon-architecture.py")
    spec = importlib.util.spec_from_file_location(
        "cannonlab_legacy_cannon_architecture_global", script
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def rotate_y(point: tuple[int, int, int], turns: int) -> tuple[int, int, int]:
    x, y, z = point
    turns %= 4
    if turns == 0:
        return x, y, z
    if turns == 1:
        return -z, y, x
    if turns == 2:
        return -x, y, -z
    return z, y, -x


def translate(
    point: tuple[int, int, int], delta: tuple[int, int, int]
) -> tuple[int, int, int]:
    return (
        point[0] + delta[0],
        point[1] + delta[1],
        point[2] + delta[2],
    )


def subtract(
    first: tuple[int, int, int], second: tuple[int, int, int]
) -> tuple[int, int, int]:
    return (
        first[0] - second[0],
        first[1] - second[1],
        first[2] - second[2],
    )


def kind_blocks(
    architecture: Any,
    blocks: dict[tuple[int, int, int], str],
) -> dict[tuple[int, int, int], str]:
    return {point: architecture.token_kind(token) for point, token in blocks.items()}


def rotate_blocks(
    blocks: dict[tuple[int, int, int], str], turns: int
) -> dict[tuple[int, int, int], str]:
    return {rotate_y(point, turns): kind for point, kind in blocks.items()}


def bounds(
    points: Iterable[tuple[int, int, int]],
) -> dict[str, tuple[int, int, int]] | None:
    points = list(points)
    if not points:
        return None
    minimum = tuple(min(point[axis] for point in points) for axis in range(3))
    maximum = tuple(max(point[axis] for point in points) for axis in range(3))
    return {"min": minimum, "max": maximum}


def signature(rows: list[list[Any]]) -> str:
    return hashlib.sha256(
        json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def oriented_anchor_signatures(
    architecture: Any,
    blocks: dict[tuple[int, int, int], str],
) -> dict[str, list[tuple[int, int, int]]]:
    output: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for anchor, anchor_kind in sorted(blocks.items()):
        if anchor_kind not in architecture.ANCHOR_KINDS:
            continue
        rows: list[list[Any]] = []
        for dx, dy, dz in architecture.MOTIF_OFFSETS:
            point = (anchor[0] + dx, anchor[1] + dy, anchor[2] + dz)
            kind = blocks.get(point)
            if kind is not None:
                rows.append([dx, dy, dz, kind])
        output[signature(rows)].append(anchor)
    return output


def expanded_contains(
    point: tuple[int, int, int],
    box: dict[str, tuple[int, int, int]],
    radius: int,
) -> bool:
    return all(
        box["min"][axis] - radius <= point[axis] <= box["max"][axis] + radius
        for axis in range(3)
    )


def structural_bank_signatures(
    architecture: Any,
    blocks: dict[tuple[int, int, int], str],
    *,
    radius: int = 6,
) -> dict[str, list[tuple[int, int, int]]]:
    dispenser_points = {point for point, kind in blocks.items() if kind == "dispenser"}
    output: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for group in architecture.groups_from_offsets(
        dispenser_points, architecture.PROXIMITY_OFFSETS
    ):
        box = bounds(group)
        if box is None:
            continue
        points = [point for point in blocks if expanded_contains(point, box, radius)]
        minimum = tuple(min(point[axis] for point in points) for axis in range(3))
        rows = sorted(
            [
                point[0] - minimum[0],
                point[1] - minimum[1],
                point[2] - minimum[2],
                blocks[point],
            ]
            for point in points
        )
        output[signature(rows)].append(minimum)
    return output


def add_signature_votes(
    votes: dict[tuple[int, int, int], float],
    support: dict[tuple[int, int, int], set[str]],
    first: dict[str, list[tuple[int, int, int]]],
    second: dict[str, list[tuple[int, int, int]]],
    *,
    prefix: str,
    max_pairs_per_signature: int,
) -> None:
    for key in sorted(set(first) & set(second)):
        first_points = first[key]
        second_points = second[key]
        product = len(first_points) * len(second_points)
        if product == 0 or product > max_pairs_per_signature:
            continue
        weight = 1.0 / product
        for first_point in first_points:
            for second_point in second_points:
                delta = subtract(first_point, second_point)
                votes[delta] += weight
                support[delta].add(f"{prefix}:{key}")


def candidate_translations(
    architecture: Any,
    first: dict[tuple[int, int, int], str],
    rotated_second: dict[tuple[int, int, int], str],
    *,
    max_candidates: int = 64,
    max_pairs_per_signature: int = 4096,
) -> list[dict[str, Any]]:
    votes: dict[tuple[int, int, int], float] = defaultdict(float)
    support: dict[tuple[int, int, int], set[str]] = defaultdict(set)

    add_signature_votes(
        votes,
        support,
        oriented_anchor_signatures(architecture, first),
        oriented_anchor_signatures(architecture, rotated_second),
        prefix="anchor",
        max_pairs_per_signature=max_pairs_per_signature,
    )
    add_signature_votes(
        votes,
        support,
        structural_bank_signatures(architecture, first),
        structural_bank_signatures(architecture, rotated_second),
        prefix="bank",
        max_pairs_per_signature=max_pairs_per_signature,
    )

    first_box = bounds(first)
    second_box = bounds(rotated_second)
    if first_box and second_box:
        for first_point, second_point, label in (
            (first_box["min"], second_box["min"], "bounds-min"),
            (first_box["max"], second_box["max"], "bounds-max"),
        ):
            delta = subtract(first_point, second_point)
            votes[delta] += 0.000001
            support[delta].add(label)

    rows = [
        {
            "translation": list(delta),
            "vote_weight": round(weight, 9),
            "supporting_signature_count": len(support[delta]),
        }
        for delta, weight in votes.items()
    ]
    rows.sort(
        key=lambda row: (
            -row["vote_weight"],
            -row["supporting_signature_count"],
            row["translation"],
        )
    )
    return rows[:max_candidates]


def largest_connected_component(points: set[tuple[int, int, int]]) -> int:
    remaining = set(points)
    largest = 0
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue = deque([start])
        size = 0
        while queue:
            point = queue.popleft()
            size += 1
            for dx, dy, dz in NEIGHBOURS:
                neighbour = (point[0] + dx, point[1] + dy, point[2] + dz)
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    queue.append(neighbour)
        largest = max(largest, size)
    return largest


def score_alignment(
    first: dict[tuple[int, int, int], str],
    second: dict[tuple[int, int, int], str],
    *,
    turns: int,
    translation_delta: tuple[int, int, int],
    vote_weight: float,
    supporting_signature_count: int,
) -> dict[str, Any]:
    transformed = {
        translate(rotate_y(point, turns), translation_delta): kind
        for point, kind in second.items()
    }
    shared_positions = set(first) & set(transformed)
    exact_positions = {
        point for point in shared_positions if first[point] == transformed[point]
    }
    conflicts = len(shared_positions) - len(exact_positions)
    exact = len(exact_positions)
    exact_union = len(first) + len(transformed) - exact
    occupied_union = len(set(first) | set(transformed))
    largest = largest_connected_component(exact_positions) if exact_positions else 0
    return {
        "turns": turns,
        "degrees": turns * 90,
        "translation": list(translation_delta),
        "exact_kind_overlap_count": exact,
        "exact_kind_jaccard": round(exact / exact_union, 6) if exact_union else 1.0,
        "first_exact_coverage": round(exact / len(first), 6) if first else 1.0,
        "second_exact_coverage": round(exact / len(second), 6) if second else 1.0,
        "occupied_position_overlap_count": len(shared_positions),
        "occupied_position_jaccard": (
            round(len(shared_positions) / occupied_union, 6) if occupied_union else 1.0
        ),
        "kind_conflict_count": conflicts,
        "kind_conflict_ratio_at_overlap": (
            round(conflicts / len(shared_positions), 6) if shared_positions else 0.0
        ),
        "largest_connected_exact_overlap": largest,
        "largest_connected_exact_overlap_ratio": (
            round(largest / exact, 6) if exact else 0.0
        ),
        "vote_weight": round(vote_weight, 9),
        "supporting_signature_count": supporting_signature_count,
    }


def alignment_confidence(best: dict[str, Any]) -> str:
    minimum_coverage = min(best["first_exact_coverage"], best["second_exact_coverage"])
    jaccard = best["exact_kind_jaccard"]
    if jaccard >= 0.75 and minimum_coverage >= 0.75:
        return "static-high"
    if jaccard >= 0.45 and minimum_coverage >= 0.5:
        return "static-medium"
    if jaccard >= 0.15:
        return "static-low"
    return "static-weak"


def align_pair(
    architecture: Any,
    first: dict[tuple[int, int, int], str],
    second: dict[tuple[int, int, int], str],
    *,
    max_candidates_per_rotation: int = 64,
    max_pairs_per_signature: int = 4096,
) -> dict[str, Any]:
    first_kinds = kind_blocks(architecture, first)
    second_kinds = kind_blocks(architecture, second)
    if not first_kinds or not second_kinds:
        raise GlobalAlignmentError("global alignment requires two non-empty functional maps")

    scored: list[dict[str, Any]] = []
    candidate_summary: list[dict[str, Any]] = []
    for turns in range(4):
        rotated_second = rotate_blocks(second_kinds, turns)
        candidates = candidate_translations(
            architecture,
            first_kinds,
            rotated_second,
            max_candidates=max_candidates_per_rotation,
            max_pairs_per_signature=max_pairs_per_signature,
        )
        candidate_summary.append(
            {"turns": turns, "degrees": turns * 90, "candidate_count": len(candidates)}
        )
        for candidate in candidates:
            delta = tuple(int(value) for value in candidate["translation"])
            scored.append(
                score_alignment(
                    first_kinds,
                    second_kinds,
                    turns=turns,
                    translation_delta=delta,
                    vote_weight=float(candidate["vote_weight"]),
                    supporting_signature_count=int(candidate["supporting_signature_count"]),
                )
            )

    if not scored:
        raise GlobalAlignmentError("no bounded global alignment candidates were generated")
    scored.sort(
        key=lambda row: (
            -row["exact_kind_jaccard"],
            -min(row["first_exact_coverage"], row["second_exact_coverage"]),
            -row["exact_kind_overlap_count"],
            row["kind_conflict_count"],
            -row["vote_weight"],
            row["turns"],
            row["translation"],
        )
    )
    best = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None
    gap = (
        round(best["exact_kind_jaccard"] - runner_up["exact_kind_jaccard"], 6)
        if runner_up
        else best["exact_kind_jaccard"]
    )
    equivalent_best_count = sum(
        row["exact_kind_jaccard"] == best["exact_kind_jaccard"]
        and row["exact_kind_overlap_count"] == best["exact_kind_overlap_count"]
        for row in scored
    )
    return {
        "best": best,
        "runner_up": runner_up,
        "uniqueness_gap": gap,
        "equivalent_best_count": equivalent_best_count,
        "confidence": alignment_confidence(best),
        "candidate_summary": candidate_summary,
        "comparison_model": (
            "one global rigid transform selected from four Y-axis quarter-turns and bounded "
            "translation votes; functional token kinds only; no reflection, scaling, or local warping"
        ),
        "truth_boundary": {
            "single_global_transform_tested": True,
            "directional_metadata_preserved": False,
            "reflection_matching_performed": False,
            "local_module_rearrangement_can_pass_as_global_alignment": False,
            "runtime_semantics_confirmed": False,
            "ec_ready": False,
        },
    }


def build_report(source_paths: list[tuple[str, Path]]) -> dict[str, Any]:
    architecture = load_architecture()
    sources: list[dict[str, Any]] = []
    maps: dict[str, dict[tuple[int, int, int], str]] = {}
    for source_id, path in source_paths:
        blocks, metadata = architecture.extract_functional_blocks(path)
        maps[source_id] = blocks
        sources.append(
            {
                "id": source_id,
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "functional_component_count": len(blocks),
                "dimensions": metadata["dimensions"],
            }
        )

    pairs: list[dict[str, Any]] = []
    for index, first in enumerate(sources):
        for second in sources[index + 1 :]:
            alignment = align_pair(architecture, maps[first["id"]], maps[second["id"]])
            pairs.append({"first": first["id"], "second": second["id"], **alignment})
    pairs.sort(
        key=lambda row: (
            -row["best"]["exact_kind_jaccard"],
            -row["best"]["exact_kind_overlap_count"],
            row["first"],
            row["second"],
        )
    )
    return {
        "schema_version": 1,
        "status": "PASS",
        "classification": "LEGACY_STATIC_SINGLE_GLOBAL_TRANSFORM_ONLY",
        "sources": sources,
        "pairwise_global_alignment": pairs,
        "summary": {
            "source_count": len(sources),
            "pair_count": len(pairs),
            "strongest_pair": (
                {
                    "first": pairs[0]["first"],
                    "second": pairs[0]["second"],
                    "exact_kind_jaccard": pairs[0]["best"]["exact_kind_jaccard"],
                }
                if pairs
                else None
            ),
        },
        "truth_boundary": {
            "single_global_rigid_transform_tested": True,
            "directional_metadata_preserved": False,
            "reflection_matching_performed": False,
            "static_alignment_proves_shared_runtime_semantics": False,
            "private_extremecraft_parity_confirmed": False,
            "ec_ready": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Test whether legacy cannon structures share one global Y-rotation and translation, "
            "rather than merely sharing a bag of independently rotated local motifs"
        )
    )
    parser.add_argument("--source", action="append", required=True, help="ID=PATH")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        architecture = load_architecture()
        source_paths = [architecture.parse_source(raw) for raw in args.source]
        ids = [source_id for source_id, _path in source_paths]
        if len(set(ids)) != len(ids):
            raise GlobalAlignmentError("source IDs must be unique")
        report = build_report(source_paths)
    except (OSError, ValueError, GlobalAlignmentError) as exc:
        report = {
            "schema_version": 1,
            "status": "FAIL",
            "error": str(exc),
            "truth_boundary": {
                "private_extremecraft_parity_confirmed": False,
                "ec_ready": False,
            },
        }
    if args.json_out:
        write_json(args.json_out.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
