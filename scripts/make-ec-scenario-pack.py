#!/usr/bin/env python3
"""Generate a consistent ExtremeCraft-candidate scenario pack for one cannon."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml


def point(value: str) -> dict[str, int]:
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected x,y,z")
    try:
        x, y, z = (int(item.strip()) for item in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected integer x,y,z") from exc
    return {"x": x, "y": y, "z": z}


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "cannon"


def base(args: argparse.Namespace, name: str, target_type: str, material: str = "obsidian") -> dict[str, Any]:
    scenario: dict[str, Any] = {
        "name": name,
        "evidence": {
            "grade": "local-runtime-candidate",
            "profile": "extremecraft-observed-2026-07-24",
            "field-ready": False,
        },
        "cannon": {
            "file": args.cannon_file,
            "origin": args.origin,
            "fire-mode": args.fire_mode,
            "fire-input": args.fire_input,
            "fire-pulse-ticks": args.fire_pulse_ticks,
            "fire-retry-ticks": args.fire_retry_ticks,
            "fire-max-attempts": args.fire_max_attempts,
            "tnt-per-dispenser": args.tnt_per_dispenser,
        },
        "limits": {"enforce-dispenser-limit": True},
        "target": {
            "type": target_type,
            "material": material,
            "alternate-material": "obsidian",
            "direction": args.direction,
            "distance": args.distance,
            "width": args.width,
            "height": args.height,
            "y-offset": args.y_offset,
            "lateral-offset": args.lateral_offset,
            "layers": args.layers,
            "spacing": args.spacing,
            "regeneration": {"enabled": False},
            "durability": {
                "mode": "native",
                "expiration-ticks": 1200,
                "only-tnt": True,
                "hit-radius": 4.0,
                "materials": {"obsidian": 4, "anvil": 3, "chipped_anvil": 3, "damaged_anvil": 3},
            },
        },
        "acceptance": {
            "require-payload": True,
            "min-target-destroyed": args.min_target_destroyed,
            "min-forward-distance": args.min_forward_distance,
            "min-remaining-dispenser-ratio": args.min_remaining_dispenser_ratio,
            "max-cannon-missing-blocks": args.max_cannon_missing_blocks,
            "max-cannon-replaced-type-blocks": args.max_cannon_replaced_type_blocks,
            "max-self-damage-blocks": args.max_self_damage_blocks,
        },
        "run": {
            "shots": args.shots,
            "volleys-per-shot": 1,
            "volley-interval-ticks": 100,
            "warmup-ticks": args.warmup_ticks,
            "max-shot-ticks": args.max_shot_ticks,
            "quiet-ticks": args.quiet_ticks,
            "shutdown-when-finished": True,
        },
    }
    return scenario


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False, width=120), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cannon_file")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--origin", type=point, default=point("0,0,0"))
    parser.add_argument("--fire-input", type=point, required=True)
    parser.add_argument("--fire-mode", choices=["redstone", "button"], default="button")
    parser.add_argument("--fire-pulse-ticks", type=int, default=4)
    parser.add_argument("--fire-retry-ticks", type=int, default=50)
    parser.add_argument("--fire-max-attempts", type=int, default=2)
    parser.add_argument("--tnt-per-dispenser", type=int, default=576)
    parser.add_argument("--direction", choices=["north", "south", "east", "west"], required=True)
    parser.add_argument("--distance", type=int, required=True)
    parser.add_argument("--width", type=int, default=17)
    parser.add_argument("--height", type=int, default=64)
    parser.add_argument("--y-offset", type=int, default=-16)
    parser.add_argument("--lateral-offset", type=int, default=0)
    parser.add_argument("--layers", type=int, default=1)
    parser.add_argument("--spacing", type=int, default=3)
    parser.add_argument("--shots", type=int, default=3)
    parser.add_argument("--warmup-ticks", type=int, default=100)
    parser.add_argument("--max-shot-ticks", type=int, default=700)
    parser.add_argument("--quiet-ticks", type=int, default=100)
    parser.add_argument("--min-target-destroyed", type=int, default=1)
    parser.add_argument("--min-forward-distance", type=float, default=1.0)
    parser.add_argument("--min-remaining-dispenser-ratio", type=float, default=0.95)
    parser.add_argument("--max-cannon-missing-blocks", type=int, default=64)
    parser.add_argument("--max-cannon-replaced-type-blocks", type=int, default=16)
    parser.add_argument("--max-self-damage-blocks", type=int, default=64)
    args = parser.parse_args()

    stem = slug(Path(args.cannon_file).stem)
    created: list[Path] = []

    dry = base(args, f"{stem}-ec-dry-baseline", "dry", "cobblestone")
    dry["target"].pop("durability")
    created.append(args.output_dir / f"{stem}-ec-dry-baseline.yml")
    write(created[-1], dry)

    watered = base(args, f"{stem}-ec-watered-obsidian", "watered")
    watered["run"]["volleys-per-shot"] = 4
    watered["run"]["volley-interval-ticks"] = 100
    created.append(args.output_dir / f"{stem}-ec-watered-obsidian.yml")
    write(created[-1], watered)

    hotdog = base(args, f"{stem}-ec-hotdog-fast-regen", "hotdog", "cobblestone")
    hotdog["target"].pop("durability")
    hotdog["target"]["hotdog-band-width"] = 2
    hotdog["target"]["regeneration"] = {
        "enabled": True,
        "delay-ticks": 4,
        "interval-ticks": 4,
        "max-blocks-per-cycle": 32,
    }
    hotdog["run"]["volleys-per-shot"] = 8
    hotdog["run"]["volley-interval-ticks"] = 40
    created.append(args.output_dir / f"{stem}-ec-hotdog-fast-regen.yml")
    write(created[-1], hotdog)

    for target_type in ("filter", "slab-filter", "pillars"):
        variant = base(args, f"{stem}-ec-{target_type}", target_type, "cobblestone")
        variant["target"].pop("durability")
        variant["target"]["layers"] = max(args.layers, 4)
        if target_type == "pillars":
            variant["target"]["pillar-spacing"] = 3
        path = args.output_dir / f"{stem}-ec-{target_type}.yml"
        created.append(path)
        write(path, variant)

    gauntlet = base(args, f"{stem}-ec-defense-gauntlet", "dry", "cobblestone")
    gauntlet["target"]["stages"] = [
        {"name": "watered-obby", "type": "watered", "material": "obsidian", "layers": 2, "spacing": 3, "gap-after": 3},
        {"name": "fast-hotdog", "type": "hotdog", "material": "cobblestone", "layers": 4, "spacing": 3, "gap-after": 3,
         "regeneration": {"enabled": True, "delay-ticks": 4, "interval-ticks": 4, "max-blocks-per-cycle": 32}},
        {"name": "slab-filter", "type": "slab-filter", "material": "cobblestone", "layers": 4, "spacing": 3, "gap-after": 3},
        {"name": "pillars", "type": "pillars", "material": "cobblestone", "layers": 4, "spacing": 3, "gap-after": 0, "pillar-spacing": 3},
    ]
    gauntlet["run"]["volleys-per-shot"] = 12
    gauntlet["run"]["volley-interval-ticks"] = 40
    path = args.output_dir / f"{stem}-ec-defense-gauntlet.yml"
    created.append(path)
    write(path, gauntlet)

    print("\n".join(str(path) for path in created))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
