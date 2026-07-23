#!/usr/bin/env python3
from __future__ import annotations

import gzip
import importlib.util
import struct
import tempfile
import zlib
from pathlib import Path
from typing import Any


def load_subject() -> Any:
    script = Path(__file__).resolve().with_name("schem-audit.py")
    spec = importlib.util.spec_from_file_location("cannonlab_schem_recovery_test", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def raw_gzip(
    decoded: bytes,
    *,
    trailer_crc: int | None = None,
    trailer_size: int | None = None,
) -> bytes:
    compressor = zlib.compressobj(level=9, wbits=-zlib.MAX_WBITS)
    deflate = compressor.compress(decoded) + compressor.flush()
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
    crc = zlib.crc32(decoded) & 0xFFFFFFFF if trailer_crc is None else trailer_crc & 0xFFFFFFFF
    size = len(decoded) & 0xFFFFFFFF if trailer_size is None else trailer_size & 0xFFFFFFFF
    return header + deflate + struct.pack("<II", crc, size)


def expect_nbt_error(subject: Any, path: Path) -> None:
    try:
        subject.load(path)
    except subject.NBTError:
        return
    raise AssertionError(f"corrupt container unexpectedly loaded: {path}")


def main() -> int:
    subject = load_subject()
    with tempfile.TemporaryDirectory(prefix="cannonlab-schem-recovery-") as temporary:
        root = Path(temporary)
        valid_path = root / "valid.schem"
        model = {
            "blocks": {
                (0, 0, 0): "minecraft:stone",
                (1, 0, 0): "minecraft:dispenser[facing=north,triggered=false]",
            },
            "block_entities": [
                {"pos": (1, 0, 0), "id": "minecraft:dispenser", "raw": {}},
            ],
            "source_dimensions": {"width": 2, "height": 1, "length": 1},
        }
        subject.write_sponge_v2(valid_path, model, 3465)

        root_name, root_nbt, trailing, decoded_size, diagnostics = subject.load(valid_path)
        assert root_name == "Schematic"
        assert trailing == b""
        assert diagnostics["strict_gzip_valid"] is True
        assert diagnostics["appended_terminal_end_tags"] == 0
        decoded = gzip.decompress(valid_path.read_bytes())
        assert decoded_size == len(decoded)
        assert decoded.endswith(b"\x00\x00"), decoded[-8:]

        truncated = decoded[:-2]
        recoverable_path = root / "recoverable-two-end-tags.schem"
        recoverable_path.write_bytes(raw_gzip(
            truncated,
            trailer_crc=(zlib.crc32(decoded) ^ 0xFFFFFFFF),
            trailer_size=len(decoded),
        ))
        recovered_name, recovered_root, recovered_trailing, recovered_size, recovered = subject.load(recoverable_path)
        assert recovered_name == root_name
        assert recovered_root == root_nbt
        assert recovered_trailing == b""
        assert recovered_size == len(decoded)
        assert recovered["compression"] == "gzip-recovered-terminal-end-tags"
        assert recovered["strict_gzip_valid"] is False
        assert recovered["raw_deflate_valid"] is True
        assert recovered["appended_terminal_end_tags"] == 2
        assert recovered["repair_scope"] == "terminal TAG_End bytes only"

        wrong_size_path = root / "wrong-isize.schem"
        wrong_size_path.write_bytes(raw_gzip(
            truncated,
            trailer_crc=0,
            trailer_size=len(decoded) + 5,
        ))
        expect_nbt_error(subject, wrong_size_path)

        crc_only_path = root / "crc-only-corruption.schem"
        crc_only_path.write_bytes(raw_gzip(
            decoded,
            trailer_crc=(zlib.crc32(decoded) ^ 0xA5A5A5A5),
            trailer_size=len(decoded),
        ))
        expect_nbt_error(subject, crc_only_path)

        broken_deflate = bytearray(recoverable_path.read_bytes())
        start, end = subject.gzip_deflate_bounds(bytes(broken_deflate))
        for index in range(start, min(end, start + 6)):
            broken_deflate[index] ^= 0xFF
        broken_deflate_path = root / "broken-deflate.schem"
        broken_deflate_path.write_bytes(bytes(broken_deflate))
        expect_nbt_error(subject, broken_deflate_path)

    print(
        "Schematic recovery accepts only the unique terminal TAG_End repair and rejects wrong ISIZE, CRC-only, and broken-deflate corruption."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
