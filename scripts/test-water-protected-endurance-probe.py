#!/usr/bin/env python3
from __future__ import annotations

import base64
import importlib.util
import tempfile
from pathlib import Path
from typing import Any


SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent


def load_script(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_script(
        "water_protected_endurance_builder",
        SCRIPTS / "build-water-protected-endurance-probe.py",
    )
    audit = load_script("water_protected_endurance_audit", SCRIPTS / "schem-audit.py")
    committed = ROOT / "cannons" / "probe-water-protected-dispenser.schem.b64"
    expected_bytes = base64.b64decode(committed.read_text(encoding="ascii"))

    with tempfile.TemporaryDirectory() as temp:
        generated = Path(temp) / "probe.schem"
        audit.write_sponge_v2(generated, builder.build_model(), 3465)
        actual_bytes = generated.read_bytes()
        assert actual_bytes == expected_bytes, (
            "committed endurance probe does not match deterministic generator"
        )
        root_name, root, trailing, _size, diagnostics = audit.load(generated)
        model = audit.decode_any(root_name, root)

    assert trailing == b"", trailing
    assert diagnostics["strict_gzip_valid"] is True, diagnostics
    assert model["format"] == "sponge-v2", model
    assert model["data_version"] == 3465, model
    dispensers = [
        point
        for point, state in model["blocks"].items()
        if audit.base(state) == "minecraft:dispenser"
    ]
    assert dispensers == [(1, 1, 1)], dispensers
    assert model["blocks"][(2, 1, 1)] == "minecraft:water[level=0]", model
    assert sum(
        audit.base(state) == "minecraft:obsidian"
        for state in model["blocks"].values()
    ) == 7, model

    print(
        "Water-protected endurance fixture is deterministic Sponge v2/DataVersion 3465 "
        "with one dispenser, one source-water cell, and seven chamber blocks."
    )


if __name__ == "__main__":
    main()
