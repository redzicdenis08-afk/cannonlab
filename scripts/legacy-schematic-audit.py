#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LegacySchematicError(ValueError):
    pass


MAX_DECOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_COLLECTION_LENGTH = 100_000_000
MAX_STRING_BYTES = 1_000_000
MAX_DEPTH = 64

LEGACY_COMPONENT_IDS = {
    8: "flowing_water",
    9: "water",
    12: "sand",
    23: "dispenser",
    29: "sticky_piston",
    33: "piston",
    34: "piston_head",
    46: "tnt",
    49: "obsidian",
    55: "redstone_wire",
    75: "unlit_redstone_torch",
    76: "redstone_torch",
    77: "stone_button",
    93: "unpowered_repeater",
    94: "powered_repeater",
    143: "wooden_button",
    152: "redstone_block",
    165: "slime_block",
    218: "observer",
}


@dataclass
class NbtReader:
    data: bytes
    offset: int = 0

    def _take(self, size: int) -> bytes:
        if size < 0 or self.offset + size > len(self.data):
            raise LegacySchematicError("truncated NBT payload")
        value = self.data[self.offset : self.offset + size]
        self.offset += size
        return value

    def u8(self) -> int:
        return self._take(1)[0]

    def i8(self) -> int:
        return struct.unpack(">b", self._take(1))[0]

    def i16(self) -> int:
        return struct.unpack(">h", self._take(2))[0]

    def u16(self) -> int:
        return struct.unpack(">H", self._take(2))[0]

    def i32(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def i64(self) -> int:
        return struct.unpack(">q", self._take(8))[0]

    def f32(self) -> float:
        return struct.unpack(">f", self._take(4))[0]

    def f64(self) -> float:
        return struct.unpack(">d", self._take(8))[0]

    def string(self) -> str:
        length = self.u16()
        if length > MAX_STRING_BYTES:
            raise LegacySchematicError(f"NBT string exceeds {MAX_STRING_BYTES} bytes")
        return self._take(length).decode("utf-8", errors="strict")

    def collection_length(self) -> int:
        length = self.i32()
        if length < 0 or length > MAX_COLLECTION_LENGTH:
            raise LegacySchematicError(f"invalid NBT collection length: {length}")
        return length

    def payload(self, tag_type: int, depth: int = 0) -> Any:
        if depth > MAX_DEPTH:
            raise LegacySchematicError("NBT nesting is too deep")
        if tag_type == 0:
            return None
        if tag_type == 1:
            return self.i8()
        if tag_type == 2:
            return self.i16()
        if tag_type == 3:
            return self.i32()
        if tag_type == 4:
            return self.i64()
        if tag_type == 5:
            return self.f32()
        if tag_type == 6:
            return self.f64()
        if tag_type == 7:
            return self._take(self.collection_length())
        if tag_type == 8:
            return self.string()
        if tag_type == 9:
            child_type = self.u8()
            return [self.payload(child_type, depth + 1) for _ in range(self.collection_length())]
        if tag_type == 10:
            result: dict[str, Any] = {}
            while True:
                child_type = self.u8()
                if child_type == 0:
                    return result
                name = self.string()
                if name in result:
                    raise LegacySchematicError(f"duplicate NBT compound key: {name}")
                result[name] = self.payload(child_type, depth + 1)
        if tag_type == 11:
            return [self.i32() for _ in range(self.collection_length())]
        if tag_type == 12:
            return [self.i64() for _ in range(self.collection_length())]
        raise LegacySchematicError(f"unsupported NBT tag type: {tag_type}")


def read_payload(path: Path) -> bytes:
    raw = path.read_bytes()
    if raw[:2] != b"\x1f\x8b":
        if len(raw) > MAX_DECOMPRESSED_BYTES:
            raise LegacySchematicError("raw NBT exceeds safety limit")
        return raw
    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as handle:
        payload = handle.read(MAX_DECOMPRESSED_BYTES + 1)
    if len(payload) > MAX_DECOMPRESSED_BYTES:
        raise LegacySchematicError("decompressed NBT exceeds safety limit")
    return payload


def parse_root(path: Path) -> tuple[str, dict[str, Any], int]:
    payload = read_payload(path)
    reader = NbtReader(payload)
    tag_type = reader.u8()
    if tag_type != 10:
        raise LegacySchematicError("root NBT tag must be a compound")
    root_name = reader.string()
    root = reader.payload(tag_type)
    if reader.offset != len(payload):
        raise LegacySchematicError(
            f"trailing bytes after root compound: {len(payload) - reader.offset}"
        )
    if not isinstance(root, dict):
        raise LegacySchematicError("root NBT payload is not a compound")
    return root_name, root, len(payload)


def require_int(root: dict[str, Any], key: str) -> int:
    value = root.get(key)
    if not isinstance(value, int):
        raise LegacySchematicError(f"missing or invalid integer tag: {key}")
    return value


def require_bytes(root: dict[str, Any], key: str) -> bytes:
    value = root.get(key)
    if not isinstance(value, bytes):
        raise LegacySchematicError(f"missing or invalid byte-array tag: {key}")
    return value


def full_block_id(blocks: bytes, add_blocks: bytes | None, index: int) -> int:
    low = blocks[index]
    if add_blocks is None:
        return low
    packed = add_blocks[index // 2]
    high = (packed & 0x0F) if index % 2 == 0 else ((packed >> 4) & 0x0F)
    return low | (high << 8)


def scan_chunk_offsets(
    dispenser_coordinates: list[tuple[int, int, int]], chunk_limit: int
) -> dict[str, Any]:
    offsets: list[dict[str, int]] = []
    best_max: int | None = None
    best_offsets: list[dict[str, int]] = []
    legal_offsets: list[dict[str, int]] = []
    for offset_x in range(16):
        for offset_z in range(16):
            counts: dict[tuple[int, int], int] = defaultdict(int)
            for x, _y, z in dispenser_coordinates:
                counts[((x + offset_x) // 16, (z + offset_z) // 16)] += 1
            maximum = max(counts.values(), default=0)
            row = {"x": offset_x, "z": offset_z, "max_dispensers_per_chunk": maximum}
            offsets.append(row)
            if best_max is None or maximum < best_max:
                best_max = maximum
                best_offsets = [row]
            elif maximum == best_max:
                best_offsets.append(row)
            if maximum <= chunk_limit:
                legal_offsets.append(row)
    return {
        "chunk_limit": chunk_limit,
        "best_max_dispensers_per_chunk": best_max or 0,
        "best_offsets": best_offsets,
        "legal_offset_count": len(legal_offsets),
        "legal_offsets": legal_offsets,
        "status": "PASS" if legal_offsets else "FAIL",
        "all_offsets_scanned": len(offsets),
    }


def audit_legacy_schematic(path: Path, chunk_limit: int = 160) -> dict[str, Any]:
    root_name, root, decompressed_bytes = parse_root(path)
    width = require_int(root, "Width")
    height = require_int(root, "Height")
    length = require_int(root, "Length")
    if min(width, height, length) <= 0:
        raise LegacySchematicError("Width, Height, and Length must be positive")
    volume = width * height * length
    if volume > MAX_COLLECTION_LENGTH:
        raise LegacySchematicError(f"schematic volume exceeds safety limit: {volume}")

    blocks = require_bytes(root, "Blocks")
    data = require_bytes(root, "Data")
    if len(blocks) != volume:
        raise LegacySchematicError(f"Blocks length {len(blocks)} does not match volume {volume}")
    if len(data) != volume:
        raise LegacySchematicError(f"Data length {len(data)} does not match volume {volume}")
    add_blocks_value = root.get("AddBlocks")
    add_blocks = add_blocks_value if isinstance(add_blocks_value, bytes) else None
    if add_blocks is not None and len(add_blocks) < (volume + 1) // 2:
        raise LegacySchematicError("AddBlocks is shorter than required for the schematic volume")

    counts: Counter[int] = Counter()
    dispenser_coordinates: list[tuple[int, int, int]] = []
    for index in range(volume):
        block_id = full_block_id(blocks, add_blocks, index)
        counts[block_id] += 1
        if block_id == 23:
            x = index % width
            z = (index // width) % length
            y = index // (width * length)
            dispenser_coordinates.append((x, y, z))

    tile_entities = root.get("TileEntities", [])
    if not isinstance(tile_entities, list):
        raise LegacySchematicError("TileEntities must be an NBT list")
    tile_entity_issues: list[dict[str, Any]] = []
    tile_entity_positions: Counter[tuple[int, int, int]] = Counter()
    for index, entity in enumerate(tile_entities):
        if not isinstance(entity, dict):
            tile_entity_issues.append({"index": index, "issue": "not_compound"})
            continue
        coords = (entity.get("x"), entity.get("y"), entity.get("z"))
        if not all(isinstance(value, int) for value in coords):
            tile_entity_issues.append({"index": index, "issue": "missing_integer_coordinates"})
            continue
        x, y, z = (int(value) for value in coords)
        tile_entity_positions[(x, y, z)] += 1
        if not (0 <= x < width and 0 <= y < height and 0 <= z < length):
            tile_entity_issues.append(
                {"index": index, "issue": "out_of_bounds", "position": [x, y, z]}
            )
    for position, count in tile_entity_positions.items():
        if count > 1:
            tile_entity_issues.append(
                {"issue": "duplicate_position", "position": list(position), "count": count}
            )

    named_counts = {
        name: counts.get(block_id, 0)
        for block_id, name in LEGACY_COMPONENT_IDS.items()
        if counts.get(block_id, 0)
    }
    block_id_counts = {str(block_id): count for block_id, count in sorted(counts.items())}
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    alignment = scan_chunk_offsets(dispenser_coordinates, chunk_limit)
    materials = root.get("Materials")
    return {
        "schema_version": 1,
        "status": "PASS" if alignment["status"] == "PASS" else "STATIC_FAIL",
        "classification": "LEGACY_STATIC_AUDIT_ONLY",
        "path": str(path),
        "sha256": sha256,
        "format": "mcedit-legacy-schematic",
        "root_name": root_name,
        "materials": materials if isinstance(materials, str) else None,
        "dimensions": {"width": width, "height": height, "length": length},
        "volume": volume,
        "compressed_bytes": path.stat().st_size,
        "decompressed_bytes": decompressed_bytes,
        "block_id_counts": block_id_counts,
        "component_counts": named_counts,
        "dispenser_count": len(dispenser_coordinates),
        "tile_entity_count": len(tile_entities),
        "tile_entity_issues": tile_entity_issues,
        "ec_chunk_alignment": alignment,
        "truth_boundary": {
            "legacy_numeric_ids_are_not_modern_block_states": True,
            "static_geometry_proves_runtime_function": False,
            "automatic_modern_conversion_performed": False,
            "private_extremecraft_parity_confirmed": False,
            "ec_ready": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Parse and statically audit a legacy MCEdit/Schematica .schematic without "
            "pretending numeric block IDs are modern block states"
        )
    )
    parser.add_argument("schematic", type=Path)
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--fail-on-limit", action="store_true")
    args = parser.parse_args()

    try:
        if args.chunk_limit <= 0:
            raise LegacySchematicError("chunk limit must be positive")
        report = audit_legacy_schematic(args.schematic, args.chunk_limit)
    except (OSError, UnicodeDecodeError, struct.error, LegacySchematicError) as exc:
        report = {
            "schema_version": 1,
            "status": "ERROR",
            "error": str(exc),
            "truth_boundary": {
                "private_extremecraft_parity_confirmed": False,
                "ec_ready": False,
            },
        }
    if args.json_out:
        write_json(args.json_out, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    if report.get("status") == "ERROR":
        return 2
    if args.fail_on_limit and report.get("status") == "STATIC_FAIL":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
