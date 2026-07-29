#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

EVIDENCE_RANK = {
    "unknown": 0,
    "inference": 1,
    "static": 2,
    "local-runtime": 3,
    "field-reported": 4,
    "field-verified": 5,
}


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Primitive:
    id: str
    capability: str
    prerequisites: tuple[str, ...]
    budget_options: tuple[int, ...]
    required_evidence: str
    experiments: tuple[str, ...]
    notes: str


PRIMITIVES: dict[str, Primitive] = {
    "control-spine": Primitive(
        "control-spine",
        "single-button-cycle",
        (),
        (0,),
        "local-runtime",
        ("static-integrity", "real-redstone-activation", "cumulative-reset"),
        "One operator input, deterministic phase ordering, and a repeatable reset path.",
    ),
    "protected-charge-cell": Primitive(
        "protected-charge-cell",
        "water-protected-impulse",
        ("control-spine",),
        (24, 48, 72, 96, 120, 144),
        "local-runtime",
        ("dry-impulse", "water-survival", "causal-tnt-trace", "one-paste-endurance"),
        "The first force source. It must survive in water and produce a measured impulse distribution.",
    ),
    "staged-booster": Primitive(
        "staged-booster",
        "multi-stage-compression",
        ("protected-charge-cell",),
        (16, 32, 48, 64, 80, 96),
        "local-runtime",
        ("stage-isolation", "impulse-gain", "cohort-separation", "survival-under-load"),
        "Adds measured impulse without collapsing separate TNT cohorts into an untraceable blast cloud.",
    ),
    "guider": Primitive(
        "guider",
        "trajectory-alignment",
        ("protected-charge-cell",),
        (0, 4, 8, 12, 16),
        "local-runtime",
        ("axis-alignment-sweep", "range-sweep", "height-sweep", "repeatability"),
        "Controls the final launch lane. It is judged by dispersion, not appearance.",
    ),
    "payload-injector": Primitive(
        "payload-injector",
        "payload-cohort",
        ("control-spine", "protected-charge-cell"),
        (4, 8, 12, 16, 24, 32),
        "local-runtime",
        ("payload-source-accounting", "fuse-separation", "muzzle-clearance", "target-envelope"),
        "Produces the damaging TNT cohort with exact source and fuse evidence.",
    ),
    "falling-payload-fusion": Primitive(
        "falling-payload-fusion",
        "watered-wall-hybrid",
        ("payload-injector", "guider"),
        (0, 8, 16, 24, 32),
        "local-runtime",
        ("falling-block-trajectory", "explosion-overlap", "watered-obsidian-four-hit", "unembedded-water-negative"),
        "Pairs falling payload and TNT at the target. Four-hit durability alone is not enough without overlap evidence.",
    ),
    "sand-compressor": Primitive(
        "sand-compressor",
        "stack-payload-compression",
        ("control-spine", "staged-booster"),
        (8, 16, 24, 32, 48, 64),
        "local-runtime",
        ("falling-block-count", "compression-volume", "order-of-entities", "jam-recovery"),
        "Compresses a known falling-block cohort while preserving order and reset reliability.",
    ),
    "hammer": Primitive(
        "hammer",
        "vertical-stacking-impulse",
        ("sand-compressor", "guider", "staged-booster"),
        (24, 48, 72, 96, 120, 144),
        "local-runtime",
        ("hammer-cohort-source", "downward-impulse", "stack-height-sweep", "overstack-negative"),
        "A separately sourced cohort that drives the stack vertically at the wall.",
    ),
    "slab-bust": Primitive(
        "slab-bust",
        "slab-filter-clearance",
        ("payload-injector", "hammer"),
        (4, 8, 12, 16, 24),
        "local-runtime",
        ("slab-timing-sweep", "slab-count-sweep", "stack-preservation", "filter-course"),
        "Clears slab/filter interference without destroying the intended stack timing.",
    ),
    "regen-bust": Primitive(
        "regen-bust",
        "regen-race-penetration",
        ("falling-payload-fusion", "hammer", "slab-bust"),
        (16, 32, 48, 64, 80, 96),
        "local-runtime",
        ("regen-delay-sweep", "contiguous-lane-before-restore", "hotdog-course", "pillar-course"),
        "Must create one aligned penetration lane before the first actual restoration.",
    ),
    "nuke-cohort": Primitive(
        "nuke-cohort",
        "multi-height-damage",
        ("payload-injector", "guider", "staged-booster"),
        (16, 32, 48, 64, 80, 96),
        "local-runtime",
        ("cohort-spacing", "height-band-coverage", "kind-conflict-negative", "watered-course"),
        "Creates intentionally separated damage cohorts. More TNT is rejected when it worsens alignment.",
    ),
    "osrb-sequence": Primitive(
        "osrb-sequence",
        "one-shot-regen-bust-sequence",
        ("regen-bust", "nuke-cohort"),
        (8, 16, 24, 32, 48),
        "local-runtime",
        ("phase-order-proof", "regen-course-one-pulse", "source-accounting", "failure-replay"),
        "A proven phase sequence, not a label inferred from a filename or dispenser count.",
    ),
    "campaign-cycle": Primitive(
        "campaign-cycle",
        "sustained-raid-cycle",
        ("osrb-sequence", "control-spine"),
        (0,),
        "local-runtime",
        ("one-paste-100", "multi-target-campaign", "refill-reset", "self-damage-budget"),
        "Preserves one physical cannon over repeated shots and changing defense stages.",
    ),
}

