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
from typing import Any


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


def signed_forward(
    direction: str,
    spawn: tuple[float, float, float],
    explosion: tuple[float, float, float],
) -> float:
    sx, _sy, sz = spawn
    ex, _ey, ez = explosion
    return {
        "EAST": ex - sx,
        "WEST": sx - ex,
        "SOUTH": ez - sz,
        "NORTH": sz - ez,
    }.get(direction.upper(), 0.0)


def point_box_distance(
    point: tuple[float, float, float],
    bounds: dict[str, Any] | None,
) -> float | None:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate CannonLab run evidence")
    parser.add_argument("results_root", type=Path)
    parser.add_argument("--expected-shots", type=int, required=True)
    parser.add_argument("--strict-single-tnt", action="store_true")
    parser.add_argument("--min-tnt-per-shot", type=int, default=1)
    parser.add_argument("--min-explosions-per-shot", type=int, default=1)
    parser.add_argument("--expected-lifetime", type=int)
    parser.add_argument("--lifetime-tolerance", type=int, default=1)
    parser.add_argument("--min-forward-travel", type=float)
    parser.add_argument("--max-target-miss-distance", type=float)
    parser.add_argument("--min-target-peak-destroyed", type=int)
    parser.add_argument("--min-target-peak-mean", type=float)
    parser.add_argument("--min-layer-breached", type=int)
    parser.add_argument("--min-embedded-payload-explosions", type=int)
    parser.add_argument("--max-unembedded-water-explosions", type=int)
    parser.add_argument("--min-contiguous-layers-before-first-regen", type=int)
    parser.add_argument("--require-all-layers-before-first-regen", action="store_true")
    parser.add_argument("--max-self-damage-blocks", type=int)
    parser.add_argument("--require-regen", action="store_true")
    parser.add_argument("--min-regen-restored", type=int, default=1)
    parser.add_argument("--min-durability-hits", type=int)
    parser.add_argument("--min-durability-breaks", type=int)
    parser.add_argument("--max-companion-missing", type=int)
    parser.add_argument("--min-companion-restored", type=int)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    if args.expected_shots < 1:
        fail("--expected-shots must be positive")
    if args.min_tnt_per_shot < 1:
        fail("--min-tnt-per-shot must be positive")
    if args.min_explosions_per_shot < 1:
        fail("--min-explosions-per-shot must be positive")
    if args.lifetime_tolerance < 0:
        fail("--lifetime-tolerance cannot be negative")
    if args.min_target_peak_mean is not None and args.min_target_peak_mean < 0:
        fail("--min-target-peak-mean cannot be negative")
    if args.max_self_damage_blocks is not None and args.max_self_damage_blocks < 0:
        fail("--max-self-damage-blocks cannot be negative")
    for name in (
        "min_embedded_payload_explosions",
        "max_unembedded_water_explosions",
        "min_contiguous_layers_before_first_regen",
    ):
        value = getattr(args, name)
        if value is not None and value < 0:
            fail(f"--{name.replace('_', '-')} cannot be negative")

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
    peak_destroyed_values: list[float] = []
    regen_restored_values: list[float] = []
    layer_breached_values: list[float] = []
    embedded_explosion_values: list[float] = []
    unembedded_water_values: list[float] = []
    layers_before_regen_values: list[float] = []
    regen_race_margin_values: list[float] = []
    self_damage_values: list[float] = []

    if args.require_regen and not bool((summary.get("regeneration") or {}).get("enabled")):
        failures.append("run summary does not report regeneration enabled")

    for shot in shots:
        number = shot.get("shot")
        if shot.get("error") is not None:
            failures.append(f"shot {number}: error={shot.get('error')}")
        if not shot.get("saw_payload"):
            failures.append(f"shot {number}: no TNT/falling-block payload observed")
        if int(shot.get("explosions", 0)) < args.min_explosions_per_shot:
            failures.append(
                f"shot {number}: explosions={shot.get('explosions', 0)} "
                f"below {args.min_explosions_per_shot}"
            )
        if int(shot.get("maximum_tnt_entities", 0)) < args.min_tnt_per_shot:
            failures.append(
                f"shot {number}: maximum_tnt_entities="
                f"{shot.get('maximum_tnt_entities', 0)} below {args.min_tnt_per_shot}"
            )
        if shot.get("finish_reason") not in {"quiet", "max_ticks"}:
            failures.append(
                f"shot {number}: unexpected finish_reason={shot.get('finish_reason')!r}"
            )

        peak_destroyed = int(shot.get("target_peak_destroyed", 0))
        regen_restored = int(shot.get("regen_blocks_restored", 0))
        max_layer = int(shot.get("max_layer_breached", 0))
        embedded_explosions = int(shot.get("embedded_payload_explosions", 0))
        unembedded_water = int(shot.get("unembedded_water_explosions", 0))
        contiguous_layers_before_regen = int(
            shot.get("contiguous_layers_breached_before_first_regen", 0)
        )
        all_layers_before_regen = bool(
            shot.get("all_layers_breached_before_first_regen", False)
        )
        regen_race_margin = int(shot.get("regen_race_margin_ticks", -1))
        self_damage = int(shot.get("self_damage_blocks", 0))
        durability_hits = int(shot.get("durability_hits", 0))
        durability_breaks = int(shot.get("durability_breaks", 0))
        companion_missing = int(shot.get("companion_cells_missing", 0))
        companion_restored = int(shot.get("companion_cells_restored", 0))
        peak_destroyed_values.append(float(peak_destroyed))
        regen_restored_values.append(float(regen_restored))
        layer_breached_values.append(float(max_layer))
        embedded_explosion_values.append(float(embedded_explosions))
        unembedded_water_values.append(float(unembedded_water))
        layers_before_regen_values.append(float(contiguous_layers_before_regen))
        if regen_race_margin >= 0:
            regen_race_margin_values.append(float(regen_race_margin))
        self_damage_values.append(float(self_damage))

        if (
            args.min_target_peak_destroyed is not None
            and peak_destroyed < args.min_target_peak_destroyed
        ):
            failures.append(
                f"shot {number}: target_peak_destroyed={peak_destroyed} "
                f"below {args.min_target_peak_destroyed}"
            )
        if args.min_layer_breached is not None and max_layer < args.min_layer_breached:
            failures.append(
                f"shot {number}: max_layer_breached={max_layer} "
                f"below {args.min_layer_breached}"
            )
        if (
            args.min_embedded_payload_explosions is not None
            and embedded_explosions < args.min_embedded_payload_explosions
        ):
            failures.append(
                f"shot {number}: embedded_payload_explosions={embedded_explosions} "
                f"below {args.min_embedded_payload_explosions}"
            )
        if (
            args.max_unembedded_water_explosions is not None
            and unembedded_water > args.max_unembedded_water_explosions
        ):
            failures.append(
                f"shot {number}: unembedded_water_explosions={unembedded_water} "
                f"above {args.max_unembedded_water_explosions}"
            )
        if (
            args.min_contiguous_layers_before_first_regen is not None
            and contiguous_layers_before_regen
            < args.min_contiguous_layers_before_first_regen
        ):
            failures.append(
                f"shot {number}: contiguous_layers_breached_before_first_regen="
                f"{contiguous_layers_before_regen} below "
                f"{args.min_contiguous_layers_before_first_regen}"
            )
        if args.require_all_layers_before_first_regen and not all_layers_before_regen:
            failures.append(
                f"shot {number}: all_layers_breached_before_first_regen=false"
            )
        if args.require_regen and regen_restored < args.min_regen_restored:
            failures.append(
                f"shot {number}: regen_blocks_restored={regen_restored} "
                f"below {args.min_regen_restored}"
            )
        if args.max_self_damage_blocks is not None and self_damage > args.max_self_damage_blocks:
            failures.append(
                f"shot {number}: self_damage_blocks={self_damage} "
                f"above {args.max_self_damage_blocks}"
            )
        if args.min_durability_hits is not None and durability_hits < args.min_durability_hits:
            failures.append(
                f"shot {number}: durability_hits={durability_hits} "
                f"below {args.min_durability_hits}"
            )
        if args.min_durability_breaks is not None and durability_breaks < args.min_durability_breaks:
            failures.append(
                f"shot {number}: durability_breaks={durability_breaks} "
                f"below {args.min_durability_breaks}"
            )
        if args.max_companion_missing is not None and companion_missing > args.max_companion_missing:
            failures.append(
                f"shot {number}: companion_cells_missing={companion_missing} "
                f"above {args.max_companion_missing}"
            )
        if args.min_companion_restored is not None and companion_restored < args.min_companion_restored:
            failures.append(
                f"shot {number}: companion_cells_restored={companion_restored} "
                f"below {args.min_companion_restored}"
            )

    if args.min_target_peak_mean is not None:
        observed_peak_mean = statistics.fmean(peak_destroyed_values)
        if observed_peak_mean < args.min_target_peak_mean:
            failures.append(
                f"target_peak_destroyed mean={observed_peak_mean:.3f} "
                f"below {args.min_target_peak_mean}"
            )

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
    forward_travel_values: list[float] = []
    target_miss_values: list[float] = []
    custom_events: Counter[str] = Counter()
    shot_details: list[dict[str, object]] = []

    direction = str(summary.get("target_direction", "EAST"))
    target_bounds = summary.get("target_bounds")

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
            event = row.get("event", "")
            if event == "ENTITY" and row.get("type") == "TNT":
                tnt_by_uuid[row.get("uuid", "")].append(row)
            if event in {"EXPLOSION", "BLOCK_EXPLOSION"}:
                explosions.append(row)
            if event not in {"ENTITY", "EXPLOSION", "BLOCK_EXPLOSION"}:
                custom_events[event] += 1

        shot_name = event_file.parent.name
        if not tnt_by_uuid:
            failures.append(f"{shot_name}: no TNT entity telemetry")
        if not explosions:
            failures.append(f"{shot_name}: no explosion telemetry")
        if args.strict_single_tnt and len(tnt_by_uuid) != 1:
            failures.append(f"{shot_name}: expected one TNT UUID, saw {len(tnt_by_uuid)}")
        if len(tnt_by_uuid) < args.min_tnt_per_shot:
            failures.append(
                f"{shot_name}: TNT UUIDs={len(tnt_by_uuid)} below {args.min_tnt_per_shot}"
            )
        if len(explosions) < args.min_explosions_per_shot:
            failures.append(
                f"{shot_name}: explosion events={len(explosions)} "
                f"below {args.min_explosions_per_shot}"
            )

        entity_details: list[dict[str, object]] = []
        shot_forward: list[float] = []
        shot_misses: list[float] = []

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
            spawn = (
                float(first["x"]),
                float(first["y"]),
                float(first["z"]),
            )
            spawn_x.append(spawn[0])
            spawn_y.append(spawn[1])
            spawn_z.append(spawn[2])
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
                failures.append(
                    f"{shot_name}: TNT {uid} has {len(bad_steps)} non-unit fuse steps"
                )

            matching_explosions = [row for row in explosions if row.get("uuid") == uid]
            lifetime = None
            forward = None
            miss = None
            if matching_explosions:
                explosion = min(matching_explosions, key=lambda row: int(row["tick"]))
                lifetime = int(explosion["tick"]) - ticks[0]
                lifetimes.append(lifetime)
                explosion_point = (
                    float(explosion["x"]),
                    float(explosion["y"]),
                    float(explosion["z"]),
                )
                explosion_x.append(explosion_point[0])
                explosion_y.append(explosion_point[1])
                explosion_z.append(explosion_point[2])
                forward = signed_forward(direction, spawn, explosion_point)
                shot_forward.append(forward)
                forward_travel_values.append(forward)
                miss = point_box_distance(explosion_point, target_bounds)
                if miss is not None:
                    shot_misses.append(miss)
                    target_miss_values.append(miss)

                if (
                    args.expected_lifetime is not None
                    and abs(lifetime - args.expected_lifetime) > args.lifetime_tolerance
                ):
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
                    "forward_travel": forward,
                    "target_miss_distance": miss,
                    "bad_steps": bad_steps[:5],
                }
            )

        best_forward = max(shot_forward) if shot_forward else None
        best_miss = min(shot_misses) if shot_misses else None
        if (
            args.min_forward_travel is not None
            and (best_forward is None or best_forward < args.min_forward_travel)
        ):
            failures.append(
                f"{shot_name}: best forward travel={best_forward} "
                f"below {args.min_forward_travel}"
            )
        if (
            args.max_target_miss_distance is not None
            and (best_miss is None or best_miss > args.max_target_miss_distance)
        ):
            failures.append(
                f"{shot_name}: closest target miss={best_miss} "
                f"above {args.max_target_miss_distance}"
            )

        shot_details.append(
            {
                "shot": shot_name,
                "tnt_uuids": len(tnt_by_uuid),
                "explosions": len(explosions),
                "best_forward_travel": best_forward,
                "closest_target_miss": best_miss,
                "entities": entity_details,
            }
        )

    if args.require_regen and custom_events["REGEN_RESTORE"] < args.expected_shots:
        failures.append(
            f"REGEN_RESTORE events={custom_events['REGEN_RESTORE']} "
            f"below one per requested shot"
        )

    fingerprint = {
        "status": "PASS" if not failures else "FAIL",
        "summary": str(summary_path),
        "scenario": summary.get("scenario"),
        "cannon_file": summary.get("cannon_file"),
        "target_type": summary.get("target_type"),
        "target_direction": direction,
        "target_bounds": target_bounds,
        "shots": len(shots),
        "total_explosions": sum(int(shot.get("explosions", 0)) for shot in shots),
        "telemetry_files": len(event_files),
        "tnt_uuid_count": len(seen_uuids),
        "first_fuse_counts": dict(Counter(first_fuses)),
        "lifetime_ticks": numeric_stats([float(value) for value in lifetimes]),
        "forward_travel": numeric_stats(forward_travel_values),
        "target_miss_distance": numeric_stats(target_miss_values),
        "target_peak_destroyed": numeric_stats(peak_destroyed_values),
        "regen_blocks_restored": numeric_stats(regen_restored_values),
        "max_layer_breached": numeric_stats(layer_breached_values),
        "embedded_payload_explosions": numeric_stats(embedded_explosion_values),
        "unembedded_water_explosions": numeric_stats(unembedded_water_values),
        "contiguous_layers_breached_before_first_regen": numeric_stats(
            layers_before_regen_values
        ),
        "regen_race_margin_ticks": numeric_stats(regen_race_margin_values),
        "self_damage_blocks": numeric_stats(self_damage_values),
        "custom_event_counts": dict(custom_events),
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
