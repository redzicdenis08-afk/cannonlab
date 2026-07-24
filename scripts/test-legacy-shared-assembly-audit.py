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


assembly = load("legacy_shared_assembly_audit_test", "legacy-shared-assembly-audit.py")


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
    dimensions: tuple[int, int, int],
    values: dict[tuple[int, int, int], tuple[int, int]],
) -> None:
    width, height, length = dimensions
    volume = width * height * length
    block_ids = [0] * volume
    metadata = [0] * volume
    for (x, y, z), (block_id, data) in values.items():
        index = x + z * width + y * width * length
        block_ids[index] = block_id
        metadata[index] = data
    low = bytes(value & 0xFF for value in block_ids)
    high = bytearray((volume + 1) // 2)
    for index, value in enumerate(block_ids):
        nibble = (value >> 8) & 0x0F
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
        tag_byte_array("Data", bytes(metadata)),
    ]
    if any(high):
        tags.append(tag_byte_array("AddBlocks", bytes(high)))
    tags.extend([tag_empty_compound_list("TileEntities"), tag_empty_compound_list("Entities")])
    root = b"\x0a" + nbt_name("Schematic") + b"".join(tags) + b"\x00"
    path.write_bytes(gzip.compress(root, mtime=0))


def run(first, second, dimensions, *, minimum=1, max_support=1000):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        first_path = root / "first.schematic"
        second_path = root / "second.schematic"
        write_legacy(first_path, dimensions, first)
        write_legacy(second_path, dimensions, second)
        return assembly.build_report(
            "first",
            first_path,
            "second",
            second_path,
            turns=0,
            translation=(0, 0, 0),
            minimum_functional_count=minimum,
            chunk_limit=160,
            max_shared_support_nodes=max_support,
        )


def test_support_bridges_functional_islands() -> None:
    blocks = {
        (0, 0, 0): (23, 5),
        (1, 0, 0): (49, 0),
        (2, 0, 0): (49, 0),
        (3, 0, 0): (55, 0),
    }
    report = run(blocks, blocks, (4, 1, 1))
    assert report["summary"]["reported_assembly_count"] == 1, report
    row = report["assemblies"][0]
    assert row["functional_count"] == 2, row
    assert row["support_count"] == 2, row
    assert row["face_connected_functional_island_count"] == 2, row
    assert row["status"] == "FACE_CLOSED_SHARED_ASSEMBLY", row
    assert row["promotion_eligible"] is False, row


def test_shared_functional_continuation_is_included() -> None:
    blocks = {
        (0, 0, 0): (23, 5),
        (1, 0, 0): (55, 0),
        (2, 0, 0): (93, 1),
    }
    report = run(blocks, blocks, (3, 1, 1))
    row = report["assemblies"][0]
    assert row["functional_count"] == 3, row
    assert row["support_count"] == 0, row
    assert row["status"] == "FACE_CLOSED_SHARED_ASSEMBLY", row


def test_one_sided_dependency_keeps_assembly_open() -> None:
    first = {
        (0, 0, 0): (23, 5),
        (1, 0, 0): (55, 0),
        (2, 0, 0): (49, 0),
    }
    second = {
        (0, 0, 0): (23, 5),
        (1, 0, 0): (55, 0),
    }
    report = run(first, second, (3, 1, 1))
    row = report["assemblies"][0]
    assert row["status"] == "OPEN_SHARED_ASSEMBLY", row
    assert row["residual_boundary_edge_counts"]["first_only_nonair"] == 1, row


def test_support_only_component_is_not_reported() -> None:
    blocks = {
        (0, 0, 0): (49, 0),
        (1, 0, 0): (49, 0),
        (3, 0, 0): (23, 5),
    }
    report = run(blocks, blocks, (4, 1, 1))
    assert report["summary"]["reported_assembly_count"] == 1, report
    assert report["assemblies"][0]["functional_count"] == 1, report
    assert report["assemblies"][0]["support_count"] == 0, report


def test_wrong_repeater_delay_is_residual_conflict() -> None:
    first = {(0, 0, 0): (23, 5), (1, 0, 0): (93, 1)}
    second = {(0, 0, 0): (23, 5), (1, 0, 0): (93, 5)}
    report = run(first, second, (2, 1, 1))
    row = report["assemblies"][0]
    assert row["functional_count"] == 1, row
    assert row["status"] == "OPEN_SHARED_ASSEMBLY", row
    assert row["residual_boundary_edge_counts"]["shared_conflicting_functional"] == 1, row


def test_support_cap_fails_closed() -> None:
    blocks = {(0, 0, 0): (23, 5), (1, 0, 0): (49, 0), (2, 0, 0): (49, 0)}
    try:
        run(blocks, blocks, (3, 1, 1), max_support=1)
    except assembly.AssemblyError as exc:
        assert "exceeds cap" in str(exc), exc
    else:
        raise AssertionError("support cap must fail closed")


def main() -> int:
    tests = [
        test_support_bridges_functional_islands,
        test_shared_functional_continuation_is_included,
        test_one_sided_dependency_keeps_assembly_open,
        test_support_only_component_is_not_reported,
        test_wrong_repeater_delay_is_residual_conflict,
        test_support_cap_fails_closed,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} shared assembly regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
