#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


DIRECTION_AXES: dict[str, tuple[int, int]] = {
    "EAST": (0, 1),
    "WEST": (0, -1),
    "SOUTH": (2, 1),
    "NORTH": (2, -1),
}


@dataclass
class Track:
    uuid: str
    entity_type: str
    first_tick: int = 2**31 - 1
    last_tick: int = -1
    samples: list[tuple[int, float, float, float]] = field(default_factory=list)
    explosion: tuple[int, float, float, float] | None = None

    def add(self, tick: int, x: float, y: float, z: float, event: str) -> None:
        self.first_tick = min(self.first_tick, tick)
        self.last_tick = max(self.last_tick, tick)
        self.samples.append((tick, x, y, z))
        if event == "EXPLOSION":
            self.explosion = (tick, x, y, z)


class ClassificationError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClassificationError(f"unable to read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ClassificationError(f"expected object in {path}")
    return payload


def _find_run_summaries(path: Path) -> list[Path]:
    if path.is_file():
        if path.name != "run-summary.json":
            raise ClassificationError("file input must be run-summary.json")
        return [path]
    rows = sorted(path.rglob("run-summary.json"))
    if not rows:
        raise ClassificationError(f"no run-summary.json below {path}")
    return rows


def _float(row: dict[str, str], key: str) -> float:
    try:
        return float(row[key])
    except (KeyError, ValueError) as exc:
        raise ClassificationError(f"bad {key!r} value in events row: {row}") from exc


def _int(row: dict[str, str], key: str) -> int:
    try:
        return int(row[key])
    except (KeyError, ValueError) as exc:
        raise ClassificationError(f"bad {key!r} value in events row: {row}") from exc


def _load_tracks(events_path: Path) -> dict[str, Track]:
    tracks: dict[str, Track] = {}
    with events_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected = {"tick", "event", "type", "uuid", "x", "y", "z"}
        if reader.fieldnames is None or not expected.issubset(reader.fieldnames):
            raise ClassificationError(f"events file missing required columns: {events_path}")
        for row in reader:
            uuid = (row.get("uuid") or "").strip()
            entity_type = (row.get("type") or "").strip().upper()
            event = (row.get("event") or "").strip().upper()
            if not uuid or entity_type not in {"TNT", "FALLING_BLOCK"}:
                continue
            track = tracks.setdefault(uuid, Track(uuid=uuid, entity_type=entity_type))
            track.add(_int(row, "tick"), _float(row, "x"), _float(row, "y"), _float(row, "z"), event)
    return tracks


def _center(bounds: dict[str, Any]) -> tuple[float, float, float]:
    return (
        (float(bounds["min_x"]) + float(bounds["max_x"])) / 2.0,
        (float(bounds["min_y"]) + float(bounds["max_y"])) / 2.0,
        (float(bounds["min_z"]) + float(bounds["max_z"])) / 2.0,
    )


def _project(position: tuple[float, float, float], origin: tuple[float, float, float], direction: str) -> float:
    axis, sign = DIRECTION_AXES[direction]
    return (position[axis] - origin[axis]) * sign


def _lane_distance(position: tuple[float, float, float], target: tuple[float, float, float], direction: str) -> float:
    if direction in {"EAST", "WEST"}:
        return math.hypot(position[1] - target[1], position[2] - target[2])
    return math.hypot(position[0] - target[0], position[1] - target[1])


def _track_metrics(
    track: Track,
    origin: tuple[float, float, float],
    target: tuple[float, float, float],
    direction: str,
) -> dict[str, Any]:
    points = [(tick, (x, y, z)) for tick, x, y, z in track.samples]
    target_forward = _project(target, origin, direction)
    closest = min(points, key=lambda item: abs(_project(item[1], origin, direction) - target_forward))
    forward_values = [_project(pos, origin, direction) for _tick, pos in points]
    result: dict[str, Any] = {
        "uuid": track.uuid,
        "entity_type": track.entity_type,
        "first_tick": track.first_tick,
        "last_tick": track.last_tick,
        "sample_count": len(points),
        "max_forward": max(forward_values),
        "min_forward": min(forward_values),
        "closest_target_plane_tick": closest[0],
        "closest_target_plane_forward_error": abs(_project(closest[1], origin, direction) - target_forward),
        "closest_target_plane_lane_error": _lane_distance(closest[1], target, direction),
        "closest_target_plane_position": list(closest[1]),
    }
    if track.explosion is not None:
        tick, x, y, z = track.explosion
        pos = (x, y, z)
        result["explosion"] = {
            "tick": tick,
            "position": [x, y, z],
            "forward": _project(pos, origin, direction),
            "forward_error": _project(pos, origin, direction) - target_forward,
            "lane_error": _lane_distance(pos, target, direction),
        }
    return result


def _group_cohorts(tracks: Iterable[Track], tolerance_ticks: int = 1) -> list[list[Track]]:
    ordered = sorted(tracks, key=lambda track: (track.first_tick, track.uuid))
    cohorts: list[list[Track]] = []
    for track in ordered:
        if not cohorts or track.first_tick - cohorts[-1][0].first_tick > tolerance_ticks:
            cohorts.append([track])
        else:
            cohorts[-1].append(track)
    return cohorts


def _minimum_overlap(
    payload_tracks: Iterable[Track],
    sand_tracks: Iterable[Track],
    tick_tolerance: int,
) -> dict[str, Any] | None:
    sand_by_tick: dict[int, list[tuple[str, tuple[float, float, float]]]] = defaultdict(list)
    for sand in sand_tracks:
        for tick, x, y, z in sand.samples:
            sand_by_tick[tick].append((sand.uuid, (x, y, z)))
    best: tuple[float, int, str, str, tuple[float, float, float], tuple[float, float, float]] | None = None
    for payload in payload_tracks:
        if payload.explosion is None:
            continue
        tick, x, y, z = payload.explosion
        payload_pos = (x, y, z)
        for candidate_tick in range(tick - tick_tolerance, tick + tick_tolerance + 1):
            for sand_uuid, sand_pos in sand_by_tick.get(candidate_tick, []):
                distance = math.dist(payload_pos, sand_pos)
                candidate = (distance, candidate_tick, payload.uuid, sand_uuid, payload_pos, sand_pos)
                if best is None or candidate < best:
                    best = candidate
    if best is None:
        return None
    return {
        "distance": best[0],
        "sand_tick": best[1],
        "payload_uuid": best[2],
        "sand_uuid": best[3],
        "payload_position": list(best[4]),
        "sand_position": list(best[5]),
    }


def _severity_self_damage(shot: dict[str, Any]) -> float:
    initial = max(1, int(shot.get("cannon_initial_blocks", 0)))
    return float(shot.get("self_damage_blocks", 0)) / initial


def _classify_one(
    run_summary_path: Path,
    lane_tolerance: float,
    fusion_tolerance: float,
    tick_tolerance: int,
) -> dict[str, Any]:
    run = _read_json(run_summary_path)
    direction = str(run.get("target_direction", "")).upper()
    if direction not in DIRECTION_AXES:
        raise ClassificationError(f"unsupported target direction {direction!r}")
    origin_obj = run.get("arena_origin") or {}
    origin = (float(origin_obj["x"]), float(origin_obj["y"]), float(origin_obj["z"]))
    target_bounds = run.get("target_bounds")
    if not isinstance(target_bounds, dict):
        raise ClassificationError("run summary missing target_bounds")
    target = _center(target_bounds)
    target_forward = _project(target, origin, direction)

    shot_reports: list[dict[str, Any]] = []
    for shot in run.get("shots", []):
        shot_number = int(shot.get("shot", len(shot_reports) + 1))
        shot_dir = run_summary_path.parent / f"shot-{shot_number:03d}"
        events_path = shot_dir / "events.csv"
        if not events_path.is_file():
            shot_reports.append({
                "shot": shot_number,
                "status": "MISSING_TRACE",
                "failures": ["TRACE_MISSING"],
                "summary": shot,
            })
            continue

        tracks = _load_tracks(events_path)
        tnt_tracks = [track for track in tracks.values() if track.entity_type == "TNT"]
        sand_tracks = [track for track in tracks.values() if track.entity_type == "FALLING_BLOCK"]
        tnt_cohorts = _group_cohorts(tnt_tracks)
        charge_tracks = tnt_cohorts[0] if tnt_cohorts else []
        payload_tracks = [track for cohort in tnt_cohorts[1:] for track in cohort]
        if not payload_tracks and len(tnt_cohorts) == 1 and len(tnt_cohorts[0]) <= 8:
            payload_tracks = list(tnt_cohorts[0])
            charge_tracks = []

        payload_metrics = [_track_metrics(track, origin, target, direction) for track in payload_tracks]
        sand_metrics = [_track_metrics(track, origin, target, direction) for track in sand_tracks]
        overlap = _minimum_overlap(payload_tracks, sand_tracks, tick_tolerance)

        payload_max_forward = max((row["max_forward"] for row in payload_metrics), default=float("-inf"))
        payload_reaching_plane = [row for row in payload_metrics if row["max_forward"] >= target_forward - 0.5]
        payload_min_lane = min(
            (row["closest_target_plane_lane_error"] for row in payload_reaching_plane),
            default=float("inf"),
        )
        sand_max_forward = max((row["max_forward"] for row in sand_metrics), default=float("-inf"))
        sand_reaching_plane = [row for row in sand_metrics if row["max_forward"] >= target_forward - 0.5]
        sand_min_lane = min(
            (row["closest_target_plane_lane_error"] for row in sand_reaching_plane),
            default=float("inf"),
        )
        explosion_rows = [row["explosion"] for row in payload_metrics if "explosion" in row]
        explosion_forward_errors = [float(row["forward_error"]) for row in explosion_rows]

        failures: list[str] = []
        recommendations: list[str] = []
        if not payload_tracks:
            failures.append("PAYLOAD_NOT_IDENTIFIED")
            recommendations.append("Separate payload activation from charge activation and record a distinct spawn cohort.")
        elif payload_max_forward < target_forward - 0.5:
            failures.append("PAYLOAD_RANGE_SHORT")
            recommendations.append("Increase or focus force only after proving the payload is seated in the charge impulse line.")
        elif payload_min_lane > lane_tolerance:
            failures.append("PAYLOAD_LANE_DIVERGENCE")
            recommendations.append("Repair guider, realignment and symmetric payload seating before changing fuse timing or force count.")

        if explosion_forward_errors:
            closest_error = min(explosion_forward_errors, key=abs)
            if closest_error < -lane_tolerance:
                failures.append("PAYLOAD_FUSE_EARLY")
                recommendations.append("Prime the payload earlier relative to charge so its fuse expires nearer the target plane.")
            elif closest_error > lane_tolerance:
                failures.append("PAYLOAD_FUSE_LATE")
                recommendations.append("Prime the payload later relative to charge so it does not overfly the target plane.")
        else:
            failures.append("PAYLOAD_EXPLOSION_NOT_RECORDED")

        if not sand_tracks:
            failures.append("SAND_NOT_RELEASED")
            recommendations.append("Prove a held-to-falling transition before evaluating hammer or fusion timing.")
        elif sand_max_forward < target_forward - 0.5:
            failures.append("SAND_RANGE_SHORT")
            recommendations.append("Add a real hammer/compression impulse; release timing alone cannot carry stationary sand to the wall.")
        elif sand_min_lane > lane_tolerance:
            failures.append("SAND_LANE_DIVERGENCE")
            recommendations.append("Align the sand column with the payload lane before tuning hybrid overlap.")

        if payload_tracks and sand_tracks and (overlap is None or overlap["distance"] > fusion_tolerance):
            failures.append("PAYLOAD_SAND_NO_FUSION")
            recommendations.append("Tune hammer and payload phases independently until sand and payload overlap within the fusion radius at the target.")

        if int(shot.get("target_peak_destroyed", 0)) <= 0:
            failures.append("TARGET_UNTOUCHED")
        elif int(shot.get("target_ever_destroyed", 0)) <= 0:
            failures.append("TARGET_DAMAGED_NOT_BROKEN")

        if int(shot.get("durability_hits", 0)) <= 0 and str(run.get("durability", {}).get("effective_mode", "")).upper() == "SIMULATE":
            failures.append("NO_DURABILITY_HIT")

        self_damage = int(shot.get("self_damage_blocks", 0))
        if self_damage > int(run.get("acceptance", {}).get("max_self_damage_blocks", 0)):
            failures.append("CANNON_SELF_DAMAGE")
            recommendations.append("Treat self-damage as a chamber/muzzle protection failure, not a cosmetic acceptance issue.")

        remaining = int(shot.get("cannon_remaining_dispensers", 0))
        initial_disp = max(1, int(shot.get("cannon_initial_dispensers", 0)))
        if remaining < initial_disp:
            failures.append("DISPENSER_LOSS")

        causal_priority = [
            "PAYLOAD_NOT_IDENTIFIED",
            "SAND_NOT_RELEASED",
            "PAYLOAD_RANGE_SHORT",
            "PAYLOAD_LANE_DIVERGENCE",
            "PAYLOAD_FUSE_EARLY",
            "PAYLOAD_FUSE_LATE",
            "SAND_RANGE_SHORT",
            "SAND_LANE_DIVERGENCE",
            "PAYLOAD_SAND_NO_FUSION",
            "NO_DURABILITY_HIT",
            "TARGET_UNTOUCHED",
            "CANNON_SELF_DAMAGE",
            "DISPENSER_LOSS",
        ]
        primary_failure = next((name for name in causal_priority if name in failures), None)
        shot_reports.append({
            "shot": shot_number,
            "status": "PASS" if not failures and bool(shot.get("contract_pass")) else "FAIL",
            "primary_failure": primary_failure,
            "failures": failures,
            "recommendations": list(dict.fromkeys(recommendations)),
            "target": {
                "center": list(target),
                "forward": target_forward,
                "lane_tolerance": lane_tolerance,
                "fusion_tolerance": fusion_tolerance,
            },
            "cohorts": {
                "tnt": [
                    {"first_tick": cohort[0].first_tick, "count": len(cohort), "uuids": [track.uuid for track in cohort]}
                    for cohort in tnt_cohorts
                ],
                "charge_count": len(charge_tracks),
                "payload_count": len(payload_tracks),
                "sand_count": len(sand_tracks),
            },
            "payload": {
                "max_forward": None if payload_max_forward == float("-inf") else payload_max_forward,
                "minimum_lane_error": None if payload_min_lane == float("inf") else payload_min_lane,
                "tracks": payload_metrics,
            },
            "sand": {
                "max_forward": None if sand_max_forward == float("-inf") else sand_max_forward,
                "minimum_lane_error": None if sand_min_lane == float("inf") else sand_min_lane,
                "tracks": sand_metrics,
            },
            "fusion": overlap,
            "integrity": {
                "self_damage_blocks": self_damage,
                "self_damage_ratio": _severity_self_damage(shot),
                "initial_dispensers": initial_disp,
                "remaining_dispensers": remaining,
            },
            "runtime_summary": shot,
        })

    return {
        "schema_version": 1,
        "classification": "CANNONLAB_CAUSAL_FAILURE_V1",
        "run_id": run.get("run_id"),
        "scenario": run.get("scenario"),
        "cannon_file": run.get("cannon_file"),
        "target_direction": direction,
        "shots": shot_reports,
        "overall_status": "PASS" if shot_reports and all(row["status"] == "PASS" for row in shot_reports) else "FAIL",
        "truth_boundary": {
            "classification_proves_runtime_function": False,
            "classification_proves_private_extremecraft_parity": False,
            "classification_is_diagnostic_only": True,
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Cannon failure classification: {report.get('scenario')}",
        "",
        f"Overall: **{report['overall_status']}**",
        "",
    ]
    for shot in report["shots"]:
        lines.extend([
            f"## Shot {shot['shot']}",
            "",
            f"Primary failure: **{shot.get('primary_failure') or 'none'}**",
            "",
            "Failures: " + (", ".join(shot["failures"]) if shot["failures"] else "none"),
            "",
        ])
        if shot["recommendations"]:
            lines.append("Next measured changes:")
            for recommendation in shot["recommendations"]:
                lines.append(f"- {recommendation}")
            lines.append("")
    lines.extend([
        "This report is diagnostic local-runtime evidence only. It does not prove private ExtremeCraft parity.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify CannonLab failures from run-summary and entity traces.")
    parser.add_argument("input", type=Path, help="run-summary.json or a directory containing one or more runs")
    parser.add_argument("--lane-tolerance", type=float, default=2.0)
    parser.add_argument("--fusion-tolerance", type=float, default=1.5)
    parser.add_argument("--tick-tolerance", type=int, default=1)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()

    if args.lane_tolerance < 0 or args.fusion_tolerance < 0 or args.tick_tolerance < 0:
        parser.error("tolerances must be non-negative")

    reports = [
        _classify_one(path, args.lane_tolerance, args.fusion_tolerance, args.tick_tolerance)
        for path in _find_run_summaries(args.input)
    ]
    payload: dict[str, Any] = reports[0] if len(reports) == 1 else {
        "schema_version": 1,
        "classification": "CANNONLAB_CAUSAL_FAILURE_BATCH_V1",
        "runs": reports,
        "overall_status": "PASS" if all(row["overall_status"] == "PASS" for row in reports) else "FAIL",
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        if len(reports) == 1:
            args.markdown_out.write_text(_markdown(reports[0]), encoding="utf-8")
        else:
            args.markdown_out.write_text("\n\n".join(_markdown(row) for row in reports), encoding="utf-8")
    return 0 if payload["overall_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
