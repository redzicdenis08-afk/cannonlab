#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path
from typing import Any


def load_script(name: str, filename: str) -> Any:
    script = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_fixture(audit: Any, path: Path, *, extra_block: bool) -> None:
    blocks = {
        (0, 0, 0): "minecraft:stone",
        (1, 0, 0): "minecraft:dispenser[facing=north,triggered=false]",
    }
    if extra_block:
        blocks[(2, 0, 0)] = "minecraft:repeater[facing=north,delay=1,locked=false,powered=false]"
    audit.write_sponge_v2(
        path,
        {
            "blocks": blocks,
            "block_entities": [
                {"pos": (1, 0, 0), "id": "minecraft:dispenser", "raw": {}},
            ],
            "source_dimensions": {
                "width": 3 if extra_block else 2,
                "height": 1,
                "length": 1,
            },
        },
        3465,
    )


def main() -> int:
    audit = load_script("cannonlab_cache_test_audit", "schem-audit.py")
    module_map = load_script("cannonlab_cache_test_module_map", "cannon-module-map.py")
    preservation = load_script(
        "cannonlab_cache_test_preservation",
        "cannon-preservation-check.py",
    )

    with tempfile.TemporaryDirectory(prefix="cannonlab-static-cache-") as temporary:
        root = Path(temporary)
        schematic = root / "fixture.schem"
        write_fixture(audit, schematic, extra_block=False)

        first = module_map.build_report(schematic)
        first_sha = first["file_sha256"]
        first["status"] = "MUTATED_BY_CALLER"
        first["modules"].clear()
        second = module_map.build_report(schematic)
        assert second["status"] == "PASS", second
        assert second["modules"], second
        assert second["file_sha256"] == first_sha
        assert len(module_map._REPORT_CACHE) == 1

        loaded_one = preservation.load_model(
            preservation.load_script("cache_audit", "schem-audit.py"),
            schematic,
        )
        loaded_one["blocks"].clear()
        loaded_two = preservation.load_model(
            preservation.load_script("cache_audit", "schem-audit.py"),
            schematic,
        )
        assert loaded_two["blocks"], loaded_two
        assert len(preservation._MODEL_CACHE) == 1

        write_fixture(audit, schematic, extra_block=True)
        stat = schematic.stat()
        os.utime(schematic, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

        third = module_map.build_report(schematic)
        assert third["file_sha256"] != first_sha, third
        assert third["architecture_summary"]["functional_components"] > second[
            "architecture_summary"
        ]["functional_components"]
        assert len(module_map._REPORT_CACHE) == 2

        loaded_three = preservation.load_model(
            preservation.load_script("cache_audit", "schem-audit.py"),
            schematic,
        )
        assert len(loaded_three["blocks"]) > len(loaded_two["blocks"])
        assert len(preservation._MODEL_CACHE) == 2

    print(
        "Static analysis caches return isolated copies and invalidate on schematic size or mtime changes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
