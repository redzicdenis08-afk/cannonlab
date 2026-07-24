#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any


TNT_TYPES = {"TNT", "PRIMED_TNT", "TNT_PRIMED"}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def point(row: dict[str, str]) -> tuple[float, float, float]:
    return float(row["x"]), float(row["y"]), float(row["z"])


def velocity(row: dict[str, str]) -> tuple[float, float, float]:
    return float(row["vx"]), float(row["vy"]), float(row["vz"])


def distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.dist(a, b)


def vector_delta(
    candidate: tuple[float, float, float],
    reference: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(candidate[i] - reference[i] for i in range(3))  # type: ignore[return-value]


def subtract_translation(
    value: tuple[float, float, float],
    translation: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(value[i] - translation[i] for i in range(3))  # type: ignore[return-value]


def entity_trajectories(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row.get("event") != "ENTITY" or row.get("type") not in TNT_TYPES:
            continue
        uuid = row.get("uuid", "")
        if uuid:
            result.setdefault(uuid, []).append(row)
    for trajectory in result.values():
        trajectory.sort(key=lambda row: int(row["tick"]))
    return result


def choose_uuid(
    trajectories: dict[str, list[dict[str, str]]],
    requested: str | None,
    index: int,
) -> str:
    if requested:
        if requested not in trajectories:
            raise ValueError(f"TNT UUID {requested} not present")
        return requested
    ordered = sorted(
        trajectories,
        key=lambda uuid: (
            int(trajectories[uuid][0]["tick"]),
            point(trajectories[uuid][0]),
            uuid,
        ),
    )
    if not ordered:
        raise ValueError("no TNT entity trajectories found")
    if index < 0 or index >= len(ordered):
        raise ValueError(f"entity index {index} outside 0..{len(ordered) - 1}")
    return ordered[index]


def explosion_for(rows: list[dict[str, str]], uuid: str) -> dict[str, str] | None:
    matches = [
        row
        for row in rows
        if row.get("event") == "EXPLOSION" and row.get("uuid") == uuid
    ]
    if not matches:
        return None
    return min(matches, key=lambda row: int(row["tick"]))


def bounds(points: list[tuple[float, float, float]]) -> dict[str, list[float]] | None:
    if not points:
        return None
    return {
        "min": [min(point[i] for point in points) for i in range(3)],
        "max": [max(point[i] for point in points) for i in range(3)],
    }


def nearby_explosion_group(
    rows: list[dict[str, str]],
    tick: int,
    center: tuple[float, float, float],
    tick_window: int,
    radius: float,
) -> dict[str, Any]:
    selected: list[dict[str, str]] = []
    for row in rows:
        if row.get("event") != "EXPLOSION":
            continue
        if abs(int(row["tick"]) - tick) > tick_window:
            continue
        if distance(point(row), center) <= radius:
            selected.append(row)
    points = [point(row) for row in selected]
    return {
        "count": len(selected),
        "tick_min": min((int(row["tick"]) for row in selected), default=None),
        "tick_max": max((int(row["tick"]) for row in selected), default=None),
        "bounds": bounds(points),
        "affected_blocks": sum(int(row.get("affected_blocks", 0) or 0) for row in selected),
    }


def compare(args: argparse.Namespace) -> dict[str, Any]:
    reference_rows = read_rows(args.reference_events)
    candidate_rows = read_rows(args.candidate_events)
    reference_trajectories = entity_trajectories(reference_rows)
    candidate_trajectories = entity_trajectories(candidate_rows)
    reference_uuid = choose_uuid(
        reference_trajectories, args.reference_uuid, args.entity_index
    )
    candidate_uuid = choose_uuid(
        candidate_trajectories, args.candidate_uuid, args.entity_index
    )
    reference = reference_trajectories[reference_uuid]
    candidate = candidate_trajectories[candidate_uuid]

    reference_first_tick = int(reference[0]["tick"])
    candidate_first_tick = int(candidate[0]["tick"])
    translation = (
        vector_delta(point(candidate[0]), point(reference[0]))
        if args.infer_translation
        else (0.0, 0.0, 0.0)
    )

    reference_by_age = {
        int(row["tick"]) - reference_first_tick: row for row in reference
    }
    candidate_by_age = {
        int(row["tick"]) - candidate_first_tick: row for row in candidate
    }
    common_ages = sorted(reference_by_age.keys() & candidate_by_age.keys())
    samples: list[dict[str, Any]] = []
    first_divergence: dict[str, Any] | None = None
    max_position_delta = 0.0
    max_velocity_delta = 0.0
    max_fuse_delta = 0

    for age in common_ages:
        reference_row = reference_by_age[age]
        candidate_row = candidate_by_age[age]
        reference_position = point(reference_row)
        candidate_position = subtract_translation(point(candidate_row), translation)
        reference_velocity = velocity(reference_row)
        candidate_velocity = velocity(candidate_row)
        position_delta = distance(reference_position, candidate_position)
        velocity_delta = distance(reference_velocity, candidate_velocity)
        fuse_delta = abs(int(reference_row["fuse"]) - int(candidate_row["fuse"]))
        max_position_delta = max(max_position_delta, position_delta)
        max_velocity_delta = max(max_velocity_delta, velocity_delta)
        max_fuse_delta = max(max_fuse_delta, fuse_delta)
        divergent = (
            position_delta > args.position_tolerance
            or velocity_delta > args.velocity_tolerance
            or fuse_delta > args.fuse_tolerance
        )
        sample = {
            "age": age,
            "reference_tick": int(reference_row["tick"]),
            "candidate_tick": int(candidate_row["tick"]),
            "reference_position": list(reference_position),
            "candidate_position_normalized": list(candidate_position),
            "reference_velocity": list(reference_velocity),
            "candidate_velocity": list(candidate_velocity),
            "position_delta": position_delta,
            "velocity_delta": velocity_delta,
            "fuse_delta": fuse_delta,
            "divergent": divergent,
        }
        if divergent and first_divergence is None:
            first_divergence = sample
        if divergent or age in {common_ages[0], common_ages[-1]}:
            samples.append(sample)

    failures: list[str] = []
    spawn_tick_delta = candidate_first_tick - reference_first_tick
    if abs(spawn_tick_delta) > args.spawn_tick_tolerance:
        failures.append(
            f"spawn_tick_delta={spawn_tick_delta} exceeds ±{args.spawn_tick_tolerance}"
        )
    if not common_ages:
        failures.append("no_common_entity_ages")
    if first_divergence is not None:
        failures.append(f"trajectory_diverged_at_age={first_divergence['age']}")
    if len(reference_by_age) != len(candidate_by_age):
        failures.append(
            f"trajectory_sample_count={len(candidate_by_age)}!={len(reference_by_age)}"
        )

    reference_explosion = explosion_for(reference_rows, reference_uuid)
    candidate_explosion = explosion_for(candidate_rows, candidate_uuid)
    explosion_report: dict[str, Any]
    if reference_explosion is None or candidate_explosion is None:
        explosion_report = {
            "reference_present": reference_explosion is not None,
            "candidate_present": candidate_explosion is not None,
        }
        failures.append("matching_explosion_missing")
    else:
        reference_explosion_position = point(reference_explosion)
        candidate_explosion_position = subtract_translation(
            point(candidate_explosion), translation
        )
        explosion_position_delta = distance(
            reference_explosion_position, candidate_explosion_position
        )
        reference_explosion_age = int(reference_explosion["tick"]) - reference_first_tick
        candidate_explosion_age = int(candidate_explosion["tick"]) - candidate_first_tick
        explosion_age_delta = candidate_explosion_age - reference_explosion_age
        if explosion_position_delta > args.explosion_position_tolerance:
            failures.append(
                "explosion_position_delta="
                f"{explosion_position_delta:.9f}>{args.explosion_position_tolerance}"
            )
        if abs(explosion_age_delta) > args.explosion_tick_tolerance:
            failures.append(
                f"explosion_age_delta={explosion_age_delta} "
                f"exceeds ±{args.explosion_tick_tolerance}"
            )
        explosion_report = {
            "reference_age": reference_explosion_age,
            "candidate_age": candidate_explosion_age,
            "age_delta": explosion_age_delta,
            "reference_position": list(reference_explosion_position),
            "candidate_position_normalized": list(candidate_explosion_position),
            "position_delta": explosion_position_delta,
        }

    divergence_context = None
    if first_divergence is not None:
        reference_center = tuple(first_divergence["reference_position"])
        candidate_center = tuple(first_divergence["candidate_position_normalized"])
        reference_tick = int(first_divergence["reference_tick"])
        candidate_tick = int(first_divergence["candidate_tick"])
        normalized_candidate_rows = []
        for row in candidate_rows:
            if row.get("event") != "EXPLOSION":
                normalized_candidate_rows.append(row)
                continue
            copied = dict(row)
            normalized = subtract_translation(point(row), translation)
            copied["x"], copied["y"], copied["z"] = map(str, normalized)
            normalized_candidate_rows.append(copied)
        divergence_context = {
            "reference_nearby_explosions": nearby_explosion_group(
                reference_rows,
                reference_tick,
                reference_center,
                args.nearby_explosion_tick_window,
                args.nearby_explosion_radius,
            ),
            "candidate_nearby_explosions": nearby_explosion_group(
                normalized_candidate_rows,
                candidate_tick,
                candidate_center,
                args.nearby_explosion_tick_window,
                args.nearby_explosion_radius,
            ),
        }

    return {
        "schema": "cannonlab-entity-trajectory-compare-v1",
        "status": "PASS" if not failures else "FAIL",
        "reference": {
            "events": str(args.reference_events),
            "uuid": reference_uuid,
            "samples": len(reference),
            "first_tick": reference_first_tick,
        },
        "candidate": {
            "events": str(args.candidate_events),
            "uuid": candidate_uuid,
            "samples": len(candidate),
            "first_tick": candidate_first_tick,
        },
        "normalization": {
            "translation": list(translation),
            "spawn_tick_delta": spawn_tick_delta,
            "aligned_by_entity_age": True,
        },
        "thresholds": {
            "position_tolerance": args.position_tolerance,
            "velocity_tolerance": args.velocity_tolerance,
            "fuse_tolerance": args.fuse_tolerance,
            "spawn_tick_tolerance": args.spawn_tick_tolerance,
            "explosion_position_tolerance": args.explosion_position_tolerance,
            "explosion_tick_tolerance": args.explosion_tick_tolerance,
        },
        "summary": {
            "common_samples": len(common_ages),
            "max_position_delta": max_position_delta,
            "max_velocity_delta": max_velocity_delta,
            "max_fuse_delta": max_fuse_delta,
            "first_divergence": first_divergence,
        },
        "explosion": explosion_report,
        "divergence_context": divergence_context,
        "selected_samples": samples[:50],
        "failures": failures,
        "truth_boundary": {
            "compares_recorded_runtime_trajectories": True,
            "translation_normalized": args.infer_translation,
            "identifies_first_observed_divergence": True,
            "proves_private_extremecraft_parity": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare one TNT trajectory across two CannonLab events.csv traces."
    )
    parser.add_argument("reference_events", type=Path)
    parser.add_argument("candidate_events", type=Path)
    parser.add_argument("--reference-uuid")
    parser.add_argument("--candidate-uuid")
    parser.add_argument("--entity-index", type=int, default=0)
    parser.add_argument("--infer-translation", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--position-tolerance", type=float, default=1.0e-6)
    parser.add_argument("--velocity-tolerance", type=float, default=1.0e-6)
    parser.add_argument("--fuse-tolerance", type=int, default=0)
    parser.add_argument("--spawn-tick-tolerance", type=int, default=0)
    parser.add_argument("--explosion-position-tolerance", type=float, default=1.0e-6)
    parser.add_argument("--explosion-tick-tolerance", type=int, default=0)
    parser.add_argument("--nearby-explosion-tick-window", type=int, default=0)
    parser.add_argument("--nearby-explosion-radius", type=float, default=16.0)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    try:
        report = compare(args)
    except (OSError, ValueError, KeyError) as exc:
        report = {
            "schema": "cannonlab-entity-trajectory-compare-v1",
            "status": "FAIL",
            "failures": [f"input_error:{exc}"],
        }

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
