#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
FUNCTIONAL_TYPES = {
    "minecraft:dispenser",
    "minecraft:dropper",
    "minecraft:redstone_wire",
    "minecraft:repeater",
    "minecraft:comparator",
    "minecraft:observer",
    "minecraft:piston",
    "minecraft:sticky_piston",
    "minecraft:slime_block",
    "minecraft:honey_block",
    "minecraft:redstone_block",
    "minecraft:redstone_torch",
    "minecraft:redstone_wall_torch",
    "minecraft:tripwire",
    "minecraft:tripwire_hook",
    "minecraft:lever",
    "minecraft:stone_button",
    "minecraft:polished_blackstone_button",
    "minecraft:water",
    "minecraft:lava",
    "minecraft:soul_sand",
    "minecraft:powered_rail",
}
CONTROL_SUFFIXES = ("_button", "_pressure_plate")


def load_auditor() -> Any:
    script = Path(__file__).resolve().with_name("schem-audit.py")
    spec = importlib.util.spec_from_file_location("cannonlab_schem_audit", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def box(points: list[tuple[int, int, int]]) -> dict[str, Any] | None:
    if not points:
        return None
    minimum = [min(point[index] for point in points) for index in range(3)]
    maximum = [max(point[index] for point in points) for index in range(3)]
    dimensions = [maximum[index] - minimum[index] + 1 for index in range(3)]
    volume = math.prod(dimensions)
    return {
        "min": minimum,
        "max": maximum,
        "dimensions": {"x": dimensions[0], "y": dimensions[1], "z": dimensions[2]},
        "volume": volume,
        "density": round(len(points) / max(1, volume), 6),
    }


def alignment_scan(points: list[tuple[int, int, int]], limit: int) -> dict[str, Any]:
    scans = []
    for offset_x in range(16):
        for offset_z in range(16):
            counts = Counter(
                ((x + offset_x) // 16, (z + offset_z) // 16)
                for x, _y, z in points
            )
            scans.append({
                "offset_x": offset_x,
                "offset_z": offset_z,
                "max": max(counts.values(), default=0),
                "chunks": len(counts),
                "top_counts": sorted(counts.values(), reverse=True)[:12],
            })
    key = lambda row: (row["max"], row["chunks"], row["offset_x"], row["offset_z"])
    safe = [row for row in scans if row["max"] <= limit]
    return {
        "best": min(scans, key=key),
        "worst": max(scans, key=key),
        "safe_alignment_count": len(safe),
        "safe_alignments": safe,
    }


def profile_model(auditor: Any, model: dict[str, Any], chunk_limit: int) -> dict[str, Any]:
    blocks = model["blocks"]
    non_air = {
        pos: state
        for pos, state in blocks.items()
        if auditor.base(state) not in AIR
    }
    functional = {
        pos: state
        for pos, state in non_air.items()
        if auditor.base(state) in FUNCTIONAL_TYPES
    }
    counts = Counter(auditor.base(state) for state in non_air.values())
    dispensers = [
        (pos, state)
        for pos, state in non_air.items()
        if auditor.base(state) == "minecraft:dispenser"
    ]
    repeaters = [
        (pos, state)
        for pos, state in non_air.items()
        if auditor.base(state) == "minecraft:repeater"
    ]
    controls = [
        (pos, state)
        for pos, state in non_air.items()
        if auditor.base(state) == "minecraft:lever"
        or auditor.base(state).endswith(CONTROL_SUFFIXES)
    ]
    dispenser_layers = sorted({pos[1] for pos, _state in dispensers})
    repeater_delays = Counter(
        auditor.properties(state).get("delay", "unknown")
        for _pos, state in repeaters
    )
    dispenser_facings = Counter(
        auditor.properties(state).get("facing", "unknown")
        for _pos, state in dispensers
    )
    observers = counts["minecraft:observer"]
    pistons = counts["minecraft:piston"] + counts["minecraft:sticky_piston"]
    water = counts["minecraft:water"]
    timing_diversity = len([
        delay for delay, count in repeater_delays.items()
        if delay != "unknown" and count
    ])
    functional_diversity = len([
        block_type for block_type, count in counts.items()
        if count and block_type in FUNCTIONAL_TYPES
    ])
    functional_bounds = box(list(functional))
    dispenser_bounds = box([pos for pos, _state in dispensers])
    functional_height = (
        functional_bounds["dimensions"]["y"] if functional_bounds else 0
    )

    modern_signals = {
        "functional_height_at_least_16": functional_height >= 16,
        "dispenser_layers_at_least_8": len(dispenser_layers) >= 8,
        "observer_logic_present": observers >= 8,
        "piston_logic_present": pistons >= 4,
        "timing_network_present": len(repeaters) >= 8 and timing_diversity >= 2,
        "water_protection_present": water > 0,
        "real_control_present": len(controls) > 0,
        "functional_type_diversity_at_least_8": functional_diversity >= 8,
    }
    failed_signals = [
        signal for signal, passed in modern_signals.items() if not passed
    ]
    morphology_score = round(
        100 * sum(modern_signals.values()) / max(1, len(modern_signals))
    )

    return {
        "format": model["format"],
        "data_version": model["data_version"],
        "dimensions": model["source_dimensions"],
        "non_air_blocks": len(non_air),
        "functional_blocks": len(functional),
        "functional_bounds": functional_bounds,
        "dispenser_bounds": dispenser_bounds,
        "block_type_counts": dict(sorted(counts.items())),
        "functional_type_diversity": functional_diversity,
        "dispensers": {
            "count": len(dispensers),
            "facings": dict(sorted(dispenser_facings.items())),
            "y_layers": len(dispenser_layers),
            "y_span": (
                max(dispenser_layers) - min(dispenser_layers) + 1
                if dispenser_layers else 0
            ),
            "alignment": alignment_scan(
                [pos for pos, _state in dispensers],
                chunk_limit,
            ),
        },
        "repeaters": {
            "count": len(repeaters),
            "delay_counts": dict(sorted(repeater_delays.items())),
            "timing_diversity": timing_diversity,
        },
        "observers": observers,
        "pistons": pistons,
        "water": water,
        "controls": {
            "count": len(controls),
            "positions": [list(pos) for pos, _state in controls],
        },
        "modern_raid_morphology": {
            "score": morphology_score,
            "verdict": "PASS" if not failed_signals else "FAIL",
            "signals": modern_signals,
            "failed_signals": failed_signals,
            "truth_boundary": (
                "This is a structural anti-pancake gate, not proof of a subsystem "
                "role, firing sequence, Sakura behavior, or ExtremeCraft readiness."
            ),
        },
    }


def load_profile(auditor: Any, path: Path, chunk_limit: int) -> dict[str, Any]:
    root_name, root, _trailing, _size = auditor.load(path)
    model = auditor.decode_any(root_name, root)
    return profile_model(auditor, model, chunk_limit)


def reference_baseline(references: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not references:
        return None

    def med(path: tuple[str, ...]) -> float:
        values = []
        for profile in references:
            current: Any = profile
            for key in path:
                current = current[key]
            values.append(float(current))
        return round(float(median(values)), 6)

    return {
        "reference_count": len(references),
        "median_functional_height": med(("functional_bounds", "dimensions", "y")),
        "median_dispenser_layers": med(("dispensers", "y_layers")),
        "median_dispenser_count": med(("dispensers", "count")),
        "median_observers": med(("observers",)),
        "median_pistons": med(("pistons",)),
        "median_repeaters": med(("repeaters", "count")),
        "median_functional_diversity": med(("functional_type_diversity",)),
    }


def ratio(value: float, baseline: float) -> float | None:
    if baseline <= 0:
        return None
    return round(value / baseline, 6)


def compare_to_baseline(
    candidate: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if baseline is None:
        return None
    comparisons = {
        "functional_height_ratio": ratio(
            candidate["functional_bounds"]["dimensions"]["y"]
            if candidate["functional_bounds"] else 0,
            baseline["median_functional_height"],
        ),
        "dispenser_layer_ratio": ratio(
            candidate["dispensers"]["y_layers"],
            baseline["median_dispenser_layers"],
        ),
        "dispenser_count_ratio": ratio(
            candidate["dispensers"]["count"],
            baseline["median_dispenser_count"],
        ),
        "observer_ratio": ratio(
            candidate["observers"],
            baseline["median_observers"],
        ),
        "piston_ratio": ratio(
            candidate["pistons"],
            baseline["median_pistons"],
        ),
        "repeater_ratio": ratio(
            candidate["repeaters"]["count"],
            baseline["median_repeaters"],
        ),
        "functional_diversity_ratio": ratio(
            candidate["functional_type_diversity"],
            baseline["median_functional_diversity"],
        ),
    }
    weak = [
        key for key, value in comparisons.items()
        if value is not None and value < 0.25
    ]
    return {
        "ratios": comparisons,
        "severe_gaps_below_25_percent": weak,
        "verdict": "FAIL" if weak else "PASS",
        "truth_boundary": (
            "Reference similarity is structural only. A smaller valid module may "
            "intentionally differ, so use intent=calibration for calibration builds."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Profile cannon geometry and reject flat fake-modern candidates"
    )
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--reference", type=Path, action="append", default=[])
    parser.add_argument(
        "--intent",
        choices=("calibration", "modern-raid"),
        default="modern-raid",
    )
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    auditor = load_auditor()
    candidate = load_profile(auditor, args.candidate, args.chunk_limit)
    references = [
        load_profile(auditor, path, args.chunk_limit)
        for path in args.reference
    ]
    baseline = reference_baseline(references)
    comparison = compare_to_baseline(candidate, baseline)

    failures = []
    if candidate["dispensers"]["count"] == 0:
        failures.append("candidate contains no dispensers")
    if candidate["dispensers"]["alignment"]["safe_alignment_count"] == 0:
        failures.append(
            f"no X/Z alignment satisfies {args.chunk_limit} dispensers per chunk"
        )
    if args.intent == "modern-raid":
        failures.extend(
            candidate["modern_raid_morphology"]["failed_signals"]
        )
        if comparison and comparison["verdict"] == "FAIL":
            failures.extend(comparison["severe_gaps_below_25_percent"])

    report = {
        "status": "PASS" if not failures else "FAIL",
        "intent": args.intent,
        "candidate_file": str(args.candidate),
        "reference_files": [str(path) for path in args.reference],
        "chunk_limit": args.chunk_limit,
        "candidate": candidate,
        "reference_baseline": baseline,
        "comparison": comparison,
        "failures": sorted(set(failures)),
        "design_rule": (
            "For modern-raid work, modify a decoded proven reference and preserve "
            "its causal sequence. Do not synthesize flat dispenser rows from scratch."
        ),
    }
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if not failures else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"},
                indent=2,
            ),
            file=__import__("sys").stderr,
        )
        raise SystemExit(3)
