#!/usr/bin/env python3
"""Static EC160 placement and bank-segmentation advisor.

The advisor never rewrites a cannon. It finds legal paste offsets first, then
maps dispenser banks and proposes symmetry-preserving segmentation contracts
only when alignment alone cannot satisfy the configured per-chunk limit.
Every proposal is a reconstruction scaffold that still requires redstone,
water, piston, entity-order, and runtime revalidation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Iterable, Sequence


OPPOSITE = {
    "east": "west",
    "west": "east",
    "north": "south",
    "south": "north",
    "up": "down",
    "down": "up",
}
HORIZONTAL_AXIS = {"east": "x", "west": "x", "north": "z", "south": "z"}
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
PROXIMITY = tuple(
    (dx, dy, dz)
    for dx in range(-2, 3)
    for dy in range(-2, 3)
    for dz in range(-2, 3)
    if (dx, dy, dz) != (0, 0, 0)
    and max(abs(dx), abs(dy), abs(dz)) <= 2
    and abs(dx) + abs(dy) + abs(dz) <= 3
)


def load_auditor() -> Any:
    path = Path(__file__).resolve().with_name("schem-audit.py")
    spec = importlib.util.spec_from_file_location("cannonlab_schem_audit_for_ec160", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def bounds(points: Sequence[tuple[int, int, int]]) -> dict[str, Any]:
    minimum = [min(point[index] for point in points) for index in range(3)]
    maximum = [max(point[index] for point in points) for index in range(3)]
    dimensions = [maximum[index] - minimum[index] + 1 for index in range(3)]
    return {
        "min": minimum,
        "max": maximum,
        "dimensions": {"x": dimensions[0], "y": dimensions[1], "z": dimensions[2]},
    }


def center(box: dict[str, Any]) -> tuple[float, float, float]:
    return tuple((box["min"][index] + box["max"][index]) / 2.0 for index in range(3))


def overlap_ratio(first: dict[str, Any], second: dict[str, Any], axis: int) -> float:
    start = max(first["min"][axis], second["min"][axis])
    end = min(first["max"][axis], second["max"][axis])
    overlap = max(0, end - start + 1)
    span = max(first["max"][axis], second["max"][axis]) - min(first["min"][axis], second["min"][axis]) + 1
    return overlap / span if span else 0.0


def bank_id(facing: str, points: Sequence[tuple[int, int, int]]) -> str:
    digest = hashlib.sha256(json.dumps(sorted(points), separators=(",", ":")).encode("utf-8")).hexdigest()[:10]
    return f"bank-{facing}-{digest}"


def group_dispenser_banks(
    dispensers: dict[tuple[int, int, int], str],
) -> list[dict[str, Any]]:
    remaining = set(dispensers)
    banks: list[dict[str, Any]] = []
    while remaining:
        start = min(remaining)
        facing = dispensers[start]
        queue = deque([start])
        remaining.remove(start)
        points: list[tuple[int, int, int]] = []
        while queue:
            point = queue.popleft()
            points.append(point)
            for delta in PROXIMITY:
                neighbour = tuple(point[index] + delta[index] for index in range(3))
                if neighbour in remaining and dispensers[neighbour] == facing:
                    remaining.remove(neighbour)
                    queue.append(neighbour)
        box = bounds(points)
        banks.append(
            {
                "id": bank_id(facing, points),
                "facing": facing,
                "count": len(points),
                "bounds": box,
                "center": list(center(box)),
                "coordinate_counts": {
                    axis: dict(sorted(Counter(point[index] for point in points).items()))
                    for axis, index in AXIS_INDEX.items()
                },
                "points": sorted(points),
            }
        )
    return sorted(banks, key=lambda item: (-item["count"], item["facing"], item["bounds"]["min"]))


def opposing_pairs(banks: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[tuple[float, int, int, dict[str, Any]]] = []
    for first_index, first in enumerate(banks):
        for second_index in range(first_index + 1, len(banks)):
            second = banks[second_index]
            if OPPOSITE.get(first["facing"]) != second["facing"]:
                continue
            firing_axis = AXIS_INDEX.get(HORIZONTAL_AXIS.get(first["facing"], "x"), 0)
            plane_axes = [axis for axis in range(3) if axis != firing_axis]
            count_similarity = min(first["count"], second["count"]) / max(first["count"], second["count"])
            plane_overlap = sum(overlap_ratio(first["bounds"], second["bounds"], axis) for axis in plane_axes) / len(plane_axes)
            separation = abs(first["center"][firing_axis] - second["center"][firing_axis])
            score = count_similarity * 0.55 + plane_overlap * 0.40 + (1.0 / (1.0 + separation)) * 0.05
            candidates.append(
                (
                    score,
                    first_index,
                    second_index,
                    {
                        "pair_id": f"pair-{first['id']}-{second['id']}",
                        "banks": [first["id"], second["id"]],
                        "facings": [first["facing"], second["facing"]],
                        "counts": [first["count"], second["count"]],
                        "count_similarity": count_similarity,
                        "plane_overlap": plane_overlap,
                        "separation": separation,
                        "confidence": "high" if count_similarity >= 0.9 and plane_overlap >= 0.7 else "medium" if score >= 0.65 else "low",
                        "preservation_rule": "Move or segment both opposing banks as one interface. Moving only one side can destroy compression symmetry.",
                    },
                )
            )
    used: set[int] = set()
    output: list[dict[str, Any]] = []
    for _score, first_index, second_index, report in sorted(candidates, reverse=True, key=lambda item: item[0]):
        if first_index in used or second_index in used:
            continue
        if report["confidence"] == "low":
            continue
        used.update((first_index, second_index))
        output.append(report)
    return output


def preferred_split_axis(bank: dict[str, Any]) -> str:
    facing = bank["facing"]
    if facing in {"east", "west"}:
        return "z"
    if facing in {"north", "south"}:
        return "x"
    x_unique = len(bank["coordinate_counts"]["x"])
    z_unique = len(bank["coordinate_counts"]["z"])
    return "x" if x_unique >= z_unique else "z"


def greedy_coordinate_segments(
    coordinate_counts: dict[int, int],
    limit: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    segments: list[dict[str, Any]] = []
    warnings: list[str] = []
    current_coordinates: list[int] = []
    current_count = 0
    for coordinate, count in sorted(coordinate_counts.items()):
        if count > limit:
            if current_coordinates:
                segments.append(
                    {
                        "coordinate_min": current_coordinates[0],
                        "coordinate_max": current_coordinates[-1],
                        "coordinates": current_coordinates,
                        "dispensers": current_count,
                    }
                )
                current_coordinates = []
                current_count = 0
            segments.append(
                {
                    "coordinate_min": coordinate,
                    "coordinate_max": coordinate,
                    "coordinates": [coordinate],
                    "dispensers": count,
                    "requires_secondary_axis_split": True,
                }
            )
            warnings.append(f"coordinate slice {coordinate} contains {count}>{limit} dispensers")
            continue
        if current_coordinates and current_count + count > limit:
            segments.append(
                {
                    "coordinate_min": current_coordinates[0],
                    "coordinate_max": current_coordinates[-1],
                    "coordinates": current_coordinates,
                    "dispensers": current_count,
                }
            )
            current_coordinates = []
            current_count = 0
        current_coordinates.append(coordinate)
        current_count += count
    if current_coordinates:
        segments.append(
            {
                "coordinate_min": current_coordinates[0],
                "coordinate_max": current_coordinates[-1],
                "coordinates": current_coordinates,
                "dispensers": current_count,
            }
        )
    return segments, warnings


def bank_segmentation(bank: dict[str, Any], limit: int) -> dict[str, Any]:
    axis = preferred_split_axis(bank)
    counts = {int(key): int(value) for key, value in bank["coordinate_counts"][axis].items()}
    segments, warnings = greedy_coordinate_segments(counts, limit)
    minimum_columns = math.ceil(bank["count"] / limit)
    return {
        "bank": bank["id"],
        "facing": bank["facing"],
        "count": bank["count"],
        "preferred_split_axis": axis,
        "minimum_chunk_columns": minimum_columns,
        "proposed_coordinate_segments": segments,
        "segment_count": len(segments),
        "warnings": warnings,
        "status": "NO_SPLIT_REQUIRED" if bank["count"] <= limit else "STATIC_SEGMENTATION_SCAFFOLD",
        "preservation_contract": [
            "Preserve every dispenser facing and vertical coordinate.",
            "Preserve same-tick cohort membership unless runtime evidence authorizes a change.",
            "Translate paired opposing segments symmetrically.",
            "Rebuild observer/repeater transport and re-measure arrival tick at every segment.",
            "Revalidate water containment, piston reset, payload alignment, self-damage, and output direction.",
        ],
    }


def chunk_distribution(
    dispensers: dict[tuple[int, int, int], str],
    offset_x: int,
    offset_z: int,
) -> dict[tuple[int, int], list[tuple[int, int, int]]]:
    chunks: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)
    for point in dispensers:
        chunks[((point[0] + offset_x) // 16, (point[2] + offset_z) // 16)].append(point)
    return chunks


def paste_point_for_min_corner(
    minimum_chunk_local_x: int,
    minimum_chunk_local_z: int,
    worldedit_offset_x: int,
    worldedit_offset_z: int,
) -> tuple[int, int]:
    """Translate a schematic-minimum residue into the player WorldEdit paste-point residue."""
    return (
        (minimum_chunk_local_x - worldedit_offset_x) % 16,
        (minimum_chunk_local_z - worldedit_offset_z) % 16,
    )


def placement_fragility(safe_count: int) -> str:
    if safe_count <= 0:
        return "none-legal"
    if safe_count <= 4:
        return "extreme"
    if safe_count <= 16:
        return "high"
    if safe_count <= 64:
        return "moderate"
    return "low"


def analyze(path: Path, limit: int) -> dict[str, Any]:
    auditor = load_auditor()
    root_name, root, trailing, decoded_bytes, compression = auditor.load(path)
    if trailing not in (b"", b"\x00"):
        raise ValueError(f"schematic contains unexpected trailing decoded bytes: {trailing.hex()}")
    model = auditor.decode_any(root_name, root)
    dispensers: dict[tuple[int, int, int], str] = {}
    for point, state in model["blocks"].items():
        if auditor.base(state) != "minecraft:dispenser":
            continue
        dispensers[point] = auditor.properties(state).get("facing", "unknown")
    if not dispensers:
        raise ValueError("schematic contains no dispensers")
    scans = auditor.scan_alignments([(point[0], point[2]) for point in dispensers])
    scans.sort(key=lambda item: (item[0], item[3], item[1], item[2]))
    best = scans[0]
    safe = [item for item in scans if item[0] <= limit]
    metadata = model.get("metadata") or {}
    we_x = int(metadata.get("WEOffsetX", 0) or 0)
    we_y = int(metadata.get("WEOffsetY", 0) or 0)
    we_z = int(metadata.get("WEOffsetZ", 0) or 0)
    best_player_x, best_player_z = paste_point_for_min_corner(best[1], best[2], we_x, we_z)
    safe_player = []
    for item in safe:
        player_x, player_z = paste_point_for_min_corner(item[1], item[2], we_x, we_z)
        safe_player.append(
            {
                "player_chunk_local_x": player_x,
                "player_chunk_local_z": player_z,
                "effective_minimum_corner_x": item[1],
                "effective_minimum_corner_z": item[2],
                "maximum_dispensers_in_one_chunk": item[0],
                "chunk_columns_used": item[3],
                "top_counts": item[4],
            }
        )
    best_chunks = chunk_distribution(dispensers, best[1], best[2])
    banks = group_dispenser_banks(dispensers)
    point_to_bank = {
        tuple(point): bank["id"]
        for bank in banks
        for point in bank["points"]
    }
    chunk_rows = []
    for chunk, points in sorted(best_chunks.items(), key=lambda item: (-len(item[1]), item[0])):
        bank_counts = Counter(point_to_bank[point] for point in points)
        chunk_rows.append(
            {
                "chunk": list(chunk),
                "dispensers": len(points),
                "banks": dict(bank_counts.most_common()),
            }
        )
    block_entity_count = len(model.get("block_entities") or [])
    segmentation = [bank_segmentation(bank, limit) for bank in banks]
    alignment_status = "ALIGNMENT_ONLY_CANDIDATE" if safe else "ARCHITECTURAL_REDISTRIBUTION_REQUIRED"
    fragility = placement_fragility(len(safe))
    return {
        "schema": "cannonlab-ec160-architecture-advisor-v1",
        "status": alignment_status,
        "source": {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "format": model["format"],
            "data_version": model["data_version"],
            "dimensions": model["source_dimensions"],
            "worldedit_metadata_offset": {"x": we_x, "y": we_y, "z": we_z},
            "decoded_bytes": decoded_bytes,
            "compression": compression,
        },
        "limits": {
            "dispenser_limit_per_xz_chunk_column": limit,
            "separate_block_entity_limit": "UNKNOWN",
            "total_dispensers": len(dispensers),
            "explicit_block_entities": block_entity_count,
            "theoretical_minimum_chunk_columns": math.ceil(len(dispensers) / limit),
        },
        "alignment": {
            "safe_offset_count": len(safe),
            "safe_fraction": len(safe) / 256.0,
            "best": {
                "paste_origin_mod_16": {"x": best[1], "z": best[2]},
                "maximum_dispensers_in_one_chunk": best[0],
                "chunk_columns_used": best[3],
                "top_counts": best[4],
            },
            "safe_offsets": [
                {
                    "paste_origin_mod_16": {"x": item[1], "z": item[2]},
                    "maximum_dispensers_in_one_chunk": item[0],
                    "chunk_columns_used": item[3],
                    "top_counts": item[4],
                }
                for item in safe
            ],
            "worldedit_paste_point": {
                "best": {
                    "player_chunk_local_x": best_player_x,
                    "player_chunk_local_z": best_player_z,
                    "effective_minimum_corner_x": best[1],
                    "effective_minimum_corner_z": best[2],
                    "maximum_dispensers_in_one_chunk": best[0],
                    "chunk_columns_used": best[3],
                    "top_counts": best[4],
                },
                "safe_count": len(safe_player),
                "safe_offsets": safe_player,
            },
            "best_chunk_map": chunk_rows,
            "fragility": fragility,
        },
        "banks": [
            {key: value for key, value in bank.items() if key != "points"}
            for bank in banks
        ],
        "opposing_bank_pairs": opposing_pairs(banks),
        "segmentation_advice": segmentation,
        "next_action": (
            "Use only a documented safe paste-origin residue, then run an empty-settle-fill-fire canary. Do not redesign the banks unless paste-side block-entity pressure or live runtime still fails."
            if safe
            else
            "Reconstruct paired bank segments across additional chunk columns, preserving cohort timing and compression symmetry, then repeat all 256 alignment scans and runtime traces."
        ),
        "truth_boundary": {
            "proves_static_dispenser_distribution": True,
            "automatically_rewrites_cannon": False,
            "proves_redstone_transport_after_segmentation": False,
            "proves_fawe_block_entity_acceptance": False,
            "proves_extremecraft_runtime": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Advise EC per-chunk placement and symmetry-preserving bank segmentation")
    parser.add_argument("schematic", type=Path)
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        if args.chunk_limit <= 0:
            raise ValueError("chunk limit must be positive")
        report = analyze(args.schematic, args.chunk_limit)
        exit_code = 0 if report["status"] == "ALIGNMENT_ONLY_CANDIDATE" else 2
    except (OSError, ValueError, KeyError) as exc:
        report = {
            "schema": "cannonlab-ec160-architecture-advisor-v1",
            "status": "FAIL",
            "error": str(exc),
        }
        exit_code = 2
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
