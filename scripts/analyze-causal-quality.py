#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


def numeric(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "spread": max(values) - min(values),
    }


def point_box_distance(point: tuple[float, float, float], bounds: dict[str, Any] | None) -> float | None:
    if not isinstance(bounds, dict):
        return None
    required = ("min_x", "min_y", "min_z", "max_x", "max_y", "max_z")
    if any(key not in bounds for key in required):
        return None
    x, y, z = point
    dx = max(float(bounds["min_x"]) - x, 0.0, x - float(bounds["max_x"]) - 1.0)
    dy = max(float(bounds["min_y"]) - y, 0.0, y - float(bounds["max_y"]) - 1.0)
    dz = max(float(bounds["min_z"]) - z, 0.0, z - float(bounds["max_z"]) - 1.0)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def radius(points: list[tuple[float, float, float]]) -> float | None:
    if not points:
        return None
    cx = statistics.fmean(point[0] for point in points)
    cy = statistics.fmean(point[1] for point in points)
    cz = statistics.fmean(point[2] for point in points)
    return max(math.dist(point, (cx, cy, cz)) for point in points)


def discover(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("causal-events.csv"))


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def cohort_map(
    rows: Iterable[dict[str, str]],
    event: str,
    *,
    entity_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("event") != event:
            continue
        if entity_types and row.get("entity_type") not in entity_types:
            continue
        grouped[int(row.get("tick") or 0)].append(row)
    return [
        {
            "tick": tick,
            "count": len(items),
            "components": sorted({item.get("component_id", "") for item in items if item.get("component_id")}),
        }
        for tick, items in sorted(grouped.items())
    ]


def custom_type(details: str) -> str:
    for part in details.split(";"):
        if part.startswith("type="):
            return part.split("=", 1)[1]
    return ""


def analyze_trace(trace: Path, impact_window: float) -> dict[str, Any]:
    with trace.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    event_counts = Counter(row.get("event", "") for row in rows)
    trigger_ticks = [
        int(row.get("tick") or 0)
        for row in rows
        if row.get("event") in {"FIRE_INPUT", "REDSTONE_CHANGE"}
    ]
    dispense = cohort_map(rows, "DISPENSE")
    tnt_add = cohort_map(rows, "ENTITY_ADD", entity_types={"TNT", "PRIMED_TNT"})
    falling_add = cohort_map(rows, "ENTITY_ADD", entity_types={"FALLING_BLOCK"})

    stage_events: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        event = row.get("event", "")
        if event not in {"TARGET_DESTROYED", "REGEN_RESTORE"}:
            continue
        typed = custom_type(row.get("details", ""))
        stage = typed.rsplit(":", 1)[0] if ":" in typed else typed or "unknown"
        stage_events[stage][event] += 1

    summary = read_json(trace.parent / "summary.json") or {}
    run_summary = read_json(trace.parent.parent / "run-summary.json") or {}
    target_bounds = run_summary.get("target_bounds")

    explosions: list[tuple[float, float, float]] = []
    target_impacts: list[tuple[float, float, float]] = []
    target_misses: list[float] = []
    for row in rows:
        if row.get("event") not in {"EXPLOSION", "BLOCK_EXPLOSION"}:
            continue
        point = (
            float(row.get("world_x") or 0.0),
            float(row.get("world_y") or 0.0),
            float(row.get("world_z") or 0.0),
        )
        explosions.append(point)
        miss = point_box_distance(point, target_bounds)
        if miss is not None:
            target_misses.append(miss)
            if miss <= impact_window:
                target_impacts.append(point)

    first_trigger = min(trigger_ticks) if trigger_ticks else None
    first_dispense = dispense[0]["tick"] if dispense else None
    trigger_latency = (
        first_dispense - first_trigger
        if first_trigger is not None and first_dispense is not None
        else None
    )
    largest_dispense = max((cohort["count"] for cohort in dispense), default=0)
    largest_tnt_add = max((cohort["count"] for cohort in tnt_add), default=0)
    largest_falling = max((cohort["count"] for cohort in falling_add), default=0)

    return {
        "trace": str(trace),
        "event_counts": dict(event_counts),
        "trigger_tick": first_trigger,
        "first_dispense_tick": first_dispense,
        "trigger_to_first_dispense_ticks": trigger_latency,
        "dispense_cohorts": dispense,
        "largest_dispense_cohort": largest_dispense,
        "tnt_spawn_cohorts": tnt_add,
        "largest_tnt_spawn_cohort": largest_tnt_add,
        "falling_block_cohorts": falling_add,
        "largest_falling_block_cohort": largest_falling,
        "explosion_count": len(explosions),
        "target_impact_count": len(target_impacts),
        "target_impact_radius": radius(target_impacts),
        "closest_target_miss": min(target_misses) if target_misses else None,
        "self_damage_blocks": int(summary.get("self_damage_blocks", 0)),
        "target_bounds_available": isinstance(target_bounds, dict),
        "stage_events": {stage: dict(counts) for stage, counts in sorted(stage_events.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score synchronization, convergence, payload and self-damage from CannonLab causal traces")
    parser.add_argument("trace_or_results", type=Path)
    parser.add_argument("--impact-window", type=float, default=12.0)
    parser.add_argument("--max-trigger-to-first-dispense", type=int)
    parser.add_argument("--min-largest-dispense-cohort", type=int)
    parser.add_argument("--max-target-impact-radius", type=float)
    parser.add_argument("--max-self-damage", type=int)
    parser.add_argument("--require-falling-block", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    traces = discover(args.trace_or_results)
    if not traces:
        raise SystemExit(f"no causal-events.csv found at {args.trace_or_results}")

    shots = [analyze_trace(trace, args.impact_window) for trace in traces]
    errors: list[str] = []
    for shot in shots:
        name = shot["trace"]
        latency = shot["trigger_to_first_dispense_ticks"]
        if args.max_trigger_to_first_dispense is not None and (
            latency is None or latency > args.max_trigger_to_first_dispense
        ):
            errors.append(f"{name}: trigger latency {latency} exceeds {args.max_trigger_to_first_dispense}")
        if args.min_largest_dispense_cohort is not None and shot["largest_dispense_cohort"] < args.min_largest_dispense_cohort:
            errors.append(
                f"{name}: largest dispense cohort {shot['largest_dispense_cohort']} below {args.min_largest_dispense_cohort}"
            )
        impact_radius = shot["target_impact_radius"]
        if args.max_target_impact_radius is not None and (
            impact_radius is None or impact_radius > args.max_target_impact_radius
        ):
            errors.append(f"{name}: target impact radius {impact_radius} exceeds {args.max_target_impact_radius}")
        if args.max_self_damage is not None and shot["self_damage_blocks"] > args.max_self_damage:
            errors.append(f"{name}: self damage {shot['self_damage_blocks']} exceeds {args.max_self_damage}")
        if args.require_falling_block and shot["largest_falling_block_cohort"] < 1:
            errors.append(f"{name}: no falling-block payload cohort")

    latencies = [float(shot["trigger_to_first_dispense_ticks"]) for shot in shots if shot["trigger_to_first_dispense_ticks"] is not None]
    impact_radii = [float(shot["target_impact_radius"]) for shot in shots if shot["target_impact_radius"] is not None]
    self_damage = [float(shot["self_damage_blocks"]) for shot in shots]
    report = {
        "status": "PASS" if not errors else "FAIL",
        "trace_count": len(shots),
        "impact_window": args.impact_window,
        "trigger_latency": numeric(latencies),
        "target_impact_radius": numeric(impact_radii),
        "self_damage_blocks": numeric(self_damage),
        "largest_dispense_cohort": numeric([float(shot["largest_dispense_cohort"]) for shot in shots]),
        "largest_tnt_spawn_cohort": numeric([float(shot["largest_tnt_spawn_cohort"]) for shot in shots]),
        "largest_falling_block_cohort": numeric([float(shot["largest_falling_block_cohort"]) for shot in shots]),
        "errors": errors,
        "shots": shots,
    }
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
