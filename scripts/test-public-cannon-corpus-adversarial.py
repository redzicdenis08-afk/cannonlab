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


legacy = load("legacy_schematic_audit_adversarial", "legacy-schematic-audit.py")
strict_fetch = load(
    "strict_fetch_public_cannon_corpus_tests",
    "strict-fetch-public-cannon-corpus.py",
)


def nbt_name(name: str) -> bytes:
    encoded = name.encode("utf-8")
    return struct.pack(">H", len(encoded)) + encoded


def tag_short(name: str, value: int) -> bytes:
    return b"\x02" + nbt_name(name) + struct.pack(">h", value)


def tag_int(name: str, value: int) -> bytes:
    return b"\x03" + nbt_name(name) + struct.pack(">i", value)


def tag_string(name: str, value: str) -> bytes:
    encoded = value.encode("utf-8")
    return b"\x08" + nbt_name(name) + struct.pack(">H", len(encoded)) + encoded


def tag_byte_array(name: str, value: bytes) -> bytes:
    return b"\x07" + nbt_name(name) + struct.pack(">i", len(value)) + value


def compound_payload(tags: list[bytes]) -> bytes:
    return b"".join(tags) + b"\x00"


def tag_list_of_compounds(name: str, compounds: list[bytes]) -> bytes:
    return (
        b"\x09"
        + nbt_name(name)
        + b"\x0a"
        + struct.pack(">i", len(compounds))
        + b"".join(compounds)
    )


def write_fixture(
    path: Path,
    *,
    block_id: int,
    add_blocks: bytes | None = None,
    tile_entity: tuple[int, int, int] | None = None,
) -> None:
    tags = [
        tag_short("Width", 1),
        tag_short("Height", 1),
        tag_short("Length", 1),
        tag_string("Materials", "Alpha"),
        tag_byte_array("Blocks", bytes([block_id & 0xFF])),
        tag_byte_array("Data", b"\x00"),
    ]
    if add_blocks is not None:
        tags.append(tag_byte_array("AddBlocks", add_blocks))
    compounds: list[bytes] = []
    if tile_entity is not None:
        x, y, z = tile_entity
        compounds.append(
            compound_payload(
                [
                    tag_string("id", "Trap"),
                    tag_int("x", x),
                    tag_int("y", y),
                    tag_int("z", z),
                ]
            )
        )
    tags.append(tag_list_of_compounds("TileEntities", compounds))
    tags.append(tag_list_of_compounds("Entities", []))
    root = b"\x0a" + nbt_name("Schematic") + compound_payload(tags)
    path.write_bytes(gzip.compress(root, mtime=0))


def expect_legacy_error(payload: bytes, phrase: str) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "bad.schematic"
        path.write_bytes(payload)
        try:
            legacy.parse_root(path)
        except legacy.LegacySchematicError as exc:
            assert phrase in str(exc), exc
        else:
            raise AssertionError(f"expected LegacySchematicError containing {phrase!r}")


def test_nonempty_tag_end_list_is_rejected_before_allocation() -> None:
    payload = (
        b"\x0a"
        + nbt_name("Root")
        + b"\x09"
        + nbt_name("Bomb")
        + b"\x00"
        + struct.pack(">i", 1_000_000)
        + b"\x00"
    )
    expect_legacy_error(payload, "TAG_End list type")


def test_impossible_fixed_width_list_is_rejected_preflight() -> None:
    payload = (
        b"\x0a"
        + nbt_name("Root")
        + b"\x09"
        + nbt_name("Bomb")
        + b"\x03"
        + struct.pack(">i", 1_000_000)
        + b"\x00"
    )
    expect_legacy_error(payload, "cannot fit")


def test_addblocks_must_match_exact_volume() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "bad-add.schematic"
        write_fixture(path, block_id=23, add_blocks=b"\x00\x00")
        try:
            legacy.audit_legacy_schematic(path)
        except legacy.LegacySchematicError as exc:
            assert "AddBlocks length" in str(exc), exc
        else:
            raise AssertionError("oversized AddBlocks should fail")


def test_tile_entity_on_air_fails_integrity() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "air-tile.schematic"
        write_fixture(path, block_id=0, tile_entity=(0, 0, 0))
        report = legacy.audit_legacy_schematic(path)
        assert report["status"] == "STATIC_FAIL", report
        assert report["integrity_status"] == "FAIL", report
        assert any(
            row["issue"] == "tile_entity_on_air"
            for row in report["tile_entity_issues"]
        ), report


def completed_row(audit_status: str, returncode: int, report: str | None = "audit.json"):
    return {
        "id": "probe",
        "status": "FETCHED",
        "pin_status": "PINNED_HASH_VERIFIED",
        "audit": {
            "status": audit_status,
            "returncode": returncode,
            "report": report,
        },
    }


def fetch_report(row: dict) -> dict:
    return {
        "schema_version": 1,
        "status": "PASS",
        "summary": {"source_count": 1},
        "sources": [row],
        "truth_boundary": {"ec_ready": False},
    }


def test_strict_fetch_rejects_audit_error() -> None:
    report = strict_fetch.validate_fetch_report(
        fetch_report(completed_row("ERROR", 2)),
        mode="fetch",
        skip_audit=False,
    )
    assert report["status"] == "FAIL", report
    issues = {row["issue"] for row in report["strict_validation"]["failures"]}
    assert "audit_not_completed" in issues, report
    assert "audit_process_failed" in issues, report


def test_strict_fetch_accepts_static_limit_failure_as_completed_audit() -> None:
    report = strict_fetch.validate_fetch_report(
        fetch_report(completed_row("STATIC_FAIL", 0)),
        mode="fetch",
        skip_audit=False,
    )
    assert report["status"] == "PASS", report
    assert report["strict_validation"]["status"] == "PASS", report


def test_strict_fetch_rejects_missing_report_even_with_zero_exit() -> None:
    report = strict_fetch.validate_fetch_report(
        fetch_report(completed_row("PASS", 0, None)),
        mode="fetch",
        skip_audit=False,
    )
    assert report["status"] == "FAIL", report
    assert any(
        row["issue"] == "audit_report_missing"
        for row in report["strict_validation"]["failures"]
    ), report


def test_strict_plan_requires_every_source_planned() -> None:
    report = strict_fetch.validate_fetch_report(
        {
            "status": "PLAN",
            "summary": {"source_count": 1},
            "sources": [{"id": "probe", "status": "PLANNED"}],
            "truth_boundary": {"ec_ready": False},
        },
        mode="plan",
        skip_audit=False,
    )
    assert report["status"] == "PLAN", report
    assert report["strict_validation"]["status"] == "PASS", report


def main() -> int:
    tests = [
        test_nonempty_tag_end_list_is_rejected_before_allocation,
        test_impossible_fixed_width_list_is_rejected_preflight,
        test_addblocks_must_match_exact_volume,
        test_tile_entity_on_air_fails_integrity,
        test_strict_fetch_rejects_audit_error,
        test_strict_fetch_accepts_static_limit_failure_as_completed_audit,
        test_strict_fetch_rejects_missing_report_even_with_zero_exit,
        test_strict_plan_requires_every_source_planned,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} adversarial public corpus regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
