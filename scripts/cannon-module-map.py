#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
FUNCTIONAL_TYPES = {
    "minecraft:dispenser",
    "minecraft:dropper",
    "minecraft:redstone_wire",
    "minecraft:repeater",
    "minecraft:comparator",
    "minecraft:observer",
    "minecraft:piston",
    "minecraft:sticky_piston",
    "minecraft:slime_block",
    "minecraft:honey_block",
    "minecraft:redstone_block",
    "minecraft:redstone_torch",
    "minecraft:redstone_wall_torch",
    "minecraft:tripwire",
    "minecraft:tripwire_hook",
    "minecraft:lever",
    "minecraft:stone_button",
    "minecraft:polished_blackstone_button",
    "minecraft:water",
    "minecraft:lava",
    "minecraft:soul_sand",
    "minecraft:sand",
    "minecraft:red_sand",
    "minecraft:gravel",
    "minecraft:anvil",
    "minecraft:chipped_anvil",
    "minecraft:damaged_anvil",
    "minecraft:piston_head",
    "minecraft:moving_piston",
    "minecraft:note_block",
    "minecraft:target",
    "minecraft:redstone_lamp",
    "minecraft:scaffolding",
    "minecraft:rail",
    "minecraft:detector_rail",
    "minecraft:activator_rail",
    "minecraft:powered_rail",
}
CONTROL_SUFFIXES = ("_button", "_pressure_plate")
FUNCTIONAL_SUFFIXES = (
    "_button",
    "_pressure_plate",
    "_trapdoor",
    "_fence_gate",
    "_concrete_powder",
)
VOLATILE_PROPERTIES = {"power", "powered", "triggered", "lit"}
FACING_VECTORS = {
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 1, 0),
    "down": (0, -1, 0),
    "south": (0, 0, 1),
    "north": (0, 0, -1),
}

_SCRIPT_CACHE: dict[str, Any] = {}
_REPORT_CACHE: dict[tuple[str, int, int, int, int], dict[str, Any]] = {}
NEIGHBOURS = (
    (1, 0, 0),
    (-1, 0, 0),
    (0, 1, 0),
    (0, -1, 0),
    (0, 0, 1),
    (0, 0, -1),
)
PROXIMITY_OFFSETS = tuple(
    (dx, dy, dz)
    for dx in range(-2, 3)
    for dy in range(-2, 3)
    for dz in range(-2, 3)
    if (dx, dy, dz) != (0, 0, 0)
    and max(abs(dx), abs(dy), abs(dz)) <= 2
    and abs(dx) + abs(dy) + abs(dz) <= 3
)
COMPONENT_ID_RE = re.compile(r"\[(-?\d+),(-?\d+),(-?\d+)\]$")


def load_script(name: str, filename: str) -> Any:
    cached = _SCRIPT_CACHE.get(filename)
    if cached is not None:
        return cached
    script = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _SCRIPT_CACHE[filename] = module
    return module


def is_functional_type(block_type: str) -> bool:
    return block_type in FUNCTIONAL_TYPES or block_type.endswith(FUNCTIONAL_SUFFIXES)


def bounds(points: Iterable[tuple[int, int, int]]) -> dict[str, Any] | None:
    points = list(points)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    minimum = (min(xs), min(ys), min(zs))
    maximum = (max(xs), max(ys), max(zs))
    dimensions = tuple(maximum[index] - minimum[index] + 1 for index in range(3))
    return {
        "min": list(minimum),
        "max": list(maximum),
        "dimensions": {"x": dimensions[0], "y": dimensions[1], "z": dimensions[2]},
        "volume": dimensions[0] * dimensions[1] * dimensions[2],
    }


def parse_component_position(component_id: str) -> tuple[int, int, int]:
    match = COMPONENT_ID_RE.search(component_id)
    if not match:
        raise ValueError(f"invalid component id: {component_id}")
    return tuple(map(int, match.groups()))


def canonical_state(auditor: Any, state: str) -> str:
    block_type = auditor.base(state)
    props = {
        key: value
        for key, value in auditor.properties(state).items()
        if key not in VOLATILE_PROPERTIES
    }
    if not props:
        return block_type
    return block_type + "[" + ",".join(f"{key}={props[key]}" for key in sorted(props)) + "]"


