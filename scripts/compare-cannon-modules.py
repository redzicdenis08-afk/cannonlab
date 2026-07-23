#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_module_map() -> Any:
    script = Path(__file__).resolve().with_name("cannon-module-map.py")
    spec = importlib.util.spec_from_file_location("cannonlab_module_map", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dimensions(module: dict[str, Any]) -> tuple[int, int, int]:
    values = (module.get("bounds") or {}).get("dimensions") or {}
    return tuple(int(values.get(axis) or 0) for axis in ("x", "y", "z"))


def origin(module: dict[str, Any]) -> tuple[int, int, int]:
    values = (module.get("bounds") or {}).get("min") or [0, 0, 0]
    return tuple(map(int, values))


def type_overlap(first: dict[str, Any], second: dict[str, Any]) -> float:
    left = Counter({key: int(value) for key, value in (first.get("block_type_counts") or {}).items()})
    right = Counter({key: int(value) for key, value in (second.get("block_type_counts") or {}).items()})
    union = set(left) | set(right)
    denominator = sum(max(left[key], right[key]) for key in union)
    if denominator == 0:
        return 1.0
    return sum(min(left[key], right[key]) for key in union) / denominator


def dimension_similarity(first: dict[str, Any], second: dict[str, Any]) -> float:
    left = dimensions(first)
    right = dimensions(second)
    denominator = max(1, sum(max(left[index], right[index]) for index in range(3)))
    return max(0.0, 1.0 - sum(abs(left[index] - right[index]) for index in range(3)) / denominator)


def scalar_similarity(first: int, second: int) -> float:
    return min(first, second) / max(1, max(first, second))


def near_similarity(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    type_score = type_overlap(first, second)
    dimension_score = dimension_similarity(first, second)
    dispenser_score = scalar_similarity(
        int(first.get("seed_dispenser_count") or 0),
        int(second.get("seed_dispenser_count") or 0),
    )
    component_score = scalar_similarity(
        int(first.get("component_count") or 0),
        int(second.get("component_count") or 0),
    )
    kind_score = 1.0 if first.get("kind") == second.get("kind") else 0.0
    facing_score = (
        1.0
        if first.get("seed_facing") == second.get("seed_facing")
        else 0.0
    )
    score = (
        type_score * 0.40
        + dimension_score * 0.20
        + dispenser_score * 0.15
        + component_score * 0.10
        + kind_score * 0.10
        + facing_score * 0.05
    )
    return {
        "score": round(score, 6),
        "type_overlap": round(type_score, 6),
        "dimension_similarity": round(dimension_score, 6),
        "dispenser_similarity": round(dispenser_score, 6),
        "component_similarity": round(component_score, 6),
        "same_kind": bool(kind_score),
        "same_facing": bool(facing_score),
    }


def compact_module(module: dict[str, Any]) -> dict[str, Any]:
    return {
        "module_id": module.get("module_id"),
        "kind": module.get("kind"),
        "component_count": module.get("component_count"),
        "seed_dispenser_count": module.get("seed_dispenser_count"),
        "seed_facing": module.get("seed_facing"),
        "bounds": module.get("bounds"),
        "block_type_counts": module.get("block_type_counts"),
        "role_candidates": module.get("role_candidates"),
        "signature": module.get("signature"),
    }


def index_by_signature(modules: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for module in modules:
        output[str(module.get("signature"))].append(module)
    for members in output.values():
        members.sort(key=lambda row: (origin(row), str(row.get("module_id"))))
    return output


def translation_vector(
    first: dict[str, Any],
    second: dict[str, Any],
) -> tuple[int, int, int]:
    first_origin = origin(first)
    second_origin = origin(second)
    return tuple(second_origin[axis] - first_origin[axis] for axis in range(3))


def translation_distance(
    translation: tuple[int, int, int],
    expected: tuple[int, int, int],
) -> int:
    return sum(abs(translation[axis] - expected[axis]) for axis in range(3))


def dominant_translation(
    first_index: dict[str, list[dict[str, Any]]],
    second_index: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    weighted_votes: Counter[tuple[int, int, int]] = Counter()
    instance_votes: Counter[tuple[int, int, int]] = Counter()
    for signature in sorted(set(first_index) & set(second_index)):
        left = first_index[signature]
        right = second_index[signature]
        weight = max(1, int(left[0].get("component_count") or 0))
        for first in left:
            for second in right:
                translation = translation_vector(first, second)
                weighted_votes[translation] += weight
                instance_votes[translation] += 1

    if not weighted_votes:
        return {
            "selected": [0, 0, 0],
            "weighted_votes": 0,
            "instance_votes": 0,
            "candidate_count": 0,
            "top_candidates": [],
            "truth_boundary": "no exact shared module signatures were available for translation voting",
        }

    ranked = sorted(
        weighted_votes,
        key=lambda translation: (
            -weighted_votes[translation],
            -instance_votes[translation],
            sum(abs(value) for value in translation),
            translation,
        ),
    )
    selected = ranked[0]
    top_weight = weighted_votes[selected]
    top_instances = instance_votes[selected]
    equally_ranked = [
        translation
        for translation in ranked
        if weighted_votes[translation] == top_weight
        and instance_votes[translation] == top_instances
    ]
    return {
        "selected": list(selected),
        "weighted_votes": top_weight,
        "instance_votes": top_instances,
        "candidate_count": len(ranked),
        "ambiguous_top_vote": len(equally_ranked) > 1,
        "equally_ranked_translations": [
            list(translation)
            for translation in equally_ranked[:16]
        ],
        "top_candidates": [
            {
                "translation": list(translation),
                "weighted_votes": weighted_votes[translation],
                "instance_votes": instance_votes[translation],
            }
            for translation in ranked[:16]
        ],
        "truth_boundary": (
            "the selected vector is a corpus-wide static alignment vote; each paired instance still reports residual distance"
        ),
    }


def pair_signature_instances(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    expected_translation: tuple[int, int, int],
) -> list[tuple[dict[str, Any], dict[str, Any], tuple[int, int, int], int]]:
    remaining_right = list(right)
    pairs: list[tuple[dict[str, Any], dict[str, Any], tuple[int, int, int], int]] = []
    for first in sorted(left, key=lambda row: (origin(row), str(row.get("module_id")))):
        if not remaining_right:
            break
        candidates = sorted(
            remaining_right,
            key=lambda second: (
                translation_distance(translation_vector(first, second), expected_translation),
                origin(second),
                str(second.get("module_id")),
            ),
        )
        second = candidates[0]
        remaining_right.remove(second)
        translation = translation_vector(first, second)
        pairs.append((
            first,
            second,
            translation,
            translation_distance(translation, expected_translation),
        ))
    return pairs


def exact_matches(
    first_modules: list[dict[str, Any]],
    second_modules: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str], set[str], dict[str, Any]]:
    first_index = index_by_signature(first_modules)
    second_index = index_by_signature(second_modules)
    translation_report = dominant_translation(first_index, second_index)
    expected_translation = tuple(map(int, translation_report["selected"]))
    matches: list[dict[str, Any]] = []
    used_first: set[str] = set()
    used_second: set[str] = set()
    total_pairs = 0
    zero_residual_pairs = 0
    residual_total = 0
    maximum_residual = 0

    for signature in sorted(set(first_index) & set(second_index)):
        left = first_index[signature]
        right = second_index[signature]
        paired = pair_signature_instances(left, right, expected_translation)
        pair_rows = []
        for first, second, translation, residual in paired:
            first_id = str(first.get("module_id"))
            second_id = str(second.get("module_id"))
            used_first.add(first_id)
            used_second.add(second_id)
            total_pairs += 1
            zero_residual_pairs += int(residual == 0)
            residual_total += residual
            maximum_residual = max(maximum_residual, residual)
            pair_rows.append({
                "first_module_id": first_id,
                "second_module_id": second_id,
                "translation_vector": list(translation),
                "dominant_translation_residual": residual,
                "component_count": int(first.get("component_count") or 0),
                "seed_dispenser_count": int(first.get("seed_dispenser_count") or 0),
            })
        matches.append({
            "signature": signature,
            "instances_first": len(left),
            "instances_second": len(right),
            "matched_instances": len(paired),
            "component_count_per_instance": int(left[0].get("component_count") or 0),
            "seed_dispenser_count_per_instance": int(left[0].get("seed_dispenser_count") or 0),
            "kind": left[0].get("kind"),
            "seed_facing": left[0].get("seed_facing"),
            "pairs": pair_rows,
            "evidence": (
                "exact canonical block-state geometry after translation; instances are paired against the dominant global translation"
            ),
        })

    matches.sort(
        key=lambda row: (
            -row["component_count_per_instance"] * row["matched_instances"],
            -row["seed_dispenser_count_per_instance"],
            row["signature"],
        )
    )
    translation_report["paired_instances"] = total_pairs
    translation_report["zero_residual_pairs"] = zero_residual_pairs
    translation_report["zero_residual_share"] = round(
        zero_residual_pairs / max(1, total_pairs), 6
    )
    translation_report["mean_residual_distance"] = round(
        residual_total / max(1, total_pairs), 6
    )
    translation_report["max_residual_distance"] = maximum_residual
    translation_report["pairing_confidence"] = (
        "high"
        if total_pairs and zero_residual_pairs == total_pairs
        else "medium"
        if total_pairs and zero_residual_pairs / total_pairs >= 0.70
        else "low"
    )
    return matches, used_first, used_second, translation_report


def near_matches(
    first_modules: list[dict[str, Any]],
    second_modules: list[dict[str, Any]],
    used_first: set[str],
    used_second: set[str],
    threshold: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for first in first_modules:
        first_id = str(first.get("module_id"))
        if first_id in used_first:
            continue
        for second in second_modules:
            second_id = str(second.get("module_id"))
            if second_id in used_second:
                continue
            similarity = near_similarity(first, second)
            if float(similarity["score"]) < threshold:
                continue
            candidates.append({
                "first_module_id": first_id,
                "second_module_id": second_id,
                "similarity": similarity,
                "first": compact_module(first),
                "second": compact_module(second),
                "evidence": (
                    "feature-level near match only; block-for-block equivalence and shared runtime role are not proven"
                ),
            })

    candidates.sort(
        key=lambda row: (
            -float(row["similarity"]["score"]),
            -min(
                int(row["first"].get("component_count") or 0),
                int(row["second"].get("component_count") or 0),
            ),
            row["first_module_id"],
            row["second_module_id"],
        )
    )
    selected: list[dict[str, Any]] = []
    claimed_first: set[str] = set()
    claimed_second: set[str] = set()
    for candidate in candidates:
        first_id = candidate["first_module_id"]
        second_id = candidate["second_module_id"]
        if first_id in claimed_first or second_id in claimed_second:
            continue
        claimed_first.add(first_id)
        claimed_second.add(second_id)
        selected.append(candidate)
    return selected


def architecture_delta(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(set(first) | set(second))
    return {
        key: {
            "first": first.get(key),
            "second": second.get(key),
            "delta": (
                second.get(key) - first.get(key)
                if isinstance(first.get(key), (int, float))
                and isinstance(second.get(key), (int, float))
                else None
            ),
        }
        for key in keys
    }


def build_report(
    first_path: Path,
    second_path: Path,
    *,
    chunk_limit: int = 160,
    assignment_radius: int = 6,
    near_match_threshold: float = 0.82,
    minimum_shared_core_components: int = 8,
) -> dict[str, Any]:
    module_map = load_module_map()
    first = module_map.build_report(first_path, chunk_limit, assignment_radius)
    second = module_map.build_report(second_path, chunk_limit, assignment_radius)
    first_modules = list(first.get("modules") or [])
    second_modules = list(second.get("modules") or [])

    exact, used_first, used_second, translation_alignment = exact_matches(first_modules, second_modules)
    near = near_matches(
        first_modules,
        second_modules,
        used_first,
        used_second,
        near_match_threshold,
    )
    first_total = sum(int(module.get("component_count") or 0) for module in first_modules)
    second_total = sum(int(module.get("component_count") or 0) for module in second_modules)
    exact_components = sum(
        row["component_count_per_instance"] * row["matched_instances"]
        for row in exact
    )
    exact_dispensers = sum(
        row["seed_dispenser_count_per_instance"] * row["matched_instances"]
        for row in exact
    )
    shared_core_candidates = [
        row
        for row in exact
        if row["component_count_per_instance"] >= minimum_shared_core_components
    ]

    unmatched_first = [
        compact_module(module)
        for module in first_modules
        if str(module.get("module_id")) not in used_first
    ]
    unmatched_second = [
        compact_module(module)
        for module in second_modules
        if str(module.get("module_id")) not in used_second
    ]
    unmatched_first.sort(key=lambda row: (-int(row.get("component_count") or 0), str(row.get("module_id"))))
    unmatched_second.sort(key=lambda row: (-int(row.get("component_count") or 0), str(row.get("module_id"))))

    return {
        "status": "PASS",
        "schema": "cannonlab-module-comparison-v2",
        "first": {
            "file": str(first_path),
            "file_sha256": first.get("file_sha256"),
            "architecture_summary": first.get("architecture_summary"),
        },
        "second": {
            "file": str(second_path),
            "file_sha256": second.get("file_sha256"),
            "architecture_summary": second.get("architecture_summary"),
        },
        "configuration": {
            "chunk_limit": chunk_limit,
            "assignment_radius": assignment_radius,
            "near_match_threshold": near_match_threshold,
            "minimum_shared_core_components": minimum_shared_core_components,
        },
        "summary": {
            "exact_signature_families": len(exact),
            "exact_module_instances": sum(row["matched_instances"] for row in exact),
            "exact_shared_components": exact_components,
            "exact_shared_dispensers": exact_dispensers,
            "first_exact_component_coverage": round(exact_components / max(1, first_total), 6),
            "second_exact_component_coverage": round(exact_components / max(1, second_total), 6),
            "shared_core_candidate_families": len(shared_core_candidates),
            "near_match_candidates": len(near),
            "unmatched_first_modules": len(unmatched_first),
            "unmatched_second_modules": len(unmatched_second),
        },
        "translation_alignment": translation_alignment,
        "architecture_delta": architecture_delta(
            first.get("architecture_summary") or {},
            second.get("architecture_summary") or {},
        ),
        "shared_core_candidates": shared_core_candidates,
        "exact_module_matches": exact,
        "near_match_candidates": near,
        "unmatched_first_modules": unmatched_first,
        "unmatched_second_modules": unmatched_second,
        "truth_boundary": {
            "exact_geometry_shared": bool(exact),
            "runtime_role_shared": False,
            "note": (
                "Exact matches prove canonical block-state geometry after translation. Near matches are heuristic. "
                "Neither proves that two modules fire in the same phase or serve the same charge, booster, hammer, "
                "sand, payload, nuke, OSRB, leftshot, or reverse function. Confirm with causal runtime traces."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find exact shared cannon modules and conservative near matches between two real schematics"
    )
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--assignment-radius", type=int, default=6)
    parser.add_argument("--near-match-threshold", type=float, default=0.82)
    parser.add_argument("--minimum-shared-core-components", type=int, default=8)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_report(
        args.first,
        args.second,
        chunk_limit=args.chunk_limit,
        assignment_radius=args.assignment_radius,
        near_match_threshold=args.near_match_threshold,
        minimum_shared_core_components=args.minimum_shared_core_components,
    )
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
