#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


def fail(message: str) -> None:
    print(f"CannonLab assertion failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def numeric_stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "spread": max(values) - min(values),
    }


def finite_row(row: dict[str, str]) -> bool:
    try:
        return all(
            math.isfinite(float(row[key]))
            for key in ("tick", "x", "y", "z", "vx", "vy", "vz", "fuse")
        )
    except (KeyError, TypeError, ValueError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate CannonLab run evidence")
    parser.add_argument("results_root", type=Path)
    parser.add_argument("--expected-shots", type=int, required=True)
    parser.add_argument("--strict-single-tnt", action="store_true")
    parser.add_argument("--expected-lifetime", type=int, default=79)
    parser.add_argument("--lifetime-tolerance", type=int, default=1)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    summaries = sorted(
        args.results_root.rglob("run-summary.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not summaries:
        fail(f"no run-summary.json below {args.results_root}")

    summary_path = summaries[0]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    if summary.get("finish_reason") != "complete":
        fail(f"finish_reason={summary.get('finish_reason')!r}")
    if summary.get("shots_requested") != args.expected_shots:
        fail(f"shots_requested={summary.get('shots_requested')} expected={args.expected_shots}")
    if summary.get("shots_completed") != args.expected_shots:
        fail(f"shots_completed={summary.get('shots_completed')} expected={args.expected_shots}")

    shots = summary.get("shots")
    if not isinstance(shots, list) or len(shots) != args.expected_shots:
        fail("shot list is missing or has the wrong length")

    failures: list[str] = []
    for shot in shots:
        number = shot.get("shot")
        if shot.get("error") is not None:
            failures.append(f"shot {number}: error={shot.get('error')}")
        if not shot.get("saw_payload"):
            failures.append(f"shot {number}: no TNT/falling-block payload observed")
        if int(shot.get("explosions", 0)) < 1:
            failures.append(f"shot {number}: no explosion observed")
        if shot.get("finish_reason") not in {"quiet", "max_ticks"}:
            failures.append(f"shot {number}: unexpected finish_reason={shot.get('finish_reason')!r}")

    event_files = sorted(summary_path.parent.rglob("events.csv"))
    if len(event_files) != args.expected_shots:
        failures.append(f"events.csv files={len(event_files)} expected={args.expected_shots}")

    seen_uuids: set[str] = set()
    first_fuses: list[int] = []
    lifetimes: list[int] = []
    spawn_x: list[float] = []
    spawn_y: list[float] = []
    spawn_z: list[float] = []
    spawn_vx: list[float] = []
    spawn_vy: list[float] = []
    spawn_vz: list[float] = []
    explosion_x: list[float] = []
    explosion_y: list[float] = []
    explosion_z: list[float] = []
    shot_details: list[dict[str, object]] = []

    for event_file in event_files:
        rows = list(csv.DictReader(event_file.open("r", encoding="utf-8", newline="")))
        if not rows:
            failures.append(f"{event_file}: contains no telemetry rows")
            continue
        invalid_rows = sum(1 for row in rows if not finite_row(row))
        if invalid_rows:
            failures.append(f"{event_file}: {invalid_rows} invalid numeric rows")

        tnt_by_uuid: dict[str, list[dict[str, str]]] = defaultdict(list)
        explosions: list[dict[str, str]] = []
        for row in rows:
            if row.get("event") == "ENTITY" and row.get("type") == "TNT":
                tnt_by_uuid[row.get("uuid", "")].append(row)
            if row.get("event") in {"EXPLOSION", "BLOCK_EXPLOSION"}:
                explosions.append(row)

        shot_name = event_file.parent.name
        if not tnt_by_uuid:
            failures.append(f"{shot_name}: no TNT entity telemetry")
        if not explosions:
            failures.append(f"{shot_name}: no explosion telemetry")
        if args.strict_single_tnt and len(tnt_by_uuid) != 1:
            failures.append(f"{shot_name}: expected one TNT UUID, saw {len(tnt_by_uuid)}")

        entity_details: list[dict[str, object]] = []
        for uid, entity_rows in tnt_by_uuid.items():
            if not uid:
                failures.append(f"{shot_name}: TNT row has blank UUID")
                continue
            if uid in seen_uuids:
                failures.append(f"{shot_name}: reused TNT UUID {uid}")
            seen_uuids.add(uid)
            entity_rows.sort(key=lambda row: int(row["tick"]))
            ticks = [int(row["tick"]) for row in entity_rows]
            fuses = [int(row["fuse"]) for row in entity_rows]
            first = entity_rows[0]
            first_fuses.append(fuses[0])
            spawn_x.append(float(first["x"]))
            spawn_y.append(float(first["y"]))
            spawn_z.append(float(first["z"]))
            spawn_vx.append(float(first["vx"]))
            spawn_vy.append(float(first["vy"]))
            spawn_vz.append(float(first["vz"]))

            bad_steps = []
            for index in range(1, len(entity_rows)):
                delta_tick = ticks[index] - ticks[index - 1]
                delta_fuse = fuses[index] - fuses[index - 1]
                if delta_tick != 1 or delta_fuse != -1:
                    bad_steps.append(
                        {
                            "from_tick": ticks[index - 1],
                            "to_tick": ticks[index],
                            "from_fuse": fuses[index - 1],
                            "to_fuse": fuses[index],
                        }
                    )
            if bad_steps:
                failures.append(f"{shot_name}: TNT {uid} has {len(bad_steps)} non-unit fuse steps")

            matching_explosions = [row for row in explosions if row.get("uuid") == uid]
            lifetime = None
            if matching_explosions:
                explosion = min(matching_explosions, key=lambda row: int(row["tick"]))
                lifetime = int(explosion["tick"]) - ticks[0]
                lifetimes.append(lifetime)
                explosion_x.append(float(explosion["x"]))
                explosion_y.append(float(explosion["y"]))
                explosion_z.append(float(explosion["z"]))
                if abs(lifetime - args.expected_lifetime) > args.lifetime_tolerance:
                    failures.append(
                        f"{shot_name}: TNT lifetime {lifetime} outside "
                        f"{args.expected_lifetime}±{args.lifetime_tolerance}"
                    )
            else:
                failures.append(f"{shot_name}: TNT {uid} has no matching explosion event")

            entity_details.append(
                {
                    "uuid": uid,
                    "first_tick": ticks[0],
                    "first_fuse": fuses[0],
                    "last_entity_tick": ticks[-1],
                    "last_fuse": fuses[-1],
                    "entity_samples": len(entity_rows),
                    "lifetime_ticks": lifetime,
                    "bad_steps": bad_steps[:5],
                }
            )

        shot_details.append(
            {
                "shot": shot_name,
                "tnt_uuids": len(tnt_by_uuid),
                "explosions": len(explosions),
                "entities": entity_details,
            }
        )

    fingerprint = {
        "status": "PASS" if not failures else "FAIL",
        "summary": str(summary_path),
        "shots": len(shots),
        "total_explosions": sum(int(shot.get("explosions", 0)) for shot in shots),
        "telemetry_files": len(event_files),
        "tnt_uuid_count": len(seen_uuids),
        "first_fuse_counts": dict(Counter(first_fuses)),
        "lifetime_ticks": numeric_stats([float(value) for value in lifetimes]),
        "spawn_position": {
            "x": numeric_stats(spawn_x),
            "y": numeric_stats(spawn_y),
            "z": numeric_stats(spawn_z),
        },
        "spawn_velocity": {
            "x": numeric_stats(spawn_vx),
            "y": numeric_stats(spawn_vy),
            "z": numeric_stats(spawn_vz),
        },
        "explosion_position": {
            "x": numeric_stats(explosion_x),
            "y": numeric_stats(explosion_y),
            "z": numeric_stats(explosion_z),
        },
        "errors": failures,
        "shot_details": shot_details,
    }

    rendered = json.dumps(fingerprint, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if failures:
        fail("; ".join(failures))


if __name__ == "__main__":
    main()
