#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any


class AssemblyError(ValueError):
    pass


def load(name: str, filename: str) -> Any:
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def connected_components(
    points: set[tuple[int, int, int]], neighbours: tuple[tuple[int, int, int], ...]
) -> list[list[tuple[int, int, int]]]:
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
            for delta in neighbours:
                neighbour = tuple(point[index] + delta[index] for index in range(3))
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    queue.append(neighbour)
        groups.append(sorted(group))
    return sorted(groups, key=lambda row: (-len(row), row[0]))


def build_report(
    first_id: str,
    first_path: Path,
    second_id: str,
    second_path: Path,
    *,
    turns: int,
    translation: tuple[int, int, int],
    minimum_functional_count: int,
    chunk_limit: int,
    max_shared_support_nodes: int,
) -> dict[str, Any]:
    if turns not in {0, 1, 2, 3}:
        raise AssemblyError("turns must be 0, 1, 2, or 3")
    if minimum_functional_count <= 0:
        raise AssemblyError("minimum_functional_count must be positive")
    if chunk_limit <= 0:
        raise AssemblyError("chunk_limit must be positive")
    if max_shared_support_nodes <= 0:
        raise AssemblyError("max_shared_support_nodes must be positive")

    shared = load("cannonlab_shared_assembly_base", "legacy-shared-core-audit.py")
    envelope = load("cannonlab_shared_assembly_envelope", "legacy-shared-core-envelope.py")
    architecture = shared.load_script(
        "cannonlab_shared_assembly_architecture", "legacy-cannon-architecture.py"
    )

    first_all, first_metadata = shared.load_legacy_map(first_path)
    raw_second, second_metadata = shared.load_legacy_map(second_path)
    second_all = {
        shared.transform_point(point, turns, translation): value
        for point, value in raw_second.items()
    }

    functional_ids = architecture.FUNCTIONAL_IDS
    common_positions = set(first_all) & set(second_all)
    proven_functional: set[tuple[int, int, int]] = set()
    equivalent_support: set[tuple[int, int, int]] = set()
    classification_counts: Counter[str] = Counter()

    for point in sorted(common_positions):
        first_value = first_all[point]
        second_value = second_all[point]
        classification = envelope.classify_outside_position(
            shared, architecture, first_value, second_value, turns
        )
        classification_counts[classification] += 1
        if classification == "shared_equivalent_functional":
            proven_functional.add(point)
        elif classification == "shared_equivalent_support":
            equivalent_support.add(point)

    if len(equivalent_support) > max_shared_support_nodes:
        raise AssemblyError(
            f"shared support node count {len(equivalent_support)} exceeds cap {max_shared_support_nodes}"
        )

    node_set = proven_functional | equivalent_support
    raw_components = connected_components(node_set, shared.FACE_NEIGHBOURS)
    assemblies: list[dict[str, Any]] = []
    for raw_index, component in enumerate(raw_components, start=1):
        region = set(component)
        functional = region & proven_functional
        support = region & equivalent_support
        if len(functional) < minimum_functional_count:
            continue

        functional_groups = connected_components(functional, shared.FACE_NEIGHBOURS)
        boundary = envelope.boundary_state(
            shared, architecture, region, first_all, second_all, turns
        )
        residual = boundary["edge_counts"]
        status = "FACE_CLOSED_SHARED_ASSEMBLY" if not residual else "OPEN_SHARED_ASSEMBLY"
        kind_counts = Counter(
            shared.kind_name(architecture, first_all[point]) for point in functional
        )
        support_id_counts = Counter(str(first_all[point][0]) for point in support)
        pressure = shared.chunk_scan(functional, first_all, chunk_limit)

        assemblies.append({
            "assembly_id": f"ASSEMBLY-{raw_index:03d}",
            "status": status,
            "node_count": len(region),
            "functional_count": len(functional),
            "support_count": len(support),
            "face_connected_functional_island_count": len(functional_groups),
            "largest_functional_island_count": max(
                (len(group) for group in functional_groups), default=0
            ),
            "bounds": shared.point_bounds(region),
            "functional_kind_counts": dict(sorted(kind_counts.items())),
            "support_legacy_id_counts": dict(sorted(support_id_counts.items())),
            "ec160": pressure,
            "residual_boundary_edge_counts": residual,
            "residual_unique_outside_position_counts": boundary[
                "unique_outside_position_counts"
            ],
            "residual_outside_kind_counts": boundary["outside_kind_counts"],
            "promotion_eligible": False,
            "truth_boundary": (
                "face-connected union of metadata-equivalent functional blocks and explicitly "
                "rotation-invariant exact shared support blocks; subsystem role, ports, indirect "
                "power, motion reach, fluids, conversion, and runtime causality remain unproven"
            ),
        })

    assemblies.sort(key=lambda row: (
        row["status"] != "FACE_CLOSED_SHARED_ASSEMBLY",
        -row["functional_count"],
        -row["node_count"],
        row["assembly_id"],
    ))
    status_counts = Counter(row["status"] for row in assemblies)
    accounted_functional = sum(row["functional_count"] for row in assemblies)

    return {
        "schema_version": 1,
        "status": "PASS",
        "classification": "LEGACY_SHARED_STATIC_ASSEMBLY_CLOSURE_ONLY",
        "sources": [
            {"id": first_id, **first_metadata},
            {"id": second_id, **second_metadata},
        ],
        "transform": {
            "turns": turns,
            "degrees": turns * 90,
            "translation": list(translation),
            "model": "single Y-axis quarter-turn plus translation; no reflection, scaling, or warping",
        },
        "node_inventory": {
            "common_nonair_position_count": len(common_positions),
            "proven_equivalent_functional_count": len(proven_functional),
            "equivalent_rotation_invariant_support_count": len(equivalent_support),
            "classification_counts": dict(sorted(classification_counts.items())),
        },
        "policy": {
            "minimum_functional_count": minimum_functional_count,
            "chunk_limit": chunk_limit,
            "max_shared_support_nodes": max_shared_support_nodes,
            "support_legacy_ids": sorted(envelope.ROTATION_INVARIANT_SUPPORT_IDS),
        },
        "assemblies": assemblies,
        "summary": {
            "reported_assembly_count": len(assemblies),
            "status_counts": dict(sorted(status_counts.items())),
            "accounted_functional_count": accounted_functional,
            "unreported_small_or_support_only_functional_count": (
                len(proven_functional) - accounted_functional
            ),
            "largest_assembly_functional_count": max(
                (row["functional_count"] for row in assemblies), default=0
            ),
            "largest_assembly_node_count": max(
                (row["node_count"] for row in assemblies), default=0
            ),
            "promotion_eligible_assembly_count": 0,
        },
        "truth_boundary": {
            "shared_static_assembly_proves_standalone_operation": False,
            "face_closure_proves_no_indirect_dependencies": False,
            "runtime_semantics_confirmed": False,
            "private_extremecraft_parity_confirmed": False,
            "ec_ready": False,
        },
    }


