#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import io
import json
import math
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, BinaryIO, Iterable

END, BYTE, SHORT, INT, LONG, FLOAT, DOUBLE, BYTE_ARRAY, STRING, LIST, COMPOUND, INT_ARRAY, LONG_ARRAY = range(13)
AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
FLUID = {"minecraft:water", "minecraft:lava"}
SUPPORT_REQUIRED = {"minecraft:redstone_wire", "minecraft:repeater", "minecraft:comparator"}
TILE_BLOCKS = {
    "minecraft:dispenser", "minecraft:dropper", "minecraft:chest", "minecraft:trapped_chest",
    "minecraft:barrel", "minecraft:hopper", "minecraft:furnace", "minecraft:blast_furnace",
    "minecraft:smoker", "minecraft:brewing_stand", "minecraft:comparator", "minecraft:beacon",
    "minecraft:ender_chest", "minecraft:spawner", "minecraft:lectern", "minecraft:sign",
    "minecraft:wall_sign", "minecraft:shulker_box",
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


def parse_decoded_nbt(decoded: bytes) -> tuple[str, dict[str, Any], bytes]:
    stream = io.BytesIO(decoded)
    root_type = unpack(stream, "B")
    if root_type != COMPOUND:
        raise NBTError(f"root tag {root_type} is not a compound")
    name = nbt_string(stream)
    return name, payload(stream, COMPOUND), stream.read()


def gzip_deflate_bounds(raw: bytes) -> tuple[int, int]:
    if len(raw) < 18 or raw[:2] != b"\x1f\x8b" or raw[2] != 8:
        raise NBTError("not a supported gzip/deflate stream")
    flags = raw[3]
    if flags & 0xE0:
        raise NBTError(f"gzip reserved flags are set: 0x{flags:02x}")
    cursor = 10
    trailer_start = len(raw) - 8
    if flags & 0x04:
        if cursor + 2 > trailer_start:
            raise NBTError("truncated gzip extra-field length")
        extra_length = struct.unpack("<H", raw[cursor:cursor + 2])[0]
        cursor += 2 + extra_length
    for flag in (0x08, 0x10):
        if flags & flag:
            terminator = raw.find(b"\x00", cursor, trailer_start)
            if terminator < 0:
                raise NBTError("unterminated gzip string header field")
            cursor = terminator + 1
    if flags & 0x02:
        cursor += 2
    if cursor >= trailer_start:
        raise NBTError("gzip stream has no deflate payload")
    return cursor, trailer_start


def recover_truncated_gzip_nbt(raw: bytes, strict_error: Exception) -> tuple[str, dict[str, Any], bytes, bytes, dict[str, Any]]:
    start, end = gzip_deflate_bounds(raw)
    try:
        decoded = zlib.decompress(raw[start:end], -zlib.MAX_WBITS)
    except zlib.error as exc:
        raise NBTError(f"gzip decompression failed: {strict_error}; raw deflate recovery failed: {exc}") from exc

    expected_size = struct.unpack("<I", raw[-4:])[0]
    repair_candidates = []
    for missing_end_tags in range(1, 5):
        repaired = decoded + (b"\x00" * missing_end_tags)
        if expected_size != (len(repaired) & 0xFFFFFFFF):
            continue
        try:
            name, root, trailing = parse_decoded_nbt(repaired)
        except NBTError:
            continue
        if trailing:
            continue
        repair_candidates.append((missing_end_tags, repaired, name, root, trailing))

    if len(repair_candidates) != 1:
        raise NBTError(
            f"gzip decompression failed: {strict_error}; recoverable terminal TAG_End candidate count={len(repair_candidates)}"
        )

    missing_end_tags, repaired, name, root, trailing = repair_candidates[0]
    diagnostics = {
        "compression": "gzip-recovered-terminal-end-tags",
        "strict_gzip_valid": False,
        "strict_error": str(strict_error),
        "raw_deflate_valid": True,
        "decoded_bytes_before_repair": len(decoded),
        "decoded_bytes_after_repair": len(repaired),
        "gzip_isize": expected_size,
        "appended_terminal_end_tags": missing_end_tags,
        "repair_scope": "terminal TAG_End bytes only",
        "warning": (
            "The gzip trailer failed validation and the raw NBT ended before terminal TAG_End bytes. "
            "CannonLab recovered exactly one structurally complete candidate whose repaired length matches gzip ISIZE."
        ),
    }
    return name, root, trailing, repaired, diagnostics


def load(path: Path) -> tuple[str, dict[str, Any], bytes, int, dict[str, Any]]:
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        try:
            decoded = gzip.decompress(raw)
            name, root, trailing = parse_decoded_nbt(decoded)
            diagnostics = {
                "compression": "gzip",
                "strict_gzip_valid": True,
                "raw_deflate_valid": True,
                "appended_terminal_end_tags": 0,
            }
            return name, root, trailing, len(decoded), diagnostics
        except OSError as exc:
            name, root, trailing, repaired, diagnostics = recover_truncated_gzip_nbt(raw, exc)
            return name, root, trailing, len(repaired), diagnostics

    name, root, trailing = parse_decoded_nbt(raw)
    return name, root, trailing, len(raw), {
        "compression": "raw-nbt",
        "strict_gzip_valid": None,
        "raw_deflate_valid": None,
        "appended_terminal_end_tags": 0,
    }


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


def encode_varints(values: Iterable[int]) -> bytes:
    out = bytearray()
    for value in values:
        if value < 0:
            raise NBTError("negative palette index")
        while True:
            part = value & 0x7F
            value >>= 7
            out.append(part | (0x80 if value else 0))
            if not value:
                break
    return bytes(out)


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


def state_string(compound: dict[str, Any]) -> str:
    name = str(compound.get("Name", "minecraft:air"))
    props = compound.get("Properties") or {}
    if not props:
        return name
    return name + "[" + ",".join(f"{key}={props[key]}" for key in sorted(props)) + "]"


def decode_packed_longs(values: list[int], count: int, palette_size: int) -> list[int]:
    bits = max(2, (max(1, palette_size) - 1).bit_length())
    expected_longs = math.ceil(count * bits / 64)
    if len(values) != expected_longs:
        raise NBTError(f"BlockStates has {len(values)} longs, expected {expected_longs} for {count} blocks at {bits} bits")
    unsigned = [value & ((1 << 64) - 1) for value in values]
    mask = (1 << bits) - 1
    result = []
    for index in range(count):
        bit_index = index * bits
        long_index, bit_offset = divmod(bit_index, 64)
        value = (unsigned[long_index] >> bit_offset) & mask
        if bit_offset + bits > 64:
            value |= (unsigned[long_index + 1] << (64 - bit_offset)) & mask
        if value >= palette_size:
            raise NBTError(f"BlockStates palette index {value} exceeds palette size {palette_size}")
        result.append(value)
    return result


def block_entity_id(block_type: str) -> str:
    if block_type.endswith("_wall_sign") or block_type.endswith("_sign"):
        return "minecraft:sign"
    if block_type.endswith("_shulker_box"):
        return "minecraft:shulker_box"
    return block_type


def decode_sponge(root_name: str, root: dict[str, Any]) -> dict[str, Any]:
    schematic = root.get("Schematic", root) if root_name != "Schematic" else root
    for required in ("Version", "DataVersion", "Width", "Height", "Length", "Palette", "BlockData"):
        if required not in schematic:
            raise NBTError(f"missing required Sponge tag {required}")
    width, height, length = map(int, (schematic["Width"], schematic["Height"], schematic["Length"]))
    if min(width, height, length) <= 0:
        raise NBTError(f"invalid dimensions {width}x{height}x{length}")
    volume = width * height * length
    id_to_state = {int(value): state for state, value in schematic["Palette"].items()}
    block_ids = varints(schematic["BlockData"], volume)
    if set(block_ids) - set(id_to_state):
        raise NBTError("BlockData references unknown palette IDs")
    blocks = {}
    for index, palette_id in enumerate(block_ids):
        x = index % width
        quotient = index // width
        z = quotient % length
        y = quotient // length
        blocks[(x, y, z)] = id_to_state[palette_id]
    entities = []
    for entity in schematic.get("BlockEntities", []) or []:
        if not isinstance(entity, dict):
            continue
        pos = entity.get("Pos", entity.get("pos"))
        if isinstance(pos, list) and len(pos) >= 3:
            x, y, z = map(int, pos[:3])
            entities.append({"pos": (x, y, z), "id": str(entity.get("Id", entity.get("id", "unknown"))), "raw": entity})
    return {
        "format": "sponge-v2",
        "version": int(schematic["Version"]),
        "sub_version": None,
        "data_version": int(schematic["DataVersion"]),
        "metadata": schematic.get("Metadata") or {},
        "offset": schematic.get("Offset"),
        "blocks": blocks,
        "block_entities": entities,
        "source_dimensions": {"width": width, "height": height, "length": length},
        "palette_entries": len(id_to_state),
        "palette_max": schematic.get("PaletteMax"),
    }


def decode_litematic(root: dict[str, Any]) -> dict[str, Any]:
    regions = root.get("Regions")
    if not isinstance(regions, dict) or not regions:
        raise NBTError("litematic has no Regions")
    blocks: dict[tuple[int, int, int], str] = {}
    block_entities = []
    overlaps = []
    region_reports = []
    for region_name, region in regions.items():
        size = region.get("Size") or {}
        position = region.get("Position") or {}
        signed = tuple(int(size.get(axis, 0)) for axis in ("x", "y", "z"))
        dimensions = tuple(abs(value) for value in signed)
        if min(dimensions) <= 0:
            raise NBTError(f"region {region_name!r} has invalid Size={size}")
        corner = tuple(int(position.get(axis, 0)) for axis in ("x", "y", "z"))
        region_min = tuple(
            min(corner[index], corner[index] + signed[index] + (1 if signed[index] < 0 else -1))
            for index in range(3)
        )
        palette = region.get("BlockStatePalette") or []
        states = [state_string(entry) for entry in palette]
        volume = dimensions[0] * dimensions[1] * dimensions[2]
        ids = decode_packed_longs(region.get("BlockStates") or [], volume, len(states))
        for index, palette_id in enumerate(ids):
            x = index % dimensions[0]
            quotient = index // dimensions[0]
            z = quotient % dimensions[2]
            y = quotient // dimensions[2]
            pos = tuple(region_min[i] + value for i, value in enumerate((x, y, z)))
            if pos in blocks and blocks[pos] != states[palette_id]:
                overlaps.append({"pos": list(pos), "first": blocks[pos], "second": states[palette_id], "region": region_name})
            blocks[pos] = states[palette_id]
        for entity in region.get("TileEntities", []) or []:
            if not isinstance(entity, dict) or not all(axis in entity for axis in ("x", "y", "z")):
                continue
            local = tuple(int(entity[axis]) for axis in ("x", "y", "z"))
            pos = tuple(region_min[index] + local[index] for index in range(3))
            state = blocks.get(pos, "minecraft:air")
            block_entities.append({"pos": pos, "id": block_entity_id(base(state)), "raw": entity})
        region_reports.append({
            "name": region_name,
            "position": dict(position),
            "size": dict(size),
            "dimensions": {"width": dimensions[0], "height": dimensions[1], "length": dimensions[2]},
            "palette_entries": len(states),
            "tile_entities": len(region.get("TileEntities", []) or []),
        })
    if overlaps:
        raise NBTError(f"litematic regions contain {len(overlaps)} conflicting overlapping blocks")
    min_x = min(x for x, _y, _z in blocks)
    min_y = min(y for _x, y, _z in blocks)
    min_z = min(z for _x, _y, z in blocks)
    normalized = {(x - min_x, y - min_y, z - min_z): state for (x, y, z), state in blocks.items()}
    normalized_entities = [dict(entity, pos=(entity["pos"][0] - min_x, entity["pos"][1] - min_y, entity["pos"][2] - min_z)) for entity in block_entities]
    max_x = max(x for x, _y, _z in normalized)
    max_y = max(y for _x, y, _z in normalized)
    max_z = max(z for _x, _y, z in normalized)
    return {
        "format": "litematic",
        "version": int(root.get("Version", 0)),
        "sub_version": root.get("SubVersion"),
        "data_version": int(root.get("MinecraftDataVersion", 0)),
        "metadata": root.get("Metadata") or {},
        "offset": [min_x, min_y, min_z],
        "blocks": normalized,
        "block_entities": normalized_entities,
        "source_dimensions": {"width": max_x + 1, "height": max_y + 1, "length": max_z + 1},
        "palette_entries": len(set(normalized.values())),
        "palette_max": None,
        "regions": region_reports,
    }


def decode_any(root_name: str, root: dict[str, Any]) -> dict[str, Any]:
    if "Regions" in root and "MinecraftDataVersion" in root:
        return decode_litematic(root)
    return decode_sponge(root_name, root)


def distribution(coords: list[tuple[int, int]], offset_x: int, offset_z: int) -> Counter[tuple[int, int]]:
    return Counter(((x + offset_x) // 16, (z + offset_z) // 16) for x, z in coords)


def scan_alignments(coords: list[tuple[int, int]]) -> list[tuple[int, int, int, int, list[int]]]:
    scans = []
    for offset_x in range(16):
        for offset_z in range(16):
            counts = distribution(coords, offset_x, offset_z)
            scans.append((max(counts.values(), default=0), offset_x, offset_z, len(counts), sorted(counts.values(), reverse=True)))
    return scans


def write_name(stream: io.BytesIO, value: str) -> None:
    raw = value.encode("utf-8")
    stream.write(struct.pack(">H", len(raw)))
    stream.write(raw)


def write_named_header(stream: io.BytesIO, tag: int, name: str) -> None:
    stream.write(struct.pack(">B", tag))
    write_name(stream, name)


def write_string_payload(stream: io.BytesIO, value: str) -> None:
    write_name(stream, value)


def write_sponge_v2(path: Path, model: dict[str, Any], data_version: int) -> None:
    blocks = model["blocks"]
    width = model["source_dimensions"]["width"]
    height = model["source_dimensions"]["height"]
    length = model["source_dimensions"]["length"]
    states = sorted(set(blocks.values()), key=lambda value: (base(value) not in AIR, value))
    if "minecraft:air" not in states:
        states.insert(0, "minecraft:air")
    palette = {state: index for index, state in enumerate(states)}
    ids = []
    for y in range(height):
        for z in range(length):
            for x in range(width):
                ids.append(palette[blocks.get((x, y, z), "minecraft:air")])
    block_data = encode_varints(ids)

    out = io.BytesIO()
    write_named_header(out, COMPOUND, "Schematic")
    write_named_header(out, COMPOUND, "Metadata")
    for axis in ("X", "Y", "Z"):
        write_named_header(out, INT, f"WEOffset{axis}")
        out.write(struct.pack(">i", 0))
    out.write(b"\x00")
    write_named_header(out, COMPOUND, "Palette")
    for state, value in palette.items():
        write_named_header(out, INT, state)
        out.write(struct.pack(">i", value))
    out.write(b"\x00")

    write_named_header(out, LIST, "BlockEntities")
    out.write(struct.pack(">B", COMPOUND))
    entities = []
    seen = set()
    for entity in model["block_entities"]:
        pos = tuple(map(int, entity["pos"]))
        state = base(blocks.get(pos, "minecraft:air"))
        if state not in TILE_BLOCKS and not state.endswith("_sign") and not state.endswith("_wall_sign") and not state.endswith("_shulker_box"):
            continue
        if pos in seen:
            continue
        seen.add(pos)
        entities.append((pos, block_entity_id(state)))
    out.write(struct.pack(">i", len(entities)))
    for (x, y, z), entity_id in entities:
        write_named_header(out, STRING, "Id")
        write_string_payload(out, entity_id)
        write_named_header(out, INT_ARRAY, "Pos")
        out.write(struct.pack(">i", 3))
        out.write(struct.pack(">iii", x, y, z))
        out.write(b"\x00")

    for tag, name, value, fmt in (
        (INT, "DataVersion", data_version, "i"),
        (SHORT, "Height", height, "h"),
        (SHORT, "Length", length, "h"),
        (INT, "PaletteMax", len(palette), "i"),
        (INT, "Version", 2, "i"),
        (SHORT, "Width", width, "h"),
    ):
        write_named_header(out, tag, name)
        out.write(struct.pack(">" + fmt, value))
    write_named_header(out, BYTE_ARRAY, "BlockData")
    out.write(struct.pack(">i", len(block_data)))
    out.write(block_data)
    write_named_header(out, INT_ARRAY, "Offset")
    out.write(struct.pack(">i", 3))
    out.write(struct.pack(">iii", 0, 0, 0))
    out.write(b"\x00")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(out.getvalue(), compresslevel=9, mtime=0))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Sponge v2 and Litematica cannon schematics")
    parser.add_argument("schematic", type=Path)
    parser.add_argument("--chunk-limit", type=int, default=160, help="ExtremeCraft user-reported current default is 160")
    parser.add_argument("--block-entity-limit", type=int, help="Optional server/FAWE total block-entity cap; unknown on ExtremeCraft")
    parser.add_argument("--expect-dispensers", type=int)
    parser.add_argument("--expect-aligned-max", type=int)
    parser.add_argument("--expect-format", choices=("sponge-v2", "litematic"))
    parser.add_argument("--require-all-alignments-safe", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--convert-sponge-out", type=Path, help="Convert decoded input to Sponge v2 .schem")
    parser.add_argument("--output-data-version", type=int, default=3465)
    parser.add_argument("--allow-data-version-retag", action="store_true", help="Allow numeric DataVersion retagging without Mojang datafixing")
    args = parser.parse_args()

    root_name, root, trailing, uncompressed_size, container_diagnostics = load(args.schematic)
    model = decode_any(root_name, root)
    blocks = model["blocks"]
    dimensions = model["source_dimensions"]
    width, height, length = dimensions["width"], dimensions["height"], dimensions["length"]
    by_type: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    state_counts: Counter[str] = Counter()
    for pos, state in blocks.items():
        by_type[base(state)].append(pos)
        state_counts[state] += 1

    dispenser_coords = [(x, z) for x, _y, z in by_type.get("minecraft:dispenser", [])]
    aligned = distribution(dispenser_coords, 0, 0)
    aligned_max = max(aligned.values(), default=0)
    scans = scan_alignments(dispenser_coords)
    best, worst = min(scans), max(scans)
    safe_alignments = [{"offset_x": scan[1], "offset_z": scan[2], "max": scan[0]} for scan in scans if scan[0] <= args.chunk_limit]

    support_failures = []
    for block_type in SUPPORT_REQUIRED:
        for x, y, z in by_type.get(block_type, []):
            if y == 0:
                support_failures.append({"block": block_type, "pos": [x, y, z], "reason": "below bounds"})
                continue
            below = base(blocks.get((x, y - 1, z), "minecraft:air"))
            if below in AIR or below in FLUID:
                support_failures.append({"block": block_type, "pos": [x, y, z], "reason": f"unsupported by {below}"})

    block_entities = model["block_entities"]
    out_of_bounds = []
    block_entity_ids: Counter[str] = Counter()
    block_entity_coords = []
    empty_dispenser_entities = 0
    for entity in block_entities:
        entity_id = str(entity.get("id", "unknown"))
        block_entity_ids[entity_id] += 1
        x, y, z = map(int, entity["pos"])
        block_entity_coords.append((x, z))
        if not (0 <= x < width and 0 <= y < height and 0 <= z < length):
            out_of_bounds.append([x, y, z])
        if base(blocks.get((x, y, z), "minecraft:air")) == "minecraft:dispenser" and not (entity.get("raw") or {}).get("Items"):
            empty_dispenser_entities += 1
    entity_scans = scan_alignments(block_entity_coords)
    entity_best, entity_worst = min(entity_scans), max(entity_scans)

    repeaters = [
        {"state": state, "count": count, "properties": properties(state)}
        for state, count in state_counts.items() if base(state) == "minecraft:repeater"
    ]
    waters = [
        {"state": state, "count": count, "properties": properties(state)}
        for state, count in state_counts.items() if base(state) == "minecraft:water"
    ]
    tile_state_blocks = sum(
        len(coords) for block_type, coords in by_type.items()
        if block_type in TILE_BLOCKS or block_type.endswith("_sign") or block_type.endswith("_wall_sign") or block_type.endswith("_shulker_box")
    )

    errors, warnings = [], []
    if container_diagnostics.get("warning"):
        warnings.append(str(container_diagnostics["warning"]))
    if model["format"] == "sponge-v2" and model["version"] != 2:
        errors.append(f"Version={model['version']} expected=2")
    if args.expect_format and model["format"] != args.expect_format:
        errors.append(f"format={model['format']} expected={args.expect_format}")
    if aligned_max > args.chunk_limit:
        errors.append(f"aligned dispenser max {aligned_max} exceeds {args.chunk_limit}")
    if not safe_alignments and dispenser_coords:
        warnings.append(f"no alignment satisfies dispenser limit {args.chunk_limit}; best max is {best[0]}")
    elif worst[0] > args.chunk_limit:
        message = f"{len(safe_alignments)}/256 alignments satisfy limit {args.chunk_limit}; worst max is {worst[0]}"
        if args.require_all_alignments_safe:
            errors.append(message)
        else:
            warnings.append(message)
    if support_failures: errors.append(f"{len(support_failures)} unsupported redstone components")
    if out_of_bounds: errors.append(f"{len(out_of_bounds)} block entities outside schematic bounds")
    if args.block_entity_limit is not None and len(block_entities) > args.block_entity_limit:
        errors.append(f"block_entities={len(block_entities)} exceeds configured limit {args.block_entity_limit}")
    if args.expect_dispensers is not None and len(dispenser_coords) != args.expect_dispensers:
        errors.append(f"dispensers={len(dispenser_coords)} expected={args.expect_dispensers}")
    if args.expect_aligned_max is not None and aligned_max != args.expect_aligned_max:
        errors.append(f"aligned_max={aligned_max} expected={args.expect_aligned_max}")
    if len(block_entities) != tile_state_blocks:
        warnings.append(f"explicit block entities {len(block_entities)} differ from tile-state blocks {tile_state_blocks}")
    if trailing not in (b"", b"\x00"):
        warnings.append(f"unexpected trailing bytes {trailing.hex()}")
    if model["format"] == "litematic":
        warnings.append("Litematica files are not pasted directly by ExtremeCraft/WorldEdit; convert to Sponge v2 first")
    if model["data_version"] != 3465:
        warnings.append(f"DataVersion={model['data_version']} differs from the field-verified ExtremeCraft Sponge target 3465")

    converted = None
    if args.convert_sponge_out:
        if model["data_version"] != args.output_data_version and not args.allow_data_version_retag:
            errors.append(
                f"conversion requested DataVersion {args.output_data_version} from source {model['data_version']} without --allow-data-version-retag"
            )
        elif errors:
            warnings.append("conversion skipped because audit has errors")
        else:
            write_sponge_v2(args.convert_sponge_out, model, args.output_data_version)
            converted = str(args.convert_sponge_out)

    report = {
        "status": "PASS" if not errors else "FAIL",
        "file": str(args.schematic),
        "format": model["format"],
        "root_name": root_name,
        "gzip_bytes": args.schematic.stat().st_size,
        "uncompressed_bytes": uncompressed_size,
        "container_diagnostics": container_diagnostics,
        "version": model["version"],
        "sub_version": model["sub_version"],
        "data_version": model["data_version"],
        "dimensions": {**dimensions, "volume": width * height * length},
        "metadata": model["metadata"],
        "regions": model.get("regions"),
        "palette_entries": model["palette_entries"],
        "palette_max": model["palette_max"],
        "offset": model["offset"],
        "block_entities": {
            "explicit": len(block_entities),
            "ids": dict(block_entity_ids),
            "tile_state_blocks": tile_state_blocks,
            "out_of_bounds": out_of_bounds,
            "empty_dispenser_entities": empty_dispenser_entities,
            "best_alignment": {"offset_x": entity_best[1], "offset_z": entity_best[2], "max": entity_best[0], "chunks": entity_best[3], "top_counts": entity_best[4][:12]},
            "worst_alignment": {"offset_x": entity_worst[1], "offset_z": entity_worst[2], "max": entity_worst[0], "chunks": entity_worst[3], "top_counts": entity_worst[4][:12]},
        },
        "dispensers": {
            "count": len(dispenser_coords),
            "chunk_limit": args.chunk_limit,
            "aligned_max": aligned_max,
            "aligned_distribution": {f"{x},{z}": value for (x, z), value in sorted(aligned.items())},
            "safe_alignment_count": len(safe_alignments),
            "safe_alignments": safe_alignments,
            "best_alignment": {"offset_x": best[1], "offset_z": best[2], "max": best[0], "chunks": best[3], "top_counts": best[4][:12]},
            "worst_alignment": {"offset_x": worst[1], "offset_z": worst[2], "max": worst[0], "chunks": worst[3], "top_counts": worst[4][:12]},
        },
        "repeaters": repeaters,
        "water_states": waters,
        "support_failures": support_failures,
        "block_type_counts": dict(sorted((key, len(value)) for key, value in by_type.items() if key not in AIR)),
        "converted_sponge": converted,
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
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, indent=2), file=sys.stderr)
        raise SystemExit(3)
