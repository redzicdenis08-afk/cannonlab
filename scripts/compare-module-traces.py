#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
from pathlib import Path
from typing import Any

TIMING_FIELDS = (
    "first_tick",
    "last_tick",
    "first_dispense_tick",
    "first_piston_tick",
    "first_falling_spawn_tick",
    "first_tnt_spawn_tick",
)
COMPONENT_ID_RE = re.compile(r"^(.*\[)(-?\d+),(-?\d+),(-?\d+)(\])$")
_RUNTIME_ANALYSIS_CACHE: dict[
    tuple[str, int, int, str, int, int, int, int, int, float],
    dict[str, Any],
] = {}
MAX_RUNTIME_ANALYSIS_CACHE_ENTRIES = 64


def load_script(name: str, filename: str) -> Any:
    script = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cached_runtime_analysis(
    analyzer: Any,
    schematic: Path,
    trace: Path,
    *,
    chunk_limit: int,
    assignment_radius: int,
    correlation_ticks: int,
    spawn_radius: float,
) -> dict[str, Any]:
    resolved_schematic = schematic.resolve()
    resolved_trace = trace.resolve()
    schematic_stat = resolved_schematic.stat()
    trace_stat = resolved_trace.stat()
    key = (
        str(resolved_schematic),
        int(schematic_stat.st_mtime_ns),
        int(schematic_stat.st_size),
        str(resolved_trace),
        int(trace_stat.st_mtime_ns),
        int(trace_stat.st_size),
        int(chunk_limit),
        int(assignment_radius),
        int(correlation_ticks),
        float(spawn_radius),
    )
    if key not in _RUNTIME_ANALYSIS_CACHE:
        if len(_RUNTIME_ANALYSIS_CACHE) >= MAX_RUNTIME_ANALYSIS_CACHE_ENTRIES:
            _RUNTIME_ANALYSIS_CACHE.pop(next(iter(_RUNTIME_ANALYSIS_CACHE)))
        _RUNTIME_ANALYSIS_CACHE[key] = analyzer.build_report(
            resolved_schematic,
            resolved_trace,
            chunk_limit=chunk_limit,
            assignment_radius=assignment_radius,
            correlation_ticks=correlation_ticks,
            spawn_radius=spawn_radius,
        )
    return _RUNTIME_ANALYSIS_CACHE[key]


def timing_delta(first: int | None, second: int | None) -> int | None:
    if first is None or second is None:
        return None
    return int(second) - int(first)


def explosion_count(module: dict[str, Any]) -> int:
    return sum(
        len(row.get("ticks") or [])
        for row in module.get("attributed_explosions") or []
    )


def point_in_reference_frame(
    raw: list[float] | tuple[float, ...],
    candidate_translation: tuple[int, int, int],
) -> list[float]:
    values = list(raw or [0.0, 0.0, 0.0])
    while len(values) < 3:
        values.append(0.0)
    return [
        float(values[index]) - candidate_translation[index]
        for index in range(3)
    ]


def normalized_entity_profile(
    profile: dict[str, Any],
    candidate_translation: tuple[int, int, int],
) -> dict[str, Any]:
    velocity = [float(value) for value in (profile.get("spawn_velocity") or [0.0, 0.0, 0.0])]
    while len(velocity) < 3:
        velocity.append(0.0)
    explosions = [
        {
            "tick": int(row.get("tick") or 0),
            "point": point_in_reference_frame(
                row.get("point") or [],
                candidate_translation,
            ),
        }
        for row in profile.get("explosions") or []
    ]
    explosions.sort(key=lambda row: (row["tick"], tuple(row["point"])))
    return {
        "entity_type": str(profile.get("entity_type") or "UNKNOWN"),
        "spawn_tick": int(profile.get("spawn_tick") or 0),
        "spawn_point": point_in_reference_frame(
            profile.get("spawn_point") or [],
            candidate_translation,
        ),
        "spawn_velocity": velocity[:3],
        "fuse": int(profile.get("fuse") if profile.get("fuse") is not None else -1),
        "explosions": explosions,
    }


def entity_profile_sort_key(profile: dict[str, Any]) -> tuple[Any, ...]:
    return (
        profile["entity_type"],
        profile["spawn_tick"],
        tuple(profile["spawn_point"]),
        tuple(profile["spawn_velocity"]),
        profile["fuse"],
        tuple(
            (row["tick"], *row["point"])
            for row in profile["explosions"]
        ),
    )


