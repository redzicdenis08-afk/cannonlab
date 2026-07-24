#!/usr/bin/env python3
from __future__ import annotations

import gzip
import importlib.util
import struct
import sys
import tempfile
from pathlib import Path


def load(name: str, filename: str):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


shared = load("legacy_shared_core_audit", "legacy-shared-core-audit.py")
architecture = load("legacy_shared_core_architecture_test", "legacy-cannon-architecture.py")


def nbt_name(name: str) -> bytes:
    encoded = name.encode("utf-8")
    return struct.pack(">H", len(encoded)) + encoded


def tag_short(name: str, value: int) -> bytes:
    return b"\x02" + nbt_name(name) + struct.pack(">h", value)


def tag_string(name: str, value: str) -> bytes:
    encoded = value.encode("utf-8")
    return b"\x08" + nbt_name(name) + struct.pack(">H", len(encoded)) + encoded


def tag_byte_array(name: str, value: bytes) -> bytes:
    return b"\x07" + nbt_name(name) + struct.pack(">i", len(value)) + value


def tag_empty_compound_list(name: str) -> bytes:
    return b"\x09" + nbt_name(name) + b"\x0a" + struct.pack(">i", 0)


def write_legacy(
    path: Path,
    *,
    width: int,
    height: int,
    length: int,
    blocks_by_position: dict[tuple[int, int, int], tuple[int, int]],
) -> None:
    volume = width * height * length
    block_ids = [0] * volume
    data = [0] * volume
    for (x, y, z), (block_id, metadata) in blocks_by_position.items():
        assert 0 <= x < width and 0 <= y < height and 0 <= z < length
        index = x + z * width + y * width * length
        block_ids[index] = block_id
        data[index] = metadata
    low = bytes(block_id & 0xFF for block_id in block_ids)
    high = bytearray((volume + 1) // 2)
    for index, block_id in enumerate(block_ids):
        nibble = (block_id >> 8) & 0x0F
        if index % 2 == 0:
            high[index // 2] |= nibble
        else:
            high[index // 2] |= nibble << 4
    tags = [
        tag_short("Width", width),
        tag_short("Height", height),
        tag_short("Length", length),
        tag_string("Materials", "Alpha"),
        tag_byte_array("Blocks", low),
        tag_byte_array("Data", bytes(data)),
    ]
    if any(high):
        tags.append(tag_byte_array("AddBlocks", bytes(high)))
    tags.extend([tag_empty_compound_list("TileEntities"), tag_empty_compound_list("Entities")])
    root = b"\x0a" + nbt_name("Schematic") + b"".join(tags) + b"\x00"
    path.write_bytes(gzip.compress(root, mtime=0))


def build_pair(
    first_blocks: dict[tuple[int, int, int], tuple[int, int]],
    second_blocks: dict[tuple[int, int, int], tuple[int, int]],
    *,
    first_dimensions: tuple[int, int, int],
    second_dimensions: tuple[int, int, int],
    turns: int = 0,
    translation: tuple[int, int, int] = (0, 0, 0),
    minimum_component_size: int = 1,
):
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    first = root / "first.schematic"
    second = root / "second.schematic"
    write_legacy(
        first,
        width=first_dimensions[0],
        height=first_dimensions[1],
        length=first_dimensions[2],
        blocks_by_position=first_blocks,
    )
    write_legacy(
        second,
        width=second_dimensions[0],
        height=second_dimensions[1],
        length=second_dimensions[2],
        blocks_by_position=second_blocks,
    )
    report = shared.build_report(
        "first",
        first,
        "second",
        second,
        turns=turns,
        translation_delta=translation,
        chunk_limit=160,
        minimum_component_size=minimum_component_size,
    )
    temporary.cleanup()
    return report


def test_metadata_equivalence_contract() -> None:
    assert shared.compare_block(architecture, (23, 5), (23, 2), 1) == "proven_equivalent"
    assert shared.compare_block(architecture, (218, 5), (218, 10), 1) == "proven_equivalent"
    assert shared.compare_block(architecture, (94, 9), (93, 8), 1) == "proven_equivalent"
    assert shared.compare_block(architecture, (93, 5), (93, 8), 1) == "metadata_conflict"
    assert shared.compare_block(architecture, (69, 1), (69, 1), 1) == "same_kind_unresolved_metadata"
    assert shared.compare_block(architecture, (55, 15), (55, 0), 0) == "proven_equivalent"


def test_rotated_translated_shared_region() -> None:
    first = {
        (0, 0, 0): (23, 5),
        (1, 0, 0): (93, 1),
        (2, 0, 0): (55, 0),
    }
    second = {
        (0, 0, 0): (55, 14),
        (0, 0, 1): (94, 0),
        (0, 0, 2): (23, 2),
    }
    report = build_pair(
        first,
        second,
        first_dimensions=(3, 1, 1),
        second_dimensions=(1, 1, 3),
        turns=1,
        translation=(2, 0, 0),
    )
    assert report["overlap"]["same_kind_position_count"] == 3, report
    assert report["overlap"]["proven_metadata_equivalent_position_count"] == 3, report
    assert report["summary"]["closed_component_candidate_count"] == 1, report
    assert report["components"][0]["component_count"] == 3, report
    assert report["components"][0]["promotion_eligible"] is False, report


def test_boundary_blocks_prevent_false_closed_component() -> None:
    blocks = {
        (0, 0, 0): (23, 5),
        (1, 0, 0): (93, 1),
        (2, 0, 0): (55, 0),
        (3, 0, 0): (1, 0),
    }
    report = build_pair(
        blocks,
        blocks,
        first_dimensions=(4, 1, 1),
        second_dimensions=(4, 1, 1),
    )
    component = report["components"][0]
    assert component["status"] == "OPEN_SHARED_REGION", report
    assert component["boundary"]["combined_unique_face_crossing_count"] == 1, report
    assert report["summary"]["promotion_eligible_component_count"] == 0, report


def test_wrong_delay_breaks_proven_component() -> None:
    first = {(0, 0, 0): (23, 5), (1, 0, 0): (93, 1), (2, 0, 0): (55, 0)}
    second = {(0, 0, 0): (23, 5), (1, 0, 0): (93, 5), (2, 0, 0): (55, 0)}
    report = build_pair(
        first,
        second,
        first_dimensions=(3, 1, 1),
        second_dimensions=(3, 1, 1),
        minimum_component_size=2,
    )
    assert report["overlap"]["classification_counts"]["metadata_conflict"] == 1, report
    assert report["overlap"]["proven_metadata_equivalent_position_count"] == 2, report
    assert report["summary"]["reported_component_count"] == 0, report


def test_component_ec160_scan() -> None:
    blocks = {(0, y, 0): (23, 2) for y in range(161)}
    report = build_pair(
        blocks,
        blocks,
        first_dimensions=(1, 161, 1),
        second_dimensions=(1, 161, 1),
    )
    component = report["components"][0]
    assert component["component_count"] == 161, report
    assert component["ec160"]["best_max_dispensers_per_chunk"] == 161, report
    assert component["ec160"]["legal_offset_count"] == 0, report


def main() -> int:
    tests = [
        test_metadata_equivalence_contract,
        test_rotated_translated_shared_region,
        test_boundary_blocks_prevent_false_closed_component,
        test_wrong_delay_breaks_proven_component,
        test_component_ec160_scan,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} shared-core regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
