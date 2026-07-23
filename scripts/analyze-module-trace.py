#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

COMPONENT_ID_RE = re.compile(r"\[(-?\d+),(-?\d+),(-?\d+)\]$")
COMPONENT_EVENTS = {
    "FIRE_INPUT",
    "REDSTONE_CHANGE",
    "PISTON_EXTEND",
    "PISTON_RETRACT",
    "DISPENSE",
    "BLOCK_PHYSICS",
}
TNT_TYPES = {"TNT", "PRIMED_TNT"}
FALLING_TYPES = {"FALLING_BLOCK"}
_MODULE_REPORT_CACHE: dict[tuple[str, int, int, int, int], dict[str, Any]] = {}
MAX_MODULE_REPORT_CACHE_ENTRIES = 64


def load_module_map() -> Any:
    script = Path(__file__).resolve().with_name("cannon-module-map.py")
    spec = importlib.util.spec_from_file_location("cannonlab_module_map", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cached_module_report(
    module_map: Any,
    schematic: Path,
    chunk_limit: int,
    assignment_radius: int,
) -> dict[str, Any]:
    resolved = schematic.resolve()
    stat = resolved.stat()
    key = (
        str(resolved),
        int(stat.st_mtime_ns),
        int(stat.st_size),
        int(chunk_limit),
        int(assignment_radius),
    )
    if key not in _MODULE_REPORT_CACHE:
        if len(_MODULE_REPORT_CACHE) >= MAX_MODULE_REPORT_CACHE_ENTRIES:
            _MODULE_REPORT_CACHE.pop(next(iter(_MODULE_REPORT_CACHE)))
        _MODULE_REPORT_CACHE[key] = module_map.build_report(
            resolved,
            chunk_limit,
            assignment_radius,
        )
    return _MODULE_REPORT_CACHE[key]


def integer(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key) or default))
    except (TypeError, ValueError):
        return default


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key) or default)
    except (TypeError, ValueError):
        return default


