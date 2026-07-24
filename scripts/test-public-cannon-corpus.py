#!/usr/bin/env python3
from __future__ import annotations

import gzip
import importlib.util
import io
import json
import struct
import sys
import tempfile
from pathlib import Path


def load_module(filename: str, name: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


legacy = load_module("legacy-schematic-audit.py", "legacy_schematic_audit")
corpus = load_module("fetch-public-cannon-corpus.py", "fetch_public_cannon_corpus")


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


def tag_list_of_compounds(name: str, compounds: list[bytes]) -> bytes:
    return (
        b"\x09"
        + nbt_name(name)
        + b"\x0a"
        + struct.pack(">i", len(compounds))
        + b"".join(compounds)
    )


def compound_payload(tags: list[bytes]) -> bytes:
    return b"".join(tags) + b"\x00"


def tag_int(name: str, value: int) -> bytes:
    return b"\x03" + nbt_name(name) + struct.pack(">i", value)


def write_legacy(
    path: Path,
    *,
    width: int,
    height: int,
    length: int,
    block_ids: list[int],
    tile_entities: list[tuple[int, int, int]] | None = None,
) -> None:
    volume = width * height * length
    assert len(block_ids) == volume
    low = bytes(block_id & 0xFF for block_id in block_ids)
    high_nibbles = [block_id >> 8 for block_id in block_ids]
    add = bytearray((volume + 1) // 2)
    for index, high in enumerate(high_nibbles):
        if index % 2 == 0:
            add[index // 2] |= high & 0x0F
        else:
            add[index // 2] |= (high & 0x0F) << 4
    tags = [
        tag_short("Width", width),
        tag_short("Height", height),
        tag_short("Length", length),
        tag_string("Materials", "Alpha"),
        tag_byte_array("Blocks", low),
        tag_byte_array("Data", bytes(volume)),
    ]
    if any(add):
        tags.append(tag_byte_array("AddBlocks", bytes(add)))
    compounds = []
    for x, y, z in tile_entities or []:
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


class FakeHeaders(dict):
    def get(self, key: str, default=None):
        return super().get(key, default)


class FakeResponse:
    def __init__(self, data: bytes, headers: dict[str, str] | None = None):
        self._stream = io.BytesIO(data)
        self.headers = FakeHeaders(headers or {})

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def test_legacy_parse_and_alignment() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "tiny.schematic"
        blocks = [0] * 8
        blocks[0] = 23
        blocks[1] = 218
        write_legacy(
            path,
            width=2,
            height=2,
            length=2,
            block_ids=blocks,
            tile_entities=[(0, 0, 0)],
        )
        report = legacy.audit_legacy_schematic(path, 160)
        assert report["status"] == "PASS", report
        assert report["format"] == "mcedit-legacy-schematic", report
        assert report["dispenser_count"] == 1, report
        assert report["component_counts"]["observer"] == 1, report
        assert report["tile_entity_count"] == 1, report
        assert report["ec_chunk_alignment"]["all_offsets_scanned"] == 256, report
        assert report["ec_chunk_alignment"]["legal_offset_count"] == 256, report
        assert report["truth_boundary"]["ec_ready"] is False, report


def test_legacy_ec160_failure() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "stacked.schematic"
        write_legacy(
            path,
            width=1,
            height=161,
            length=1,
            block_ids=[23] * 161,
        )
        report = legacy.audit_legacy_schematic(path, 160)
        assert report["status"] == "STATIC_FAIL", report
        assert report["dispenser_count"] == 161, report
        assert report["ec_chunk_alignment"]["legal_offset_count"] == 0, report
        assert report["ec_chunk_alignment"]["best_max_dispensers_per_chunk"] == 161, report


def test_addblocks_round_trip() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "high-id.schematic"
        write_legacy(path, width=1, height=1, length=2, block_ids=[23, 300])
        report = legacy.audit_legacy_schematic(path, 160)
        assert report["block_id_counts"]["300"] == 1, report


def test_manifest_validation_and_plan() -> None:
    manifest = {
        "schema_version": 1,
        "id": "test-corpus",
        "policy": {
            "allowed_hosts": ["example.com", "cdn.example.com"],
            "max_bytes_per_file": 4096,
            "repository_storage": "fetch-only",
            "chunk_limit": 160,
        },
        "sources": [
            {
                "id": "probe",
                "source_page": "https://example.com/schematics",
                "download_url": "https://cdn.example.com/probe.schematic",
                "filename": "probe.schematic",
                "authors": ["Builder"],
                "claimed_capabilities": ["osrb"],
                "target_environment": {"jar": "unknown"},
                "redistribution": "fetch-only",
                "license_status": "not-stated",
                "expected_sha256": None,
            }
        ],
    }
    normalized = corpus.validate_manifest(manifest)
    assert normalized["id"] == "test-corpus", normalized
    assert normalized["policy"]["allowed_hosts"] == ["cdn.example.com", "example.com"], normalized
    with tempfile.TemporaryDirectory() as temporary:
        temporary_path = Path(temporary)
        manifest_path = temporary_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        report = corpus.run_corpus(
            manifest_path,
            temporary_path / "out",
            repo_root=temporary_path,
            mode="plan",
            lock_path=None,
            write_lock_path=None,
            accept_new_hashes=False,
            skip_audit=True,
        )
        assert report["status"] == "PLAN", report
        assert report["sources"][0]["status"] == "PLANNED", report
        assert report["truth_boundary"]["ec_ready"] is False, report


def test_manifest_rejects_insecure_and_duplicate_sources() -> None:
    base_source = {
        "id": "probe",
        "source_page": "https://example.com/page",
        "download_url": "https://example.com/probe.schem",
        "filename": "probe.schem",
        "authors": ["Builder"],
        "claimed_capabilities": [],
        "redistribution": "fetch-only",
        "license_status": "not-stated",
        "expected_sha256": None,
    }
    manifest = {
        "schema_version": 1,
        "id": "bad",
        "policy": {
            "allowed_hosts": ["example.com"],
            "repository_storage": "fetch-only",
        },
        "sources": [base_source, dict(base_source)],
    }
    try:
        corpus.validate_manifest(manifest)
    except corpus.CorpusError as exc:
        assert "duplicate source id" in str(exc)
    else:
        raise AssertionError("duplicate source IDs should fail")

    insecure = json.loads(json.dumps(manifest))
    insecure["sources"] = [dict(base_source)]
    insecure["sources"][0]["download_url"] = "http://example.com/probe.schem"
    try:
        corpus.validate_manifest(insecure)
    except corpus.CorpusError as exc:
        assert "must use https" in str(exc)
    else:
        raise AssertionError("HTTP source should fail")


def test_stream_limits_and_html_rejection() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        destination = Path(temporary) / "file.schematic"
        response = FakeResponse(b"binary-schematic", {"Content-Type": "application/octet-stream"})
        result = corpus.stream_response_to_file(response, destination, 1024)
        assert result["bytes"] == len(b"binary-schematic"), result
        assert destination.read_bytes() == b"binary-schematic"

        html = FakeResponse(b"<!doctype html><title>nope</title>", {"Content-Type": "text/html"})
        try:
            corpus.stream_response_to_file(html, destination, 1024)
        except corpus.CorpusError as exc:
            assert "HTML" in str(exc)
        else:
            raise AssertionError("HTML response should fail")

        oversized = FakeResponse(b"x" * 20, {"Content-Length": "20"})
        try:
            corpus.stream_response_to_file(oversized, destination, 10)
        except corpus.CorpusError as exc:
            assert "exceeds limit" in str(exc)
        else:
            raise AssertionError("oversized response should fail")


def test_hash_pin_contract() -> None:
    source = {"id": "probe"}
    observed = "a" * 64
    assert corpus.verify_or_record_hash(source, observed, None, True) == "NEW_HASH_ACCEPTED"
    try:
        corpus.verify_or_record_hash(source, observed, None, False)
    except corpus.CorpusError as exc:
        assert "unpinned" in str(exc)
    else:
        raise AssertionError("unpinned fetch should fail without explicit acceptance")
    try:
        corpus.verify_or_record_hash(source, observed, "b" * 64, True)
    except corpus.CorpusError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("hash mismatch should fail")


def main() -> int:
    tests = [
        test_legacy_parse_and_alignment,
        test_legacy_ec160_failure,
        test_addblocks_round_trip,
        test_manifest_validation_and_plan,
        test_manifest_rejects_insecure_and_duplicate_sources,
        test_stream_limits_and_html_rejection,
        test_hash_pin_contract,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} public corpus regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