def parse_triplet(raw: str) -> tuple[int, int, int]:
    try:
        values = tuple(int(value.strip()) for value in raw.split(","))
    except ValueError as exc:
        raise AssemblyError("translation must be X,Y,Z integers") from exc
    if len(values) != 3:
        raise AssemblyError("translation must be X,Y,Z integers")
    return values  # type: ignore[return-value]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Merge globally aligned metadata-equivalent functional regions through exact shared "
            "rotation-invariant support to expose bounded static assembly boundaries"
        )
    )
    parser.add_argument("--first-id", required=True)
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second-id", required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--turns", type=int, required=True)
    parser.add_argument("--translation", required=True)
    parser.add_argument("--minimum-functional-count", type=int, default=8)
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--max-shared-support-nodes", type=int, default=100000)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        report = build_report(
            args.first_id,
            args.first.resolve(),
            args.second_id,
            args.second.resolve(),
            turns=args.turns,
            translation=parse_triplet(args.translation),
            minimum_functional_count=args.minimum_functional_count,
            chunk_limit=args.chunk_limit,
            max_shared_support_nodes=args.max_shared_support_nodes,
        )
    except (OSError, ValueError, AssemblyError) as exc:
        report = {
            "schema_version": 1,
            "status": "FAIL",
            "error": str(exc),
            "truth_boundary": {"ec_ready": False},
        }
    if args.json_out:
        write_json(args.json_out.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
