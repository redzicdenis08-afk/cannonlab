#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import io
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, BinaryIO

END, BYTE, SHORT, INT, LONG, FLOAT, DOUBLE, BYTE_ARRAY, STRING, LIST, COMPOUND, INT_ARRAY, LONG_ARRAY = range(13)
AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
FLUID = {"minecraft:water", "minecraft:lava"}
SUPPORT_REQUIRED = {"minecraft:redstone_wire", "minecraft:repeater", "minecraft:comparator"}
TILE_BLOCKS = {
    "minecraft:dispenser", "minecraft:dropper", "minecraft:chest", "minecraft:trapped_chest",
    "minecraft:barrel", "minecraft:hopper", "minecraft:furnace", "minecraft:blast_furnace",
    "minecraft:smoker", "minecraft:brewing_stand", "minecraft:comparator", "minecraft:beacon",
    "minecraft:ender_chest", "minecraft:spawner", "minecraft:lectern",
}


class NBTError(ValueError):
    pass


def exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise NBTError(f"unexpected EOF: wanted {size}, got {len(data)}")
    return data


def unpack(stream: BinaryIO, fmt: str) -> Any:
    return struct.unpack(">" + fmt, exact(stream, struct.calcsize(">" + fmt)))[0]


def nbt_string(stream: BinaryIO) -> str:
    return exact(stream, unpack(stream, "H")).decode("utf-8")


def payload(stream: BinaryIO, tag: int) -> Any:
    if tag == BYTE: return unpack(stream, "b")
    if tag == SHORT: return unpack(stream, "h")
    if tag == INT: return unpack(stream, "i")
    if tag == LONG: return unpack(stream, "q")
    if tag == FLOAT: return unpack(stream, "f")
    if tag == DOUBLE: return unpack(stream, "d")
    if tag == BYTE_ARRAY:
        length = unpack(stream, "i")
        if length < 0: raise NBTError("negative byte-array length")
        return exact(stream, length)
    if tag == STRING: return nbt_string(stream)
    if tag == LIST:
        child, length = unpack(stream, "B"), unpack(stream, "i")
        if length < 0: raise NBTError("negative list length")
        return [payload(stream, child) for _ in range(length)]
    if tag == COMPOUND:
        result = {}
        while True:
            child = unpack(stream, "B")
            if child == END: return result
            name = nbt_string(stream)
            result[name] = payload(stream, child)
    if tag == INT_ARRAY:
        length = unpack(stream, "i")
        if length < 0: raise NBTError("negative int-array length")
        return [unpack(stream, "i") for _ in range(length)]
    if tag == LONG_ARRAY:
        length = unpack(stream, "i")
        if length < 0: raise NBTError("negative long-array length")
        return [unpack(stream, "q") for _ in range(length)]
    raise NBTError(f"unknown NBT tag {tag}")


def load(path: Path) -> tuple[str, dict[str, Any], bytes, int]:
    raw = path.read_bytes()
    try:
        decoded = gzip.decompress(raw)
    except OSError:
        decoded = raw
    stream = io.BytesIO(decoded)
    root_type = unpack(stream, "B")
    if root_type != COMPOUND:
        raise NBTError(f"root tag {root_type} is not a compound")
    name = nbt_string(stream)
    return name, payload(stream, COMPOUND), stream.read(), len(decoded)


def varints(data: bytes, expected: int) -> list[int]:
    values, value, shift = [], 0, 0
    for raw in data:
        value |= (raw & 0x7F) << shift
        if raw & 0x80:
            shift += 7
            if shift > 35: raise NBTError("VarInt too long")
        else:
            values.append(value)
            value, shift = 0, 0
    if shift: raise NBTError("truncated final VarInt")
    if len(values) != expected:
        raise NBTError(f"BlockData has {len(values)} entries, expected {expected}")
    return values


def base(state: str) -> str:
    return state.split("[", 1)[0]