def compare_entity_profiles(
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    candidate_translation: tuple[int, int, int],
    max_timing_delta: int,
    max_spawn_position_delta: float,
    max_spawn_velocity_delta: float,
    max_fuse_delta: int,
    max_explosion_position_delta: float,
) -> dict[str, Any]:
    first_profiles = [
        normalized_entity_profile(profile, (0, 0, 0))
        for profile in first.get("correlated_entity_profiles") or []
    ]
    second_profiles = [
        normalized_entity_profile(profile, candidate_translation)
        for profile in second.get("correlated_entity_profiles") or []
    ]
    first_profiles.sort(key=entity_profile_sort_key)
    second_profiles.sort(key=entity_profile_sort_key)

    failures: list[str] = []
    if len(first_profiles) != len(second_profiles):
        failures.append("entity_profile_count_changed")

    pair_reports: list[dict[str, Any]] = []
    max_observed: dict[str, int | float] = {
        "spawn_tick_delta": 0,
        "spawn_position_delta": 0.0,
        "spawn_velocity_delta": 0.0,
        "fuse_delta": 0,
        "explosion_tick_delta": 0,
        "explosion_position_delta": 0.0,
    }

    for index, (left, right) in enumerate(zip(first_profiles, second_profiles)):
        pair_failures: list[str] = []
        if left["entity_type"] != right["entity_type"]:
            pair_failures.append("entity_type_changed")

        spawn_tick_delta = int(right["spawn_tick"]) - int(left["spawn_tick"])
        spawn_position_delta = math.dist(left["spawn_point"], right["spawn_point"])
        spawn_velocity_delta = math.dist(left["spawn_velocity"], right["spawn_velocity"])
        fuse_delta = int(right["fuse"]) - int(left["fuse"])
        if abs(spawn_tick_delta) > max_timing_delta:
            pair_failures.append("entity_spawn_tick_delta_exceeded")
        if spawn_position_delta > max_spawn_position_delta:
            pair_failures.append("entity_spawn_position_delta_exceeded")
        if spawn_velocity_delta > max_spawn_velocity_delta:
            pair_failures.append("entity_spawn_velocity_delta_exceeded")
        if abs(fuse_delta) > max_fuse_delta:
            pair_failures.append("entity_fuse_delta_exceeded")

        left_explosions = left["explosions"]
        right_explosions = right["explosions"]
        if len(left_explosions) != len(right_explosions):
            pair_failures.append("entity_explosion_count_changed")

        explosion_pairs: list[dict[str, Any]] = []
        for left_explosion, right_explosion in zip(left_explosions, right_explosions):
            explosion_tick_delta = int(right_explosion["tick"]) - int(left_explosion["tick"])
            explosion_position_delta = math.dist(
                left_explosion["point"],
                right_explosion["point"],
            )
            explosion_failures: list[str] = []
            if abs(explosion_tick_delta) > max_timing_delta:
                explosion_failures.append("entity_explosion_tick_delta_exceeded")
            if explosion_position_delta > max_explosion_position_delta:
                explosion_failures.append("entity_explosion_position_delta_exceeded")
            pair_failures.extend(explosion_failures)
            max_observed["explosion_tick_delta"] = max(
                int(max_observed["explosion_tick_delta"]),
                abs(explosion_tick_delta),
            )
            max_observed["explosion_position_delta"] = max(
                float(max_observed["explosion_position_delta"]),
                explosion_position_delta,
            )
            explosion_pairs.append({
                "first": left_explosion,
                "second": right_explosion,
                "tick_delta": explosion_tick_delta,
                "position_delta": round(explosion_position_delta, 8),
                "failures": explosion_failures,
            })

        max_observed["spawn_tick_delta"] = max(
            int(max_observed["spawn_tick_delta"]),
            abs(spawn_tick_delta),
        )
        max_observed["spawn_position_delta"] = max(
            float(max_observed["spawn_position_delta"]),
            spawn_position_delta,
        )
        max_observed["spawn_velocity_delta"] = max(
            float(max_observed["spawn_velocity_delta"]),
            spawn_velocity_delta,
        )
        max_observed["fuse_delta"] = max(
            int(max_observed["fuse_delta"]),
            abs(fuse_delta),
        )
        pair_reports.append({
            "pair_index": index,
            "entity_type": {
                "first": left["entity_type"],
                "second": right["entity_type"],
            },
            "spawn_tick": {
                "first": left["spawn_tick"],
                "second": right["spawn_tick"],
                "delta": spawn_tick_delta,
            },
            "spawn_point": {
                "first": left["spawn_point"],
                "second": right["spawn_point"],
                "distance": round(spawn_position_delta, 8),
            },
            "spawn_velocity": {
                "first": left["spawn_velocity"],
                "second": right["spawn_velocity"],
                "distance": round(spawn_velocity_delta, 8),
            },
            "fuse": {
                "first": left["fuse"],
                "second": right["fuse"],
                "delta": fuse_delta,
            },
            "explosions": explosion_pairs,
            "failures": sorted(set(pair_failures)),
        })
        failures.extend(pair_failures)

    return {
        "status": "PASS" if not failures else "FAIL",
        "candidate_translation": list(candidate_translation),
        "first_profile_count": len(first_profiles),
        "second_profile_count": len(second_profiles),
        "failures": sorted(set(failures)),
        "max_observed": {
            key: round(value, 8) if isinstance(value, float) else value
            for key, value in max_observed.items()
        },
        "pairs": pair_reports,
    }


def compare_runtime_module(
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    candidate_translation: tuple[int, int, int],
    max_timing_delta: int,
    max_spawn_position_delta: float,
    max_spawn_velocity_delta: float,
    max_fuse_delta: int,
    max_explosion_position_delta: float,
    minimum_module_entity_profile_coverage: float,
    require_event_counts_equal: bool,
    require_items_equal: bool,
    require_entity_types_equal: bool,
    require_explosion_counts_equal: bool,
    require_entity_physics_equal: bool,
) -> dict[str, Any]:
    timing = {
        field: {
            "first": first.get(field),
            "second": second.get(field),
            "delta": timing_delta(first.get(field), second.get(field)),
        }
        for field in TIMING_FIELDS
    }
    failures: list[str] = []
    for field, row in timing.items():
        left = row["first"]
        right = row["second"]
        delta = row["delta"]
        if (left is None) != (right is None):
            failures.append(f"{field}_presence_changed")
        elif delta is not None and abs(int(delta)) > max_timing_delta:
            failures.append(f"{field}_delta_exceeded")

    first_events = first.get("exclusive_event_counts") or first.get("event_counts") or {}
    second_events = second.get("exclusive_event_counts") or second.get("event_counts") or {}
    first_inclusive_events = first.get("event_counts") or {}
    second_inclusive_events = second.get("event_counts") or {}
    first_items = first.get("items_dispensed") or {}
    second_items = second.get("items_dispensed") or {}
    first_entities = first.get("correlated_entity_types") or {}
    second_entities = second.get("correlated_entity_types") or {}
    first_explosions = explosion_count(first)
    second_explosions = explosion_count(second)
    entity_profiles = compare_entity_profiles(
        first,
        second,
        candidate_translation=candidate_translation,
        max_timing_delta=max_timing_delta,
        max_spawn_position_delta=max_spawn_position_delta,
        max_spawn_velocity_delta=max_spawn_velocity_delta,
        max_fuse_delta=max_fuse_delta,
        max_explosion_position_delta=max_explosion_position_delta,
    )
    first_profile_coverage = float(first.get("entity_profile_coverage", 1.0))
    second_profile_coverage = float(second.get("entity_profile_coverage", 1.0))

    if require_event_counts_equal and first_events != second_events:
        failures.append("event_counts_changed")
    if require_items_equal and first_items != second_items:
        failures.append("dispensed_items_changed")
    if require_entity_types_equal and first_entities != second_entities:
        failures.append("correlated_entity_types_changed")
    if require_explosion_counts_equal and first_explosions != second_explosions:
        failures.append("attributed_explosion_count_changed")
    if require_entity_physics_equal and entity_profiles["status"] != "PASS":
        failures.extend(entity_profiles["failures"])
    if first_profile_coverage < minimum_module_entity_profile_coverage:
        failures.append("reference_module_entity_profile_coverage_too_low")
    if second_profile_coverage < minimum_module_entity_profile_coverage:
        failures.append("candidate_module_entity_profile_coverage_too_low")

    return {
        "status": "PASS" if not failures else "FAIL",
        "first_module_id": first.get("module_id"),
        "second_module_id": second.get("module_id"),
        "signature": first.get("signature"),
        "candidate_translation": list(candidate_translation),
        "failures": sorted(set(failures)),
        "timing": timing,
        "event_counts": {"first": first_events, "second": second_events},
        "inclusive_event_counts": {
            "first": first_inclusive_events,
            "second": second_inclusive_events,
        },
        "items_dispensed": {"first": first_items, "second": second_items},
        "correlated_entity_types": {"first": first_entities, "second": second_entities},
        "attributed_explosion_count": {
            "first": first_explosions,
            "second": second_explosions,
        },
        "entity_physics": entity_profiles,
        "entity_profile_coverage": {
            "first": first_profile_coverage,
            "second": second_profile_coverage,
            "minimum": minimum_module_entity_profile_coverage,
        },
    }


