#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import importlib.util
from pathlib import Path
from typing import Any


def load_audit() -> Any:
    script = Path(__file__).with_name("schem-audit.py")
    spec = importlib.util.spec_from_file_location("endurance_probe_audit", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_model() -> dict[str, Any]:
    blocks: dict[tuple[int, int, int], str] = {
        # Native redstone input is AIR at (0, 1, 1); CannonLab briefly places a
        # redstone block there. These supports make the fixture paste-stable.
        (0, 0, 1): "minecraft:obsidian",
        (1, 0, 1): "minecraft:obsidian",
        # The dispenser fires east into one fully enclosed source-water cell.
        (1, 1, 1): "minecraft:dispenser[facing=east,triggered=false]",
        (2, 1, 1): "minecraft:water[level=0]",
        # Water/explosion chamber. TNT exploding in water must leave this exact
        # baseline intact for cumulative endurance to pass.
        (2, 0, 1): "minecraft:obsidian",
        (2, 2, 1): "minecraft:obsidian",
        (2, 1, 0): "minecraft:obsidian",
        (2, 1, 2): "minecraft:obsidian",
        (3, 1, 1): "minecraft:obsidian",
    }
    return {
        "blocks": blocks,
        "block_entities": [
            {"pos": (1, 1, 1), "id": "minecraft:dispenser", "raw": {}}
        ],
        "source_dimensions": {"width": 4, "height": 3, "length": 3},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the one-paste water-protected CannonLab endurance probe."
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--base64-out", type=Path)
    args = parser.parse_args()

    audit = load_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    audit.write_sponge_v2(
        args.output,
        build_model(),
        3465,
        canonical_gzip=True,
    )

    root_name, root, trailing, _decoded_size, diagnostics = audit.load(args.output)
    model = audit.decode_any(root_name, root)
    dispenser_count = sum(
        audit.base(state) == "minecraft:dispenser"
        for state in model.get("blocks", {}).values()
    )
    errors: list[str] = []
    if trailing:
        errors.append(f"unexpected trailing NBT bytes: {len(trailing)}")
    if diagnostics.get("strict_gzip_valid") is not True:
        errors.append("strict gzip validation failed")
    if dispenser_count != 1:
        errors.append(f"expected exactly one dispenser, observed {dispenser_count}")
    if errors:
        raise SystemExit("endurance probe audit failed: " + "; ".join(errors))

    if args.base64_out:
        args.base64_out.parent.mkdir(parents=True, exist_ok=True)
        args.base64_out.write_text(
            base64.b64encode(args.output.read_bytes()).decode("ascii") + "\n",
            encoding="ascii",
        )

    print(
        f"Built {args.output} with one east-facing dispenser and a sealed water chamber."
    )


if __name__ == "__main__":
    main()
