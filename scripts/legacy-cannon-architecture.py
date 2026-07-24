#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Iterable


class ArchitectureError(ValueError):
    pass


FUNCTIONAL_IDS = {
    8, 9, 10, 11, 12, 13, 23, 29, 33, 34, 46, 55, 69, 70, 72, 75, 76,
    77, 93, 94, 143, 147, 148, 149, 150, 152, 165, 218,
}
ANCHOR_KINDS = {
    "dispenser", "repeater", "piston", "sticky_piston", "redstone_block",
    "stone_button", "wooden_button", "comparator", "observer",
}
PROXIMITY_OFFSETS = tuple(
    (dx, dy, dz)
    for dx in range(-2, 3)
    for dy in range(-2, 3)
    for dz in range(-2, 3)
    if (dx, dy, dz) != (0, 0, 0)
    and max(abs(dx), abs(dy), abs(dz)) <= 2
    and abs(dx) + abs(dy) + abs(dz) <= 3
)
MOTIF_OFFSETS = tuple(
    (dx, dy, dz)
    for dx in range(-2, 3)
    for dy in range(-2, 3)
    for dz in range(-2, 3)
    if abs(dx) + abs(dy) + abs(dz) <= 3
)


def load_legacy_parser() -> Any:
    script = Path(__file__).resolve().with_name("legacy-schematic-audit.py")
    spec = importlib.util.spec_from_file_location("cannonlab_legacy_schematic_audit", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def clean_identifier(raw: str) -> str:
    value = str(raw or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    if not value or any(character not in allowed for character in value):
        raise ArchitectureError("source id must use letters, digits, dot, dash, or underscore")
    return value


def canonical_token(block_id: int, data: int) -> str:
    value = int(data) & 0xFF
    if block_id == 23:
        return f"dispenser:{value & 7}"
    if block_id == 29:
        return f"sticky_piston:{value & 7}"
    if block_id == 33:
        return f"piston:{value & 7}"
    if block_id == 34:
        return f"piston_head:{value & 7}"
    if block_id in {93, 94}:
        return f"repeater:{value & 15}"
    if block_id in {149, 150}:
        return f"comparator:{value & 7}"
    if block_id in {75, 76}:
        return f"redstone_torch:{value & 7}"
    if block_id == 55:
        return "redstone_wire"
    if block_id == 69:
        return f"lever:{value & 7}"
    if block_id in {70, 72}:
        return f"pressure_plate:{block_id}"
    if block_id == 77:
        return f"stone_button:{value & 7}"
    if block_id == 143:
        return f"wooden_button:{value & 7}"
    if block_id in {147, 148}:
        return f"weighted_pressure_plate:{block_id}"
    if block_id == 152:
        return "redstone_block"
    if block_id == 165:
        return "slime_block"
    if block_id == 218:
        return f"observer:{value & 7}"
    if block_id in {8, 9}:
        return f"water:{value & 15}"
    if block_id in {10, 11}:
        return f"lava:{value & 15}"
    if block_id == 12:
        return f"sand:{value & 1}"
    if block_id == 13:
        return "gravel"
    if block_id == 46:
        return "tnt"
    return f"legacy-{block_id}:{value}"


def token_kind(token: str) -> str:
    return token.split(":", 1)[0]


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


def groups_from_offsets(
    points: set[tuple[int, int, int]], offsets: tuple[tuple[int, int, int], ...]
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
            for dx, dy, dz in offsets:
                neighbour = (point[0] + dx, point[1] + dy, point[2] + dz)
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    queue.append(neighbour)
        groups.append(sorted(group))
    return sorted(groups, key=lambda group: (-len(group), group[0]))


def normalized_signature(
    blocks: dict[tuple[int, int, int], str], points: Iterable[tuple[int, int, int]]
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
            blocks[point],
        ]
        for point in sorted(points)
    ]
    encoded = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def extract_functional_blocks(path: Path) -> tuple[dict[tuple[int, int, int], str], dict[str, Any]]:
    legacy = load_legacy_parser()
    root_name, root, decompressed_bytes = legacy.parse_root(path)
    width = legacy.require_int(root, "Width")
    height = legacy.require_int(root, "Height")
    length = legacy.require_int(root, "Length")
    if min(width, height, length) <= 0:
        raise ArchitectureError("legacy schematic dimensions must be positive")
    volume = width * height * length
    blocks_raw = legacy.require_bytes(root, "Blocks")
    data_raw = legacy.require_bytes(root, "Data")
    if len(blocks_raw) != volume or len(data_raw) != volume:
        raise ArchitectureError("legacy Blocks/Data length does not match volume")
    add_value = root.get("AddBlocks")
    add_blocks = add_value if isinstance(add_value, bytes) else None
    if add_blocks is not None and len(add_blocks) < (volume + 1) // 2:
        raise ArchitectureError("legacy AddBlocks is shorter than required")

    functional: dict[tuple[int, int, int], str] = {}
    for index, low in enumerate(blocks_raw):
        block_id = low
        if add_blocks is not None:
            packed = add_blocks[index // 2]
            high = (packed & 0x0F) if index % 2 == 0 else ((packed >> 4) & 0x0F)
            block_id |= high << 8
        if block_id not in FUNCTIONAL_IDS:
            continue
        x = index % width
        z = (index // width) % length
        y = index // (width * length)
        functional[(x, y, z)] = canonical_token(block_id, data_raw[index])
    return functional, {
        "root_name": root_name,
        "dimensions": {"width": width, "height": height, "length": length},
        "volume": volume,
        "decompressed_bytes": decompressed_bytes,
    }


def dispenser_banks(blocks: dict[tuple[int, int, int], str]) -> list[dict[str, Any]]:
    by_orientation: dict[str, set[tuple[int, int, int]]] = defaultdict(set)
    for point, token in blocks.items():
        if token_kind(token) == "dispenser":
            by_orientation[token].add(point)
    banks: list[dict[str, Any]] = []
    for orientation, points in sorted(by_orientation.items()):
        for group in groups_from_offsets(points, PROXIMITY_OFFSETS):
            box = bounds(group)
            assert box is not None
            banks.append({
                "bank_id": f"DBANK-{len(banks) + 1:03d}",
                "orientation_token": orientation,
                "dispenser_count": len(group),
                "bounds": box,
                "density": round(len(group) / max(1, box["volume"]), 6),
                "points": group,
                "truth_boundary": "same-orientation proximity cluster; runtime role unconfirmed",
            })
    return sorted(banks, key=lambda row: (-row["dispenser_count"], row["bank_id"]))


def inside_expanded(point: tuple[int, int, int], box: dict[str, Any], radius: int) -> bool:
    return all(
        box["min"][axis] - radius <= point[axis] <= box["max"][axis] + radius
        for axis in range(3)
    )


def bank_context_modules(
    blocks: dict[tuple[int, int, int], str], banks: list[dict[str, Any]], radius: int = 6
) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    for bank in banks:
        points = sorted(point for point in blocks if inside_expanded(point, bank["bounds"], radius))
        counts = Counter(token_kind(blocks[point]) for point in points)
        modules.append({
            "module_id": f"MODULE-{len(modules) + 1:03d}",
            "seed_bank_id": bank["bank_id"],
            "seed_dispenser_count": bank["dispenser_count"],
            "context_radius": radius,
            "component_count": len(points),
            "bounds": bounds(points),
            "kind_counts": dict(sorted(counts.items())),
            "signature": normalized_signature(blocks, points),
            "truth_boundary": "bounded bank context; ownership and phase remain unconfirmed",
        })
    return modules


def slice_families(blocks: dict[tuple[int, int, int], str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for axis, axis_name in enumerate(("x", "y", "z")):
        slices: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
        for point in blocks:
            slices[point[axis]].append(point)
        grouped: dict[str, list[dict[str, int]]] = defaultdict(list)
        for coordinate, points in sorted(slices.items()):
            other = [index for index in range(3) if index != axis]
            minimum = [min(point[index] for point in points) for index in other]
            rows = [
                [
                    point[other[0]] - minimum[0],
                    point[other[1]] - minimum[1],
                    blocks[point],
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
                "component_count_per_slice": members[0]["count"],
                "regular_spacing": bool(deltas) and len(set(deltas)) == 1,
                "spacing": deltas[0] if deltas and len(set(deltas)) == 1 else None,
                "evidence": "exact legacy functional-token translation symmetry",
            })
    return sorted(output, key=lambda row: (-row["instances"], row["axis"], row["coordinates"]))


def motif_rows(
    blocks: dict[tuple[int, int, int], str]
) -> tuple[Counter[str], dict[str, dict[str, Any]]]:
    counts: Counter[str] = Counter()
    metadata: dict[str, dict[str, Any]] = {}
    for anchor, anchor_token in sorted(blocks.items()):
        anchor_kind = token_kind(anchor_token)
        if anchor_kind not in ANCHOR_KINDS:
            continue
        rows = []
        for dx, dy, dz in MOTIF_OFFSETS:
            point = (anchor[0] + dx, anchor[1] + dy, anchor[2] + dz)
            token = blocks.get(point)
            if token is not None:
                rows.append([dx, dy, dz, token])
        signature = hashlib.sha256(
            json.dumps(rows, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        counts[signature] += 1
        metadata.setdefault(signature, {
            "anchor_kind": anchor_kind,
            "anchor_token": anchor_token,
            "component_count": len(rows),
        })
    return counts, metadata


def analyze_blocks(
    source_id: str,
    blocks: dict[tuple[int, int, int], str],
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    banks = dispenser_banks(blocks)
    modules = bank_context_modules(blocks, banks)
    motifs, motif_metadata = motif_rows(blocks)
    module_groups: dict[str, list[str]] = defaultdict(list)
    for module in modules:
        module_groups[module["signature"]].append(module["module_id"])
    repeated_modules = [
        {"signature": signature, "instances": len(ids), "module_ids": ids}
        for signature, ids in module_groups.items()
        if len(ids) >= 2
    ]
    repeated_modules.sort(key=lambda row: (-row["instances"], row["signature"]))
    kind_counts = Counter(token_kind(token) for token in blocks.values())
    return {
        "source_id": source_id,
        "source_metadata": source_metadata or {},
        "functional_component_count": len(blocks),
        "functional_kind_counts": dict(sorted(kind_counts.items())),
        "functional_bounds": bounds(blocks),
        "dispenser_banks": [
            {key: value for key, value in bank.items() if key != "points"}
            for bank in banks
        ],
        "bank_context_modules": modules,
        "repeated_exact_bank_contexts": repeated_modules,
        "slice_families": slice_families(blocks),
        "motif_counts": dict(motifs),
        "motif_metadata": motif_metadata,
        "truth_boundary": {
            "functional_tokens_are_legacy_id_data_canonicalizations": True,
            "module_roles_confirmed": False,
            "timing_phases_confirmed": False,
            "runtime_function_confirmed": False,
        },
    }


def multiset_jaccard(first: Counter[str], second: Counter[str]) -> float:
    keys = set(first) | set(second)
    union = sum(max(first[key], second[key]) for key in keys)
    if union == 0:
        return 1.0
    intersection = sum(min(first[key], second[key]) for key in keys)
    return intersection / union


def compare_sources(source_reports: list[dict[str, Any]]) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    for first_index, first in enumerate(source_reports):
        for second in source_reports[first_index + 1 :]:
            first_motifs = Counter(first["motif_counts"])
            second_motifs = Counter(second["motif_counts"])
            first_modules = {row["signature"] for row in first["bank_context_modules"]}
            second_modules = {row["signature"] for row in second["bank_context_modules"]}
            first_slices = {row["signature"] for row in first["slice_families"]}
            second_slices = {row["signature"] for row in second["slice_families"]}
            pairs.append({
                "first": first["source_id"],
                "second": second["source_id"],
                "motif_weighted_jaccard": round(multiset_jaccard(first_motifs, second_motifs), 6),
                "shared_motif_signature_count": len(set(first_motifs) & set(second_motifs)),
                "shared_exact_bank_context_count": len(first_modules & second_modules),
                "shared_exact_slice_family_count": len(first_slices & second_slices),
                "evidence": "translation-invariant static legacy functional-token overlap",
            })
    pairs.sort(key=lambda row: (
        -row["motif_weighted_jaccard"],
        -row["shared_exact_bank_context_count"],
        row["first"],
        row["second"],
    ))

    motif_sources: dict[str, dict[str, int]] = defaultdict(dict)
    motif_metadata: dict[str, dict[str, Any]] = {}
    for report in source_reports:
        for signature, count in report["motif_counts"].items():
            motif_sources[signature][report["source_id"]] = int(count)
            motif_metadata.setdefault(signature, report["motif_metadata"][signature])
    shared_motifs = []
    for signature, per_source in motif_sources.items():
        if len(per_source) < 2:
            continue
        shared_motifs.append({
            "signature": signature,
            "source_count": len(per_source),
            "total_occurrences": sum(per_source.values()),
            "occurrences_by_source": dict(sorted(per_source.items())),
            **motif_metadata[signature],
            "truth_boundary": "local construction motif; subsystem role and causality unconfirmed",
        })
    shared_motifs.sort(key=lambda row: (
        -row["source_count"], -row["total_occurrences"], -row["component_count"], row["signature"]
    ))
    return {
        "pairwise_similarity": pairs,
        "shared_local_motifs": shared_motifs,
        "summary": {
            "source_count": len(source_reports),
            "pair_count": len(pairs),
            "shared_motif_count": len(shared_motifs),
            "motifs_present_in_all_sources": sum(
                row["source_count"] == len(source_reports) for row in shared_motifs
            ),
        },
    }


def compact_source_report(report: dict[str, Any]) -> dict[str, Any]:
    compact = copy.deepcopy(report)
    compact.pop("motif_counts", None)
    compact.pop("motif_metadata", None)
    return compact


def build_corpus_report(source_paths: list[tuple[str, Path]]) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for source_id, path in source_paths:
        blocks, metadata = extract_functional_blocks(path)
        metadata["path"] = str(path)
        metadata["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        reports.append(analyze_blocks(source_id, blocks, metadata))
    comparison = compare_sources(reports)
    return {
        "schema_version": 1,
        "status": "PASS",
        "classification": "LEGACY_STATIC_ARCHITECTURE_ONLY",
        "sources": [compact_source_report(report) for report in reports],
        "comparison": comparison,
        "truth_boundary": {
            "legacy_numeric_ids_are_modern_block_states": False,
            "rotation_or_reflection_matching_performed": False,
            "source_claims_prove_detected_roles": False,
            "static_similarity_proves_shared_runtime_semantics": False,
            "private_extremecraft_parity_confirmed": False,
            "ec_ready": False,
        },
    }


def parse_source(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise ArchitectureError("--source must use ID=PATH")
    source_id, path = raw.split("=", 1)
    source_id = clean_identifier(source_id)
    source_path = Path(path).resolve()
    if not source_path.is_file():
        raise ArchitectureError(f"source path does not exist: {source_path}")
    if source_path.suffix.lower() != ".schematic":
        raise ArchitectureError("legacy architecture sources must use .schematic")
    return source_id, source_path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Map translation-safe legacy cannon architecture and shared local construction motifs "
            "without converting numeric IDs or inventing subsystem roles"
        )
    )
    parser.add_argument("--source", action="append", required=True, help="ID=PATH")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        source_paths = [parse_source(raw) for raw in args.source]
        ids = [source_id for source_id, _path in source_paths]
        if len(set(ids)) != len(ids):
            raise ArchitectureError("source IDs must be unique")
        report = build_corpus_report(source_paths)
    except (OSError, json.JSONDecodeError, ArchitectureError, ValueError) as exc:
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