def is_control(block_type: str) -> bool:
    return block_type == "minecraft:lever" or block_type.endswith(CONTROL_SUFFIXES)


def manhattan(first: tuple[int, int, int], second: tuple[int, int, int]) -> int:
    return sum(abs(first[index] - second[index]) for index in range(3))


def groups_from_offsets(
    points: set[tuple[int, int, int]],
    offsets: tuple[tuple[int, int, int], ...],
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
            for delta in offsets:
                neighbour = tuple(point[index] + delta[index] for index in range(3))
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    queue.append(neighbour)
        groups.append(sorted(group))
    return sorted(groups, key=lambda group: (-len(group), group[0]))


def connected_components(points: set[tuple[int, int, int]]) -> list[list[tuple[int, int, int]]]:
    return groups_from_offsets(points, NEIGHBOURS)


def normalized_signature(
    auditor: Any,
    blocks: dict[tuple[int, int, int], str],
    points: Iterable[tuple[int, int, int]],
) -> str:
    points = list(points)
    box = bounds(points)
    if not box:
        return hashlib.sha256(b"[]").hexdigest()
    minimum = box["min"]
    rows = [
        [
            point[0] - minimum[0],
            point[1] - minimum[1],
            point[2] - minimum[2],
            canonical_state(auditor, blocks[point]),
        ]
        for point in sorted(points)
    ]
    encoded = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def slice_families(
    auditor: Any,
    blocks: dict[tuple[int, int, int], str],
    functional_points: set[tuple[int, int, int]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for axis, axis_name in enumerate(("x", "y", "z")):
        slices: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
        for point in functional_points:
            slices[point[axis]].append(point)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for coordinate, points in sorted(slices.items()):
            other = [index for index in range(3) if index != axis]
            minimum = [min(point[index] for point in points) for index in other]
            rows = [
                [
                    point[other[0]] - minimum[0],
                    point[other[1]] - minimum[1],
                    canonical_state(auditor, blocks[point]),
                ]
                for point in sorted(points)
            ]
            signature = hashlib.sha256(
                json.dumps(rows, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            grouped[signature].append({"coordinate": coordinate, "count": len(points)})
        for signature, members in grouped.items():
            if len(members) < 3:
                continue
            coordinates = [member["coordinate"] for member in members]
            deltas = [coordinates[index + 1] - coordinates[index] for index in range(len(coordinates) - 1)]
            output.append({
                "axis": axis_name,
                "signature": signature,
                "instances": len(members),
                "coordinates": coordinates,
                "block_count_per_slice": members[0]["count"],
                "regular_spacing": len(set(deltas)) <= 1,
                "spacing": deltas[0] if deltas and len(set(deltas)) == 1 else None,
                "evidence": "exact static translation symmetry; subsystem role remains unconfirmed",
            })
    return sorted(output, key=lambda row: (-row["instances"], row["axis"], row["coordinates"]))


def directional_links(
    auditor: Any,
    blocks: dict[tuple[int, int, int], str],
    functional_points: set[tuple[int, int, int]],
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for point in sorted(functional_points):
        state = blocks[point]
        block_type = auditor.base(state)
        facing = auditor.properties(state).get("facing")
        vector = FACING_VECTORS.get(facing or "")
        if not vector or block_type not in {
            "minecraft:observer",
            "minecraft:repeater",
            "minecraft:comparator",
            "minecraft:piston",
            "minecraft:sticky_piston",
            "minecraft:dispenser",
            "minecraft:dropper",
        }:
            continue
        front = tuple(point[index] + vector[index] for index in range(3))
        back = tuple(point[index] - vector[index] for index in range(3))
        links.append({
            "component": [*point],
            "type": block_type,
            "facing": facing,
            "front": [*front],
            "front_type": auditor.base(blocks.get(front, "minecraft:air")),
            "back": [*back],
            "back_type": auditor.base(blocks.get(back, "minecraft:air")),
        })
    return links


def module_role_candidates(module: dict[str, Any]) -> list[dict[str, str]]:
    counts = module["block_type_counts"]
    dimensions = (module.get("bounds") or {}).get("dimensions") or {"x": 0, "y": 0, "z": 0}
    candidates: list[dict[str, str]] = []
    dispensers = counts.get("minecraft:dispenser", 0)
    pistons = counts.get("minecraft:piston", 0) + counts.get("minecraft:sticky_piston", 0)
    timing = counts.get("minecraft:repeater", 0) + counts.get("minecraft:comparator", 0)
    observers = counts.get("minecraft:observer", 0)
    fluids = counts.get("minecraft:water", 0) + counts.get("minecraft:lava", 0)
    controls = module.get("control_count", 0)

    if dispensers >= 32 and max(dimensions.values()) >= 12:
        candidates.append({
            "label": "large-dispenser-bank-candidate",
            "confidence": "static-medium",
            "evidence": "large spatially coherent dispenser population",
        })
    if dispensers and dimensions["y"] >= max(12, dimensions["x"] * 2, dimensions["z"] * 2):
        candidates.append({
            "label": "vertical-bank-or-stack-candidate",
            "confidence": "static-medium",
            "evidence": "tall narrow dispenser geometry",
        })
    if dispensers and (pistons or observers) and fluids:
        candidates.append({
            "label": "compression-or-payload-handling-candidate",
            "confidence": "static-low",
            "evidence": "dispensers colocated with motion components and fluid handling",
        })
    if not dispensers and timing >= 2:
        candidates.append({
            "label": "timing-spine-candidate",
            "confidence": "static-medium" if controls else "static-low",
            "evidence": "timing components without a local dispenser bank",
        })
    if controls:
        candidates.append({
            "label": "operator-control-candidate",
            "confidence": "static-high",
            "evidence": "contains a button, pressure plate, or lever",
        })
    if not candidates:
        candidates.append({
            "label": "unclassified-functional-module",
            "confidence": "static-low",
            "evidence": "runtime trace required for charge/booster/hammer/payload naming",
        })
    return candidates


def build_report(path: Path, chunk_limit: int = 160, assignment_radius: int = 6) -> dict[str, Any]:
    path = path.resolve()
    stat = path.stat()
    cache_key = (
        str(path),
        int(stat.st_size),
        int(stat.st_mtime_ns),
        int(chunk_limit),
        int(assignment_radius),
    )
    cached = _REPORT_CACHE.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)
    auditor = load_script("cannonlab_schem_audit", "schem-audit.py")
    static_map = load_script("cannonlab_static_map", "cannon-static-map.py")
    root_name, root, trailing, decoded_size, container_diagnostics = auditor.load(path)
    model = auditor.decode_any(root_name, root)
    blocks = model["blocks"]
    file_bytes = path.read_bytes()

    functional_points = {
        point
        for point, state in blocks.items()
        if is_functional_type(auditor.base(state))
    }
    banks = static_map.map_dispenser_banks(auditor, blocks, chunk_limit)
    bank_points: dict[str, set[tuple[int, int, int]]] = {
        bank["bank_id"]: {parse_component_position(value) for value in bank["component_ids"]}
        for bank in banks
    }

    assignments: dict[str, set[tuple[int, int, int]]] = {
        bank_id: set(points) for bank_id, points in bank_points.items()
    }
    shared: dict[tuple[int, int, int], list[str]] = {}
    unassigned: set[tuple[int, int, int]] = set()
    for point in sorted(functional_points):
        if any(point in points for points in bank_points.values()):
            continue
        distances = [
            (min(manhattan(point, seed) for seed in seeds), bank_id)
            for bank_id, seeds in bank_points.items()
            if seeds
        ]
        if not distances:
            unassigned.add(point)
            continue
        minimum = min(distance for distance, _bank_id in distances)
        nearest = sorted(bank_id for distance, bank_id in distances if distance == minimum)
        if minimum <= assignment_radius:
            assignments[nearest[0]].add(point)
            if len(nearest) > 1:
                shared[point] = nearest
        else:
            unassigned.add(point)

    modules: list[dict[str, Any]] = []
    bank_by_id = {bank["bank_id"]: bank for bank in banks}
    for bank_id, points in sorted(assignments.items()):
        if not points:
            continue
        counts = Counter(auditor.base(blocks[point]) for point in points)
        face_components = connected_components(set(points))
        module = {
            "module_id": f"MODULE-{len(modules) + 1:03d}",
            "kind": "bank-centric",
            "seed_bank_id": bank_id,
            "seed_dispenser_count": bank_by_id[bank_id]["count"],
            "seed_facing": bank_by_id[bank_id]["facing"],
            "seed_bank_shape": bank_by_id[bank_id]["shape"],
            "seed_bank_bounds": bank_by_id[bank_id]["bounds"],
            "component_count": len(points),
            "face_connected_components": len(face_components),
            "support_gap_bridges": max(0, len(face_components) - 1),
            "component_positions": [list(point) for point in sorted(points)],
            "bounds": bounds(points),
            "block_type_counts": dict(sorted(counts.items())),
            "control_count": sum(1 for point in points if is_control(auditor.base(blocks[point]))),
            "repeater_delays": dict(sorted(Counter(
                auditor.properties(blocks[point]).get("delay", "unknown")
                for point in points
                if auditor.base(blocks[point]) == "minecraft:repeater"
            ).items())),
            "signature": normalized_signature(auditor, blocks, points),
            "shared_component_count": sum(1 for point in points if point in shared),
            "truth_boundary": "bank-centric proximity assignment; runtime ownership not proven",
        }
        module["role_candidates"] = module_role_candidates(module)
        modules.append(module)

    for group in groups_from_offsets(unassigned, PROXIMITY_OFFSETS):
        counts = Counter(auditor.base(blocks[point]) for point in group)
        face_components = connected_components(set(group))
        module = {
            "module_id": f"MODULE-{len(modules) + 1:03d}",
            "kind": "unseeded-functional",
            "seed_bank_id": None,
            "seed_dispenser_count": 0,
            "seed_facing": None,
            "component_count": len(group),
            "face_connected_components": len(face_components),
            "support_gap_bridges": max(0, len(face_components) - 1),
            "component_positions": [list(point) for point in group],
            "bounds": bounds(group),
            "block_type_counts": dict(sorted(counts.items())),
            "control_count": sum(1 for point in group if is_control(auditor.base(blocks[point]))),
            "repeater_delays": dict(sorted(Counter(
                auditor.properties(blocks[point]).get("delay", "unknown")
                for point in group
                if auditor.base(blocks[point]) == "minecraft:repeater"
            ).items())),
            "signature": normalized_signature(auditor, blocks, group),
            "shared_component_count": 0,
            "truth_boundary": (
                "support-gap functional island without a nearby dispenser-bank seed; "
                "static grouping only"
            ),
        }
        module["role_candidates"] = module_role_candidates(module)
        modules.append(module)

    signature_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for module in modules:
        signature_groups[module["signature"]].append(module)
    repeated_modules = []
    for signature, members in signature_groups.items():
        if len(members) < 2:
            continue
        origins = [member["bounds"]["min"] for member in members if member.get("bounds")]
        vectors = [
            [origins[index][axis] - origins[0][axis] for axis in range(3)]
            for index in range(1, len(origins))
        ]
        repeated_modules.append({
            "signature": signature,
            "instances": len(members),
            "module_ids": [member["module_id"] for member in members],
            "translation_vectors_from_first": vectors,
            "evidence": "exact canonical-state translation match; runtime role remains unconfirmed",
        })

    bank_to_module = {
        str(module.get("seed_bank_id")): str(module.get("module_id"))
        for module in modules
        if module.get("seed_bank_id")
    }
    point_modules: dict[tuple[int, int, int], set[str]] = defaultdict(set)
    for module in modules:
        module_id = str(module.get("module_id"))
        for raw in module.get("component_positions") or []:
            point_modules[tuple(map(int, raw))].add(module_id)
    for point, bank_ids in shared.items():
        point_modules[point].update(
            bank_to_module[bank_id]
            for bank_id in bank_ids
            if bank_id in bank_to_module
        )

    coupling_evidence: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    positive_neighbours = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    for point, module_ids in point_modules.items():
        for first in sorted(module_ids):
            for second in sorted(module_ids):
                if first >= second:
                    continue
                coupling_evidence[(first, second)]["shared_component_ties"] += 1
        for delta in positive_neighbours:
            neighbour = tuple(point[index] + delta[index] for index in range(3))
            for first in module_ids:
                for second in point_modules.get(neighbour, set()):
                    if first == second:
                        continue
                    edge = tuple(sorted((first, second)))
                    coupling_evidence[edge]["face_adjacencies"] += 1

    links = directional_links(auditor, blocks, functional_points)
    for link in links:
        source = tuple(map(int, link["component"]))
        for endpoint_name in ("front", "back"):
            endpoint = tuple(map(int, link[endpoint_name]))
            for first in point_modules.get(source, set()):
                for second in point_modules.get(endpoint, set()):
                    if first == second:
                        continue
                    edge = tuple(sorted((first, second)))
                    coupling_evidence[edge]["directional_links"] += 1

    module_couplings = [
        {
            "first_module_id": first,
            "second_module_id": second,
            "shared_component_ties": counts.get("shared_component_ties", 0),
            "face_adjacencies": counts.get("face_adjacencies", 0),
            "directional_links": counts.get("directional_links", 0),
            "evidence": (
                "static coupling candidate from shared ownership, face adjacency, or directed component endpoints; "
                "signal flow remains runtime-unconfirmed"
            ),
        }
        for (first, second), counts in coupling_evidence.items()
    ]
    module_couplings.sort(key=lambda row: (
        -row["directional_links"],
        -row["shared_component_ties"],
        -row["face_adjacencies"],
        row["first_module_id"],
        row["second_module_id"],
    ))


    controls = [
        {"pos": list(point), "type": auditor.base(blocks[point]), "state": blocks[point]}
        for point in sorted(functional_points)
        if is_control(auditor.base(blocks[point]))
    ]
    functional_counts = Counter(auditor.base(blocks[point]) for point in functional_points)
    largest = max((module["component_count"] for module in modules), default=0)
    report = {
        "status": "PASS",
        "schema": "cannonlab-module-map-v2",
        "file": str(path),
        "file_sha256": hashlib.sha256(file_bytes).hexdigest(),
        "format": model["format"],
        "data_version": model["data_version"],
        "decoded_bytes": decoded_size,
        "trailing_bytes": len(trailing),
        "container_diagnostics": container_diagnostics,
        "source_dimensions": model["source_dimensions"],
        "assignment_radius": assignment_radius,
        "architecture_summary": {
            "functional_components": len(functional_points),
            "functional_type_diversity": len(functional_counts),
            "dispenser_banks": len(banks),
            "modules": len(modules),
            "bank_centric_modules": sum(module["kind"] == "bank-centric" for module in modules),
            "unseeded_modules": sum(module["kind"] == "unseeded-functional" for module in modules),
            "largest_module_components": largest,
            "largest_module_share": round(largest / max(1, len(functional_points)), 6),
            "shared_components": len(shared),
            "repeated_module_families": len(repeated_modules),
            "modules_with_support_gap_bridges": sum(
                int(module.get("support_gap_bridges") or 0) > 0
                for module in modules
            ),
            "total_support_gap_bridges": sum(
                int(module.get("support_gap_bridges") or 0)
                for module in modules
            ),
            "module_couplings": len(module_couplings),
        },
        "functional_type_counts": dict(sorted(functional_counts.items())),
        "controls": controls,
        "modules": modules,
        "repeated_module_families": sorted(
            repeated_modules,
            key=lambda row: (-row["instances"], row["module_ids"]),
        ),
        "repeated_slice_families": slice_families(auditor, blocks, functional_points),
        "directional_links": links,
        "module_couplings": module_couplings,
        "shared_component_assignments": [
            {
                "pos": list(point),
                "candidate_bank_ids": bank_ids,
                "candidate_module_ids": [
                    module["module_id"]
                    for module in modules
                    if module.get("seed_bank_id") in bank_ids
                ],
                "candidate_modules": [
                    module["module_id"]
                    for module in modules
                    if module.get("seed_bank_id") in bank_ids
                ],
                "evidence": (
                    "equal-distance static assignment tie; runtime ownership is ambiguous and "
                    "all candidate modules must be considered"
                ),
            }
            for point, bank_ids in sorted(shared.items())
        ],
        "truth_boundary": {
            "geometry_confirmed": True,
            "module_ownership_confirmed": False,
            "runtime_roles_confirmed": False,
            "note": (
                "Module boundaries, repeated lanes and role candidates are conservative static evidence. "
                "Charge, booster, hammer, sand, payload, nuke, OSRB and leftshot labels require causal runtime proof."
            ),
        },
    }
    _REPORT_CACHE[cache_key] = report
    return copy.deepcopy(report)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Map bank-centric cannon modules and repeated static lanes without inventing runtime roles"
    )
    parser.add_argument("schematic", type=Path)
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--assignment-radius", type=int, default=6)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_report(args.schematic, args.chunk_limit, args.assignment_radius)
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
