#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
LOW_SIGNAL_ANCHOR_TYPES = {
    "minecraft:air",
    "minecraft:cave_air",
    "minecraft:void_air",
    "minecraft:redstone_wire",
    "minecraft:water",
    "minecraft:lava",
    "minecraft:sand",
    "minecraft:red_sand",
    "minecraft:gravel",
    "minecraft:scaffolding",
    "minecraft:dispenser",
}
CONTROL_SUFFIXES = ("_button", "_pressure_plate")
TIMING_TYPES = {
    "minecraft:repeater",
    "minecraft:comparator",
    "minecraft:observer",
    "minecraft:redstone_torch",
    "minecraft:redstone_wall_torch",
    "minecraft:tripwire",
    "minecraft:tripwire_hook",
}
MOTION_TYPES = {
    "minecraft:piston",
    "minecraft:sticky_piston",
    "minecraft:piston_head",
    "minecraft:moving_piston",
    "minecraft:slime_block",
    "minecraft:honey_block",
}
FACE_NEIGHBOURS = (
    (1, 0, 0),
    (-1, 0, 0),
    (0, 1, 0),
    (0, -1, 0),
    (0, 0, 1),
    (0, 0, -1),
)
SUPPORT_OFFSETS = tuple(
    (dx, dy, dz)
    for dx in range(-2, 3)
    for dy in range(-2, 3)
    for dz in range(-2, 3)
    if (dx, dy, dz) != (0, 0, 0)
    and max(abs(dx), abs(dy), abs(dz)) <= 2
    and abs(dx) + abs(dy) + abs(dz) <= 3
)


