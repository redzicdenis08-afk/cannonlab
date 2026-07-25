#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


LEVELS = ["STATIC", "LOCAL_CAUSAL", "LOCAL_ENDURANCE", "FIELD_CANARY", "FIELD_READY"]
PROVEN_PARITY_STATUSES = {"measured", "field-verified"}


class RaidPlanError(ValueError):
    pass


def read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RaidPlanError(f"unable to read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RaidPlanError(f"expected a JSON object in {path}")
    return payload


def level_index(level: str) -> int:
    try:
        return LEVELS.index(level)
    except ValueError as exc:
        raise RaidPlanError(f"unsupported evidence level {level!r}") from exc


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def expand_modules(grammar: dict[str, Any], objective: dict[str, Any]) -> list[dict[str, Any]]:
    module_rows = grammar.get("modules") or []
    modules = {str(row.get("id")): row for row in module_rows}
    if len(modules) != len(module_rows):
        raise RaidPlanError("grammar contains duplicate module IDs")

    requested = list(objective.get("required_modules") or [])
    requested.extend(objective.get("enabled_conditional_modules") or [])
    if not requested:
        raise RaidPlanError("raid objective must request at least one module")
    unknown = sorted(set(requested) - set(modules))
    if unknown:
        raise RaidPlanError(f"raid objective references unknown modules: {unknown}")

    desired_level = str(objective.get("desired_module_level", "FIELD_READY"))
    desired_index = level_index(desired_level)
    evidence = objective.get("available_module_evidence") or {}
    if not isinstance(evidence, dict):
        raise RaidPlanError("available_module_evidence must be an object")
    for module_id, level in evidence.items():
        if module_id not in modules:
            raise RaidPlanError(f"module evidence references unknown module {module_id!r}")
        level_index(str(level))

    visiting: set[str] = set()
    visited: set[str] = set()
    order: list[str] = []
    fixture_requirements: dict[str, list[str]] = {}

    def visit(module_id: str) -> None:
        if module_id in visited:
            return
        if module_id in visiting:
            raise RaidPlanError(f"module dependency cycle at {module_id}")
        visiting.add(module_id)
        external: list[str] = []
        for dependency in modules[module_id].get("requires", []):
            dependency = str(dependency)
            if dependency in modules:
                visit(dependency)
            else:
                external.append(dependency)
        fixture_requirements[module_id] = sorted(set(external))
        visiting.remove(module_id)
        visited.add(module_id)
        order.append(module_id)

    for module_id in requested:
        visit(module_id)

    stages: list[dict[str, Any]] = []
    for module_id in order:
        row = modules[module_id]
        current_level = str(evidence.get(module_id, "UNPROVEN"))
        current_index = level_index(current_level) if current_level != "UNPROVEN" else -1
        action = "REUSE_EVIDENCE" if current_index >= desired_index else "PROVE_MODULE"
        stages.append(
            {
                "order": len(stages) + 1,
                "module": module_id,
                "action": action,
                "current_level": current_level,
                "required_level": desired_level,
                "dependencies": [
                    dependency
                    for dependency in row.get("requires", [])
                    if dependency in modules
                ],
                "fixture_requirements": fixture_requirements[module_id],
                "expected_outputs": row.get("outputs", []),
                "acceptance_evidence": row.get("minimum_evidence", []),
                "stop_on_failures": row.get("failure_signals", []),
            }
        )
    return stages


def build_throughput(objective: dict[str, Any]) -> dict[str, Any]:
    target = objective.get("objective") or {}
    operations = objective.get("operations") or {}
    wall_groups = target.get("wall_group_count")
    shots_per_wall = operations.get("shots_per_wall_group")
    interval = operations.get("fire_interval_seconds")
    reload_overhead = operations.get("reload_overhead_seconds_per_shot")
    target_minutes = operations.get("target_raid_time_minutes")

    required = {
        "wall_group_count": wall_groups,
        "shots_per_wall_group": shots_per_wall,
        "fire_interval_seconds": interval,
        "reload_overhead_seconds_per_shot": reload_overhead,
    }
    missing = sorted(key for key, value in required.items() if not _is_number(value))
    if missing:
        return {
            "status": "UNCOMPUTED",
            "missing_inputs": missing,
            "uses_buffer_depth_as_wall_count": False,
            "truth_boundary": {
                "throughput_includes_live_patching": False,
                "throughput_includes_unknown_regeneration": False,
            },
        }

    if wall_groups <= 0 or shots_per_wall <= 0 or interval < 0 or reload_overhead < 0:
        raise RaidPlanError("throughput inputs must be positive, with non-negative timing values")
    total_shots = int(wall_groups * shots_per_wall)
    cycle_seconds = float(interval + reload_overhead)
    theoretical_seconds = total_shots * cycle_seconds
    report: dict[str, Any] = {
        "status": "THEORETICAL_ONLY",
        "wall_group_count": int(wall_groups),
        "shots_per_wall_group": float(shots_per_wall),
        "total_shots": total_shots,
        "shot_cycle_seconds": cycle_seconds,
        "theoretical_seconds": theoretical_seconds,
        "theoretical_minutes": theoretical_seconds / 60.0,
        "uses_buffer_depth_as_wall_count": False,
        "truth_boundary": {
            "throughput_includes_live_patching": False,
            "throughput_includes_unknown_regeneration": False,
            "throughput_proves_raid_completion": False,
        },
    }
    if _is_number(target_minutes) and target_minutes > 0:
        budget_seconds = float(target_minutes) * 60.0
        report["target_raid_time_minutes"] = float(target_minutes)
        report["time_margin_seconds"] = budget_seconds - theoretical_seconds
        report["meets_theoretical_time_budget"] = theoretical_seconds <= budget_seconds
    return report


def build_plan(
    grammar: dict[str, Any],
    parity: dict[str, Any],
    objective: dict[str, Any],
) -> dict[str, Any]:
    if grammar.get("id") != "modern-factions-cannon-grammar-v1":
        raise RaidPlanError("unexpected cannon grammar")
    if parity.get("id") != "extremecraft-private-parity-required-v1":
        raise RaidPlanError("unexpected ExtremeCraft parity profile")
    if objective.get("id") != "extremecraft-15-chunk-regen-objective-v1":
        raise RaidPlanError("unexpected raid objective")

    target = objective.get("objective") or {}
    operations = objective.get("operations") or {}
    constraints = objective.get("constraints") or {}
    truth = objective.get("truth_boundary") or {}
    if target.get("buffer_depth_chunks") != 15:
        raise RaidPlanError("the canonical objective must preserve the fifteen-chunk buffer target")
    if truth.get("fifteen_chunks_equals_240_block_projectile_distance") is not False:
        raise RaidPlanError("raid objective must not collapse fifteen chunks into a projectile distance")
    if constraints.get("maximum_dispensers_per_xz_chunk_column") != 160:
        raise RaidPlanError("raid objective must preserve the current field-reported EC160 limit")
    if constraints.get("required_chunk_alignment_offsets") != 256:
        raise RaidPlanError("raid objective must require all 256 X/Z chunk offsets")

    parity_dimensions = parity.get("dimensions") or []
    parity_missing = [
        str(row.get("id"))
        for row in parity_dimensions
        if str(row.get("status", "unknown")) not in PROVEN_PARITY_STATUSES
    ]
    module_stages = expand_modules(grammar, objective)
    unproven_modules = [
        row["module"] for row in module_stages if row["action"] == "PROVE_MODULE"
    ]

    measurement_fields = {
        "regen_depth_chunks": target.get("regen_depth_chunks"),
        "exact_muzzle_to_first_target_blocks": target.get("exact_muzzle_to_first_target_blocks"),
        "exact_muzzle_to_core_blocks": target.get("exact_muzzle_to_core_blocks"),
        "wall_group_count": target.get("wall_group_count"),
        "target_height_min": target.get("target_height_min"),
        "target_height_max": target.get("target_height_max"),
        "target_lane": target.get("target_lane"),
    }
    missing_measurements = sorted(
        key for key, value in measurement_fields.items() if value is None
    )
    unknown_rules = sorted(
        key
        for key in (
            "one_wall_per_press_rule",
            "automatic_cannoning_rule",
            "allowed_reverse_or_left_right_rules",
            "patching_pressure_model",
        )
        if str(operations.get(key, "unknown-current")).startswith("unknown")
    )
    constraint_blockers = []
    if constraints.get("fawe_block_entity_limit") is None:
        constraint_blockers.append("fawe_block_entity_limit")
    if constraints.get("exact_field_workflow_required") is not True:
        raise RaidPlanError("exact field workflow must remain mandatory")

    blockers = {
        "private_parity_dimensions": parity_missing,
        "course_measurements": missing_measurements,
        "operational_rules": unknown_rules,
        "paste_constraints": constraint_blockers,
        "module_evidence": unproven_modules,
    }
    blocker_count = sum(len(rows) for rows in blockers.values())

    course_stages = [
        {
            "id": "private-profile",
            "name": "Complete paired public-Sakura and ExtremeCraft mechanics fingerprint",
            "status": "BLOCKED" if parity_missing else "READY",
            "blockers": parity_missing,
        },
        {
            "id": "course-survey",
            "name": "Measure the actual raid lane, target heights, wall groups, regen depth and muzzle distances",
            "status": "BLOCKED" if missing_measurements else "READY",
            "blockers": missing_measurements,
        },
        {
            "id": "module-proof",
            "name": "Prove every required cannon module in dependency order",
            "status": "BLOCKED" if unproven_modules else "READY",
            "blockers": unproven_modules,
            "modules": module_stages,
        },
        {
            "id": "single-cell-watered",
            "name": "Break one external watered durable cell with source-accounted payload-sand fusion",
            "status": "BLOCKED" if unproven_modules or parity_missing else "READY",
            "requires": ["module-proof", "private-profile"],
        },
        {
            "id": "one-chunk-course",
            "name": "Qualify one measured chunk of the real defense family",
            "status": "BLOCKED",
            "requires": ["single-cell-watered", "course-survey"],
        },
        {
            "id": "three-chunk-mixed-course",
            "name": "Qualify mixed regen, filter, hotdog and pillar transitions over three chunks",
            "status": "BLOCKED",
            "requires": ["one-chunk-course"],
        },
        {
            "id": "measured-regen-depth-course",
            "name": "Qualify the exact current-map regeneration depth without combining scattered damage",
            "status": "BLOCKED",
            "requires": ["three-chunk-mixed-course", "regeneration.algorithm"],
        },
        {
            "id": "fifteen-chunk-course",
            "name": "Run the full fifteen-chunk buffer course with measured wall count and external target geometry",
            "status": "BLOCKED",
            "requires": ["measured-regen-depth-course"],
        },
        {
            "id": "one-paste-endurance",
            "name": "Repeat the full firing cycle on one physical cannon with bounded variance and survival",
            "status": "BLOCKED",
            "requires": ["fifteen-chunk-course"],
        },
        {
            "id": "field-canary",
            "name": "Reproduce the exact hashed candidate and workflow in a controlled low-risk ExtremeCraft canary",
            "status": "BLOCKED",
            "requires": ["one-paste-endurance", "full_cannon.field_workflow"],
        },
    ]

    return {
        "schema_version": 1,
        "id": "extremecraft-fifteen-chunk-raid-program-v1",
        "objective_id": objective.get("id"),
        "readiness": "BLOCKED" if blocker_count else "PROGRAM_INPUTS_COMPLETE",
        "blocker_count": blocker_count,
        "blockers": blockers,
        "distinctions": {
            "buffer_depth_chunks": target.get("buffer_depth_chunks"),
            "buffer_depth_is_projectile_distance": False,
            "buffer_depth_is_wall_count": False,
            "buffer_depth_is_regen_depth": False,
            "exact_flight_distance_blocks": target.get("exact_muzzle_to_first_target_blocks"),
            "regen_depth_chunks": target.get("regen_depth_chunks"),
            "wall_group_count": target.get("wall_group_count"),
        },
        "module_stage_count": len(module_stages),
        "module_stages": module_stages,
        "course_stages": course_stages,
        "throughput": build_throughput(objective),
        "constraints": constraints,
        "truth_boundary": {
            "program_plan_proves_geometry": False,
            "program_plan_proves_runtime": False,
            "program_plan_proves_private_extremecraft_parity": False,
            "program_plan_proves_fifteen_chunk_raid_capability": False,
            "theoretical_throughput_proves_live_raid_time": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan a fail-closed ExtremeCraft fifteen-chunk regeneration raid program."
    )
    parser.add_argument("grammar", type=Path)
    parser.add_argument("parity", type=Path)
    parser.add_argument("objective", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_plan(
        read_object(args.grammar),
        read_object(args.parity),
        read_object(args.objective),
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report["readiness"] == "PROGRAM_INPUTS_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