FEATURE_ROOTS = {
    "hybrid": "falling-payload-fusion",
    "stacker": "hammer",
    "slab-bust": "slab-bust",
    "regen-bust": "regen-bust",
    "nuke": "nuke-cohort",
    "osrb": "osrb-sequence",
    "campaign": "campaign-cycle",
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PlanError("request must be a JSON object")
    return payload


def require_int(mapping: dict[str, Any], key: str, minimum: int, maximum: int | None = None) -> int:
    try:
        value = int(mapping[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise PlanError(f"{key} must be an integer") from exc
    if value < minimum or (maximum is not None and value > maximum):
        suffix = f"..{maximum}" if maximum is not None else f">={minimum}"
        raise PlanError(f"{key} must be in {suffix}")
    return value


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
    require_int(objective, "regen_layers", 1, 10000)
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


def dependency_closure(roots: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    visiting: set[str] = set()
    ordered: list[str] = []

    def visit(primitive_id: str) -> None:
        if primitive_id in seen:
            return
        if primitive_id in visiting:
            raise PlanError(f"primitive dependency cycle at {primitive_id}")
        visiting.add(primitive_id)
        primitive = PRIMITIVES[primitive_id]
        for dependency in primitive.prerequisites:
            visit(dependency)
        visiting.remove(primitive_id)
        seen.add(primitive_id)
        ordered.append(primitive_id)

    for root in roots:
        visit(root)
    return ordered


def options_for(primitive: Primitive, objective: dict[str, Any]) -> tuple[int, ...]:
    options = primitive.budget_options
    stack_height = int(objective.get("stack_height", 1))
    regen_layers = int(objective.get("regen_layers", 1))
    range_blocks = int(objective.get("range_blocks", 1))
    if primitive.id == "hammer" and stack_height >= 200:
        options = tuple(value for value in options if value >= 72)
    if primitive.id == "regen-bust" and regen_layers >= 8:
        options = tuple(value for value in options if value >= 48)
    if primitive.id in {"protected-charge-cell", "staged-booster"} and range_blocks >= 192:
        options = tuple(value for value in options if value >= 48)
    if not options:
        raise PlanError(f"no budget options remain for {primitive.id}")
    return options


def candidate_combinations(primitive_ids: list[str], objective: dict[str, Any], limit: int) -> list[dict[str, int]]:
    varying = [primitive_id for primitive_id in primitive_ids if len(options_for(PRIMITIVES[primitive_id], objective)) > 1]
    fixed = {
        primitive_id: options_for(PRIMITIVES[primitive_id], objective)[0]
        for primitive_id in primitive_ids
        if primitive_id not in varying
    }
    # Deterministic, bounded sampling over an otherwise exponential option grid.
    # Explicit low/middle/high anchors are followed by hash-derived rows so the
    # candidate family explores mixed budgets instead of walking one diagonal.
    rows: list[dict[str, int]] = []
    seen: set[tuple[tuple[str, int], ...]] = set()

    def append(indices: dict[str, int]) -> None:
        row = dict(fixed)
        for primitive_id in varying:
            options = options_for(PRIMITIVES[primitive_id], objective)
            row[primitive_id] = options[indices[primitive_id] % len(options)]
        key = tuple(sorted(row.items()))
        if key not in seen:
            seen.add(key)
            rows.append(row)

    for anchor in (0, 1, 2):
        append({
            primitive_id: (
                0
                if anchor == 0
                else (
                    len(options_for(PRIMITIVES[primitive_id], objective)) - 1
                    if anchor == 2
                    else len(options_for(PRIMITIVES[primitive_id], objective)) // 2
                )
            )
            for primitive_id in varying
        })

    phase = 0
    while len(rows) < limit and phase < limit * 64:
        indices: dict[str, int] = {}
        for primitive_id in varying:
            raw = hashlib.sha256(f"{phase}:{primitive_id}".encode("utf-8")).digest()
            indices[primitive_id] = int.from_bytes(raw[:8], "big")
        append(indices)
        phase += 1
    return rows[:limit]


def pack_columns(budgets: dict[str, int], capacity: int, max_columns: int) -> tuple[list[dict[str, Any]], bool]:
    columns: list[dict[str, Any]] = []
    items = sorted(((count, primitive_id) for primitive_id, count in budgets.items() if count), reverse=True)
    for count, primitive_id in items:
        remaining = count
        segment = 1
        while remaining:
            piece = min(remaining, capacity)
            best_index = None
            best_remaining = None
            for index, column in enumerate(columns):
                free = capacity - int(column["load"])
                if free >= piece and (best_remaining is None or free - piece < best_remaining):
                    best_index = index
                    best_remaining = free - piece
            if best_index is None:
                if len(columns) >= max_columns:
                    return columns, False
                columns.append({"column": len(columns), "load": 0, "segments": []})
                best_index = len(columns) - 1
            columns[best_index]["load"] += piece
            columns[best_index]["segments"].append({
                "primitive": primitive_id,
                "segment": segment,
                "dispensers": piece,
            })
            remaining -= piece
            segment += 1
    return columns, True


def architecture_candidates(request: dict[str, Any], primitive_ids: list[str]) -> list[dict[str, Any]]:
    constraints = request["constraints"]
    objective = request["objective"]
    chunk_limit = int(constraints["chunk_limit"])
    margin = int(constraints["min_chunk_margin"])
    capacity = chunk_limit - margin
    max_columns = int(constraints["max_columns"])
    max_total = int(constraints["max_total_dispensers"])
    max_candidates = int(constraints["max_candidate_count"])
    rows = candidate_combinations(primitive_ids, objective, max_candidates * 4)
    output: list[dict[str, Any]] = []
    for budgets in rows:
        total = sum(budgets.values())
        if total > max_total:
            continue
        columns, legal = pack_columns(budgets, capacity, max_columns)
        if not legal:
            continue
        max_load = max((int(column["load"]) for column in columns), default=0)
        min_margin = chunk_limit - max_load
        score = (
            len(columns),
            -min_margin,
            total,
            tuple(budgets[primitive_id] for primitive_id in primitive_ids),
        )
        output.append({
            "id": "arch-" + hashlib.sha256(json.dumps(budgets, sort_keys=True).encode()).hexdigest()[:12],
            "status": "ARCHITECTURE_BUDGET_ONLY",
            "dispenser_budgets": budgets,
            "total_dispensers": total,
            "chunk_capacity_after_margin": capacity,
            "columns": columns,
            "column_count": len(columns),
            "max_column_load": max_load,
            "minimum_chunk_margin": min_margin,
            "score": [len(columns), -min_margin, total],
            "score_key": score,
        })
    output.sort(key=lambda row: row["score_key"])
    for row in output:
        row.pop("score_key", None)
    return output[:max_candidates]


def acceptance_contract(primitive_id: str, objective: dict[str, Any]) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "require_exact_geometry_identity": True,
        "require_causal_source_accounting": True,
        "allow_single_lucky_shot_promotion": False,
    }
    if primitive_id in {"protected-charge-cell", "staged-booster", "guider", "payload-injector"}:
        contract["minimum_forward_range_blocks"] = int(objective["range_blocks"])
    if primitive_id == "falling-payload-fusion":
        contract.update({
            "required_registered_obsidian_hits": int(objective["watered_obsidian_hits"]),
            "minimum_embedded_payload_explosions": 1,
            "maximum_unembedded_water_explosions": 0,
        })
    if primitive_id in {"sand-compressor", "hammer"}:
        contract["target_stack_height"] = int(objective["stack_height"])
    if primitive_id in {"regen-bust", "osrb-sequence"}:
        contract.update({
            "target_regen_layers": int(objective["regen_layers"]),
            "require_one_contiguous_lane_before_first_restore": True,
        })
    if primitive_id == "campaign-cycle":
        contract.update({
            "maximum_shot_cadence_ticks": int(objective["shot_cadence_ticks"]),
            "minimum_one_paste_shots": 100,
            "require_refill_and_reset_proof": True,
        })
    return contract


def experiment_program(primitive_ids: list[str], minimum_evidence: str, objective: dict[str, Any]) -> list[dict[str, Any]]:
    program: list[dict[str, Any]] = []
    for index, primitive_id in enumerate(primitive_ids, start=1):
        primitive = PRIMITIVES[primitive_id]
        program.append({
            "stage": index,
            "primitive": primitive.id,
            "capability": primitive.capability,
            "prerequisites": list(primitive.prerequisites),
            "required_evidence": max(
                (minimum_evidence, primitive.required_evidence),
                key=lambda value: EVIDENCE_RANK[value],
            ),
            "experiments": list(primitive.experiments),
            "acceptance_contract": acceptance_contract(primitive_id, objective),
            "promotion_rule": (
                "Every experiment must pass on one exact geometry with causal source accounting; "
                "static shape, filenames, labels, or one lucky shot cannot promote the primitive."
            ),
            "notes": primitive.notes,
        })
    return program


def build_report(request: dict[str, Any]) -> dict[str, Any]:
    validate_request(request)
    objective = request["objective"]
    roots = [FEATURE_ROOTS[str(feature)] for feature in objective["features"]]
    primitive_ids = dependency_closure(roots)
    architectures = architecture_candidates(request, primitive_ids)
    return {
        "schema_version": 1,
        "status": "RESEARCH_PROGRAM_ONLY",
        "request_id": str(request.get("id", "unnamed")),
        "mode": "from-scratch",
        "source_schematic_used": False,
        "requested_features": list(map(str, objective["features"])),
        "objective": dict(objective),
        "required_primitives": primitive_ids,
        "experiment_program": experiment_program(
            primitive_ids,
            str(request.get("minimum_evidence", "local-runtime")),
            objective,
        ),
        "architecture_candidates": architectures,
        "strongest_architecture": architectures[0] if architectures else None,
        "truth_boundary": {
            "architecture_budget_is_geometry": False,
            "architecture_budget_is_runtime_proof": False,
            "public_paper_or_sakura_is_extremecraft_parity": False,
            "final_required_gate": "controlled-live-EC-canary",
            "note": (
                "This planner creates a source-free primitive discovery program and EC160-aware dispenser budgets. "
                "It does not invent redstone geometry, subsystem semantics, or private server parity."
            ),
        },
    }


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
