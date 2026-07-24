#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable

TNT_TYPES = {"TNT", "PRIMED_TNT", "TNT_PRIMED"}
FALLING_TYPES = {"FALLING_BLOCK"}
DURABILITY_HIT_RE = re.compile(r"remaining=(\d+)/(\d+)")
DURABILITY_BREAK_RE = re.compile(r"hits=(\d+)")


@dataclass(frozen=True)
class BreachContract:
    name: str
    min_shots: int = 1
    required_material: str | None = None
    required_target_type: str | None = None
    require_target_damage: bool = False
    min_target_breaks: int = 0
    expected_hits_to_break: int | None = None
    require_direct_durability_sequence: bool = False
    min_embedded_payload_explosions: int = 0
    max_unembedded_water_explosions: int = 2**31 - 1
    require_falling_payload: bool = False
    min_connected_opening: int = 0
    min_contiguous_layers: int = 0
    require_regeneration: bool = False
    require_positive_regen_margin: bool = False
    max_self_damage_blocks: int = 2**31 - 1
    min_dispenser_survival_ratio: float = 0.0
    min_usable_breach_rate: float = 1.0
    min_lane_repeatability: float = 0.0


PROFILES: dict[str, BreachContract] = {
    "diagnostic": BreachContract(name="diagnostic"),
    "dry-obsidian": BreachContract(
        name="dry-obsidian",
        required_material="OBSIDIAN",
        require_target_damage=True,
        min_target_breaks=1,
        expected_hits_to_break=4,
        require_direct_durability_sequence=True,
        min_connected_opening=1,
        min_contiguous_layers=1,
        max_self_damage_blocks=0,
        min_dispenser_survival_ratio=1.0,
    ),
    "watered-obsidian": BreachContract(
        name="watered-obsidian",
        required_material="OBSIDIAN",
        required_target_type="WATERED",
        require_target_damage=True,
        min_target_breaks=1,
        expected_hits_to_break=4,
        require_direct_durability_sequence=True,
        min_embedded_payload_explosions=1,
        max_unembedded_water_explosions=0,
        require_falling_payload=True,
        min_connected_opening=1,
        min_contiguous_layers=1,
        max_self_damage_blocks=0,
        min_dispenser_survival_ratio=1.0,
    ),
    "regen-course": BreachContract(
        name="regen-course",
        require_target_damage=True,
        min_target_breaks=1,
        min_connected_opening=1,
        min_contiguous_layers=2,
        require_regeneration=True,
        require_positive_regen_margin=True,
        max_self_damage_blocks=0,
        min_dispenser_survival_ratio=0.99,
    ),
    "raid-course": BreachContract(
        name="raid-course",
        min_shots=5,
        require_target_damage=True,
        min_target_breaks=1,
        require_falling_payload=True,
        min_connected_opening=1,
        min_contiguous_layers=2,
        max_self_damage_blocks=0,
        min_dispenser_survival_ratio=0.99,
        min_usable_breach_rate=1.0,
        min_lane_repeatability=0.8,
    ),
}


DIAGNOSIS_GUIDANCE: dict[str, dict[str, str]] = {
    "payload-axis-mismatch": {
        "meaning": "The falling payload's dominant movement axis disagrees with the target direction.",
        "next": "Fix schematic rotation, mirror, target binding, or the side of the propulsion explosion before changing timing ratios.",
    },
    "falling-payload-stalled": {
        "meaning": "Falling payload exists but receives too little forward displacement to enter the wall corridor.",
        "next": "Inspect the source explosion relative to the payload and repair the forward impulse interface before adding nuke TNT.",
    },
    "falling-payload-backfire": {
        "meaning": "The falling payload travels materially toward the cannon instead of the target.",
        "next": "Stop the run and repair power-bank side, collision alignment, or rotation. More power will amplify the wrong vector.",
    },
    "tnt-only-target-contact": {
        "meaning": "TNT reaches the target but no falling payload overlaps the target-contact explosion.",
        "next": "Sweep one evidence-selected sand-release, hammer, stopper, or one-shot timing site around the target TNT arrival. Do not sweep the whole machine.",
    },
    "payload-near-wall-timing-gap": {
        "meaning": "Falling payload approaches the target but is not co-located when the TNT explodes.",
        "next": "Run a bounded tick sweep on the last payload or nuke timing interface and rank minimum TNT-to-falling distance at target contact.",
    },
    "payload-at-wall-without-target-tnt": {
        "meaning": "The falling payload reaches the target corridor, but no TNT explosion reaches that corridor.",
        "next": "Repair the projectile/hybrid TNT launch cohort. Do not change the proven sand propulsion geometry.",
    },
    "payload-tnt-arrival-desynchronized": {
        "meaning": "Both payload and TNT reach the target corridor, but their measured arrival ticks do not overlap.",
        "next": "Sweep only the projectile/hybrid TNT branch around the measured arrival gap while preserving the sand and main-power cohorts.",
    },
    "propulsion-impulse-off-axis": {
        "meaning": "The strongest measured explosion-to-falling-block impulse points away from the target axis.",
        "next": "Repair the source explosion side, chamber orientation, or schematic rotation. Timing sweeps cannot fix a propulsion vector aimed sideways.",
    },
    "propulsion-impulse-reversed": {
        "meaning": "The strongest measured impulse pushes the falling payload back toward the cannon.",
        "next": "Stop adding power. Correct the source/recipient ordering, blast side, or collision cell before another runtime sweep.",
    },
    "durability-hit-scatter": {
        "meaning": "Durability pressure is spread across cells instead of concentrating enough hits on one protected block.",
        "next": "Tighten guider, stack alignment, and repeated impact coordinates before increasing volley count.",
    },
    "native-hit-sequence-unobserved": {
        "meaning": "A native durable block broke, but intermediate per-cell hit decrements were not directly recorded.",
        "next": "Capture native durability callbacks or a calibrated target-contact sequence before claiming exact hit concentration.",
    },
    "no-connected-opening": {
        "meaning": "Destroyed target cells do not form the required usable aperture.",
        "next": "Align impacts into one connected lane. Raw destroyed-block totals are not enough.",
    },
    "no-contiguous-breach-lane": {
        "meaning": "Damage appears on multiple layers but not through the same cross-section lane from the front layer onward.",
        "next": "Stabilize the payload trajectory and repeated impact height before testing deeper wall courses.",
    },
    "regen-wins": {
        "meaning": "The course restores before the required contiguous breach is completed.",
        "next": "First prove one clean embedded breach, then tune cadence or a second attributed impact package against the measured restore window.",
    },
    "self-damage": {
        "meaning": "The cannon loses blocks while firing.",
        "next": "Repair water containment, chamber clearance, fuse separation, and reset order before adding power.",
    },
    "dispenser-loss": {
        "meaning": "One or more dispenser banks do not survive the shot.",
        "next": "Treat this as a cannon failure. Identify the first internal explosion or fluid loss and preserve the bank topology while repairing it.",
    },
    "fake-green-contract": {
        "meaning": "The original scenario reported contract_pass while the wall-breach contract still fails.",
        "next": "Tighten the scenario acceptance fields. Never promote a flight-only or explosion-only green result as a breach.",
    },
    "target-contact-without-damage": {
        "meaning": "Target-contact explosions occur but no target cell is actually removed.",
        "next": "Verify durable-hit concentration, embedded payload overlap, explosion center, and server durability profile.",
    },
    "range-underreach": {
        "meaning": "The measured payload or TNT travel does not reach the declared target distance.",
        "next": "Calibrate the propulsion stage and adjustment first. Do not compensate with wall-side modules.",
    },
}