def read_trace(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required = {"tick", "sequence", "event", "component_id", "entity_uuid", "entity_type"}
    columns = set(rows[0]) if rows else set()
    missing = required - columns
    if missing:
        raise ValueError(f"trace is missing columns: {sorted(missing)}")
    rows.sort(key=lambda row: (integer(row, "tick"), integer(row, "sequence")))
    return rows


def component_position(row: dict[str, str]) -> tuple[int, int, int] | None:
    component_id = row.get("component_id") or ""
    match = COMPONENT_ID_RE.search(component_id)
    if match:
        return tuple(map(int, match.groups()))
    if any(row.get(key) not in (None, "") for key in ("relative_x", "relative_y", "relative_z")):
        values = tuple(number(row, key) for key in ("relative_x", "relative_y", "relative_z"))
        rounded = tuple(round(value) for value in values)
        if all(abs(values[index] - rounded[index]) <= 1e-6 for index in range(3)):
            return tuple(map(int, rounded))
    return None


def entity_point(row: dict[str, str]) -> tuple[float, float, float]:
    if any(row.get(key) not in (None, "") for key in ("relative_x", "relative_y", "relative_z")):
        return tuple(number(row, key) for key in ("relative_x", "relative_y", "relative_z"))
    return tuple(number(row, key) for key in ("world_x", "world_y", "world_z"))


def entity_velocity(row: dict[str, str]) -> tuple[float, float, float]:
    return tuple(number(row, key) for key in ("vx", "vy", "vz"))


def point_bounds(points: list[list[float]]) -> dict[str, list[float]] | None:
    if not points:
        return None
    return {
        "min": [min(point[index] for point in points) for index in range(3)],
        "max": [max(point[index] for point in points) for index in range(3)],
    }


def mean_vector(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return [0.0, 0.0, 0.0]
    return [
        round(sum(vector[index] for vector in vectors) / len(vectors), 8)
        for index in range(3)
    ]


def compact_static_module(module: dict[str, Any]) -> dict[str, Any]:
    return {
        "module_id": module.get("module_id"),
        "kind": module.get("kind"),
        "seed_bank_id": module.get("seed_bank_id"),
        "seed_dispenser_count": module.get("seed_dispenser_count"),
        "seed_facing": module.get("seed_facing"),
        "component_count": module.get("component_count"),
        "bounds": module.get("bounds"),
        "block_type_counts": module.get("block_type_counts"),
        "static_role_candidates": module.get("role_candidates"),
        "signature": module.get("signature"),
    }


def module_position_index(module_report: dict[str, Any]) -> dict[tuple[int, int, int], list[str]]:
    output: dict[tuple[int, int, int], list[str]] = defaultdict(list)
    for module in module_report.get("modules") or []:
        module_id = str(module.get("module_id"))
        for raw in module.get("component_positions") or []:
            output[tuple(map(int, raw))].append(module_id)
    for module_ids in output.values():
        module_ids.sort()
    for shared in module_report.get("shared_component_assignments") or []:
        raw = shared.get("pos") or []
        if len(raw) < 3:
            continue
        point = tuple(map(int, raw[:3]))
        module_ids = {
            *output.get(point, []),
            *(str(value) for value in shared.get("candidate_module_ids") or []),
        }
        output[point] = sorted(module_ids)
    return dict(output)


def event_modules(
    row: dict[str, str],
    position_index: dict[tuple[int, int, int], list[str]],
) -> list[str]:
    point = component_position(row)
    return list(position_index.get(point, [])) if point is not None else []


def correlate_entity_spawns(
    rows: list[dict[str, str]],
    row_modules: dict[int, list[str]],
    *,
    correlation_ticks: int,
    spawn_radius: float,
) -> tuple[list[dict[str, Any]], dict[str, set[str]], dict[str, set[str]]]:
    dispense_rows = [
        (index, row)
        for index, row in enumerate(rows)
        if row.get("event") == "DISPENSE" and row_modules.get(index)
    ]
    correlations: list[dict[str, Any]] = []
    entity_sources: dict[str, set[str]] = defaultdict(set)
    module_entities: dict[str, set[str]] = defaultdict(set)

    for index, row in enumerate(rows):
        if row.get("event") != "ENTITY_ADD":
            continue
        entity_uuid = row.get("entity_uuid") or ""
        if not entity_uuid:
            continue
        point = entity_point(row)
        candidates: list[dict[str, Any]] = []
        for dispense_index, dispense in dispense_rows:
            delta = integer(row, "tick") - integer(dispense, "tick")
            if delta < 0 or delta > correlation_ticks:
                continue
            distance = math.dist(point, entity_point(dispense))
            if distance > spawn_radius:
                continue
            for module_id in row_modules.get(dispense_index, []):
                candidates.append({
                    "module_id": module_id,
                    "dispense_tick": integer(dispense, "tick"),
                    "dispense_component": dispense.get("component_id") or "",
                    "dispensed_item": dispense.get("item") or "",
                    "tick_delta": delta,
                    "distance": round(distance, 8),
                })
        if candidates:
            best_distance = min(float(candidate["distance"]) for candidate in candidates)
            best_tick_delta = min(
                int(candidate["tick_delta"])
                for candidate in candidates
                if abs(float(candidate["distance"]) - best_distance) <= 1e-8
            )
            best = [
                candidate
                for candidate in candidates
                if abs(float(candidate["distance"]) - best_distance) <= 1e-8
                and int(candidate["tick_delta"]) == best_tick_delta
            ]
            modules = sorted({str(candidate["module_id"]) for candidate in best})
        else:
            best = []
            modules = []
        for module_id in modules:
            entity_sources[entity_uuid].add(module_id)
            module_entities[module_id].add(entity_uuid)
        correlations.append({
            "entity_uuid": entity_uuid,
            "entity_type": row.get("entity_type") or "",
            "spawn_tick": integer(row, "tick"),
            "point": list(point),
            "velocity": list(entity_velocity(row)),
            "fuse": integer(row, "fuse", -1),
            "candidate_modules": modules,
            "unambiguous": len(modules) == 1,
            "best_dispense_matches": best,
        })
    return correlations, entity_sources, module_entities


def runtime_role_candidates(module: dict[str, Any], first_tnt_tick: int | None) -> list[dict[str, Any]]:
    counts = module.get("event_counts") or {}
    entity_counts = module.get("correlated_entity_types") or {}
    first_tnt_spawn = module.get("first_tnt_spawn_tick")
    first_piston = module.get("first_piston_tick")
    first_falling = module.get("first_falling_spawn_tick")
    candidates: list[dict[str, Any]] = []

    if entity_counts.get("PRIMED_TNT", 0) + entity_counts.get("TNT", 0) > 0:
        phase = "early" if first_tnt_tick is not None and first_tnt_spawn == first_tnt_tick else "later"
        candidates.append({
            "label": f"{phase}-tnt-cohort-source-candidate",
            "confidence": "runtime-medium",
            "evidence": "dispenser events were spatially and temporally correlated with TNT entity spawns",
        })
    if entity_counts.get("FALLING_BLOCK", 0) > 0:
        candidates.append({
            "label": "falling-payload-source-candidate",
            "confidence": "runtime-medium",
            "evidence": "dispenser events were spatially and temporally correlated with falling-block spawns",
        })
    if first_piston is not None and first_falling is not None and first_piston <= first_falling:
        candidates.append({
            "label": "payload-positioning-or-compression-candidate",
            "confidence": "runtime-low",
            "evidence": "piston activity preceded a correlated falling-block spawn in the same static module",
        })
    if counts.get("REDSTONE_CHANGE", 0) and not counts.get("DISPENSE", 0):
        candidates.append({
            "label": "timing-or-control-path-candidate",
            "confidence": "runtime-low",
            "evidence": "runtime redstone activity occurred without a mapped dispense event",
        })
    if counts.get("PISTON_EXTEND", 0) + counts.get("PISTON_RETRACT", 0) > 0:
        candidates.append({
            "label": "motion-stage-candidate",
            "confidence": "runtime-medium",
            "evidence": "mapped piston activity occurred during the shot",
        })
    if not candidates and sum(int(value) for value in counts.values()) > 0:
        candidates.append({
            "label": "active-unclassified-module",
            "confidence": "runtime-low",
            "evidence": "the module participated in the causal trace but its subsystem role is not proven",
        })
    return candidates


def build_report(
    schematic: Path,
    trace: Path,
    *,
    chunk_limit: int = 160,
    assignment_radius: int = 6,
    correlation_ticks: int = 2,
    spawn_radius: float = 3.0,
) -> dict[str, Any]:
    module_map = load_module_map()
    module_report = cached_module_report(
        module_map,
        schematic,
        chunk_limit,
        assignment_radius,
    )
    rows = read_trace(trace)
    position_index = module_position_index(module_report)
    modules_by_id = {
        str(module.get("module_id")): module
        for module in module_report.get("modules") or []
    }

    row_modules: dict[int, list[str]] = {}
    shared_event_groups: dict[tuple[str, ...], dict[str, Any]] = {}
    mapped_component_events = 0
    total_component_events = 0
    ambiguous_component_events = 0
    unmapped_component_rows: list[dict[str, Any]] = []
    runtime: dict[str, dict[str, Any]] = {}
    for module_id, module in modules_by_id.items():
        runtime[module_id] = {
            "static": compact_static_module(module),
            "event_counts": Counter(),
            "exclusive_event_counts": Counter(),
            "ambiguous_event_counts": Counter(),
            "event_ticks": defaultdict(list),
            "exclusive_event_ticks": defaultdict(list),
            "items_dispensed": Counter(),
            "piston_directions": Counter(),
            "piston_moved_blocks": 0,
            "component_ids": set(),
            "first_tick": None,
            "last_tick": None,
        }

    for index, row in enumerate(rows):
        event = row.get("event") or ""
        modules = event_modules(row, position_index)
        row_modules[index] = modules
        if event in COMPONENT_EVENTS and (row.get("component_id") or component_position(row) is not None):
            total_component_events += 1
            if modules:
                mapped_component_events += 1
            else:
                unmapped_component_rows.append({
                    "tick": integer(row, "tick"),
                    "sequence": integer(row, "sequence"),
                    "event": event,
                    "component_id": row.get("component_id") or "",
                    "position": list(component_position(row)) if component_position(row) else None,
                })
            if len(modules) > 1:
                ambiguous_component_events += 1
                group_key = tuple(sorted(modules))
                group = shared_event_groups.setdefault(group_key, {
                    "module_ids": list(group_key),
                    "event_counts": Counter(),
                    "event_ticks": defaultdict(list),
                    "component_ids": set(),
                })
                group["event_counts"][event] += 1
                group["event_ticks"][event].append(integer(row, "tick"))
                if row.get("component_id"):
                    group["component_ids"].add(row.get("component_id") or "")
        for module_id in modules:
            state = runtime[module_id]
            tick = integer(row, "tick")
            state["event_counts"][event] += 1
            state["event_ticks"][event].append(tick)
            if len(modules) == 1:
                state["exclusive_event_counts"][event] += 1
                state["exclusive_event_ticks"][event].append(tick)
            elif len(modules) > 1:
                state["ambiguous_event_counts"][event] += 1
            if row.get("component_id"):
                state["component_ids"].add(row.get("component_id") or "")
            if state["first_tick"] is None or tick < state["first_tick"]:
                state["first_tick"] = tick
            if state["last_tick"] is None or tick > state["last_tick"]:
                state["last_tick"] = tick
            if event == "DISPENSE" and row.get("item"):
                state["items_dispensed"][row.get("item") or ""] += 1
            if event in {"PISTON_EXTEND", "PISTON_RETRACT"}:
                if row.get("direction"):
                    state["piston_directions"][row.get("direction") or ""] += 1
                state["piston_moved_blocks"] += integer(row, "moved_blocks")

    correlations, entity_sources, module_entities = correlate_entity_spawns(
        rows,
        row_modules,
        correlation_ticks=correlation_ticks,
        spawn_radius=spawn_radius,
    )
    spawn_rows_by_uuid = {
        row.get("entity_uuid") or "": row
        for row in rows
        if row.get("event") == "ENTITY_ADD" and row.get("entity_uuid")
    }
    entity_type_by_uuid = {
        entity_uuid: row.get("entity_type") or ""
        for entity_uuid, row in spawn_rows_by_uuid.items()
    }
    spawn_tick_by_uuid = {
        entity_uuid: integer(row, "tick")
        for entity_uuid, row in spawn_rows_by_uuid.items()
    }
    explosion_records_by_uuid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("event") not in {"EXPLOSION", "BLOCK_EXPLOSION"}:
            continue
        entity_uuid = row.get("entity_uuid") or ""
        if entity_uuid:
            explosion_records_by_uuid[entity_uuid].append({
                "tick": integer(row, "tick"),
                "point": list(entity_point(row)),
                "velocity": list(entity_velocity(row)),
            })

    joint_entity_groups: dict[
        tuple[int, str, tuple[float, float, float], tuple[str, ...], tuple[str, ...]],
        list[dict[str, Any]],
    ] = defaultdict(list)
    for correlation in correlations:
        candidate_modules = tuple(sorted(
            str(value)
            for value in correlation.get("candidate_modules") or []
        ))
        if len(candidate_modules) <= 1:
            continue
        point = tuple(round(float(value), 8) for value in correlation.get("point") or [0.0, 0.0, 0.0])
        components = tuple(sorted({
            str(match.get("dispense_component") or "")
            for match in correlation.get("best_dispense_matches") or []
            if match.get("dispense_component")
        }))
        key = (
            int(correlation.get("spawn_tick") or 0),
            str(correlation.get("entity_type") or "UNKNOWN"),
            point,
            candidate_modules,
            components,
        )
        entity_uuid = str(correlation.get("entity_uuid") or "")
        joint_entity_groups[key].append({
            "entity_uuid": entity_uuid,
            "entity_type": str(correlation.get("entity_type") or "UNKNOWN"),
            "spawn_tick": int(correlation.get("spawn_tick") or 0),
            "spawn_point": list(point),
            "spawn_velocity": [
                float(value)
                for value in correlation.get("velocity") or [0.0, 0.0, 0.0]
            ],
            "fuse": int(correlation.get("fuse") if correlation.get("fuse") is not None else -1),
            "explosions": explosion_records_by_uuid.get(entity_uuid, []),
        })

    joint_entity_source_cohorts: list[dict[str, Any]] = []
    for key, profiles in sorted(joint_entity_groups.items()):
        spawn_tick, entity_type, point, candidate_modules, components = key
        profiles.sort(key=lambda row: (
            tuple(row["spawn_velocity"]),
            row["fuse"],
            tuple(
                (event["tick"], *event["point"])
                for event in row["explosions"]
            ),
            row["entity_uuid"],
        ))
        velocities = [list(map(float, row["spawn_velocity"])) for row in profiles]
        fuses = Counter(int(row["fuse"]) for row in profiles)
        explosion_events = [
            event
            for profile in profiles
            for event in profile.get("explosions") or []
        ]
        candidate_dispense_events = sorted({
            (
                int(match.get("dispense_tick") or 0),
                str(match.get("dispense_component") or ""),
                str(match.get("module_id") or ""),
                str(match.get("dispensed_item") or ""),
            )
            for correlation in correlations
            if int(correlation.get("spawn_tick") or 0) == spawn_tick
            and str(correlation.get("entity_type") or "UNKNOWN") == entity_type
            and tuple(round(float(value), 8) for value in correlation.get("point") or []) == point
            and tuple(sorted(str(value) for value in correlation.get("candidate_modules") or [])) == candidate_modules
            for match in correlation.get("best_dispense_matches") or []
        })
        joint_entity_source_cohorts.append({
            "spawn_tick": spawn_tick,
            "entity_type": entity_type,
            "spawn_point": list(point),
            "entity_count": len(profiles),
            "candidate_module_ids": list(candidate_modules),
            "candidate_dispense_components": list(components),
            "candidate_dispense_events": [
                {
                    "tick": tick,
                    "component_id": component_id,
                    "module_id": module_id,
                    "item": item,
                }
                for tick, component_id, module_id, item in candidate_dispense_events
            ],
            "mean_velocity": mean_vector(velocities),
            "fuse_counts": {
                str(fuse): count
                for fuse, count in sorted(fuses.items())
            },
            "explosion_event_count": len(explosion_events),
            "explosion_ticks": dict(sorted(Counter(
                int(event["tick"])
                for event in explosion_events
            ).items())),
            "explosion_position_bounds": point_bounds([
                list(map(float, event["point"]))
                for event in explosion_events
            ]),
            "entity_profiles": profiles,
            "evidence": (
                "multiple equally plausible dispenser modules intentionally converge on one spawn point; "
                "the cohort is fully accounted for without inventing per-UUID ownership"
            ),
        })

    active_modules: list[dict[str, Any]] = []
    for module_id, state in runtime.items():
        correlated = sorted(module_entities.get(module_id, set()))
        correlated_type_counts = Counter(entity_type_by_uuid.get(uuid, "UNKNOWN") for uuid in correlated)
        unambiguous_entities = [
            uuid for uuid in correlated if len(entity_sources.get(uuid, set())) == 1
        ]
        attributed_explosions = [
            {
                "entity_uuid": uuid,
                "ticks": [record["tick"] for record in explosion_records_by_uuid.get(uuid, [])],
                "points": [record["point"] for record in explosion_records_by_uuid.get(uuid, [])],
                "events": explosion_records_by_uuid.get(uuid, []),
            }
            for uuid in unambiguous_entities
            if explosion_records_by_uuid.get(uuid)
        ]
        correlated_entity_profiles = []
        for uuid in unambiguous_entities:
            spawn = spawn_rows_by_uuid.get(uuid)
            if spawn is None:
                continue
            correlated_entity_profiles.append({
                "entity_uuid": uuid,
                "entity_type": entity_type_by_uuid.get(uuid, "UNKNOWN"),
                "spawn_tick": integer(spawn, "tick"),
                "spawn_point": list(entity_point(spawn)),
                "spawn_velocity": list(entity_velocity(spawn)),
                "fuse": integer(spawn, "fuse", -1),
                "explosions": explosion_records_by_uuid.get(uuid, []),
            })
        correlated_entity_profiles.sort(key=lambda row: (
            row["entity_type"],
            row["spawn_tick"],
            tuple(row["spawn_point"]),
            tuple(row["spawn_velocity"]),
            row["fuse"],
            row["entity_uuid"],
        ))
        dispense_ticks = state["event_ticks"].get("DISPENSE", [])
        piston_ticks = (
            state["event_ticks"].get("PISTON_EXTEND", [])
            + state["event_ticks"].get("PISTON_RETRACT", [])
        )
        falling_ticks = [
            spawn_tick_by_uuid[uuid]
            for uuid in correlated
            if entity_type_by_uuid.get(uuid) in FALLING_TYPES
        ]
        tnt_ticks = [
            spawn_tick_by_uuid[uuid]
            for uuid in correlated
            if entity_type_by_uuid.get(uuid) in TNT_TYPES
        ]
        module_row = {
            **state["static"],
            "active": state["first_tick"] is not None or bool(correlated),
            "first_tick": state["first_tick"],
            "last_tick": state["last_tick"],
            "event_counts": dict(sorted(state["event_counts"].items())),
            "exclusive_event_counts": dict(sorted(state["exclusive_event_counts"].items())),
            "ambiguous_event_counts": dict(sorted(state["ambiguous_event_counts"].items())),
            "event_ticks": {
                key: sorted(values)
                for key, values in sorted(state["event_ticks"].items())
            },
            "exclusive_event_ticks": {
                key: sorted(values)
                for key, values in sorted(state["exclusive_event_ticks"].items())
            },
            "component_ids_observed": sorted(state["component_ids"]),
            "items_dispensed": dict(sorted(state["items_dispensed"].items())),
            "piston_directions": dict(sorted(state["piston_directions"].items())),
            "piston_moved_blocks": state["piston_moved_blocks"],
            "first_dispense_tick": min(dispense_ticks) if dispense_ticks else None,
            "first_piston_tick": min(piston_ticks) if piston_ticks else None,
            "first_falling_spawn_tick": min(falling_ticks) if falling_ticks else None,
            "first_tnt_spawn_tick": min(tnt_ticks) if tnt_ticks else None,
            "correlated_entity_uuids": correlated,
            "unambiguous_correlated_entity_uuids": unambiguous_entities,
            "entity_profile_coverage": round(
                len(unambiguous_entities) / max(1, len(correlated)),
                6,
            ) if correlated else 1.0,
            "correlated_entity_types": dict(sorted(correlated_type_counts.items())),
            "correlated_entity_profiles": correlated_entity_profiles,
            "attributed_explosions": attributed_explosions,
        }
        active_modules.append(module_row)

    tnt_source_ticks = [
        int(module["first_tnt_spawn_tick"])
        for module in active_modules
        if module["first_tnt_spawn_tick"] is not None
    ]
    first_tnt_tick = min(tnt_source_ticks) if tnt_source_ticks else None
    for module in active_modules:
        module["runtime_role_candidates"] = runtime_role_candidates(module, first_tnt_tick)

    active_modules.sort(
        key=lambda row: (
            row["first_tick"] is None,
            row["first_tick"] if row["first_tick"] is not None else 10**12,
            str(row["module_id"]),
        )
    )
    active_only = [module for module in active_modules if module["active"]]
    shared_component_event_cohorts = []
    for group_key, group in sorted(shared_event_groups.items()):
        all_ticks = [
            tick
            for ticks in group["event_ticks"].values()
            for tick in ticks
        ]
        shared_component_event_cohorts.append({
            "module_ids": list(group_key),
            "event_counts": dict(sorted(group["event_counts"].items())),
            "event_ticks": {
                event: sorted(ticks)
                for event, ticks in sorted(group["event_ticks"].items())
            },
            "first_tick": min(all_ticks) if all_ticks else None,
            "last_tick": max(all_ticks) if all_ticks else None,
            "component_ids": sorted(group["component_ids"]),
            "evidence": (
                "events occurred on static components with multiple equal-distance candidate modules; "
                "ownership remains joint"
            ),
        })
    phase_order = [
        {
            "phase_index": index + 1,
            "module_id": module["module_id"],
            "first_tick": module["first_tick"],
            "last_tick": module["last_tick"],
            "event_counts": module["event_counts"],
            "items_dispensed": module["items_dispensed"],
            "correlated_entity_types": module["correlated_entity_types"],
            "runtime_role_candidates": module["runtime_role_candidates"],
        }
        for index, module in enumerate(active_only)
    ]

    phase_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for module in active_only:
        if module["first_tick"] is not None:
            phase_groups[int(module["first_tick"])].append(module)
    phase_cohorts: list[dict[str, Any]] = []
    previous_tick: int | None = None
    for phase_index, tick in enumerate(sorted(phase_groups), start=1):
        members = phase_groups[tick]
        event_counts: Counter[str] = Counter()
        items: Counter[str] = Counter()
        entity_types: Counter[str] = Counter()
        for module in members:
            event_counts.update(module.get("event_counts") or {})
            items.update(module.get("items_dispensed") or {})
            entity_types.update(module.get("correlated_entity_types") or {})
        phase_cohorts.append({
            "phase_index": phase_index,
            "first_tick": tick,
            "gap_from_previous_phase": None if previous_tick is None else tick - previous_tick,
            "last_tick": max(
                int(module["last_tick"])
                for module in members
                if module["last_tick"] is not None
            ),
            "module_ids": sorted(str(module["module_id"]) for module in members),
            "event_counts": dict(sorted(event_counts.items())),
            "items_dispensed": dict(sorted(items.items())),
            "correlated_entity_types": dict(sorted(entity_types.items())),
            "evidence": "modules with the same first observed runtime tick",
        })
        previous_tick = tick

    entity_source_groups: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    explosion_source_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for module in active_modules:
        module_id = str(module["module_id"])
        for profile in module.get("correlated_entity_profiles") or []:
            key = (int(profile["spawn_tick"]), str(profile["entity_type"]))
            entity_source_groups[key].append({"module_id": module_id, **profile})
            for explosion in profile.get("explosions") or []:
                explosion_source_groups[int(explosion["tick"])].append({
                    "module_id": module_id,
                    "entity_type": profile["entity_type"],
                    "point": explosion["point"],
                })

    entity_source_cohorts = []
    for (tick, entity_type), members in sorted(entity_source_groups.items()):
        positions = [list(map(float, member["spawn_point"])) for member in members]
        velocities = [list(map(float, member["spawn_velocity"])) for member in members]
        fuses = [int(member["fuse"]) for member in members]
        entity_source_cohorts.append({
            "spawn_tick": tick,
            "entity_type": entity_type,
            "count": len(members),
            "module_ids": sorted({str(member["module_id"]) for member in members}),
            "position_bounds": point_bounds(positions),
            "mean_velocity": mean_vector(velocities),
            "fuse_range": {"min": min(fuses), "max": max(fuses)} if fuses else None,
            "evidence": "unambiguous entity sources grouped by spawn tick and type",
        })

    explosion_source_cohorts = []
    for tick, members in sorted(explosion_source_groups.items()):
        positions = [list(map(float, member["point"])) for member in members]
        explosion_source_cohorts.append({
            "explosion_tick": tick,
            "count": len(members),
            "module_ids": sorted({str(member["module_id"]) for member in members}),
            "entity_types": dict(sorted(Counter(
                str(member["entity_type"])
                for member in members
            ).items())),
            "position_bounds": point_bounds(positions),
            "evidence": "explosions attributed through unambiguous source entity UUIDs",
        })

    unambiguous_correlations = sum(1 for row in correlations if row["unambiguous"])
    ambiguous_correlations = sum(1 for row in correlations if len(row["candidate_modules"]) > 1)
    mapped_correlations = sum(1 for row in correlations if row["candidate_modules"])
    return {
        "status": "PASS",
        "schema": "cannonlab-module-trace-v2",
        "schematic": str(schematic),
        "schematic_sha256": module_report.get("file_sha256"),
        "trace": str(trace),
        "configuration": {
            "chunk_limit": chunk_limit,
            "assignment_radius": assignment_radius,
            "correlation_ticks": correlation_ticks,
            "spawn_radius": spawn_radius,
        },
        "summary": {
            "static_modules": len(active_modules),
            "active_modules": len(active_only),
            "total_component_events": total_component_events,
            "mapped_component_events": mapped_component_events,
            "component_event_coverage": round(mapped_component_events / max(1, total_component_events), 6),
            "ambiguous_component_events": ambiguous_component_events,
            "shared_component_event_cohorts": len(shared_component_event_cohorts),
            "entity_spawns": len(correlations),
            "unambiguous_entity_correlations": unambiguous_correlations,
            "ambiguous_entity_correlations": ambiguous_correlations,
            "unmapped_entity_spawns": sum(1 for row in correlations if not row["candidate_modules"]),
            "mapped_entity_correlations": mapped_correlations,
            "entity_source_accounting_coverage": round(
                mapped_correlations / max(1, len(correlations)),
                6,
            ),
            "joint_entity_source_cohorts": len(joint_entity_source_cohorts),
            "joint_entity_source_entities": sum(
                int(cohort["entity_count"])
                for cohort in joint_entity_source_cohorts
            ),
            "phase_cohorts": len(phase_cohorts),
            "entity_source_cohorts": len(entity_source_cohorts),
            "explosion_source_cohorts": len(explosion_source_cohorts),
            "attributed_explosion_entities": sum(
                len(module["attributed_explosions"])
                for module in active_modules
            ),
            "attributed_explosions": sum(
                len(module["attributed_explosions"])
                for module in active_modules
            ),
            "attributed_explosion_events": sum(
                sum(len(row.get("events") or []) for row in module["attributed_explosions"])
                for module in active_modules
            ),
            "first_tnt_source_tick": first_tnt_tick,
        },
        "phase_order": phase_order,
        "shared_component_event_cohorts": shared_component_event_cohorts,
        "phase_cohorts": phase_cohorts,
        "entity_source_cohorts": entity_source_cohorts,
        "joint_entity_source_cohorts": joint_entity_source_cohorts,
        "explosion_source_cohorts": explosion_source_cohorts,
        "modules": active_modules,
        "entity_correlations": correlations,
        "unmapped_component_events": unmapped_component_rows[:500],
        "unmapped_component_events_truncated": len(unmapped_component_rows) > 500,
        "truth_boundary": {
            "static_module_geometry_confirmed": True,
            "runtime_event_order_confirmed": True,
            "entity_source_correlation_confirmed": False,
            "subsystem_roles_confirmed": False,
            "note": (
                "Component-to-module mapping is exact by schematic-relative coordinate. Entity source attribution is "
                "a bounded timing-and-distance correlation. Charge, booster, hammer, sand, payload, nuke, OSRB, "
                "leftshot and reverse labels remain unconfirmed until stronger causal and live evidence exists."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Join a real cannon module map to one causal runtime trace and recover observed firing phases"
    )
    parser.add_argument("schematic", type=Path)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--assignment-radius", type=int, default=6)
    parser.add_argument("--correlation-ticks", type=int, default=2)
    parser.add_argument("--spawn-radius", type=float, default=3.0)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_report(
        args.schematic,
        args.trace,
        chunk_limit=args.chunk_limit,
        assignment_radius=args.assignment_radius,
        correlation_ticks=args.correlation_ticks,
        spawn_radius=args.spawn_radius,
    )
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
