#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
from pathlib import Path
from typing import Any, Iterable


def load_auditor(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("cannonlab_schem_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load auditor: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def distribution(
    coords: Iterable[tuple[int, int]],
    offset_x: int,
    offset_z: int,
) -> collections.Counter[tuple[int, int]]:
    return collections.Counter(
        ((x + offset_x) // 16, (z + offset_z) // 16)
        for x, z in coords
    )


def effective_min_corner(
    paste_chunk_local_x: int,
    paste_chunk_local_z: int,
    worldedit_offset_x: int,
    worldedit_offset_z: int,
) -> tuple[int, int]:
    """Translate a WorldEdit paste-point chunk offset into the schematic-minimum frame."""
    return (
        (paste_chunk_local_x + worldedit_offset_x) % 16,
        (paste_chunk_local_z + worldedit_offset_z) % 16,
    )


def paste_point_for_min_corner(
    minimum_chunk_local_x: int,
    minimum_chunk_local_z: int,
    worldedit_offset_x: int,
    worldedit_offset_z: int,
) -> tuple[int, int]:
    return (
        (minimum_chunk_local_x - worldedit_offset_x) % 16,
        (minimum_chunk_local_z - worldedit_offset_z) % 16,
    )


def summarize_scan(
    coords: list[tuple[int, int]],
    limit: int | None,
    worldedit_offset_x: int = 0,
    worldedit_offset_z: int = 0,
    *,
    paste_point_frame: bool,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for x in range(16):
        for z in range(16):
            effective_x, effective_z = (
                effective_min_corner(x, z, worldedit_offset_x, worldedit_offset_z)
                if paste_point_frame
                else (x, z)
            )
            counts = distribution(coords, effective_x, effective_z)
            maximum = max(counts.values(), default=0)
            row: dict[str, Any] = {
                "max": maximum,
                "chunks": len(counts),
                "top_counts": sorted(counts.values(), reverse=True)[:12],
            }
            if paste_point_frame:
                row.update({
                    "paste_chunk_local_x": x,
                    "paste_chunk_local_z": z,
                    "effective_min_corner_x": effective_x,
                    "effective_min_corner_z": effective_z,
                })
            else:
                row.update({"offset_x": x, "offset_z": z})
            if limit is not None:
                row["safe"] = maximum <= limit
            rows.append(row)

    best = min(
        rows,
        key=lambda row: (
            row["max"],
            row.get("paste_chunk_local_x", row.get("offset_x", 0)),
            row.get("paste_chunk_local_z", row.get("offset_z", 0)),
        ),
    )
    worst = max(
        rows,
        key=lambda row: (
            row["max"],
            row.get("paste_chunk_local_x", row.get("offset_x", 0)),
            row.get("paste_chunk_local_z", row.get("offset_z", 0)),
        ),
    )
    output: dict[str, Any] = {"best": best, "worst": worst}
    if limit is not None:
        safe_rows = [row for row in rows if row["safe"]]
        output["limit"] = limit
        output["safe_count"] = len(safe_rows)
        output["safe_offsets"] = safe_rows
    return output


def build_report(
    model: dict[str, Any],
    auditor: Any,
    file_path: Path,
    chunk_limit: int,
    block_entity_limit: int | None,
) -> dict[str, Any]:
    blocks = model["blocks"]
    dispenser_coords = [
        (x, z)
        for (x, _y, z), state in blocks.items()
        if auditor.base(state) == "minecraft:dispenser"
    ]
    block_entity_coords = [
        (int(entity["pos"][0]), int(entity["pos"][2]))
        for entity in model.get("block_entities", [])
        if entity.get("pos") is not None
    ]
    metadata = model.get("metadata") or {}
    we_x = int(metadata.get("WEOffsetX", 0) or 0)
    we_y = int(metadata.get("WEOffsetY", 0) or 0)
    we_z = int(metadata.get("WEOffsetZ", 0) or 0)

    dispenser_minimum = summarize_scan(
        dispenser_coords,
        chunk_limit,
        paste_point_frame=False,
    )
    dispenser_paste = summarize_scan(
        dispenser_coords,
        chunk_limit,
        we_x,
        we_z,
        paste_point_frame=True,
    )
    block_entity_minimum = summarize_scan(
        block_entity_coords,
        block_entity_limit,
        paste_point_frame=False,
    )
    block_entity_paste = summarize_scan(
        block_entity_coords,
        block_entity_limit,
        we_x,
        we_z,
        paste_point_frame=True,
    )

    warnings: list[str] = []
    errors: list[str] = []
    if we_x or we_z:
        warnings.append(
            "WorldEdit Metadata WEOffset changes the safe player paste-point offsets; "
            "do not copy schematic-minimum offsets directly into //paste instructions."
        )
    if dispenser_paste.get("safe_count", 0) == 0 and dispenser_coords:
        errors.append(
            f"no WorldEdit paste-point alignment satisfies dispenser limit {chunk_limit}"
        )
    if not dispenser_coords:
        errors.append("schematic contains no dispensers")
    if block_entity_limit is None:
        warnings.append(
            "block-entity pressure is reported without a pass/fail limit because the live FAWE threshold is unknown"
        )
    elif block_entity_coords and block_entity_paste.get("safe_count", 0) == 0:
        errors.append(
            "no WorldEdit paste-point alignment satisfies configured block-entity limit "
            f"{block_entity_limit}"
        )

    return {
        "status": "FAIL" if errors else "PASS",
        "schema": "cannonlab-paste-alignment-v1",
        "file": str(file_path),
        "format": model.get("format"),
        "data_version": model.get("data_version"),
        "dimensions": model.get("source_dimensions"),
        "schematic_offset": model.get("offset"),
        "worldedit_metadata_offset": {"x": we_x, "y": we_y, "z": we_z},
        "dispensers": {
            "count": len(dispenser_coords),
            "minimum_corner_alignment": dispenser_minimum,
            "worldedit_paste_point_alignment": dispenser_paste,
        },
        "block_entities": {
            "count": len(block_entity_coords),
            "minimum_corner_alignment": block_entity_minimum,
            "worldedit_paste_point_alignment": block_entity_paste,
        },
        "errors": errors,
        "warnings": warnings,
        "truth_boundary": (
            "The WorldEdit paste-point frame applies Sponge Metadata WEOffset X/Z values. "
            "This is static placement math, not proof that private ExtremeCraft FAWE uses every "
            "metadata field identically; verify one live chunk-coordinate canary."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit both schematic-minimum and WorldEdit player paste-point chunk alignments."
        )
    )
    parser.add_argument("schematic", type=Path)
    parser.add_argument(
        "--auditor",
        type=Path,
        default=Path(__file__).resolve().with_name("schem-audit.py"),
    )
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--block-entity-limit", type=int)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    auditor = load_auditor(args.auditor)
    loaded = auditor.load(args.schematic)
    model = auditor.decode_any(loaded[0], loaded[1])
    report = build_report(
        model,
        auditor,
        args.schematic,
        args.chunk_limit,
        args.block_entity_limit,
    )
    text = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