def entity_correlation_coverage(runtime: dict[str, Any]) -> float:
    summary = runtime.get("summary") or {}
    total = int(summary.get("entity_spawns") or 0)
    if total == 0:
        return 1.0
    unambiguous = int(summary.get("unambiguous_entity_correlations") or 0)
    return unambiguous / total


def entity_source_accounting_coverage(runtime: dict[str, Any]) -> float:
    summary = runtime.get("summary") or {}
    total = int(summary.get("entity_spawns") or 0)
    if total == 0:
        return 1.0
    mapped = int(summary.get("mapped_entity_correlations") or 0)
    return mapped / total


def shared_component_accounting_coverage(runtime: dict[str, Any]) -> float:
    summary = runtime.get("summary") or {}
    ambiguous = int(summary.get("ambiguous_component_events") or 0)
    if ambiguous == 0:
        return 1.0
    accounted = sum(
        sum(int(count) for count in (cohort.get("event_counts") or {}).values())
        for cohort in runtime.get("shared_component_event_cohorts") or []
    )
    return min(1.0, accounted / ambiguous)


def joint_entity_accounting_coverage(runtime: dict[str, Any]) -> float:
    summary = runtime.get("summary") or {}
    ambiguous = int(summary.get("ambiguous_entity_correlations") or 0)
    if ambiguous == 0:
        return 1.0
    accounted = sum(
        int(cohort.get("entity_count") or 0)
        for cohort in runtime.get("joint_entity_source_cohorts") or []
    )
    return min(1.0, accounted / ambiguous)


def component_id_in_reference_frame(
    component_id: str,
    candidate_translation: tuple[int, int, int],
) -> str:
    match = COMPONENT_ID_RE.match(str(component_id or ""))
    if match is None:
        return str(component_id or "")
    x, y, z = (int(match.group(index)) for index in (2, 3, 4))
    return (
        f"{match.group(1)}"
        f"{x - candidate_translation[0]},"
        f"{y - candidate_translation[1]},"
        f"{z - candidate_translation[2]}"
        f"{match.group(5)}"
    )


def joint_source_contract(
    cohort: dict[str, Any],
    *,
    candidate: bool,
    candidate_to_reference: dict[str, str],
    candidate_translation: tuple[int, int, int],
) -> dict[str, Any]:
    translation = candidate_translation if candidate else (0, 0, 0)
    components = sorted(
        component_id_in_reference_frame(str(value), translation)
        for value in cohort.get("candidate_dispense_components") or []
    )
    events: dict[tuple[str, str, str], list[int]] = {}
    for event in cohort.get("candidate_dispense_events") or []:
        module_id = str(event.get("module_id") or "")
        if candidate:
            module_id = candidate_to_reference.get(module_id, f"candidate:{module_id}")
        key = (
            module_id,
            component_id_in_reference_frame(
                str(event.get("component_id") or ""),
                translation,
            ),
            str(event.get("item") or ""),
        )
        events.setdefault(key, []).append(int(event.get("tick") or 0))
    for ticks in events.values():
        ticks.sort()
    return {
        "components": components,
        "event_ticks": events,
    }


def compare_tick_lists(
    first: list[int],
    second: list[int],
    max_timing_delta: int,
) -> dict[str, Any]:
    failures: list[str] = []
    if len(first) != len(second):
        failures.append("tick_count_changed")
    deltas = [
        int(right) - int(left)
        for left, right in zip(first, second)
    ]
    if any(abs(delta) > max_timing_delta for delta in deltas):
        failures.append("tick_delta_exceeded")
    return {
        "status": "PASS" if not failures else "FAIL",
        "first_count": len(first),
        "second_count": len(second),
        "max_absolute_delta": max((abs(delta) for delta in deltas), default=0),
        "failures": failures,
    }


def compare_shared_component_cohorts(
    reference_runtime: dict[str, Any],
    candidate_runtime: dict[str, Any],
    *,
    candidate_to_reference: dict[str, str],
    allowed_reference_modules: set[str],
    allowed_candidate_modules: set[str],
    max_timing_delta: int,
) -> dict[str, Any]:
    def normalize(
        runtime: dict[str, Any],
        *,
        candidate: bool,
    ) -> dict[tuple[str, ...], dict[str, Any]]:
        output: dict[tuple[str, ...], dict[str, Any]] = {}
        for cohort in runtime.get("shared_component_event_cohorts") or []:
            source_ids = [str(value) for value in cohort.get("module_ids") or []]
            if candidate:
                if set(source_ids) & allowed_candidate_modules:
                    continue
                mapped = [candidate_to_reference.get(value, f"candidate:{value}") for value in source_ids]
                if set(mapped) & allowed_reference_modules:
                    continue
            else:
                if set(source_ids) & allowed_reference_modules:
                    continue
                mapped = source_ids
            output[tuple(sorted(mapped))] = cohort
        return output

    first = normalize(reference_runtime, candidate=False)
    second = normalize(candidate_runtime, candidate=True)
    missing = sorted(set(first) - set(second))
    extra = sorted(set(second) - set(first))
    comparisons: list[dict[str, Any]] = []
    failures: list[str] = []
    if missing:
        failures.append("shared_component_cohorts_missing")
    if extra:
        failures.append("shared_component_cohorts_added")

    for module_ids in sorted(set(first) & set(second)):
        left = first[module_ids]
        right = second[module_ids]
        cohort_failures: list[str] = []
        if (left.get("event_counts") or {}) != (right.get("event_counts") or {}):
            cohort_failures.append("shared_event_counts_changed")
        event_tick_comparisons = {}
        for event in sorted(set(left.get("event_ticks") or {}) | set(right.get("event_ticks") or {})):
            tick_report = compare_tick_lists(
                [int(value) for value in (left.get("event_ticks") or {}).get(event, [])],
                [int(value) for value in (right.get("event_ticks") or {}).get(event, [])],
                max_timing_delta,
            )
            event_tick_comparisons[event] = tick_report
            if tick_report["status"] != "PASS":
                cohort_failures.append(f"shared_{event.lower()}_ticks_changed")
        comparisons.append({
            "status": "PASS" if not cohort_failures else "FAIL",
            "module_ids": list(module_ids),
            "failures": sorted(set(cohort_failures)),
            "event_counts": {
                "first": left.get("event_counts") or {},
                "second": right.get("event_counts") or {},
            },
            "event_ticks": event_tick_comparisons,
        })
        failures.extend(cohort_failures)

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": sorted(set(failures)),
        "missing_module_sets": [list(value) for value in missing],
        "extra_module_sets": [list(value) for value in extra],
        "comparisons": comparisons,
    }




