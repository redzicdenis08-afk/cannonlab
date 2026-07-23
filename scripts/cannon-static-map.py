#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

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
FACING_VECTORS = {
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 1, 0),
    "down": (0, -1, 0),
    "south": (0, 0, 1),
    "north": (0, 0, -1),
}
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


def load_auditor() -> Any:
    script = Path(__file__).resolve().with_name("schem-audit.py")
    spec = importlib.util.spec_from_file_location("cannonlab_schem_audit", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_functional_type(block_type: str) -> bool:
    return block_type in FUNCTIONAL_TYPES or block_type.endswith(FUNCTIONAL_SUFFIXES)


def component_prefix(block_type: str) -> str:
    return {
        "minecraft:dispenser": "D",
        "minecraft:dropper": "DR",
        "minecraft:redstone_wire": "W",
        "minecraft:repeater": "R",
        "minecraft:comparator": "C",
        "minecraft:observer": "O",
        "minecraft:piston": "P",
        "minecraft:sticky_piston": "P",
        "minecraft:redstone_block": "RB",
        "minecraft:redstone_torch": "T",
        "minecraft:redstone_wall_torch": "T",
        "minecraft:water": "H2O",
        "minecraft:lava": "LAVA",
    }.get(block_type, "B")


def component_id(block_type: str, pos: tuple[int, int, int]) -> str:
    return f"{component_prefix(block_type)}[{pos[0]},{pos[1]},{pos[2]}]"


def parse_properties(auditor: Any, state: str) -> dict[str, str]:
    return auditor.properties(state)


def bounds(points: list[tuple[int, int, int]]) -> dict[str, Any]:
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


def distribution(
    points: list[tuple[int, int, int]],
    offset_x: int,
    offset_z: int,
) -> Counter[tuple[int, int]]:
    return Counter(((x + offset_x) // 16, (z + offset_z) // 16) for x, _y, z in points)


def alignment_scan(points: list[tuple[int, int, int]], limit: int) -> dict[str, Any]:
    scans = []
    for offset_x in range(16):
        for offset_z in range(16):
            counts = distribution(points, offset_x, offset_z)
            scans.append({
                "offset_x": offset_x,
                "offset_z": offset_z,
                "max": max(counts.values(), default=0),
                "chunks": len(counts),
                "top_counts": sorted(counts.values(), reverse=True)[:12],
            })
    by_key = lambda row: (row["max"], row["chunks"], row["offset_x"], row["offset_z"])
    best = min(scans, key=by_key)
    worst = max(scans, key=by_key)
    safe = [row for row in scans if row["max"] <= limit]
    return {
        "best": best,
        "worst": worst,
        "safe_alignment_count": len(safe),
        "safe_alignments": safe,
    }


def groups_from_offsets(
    points: set[tuple[int, int, int]],
    offsets: tuple[tuple[int, int, int], ...],
) -> list[list[tuple[int, int, int]]]:
    remaining = set(points)
    groups = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue = deque([start])
        group = []
        while queue:
            point = queue.popleft()
            group.append(point)
            for dx, dy, dz in offsets:
                neighbour = (point[0] + dx, point[1] + dy, point[2] + dz)
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    queue.append(neighbour)
        groups.append(sorted(group))
    return sorted(groups, key=lambda group: (-len(group), group[0]))


def connected_components(points: set[tuple[int, int, int]]) -> list[list[tuple[int, int, int]]]:
    return groups_from_offsets(points, NEIGHBOURS)


def proximity_clusters(points: set[tuple[int, int, int]]) -> list[list[tuple[int, int, int]]]:
    return groups_from_offsets(points, PROXIMITY_OFFSETS)


def shape_name(box: dict[str, Any], count: int) -> str:
    dimensions = box["dimensions"]
    ordered = sorted((dimensions["x"], dimensions["y"], dimensions["z"]))
    density = count / max(1, box["volume"])
    if ordered[0] == 1 and density >= 0.75:
        return "dense-panel"
    if ordered[1] == 1 and density >= 0.75:
        return "dense-line"
    if density >= 0.75:
        return "dense-volume"
    if ordered[0] == 1:
        return "sparse-panel"
    return "irregular-volume"


def map_dispenser_banks(
    auditor: Any,
    blocks: dict[tuple[int, int, int], str],
    chunk_limit: int,
) -> list[dict[str, Any]]:
    by_facing: dict[str, set[tuple[int, int, int]]] = defaultdict(set)
    for pos, state in blocks.items():
        if auditor.base(state) != "minecraft:dispenser":
            continue
        facing = parse_properties(auditor, state).get("facing", "unknown")
        by_facing[facing].add(pos)

    banks = []
    for facing, positions in sorted(by_facing.items()):
        touching = connected_components(positions)
        touching_lookup = {
            point: index + 1
            for index, group in enumerate(touching)
            for point in group
        }
        for group in proximity_clusters(positions):
            box = bounds(group)
            density = len(group) / max(1, box["volume"])
            y_layers = sorted({point[1] for point in group})
            touching_groups = sorted({touching_lookup[point] for point in group})
            bank = {
                "bank_id": f"DBANK-{len(banks) + 1:03d}",
                "facing": facing,
                "count": len(group),
                "shape": shape_name(box, len(group)),
                "density": round(density, 6),
                "bounds": box,
                "y_layers": len(y_layers),
                "y_span": max(y_layers) - min(y_layers) + 1,
                "touching_group_count": len(touching_groups),
                "cluster_rule": (
                    "same-facing dispensers linked across support-sized gaps up to "
                    "two blocks; structural grouping only"
                ),
                "component_ids": [
                    component_id("minecraft:dispenser", point) for point in group
                ],
                "alignment": alignment_scan(group, chunk_limit),
                "role": "unclassified",
                "role_evidence": (
                    "Static geometry cannot prove charge/stack/hammer/booster/OSRB role."
                ),
            }
            banks.append(bank)
    return sorted(banks, key=lambda bank: (-bank["count"], bank["bank_id"]))


def list_components(
    auditor: Any,
    blocks: dict[tuple[int, int, int], str],
    block_type: str,
) -> list[dict[str, Any]]:
    output = []
    for pos, state in sorted(blocks.items()):
        if auditor.base(state) != block_type:
            continue
        output.append({
            "id": component_id(block_type, pos),
            "pos": list(pos),
            "state": state,
            "properties": parse_properties(auditor, state),
        })
    return output


def controls(
    auditor: Any,
    blocks: dict[tuple[int, int, int], str],
) -> list[dict[str, Any]]:
    output = []
    for pos, state in sorted(blocks.items()):
        block_type = auditor.base(state)
        if block_type != "minecraft:lever" and not block_type.endswith(CONTROL_SUFFIXES):
            continue
        output.append({
            "id": component_id(block_type, pos),
            "pos": list(pos),
            "type": block_type,
            "state": state,
            "properties": parse_properties(auditor, state),
        })
    return output


def observer_links(
    auditor: Any,
    blocks: dict[tuple[int, int, int], str],
) -> list[dict[str, Any]]:
    links = []
    for pos, state in sorted(blocks.items()):
        if auditor.base(state) != "minecraft:observer":
            continue
        facing = parse_properties(auditor, state).get("facing", "unknown")
        vector = FACING_VECTORS.get(facing)
        observed = None
        output = None
        if vector:
            observed_pos = tuple(pos[index] + vector[index] for index in range(3))
            output_pos = tuple(pos[index] - vector[index] for index in range(3))
            observed_state = blocks.get(observed_pos, "minecraft:air")
            output_state = blocks.get(output_pos, "minecraft:air")
            observed = {
                "pos": list(observed_pos),
                "type": auditor.base(observed_state),
                "state": observed_state,
            }
            output = {
                "pos": list(output_pos),
                "type": auditor.base(output_state),
                "state": output_state,
            }
        links.append({
            "id": component_id("minecraft:observer", pos),
            "pos": list(pos),
            "facing": facing,
            "observed": observed,
            "output": output,
        })
    return links


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a conservative functional map for Sponge/Litematica cannons"
    )
    parser.add_argument("schematic", type=Path)
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    auditor = load_auditor()
    root_name, root, _trailing, _size, container_diagnostics = auditor.load(args.schematic)
    model = auditor.decode_any(root_name, root)
    blocks = model["blocks"]

    counts = Counter(
        auditor.base(state)
        for state in blocks.values()
        if auditor.base(state) not in AIR
    )
    functional_points = [
        pos for pos, state in blocks.items()
        if is_functional_type(auditor.base(state))
    ]
    functional_box = bounds(functional_points) if functional_points else None
    dispenser_banks = map_dispenser_banks(auditor, blocks, args.chunk_limit)
    dispenser_points = [
        pos for pos, state in blocks.items()
        if auditor.base(state) == "minecraft:dispenser"
    ]
    dispenser_layers = sorted({point[1] for point in dispenser_points})

    report = {
        "status": "PASS",
        "file": str(args.schematic),
        "format": model["format"],
        "container_diagnostics": container_diagnostics,
        "data_version": model["data_version"],
        "dimensions": model["source_dimensions"],
        "functional_bounds": functional_box,
        "architecture_summary": {
            "functional_height": (
                functional_box["dimensions"]["y"] if functional_box else 0
            ),
            "functional_type_diversity": len([
                block_type for block_type in counts
                if is_functional_type(block_type)
            ]),
            "dispenser_count": len(dispenser_points),
            "dispenser_y_layers": len(dispenser_layers),
            "dispenser_y_span": (
                max(dispenser_layers) - min(dispenser_layers) + 1
                if dispenser_layers else 0
            ),
            "dispenser_bank_count": len(dispenser_banks),
        },
        "block_type_counts": dict(sorted(counts.items())),
        "controls": controls(auditor, blocks),
        "repeaters": list_components(auditor, blocks, "minecraft:repeater"),
        "comparators": list_components(auditor, blocks, "minecraft:comparator"),
        "observers": observer_links(auditor, blocks),
        "pistons": (
            list_components(auditor, blocks, "minecraft:piston")
            + list_components(auditor, blocks, "minecraft:sticky_piston")
        ),
        "water": list_components(auditor, blocks, "minecraft:water"),
        "dispenser_banks": dispenser_banks,
        "largest_dispenser_bank": dispenser_banks[0] if dispenser_banks else None,
        "truth_boundary": {
            "geometry_confirmed": True,
            "runtime_confirmed": False,
            "subsystem_roles_confirmed": False,
            "note": (
                "Names such as charge, hammer, booster, nuke and OSRB require causal runtime evidence."
            ),
        },
    }
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"},
                indent=2,
            ),
            file=__import__("sys").stderr,
        )
        raise SystemExit(3)