def latest_summary(path: Path) -> Path:
    if path.is_file():
        if path.name != "run-summary.json":
            raise ValueError(f"expected run-summary.json, got {path}")
        return path.resolve()
    summaries = sorted(
        path.rglob("run-summary.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not summaries:
        raise FileNotFoundError(f"no run-summary.json below {path}")
    return summaries[0].resolve()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def point(row: dict[str, Any]) -> tuple[float, float, float]:
    return as_float(row.get("x")), as_float(row.get("y")), as_float(row.get("z"))


def block_point(row: dict[str, Any]) -> tuple[int, int, int]:
    return tuple(int(round(value)) for value in point(row))  # type: ignore[return-value]


def direction_vector(direction: str) -> tuple[int, int, int]:
    return {
        "EAST": (1, 0, 0),
        "WEST": (-1, 0, 0),
        "SOUTH": (0, 0, 1),
        "NORTH": (0, 0, -1),
    }.get(direction.upper(), (1, 0, 0))


def forward_coordinate(position: tuple[int, int, int], direction: str) -> int:
    x, _y, z = position
    return {
        "EAST": x,
        "WEST": -x,
        "SOUTH": z,
        "NORTH": -z,
    }.get(direction.upper(), x)


def cross_lane(position: tuple[int, int, int], direction: str) -> tuple[int, int]:
    x, y, z = position
    return (y, z) if direction.upper() in {"EAST", "WEST"} else (x, y)


def point_box_distance(
    position: tuple[float, float, float],
    bounds: dict[str, Any] | None,
) -> float | None:
    if not isinstance(bounds, dict):
        return None
    required = ("min_x", "min_y", "min_z", "max_x", "max_y", "max_z")
    if any(key not in bounds for key in required):
        return None
    x, y, z = position
    dx = max(as_float(bounds["min_x"]) - x, 0.0, x - as_float(bounds["max_x"]) - 1.0)
    dy = max(as_float(bounds["min_y"]) - y, 0.0, y - as_float(bounds["max_y"]) - 1.0)
    dz = max(as_float(bounds["min_z"]) - z, 0.0, z - as_float(bounds["max_z"]) - 1.0)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def expected_layer_planes(
    summary: dict[str, Any],
    course: dict[str, Any] | None,
) -> tuple[dict[int, int], list[dict[str, Any]]]:
    direction = str(summary.get("target_direction", "EAST")).upper()
    origin = summary.get("arena_origin") or {}
    origin_x = as_int(origin.get("x"))
    origin_z = as_int(origin.get("z"))
    stages = (course or {}).get("stages")
    if not isinstance(stages, list) or not stages:
        stages = [{
            "index": 0,
            "name": "legacy-target",
            "start_distance": as_int(summary.get("target_distance")),
            "layers": as_int(summary.get("target_layers"), 1),
            "spacing": as_int(summary.get("target_spacing"), 3),
        }]

    plane_to_layer: dict[int, int] = {}
    rows: list[dict[str, Any]] = []
    global_layer = 0
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        start = as_int(stage.get("start_distance"))
        layers = max(0, as_int(stage.get("layers")))
        spacing = max(1, as_int(stage.get("spacing"), 1))
        for local_layer in range(layers):
            distance = start + local_layer * spacing
            if direction == "EAST":
                plane = origin_x + distance
            elif direction == "WEST":
                plane = -(origin_x - distance)
            elif direction == "SOUTH":
                plane = origin_z + distance
            else:
                plane = -(origin_z - distance)
            plane_to_layer[plane] = global_layer
            rows.append({
                "global_layer": global_layer,
                "stage_index": as_int(stage.get("index")),
                "stage_name": str(stage.get("name", f"stage-{as_int(stage.get('index'))}")),
                "local_layer": local_layer,
                "forward_plane": plane,
                "distance": distance,
            })
            global_layer += 1
    return plane_to_layer, rows


def largest_component(points: set[tuple[int, int]]) -> dict[str, Any]:
    if not points:
        return {"size": 0, "points": [], "extent_a": 0, "extent_b": 0}
    remaining = set(points)
    components: list[set[tuple[int, int]]] = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue = deque([start])
        component = {start}
        while queue:
            a, b = queue.popleft()
            for neighbour in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    component.add(neighbour)
                    queue.append(neighbour)
        components.append(component)
    winner = max(components, key=lambda item: (len(item), sorted(item)))
    aa = [item[0] for item in winner]
    bb = [item[1] for item in winner]
    return {
        "size": len(winner),
        "points": [list(item) for item in sorted(winner)],
        "extent_a": max(aa) - min(aa) + 1,
        "extent_b": max(bb) - min(bb) + 1,
    }


def parse_durability(
    events: list[dict[str, str]],
) -> dict[str, Any]:
    by_cell: dict[tuple[int, int, int], dict[str, Any]] = defaultdict(
        lambda: {"hits": [], "breaks": [], "target_destroyed": []}
    )
    for row in sorted(events, key=lambda item: as_int(item.get("tick"))):
        event = str(row.get("event", ""))
        if event not in {"DURABILITY_HIT", "DURABILITY_BREAK", "TARGET_DESTROYED"}:
            continue
        cell = block_point(row)
        if event == "DURABILITY_HIT":
            match = DURABILITY_HIT_RE.search(str(row.get("type", "")))
            by_cell[cell]["hits"].append({
                "tick": as_int(row.get("tick")),
                "remaining": as_int(match.group(1)) if match else None,
                "full": as_int(match.group(2)) if match else None,
                "type": row.get("type"),
            })
        elif event == "DURABILITY_BREAK":
            match = DURABILITY_BREAK_RE.search(str(row.get("type", "")))
            by_cell[cell]["breaks"].append({
                "tick": as_int(row.get("tick")),
                "hits": as_int(match.group(1)) if match else None,
                "type": row.get("type"),
            })
        else:
            by_cell[cell]["target_destroyed"].append({
                "tick": as_int(row.get("tick")),
                "type": row.get("type"),
            })

    direct_sequences = 0
    direct_breaks = 0
    target_destroyed_cells = 0
    total_hit_events = 0
    max_pressure = 0
    cells: list[dict[str, Any]] = []
    for cell, evidence in sorted(by_cell.items()):
        hits = evidence["hits"]
        breaks = evidence["breaks"]
        destroyed = evidence["target_destroyed"]
        total_hit_events += len(hits)
        target_destroyed_cells += int(bool(destroyed))
        direct_breaks += len(breaks)
        max_pressure = max(max_pressure, len(hits) + len(breaks))
        complete = False
        for break_event in breaks:
            full = break_event.get("hits")
            if not isinstance(full, int) or full < 1:
                continue
            prior = [
                hit.get("remaining")
                for hit in hits
                if as_int(hit.get("tick")) <= as_int(break_event.get("tick"))
            ]
            expected = list(range(full - 1, 0, -1))
            if not expected or prior[-len(expected):] == expected:
                complete = True
                break
        if complete:
            direct_sequences += 1
        cells.append({
            "position": list(cell),
            "hit_events": hits,
            "break_events": breaks,
            "target_destroyed_events": destroyed,
            "direct_sequence_complete": complete,
            "pressure_events": len(hits) + len(breaks),
        })

    concentration = (
        max_pressure / max(1, total_hit_events + direct_breaks)
        if total_hit_events + direct_breaks > 0
        else None
    )
    return {
        "cells": cells,
        "cell_count": len(cells),
        "direct_hit_events": total_hit_events,
        "direct_break_events": direct_breaks,
        "direct_complete_sequences": direct_sequences,
        "target_destroyed_cells": target_destroyed_cells,
        "max_pressure_events_one_cell": max_pressure,
        "pressure_concentration": concentration,
    }


def payload_motion(
    events: list[dict[str, str]],
    direction: str,
    target_bounds: dict[str, Any] | None,
) -> dict[str, Any]:
    target = direction_vector(direction)
    trajectories: dict[str, list[dict[str, str]]] = defaultdict(list)
    explosions = [
        row
        for row in events
        if row.get("event") in {"EXPLOSION", "BLOCK_EXPLOSION"}
        and str(row.get("type", "")).upper() in TNT_TYPES
    ]
    for row in events:
        if row.get("event") == "ENTITY" and str(row.get("type", "")).upper() in FALLING_TYPES:
            uid = str(row.get("uuid", ""))
            if uid:
                trajectories[uid].append(row)

    entities: list[dict[str, Any]] = []
    for uid, rows in trajectories.items():
        rows.sort(key=lambda item: as_int(item.get("tick")))
        start = point(rows[0])
        max_forward = -math.inf
        min_forward = math.inf
        best_target_distance: float | None = None
        closest_target_sample: dict[str, Any] | None = None
        furthest_point = start
        furthest_distance = -1.0
        impulses: list[dict[str, Any]] = []
        previous_velocity: tuple[float, float, float] | None = None

        for row in rows:
            current = point(row)
            velocity = (
                as_float(row.get("vx")),
                as_float(row.get("vy")),
                as_float(row.get("vz")),
            )
            delta = tuple(current[index] - start[index] for index in range(3))
            forward = sum(delta[index] * target[index] for index in range(3))
            max_forward = max(max_forward, forward)
            min_forward = min(min_forward, forward)
            displacement = math.dist(start, current)
            if displacement > furthest_distance:
                furthest_distance = displacement
                furthest_point = current
            distance = point_box_distance(current, target_bounds)
            if distance is not None:
                if best_target_distance is None or distance < best_target_distance:
                    best_target_distance = distance
                    closest_target_sample = {
                        "tick": as_int(row.get("tick")),
                        "position": list(current),
                        "velocity": list(velocity),
                        "distance": distance,
                    }

            if previous_velocity is not None:
                delta_velocity = tuple(
                    velocity[index] - previous_velocity[index]
                    for index in range(3)
                )
                impulse_magnitude = math.sqrt(
                    sum(value * value for value in delta_velocity)
                )
                if impulse_magnitude >= 0.08:
                    tick = as_int(row.get("tick"))
                    nearby: list[tuple[float, int, tuple[float, float, float]]] = []
                    for explosion in explosions:
                        explosion_tick = as_int(explosion.get("tick"))
                        if abs(explosion_tick - tick) > 1:
                            continue
                        explosion_position = point(explosion)
                        distance_to_recipient = math.dist(current, explosion_position)
                        if distance_to_recipient <= 8.0:
                            nearby.append(
                                (distance_to_recipient, explosion_tick, explosion_position)
                            )
                    nearby.sort(key=lambda item: (item[0], item[1], item[2]))
                    target_cosine = sum(
                        delta_velocity[index] * target[index]
                        for index in range(3)
                    ) / impulse_magnitude
                    impulses.append({
                        "tick": tick,
                        "recipient_position": list(current),
                        "velocity_before": list(previous_velocity),
                        "velocity_after": list(velocity),
                        "delta_velocity": list(delta_velocity),
                        "magnitude": impulse_magnitude,
                        "target_axis_cosine": target_cosine,
                        "nearest_source_explosion": (
                            {
                                "distance": nearby[0][0],
                                "tick": nearby[0][1],
                                "position": list(nearby[0][2]),
                            }
                            if nearby
                            else None
                        ),
                    })
            previous_velocity = velocity

        net = tuple(furthest_point[index] - start[index] for index in range(3))
        net_length = math.sqrt(sum(value * value for value in net))
        cosine = (
            sum(net[index] * target[index] for index in range(3)) / net_length
            if net_length > 1.0e-9
            else None
        )
        entities.append({
            "uuid": uid,
            "samples": len(rows),
            "spawn": list(start),
            "furthest": list(furthest_point),
            "maximum_forward_displacement": max_forward,
            "maximum_reverse_displacement": -min_forward,
            "furthest_displacement": furthest_distance,
            "target_axis_cosine": cosine,
            "closest_target_distance": best_target_distance,
            "closest_target_sample": closest_target_sample,
            "impulses": sorted(
                impulses,
                key=lambda item: (
                    -as_float(item.get("magnitude")),
                    as_int(item.get("tick")),
                ),
            )[:20],
        })

    entities.sort(
        key=lambda item: (
            -as_float(item.get("maximum_forward_displacement"), -1.0e9),
            as_float(item.get("closest_target_distance"), 1.0e9),
            str(item.get("uuid")),
        )
    )
    best_forward = max(
        (as_float(item.get("maximum_forward_displacement"), -math.inf) for item in entities),
        default=None,
    )
    worst_reverse = max(
        (as_float(item.get("maximum_reverse_displacement"), 0.0) for item in entities),
        default=None,
    )
    closest = min(
        (
            as_float(item.get("closest_target_distance"), math.inf)
            for item in entities
            if item.get("closest_target_distance") is not None
        ),
        default=None,
    )
    closest_entity = min(
        (
            item
            for item in entities
            if item.get("closest_target_distance") is not None
        ),
        key=lambda item: as_float(item.get("closest_target_distance"), math.inf),
        default=None,
    )
    dominant = max(
        entities,
        key=lambda item: as_float(item.get("furthest_displacement")),
        default=None,
    )
    measured_impulses = [
        impulse
        for entity in entities
        for impulse in entity.get("impulses", [])
        if impulse.get("nearest_source_explosion") is not None
    ]
    strongest_impulse = max(
        measured_impulses,
        key=lambda item: as_float(item.get("magnitude")),
        default=None,
    )
    return {
        "entity_count": len(entities),
        "maximum_forward_displacement": best_forward,
        "maximum_reverse_displacement": worst_reverse,
        "closest_target_distance": closest,
        "closest_target_sample": (
            closest_entity.get("closest_target_sample") if closest_entity else None
        ),
        "dominant_target_axis_cosine": dominant.get("target_axis_cosine") if dominant else None,
        "dominant_entity": dominant,
        "strongest_attributed_impulse": strongest_impulse,
        "attributed_impulse_count": len(measured_impulses),
        "entities": entities[:40],
    }


def target_damage_geometry(
    events: list[dict[str, str]],
    summary: dict[str, Any],
    course: dict[str, Any] | None,
) -> dict[str, Any]:
    direction = str(summary.get("target_direction", "EAST")).upper()
    plane_map, layer_rows = expected_layer_planes(summary, course)
    restore_ticks = [
        as_int(row.get("tick"))
        for row in events
        if row.get("event") == "REGEN_RESTORE"
    ]
    first_restore = min(restore_ticks) if restore_ticks else None
    destroyed_rows = [row for row in events if row.get("event") == "TARGET_DESTROYED"]
    before_restore = [
        row for row in destroyed_rows
        if first_restore is None or as_int(row.get("tick")) < first_restore
    ]

    layer_points: dict[int, set[tuple[int, int]]] = defaultdict(set)
    unknown_planes: list[dict[str, Any]] = []
    for row in before_restore:
        position = block_point(row)
        plane = forward_coordinate(position, direction)
        layer = plane_map.get(plane)
        if layer is None:
            unknown_planes.append({"position": list(position), "forward_plane": plane})
            continue
        layer_points[layer].add(cross_lane(position, direction))

    layer_reports = []
    for layer in range(len(layer_rows)):
        component = largest_component(layer_points.get(layer, set()))
        layer_reports.append({
            **layer_rows[layer],
            "destroyed_cells_before_first_restore": len(layer_points.get(layer, set())),
            "largest_connected_opening": component,
        })

    lane_layers: dict[tuple[int, int], set[int]] = defaultdict(set)
    for layer, points in layer_points.items():
        for lane in points:
            lane_layers[lane].add(layer)
    lane_reports = []
    for lane, layers in sorted(lane_layers.items()):
        contiguous = 0
        while contiguous in layers:
            contiguous += 1
        lane_reports.append({
            "lane": list(lane),
            "layers": sorted(layers),
            "contiguous_from_front": contiguous,
        })
    lane_reports.sort(key=lambda item: (-as_int(item["contiguous_from_front"]), item["lane"]))
    dominant_lane = lane_reports[0] if lane_reports else None
    largest_opening = max(
        (as_int(item["largest_connected_opening"]["size"]) for item in layer_reports),
        default=0,
    )
    return {
        "first_regen_restore_tick": first_restore,
        "target_destroyed_events": len(destroyed_rows),
        "target_destroyed_before_first_restore": len(before_restore),
        "expected_layer_count": len(layer_rows),
        "damaged_layer_count_before_first_restore": len(layer_points),
        "largest_connected_opening": largest_opening,
        "best_contiguous_lane_layers": as_int(dominant_lane.get("contiguous_from_front")) if dominant_lane else 0,
        "dominant_lane": dominant_lane,
        "layers": layer_reports,
        "lanes": lane_reports[:100],
        "unknown_target_planes": unknown_planes,
    }


def breach_explosions(rows: list[dict[str, str]]) -> dict[str, Any]:
    tnt = [row for row in rows if str(row.get("entity_type", "")).upper() in TNT_TYPES]
    target = [row for row in tnt if as_bool(row.get("target_contact"))]
    embedded = [row for row in target if as_bool(row.get("falling_overlap_evidence"))]
    water = [row for row in target if as_bool(row.get("center_water_contact"))]
    unembedded_water = [
        row for row in target
        if as_bool(row.get("center_water_contact"))
        and not as_bool(row.get("falling_overlap_evidence"))
    ]
    falling_distances = [
        as_float(row.get("falling_distance"))
        for row in target
        if as_float(row.get("falling_distance"), -1.0) >= 0.0
    ]
    return {
        "all_rows": len(rows),
        "tnt_explosions": len(tnt),
        "target_contact_explosions": len(target),
        "target_contact_rate": len(target) / len(tnt) if tnt else 0.0,
        "embedded_payload_explosions": len(embedded),
        "water_contact_explosions": len(water),
        "unembedded_water_explosions": len(unembedded_water),
        "nearest_falling_distance": min(falling_distances) if falling_distances else None,
        "median_falling_distance": statistics.median(falling_distances) if falling_distances else None,
        "target_contact_rows": target[:100],
    }


def dispenser_survival(shot: dict[str, Any]) -> float | None:
    initial = as_int(shot.get("cannon_initial_dispensers"))
    remaining = as_int(shot.get("cannon_remaining_dispensers"))
    if initial <= 0:
        return None
    return remaining / initial


def rank_diagnoses(codes: Iterable[str], shot_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter(codes)
    output = []
    for code, count in counter.most_common():
        guidance = DIAGNOSIS_GUIDANCE.get(code, {})
        output.append({
            "code": code,
            "shots": count,
            "meaning": guidance.get("meaning", "The wall-breach contract observed this failure."),
            "next_action": guidance.get("next", "Inspect the cited shot evidence and change one causal variable."),
            "evidence_shots": [
                report["shot"]
                for report in shot_reports
                if code in report.get("diagnosis_codes", [])
            ],
        })
    return output


def analyze_shot(
    summary_path: Path,
    summary: dict[str, Any],
    course: dict[str, Any] | None,
    shot: dict[str, Any],
    contract: BreachContract,
) -> dict[str, Any]:
    number = as_int(shot.get("shot"))
    shot_dir = summary_path.parent / f"shot-{number:03d}"
    events_path = shot_dir / "events.csv"
    breach_path = shot_dir / "breach-events.csv"
    events = read_csv(events_path)
    breach_rows = read_csv(breach_path)
    direction = str(summary.get("target_direction", "EAST")).upper()

    failures: list[str] = []
    diagnoses: list[str] = []
    warnings: list[str] = []
    if not events_path.is_file():
        failures.append("events_missing")
    if (
        contract.min_embedded_payload_explosions > 0
        or contract.max_unembedded_water_explosions < 2**31 - 1
    ) and not breach_path.is_file():
        failures.append("breach_events_missing")

    durability = parse_durability(events)
    geometry = target_damage_geometry(events, summary, course)
    explosions = breach_explosions(breach_rows)
    motion = payload_motion(events, direction, summary.get("target_bounds"))

    summary_target_destroyed = max(
        as_int(shot.get("target_ever_destroyed")),
        as_int(shot.get("target_blocks_destroyed")),
        as_int(shot.get("target_peak_destroyed")),
    )
    target_breaks = max(
        as_int(durability.get("direct_break_events")),
        as_int(durability.get("target_destroyed_cells")),
        summary_target_destroyed,
    )
    target_damage = target_breaks > 0
    direct_sequence = as_int(durability.get("direct_complete_sequences")) > 0
    survival = dispenser_survival(shot)
    self_damage = as_int(shot.get("self_damage_blocks"))
    regen_enabled = as_bool((summary.get("regeneration") or {}).get("enabled"))
    regen_margin = as_int(shot.get("regen_race_margin_ticks"), -1)
    falling_present = as_int(motion.get("entity_count")) > 0
    target_distance = max(1.0, as_float(summary.get("target_distance"), 1.0))
    falling_forward = motion.get("maximum_forward_displacement")
    falling_reverse = motion.get("maximum_reverse_displacement")
    alignment_cosine = motion.get("dominant_target_axis_cosine")
    closest_falling = motion.get("closest_target_distance")
    closest_target_sample = motion.get("closest_target_sample") or {}
    payload_arrival_tick = (
        as_int(closest_target_sample.get("tick"))
        if closest_target_sample
        else None
    )
    payload_reached_target = (
        closest_falling is not None and as_float(closest_falling, math.inf) <= 0.5
    )
    target_tnt_ticks = sorted(
        as_int(row.get("tick"))
        for row in explosions.get("target_contact_rows", [])
    )
    arrival_tick_gap = (
        min(abs(tick - payload_arrival_tick) for tick in target_tnt_ticks)
        if payload_arrival_tick is not None and target_tnt_ticks
        else None
    )

    if contract.require_target_damage and not target_damage:
        failures.append("target_damage=0")
    if target_breaks < contract.min_target_breaks:
        failures.append(f"target_breaks={target_breaks}<{contract.min_target_breaks}")
    if contract.require_direct_durability_sequence and not direct_sequence:
        failures.append("direct_durability_sequence_missing")
    if explosions["embedded_payload_explosions"] < contract.min_embedded_payload_explosions:
        failures.append(
            "embedded_payload_explosions="
            f"{explosions['embedded_payload_explosions']}"
            f"<{contract.min_embedded_payload_explosions}"
        )
    if explosions["unembedded_water_explosions"] > contract.max_unembedded_water_explosions:
        failures.append(
            "unembedded_water_explosions="
            f"{explosions['unembedded_water_explosions']}"
            f">{contract.max_unembedded_water_explosions}"
        )
    if contract.require_falling_payload and not falling_present:
        failures.append("falling_payload_missing")
    if geometry["largest_connected_opening"] < contract.min_connected_opening:
        failures.append(
            f"largest_connected_opening={geometry['largest_connected_opening']}"
            f"<{contract.min_connected_opening}"
        )
    if geometry["best_contiguous_lane_layers"] < contract.min_contiguous_layers:
        failures.append(
            f"best_contiguous_lane_layers={geometry['best_contiguous_lane_layers']}"
            f"<{contract.min_contiguous_layers}"
        )
    if contract.require_regeneration and not regen_enabled:
        failures.append("regeneration_not_enabled")
    if contract.require_positive_regen_margin and regen_margin <= 0:
        failures.append(f"regen_race_margin_ticks={regen_margin}<=0")
    if self_damage > contract.max_self_damage_blocks:
        failures.append(f"self_damage_blocks={self_damage}>{contract.max_self_damage_blocks}")
    if survival is None:
        if contract.min_dispenser_survival_ratio > 0:
            failures.append("dispenser_survival_unavailable")
    elif survival < contract.min_dispenser_survival_ratio:
        failures.append(
            f"dispenser_survival_ratio={survival:.6f}"
            f"<{contract.min_dispenser_survival_ratio}"
        )

    motion_relevant = contract.require_falling_payload or contract.name in {
        "diagnostic", "regen-course", "raid-course"
    }
    if falling_present and motion_relevant:
        dominant = motion.get("dominant_entity") or {}
        furthest = as_float(dominant.get("furthest_displacement"))
        if (
            not payload_reached_target
            and alignment_cosine is not None
            and furthest >= 0.5
            and as_float(alignment_cosine) < 0.5
        ):
            diagnoses.append("payload-axis-mismatch")
        if (
            not payload_reached_target
            and as_float(falling_reverse) >= max(2.0, as_float(falling_forward) + 1.0)
        ):
            diagnoses.append("falling-payload-backfire")
        if (
            not payload_reached_target
            and as_float(falling_forward) < max(2.0, target_distance * 0.25)
        ):
            diagnoses.append("falling-payload-stalled")
        strongest_impulse = motion.get("strongest_attributed_impulse") or {}
        impulse_cosine = strongest_impulse.get("target_axis_cosine")
        if impulse_cosine is not None and as_float(impulse_cosine) < 0.5:
            diagnoses.append("propulsion-impulse-off-axis")
        if impulse_cosine is not None and as_float(impulse_cosine) < -0.2:
            diagnoses.append("propulsion-impulse-reversed")
    if explosions["target_contact_explosions"] > 0 and explosions["embedded_payload_explosions"] == 0:
        diagnoses.append("tnt-only-target-contact")
        if closest_falling is not None and as_float(closest_falling, 1.0e9) <= 3.0:
            diagnoses.append("payload-near-wall-timing-gap")
        if payload_reached_target and arrival_tick_gap is not None and arrival_tick_gap > 1:
            diagnoses.append("payload-tnt-arrival-desynchronized")
    if payload_reached_target and explosions["target_contact_explosions"] == 0:
        diagnoses.append("payload-at-wall-without-target-tnt")
    if explosions["target_contact_explosions"] > 0 and not target_damage:
        diagnoses.append("target-contact-without-damage")
    expected_hits = contract.expected_hits_to_break
    total_pressure = as_int(durability.get("direct_hit_events")) + as_int(
        durability.get("direct_break_events")
    )
    if (
        expected_hits is not None
        and total_pressure >= expected_hits
        and as_int(durability.get("max_pressure_events_one_cell")) < expected_hits
    ):
        diagnoses.append("durability-hit-scatter")
    durability_mode = str((summary.get("durability") or {}).get("effective_mode", "DISABLED")).upper()
    if target_damage and durability_mode == "NATIVE" and not direct_sequence:
        diagnoses.append("native-hit-sequence-unobserved")
        warnings.append(
            "Native durability final break is visible, but intermediate per-cell decrements are not direct evidence."
        )
    if contract.min_connected_opening > 0 and geometry["largest_connected_opening"] < contract.min_connected_opening:
        diagnoses.append("no-connected-opening")
    if contract.min_contiguous_layers > 0 and geometry["best_contiguous_lane_layers"] < contract.min_contiguous_layers:
        diagnoses.append("no-contiguous-breach-lane")
    if contract.require_positive_regen_margin and regen_margin <= 0:
        diagnoses.append("regen-wins")
    if self_damage > 0:
        diagnoses.append("self-damage")
    if survival is not None and survival < 1.0:
        diagnoses.append("dispenser-loss")
    if as_bool(shot.get("contract_pass")) and failures:
        diagnoses.append("fake-green-contract")
    maximum_forward = as_float(shot.get("maximum_forward_distance"))
    if maximum_forward > 0 and maximum_forward < target_distance * 0.9:
        diagnoses.append("range-underreach")

    diagnoses = list(dict.fromkeys(diagnoses))
    evidence_grade = (
        "direct-durability-sequence"
        if direct_sequence
        else "native-final-break-only"
        if target_damage and durability_mode == "NATIVE"
        else "target-destruction-only"
        if target_damage
        else "no-breach"
    )
    return {
        "shot": number,
        "status": "PASS" if not failures else "FAIL",
        "usable_breach": not failures,
        "original_contract_pass": shot.get("contract_pass"),
        "evidence_grade": evidence_grade,
        "paths": {
            "events": str(events_path),
            "breach_events": str(breach_path),
        },
        "summary_metrics": {
            "explosions": as_int(shot.get("explosions")),
            "target_breaks": target_breaks,
            "target_peak_destroyed": as_int(shot.get("target_peak_destroyed")),
            "self_damage_blocks": self_damage,
            "dispenser_survival_ratio": survival,
            "maximum_forward_distance": maximum_forward,
            "regen_race_margin_ticks": regen_margin,
            "payload_reached_target": payload_reached_target,
            "payload_arrival_tick": payload_arrival_tick,
            "target_tnt_ticks": target_tnt_ticks,
            "nearest_payload_tnt_tick_gap": arrival_tick_gap,
        },
        "durability": durability,
        "target_geometry": geometry,
        "explosion_overlap": explosions,
        "falling_payload_motion": motion,
        "failures": failures,
        "diagnosis_codes": diagnoses,
        "warnings": warnings,
    }


def analyze(summary_path: Path, contract: BreachContract) -> dict[str, Any]:
    summary = load_json(summary_path)
    course_path = summary_path.parent / "target-course.json"
    course = load_json(course_path) if course_path.is_file() else None
    shots_raw = summary.get("shots")
    shots = [item for item in shots_raw if isinstance(item, dict)] if isinstance(shots_raw, list) else []
    shot_reports = [
        analyze_shot(summary_path, summary, course, shot, contract)
        for shot in shots
    ]
    blockers: list[str] = []
    target_material = str(summary.get("target_material", "")).upper()
    target_type = str(summary.get("target_type", "")).upper()
    if len(shots) < contract.min_shots:
        blockers.append(f"shots={len(shots)}<{contract.min_shots}")
    if contract.required_material and target_material != contract.required_material:
        blockers.append(
            f"target_material={target_material!r}!={contract.required_material!r}"
        )
    if contract.required_target_type and target_type != contract.required_target_type:
        blockers.append(
            f"target_type={target_type!r}!={contract.required_target_type!r}"
        )
    if contract.require_regeneration and not as_bool((summary.get("regeneration") or {}).get("enabled")):
        blockers.append("run_regeneration_not_enabled")
    if not shots:
        blockers.append("run_summary_has_no_shots")

    usable = [report for report in shot_reports if report["usable_breach"]]
    usable_rate = len(usable) / len(shot_reports) if shot_reports else 0.0
    if usable_rate < contract.min_usable_breach_rate:
        blockers.append(
            f"usable_breach_rate={usable_rate:.6f}<{contract.min_usable_breach_rate}"
        )

    lanes = [
        tuple(report["target_geometry"]["dominant_lane"]["lane"])
        for report in shot_reports
        if report["target_geometry"].get("dominant_lane") is not None
    ]
    lane_mode = Counter(lanes).most_common(1)[0] if lanes else None
    lane_repeatability = lane_mode[1] / len(shot_reports) if lane_mode and shot_reports else 0.0
    if lane_repeatability < contract.min_lane_repeatability:
        blockers.append(
            f"lane_repeatability={lane_repeatability:.6f}<{contract.min_lane_repeatability}"
        )

    all_codes = [
        code
        for report in shot_reports
        for code in report.get("diagnosis_codes", [])
    ]
    report = {
        "schema": "cannonlab-wall-breach-intelligence-v1",
        "status": "PASS" if not blockers else "FAIL",
        "profile": contract.name,
        "contract": asdict(contract),
        "summary": str(summary_path),
        "scenario": summary.get("scenario"),
        "cannon_file": summary.get("cannon_file"),
        "run_finish_reason": summary.get("finish_reason"),
        "target": {
            "type": target_type,
            "material": target_material,
            "direction": summary.get("target_direction"),
            "distance": summary.get("target_distance"),
            "layers": summary.get("target_layers"),
            "bounds": summary.get("target_bounds"),
            "regeneration": summary.get("regeneration"),
            "durability": summary.get("durability"),
            "target_course": str(course_path) if course_path.is_file() else None,
        },
        "aggregate": {
            "shots": len(shot_reports),
            "usable_breaches": len(usable),
            "usable_breach_rate": usable_rate,
            "dominant_lane": list(lane_mode[0]) if lane_mode else None,
            "dominant_lane_shots": lane_mode[1] if lane_mode else 0,
            "lane_repeatability": lane_repeatability,
            "direct_durability_sequence_rate": (
                sum(
                    report["durability"]["direct_complete_sequences"] > 0
                    for report in shot_reports
                ) / len(shot_reports)
                if shot_reports
                else 0.0
            ),
            "minimum_connected_opening": min(
                (
                    report["target_geometry"]["largest_connected_opening"]
                    for report in shot_reports
                ),
                default=0,
            ),
            "minimum_contiguous_lane_layers": min(
                (
                    report["target_geometry"]["best_contiguous_lane_layers"]
                    for report in shot_reports
                ),
                default=0,
            ),
            "minimum_embedded_payload_explosions": min(
                (
                    report["explosion_overlap"]["embedded_payload_explosions"]
                    for report in shot_reports
                ),
                default=0,
            ),
            "maximum_self_damage_blocks": max(
                (report["summary_metrics"]["self_damage_blocks"] for report in shot_reports),
                default=0,
            ),
            "minimum_dispenser_survival_ratio": min(
                (
                    report["summary_metrics"]["dispenser_survival_ratio"]
                    for report in shot_reports
                    if report["summary_metrics"]["dispenser_survival_ratio"] is not None
                ),
                default=None,
            ),
        },
        "blockers": blockers,
        "diagnoses": rank_diagnoses(all_codes, shot_reports),
        "shots": shot_reports,
        "truth_boundary": {
            "runtime_files_are_local_evidence": True,
            "private_extremecraft_parity_confirmed": False,
            "direct_durability_sequence_requires_DURABILITY_HIT_and_BREAK_events": True,
            "native_final_break_without_callbacks_is_labeled_incomplete": True,
            "connected_opening_is_target_cell_geometry_not_visual_inference": True,
            "contiguous_lane_requires_the_same_cross_section_from_front_layer": True,
            "falling_payload_axis_uses_recorded_entity_trajectories": True,
            "profile_pass_is_not_ec_ready": True,
        },
    }
    return report


def contract_from_args(args: argparse.Namespace) -> BreachContract:
    contract = PROFILES[args.profile]
    updates: dict[str, Any] = {}
    mapping = {
        "min_shots": args.min_shots,
        "expected_hits_to_break": args.expected_hits_to_break,
        "min_target_breaks": args.min_target_breaks,
        "min_embedded_payload_explosions": args.min_embedded_payload_explosions,
        "max_unembedded_water_explosions": args.max_unembedded_water_explosions,
        "min_connected_opening": args.min_connected_opening,
        "min_contiguous_layers": args.min_contiguous_layers,
        "max_self_damage_blocks": args.max_self_damage_blocks,
        "min_dispenser_survival_ratio": args.min_dispenser_survival_ratio,
        "min_usable_breach_rate": args.min_usable_breach_rate,
        "min_lane_repeatability": args.min_lane_repeatability,
    }
    for key, value in mapping.items():
        if value is not None:
            updates[key] = value
    if args.require_direct_durability_sequence:
        updates["require_direct_durability_sequence"] = True
    if args.require_falling_payload:
        updates["require_falling_payload"] = True
    if args.require_regeneration:
        updates["require_regeneration"] = True
    if args.require_positive_regen_margin:
        updates["require_positive_regen_margin"] = True
    return replace(contract, **updates)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed wall-breach intelligence for durable, watered and regenerating targets. "
            "It rejects flight-only greens, reconstructs per-cell durability pressure, verifies "
            "connected openings and same-lane continuation, and diagnoses TNT/falling-payload drift."
        )
    )
    parser.add_argument("results", type=Path)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="diagnostic")
    parser.add_argument("--min-shots", type=int)
    parser.add_argument("--expected-hits-to-break", type=int)
    parser.add_argument("--min-target-breaks", type=int)
    parser.add_argument("--require-direct-durability-sequence", action="store_true")
    parser.add_argument("--min-embedded-payload-explosions", type=int)
    parser.add_argument("--max-unembedded-water-explosions", type=int)
    parser.add_argument("--require-falling-payload", action="store_true")
    parser.add_argument("--min-connected-opening", type=int)
    parser.add_argument("--min-contiguous-layers", type=int)
    parser.add_argument("--require-regeneration", action="store_true")
    parser.add_argument("--require-positive-regen-margin", action="store_true")
    parser.add_argument("--max-self-damage-blocks", type=int)
    parser.add_argument("--min-dispenser-survival-ratio", type=float)
    parser.add_argument("--min-usable-breach-rate", type=float)
    parser.add_argument("--min-lane-repeatability", type=float)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    contract = contract_from_args(args)
    if contract.min_shots < 1:
        parser.error("min_shots must be positive")
    for name in (
        "min_target_breaks",
        "min_embedded_payload_explosions",
        "max_unembedded_water_explosions",
        "min_connected_opening",
        "min_contiguous_layers",
        "max_self_damage_blocks",
    ):
        if getattr(contract, name) < 0:
            parser.error(f"{name} cannot be negative")
    for name in (
        "min_dispenser_survival_ratio",
        "min_usable_breach_rate",
        "min_lane_repeatability",
    ):
        value = getattr(contract, name)
        if not 0.0 <= value <= 1.0:
            parser.error(f"{name} must be between 0 and 1")

    try:
        summary_path = latest_summary(args.results)
        report = analyze(summary_path, contract)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema": "cannonlab-wall-breach-intelligence-v1",
            "status": "ERROR",
            "error": str(exc),
        }
        exit_code = 3
    else:
        exit_code = 0 if report["status"] == "PASS" else 2

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
