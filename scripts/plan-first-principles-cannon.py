#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

CORE_SCRIPT = Path(__file__).with_name("first-principles-cannon-core.py")
spec = importlib.util.spec_from_file_location("first_principles_core", CORE_SCRIPT)
if spec is None or spec.loader is None:
    raise RuntimeError(f"unable to load {CORE_SCRIPT}")
core = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = core
spec.loader.exec_module(core)

PlanError = core.PlanError
Primitive = core.Primitive
PRIMITIVES = core.PRIMITIVES
FEATURE_ROOTS = core.FEATURE_ROOTS
EVIDENCE_RANK = core.EVIDENCE_RANK
load_json = core.load_json
require_int = core.require_int
dependency_closure = core.dependency_closure
candidate_combinations = core.candidate_combinations
architecture_candidates = core.architecture_candidates
experiment_program = core.experiment_program


def validate_request(request: dict[str, Any]) -> None:
    if int(request.get("schema_version", 0)) != 1:
        raise PlanError("schema_version must equal 1")
    if request.get("mode") != "from-scratch":
        raise PlanError("mode must equal 'from-scratch'")
    if request.get("source_schematic") not in (None, ""):
        raise PlanError("from-scratch mode forbids source_schematic")
    constraints = request.get("constraints")
    objective = request.get("objective")
    if not isinstance(constraints, dict) or not isinstance(objective, dict):
        raise PlanError("constraints and objective must be objects")
    chunk_limit = require_int(constraints, "chunk_limit", 1, 10000)
    margin = require_int(constraints, "min_chunk_margin", 0, chunk_limit - 1)
    require_int(constraints, "max_columns", 1, 128)
    require_int(constraints, "max_total_dispensers", 1, 100000)
    require_int(constraints, "max_candidate_count", 1, 1024)
    if chunk_limit - margin < 1:
        raise PlanError("chunk limit minus margin must remain positive")
    require_int(objective, "range_blocks", 1, 100000)
    require_int(objective, "watered_obsidian_hits", 1, 1000)
    require_int(objective, "stack_height", 1, 10000)
    require_int(objective, "raid_depth_chunks", 1, 10000)
    require_int(objective, "shot_cadence_ticks", 1, 100000)
    features = objective.get("features")
    if not isinstance(features, list) or not features:
        raise PlanError("objective.features must be a non-empty list")
    unknown = sorted(set(map(str, features)) - FEATURE_ROOTS.keys())
    if unknown:
        raise PlanError(f"unknown features: {', '.join(unknown)}")
    required_evidence = str(request.get("minimum_evidence", "local-runtime"))
    if required_evidence not in EVIDENCE_RANK:
        raise PlanError(f"invalid minimum_evidence {required_evidence!r}")
    if EVIDENCE_RANK[required_evidence] < EVIDENCE_RANK["local-runtime"]:
        raise PlanError("from-scratch advanced planning requires at least local-runtime evidence")


def options_for(primitive: Primitive, objective: dict[str, Any]) -> tuple[int, ...]:
    options = primitive.budget_options
    stack_height = int(objective.get("stack_height", 1))
    raid_depth_chunks = int(objective.get("raid_depth_chunks", 1))
    range_blocks = int(objective.get("range_blocks", 1))
    if primitive.id == "hammer" and stack_height >= 200:
        options = tuple(value for value in options if value >= 72)
    if primitive.id == "regen-bust" and raid_depth_chunks >= 8:
        options = tuple(value for value in options if value >= 48)
    if primitive.id in {"protected-charge-cell", "staged-booster"} and range_blocks >= 192:
        options = tuple(value for value in options if value >= 48)
    if not options:
        raise PlanError(f"no budget options remain for {primitive.id}")
    return options


def pack_columns(budgets: dict[str, int], capacity: int, max_columns: int) -> tuple[list[dict[str, Any]], bool]:
    columns: list[dict[str, Any]] = []
    items = sorted(((count, primitive_id) for primitive_id, count in budgets.items() if count), reverse=True)
    for count, primitive_id in items:
        remaining = count
        segment = 1
        while remaining:
            free_columns = [
                (capacity - int(column["load"]), index)
                for index, column in enumerate(columns)
                if int(column["load"]) < capacity
            ]
            fitting = [(free, index) for free, index in free_columns if free >= remaining]
            if fitting:
                free, best_index = min(fitting)
            elif free_columns:
                free, best_index = max(free_columns)
            else:
                if len(columns) >= max_columns:
                    return columns, False
                columns.append({"column": len(columns), "load": 0, "segments": []})
                best_index = len(columns) - 1
                free = capacity
            piece = min(remaining, free)
            columns[best_index]["load"] += piece
            columns[best_index]["segments"].append({
                "primitive": primitive_id,
                "segment": segment,
                "dispensers": piece,
            })
            remaining -= piece
            segment += 1
    return columns, True


def acceptance_contract(primitive_id: str, objective: dict[str, Any]) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "require_exact_geometry_identity": True,
        "require_causal_source_accounting": True,
        "allow_single_lucky_shot_promotion": False,
    }
    if primitive_id == "control-spine":
        contract.update({
            "require_real_redstone_activation": True,
            "require_deterministic_phase_order": True,
            "require_repeatable_reset": True,
        })
    if primitive_id == "protected-charge-cell":
        contract.update({
            "require_measured_impulse_distribution": True,
            "minimum_one_paste_shots": 100,
            "maximum_self_damage_blocks": 0,
        })
    if primitive_id == "staged-booster":
        contract.update({
            "require_positive_impulse_gain_over_baseline": True,
            "require_separate_source_cohorts": True,
        })
    if primitive_id == "guider":
        contract.update({
            "minimum_forward_range_blocks": int(objective["range_blocks"]),
            "require_repeatable_target_lane": True,
        })
    if primitive_id == "payload-injector":
        contract.update({
            "require_payload_fuse_separation": True,
            "require_muzzle_clearance": True,
        })
    if primitive_id == "falling-payload-fusion":
        contract.update({
            "required_registered_obsidian_hits": int(objective["watered_obsidian_hits"]),
            "minimum_embedded_payload_explosions": 1,
            "maximum_unembedded_water_explosions": 0,
        })
    if primitive_id in {"sand-compressor", "hammer"}:
        contract["target_stack_height"] = int(objective["stack_height"])
    if primitive_id == "slab-bust":
        contract.update({
            "require_slab_filter_clearance": True,
            "require_stack_preservation": True,
        })
    if primitive_id in {"regen-bust", "osrb-sequence"}:
        contract.update({
            "target_raid_depth_chunks": int(objective["raid_depth_chunks"]),
            "require_stage_geometry_manifest": True,
            "require_one_contiguous_lane_before_first_restore": True,
        })
    if primitive_id == "nuke-cohort":
        contract.update({
            "require_separated_damage_cohorts": True,
            "require_height_band_coverage": True,
        })
    if primitive_id == "campaign-cycle":
        contract.update({
            "target_raid_depth_chunks": int(objective["raid_depth_chunks"]),
            "maximum_shot_cadence_ticks": int(objective["shot_cadence_ticks"]),
            "minimum_one_paste_shots": 100,
            "require_refill_and_reset_proof": True,
            "require_multi_stage_defense_campaign": True,
        })
    return contract


core.validate_request = validate_request
core.options_for = options_for
core.pack_columns = pack_columns
core.acceptance_contract = acceptance_contract
build_report = core.build_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan a source-free, first-principles cannon research program")
    parser.add_argument("request", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    report = build_report(load_json(args.request))
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise SystemExit(2)
