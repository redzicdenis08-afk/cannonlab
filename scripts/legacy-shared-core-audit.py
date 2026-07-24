#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any, Iterable


class SharedCoreError(ValueError):
    pass


FACE_NEIGHBOURS = (
    (1, 0, 0), (-1, 0, 0), (0, 1, 0),
    (0, -1, 0), (0, 0, 1), (0, 0, -1),
)
FACING_CODE_VECTORS = {
    0: (0, -1, 0), 1: (0, 1, 0), 2: (0, 0, -1),
    3: (0, 0, 1), 4: (-1, 0, 0), 5: (1, 0, 0),
}
VECTOR_FACING_CODES = {value: key for key, value in FACING_CODE_VECTORS.items()}
HORIZONTAL_FACING_VECTORS = {
    0: (0, 0, -1), 1: (1, 0, 0), 2: (0, 0, 1), 3: (-1, 0, 0),
}
VECTOR_HORIZONTAL_CODES = {value: key for key, value in HORIZONTAL_FACING_VECTORS.items()}

PROVEN_ROTATABLE_IDS = {23, 29, 33, 34, 93, 94, 149, 150, 218}
UNRESOLVED_DIRECTIONAL_IDS = {69, 75, 76, 77, 143}
MAX_LEGACY_VOLUME = 100_000_000
_MODULE_CACHE: dict[str, Any] = {}


def load_script(name: str, filename: str) -> Any:
    cached = _MODULE_CACHE.get(filename)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _MODULE_CACHE[filename] = module
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