def load_script(name: str, filename: str) -> Any:
    script = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decode(path: Path, auditor: Any) -> dict[str, Any]:
    loaded = auditor.load(path)
    root_name, root = loaded[0], loaded[1]
    model = auditor.decode_any(root_name, root)
    model["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return model


def canonical_state(auditor: Any, state: str) -> str:
    block_type = auditor.base(state)
    properties = {
        key: value
        for key, value in auditor.properties(state).items()
        if key not in {"power", "powered", "triggered", "lit"}
    }
    if not properties:
        return block_type
    return block_type + "[" + ",".join(
        f"{key}={properties[key]}" for key in sorted(properties)
    ) + "]"


def canonical_blocks(
    auditor: Any,
    blocks: dict[tuple[int, int, int], str],
) -> dict[tuple[int, int, int], str]:
    return {
        point: canonical_state(auditor, state)
        for point, state in blocks.items()
        if auditor.base(state) not in AIR
    }


def functional_blocks(
    auditor: Any,
    module_map: Any,
    blocks: dict[tuple[int, int, int], str],
) -> dict[tuple[int, int, int], str]:
    return {
        point: canonical_state(auditor, state)
        for point, state in blocks.items()
        if module_map.is_functional_type(auditor.base(state))
    }


def block_type(state: str) -> str:
    return state.split("[", 1)[0]


def is_control(block: str) -> bool:
    return block == "minecraft:lever" or block.endswith(CONTROL_SUFFIXES)


def bounds(points: Iterable[tuple[int, int, int]]) -> dict[str, Any] | None:
    points = list(points)
    if not points:
        return None
    minimum = [min(point[axis] for point in points) for axis in range(3)]
    maximum = [max(point[axis] for point in points) for axis in range(3)]
    dimensions = [maximum[axis] - minimum[axis] + 1 for axis in range(3)]
    return {
        "min": minimum,
        "max": maximum,
        "dimensions": {"x": dimensions[0], "y": dimensions[1], "z": dimensions[2]},
        "volume": dimensions[0] * dimensions[1] * dimensions[2],
    }


def translated(point: tuple[int, int, int], vector: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(point[axis] + vector[axis] for axis in range(3))


def micro_signature(
    functional: dict[tuple[int, int, int], str],
    point: tuple[int, int, int],
    radius: int,
) -> tuple[str, int]:
    rows: list[tuple[int, int, int, str]] = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                if max(abs(dx), abs(dy), abs(dz)) > radius:
                    continue
                if abs(dx) + abs(dy) + abs(dz) > radius + 1:
                    continue
                state = functional.get((point[0] + dx, point[1] + dy, point[2] + dz))
                if state is not None:
                    rows.append((dx, dy, dz, state))
    encoded = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(rows)


def anchor_index(
    functional: dict[tuple[int, int, int], str],
    radius: int,
    minimum_neighbours: int,
) -> dict[str, list[tuple[tuple[int, int, int], int]]]:
    output: dict[str, list[tuple[tuple[int, int, int], int]]] = defaultdict(list)
    for point, state in functional.items():
        if block_type(state) in LOW_SIGNAL_ANCHOR_TYPES:
            continue
        signature, size = micro_signature(functional, point, radius)
        if size < minimum_neighbours:
            continue
        output[signature].append((point, size))
    for values in output.values():
        values.sort()
    return dict(output)


def candidate_translations(
    first_functional: dict[tuple[int, int, int], str],
    second_functional: dict[tuple[int, int, int], str],
    radius: int,
    minimum_neighbours: int,
    max_anchor_instances: int,
    top_translations: int,
) -> tuple[list[tuple[int, int, int]], dict[str, Any]]:
    first_index = anchor_index(first_functional, radius, minimum_neighbours)
    second_index = anchor_index(second_functional, radius, minimum_neighbours)
    weighted_votes: Counter[tuple[int, int, int]] = Counter()
    instance_votes: Counter[tuple[int, int, int]] = Counter()
    matched_signatures = 0
    skipped_repetitive_signatures = 0

    for signature in sorted(set(first_index) & set(second_index)):
        first_members = first_index[signature]
        second_members = second_index[signature]
        if len(first_members) > max_anchor_instances or len(second_members) > max_anchor_instances:
            skipped_repetitive_signatures += 1
            continue
        matched_signatures += 1
        rarity = max(1, max_anchor_instances // max(len(first_members), len(second_members)))
        for first_point, first_size in first_members:
            for second_point, second_size in second_members:
                vector = tuple(second_point[axis] - first_point[axis] for axis in range(3))
                weight = max(1, min(first_size, second_size, 16)) * rarity
                weighted_votes[vector] += weight
                instance_votes[vector] += 1

    # Rare canonical states are a fallback for sparse timing/control cores that do not
    # have enough intact local neighbourhoods to produce a micro-signature vote.
    first_by_state: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    second_by_state: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for point, state in first_functional.items():
        if block_type(state) not in LOW_SIGNAL_ANCHOR_TYPES:
            first_by_state[state].append(point)
    for point, state in second_functional.items():
        if block_type(state) not in LOW_SIGNAL_ANCHOR_TYPES:
            second_by_state[state].append(point)
    rare_state_votes = 0
    for state in sorted(set(first_by_state) & set(second_by_state)):
        left = first_by_state[state]
        right = second_by_state[state]
        if len(left) > 12 or len(right) > 12:
            continue
        for first_point in left:
            for second_point in right:
                vector = tuple(second_point[axis] - first_point[axis] for axis in range(3))
                weighted_votes[vector] += 1
                instance_votes[vector] += 1
                rare_state_votes += 1

    ranked = sorted(
        weighted_votes,
        key=lambda vector: (
            -weighted_votes[vector],
            -instance_votes[vector],
            sum(abs(value) for value in vector),
            vector,
        ),
    )[:top_translations]
    if not ranked:
        ranked = [(0, 0, 0)]
    evidence = {
        "anchor_radius": radius,
        "minimum_anchor_neighbours": minimum_neighbours,
        "matched_micro_signatures": matched_signatures,
        "skipped_repetitive_signatures": skipped_repetitive_signatures,
        "rare_state_pair_votes": rare_state_votes,
        "candidate_count": len(weighted_votes),
        "top_vote_candidates": [
            {
                "translation": list(vector),
                "weighted_votes": weighted_votes[vector],
                "instance_votes": instance_votes[vector],
            }
            for vector in ranked[:10]
        ],
    }
    return ranked, evidence


def connected_components(
    points: set[tuple[int, int, int]],
    offsets: tuple[tuple[int, int, int], ...],
) -> list[list[tuple[int, int, int]]]:
    remaining = set(points)
    output: list[list[tuple[int, int, int]]] = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue = deque([start])
        component: list[tuple[int, int, int]] = []
        while queue:
            point = queue.popleft()
            component.append(point)
            for delta in offsets:
                neighbour = tuple(point[axis] + delta[axis] for axis in range(3))
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    queue.append(neighbour)
        output.append(sorted(component))
    return sorted(output, key=lambda component: (-len(component), component[0]))


def overlap_category_counts(
    states: Iterable[str],
) -> dict[str, int]:
    counts = Counter(block_type(state) for state in states)
    return {
        "dispensers": counts["minecraft:dispenser"],
        "wiring_components": (
            counts["minecraft:redstone_wire"]
            + counts["minecraft:redstone_block"]
            + counts["minecraft:redstone_torch"]
            + counts["minecraft:redstone_wall_torch"]
        ),
        "timing_components": (
            counts["minecraft:repeater"]
            + counts["minecraft:comparator"]
            + counts["minecraft:observer"]
            + counts["minecraft:tripwire"]
            + counts["minecraft:tripwire_hook"]
        ),
        "motion_components": sum(counts[name] for name in MOTION_TYPES),
        "controls": sum(value for name, value in counts.items() if is_control(name)),
        "fluids": counts["minecraft:water"] + counts["minecraft:lava"],
        "falling_payload_blocks": (
            counts["minecraft:sand"]
            + counts["minecraft:red_sand"]
            + counts["minecraft:gravel"]
            + sum(value for name, value in counts.items() if name.endswith("_concrete_powder"))
        ),
    }


def evaluate_translation(
    vector: tuple[int, int, int],
    first_non_air: dict[tuple[int, int, int], str],
    second_non_air: dict[tuple[int, int, int], str],
    first_functional: dict[tuple[int, int, int], str],
    second_functional: dict[tuple[int, int, int], str],
) -> dict[str, Any]:
    exact_functional = {
        point: state
        for point, state in first_functional.items()
        if second_functional.get(translated(point, vector)) == state
    }
    same_type_functional = {
        point: state
        for point, state in first_functional.items()
        if block_type(second_functional.get(translated(point, vector), "minecraft:air")) == block_type(state)
    }
    exact_non_air = {
        point: state
        for point, state in first_non_air.items()
        if second_non_air.get(translated(point, vector)) == state
    }
    face_components = connected_components(set(exact_functional), FACE_NEIGHBOURS)
    support_components = connected_components(set(exact_functional), SUPPORT_OFFSETS)
    first_functional_count = len(first_functional)
    second_functional_count = len(second_functional)
    first_non_air_count = len(first_non_air)
    second_non_air_count = len(second_non_air)
    return {
        "translation": list(vector),
        "exact_functional": len(exact_functional),
        "same_type_functional": len(same_type_functional),
        "exact_non_air": len(exact_non_air),
        "first_functional_coverage": round(len(exact_functional) / max(1, first_functional_count), 6),
        "second_functional_coverage": round(len(exact_functional) / max(1, second_functional_count), 6),
        "first_non_air_coverage": round(len(exact_non_air) / max(1, first_non_air_count), 6),
        "second_non_air_coverage": round(len(exact_non_air) / max(1, second_non_air_count), 6),
        "largest_face_connected_functional": len(face_components[0]) if face_components else 0,
        "largest_support_connected_functional": len(support_components[0]) if support_components else 0,
        "functional_component_count": len(support_components),
        "overlap_bounds_in_first_frame": bounds(exact_functional),
        "overlap_categories": overlap_category_counts(exact_functional.values()),
        "exact_functional_type_counts": dict(sorted(Counter(map(block_type, exact_functional.values())).items())),
    }


def confidence(
    result: dict[str, Any],
    minimum_shared_functional: int,
    minimum_connected_functional: int,
    minimum_shared_non_dispenser: int,
    minimum_mechanism_diversity: int,
) -> tuple[bool, str, list[str]]:
    reasons: list[str] = []
    if result["exact_functional"] < minimum_shared_functional:
        reasons.append("exact_functional_below_threshold")
    if result["largest_support_connected_functional"] < minimum_connected_functional:
        reasons.append("connected_functional_core_below_threshold")
    category = result["overlap_categories"]
    non_dispenser_functional = result["exact_functional"] - category["dispensers"]
    if non_dispenser_functional < minimum_shared_non_dispenser:
        reasons.append("non_dispenser_functional_below_threshold")
    mechanism_diversity = sum(
        int(category[name] > 0)
        for name in (
            "wiring_components",
            "timing_components",
            "motion_components",
            "controls",
            "fluids",
            "falling_payload_blocks",
        )
    )
    nearly_identical = (
        result["first_functional_coverage"] >= 0.95
        and result["second_functional_coverage"] >= 0.95
    )
    if mechanism_diversity < minimum_mechanism_diversity and not nearly_identical:
        reasons.append("mechanism_diversity_below_threshold")
    candidate = not reasons
    if not candidate:
        return False, "none", reasons

    if (
        result["exact_functional"] >= max(64, minimum_shared_functional * 4)
        and result["largest_support_connected_functional"] >= max(32, minimum_connected_functional * 4)
        and mechanism_diversity >= 3
    ):
        return True, "high", []
    if mechanism_diversity >= 2:
        return True, "medium", []
    return True, "low", ["shared_geometry_has_low_mechanism_diversity"]


def build_report(
    first_path: Path,
    second_path: Path,
    anchor_radius: int,
    minimum_anchor_neighbours: int,
    max_anchor_instances: int,
    top_translations: int,
    minimum_shared_functional: int,
    minimum_connected_functional: int,
    minimum_shared_non_dispenser: int,
    minimum_mechanism_diversity: int,
) -> dict[str, Any]:
    auditor = load_script("cannonlab_schem_audit_core_compare", "schem-audit.py")
    module_map = load_script("cannonlab_module_map_core_compare", "cannon-module-map.py")
    first = decode(first_path, auditor)
    second = decode(second_path, auditor)
    first_non_air = canonical_blocks(auditor, first["blocks"])
    second_non_air = canonical_blocks(auditor, second["blocks"])
    first_functional = functional_blocks(auditor, module_map, first["blocks"])
    second_functional = functional_blocks(auditor, module_map, second["blocks"])

    candidates, vote_evidence = candidate_translations(
        first_functional,
        second_functional,
        anchor_radius,
        minimum_anchor_neighbours,
        max_anchor_instances,
        top_translations,
    )
    evaluated = [
        evaluate_translation(
            vector,
            first_non_air,
            second_non_air,
            first_functional,
            second_functional,
        )
        for vector in candidates
    ]
    evaluated.sort(
        key=lambda row: (
            -row["exact_functional"],
            -row["largest_support_connected_functional"],
            -row["exact_non_air"],
            sum(abs(value) for value in row["translation"]),
            row["translation"],
        )
    )
    selected = evaluated[0]
    is_candidate, confidence_level, reasons = confidence(
        selected,
        minimum_shared_functional,
        minimum_connected_functional,
        minimum_shared_non_dispenser,
        minimum_mechanism_diversity,
    )
    return {
        "status": "PASS",
        "schema": "cannonlab-translated-core-overlap-v1",
        "first": {
            "file": str(first_path),
            "file_sha256": first["file_sha256"],
            "format": first["format"],
            "data_version": first["data_version"],
            "dimensions": first["source_dimensions"],
            "non_air": len(first_non_air),
            "functional": len(first_functional),
        },
        "second": {
            "file": str(second_path),
            "file_sha256": second["file_sha256"],
            "format": second["format"],
            "data_version": second["data_version"],
            "dimensions": second["source_dimensions"],
            "non_air": len(second_non_air),
            "functional": len(second_functional),
        },
        "translation_search": vote_evidence,
        "selected_overlap": selected,
        "shared_core_candidate": is_candidate,
        "confidence": confidence_level,
        "reasons": reasons,
        "thresholds": {
            "minimum_shared_functional": minimum_shared_functional,
            "minimum_connected_functional": minimum_connected_functional,
            "minimum_shared_non_dispenser": minimum_shared_non_dispenser,
            "minimum_mechanism_diversity": minimum_mechanism_diversity,
        },
        "alternative_overlaps": evaluated[1:10],
        "truth_boundary": {
            "exact_translated_geometry": True,
            "runtime_role_shared": False,
            "ec_functionality_proven": False,
            "note": (
                "This report detects an exact translated partial geometry core even when whole-module "
                "boundaries differ. It does not prove that the shared cells fire in the same phase, have "
                "the same external inputs, or serve the same charge, booster, hammer, payload, nuke, "
                "OSRB, leftshot, reverse, slab-bust, bypass, double-tap, anti-patch, or worm role. "
                "Confirm with matched causal runtime traces and live ExtremeCraft canaries."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Find an exact translated partial functional core between two real cannons without "
            "requiring their inferred whole-module boundaries to match"
        )
    )
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--anchor-radius", type=int, default=2)
    parser.add_argument("--minimum-anchor-neighbours", type=int, default=3)
    parser.add_argument("--max-anchor-instances", type=int, default=48)
    parser.add_argument("--top-translations", type=int, default=32)
    parser.add_argument("--minimum-shared-functional", type=int, default=16)
    parser.add_argument("--minimum-connected-functional", type=int, default=8)
    parser.add_argument("--minimum-shared-non-dispenser", type=int, default=8)
    parser.add_argument("--minimum-mechanism-diversity", type=int, default=2)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if args.anchor_radius < 1 or args.anchor_radius > 4:
        parser.error("--anchor-radius must be between 1 and 4")
    if args.minimum_anchor_neighbours < 1:
        parser.error("--minimum-anchor-neighbours must be positive")
    if args.max_anchor_instances < 1 or args.top_translations < 1:
        parser.error("anchor and candidate limits must be positive")
    report = build_report(
        args.first,
        args.second,
        args.anchor_radius,
        args.minimum_anchor_neighbours,
        args.max_anchor_instances,
        args.top_translations,
        args.minimum_shared_functional,
        args.minimum_connected_functional,
        args.minimum_shared_non_dispenser,
        args.minimum_mechanism_diversity,
    )
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