def compare_joint_entity_cohorts(
    reference_runtime: dict[str, Any],
    candidate_runtime: dict[str, Any],
    *,
    candidate_to_reference: dict[str, str],
    candidate_translation: tuple[int, int, int],
    allowed_reference_modules: set[str],
    allowed_candidate_modules: set[str],
    max_timing_delta: int,
    max_spawn_position_delta: float,
    max_spawn_velocity_delta: float,
    max_fuse_delta: int,
    max_explosion_position_delta: float,
) -> dict[str, Any]:
    def normalize_groups(
        runtime: dict[str, Any],
        *,
        candidate: bool,
    ) -> dict[tuple[tuple[str, ...], str], list[dict[str, Any]]]:
        output: dict[tuple[tuple[str, ...], str], list[dict[str, Any]]] = {}
        for cohort in runtime.get("joint_entity_source_cohorts") or []:
            source_ids = [
                str(value)
                for value in cohort.get("candidate_module_ids") or []
            ]
            if candidate:
                if set(source_ids) & allowed_candidate_modules:
                    continue
                mapped = [
                    candidate_to_reference.get(value, f"candidate:{value}")
                    for value in source_ids
                ]
                if set(mapped) & allowed_reference_modules:
                    continue
            else:
                if set(source_ids) & allowed_reference_modules:
                    continue
                mapped = source_ids
            key = (
                tuple(sorted(mapped)),
                str(cohort.get("entity_type") or "UNKNOWN"),
            )
            output.setdefault(key, []).append(cohort)
        for cohorts in output.values():
            cohorts.sort(key=lambda row: (
                int(row.get("spawn_tick") or 0),
                tuple(point_in_reference_frame(
                    row.get("spawn_point") or [],
                    candidate_translation if candidate else (0, 0, 0),
                )),
                int(row.get("entity_count") or 0),
                len(row.get("candidate_dispense_components") or []),
            ))
        return output

    first = normalize_groups(reference_runtime, candidate=False)
    second = normalize_groups(candidate_runtime, candidate=True)
    failures: list[str] = []
    comparisons: list[dict[str, Any]] = []
    missing_keys = sorted(set(first) - set(second))
    extra_keys = sorted(set(second) - set(first))
    if missing_keys:
        failures.append("joint_entity_cohort_families_missing")
    if extra_keys:
        failures.append("joint_entity_cohort_families_added")

    for key in sorted(set(first) & set(second)):
        left_rows = first[key]
        right_rows = second[key]
        family_failures: list[str] = []
        if len(left_rows) != len(right_rows):
            family_failures.append("joint_entity_cohort_count_changed")
        pair_rows: list[dict[str, Any]] = []
        for left, right in zip(left_rows, right_rows):
            pair_failures: list[str] = []
            left_sources = joint_source_contract(
                left,
                candidate=False,
                candidate_to_reference=candidate_to_reference,
                candidate_translation=(0, 0, 0),
            )
            right_sources = joint_source_contract(
                right,
                candidate=True,
                candidate_to_reference=candidate_to_reference,
                candidate_translation=candidate_translation,
            )
            spawn_tick_delta = int(right.get("spawn_tick") or 0) - int(left.get("spawn_tick") or 0)
            left_point = point_in_reference_frame(left.get("spawn_point") or [], (0, 0, 0))
            right_point = point_in_reference_frame(
                right.get("spawn_point") or [],
                candidate_translation,
            )
            spawn_position_delta = math.dist(left_point, right_point)
            velocity_delta = math.dist(
                [float(value) for value in left.get("mean_velocity") or [0.0, 0.0, 0.0]],
                [float(value) for value in right.get("mean_velocity") or [0.0, 0.0, 0.0]],
            )
            if abs(spawn_tick_delta) > max_timing_delta:
                pair_failures.append("joint_spawn_tick_delta_exceeded")
            if spawn_position_delta > max_spawn_position_delta:
                pair_failures.append("joint_spawn_position_delta_exceeded")
            if velocity_delta > max_spawn_velocity_delta:
                pair_failures.append("joint_spawn_velocity_delta_exceeded")
            if int(left.get("entity_count") or 0) != int(right.get("entity_count") or 0):
                pair_failures.append("joint_entity_count_changed")
            if left_sources["components"] != right_sources["components"]:
                pair_failures.append("joint_candidate_dispenser_sources_changed")
            left_event_keys = set(left_sources["event_ticks"])
            right_event_keys = set(right_sources["event_ticks"])
            if left_event_keys != right_event_keys:
                pair_failures.append("joint_candidate_dispense_events_changed")
            source_timing: list[dict[str, Any]] = []
            for event_key in sorted(left_event_keys & right_event_keys):
                tick_report = compare_tick_lists(
                    left_sources["event_ticks"][event_key],
                    right_sources["event_ticks"][event_key],
                    max_timing_delta,
                )
                source_timing.append({
                    "module_id": event_key[0],
                    "component_id": event_key[1],
                    "item": event_key[2],
                    "timing": tick_report,
                })
                if tick_report["status"] != "PASS":
                    pair_failures.append("joint_candidate_dispense_timing_changed")
            if (left.get("fuse_counts") or {}) != (right.get("fuse_counts") or {}):
                left_fuses = sorted(
                    (int(value), int(count))
                    for value, count in (left.get("fuse_counts") or {}).items()
                )
                right_fuses = sorted(
                    (int(value), int(count))
                    for value, count in (right.get("fuse_counts") or {}).items()
                )
                if len(left_fuses) != len(right_fuses) or any(
                    left_count != right_count
                    or abs(right_value - left_value) > max_fuse_delta
                    for (left_value, left_count), (right_value, right_count)
                    in zip(left_fuses, right_fuses)
                ):
                    pair_failures.append("joint_fuse_distribution_changed")
            explosion_ticks = compare_tick_lists(
                sorted([
                    int(tick)
                    for tick, count in (left.get("explosion_ticks") or {}).items()
                    for _ in range(int(count))
                ]),
                sorted([
                    int(tick)
                    for tick, count in (right.get("explosion_ticks") or {}).items()
                    for _ in range(int(count))
                ]),
                max_timing_delta,
            )
            if explosion_ticks["status"] != "PASS":
                pair_failures.append("joint_explosion_tick_distribution_changed")
            if int(left.get("explosion_event_count") or 0) != int(right.get("explosion_event_count") or 0):
                pair_failures.append("joint_explosion_event_count_changed")
            physics = compare_entity_profiles(
                {"correlated_entity_profiles": left.get("entity_profiles") or []},
                {"correlated_entity_profiles": right.get("entity_profiles") or []},
                candidate_translation=candidate_translation,
                max_timing_delta=max_timing_delta,
                max_spawn_position_delta=max_spawn_position_delta,
                max_spawn_velocity_delta=max_spawn_velocity_delta,
                max_fuse_delta=max_fuse_delta,
                max_explosion_position_delta=max_explosion_position_delta,
            )
            if physics["status"] != "PASS":
                pair_failures.extend(
                    f"joint_{failure}"
                    for failure in physics["failures"]
                )
            pair_rows.append({
                "status": "PASS" if not pair_failures else "FAIL",
                "failures": sorted(set(pair_failures)),
                "spawn_tick": {
                    "first": left.get("spawn_tick"),
                    "second": right.get("spawn_tick"),
                    "delta": spawn_tick_delta,
                },
                "spawn_point": {
                    "first": left_point,
                    "second": right_point,
                    "distance": round(spawn_position_delta, 8),
                },
                "entity_count": {
                    "first": left.get("entity_count"),
                    "second": right.get("entity_count"),
                },
                "source_components": {
                    "first": left_sources["components"],
                    "second": right_sources["components"],
                },
                "source_event_timing": source_timing,
                "explosion_timing": explosion_ticks,
                "physics": physics,
            })
            family_failures.extend(pair_failures)
        comparisons.append({
            "status": "PASS" if not family_failures else "FAIL",
            "module_ids": list(key[0]),
            "entity_type": key[1],
            "first_cohort_count": len(left_rows),
            "second_cohort_count": len(right_rows),
            "failures": sorted(set(family_failures)),
            "pairs": pair_rows,
        })
        failures.extend(family_failures)

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": sorted(set(failures)),
        "missing_families": [
            {"module_ids": list(key[0]), "entity_type": key[1]}
            for key in missing_keys
        ],
        "extra_families": [
            {"module_ids": list(key[0]), "entity_type": key[1]}
            for key in extra_keys
        ],
        "comparisons": comparisons,
    }

