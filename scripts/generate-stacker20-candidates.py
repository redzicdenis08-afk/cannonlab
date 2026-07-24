#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}


class GenerationError(ValueError):
    pass


def load_audit() -> Any:
    script = Path(__file__).with_name("schem-audit.py")
    spec = importlib.util.spec_from_file_location("stacker20_audit", script)
    if spec is None or spec.loader is None:
        raise GenerationError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def base(state: str) -> str:
    return state.split("[", 1)[0]


def set_block(blocks: dict[tuple[int, int, int], str], pos: tuple[int, int, int], state: str) -> None:
    previous = blocks.get(pos)
    if previous is not None and previous != state:
        raise GenerationError(f"conflicting blocks at {pos}: {previous!r} vs {state!r}")
    blocks[pos] = state


def fill(
    blocks: dict[tuple[int, int, int], str],
    minimum: tuple[int, int, int],
    maximum: tuple[int, int, int],
    state: str,
) -> None:
    for x in range(minimum[0], maximum[0] + 1):
        for y in range(minimum[1], maximum[1] + 1):
            for z in range(minimum[2], maximum[2] + 1):
                set_block(blocks, (x, y, z), state)


def model_for(charge_count: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if charge_count not in {40, 48, 52}:
        raise GenerationError(f"unsupported charge count {charge_count}")

    width, height, length = 12, 7, 8
    blocks: dict[tuple[int, int, int], str] = {}
    dispensers: list[tuple[int, int, int]] = []
    primary: list[list[int]] = []
    delayed: list[list[int]] = []

    obsidian = "minecraft:obsidian"
    water = "minecraft:water[level=0]"

    fill(blocks, (0, 0, 1), (10, 0, 6), obsidian)
    fill(blocks, (0, 2, 1), (10, 2, 1), obsidian)
    fill(blocks, (0, 2, 6), (10, 2, 6), obsidian)
    for x in (0, 9, 10):
        set_block(blocks, (x, 1, 1), obsidian)
        set_block(blocks, (x, 1, 6), obsidian)
    if charge_count == 52:
        fill(blocks, (0, 2, 2), (0, 2, 5), obsidian)
    else:
        fill(blocks, (0, 1, 2), (0, 2, 5), obsidian)
    fill(blocks, (1, 1, 2), (8, 1, 5), water)

    top_x = range(3, 9) if charge_count == 40 else range(1, 9)
    for x in top_x:
        for z in range(2, 6):
            pos = (x, 2, z)
            set_block(blocks, pos, "minecraft:dispenser[facing=down,triggered=false]")
            dispensers.append(pos)
            primary.append([x, 3, z])

    for x in range(1, 9):
        south = (x, 1, 1)
        north = (x, 1, 6)
        set_block(blocks, south, "minecraft:dispenser[facing=south,triggered=false]")
        set_block(blocks, north, "minecraft:dispenser[facing=north,triggered=false]")
        dispensers.extend((south, north))
        primary.extend(([x, 1, 0], [x, 1, 7]))

    if charge_count == 52:
        for z in range(2, 6):
            pos = (0, 1, z)
            set_block(blocks, pos, "minecraft:dispenser[facing=east,triggered=false]")
            dispensers.append(pos)
            primary.append([-1, 1, z])

    for z in range(2, 6):
        pos = (9, 1, z)
        set_block(blocks, pos, "minecraft:dispenser[facing=east,triggered=false]")
        dispensers.append(pos)
        delayed.append([9, 2, z])

    set_block(blocks, (10, 1, 1), obsidian)
    set_block(blocks, (10, 1, 6), obsidian)

    for z in (3, 4):
        set_block(
            blocks,
            (10, 3, z),
            "minecraft:oak_trapdoor[facing=east,half=bottom,open=false,powered=false,waterlogged=false]",
        )
        set_block(blocks, (10, 4, z), "minecraft:sand")
        delayed.append([11, 3, z])

    set_block(blocks, (0, 3, 3), "minecraft:cyan_concrete")

    expected_total = charge_count + 4
    if len(dispensers) != expected_total:
        raise GenerationError(f"dispenser count {len(dispensers)} != {expected_total}")

    entities = [
        {"pos": pos, "id": "minecraft:dispenser", "raw": {}}
        for pos in sorted(dispensers)
    ]
    model = {
        "blocks": blocks,
        "block_entities": entities,
        "source_dimensions": {
            "width": width,
            "height": height,
            "length": length,
        },
    }
    metadata = {
        "charge_count": charge_count,
        "payload_count": 4,
        "sand_count": 2,
        "total_dispenser_count": expected_total,
        "primary_fire_inputs": primary,
        "delayed_fire_inputs": delayed,
        "cannon_max_x": 10,
        "target_water_x": 31,
        "target_wall_x": 32,
        "clear_corridor_blocks": 20,
        "truth_boundary": {
            "target_in_schematic": False,
            "runtime_proven": False,
            "private_extremecraft_parity": False,
        },
    }
    return model, metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    audit = load_audit()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    rows = []

    for charge in (40, 48, 52):
        model, metadata = model_for(charge)
        path = args.output_directory / f"EC160-STACKER20-C{charge}-P4-S2-v2.schem"
        audit.write_sponge_v2(path, model, 3465, canonical_gzip=True)

        root_name, root, trailing, _size, diagnostics = audit.load(path)
        decoded = audit.decode_any(root_name, root)
        if trailing:
            raise GenerationError(f"trailing NBT in {path.name}")
        if diagnostics.get("strict_gzip_valid") is not True:
            raise GenerationError(f"non-canonical gzip in {path.name}")
        observed = {
            pos: state
            for pos, state in (decoded.get("blocks") or {}).items()
            if base(state) not in AIR
        }
        expected = {
            pos: state
            for pos, state in model["blocks"].items()
            if base(state) not in AIR
        }
        if observed != expected:
            raise GenerationError(f"round-trip geometry mismatch in {path.name}")

        dispenser_coords = [
            (x, z)
            for (x, _y, z), state in decoded["blocks"].items()
            if base(state) == "minecraft:dispenser"
        ]
        scans = audit.scan_alignments(dispenser_coords)
        safe = [row for row in scans if row[0] <= 160]
        if len(dispenser_coords) != metadata["total_dispenser_count"]:
            raise GenerationError(
                f"dispenser count {len(dispenser_coords)} != {metadata['total_dispenser_count']} in {path.name}"
            )
        if len(safe) != 256:
            raise GenerationError(f"not all alignments are EC160-safe in {path.name}")

        b64_path = Path(str(path) + ".b64")
        b64_path.write_text(base64.b64encode(path.read_bytes()).decode("ascii"), encoding="ascii")
        rows.append({
            "id": f"c{charge}",
            "schematic": path.name,
            "base64": b64_path.name,
            "metadata": metadata,
            "audit": {
                "status": "PASS",
                "dispenser_count": len(dispenser_coords),
                "safe_alignment_count": len(safe),
                "best_max": min(scans)[0],
                "worst_max": max(scans)[0],
            },
        })

    manifest = {
        "schema_version": 2,
        "mode": "from-scratch",
        "source_schematic": None,
        "data_version": 3465,
        "chunk_limit": 160,
        "candidates": rows,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
