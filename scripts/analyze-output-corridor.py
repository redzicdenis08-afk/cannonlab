#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "cannonlab-output-corridor-v1"
DIRECTION_VECTORS = {
    "EAST": (1.0, 0.0),
    "WEST": (-1.0, 0.0),
    "SOUTH": (0.0, 1.0),
    "NORTH": (0.0, -1.0),
}


@dataclass(frozen=True)
class Sample:
    tick: int
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class EntityPath:
    entity_type: str
    entity_uuid: str
    samples: tuple[Sample, ...]


def fail(message: str, *, report: dict[str, Any] | None = None) -> int:
    payload = report or {"schema": SCHEMA}
    payload["status"] = "FAIL"
    payload.setdefault("failures", []).append(message)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 2


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.fmean(items) if items else 0.0


def spread(values: Iterable[float]) -> float:
    items = list(values)
    return max(items) - min(items) if items else 0.0


def population_stddev(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.pstdev(items) if len(items) > 1 else 0.0


def locate_run_directory(path: Path) -> Path:
    if (path / "run-summary.json").is_file():
        return path
    summaries = sorted(path.rglob("run-summary.json"))
    if len(summaries) != 1:
        raise ValueError(
            f"expected exactly one run-summary.json below {path}, found {len(summaries)}"
        )
    return summaries[0].parent


def read_summary(run_directory: Path) -> dict[str, Any]:
    payload = json.loads((run_directory / "run-summary.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("run-summary.json must contain an object")
    return payload


def parse_entity_paths(events_path: Path, allowed_types: set[str]) -> list[EntityPath]:
    grouped: dict[tuple[str, str], list[Sample]] = defaultdict(list)
    with events_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("event", "")).upper() != "ENTITY":
                continue
            entity_type = str(row.get("type", "")).upper()
            entity_uuid = str(row.get("uuid", "")).strip()
            if entity_type not in allowed_types or not entity_uuid:
                continue
            try:
                grouped[(entity_type, entity_uuid)].append(
                    Sample(
                        tick=int(row["tick"]),
                        x=float(row["x"]),
                        y=float(row["y"]),
                        z=float(row["z"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as exception:
                raise ValueError(f"invalid entity row in {events_path}: {row}") from exception

    result: list[EntityPath] = []
    for (entity_type, entity_uuid), samples in grouped.items():
        ordered = tuple(sorted(samples, key=lambda sample: sample.tick))
        if len(ordered) >= 2:
            result.append(EntityPath(entity_type, entity_uuid, ordered))
    return result


def horizontal_metrics(
    path: EntityPath,
    forward_axis: tuple[float, float],
) -> dict[str, Any]:
    first = path.samples[0]
    ux, uz = forward_axis
    lateral_x, lateral_z = -uz, ux
    projected: list[tuple[float, float, float, Sample]] = []
    for sample in path.samples:
        dx = sample.x - first.x
        dz = sample.z - first.z
        forward = dx * ux + dz * uz
        lateral = dx * lateral_x + dz * lateral_z
        vertical = sample.y - first.y
        projected.append((forward, lateral, vertical, sample))

    max_forward, lateral_at_max, vertical_at_max, max_sample = max(
        projected,
        key=lambda item: item[0],
    )
    delta_x_at_max = max_sample.x - first.x
    delta_z_at_max = max_sample.z - first.z
    min_forward = min(item[0] for item in projected)
    final_forward, final_lateral, final_vertical, final_sample = projected[-1]
    horizontal_distance = math.hypot(max_forward, lateral_at_max)
    angle = math.degrees(math.atan2(lateral_at_max, max_forward)) if horizontal_distance else 0.0
    return {
        "entity_type": path.entity_type,
        "entity_uuid": path.entity_uuid,
        "first_tick": first.tick,
        "last_tick": final_sample.tick,
        "samples": len(path.samples),
        "max_forward": max_forward,
        "delta_x_at_max_forward": delta_x_at_max,
        "delta_z_at_max_forward": delta_z_at_max,
        "min_forward": min_forward,
        "lateral_at_max_forward": lateral_at_max,
        "vertical_at_max_forward": vertical_at_max,
        "angle_degrees": angle,
        "final_forward": final_forward,
        "final_lateral": final_lateral,
        "final_vertical": final_vertical,
        "max_forward_tick": max_sample.tick,
    }


def shot_report(
    shot_directory: Path,
    shot_number: int,
    forward_axis: tuple[float, float],
    allowed_types: set[str],
    min_forward: float,
    half_width: float,
    vertical_tolerance: float,
    min_entities: int,
    max_entity_details: int,
) -> dict[str, Any]:
    events_path = shot_directory / "events.csv"
    if not events_path.is_file():
        return {
            "shot": shot_number,
            "status": "FAIL",
            "failures": ["events.csv missing"],
            "qualifying_entities": 0,
            "entities": [],
        }

    entities = [
        horizontal_metrics(path, forward_axis)
        for path in parse_entity_paths(events_path, allowed_types)
    ]
    qualifying = [item for item in entities if item["max_forward"] >= min_forward]
    failures: list[str] = []
    if len(qualifying) < min_entities:
        failures.append(
            f"qualifying_entities={len(qualifying)}<{min_entities} at min_forward={min_forward}"
        )

    corridor_violations = [
        item
        for item in qualifying
        if abs(item["lateral_at_max_forward"]) > half_width
        or abs(item["vertical_at_max_forward"]) > vertical_tolerance
    ]
    if corridor_violations:
        failures.append(f"output-corridor violations={len(corridor_violations)}")

    reverse_entities = [item for item in qualifying if item["min_forward"] < -0.5]
    if reverse_entities:
        failures.append(f"reverse-output entities={len(reverse_entities)}")

    angles = [item["angle_degrees"] for item in qualifying]
    forwards = [item["max_forward"] for item in qualifying]
    laterals = [item["lateral_at_max_forward"] for item in qualifying]
    verticals = [item["vertical_at_max_forward"] for item in qualifying]
    delta_x_values = [item["delta_x_at_max_forward"] for item in qualifying]
    delta_z_values = [item["delta_z_at_max_forward"] for item in qualifying]
    return {
        "shot": shot_number,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "qualifying_entities": len(qualifying),
        "corridor_violations": len(corridor_violations),
        "reverse_entities": len(reverse_entities),
        "dominant_angle_degrees": statistics.median(angles) if angles else None,
        "mean_forward": mean(forwards),
        "min_forward": min(forwards) if forwards else None,
        "max_forward": max(forwards) if forwards else None,
        "mean_lateral": mean(laterals),
        "max_abs_lateral": max((abs(value) for value in laterals), default=0.0),
        "mean_vertical": mean(verticals),
        "max_abs_vertical": max((abs(value) for value in verticals), default=0.0),
        "mean_delta_x": mean(delta_x_values),
        "mean_delta_z": mean(delta_z_values),
        "entity_details_truncated": max(0, len(qualifying) - max_entity_details),
        "entities": qualifying[:max_entity_details],
    }


def cardinal_direction(delta_x: float, delta_z: float) -> str | None:
    if abs(delta_x) < 1e-12 and abs(delta_z) < 1e-12:
        return None
    if abs(delta_x) >= abs(delta_z):
        return "EAST" if delta_x >= 0 else "WEST"
    return "SOUTH" if delta_z >= 0 else "NORTH"


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    run_directory = locate_run_directory(args.results)
    summary = read_summary(run_directory)
    expected_direction = (args.expected_direction or summary.get("target_direction") or "").upper()
    if expected_direction not in DIRECTION_VECTORS:
        raise ValueError(
            f"expected direction must be one of {sorted(DIRECTION_VECTORS)}, got {expected_direction!r}"
        )

    shot_directories = sorted(
        path for path in run_directory.glob("shot-*") if path.is_dir()
    )
    shots = [
        shot_report(
            shot_directory,
            index,
            DIRECTION_VECTORS[expected_direction],
            set(args.entity_type),
            args.min_forward,
            args.half_width,
            args.vertical_tolerance,
            args.min_entities_per_shot,
            args.max_entity_details,
        )
        for index, shot_directory in enumerate(shot_directories, start=1)
    ]

    failures: list[str] = []
    if len(shots) < args.min_shots:
        failures.append(f"shots={len(shots)}<{args.min_shots}")
    failed_shots = [shot for shot in shots if shot["status"] != "PASS"]
    if failed_shots:
        failures.append(f"failed_shots={len(failed_shots)}")

    shot_angles = [
        float(shot["dominant_angle_degrees"])
        for shot in shots
        if shot["dominant_angle_degrees"] is not None
    ]
    shot_forwards = [float(shot["mean_forward"]) for shot in shots if shot["qualifying_entities"]]
    shot_laterals = [float(shot["mean_lateral"]) for shot in shots if shot["qualifying_entities"]]
    dominant_delta_x = mean(
        float(shot["mean_delta_x"]) for shot in shots if shot["qualifying_entities"]
    )
    dominant_delta_z = mean(
        float(shot["mean_delta_z"]) for shot in shots if shot["qualifying_entities"]
    )
    dominant_direction = cardinal_direction(dominant_delta_x, dominant_delta_z)
    angular_spread = spread(shot_angles)
    max_abs_angle = max((abs(value) for value in shot_angles), default=0.0)
    forward_spread = spread(shot_forwards)
    forward_mean = mean(shot_forwards)
    forward_relative_spread = forward_spread / forward_mean if forward_mean > 0 else None
    lateral_center_spread = spread(shot_laterals)

    if max_abs_angle > args.max_abs_angle:
        failures.append(
            f"max_abs_angle={max_abs_angle:.6f}>{args.max_abs_angle:.6f}"
        )
    if angular_spread > args.max_angular_spread:
        failures.append(
            f"angular_spread={angular_spread:.6f}>{args.max_angular_spread:.6f}"
        )
    if dominant_direction != expected_direction:
        failures.append(
            f"dominant_output_direction={dominant_direction!r}!={expected_direction!r}"
        )
    if forward_relative_spread is None:
        failures.append("forward_relative_spread unavailable")
    elif forward_relative_spread > args.max_forward_relative_spread:
        failures.append(
            "forward_relative_spread="
            f"{forward_relative_spread:.6f}>{args.max_forward_relative_spread:.6f}"
        )
    if lateral_center_spread > args.max_lateral_center_spread:
        failures.append(
            f"lateral_center_spread={lateral_center_spread:.6f}>"
            f"{args.max_lateral_center_spread:.6f}"
        )

    dominant_angle = statistics.median(shot_angles) if shot_angles else None
    direction_repeatability = {
        "shots_required": args.min_shots,
        "shots_observed": len(shots),
        "passing_shots": len(shots) - len(failed_shots),
        "dominant_angle_degrees": dominant_angle,
        "max_abs_angle_degrees": max_abs_angle,
        "angular-spread": angular_spread,
        "forward_mean": forward_mean,
        "forward_spread": forward_spread,
        "forward_relative_spread": forward_relative_spread,
        "lateral_center_spread": lateral_center_spread,
        "angle_stddev": population_stddev(shot_angles),
        "dominant_output_vector": {
            "delta_x": dominant_delta_x,
            "delta_z": dominant_delta_z,
        },
        "dominant_output_direction": dominant_direction,
    }
    output_corridor = {
        "expected_direction": expected_direction,
        "min_forward": args.min_forward,
        "half_width": args.half_width,
        "vertical_tolerance": args.vertical_tolerance,
        "entity_types": sorted(set(args.entity_type)),
        "min_entities_per_shot": args.min_entities_per_shot,
        "corridor_violations": sum(int(shot.get("corridor_violations", 0)) for shot in shots),
    }
    return {
        "schema": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "run_directory": str(run_directory),
        "scenario": summary.get("scenario"),
        "cannon_file": summary.get("cannon_file"),
        "dominant-output-direction": dominant_direction,
        "output-corridor": output_corridor,
        "direction-repeatability": direction_repeatability,
        "shots": shots,
        "failures": failures,
        "truth_boundary": (
            "This is measured local runtime trajectory evidence. It does not prove private "
            "ExtremeCraft parity or live raid readiness without a field canary."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure CannonLab output-corridor and multi-shot direction repeatability"
    )
    parser.add_argument("results", type=Path)
    parser.add_argument("--expected-direction", choices=sorted(DIRECTION_VECTORS))
    parser.add_argument("--entity-type", action="append", default=["TNT", "FALLING_BLOCK"])
    parser.add_argument("--min-shots", type=int, default=5)
    parser.add_argument("--min-entities-per-shot", type=int, default=1)
    parser.add_argument("--max-entity-details", type=int, default=100)
    parser.add_argument("--min-forward", type=float, default=10.0)
    parser.add_argument("--half-width", type=float, default=2.0)
    parser.add_argument("--vertical-tolerance", type=float, default=6.0)
    parser.add_argument("--max-abs-angle", type=float, default=5.0)
    parser.add_argument("--max-angular-spread", type=float, default=3.0)
    parser.add_argument("--max-forward-relative-spread", type=float, default=0.10)
    parser.add_argument("--max-lateral-center-spread", type=float, default=1.0)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    if args.min_shots < 1 or args.min_entities_per_shot < 1 or args.max_entity_details < 1:
        return fail("min-shots, min-entities-per-shot and max-entity-details must be positive")
    if args.min_forward <= 0 or args.half_width < 0 or args.vertical_tolerance < 0:
        return fail("corridor dimensions are invalid")
    if args.max_abs_angle < 0 or args.max_angular_spread < 0:
        return fail("angle limits must be non-negative")
    try:
        report = build_report(args)
    except (OSError, ValueError, json.JSONDecodeError) as exception:
        return fail(str(exception))

    text = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
