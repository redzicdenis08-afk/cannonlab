#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
auditor = root / "scripts/schem-audit.py"
text = auditor.read_text(encoding="utf-8")
old = '''            pos = tuple(int(entity[axis]) for axis in ("x", "y", "z"))
            state = blocks.get(pos, "minecraft:air")
'''
new = '''            local = tuple(int(entity[axis]) for axis in ("x", "y", "z"))
            pos = tuple(region_min[index] + local[index] for index in range(3))
            state = blocks.get(pos, "minecraft:air")
'''
if text.count(old) != 1:
    raise SystemExit(f"expected one block-entity coordinate anchor, found {text.count(old)}")
auditor.write_text(text.replace(old, new, 1), encoding="utf-8")

negative_test = root / "scripts/test-negative-litematic.py"
test = negative_test.read_text(encoding="utf-8")
nt_old = '''            "BlockStates": [36],
            "TileEntities": [],
'''
nt_new = '''            "BlockStates": [36],
            "TileEntities": [{"id": "minecraft:dispenser", "x": 0, "y": 0, "z": 0, "Items": []}],
'''
if test.count(nt_old) != 1:
    raise SystemExit(f"expected one regression fixture anchor, found {test.count(nt_old)}")
test = test.replace(nt_old, nt_new, 1)
old_assert = '''assert model["offset"] == [0, 0, 0], model["offset"]
print("negative-region Litematica coordinate order PASS")
'''
new_assert = '''assert model["offset"] == [0, 0, 0], model["offset"]
assert model["block_entities"][0]["pos"] == (0, 0, 0), model["block_entities"]
print("negative-region Litematica coordinate and block-entity order PASS")
'''
if test.count(old_assert) != 1:
    raise SystemExit(f"expected one regression assertion anchor, found {test.count(old_assert)}")
negative_test.write_text(test.replace(old_assert, new_assert, 1), encoding="utf-8")
print("Litematica region-local block entities fixed.")
