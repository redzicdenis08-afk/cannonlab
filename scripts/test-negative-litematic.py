#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("schem_audit", ROOT / "scripts/schem-audit.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = {
    "Version": 7,
    "MinecraftDataVersion": 3839,
    "Regions": {
        "negative-x": {
            "Position": {"x": 2, "y": 0, "z": 0},
            "Size": {"x": -3, "y": 1, "z": 1},
            "BlockStatePalette": [
                {"Name": "minecraft:stone"},
                {"Name": "minecraft:redstone_wire"},
                {"Name": "minecraft:glass"},
            ],
            "BlockStates": [36],
            "TileEntities": [],
        }
    },
}
model = module.decode_litematic(root)
assert model["source_dimensions"] == {"width": 3, "height": 1, "length": 1}, model
assert model["blocks"][(0, 0, 0)] == "minecraft:stone", model["blocks"]
assert model["blocks"][(1, 0, 0)] == "minecraft:redstone_wire", model["blocks"]
assert model["blocks"][(2, 0, 0)] == "minecraft:glass", model["blocks"]
assert model["offset"] == [0, 0, 0], model["offset"]
print("negative-region Litematica coordinate order PASS")