def build_report(
    reference_schematic: Path,
    reference_trace: Path,
    candidate_schematic: Path,
    candidate_trace: Path,
    *,
    chunk_limit: int = 160,
    assignment_radius: int = 6,
    correlation_ticks: int = 2,
    spawn_radius: float = 3.0,
    max_timing_delta: int = 2,
    max_spawn_position_delta: float = 0.25,
    max_spawn_velocity_delta: float = 0.02,
    max_fuse_delta: int = 1,
    max_explosion_position_delta: float = 1.0,
    minimum_component_event_coverage: float = 0.95,
    minimum_entity_correlation_coverage: float = 0.0,
    minimum_entity_source_accounting_coverage: float = 0.95,
    minimum_shared_component_accounting_coverage: float = 0.95,
    minimum_joint_entity_accounting_coverage: float = 0.95,
    minimum_module_entity_profile_coverage: float = 0.0,
    max_ambiguous_component_events: int = 1_000_000,
    minimum_pairing_confidence: str = "high",
    max_pairing_residual_distance: int = 0,
    allow_ambiguous_pairing: bool = False,
    minimum_unchanged_runtime_contracts: int = 1,
    allowed_reference_modules: set[str] | None = None,
    allowed_candidate_modules: set[str] | None = None,
    max_extra_active_candidate_modules: int = 0,
    require_event_counts_equal: bool = True,
    require_items_equal: bool = True,
    require_entity_types_equal: bool = True,
    require_explosion_counts_equal: bool = True,
    require_entity_physics_equal: bool = True,
    require_shared_component_cohorts_equal: bool = True,
    require_joint_entity_cohorts_equal: bool = True,
) -> dict[str, Any]:
    allowed_reference_modules = set(allowed_reference_modules or set())
    allowed_candidate_modules = set(allowed_candidate_modules or set())
    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    if minimum_pairing_confidence not in confidence_rank:
        raise ValueError("minimum_pairing_confidence must be low, medium, or high")
    comparator = load_script("cannonlab_compare_modules", "compare-cannon-modules.py")
    analyzer = load_script("cannonlab_analyze_module_trace", "analyze-module-trace.py")

    geometry = comparator.build_report(
        reference_schematic,
        candidate_schematic,
        chunk_limit=chunk_limit,
        assignment_radius=assignment_radius,
    )
    reference_runtime = cached_runtime_analysis(
        analyzer,
        reference_schematic,
        reference_trace,
        chunk_limit=chunk_limit,
        assignment_radius=assignment_radius,
        correlation_ticks=correlation_ticks,
        spawn_radius=spawn_radius,
    )
    candidate_runtime = cached_runtime_analysis(
        analyzer,
        candidate_schematic,
        candidate_trace,
        chunk_limit=chunk_limit,
        assignment_radius=assignment_radius,
        correlation_ticks=correlation_ticks,
        spawn_radius=spawn_radius,
    )

    reference_modules = {
        str(module.get("module_id")): module
        for module in reference_runtime.get("modules") or []
    }
    candidate_modules = {
        str(module.get("module_id")): module
        for module in candidate_runtime.get("modules") or []
    }
    unknown_allowed_modules = sorted(
        allowed_reference_modules - set(reference_modules)
    )
    unknown_allowed_candidate_modules = sorted(
        allowed_candidate_modules - set(candidate_modules)
    )

    exact_pairs: list[dict[str, Any]] = []
    for family in geometry.get("exact_module_matches") or []:
        for pair in family.get("pairs") or []:
            raw_translation = pair.get("translation_vector") or [0, 0, 0]
            exact_pairs.append({
                "reference_id": str(pair.get("first_module_id")),
                "candidate_id": str(pair.get("second_module_id")),
                "translation": tuple(map(int, raw_translation[:3])),
            })
    candidate_to_reference = {
        pair["candidate_id"]: pair["reference_id"]
        for pair in exact_pairs
    }
    reference_to_candidate = {
        pair["reference_id"]: pair["candidate_id"]
        for pair in exact_pairs
    }
    effective_allowed_reference_modules = {
        *allowed_reference_modules,
        *(
            candidate_to_reference[module_id]
            for module_id in allowed_candidate_modules
            if module_id in candidate_to_reference
        ),
    }
    effective_allowed_candidate_modules = {
        *allowed_candidate_modules,
        *(
            reference_to_candidate[module_id]
            for module_id in allowed_reference_modules
            if module_id in reference_to_candidate
        ),
    }
    translation_report = geometry.get("translation_alignment") or {}
    selected_translation_raw = translation_report.get("selected") or [0, 0, 0]
    selected_translation = tuple(map(int, selected_translation_raw[:3]))

    contracts: list[dict[str, Any]] = []
    matched_reference: set[str] = set()
    matched_candidate: set[str] = set()
    for pair in exact_pairs:
        reference_id = pair["reference_id"]
        candidate_id = pair["candidate_id"]
        translation = pair["translation"]
        reference_module = reference_modules.get(reference_id)
        candidate_module = candidate_modules.get(candidate_id)
        if reference_module is None or candidate_module is None:
            continue
        matched_reference.add(reference_id)
        matched_candidate.add(candidate_id)
        if (
            reference_id in allowed_reference_modules
            or candidate_id in allowed_candidate_modules
        ):
            contracts.append({
                "status": "ALLOWED_CHANGE",
                "first_module_id": reference_id,
                "second_module_id": candidate_id,
                "signature": reference_module.get("signature"),
                "candidate_translation": list(translation),
                "failures": [],
                "note": "reference module was explicitly excluded from the unchanged runtime contract",
            })
            continue
        contracts.append(compare_runtime_module(
            reference_module,
            candidate_module,
            candidate_translation=translation,
            max_timing_delta=max_timing_delta,
            max_spawn_position_delta=max_spawn_position_delta,
            max_spawn_velocity_delta=max_spawn_velocity_delta,
            max_fuse_delta=max_fuse_delta,
            max_explosion_position_delta=max_explosion_position_delta,
            minimum_module_entity_profile_coverage=minimum_module_entity_profile_coverage,
            require_event_counts_equal=require_event_counts_equal,
            require_items_equal=require_items_equal,
            require_entity_types_equal=require_entity_types_equal,
            require_explosion_counts_equal=require_explosion_counts_equal,
            require_entity_physics_equal=require_entity_physics_equal,
        ))

    shared_component_contract = compare_shared_component_cohorts(
        reference_runtime,
        candidate_runtime,
        candidate_to_reference=candidate_to_reference,
        allowed_reference_modules=effective_allowed_reference_modules,
        allowed_candidate_modules=effective_allowed_candidate_modules,
        max_timing_delta=max_timing_delta,
    )
    joint_entity_contract = compare_joint_entity_cohorts(
        reference_runtime,
        candidate_runtime,
        candidate_to_reference=candidate_to_reference,
        candidate_translation=selected_translation,
        allowed_reference_modules=effective_allowed_reference_modules,
        allowed_candidate_modules=effective_allowed_candidate_modules,
        max_timing_delta=max_timing_delta,
        max_spawn_position_delta=max_spawn_position_delta,
        max_spawn_velocity_delta=max_spawn_velocity_delta,
        max_fuse_delta=max_fuse_delta,
        max_explosion_position_delta=max_explosion_position_delta,
    )

    active_reference = {
        module_id
        for module_id, module in reference_modules.items()
        if module.get("active")
    }
    active_candidate = {
        module_id
        for module_id, module in candidate_modules.items()
        if module.get("active")
    }
    unmatched_reference_active = sorted(
        active_reference - matched_reference - allowed_reference_modules
    )
    unmatched_candidate_active = sorted(
        active_candidate - matched_candidate - allowed_candidate_modules
    )

    failures: list[str] = []
    pairing_confidence = str(translation_report.get("pairing_confidence") or "low")
    pairing_residual = int(translation_report.get("max_residual_distance") or 0)
    if confidence_rank.get(pairing_confidence, -1) < confidence_rank[minimum_pairing_confidence]:
        failures.append("module_pairing_confidence_below_minimum")
    if pairing_residual > max_pairing_residual_distance:
        failures.append("module_pairing_residual_exceeded")
    if translation_report.get("ambiguous_top_vote") and not allow_ambiguous_pairing:
        failures.append("ambiguous_module_pairing_translation")
    failed_contracts = [row for row in contracts if row.get("status") == "FAIL"]
    if unknown_allowed_modules:
        failures.append("unknown_allowed_reference_modules")
    if unknown_allowed_candidate_modules:
        failures.append("unknown_allowed_candidate_modules")
    if failed_contracts:
        failures.append("unchanged_module_runtime_contract_failed")
    if require_shared_component_cohorts_equal and shared_component_contract["status"] != "PASS":
        failures.append("shared_component_cohort_contract_failed")
    if require_joint_entity_cohorts_equal and joint_entity_contract["status"] != "PASS":
        failures.append("joint_entity_cohort_contract_failed")
    protected_contracts = [
        row for row in contracts if row.get("status") != "ALLOWED_CHANGE"
    ]
    if len(protected_contracts) < minimum_unchanged_runtime_contracts:
        failures.append("minimum_unchanged_runtime_contracts_not_met")
    if unmatched_reference_active:
        failures.append("active_reference_modules_lost_exact_geometry")
    if len(unmatched_candidate_active) > max_extra_active_candidate_modules:
        failures.append("extra_active_candidate_modules_exceeded")

    reference_summary = reference_runtime.get("summary") or {}
    candidate_summary = candidate_runtime.get("summary") or {}
    reference_coverage = float(reference_summary.get("component_event_coverage") or 0.0)
    candidate_coverage = float(candidate_summary.get("component_event_coverage") or 0.0)
    reference_entity_coverage = entity_correlation_coverage(reference_runtime)
    candidate_entity_coverage = entity_correlation_coverage(candidate_runtime)
    reference_source_accounting = entity_source_accounting_coverage(reference_runtime)
    candidate_source_accounting = entity_source_accounting_coverage(candidate_runtime)
    reference_shared_accounting = shared_component_accounting_coverage(reference_runtime)
    candidate_shared_accounting = shared_component_accounting_coverage(candidate_runtime)
    reference_joint_accounting = joint_entity_accounting_coverage(reference_runtime)
    candidate_joint_accounting = joint_entity_accounting_coverage(candidate_runtime)
    reference_ambiguous_components = int(reference_summary.get("ambiguous_component_events") or 0)
    candidate_ambiguous_components = int(candidate_summary.get("ambiguous_component_events") or 0)

    if reference_coverage < minimum_component_event_coverage:
        failures.append("reference_component_event_coverage_too_low")
    if candidate_coverage < minimum_component_event_coverage:
        failures.append("candidate_component_event_coverage_too_low")
    if reference_entity_coverage < minimum_entity_correlation_coverage:
        failures.append("reference_entity_correlation_coverage_too_low")
    if candidate_entity_coverage < minimum_entity_correlation_coverage:
        failures.append("candidate_entity_correlation_coverage_too_low")
    if reference_source_accounting < minimum_entity_source_accounting_coverage:
        failures.append("reference_entity_source_accounting_coverage_too_low")
    if candidate_source_accounting < minimum_entity_source_accounting_coverage:
        failures.append("candidate_entity_source_accounting_coverage_too_low")
    if reference_shared_accounting < minimum_shared_component_accounting_coverage:
        failures.append("reference_shared_component_accounting_coverage_too_low")
    if candidate_shared_accounting < minimum_shared_component_accounting_coverage:
        failures.append("candidate_shared_component_accounting_coverage_too_low")
    if reference_joint_accounting < minimum_joint_entity_accounting_coverage:
        failures.append("reference_joint_entity_accounting_coverage_too_low")
    if candidate_joint_accounting < minimum_joint_entity_accounting_coverage:
        failures.append("candidate_joint_entity_accounting_coverage_too_low")
    if reference_ambiguous_components > max_ambiguous_component_events:
        failures.append("reference_ambiguous_component_events_exceeded")
    if candidate_ambiguous_components > max_ambiguous_component_events:
        failures.append("candidate_ambiguous_component_events_exceeded")

    return {
        "status": "PASS" if not failures else "FAIL",
        "schema": "cannonlab-module-runtime-contract-v3",
        "reference": {
            "schematic": str(reference_schematic),
            "trace": str(reference_trace),
            "schematic_sha256": reference_runtime.get("schematic_sha256"),
        },
        "candidate": {
            "schematic": str(candidate_schematic),
            "trace": str(candidate_trace),
            "schematic_sha256": candidate_runtime.get("schematic_sha256"),
        },
        "policy": {
            "chunk_limit": chunk_limit,
            "assignment_radius": assignment_radius,
            "correlation_ticks": correlation_ticks,
            "spawn_radius": spawn_radius,
            "max_timing_delta": max_timing_delta,
            "max_spawn_position_delta": max_spawn_position_delta,
            "max_spawn_velocity_delta": max_spawn_velocity_delta,
            "max_fuse_delta": max_fuse_delta,
            "max_explosion_position_delta": max_explosion_position_delta,
            "minimum_component_event_coverage": minimum_component_event_coverage,
            "minimum_entity_correlation_coverage": minimum_entity_correlation_coverage,
            "minimum_entity_source_accounting_coverage": minimum_entity_source_accounting_coverage,
            "minimum_shared_component_accounting_coverage": minimum_shared_component_accounting_coverage,
            "minimum_joint_entity_accounting_coverage": minimum_joint_entity_accounting_coverage,
            "minimum_module_entity_profile_coverage": minimum_module_entity_profile_coverage,
            "max_ambiguous_component_events": max_ambiguous_component_events,
            "minimum_pairing_confidence": minimum_pairing_confidence,
            "max_pairing_residual_distance": max_pairing_residual_distance,
            "allow_ambiguous_pairing": allow_ambiguous_pairing,
            "minimum_unchanged_runtime_contracts": minimum_unchanged_runtime_contracts,
            "allowed_reference_modules": sorted(allowed_reference_modules),
            "allowed_candidate_modules": sorted(allowed_candidate_modules),
            "max_extra_active_candidate_modules": max_extra_active_candidate_modules,
            "require_event_counts_equal": require_event_counts_equal,
            "require_items_equal": require_items_equal,
            "require_entity_types_equal": require_entity_types_equal,
            "require_explosion_counts_equal": require_explosion_counts_equal,
            "require_entity_physics_equal": require_entity_physics_equal,
            "require_shared_component_cohorts_equal": require_shared_component_cohorts_equal,
            "require_joint_entity_cohorts_equal": require_joint_entity_cohorts_equal,
        },
        "summary": {
            "exact_geometry_pairs": len(exact_pairs),
            "runtime_contracts": len(contracts),
            "failed_runtime_contracts": len(failed_contracts),
            "protected_runtime_contracts": len(protected_contracts),
            "active_reference_modules": len(active_reference),
            "active_candidate_modules": len(active_candidate),
            "unmatched_reference_active_modules": len(unmatched_reference_active),
            "unmatched_candidate_active_modules": len(unmatched_candidate_active),
            "reference_component_event_coverage": round(reference_coverage, 6),
            "candidate_component_event_coverage": round(candidate_coverage, 6),
            "reference_entity_correlation_coverage": round(reference_entity_coverage, 6),
            "candidate_entity_correlation_coverage": round(candidate_entity_coverage, 6),
            "reference_entity_source_accounting_coverage": round(reference_source_accounting, 6),
            "candidate_entity_source_accounting_coverage": round(candidate_source_accounting, 6),
            "reference_shared_component_accounting_coverage": round(reference_shared_accounting, 6),
            "candidate_shared_component_accounting_coverage": round(candidate_shared_accounting, 6),
            "reference_joint_entity_accounting_coverage": round(reference_joint_accounting, 6),
            "candidate_joint_entity_accounting_coverage": round(candidate_joint_accounting, 6),
            "shared_component_cohort_contract_status": shared_component_contract["status"],
            "joint_entity_cohort_contract_status": joint_entity_contract["status"],
            "reference_ambiguous_component_events": reference_ambiguous_components,
            "candidate_ambiguous_component_events": candidate_ambiguous_components,
            "module_pairing_confidence": pairing_confidence,
            "module_pairing_max_residual_distance": pairing_residual,
            "module_pairing_ambiguous_top_vote": bool(
                translation_report.get("ambiguous_top_vote")
            ),
        },
        "failures": sorted(set(failures)),
        "unknown_allowed_reference_modules": unknown_allowed_modules,
        "unknown_allowed_candidate_modules": unknown_allowed_candidate_modules,
        "module_runtime_contracts": contracts,
        "shared_component_cohort_contract": shared_component_contract,
        "joint_entity_cohort_contract": joint_entity_contract,
        "unmatched_reference_active_modules": unmatched_reference_active,
        "unmatched_candidate_active_modules": unmatched_candidate_active,
        "geometry_summary": geometry.get("summary"),
        "geometry_translation": translation_report,
        "reference_runtime_summary": reference_summary,
        "candidate_runtime_summary": candidate_summary,
        "truth_boundary": (
            "PASS proves that exact-geometry modules outside the declared change set replayed within the configured "
            "local timing, cohort, spawn, velocity, fuse and explosion-position contract. It does not prove the "
            "edited module is correct, wall-busting performance, private ExtremeCraft parity, or live EC readiness."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail when untouched exact cannon modules stop replaying their reference runtime behavior"
    )
    parser.add_argument("reference_schematic", type=Path)
    parser.add_argument("reference_trace", type=Path)
    parser.add_argument("candidate_schematic", type=Path)
    parser.add_argument("candidate_trace", type=Path)
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--assignment-radius", type=int, default=6)
    parser.add_argument("--correlation-ticks", type=int, default=2)
    parser.add_argument("--spawn-radius", type=float, default=3.0)
    parser.add_argument("--max-timing-delta", type=int, default=2)
    parser.add_argument("--max-spawn-position-delta", type=float, default=0.25)
    parser.add_argument("--max-spawn-velocity-delta", type=float, default=0.02)
    parser.add_argument("--max-fuse-delta", type=int, default=1)
    parser.add_argument("--max-explosion-position-delta", type=float, default=1.0)
    parser.add_argument("--minimum-component-event-coverage", type=float, default=0.95)
    parser.add_argument("--minimum-entity-correlation-coverage", type=float, default=0.0)
    parser.add_argument("--minimum-entity-source-accounting-coverage", type=float, default=0.95)
    parser.add_argument("--minimum-shared-component-accounting-coverage", type=float, default=0.95)
    parser.add_argument("--minimum-joint-entity-accounting-coverage", type=float, default=0.95)
    parser.add_argument("--minimum-module-entity-profile-coverage", type=float, default=0.0)
    parser.add_argument("--max-ambiguous-component-events", type=int, default=1_000_000)
    parser.add_argument(
        "--minimum-pairing-confidence",
        choices=("low", "medium", "high"),
        default="high",
    )
    parser.add_argument("--max-pairing-residual-distance", type=int, default=0)
    parser.add_argument("--allow-ambiguous-pairing", action="store_true")
    parser.add_argument("--minimum-unchanged-runtime-contracts", type=int, default=1)
    parser.add_argument("--allow-reference-module", action="append", default=[])
    parser.add_argument("--allow-candidate-module", action="append", default=[])
    parser.add_argument("--max-extra-active-candidate-modules", type=int, default=0)
    parser.add_argument("--allow-event-count-changes", action="store_true")
    parser.add_argument("--allow-dispensed-item-changes", action="store_true")
    parser.add_argument("--allow-entity-type-changes", action="store_true")
    parser.add_argument("--allow-explosion-count-changes", action="store_true")
    parser.add_argument("--allow-entity-physics-changes", action="store_true")
    parser.add_argument("--allow-shared-component-cohort-changes", action="store_true")
    parser.add_argument("--allow-joint-entity-cohort-changes", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_report(
        args.reference_schematic,
        args.reference_trace,
        args.candidate_schematic,
        args.candidate_trace,
        chunk_limit=args.chunk_limit,
        assignment_radius=args.assignment_radius,
        correlation_ticks=args.correlation_ticks,
        spawn_radius=args.spawn_radius,
        max_timing_delta=args.max_timing_delta,
        max_spawn_position_delta=args.max_spawn_position_delta,
        max_spawn_velocity_delta=args.max_spawn_velocity_delta,
        max_fuse_delta=args.max_fuse_delta,
        max_explosion_position_delta=args.max_explosion_position_delta,
        minimum_component_event_coverage=args.minimum_component_event_coverage,
        minimum_entity_correlation_coverage=args.minimum_entity_correlation_coverage,
        minimum_entity_source_accounting_coverage=args.minimum_entity_source_accounting_coverage,
        minimum_shared_component_accounting_coverage=args.minimum_shared_component_accounting_coverage,
        minimum_joint_entity_accounting_coverage=args.minimum_joint_entity_accounting_coverage,
        minimum_module_entity_profile_coverage=args.minimum_module_entity_profile_coverage,
        max_ambiguous_component_events=args.max_ambiguous_component_events,
        minimum_pairing_confidence=args.minimum_pairing_confidence,
        max_pairing_residual_distance=args.max_pairing_residual_distance,
        allow_ambiguous_pairing=args.allow_ambiguous_pairing,
        minimum_unchanged_runtime_contracts=args.minimum_unchanged_runtime_contracts,
        allowed_reference_modules=set(args.allow_reference_module),
        allowed_candidate_modules=set(args.allow_candidate_module),
        max_extra_active_candidate_modules=args.max_extra_active_candidate_modules,
        require_event_counts_equal=not args.allow_event_count_changes,
        require_items_equal=not args.allow_dispensed_item_changes,
        require_entity_types_equal=not args.allow_entity_type_changes,
        require_explosion_counts_equal=not args.allow_explosion_count_changes,
        require_entity_physics_equal=not args.allow_entity_physics_changes,
        require_shared_component_cohorts_equal=not args.allow_shared_component_cohort_changes,
        require_joint_entity_cohorts_equal=not args.allow_joint_entity_cohort_changes,
    )
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
