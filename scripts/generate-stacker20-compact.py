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
    spec = importlib.util.spec_from_file_location("stacker20_open_muzzle_audit", script)
    if spec is None or spec.loader is None:
        raise GenerationError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def base(state: str) -> str:
    return state.split("[", 1)[0]


def put(blocks: dict[tuple[int, int, int], str], pos: tuple[int, int, int], state: str) -> None:
    previous = blocks.get(pos)
    if previous is not None and previous != state:
        raise GenerationError(f"conflict at {pos}: {previous!r} vs {state!r}")
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
                put(blocks, (x, y, z), state)


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    width, height, length = 12, 5, 8
    blocks: dict[tuple[int, int, int], str] = {}
    dispensers: list[tuple[int, int, int]] = []
    primary: list[list[int]] = []
    delayed: list[list[int]] = []
    obsidian = "minecraft:obsidian"

    # Muzzle floor and rails. Initial cannon max X is 11 because of the sand
    # blocks. The runtime target water begins at X=32, leaving X=12..31 clear.
    fill(blocks, (5, 0, 1), (5, 0, 6), obsidian)
    fill(blocks, (9, 0, 1), (11, 0, 6), obsidian)
    fill(blocks, (6, 0, 1), (8, 0, 1), obsidian)
    fill(blocks, (6, 0, 6), (8, 0, 6), obsidian)
    fill(blocks, (9, 1, 1), (11, 2, 1), obsidian)
    fill(blocks, (9, 1, 6), (11, 2, 6), obsidian)

    # One-high 3x4 source-water charge bed. The front is deliberately open to
    # the slab-supported projectile, unlike the rejected sealed-wall design.
    fill(blocks, (6, 1, 2), (8, 1, 5), "minecraft:water[level=0]")

    # Twelve top and twelve bottom charge dispensers.
    for x in (6, 7, 8):
        for z in range(2, 6):
            top = (x, 2, z)
            bottom = (x, 0, z)
            put(blocks, top, "minecraft:dispenser[facing=down,triggered=false]")
            put(blocks, bottom, "minecraft:dispenser[facing=up,triggered=false]")
            dispensers.extend((top, bottom))
            primary.extend(([x, 3, z], [x, -1, z]))

    # Six side charge dispensers.
    for x in (6, 7, 8):
        north = (x, 1, 1)
        south = (x, 1, 6)
        put(blocks, north, "minecraft:dispenser[facing=south,triggered=false]")
        put(blocks, south, "minecraft:dispenser[facing=north,triggered=false]")
        dispensers.extend((north, south))
        primary.extend(([x, 1, 0], [x, 1, 7]))

    # Two rear charge dispensers complete the 32-TNT charge. Rear corner cells
    # are sealed with obsidian.
    put(blocks, (5, 1, 2), obsidian)
    put(blocks, (5, 1, 5), obsidian)
    for z in (3, 4):
        rear = (5, 1, z)
        put(blocks, rear, "minecraft:dispenser[facing=east,triggered=false]")
        dispensers.append(rear)
        primary.append([4, 1, z])

    # Four bottom slabs stop the water while exposing the projectile above the
    # slab to the horizontal charge impulse. Payload dispensers drop TNT from
    # above so there is no full block between charge and projectile.
    for z in range(2, 6):
        put(
            blocks,
            (9, 1, z),
            "minecraft:stone_slab[type=bottom,waterlogged=false]",
        )
        payload = (9, 3, z)
        put(blocks, payload, "minecraft:dispenser[facing=down,triggered=false]")
        dispensers.append(payload)
        delayed.append([9, 4, z])

    # Two piston-released sand blocks. They begin at X=11 and are pushed to
    # X=12, the first block of the runtime flight corridor, where they fall.
    for z in (3, 4):
        put(blocks, (10, 3, z), "minecraft:piston[facing=east,extended=false]")
        put(blocks, (11, 3, z), "minecraft:sand")
        delayed.append([10, 4, z])

    put(blocks, (5, 3, 3), "minecraft:cyan_concrete")

    if len(dispensers) != 36:
        raise GenerationError(f"expected 36 dispensers, observed {len(dispensers)}")

    model = {
        "blocks": blocks,
        "block_entities": [
            {"pos": pos, "id": "minecraft:dispenser", "raw": {}}
            for pos in sorted(dispensers)
        ],
        "source_dimensions": {
            "width": width,
            "height": height,
            "length": length,
        },
    }
    metadata = {
        "id": "c32-open-muzzle",
        "charge_tnt": 32,
        "payload_tnt": 4,
        "sand_blocks": 2,
        "dispenser_count": 36,
        "primary_fire_inputs": primary,
        "delayed_fire_inputs": delayed,
        "cannon_max_x": 11,
        "target_water_x": 32,
        "target_wall_x": 33,
        "clear_corridor_blocks": 20,
        "truth_boundary": {
            "target_in_schematic": False,
            "field_control_proven": False,
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
    model, metadata = build()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    path = args.output_directory / "EC160-STACKER20-C32-OPENMUZZLE-P4-S2-v4.schem"
    audit.write_sponge_v2(path, model, 3465, canonical_gzip=True)

    root_name, root, trailing, _size, diagnostics = audit.load(path)
    decoded = audit.decode_any(root_name, root)
    if trailing:
        raise GenerationError("unexpected trailing NBT")
    if diagnostics.get("strict_gzip_valid") is not True:
        raise GenerationError("canonical gzip validation failed")
    expected = {
        pos: state for pos, state in model["blocks"].items() if base(state) not in AIR
    }
    observed = {
        pos: state for pos, state in decoded["blocks"].items() if base(state) not in AIR
    }
    if expected != observed:
        raise GenerationError("round-trip geometry mismatch")

    dispenser_coords = [
        (x, z)
        for (x, _y, z), state in decoded["blocks"].items()
        if base(state) == "minecraft:dispenser"
    ]
    scans = audit.scan_alignments(dispenser_coords)
    safe = [row for row in scans if row[0] <= 160]
    if len(dispenser_coords) != 36:
        raise GenerationError(f"round-trip dispenser count is {len(dispenser_coords)}")
    if len(safe) != 256:
        raise GenerationError(f"only {len(safe)}/256 EC160-safe alignments")

    b64 = Path(str(path) + ".b64")
    b64.write_text(base64.b64encode(path.read_bytes()).decode("ascii"), encoding="ascii")
    manifest = {
        "schema_version": 1,
        "mode": "from-scratch",
        "source_schematic": None,
        "data_version": 3465,
        "chunk_limit": 160,
        "candidate": {
            "schematic": path.name,
            "base64": b64.name,
            "metadata": metadata,
            "audit": {
                "status": "PASS",
                "safe_alignment_count": len(safe),
                "best_max": min(scans)[0],
                "worst_max": max(scans)[0],
            },
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
