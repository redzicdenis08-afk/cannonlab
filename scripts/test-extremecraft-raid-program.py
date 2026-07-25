#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "plan-extremecraft-raid-program.py"


def load_module():
    spec = importlib.util.spec_from_file_location("plan_extremecraft_raid_program", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def clone(payload: dict) -> dict:
    return json.loads(json.dumps(payload))


def main() -> None:
    planner = load_module()
    grammar = load_json("profiles/grammar/modern-factions-cannon-grammar-v1.json")
    parity = load_json("profiles/parity/extremecraft-private-parity-required-v1.json")
    objective = load_json("profiles/raid/extremecraft-15-chunk-regen-objective-v1.json")

    blocked = planner.build_plan(grammar, parity, objective)
    assert blocked["readiness"] == "BLOCKED", blocked
    assert blocked["distinctions"]["buffer_depth_chunks"] == 15, blocked
    assert blocked["distinctions"]["buffer_depth_is_projectile_distance"] is False, blocked
    assert blocked["distinctions"]["exact_flight_distance_blocks"] is None, blocked
    assert blocked["throughput"]["uses_buffer_depth_as_wall_count"] is False, blocked
    assert "exact_muzzle_to_first_target_blocks" in blocked["blockers"]["course_measurements"], blocked

    module_ids = [row["module"] for row in blocked["module_stages"]]
    required_core = {
        "charge-force",
        "payload",
        "guider-realignment",
        "slab-bust",
        "sand-release",
        "hammer",
        "sand-compression",
        "hybrid-fusion",
        "one-shot-cycle",
    }
    assert required_core <= set(module_ids), module_ids
    assert module_ids.index("charge-force") < module_ids.index("payload"), module_ids
    assert module_ids.index("sand-release") < module_ids.index("hammer"), module_ids
    assert module_ids.index("hammer") < module_ids.index("hybrid-fusion"), module_ids

    reverse_objective = clone(objective)
    reverse_objective["enabled_conditional_modules"] = ["reverse"]
    reverse_plan = planner.build_plan(grammar, parity, reverse_objective)
    reverse_ids = [row["module"] for row in reverse_plan["module_stages"]]
    assert "reverse" in reverse_ids, reverse_ids
    assert "reverse" not in module_ids, module_ids

    complete = clone(objective)
    complete_target = complete["objective"]
    complete_target.update(
        {
            "regen_depth_chunks": 8,
            "exact_muzzle_to_first_target_blocks": 180,
            "exact_muzzle_to_core_blocks": 420,
            "wall_group_count": 48,
            "target_height_min": 5,
            "target_height_max": 255,
            "target_lane": {"axis": "east", "lateral": 0},
        }
    )
    complete["operations"].update(
        {
            "shots_per_wall_group": 1,
            "fire_interval_seconds": 2,
            "reload_overhead_seconds_per_shot": 0.5,
            "target_raid_time_minutes": 15,
            "one_wall_per_press_rule": "measured-allowed",
            "automatic_cannoning_rule": "measured-manual-only",
            "allowed_reverse_or_left_right_rules": "measured-profile",
            "patching_pressure_model": "measured-separately",
        }
    )
    complete["constraints"]["fawe_block_entity_limit"] = 1024
    measured_parity = clone(parity)
    for dimension in measured_parity["dimensions"]:
        dimension["status"] = "measured"
    preliminary = planner.build_plan(grammar, measured_parity, complete)
    complete["available_module_evidence"] = {
        row["module"]: "FIELD_READY" for row in preliminary["module_stages"]
    }
    ready = planner.build_plan(grammar, measured_parity, complete)
    assert ready["readiness"] == "PROGRAM_INPUTS_COMPLETE", ready
    assert ready["blocker_count"] == 0, ready
    assert ready["throughput"]["status"] == "THEORETICAL_ONLY", ready
    assert ready["throughput"]["wall_group_count"] == 48, ready
    assert ready["throughput"]["total_shots"] == 48, ready
    assert ready["throughput"]["theoretical_seconds"] == 120.0, ready
    assert ready["throughput"]["truth_boundary"]["throughput_proves_raid_completion"] is False
    assert ready["truth_boundary"]["program_plan_proves_fifteen_chunk_raid_capability"] is False

    bad = clone(objective)
    bad["required_modules"] = ["magic-cannon"]
    try:
        planner.build_plan(grammar, parity, bad)
    except planner.RaidPlanError as exc:
        assert "unknown modules" in str(exc), exc
    else:
        raise AssertionError("unknown raid module unexpectedly passed")

    collapsed = clone(objective)
    collapsed["truth_boundary"]["fifteen_chunks_equals_240_block_projectile_distance"] = True
    try:
        planner.build_plan(grammar, parity, collapsed)
    except planner.RaidPlanError as exc:
        assert "collapse" in str(exc), exc
    else:
        raise AssertionError("15 chunks = 240 blocks collapse unexpectedly passed")

    print("PASS fifteen chunks remains distinct from range, wall count and regen depth")
    print("PASS raid module dependency expansion")
    print("PASS conditional reverse gating")
    print("PASS complete-input theoretical throughput without capability promotion")
    print("PASS unknown-module and distance-collapse rejection")


if __name__ == "__main__":
    main()
