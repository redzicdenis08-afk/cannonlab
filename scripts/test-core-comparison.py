#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
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


def translated_blocks(
    blocks: dict[tuple[int, int, int], str],
    vector: tuple[int, int, int],
) -> dict[tuple[int, int, int], str]:
    return {
        tuple(point[axis] + vector[axis] for axis in range(3)): state
        for point, state in blocks.items()
    }


def write_model(
    audit: Any,
    path: Path,
    blocks: dict[tuple[int, int, int], str],
    dimensions: tuple[int, int, int],
) -> None:
    block_entities = [
        {"pos": point, "id": "minecraft:dispenser", "raw": {}}
        for point, state in blocks.items()
        if audit.base(state) == "minecraft:dispenser"
    ]
    audit.write_sponge_v2(
        path,
        {
            "blocks": blocks,
            "block_entities": block_entities,
            "source_dimensions": {
                "width": dimensions[0],
                "height": dimensions[1],
                "length": dimensions[2],
            },
        },
        3465,
    )


def main() -> int:
    audit = load_script("core_compare_test_audit", "schem-audit.py")
    compare = load_script("core_compare_test_subject", "compare-cannon-cores.py")
    core = {
        (0, 1, 1): "minecraft:stone_button[face=floor,facing=east,powered=false]",
        (1, 1, 1): "minecraft:redstone_wire[north=none,east=side,south=none,west=side,power=0]",
        (2, 1, 1): "minecraft:repeater[delay=2,facing=east,locked=false,powered=false]",
        (3, 1, 1): "minecraft:redstone_wire[north=none,east=side,south=none,west=side,power=0]",
        (4, 1, 1): "minecraft:observer[facing=east,powered=false]",
        (5, 1, 1): "minecraft:sticky_piston[extended=false,facing=east]",
        (6, 1, 1): "minecraft:slime_block",
        (7, 1, 1): "minecraft:dispenser[facing=east,triggered=false]",
        (8, 1, 1): "minecraft:water[level=0]",
        (7, 2, 1): "minecraft:sand",
    }
    for x in range(0, 9):
        core[(x, 0, 1)] = "minecraft:stone"

    with tempfile.TemporaryDirectory(prefix="cannonlab-core-compare-") as temporary:
        root = Path(temporary)
        first = root / "first.schem"
        second = root / "second.schem"
        bank_first = root / "bank-first.schem"
        bank_second = root / "bank-second.schem"
        write_model(audit, first, core, (10, 4, 4))

        vector = (4, 1, 2)
        expanded = translated_blocks(core, vector)
        for x in range(1, 13):
            expanded[(x, 1, 7)] = "minecraft:dispenser[facing=north,triggered=false]"
            expanded[(x, 0, 7)] = "minecraft:stone"
        expanded[(13, 1, 7)] = "minecraft:repeater[delay=4,facing=east,locked=false,powered=false]"
        write_model(audit, second, expanded, (16, 6, 10))

        positive = compare.build_report(
            first,
            second,
            anchor_radius=2,
            minimum_anchor_neighbours=2,
            max_anchor_instances=48,
            top_translations=32,
            minimum_shared_functional=8,
            minimum_connected_functional=6,
            minimum_shared_non_dispenser=6,
            minimum_mechanism_diversity=3,
        )
        assert positive["shared_core_candidate"] is True, positive
        assert positive["selected_overlap"]["translation"] == list(vector), positive
        assert positive["selected_overlap"]["exact_functional"] == 10, positive
        assert positive["confidence"] in {"medium", "high"}, positive

        generic_bank = {
            (x, y, 1): "minecraft:dispenser[facing=east,triggered=false]"
            for x in range(5)
            for y in range(4)
        }
        write_model(audit, bank_first, generic_bank, (6, 5, 3))
        write_model(audit, bank_second, generic_bank, (6, 5, 3))
        negative = compare.build_report(
            bank_first,
            bank_second,
            anchor_radius=2,
            minimum_anchor_neighbours=2,
            max_anchor_instances=48,
            top_translations=32,
            minimum_shared_functional=16,
            minimum_connected_functional=8,
            minimum_shared_non_dispenser=4,
            minimum_mechanism_diversity=1,
        )
        assert negative["selected_overlap"]["exact_functional"] == 20, negative
        assert negative["shared_core_candidate"] is False, negative
        assert "non_dispenser_functional_below_threshold" in negative["reasons"], negative

    print("Translated partial cores are recovered and generic dispenser panels are rejected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