def properties(state: str) -> dict[str, str]:
    if "[" not in state: return {}
    result = {}
    for part in state.split("[", 1)[1].rsplit("]", 1)[0].split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def distribution(coords: list[tuple[int, int]], offset_x: int, offset_z: int) -> Counter[tuple[int, int]]:
    return Counter(((x + offset_x) // 16, (z + offset_z) // 16) for x, z in coords)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Sponge v2 cannon schematics")
    parser.add_argument("schematic", type=Path)
    parser.add_argument("--chunk-limit", type=int, default=128)
    parser.add_argument("--expect-dispensers", type=int)
    parser.add_argument("--expect-aligned-max", type=int)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    root_name, root, trailing, uncompressed_size = load(args.schematic)
    schematic = root.get("Schematic", root) if root_name != "Schematic" else root
    for required in ("Version", "DataVersion", "Width", "Height", "Length", "Palette", "BlockData"):
        if required not in schematic:
            raise NBTError(f"missing required tag {required}")

    width, height, length = map(int, (schematic["Width"], schematic["Height"], schematic["Length"]))
    volume = width * height * length
    palette = schematic["Palette"]
    id_to_state = {int(value): state for state, value in palette.items()}
    block_ids = varints(schematic["BlockData"], volume)
    if set(block_ids) - set(id_to_state):
        raise NBTError("BlockData references unknown palette IDs")

    blocks: dict[tuple[int, int, int], str] = {}
    by_type: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    state_counts: Counter[str] = Counter()
    for index, palette_id in enumerate(block_ids):
        x = index % width
        quotient = index // width
        z = quotient % length
        y = quotient // length
        state = id_to_state[palette_id]
        blocks[(x, y, z)] = state
        by_type[base(state)].append((x, y, z))
        state_counts[state] += 1

    dispenser_coords = [(x, z) for x, _y, z in by_type.get("minecraft:dispenser", [])]
    aligned = distribution(dispenser_coords, 0, 0)
    aligned_max = max(aligned.values(), default=0)
    scans = []
    for offset_x in range(16):
        for offset_z in range(16):
            counts = distribution(dispenser_coords, offset_x, offset_z)
            scans.append((max(counts.values(), default=0), offset_x, offset_z, len(counts), sorted(counts.values(), reverse=True)))
    best = min(scans)
    worst = max(scans)

    support_failures = []
    for block_type in SUPPORT_REQUIRED:
        for x, y, z in by_type.get(block_type, []):
            if y == 0:
                support_failures.append({"block": block_type, "pos": [x, y, z], "reason": "below bounds"})
                continue
            below = base(blocks[(x, y - 1, z)])
            if below in AIR or below in FLUID:
                support_failures.append({"block": block_type, "pos": [x, y, z], "reason": f"unsupported by {below}"})

    block_entities = schematic.get("BlockEntities", []) or []
    out_of_bounds = []
    block_entity_ids: Counter[str] = Counter()
    for entity in block_entities:
        entity_id = str(entity.get("Id", entity.get("id", "unknown"))) if isinstance(entity, dict) else "invalid"
        block_entity_ids[entity_id] += 1
        pos = entity.get("Pos", entity.get("pos")) if isinstance(entity, dict) else None
        if isinstance(pos, list) and len(pos) >= 3:
            x, y, z = map(int, pos[:3])
            if not (0 <= x < width and 0 <= y < height and 0 <= z < length):
                out_of_bounds.append([x, y, z])

    repeaters = [
        {"state": state, "count": count, "properties": properties(state)}
        for state, count in state_counts.items() if base(state) == "minecraft:repeater"
    ]
    waters = [
        {"state": state, "count": count, "properties": properties(state)}
        for state, count in state_counts.items() if base(state) == "minecraft:water"
    ]
    tile_state_blocks = sum(len(coords) for block_type, coords in by_type.items() if block_type in TILE_BLOCKS)

    errors, warnings = [], []
    if int(schematic["Version"]) != 2: errors.append(f"Version={schematic['Version']} expected=2")
    if aligned_max > args.chunk_limit: errors.append(f"aligned dispenser max {aligned_max} exceeds {args.chunk_limit}")
    if support_failures: errors.append(f"{len(support_failures)} unsupported redstone components")
    if out_of_bounds: errors.append(f"{len(out_of_bounds)} block entities outside schematic bounds")
    if args.expect_dispensers is not None and len(dispenser_coords) != args.expect_dispensers:
        errors.append(f"dispensers={len(dispenser_coords)} expected={args.expect_dispensers}")
    if args.expect_aligned_max is not None and aligned_max != args.expect_aligned_max:
        errors.append(f"aligned_max={aligned_max} expected={args.expect_aligned_max}")
    if best[0] > args.chunk_limit:
        warnings.append(f"no alignment satisfies limit {args.chunk_limit}; best max is {best[0]}")
    if len(block_entities) != tile_state_blocks:
        warnings.append(f"explicit block entities {len(block_entities)} differ from tile-state blocks {tile_state_blocks}")
    if trailing not in (b"", b"\x00"):
        warnings.append(f"unexpected trailing bytes {trailing.hex()}")

    report = {
        "status": "PASS" if not errors else "FAIL",
        "file": str(args.schematic),
        "root_name": root_name,
        "gzip_bytes": args.schematic.stat().st_size,
        "uncompressed_bytes": uncompressed_size,
        "version": int(schematic["Version"]),
        "data_version": int(schematic["DataVersion"]),
        "dimensions": {"width": width, "height": height, "length": length, "volume": volume},
        "palette_entries": len(palette),
        "palette_max": schematic.get("PaletteMax"),
        "offset": schematic.get("Offset"),
        "block_entities": {
            "explicit": len(block_entities),
            "ids": dict(block_entity_ids),
            "tile_state_blocks": tile_state_blocks,
            "out_of_bounds": out_of_bounds,
        },
        "dispensers": {
            "count": len(dispenser_coords),
            "chunk_limit": args.chunk_limit,
            "aligned_max": aligned_max,
            "aligned_distribution": {f"{x},{z}": value for (x, z), value in sorted(aligned.items())},
            "best_alignment": {"offset_x": best[1], "offset_z": best[2], "max": best[0], "chunks": best[3], "top_counts": best[4][:12]},
            "worst_alignment": {"offset_x": worst[1], "offset_z": worst[2], "max": worst[0], "chunks": worst[3], "top_counts": worst[4][:12]},
        },
        "repeaters": repeaters,
        "water_states": waters,
        "support_failures": support_failures,
        "block_type_counts": dict(sorted((key, len(value)) for key, value in by_type.items() if key not in AIR)),
        "errors": errors,
        "warnings": warnings,
    }
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if not errors else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (NBTError, OSError, EOFError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, indent=2), file=sys.stderr)
        raise SystemExit(3)