def translate(point: tuple[int, int, int], delta: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(point[index] + delta[index] for index in range(3))  # type: ignore[return-value]


def transform_point(
    point: tuple[int, int, int], turns: int, delta: tuple[int, int, int]
) -> tuple[int, int, int]:
    return translate(rotate_y(point, turns), delta)


def rotate_legacy_data(block_id: int, data: int, turns: int) -> tuple[int, bool]:
    turns %= 4
    value = int(data) & 0xFF
    if turns == 0:
        return value, True
    if block_id in {23, 29, 33, 34, 218}:
        vector = FACING_CODE_VECTORS.get(value & 0x7)
        rotated = VECTOR_FACING_CODES.get(rotate_y(vector, turns)) if vector else None
        if rotated is None:
            return value, False
        return (value & ~0x7) | rotated, True
    if block_id in {93, 94, 149, 150}:
        vector = HORIZONTAL_FACING_VECTORS.get(value & 0x3)
        rotated = VECTOR_HORIZONTAL_CODES.get(rotate_y(vector, turns)) if vector else None
        if rotated is None:
            return value, False
        return (value & ~0x3) | rotated, True
    return value, False


def load_legacy_map(path: Path) -> tuple[dict[tuple[int, int, int], tuple[int, int]], dict[str, Any]]:
    legacy = load_script("cannonlab_legacy_shared_core_parser", "legacy-schematic-audit.py")
    root_name, root, decompressed_bytes = legacy.parse_root(path)
    width = legacy.require_int(root, "Width")
    height = legacy.require_int(root, "Height")
    length = legacy.require_int(root, "Length")
    if min(width, height, length) <= 0:
        raise SharedCoreError("legacy schematic dimensions must be positive")
    volume = width * height * length
    if volume > MAX_LEGACY_VOLUME:
        raise SharedCoreError(f"legacy schematic volume exceeds {MAX_LEGACY_VOLUME}")
    blocks = legacy.require_bytes(root, "Blocks")
    data = legacy.require_bytes(root, "Data")
    if len(blocks) != volume or len(data) != volume:
        raise SharedCoreError("legacy Blocks/Data length does not match volume")
    add_value = root.get("AddBlocks")
    add_blocks = add_value if isinstance(add_value, bytes) else None
    if add_blocks is not None and len(add_blocks) != (volume + 1) // 2:
        raise SharedCoreError("legacy AddBlocks length does not exactly match volume")

    output: dict[tuple[int, int, int], tuple[int, int]] = {}
    for index in range(volume):
        block_id = legacy.full_block_id(blocks, add_blocks, index)
        if block_id == 0:
            continue
        x = index % width
        z = (index // width) % length
        y = index // (width * length)
        output[(x, y, z)] = (block_id, data[index])
    return output, {
        "root_name": root_name,
        "dimensions": {"width": width, "height": height, "length": length},
        "volume": volume,
        "decompressed_bytes": decompressed_bytes,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def canonical_token(architecture: Any, value: tuple[int, int]) -> str:
    return architecture.canonical_token(value[0], value[1])


def kind_name(architecture: Any, value: tuple[int, int]) -> str:
    return architecture.token_kind(canonical_token(architecture, value))


def compare_block(
    architecture: Any,
    first: tuple[int, int],
    second: tuple[int, int],
    turns: int,
) -> str:
    first_kind = kind_name(architecture, first)
    second_kind = kind_name(architecture, second)
    if first_kind != second_kind:
        return "kind_conflict"

    first_id, _first_data = first
    second_id, second_data = second
    if turns % 4 and (
        first_id in UNRESOLVED_DIRECTIONAL_IDS or second_id in UNRESOLVED_DIRECTIONAL_IDS
    ):
        return "same_kind_unresolved_metadata"

    if second_id in PROVEN_ROTATABLE_IDS:
        rotated_data, proven = rotate_legacy_data(second_id, second_data, turns)
        if not proven:
            return "same_kind_unresolved_metadata"
        rotated_second = (second_id, rotated_data)
        return (
            "proven_equivalent"
            if canonical_token(architecture, first) == canonical_token(architecture, rotated_second)
            else "metadata_conflict"
        )

    return (
        "proven_equivalent"
        if canonical_token(architecture, first) == canonical_token(architecture, second)
        else "same_kind_unresolved_metadata"
    )


def face_components(points: set[tuple[int, int, int]]) -> list[list[tuple[int, int, int]]]:
    remaining = set(points)
    groups: list[list[tuple[int, int, int]]] = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue = deque([start])
        group: list[tuple[int, int, int]] = []
        while queue:
            point = queue.popleft()
            group.append(point)
            for delta in FACE_NEIGHBOURS:
                neighbour = tuple(point[index] + delta[index] for index in range(3))
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    queue.append(neighbour)
        groups.append(sorted(group))
    return sorted(groups, key=lambda row: (-len(row), row[0]))


def point_bounds(points: Iterable[tuple[int, int, int]]) -> dict[str, Any] | None:
    values = list(points)
    if not values:
        return None
    minimum = tuple(min(point[index] for point in values) for index in range(3))
    maximum = tuple(max(point[index] for point in values) for index in range(3))
    dimensions = tuple(maximum[index] - minimum[index] + 1 for index in range(3))
    return {
        "min": list(minimum),
        "max": list(maximum),
        "dimensions": {"x": dimensions[0], "y": dimensions[1], "z": dimensions[2]},
        "volume": dimensions[0] * dimensions[1] * dimensions[2],
    }


def normalized_signature(
    architecture: Any,
    points: Iterable[tuple[int, int, int]],
    first_map: dict[tuple[int, int, int], tuple[int, int]],
) -> str:
    values = list(points)
    box = point_bounds(values)
    if not box:
        return hashlib.sha256(b"[]").hexdigest()
    minimum = box["min"]
    rows = [
        [
            point[0] - minimum[0],
            point[1] - minimum[1],
            point[2] - minimum[2],
            canonical_token(architecture, first_map[point]),
        ]
        for point in sorted(values)
    ]
    return hashlib.sha256(
        json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def chunk_scan(
    points: Iterable[tuple[int, int, int]],
    first_map: dict[tuple[int, int, int], tuple[int, int]],
    limit: int,
) -> dict[str, Any]:
    dispensers = [point for point in points if first_map[point][0] == 23]
    best: int | None = None
    legal = 0
    for offset_x in range(16):
        for offset_z in range(16):
            counts: Counter[tuple[int, int]] = Counter(
                ((point[0] + offset_x) // 16, (point[2] + offset_z) // 16)
                for point in dispensers
            )
            maximum = max(counts.values(), default=0)
            best = maximum if best is None else min(best, maximum)
            legal += maximum <= limit
    return {
        "dispenser_count": len(dispensers),
        "best_max_dispensers_per_chunk": best or 0,
        "legal_offset_count": legal,
        "chunk_limit": limit,
    }


def boundary_summary(
    component: set[tuple[int, int, int]],
    first_all: dict[tuple[int, int, int], tuple[int, int]],
    transformed_second_all: dict[tuple[int, int, int], tuple[int, int]],
    architecture: Any,
) -> dict[str, Any]:
    first_crossings: set[tuple[tuple[int, int, int], tuple[int, int, int]]] = set()
    second_crossings: set[tuple[tuple[int, int, int], tuple[int, int, int]]] = set()
    first_outside_kinds: Counter[str] = Counter()
    second_outside_kinds: Counter[str] = Counter()
    for point in component:
        for delta in FACE_NEIGHBOURS:
            neighbour = tuple(point[index] + delta[index] for index in range(3))
            if neighbour in component:
                continue
            if neighbour in first_all:
                first_crossings.add((point, neighbour))
                first_outside_kinds[kind_name(architecture, first_all[neighbour])] += 1
            if neighbour in transformed_second_all:
                second_crossings.add((point, neighbour))
                second_outside_kinds[kind_name(architecture, transformed_second_all[neighbour])] += 1
    return {
        "first_nonair_face_crossing_count": len(first_crossings),
        "second_nonair_face_crossing_count": len(second_crossings),
        "combined_unique_face_crossing_count": len(first_crossings | second_crossings),
        "first_outside_kind_counts": dict(sorted(first_outside_kinds.items())),
        "second_outside_kind_counts": dict(sorted(second_outside_kinds.items())),
        "functionally_closed_in_both_sources": not first_crossings and not second_crossings,
        "truth_boundary": (
            "face-adjacent non-air boundary audit only; quasi-connectivity, redstone power propagation, "
            "piston motion reach, fluid flow, and runtime ownership remain unproven"
        ),
    }


def build_report(
    first_id: str,
    first_path: Path,
    second_id: str,
    second_path: Path,
    *,
    turns: int,
    translation_delta: tuple[int, int, int],
    chunk_limit: int,
    minimum_component_size: int,
) -> dict[str, Any]:
    if turns not in {0, 1, 2, 3}:
        raise SharedCoreError("turns must be 0, 1, 2, or 3")
    if chunk_limit <= 0:
        raise SharedCoreError("chunk_limit must be positive")
    if minimum_component_size <= 0:
        raise SharedCoreError("minimum_component_size must be positive")

    architecture = load_script(
        "cannonlab_legacy_shared_core_architecture", "legacy-cannon-architecture.py"
    )
    first_all, first_metadata = load_legacy_map(first_path)
    second_all, second_metadata = load_legacy_map(second_path)
    transformed_second_all = {
        transform_point(point, turns, translation_delta): value
        for point, value in second_all.items()
    }
    functional_ids = architecture.FUNCTIONAL_IDS
    first_functional = {point: value for point, value in first_all.items() if value[0] in functional_ids}
    second_functional = {
        point: value for point, value in transformed_second_all.items() if value[0] in functional_ids
    }

    shared_positions = set(first_functional) & set(second_functional)
    classification_counts: Counter[str] = Counter()
    proven_points: set[tuple[int, int, int]] = set()
    same_kind_points: set[tuple[int, int, int]] = set()
    for point in sorted(shared_positions):
        classification = compare_block(
            architecture, first_functional[point], second_functional[point], turns
        )
        classification_counts[classification] += 1
        if classification != "kind_conflict":
            same_kind_points.add(point)
        if classification == "proven_equivalent":
            proven_points.add(point)

    component_rows: list[dict[str, Any]] = []
    for index, points in enumerate(face_components(proven_points), start=1):
        if len(points) < minimum_component_size:
            continue
        point_set = set(points)
        type_counts = Counter(kind_name(architecture, first_functional[point]) for point in points)
        boundary = boundary_summary(point_set, first_all, transformed_second_all, architecture)
        status = (
            "CLOSED_STATIC_COMPONENT_CANDIDATE"
            if boundary["functionally_closed_in_both_sources"]
            else "OPEN_SHARED_REGION"
        )
        component_rows.append({
            "component_id": f"SHARED-{index:03d}",
            "status": status,
            "component_count": len(points),
            "bounds": point_bounds(points),
            "legacy_kind_counts": dict(sorted(type_counts.items())),
            "normalized_canonical_token_signature": normalized_signature(
                architecture, points, first_functional
            ),
            "ec160": chunk_scan(points, first_functional, chunk_limit),
            "boundary": boundary,
            "promotion_eligible": False,
            "truth_boundary": (
                "shared legacy static region only; no subsystem role, timing phase, standalone "
                "operation, conversion safety, or runtime causality is confirmed"
            ),
        })
    component_rows.sort(key=lambda row: (
        row["status"] != "CLOSED_STATIC_COMPONENT_CANDIDATE",
        -row["component_count"], row["component_id"],
    ))

    return {
        "schema_version": 1,
        "status": "PASS",
        "classification": "LEGACY_SHARED_CORE_STATIC_AUDIT_ONLY",
        "sources": [{"id": first_id, **first_metadata}, {"id": second_id, **second_metadata}],
        "transform": {
            "turns": turns,
            "degrees": turns * 90,
            "translation": list(translation_delta),
            "model": "single Y-axis quarter-turn plus translation; no reflection, scaling, or warping",
        },
        "overlap": {
            "shared_functional_position_count": len(shared_positions),
            "same_kind_position_count": len(same_kind_points),
            "proven_metadata_equivalent_position_count": len(proven_points),
            "classification_counts": dict(sorted(classification_counts.items())),
            "proven_equivalent_ratio_of_same_kind": (
                round(len(proven_points) / len(same_kind_points), 6) if same_kind_points else 0.0
            ),
        },
        "components": component_rows,
        "summary": {
            "minimum_component_size": minimum_component_size,
            "reported_component_count": len(component_rows),
            "closed_component_candidate_count": sum(
                row["status"] == "CLOSED_STATIC_COMPONENT_CANDIDATE" for row in component_rows
            ),
            "open_shared_region_count": sum(
                row["status"] == "OPEN_SHARED_REGION" for row in component_rows
            ),
            "largest_reported_component_count": max(
                (row["component_count"] for row in component_rows), default=0
            ),
            "promotion_eligible_component_count": 0,
        },
        "truth_boundary": {
            "legacy_numeric_ids_are_modern_block_states": False,
            "directional_metadata_equivalence_fully_resolved": False,
            "same_kind_overlap_proves_wiring_equivalence": False,
            "closed_face_boundary_proves_standalone_operation": False,
            "runtime_semantics_confirmed": False,
            "private_extremecraft_parity_confirmed": False,
            "ec_ready": False,
        },
    }


def parse_triplet(raw: str, label: str) -> tuple[int, int, int]:
    try:
        values = tuple(int(value.strip()) for value in raw.split(","))
    except ValueError as exc:
        raise SharedCoreError(f"{label} must be X,Y,Z integers") from exc
    if len(values) != 3:
        raise SharedCoreError(f"{label} must be X,Y,Z integers")
    return values  # type: ignore[return-value]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit whether globally aligned legacy cannons contain metadata-equivalent, "
            "face-connected shared regions without promoting static overlap into runtime roles"
        )
    )
    parser.add_argument("--first-id", required=True)
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second-id", required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--turns", type=int, required=True)
    parser.add_argument("--translation", required=True, help="X,Y,Z")
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--minimum-component-size", type=int, default=8)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        if args.first_id == args.second_id:
            raise SharedCoreError("source IDs must be different")
        report = build_report(
            args.first_id, args.first.resolve(), args.second_id, args.second.resolve(),
            turns=args.turns,
            translation_delta=parse_triplet(args.translation, "translation"),
            chunk_limit=args.chunk_limit,
            minimum_component_size=args.minimum_component_size,
        )
    except (OSError, ValueError, SharedCoreError) as exc:
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
