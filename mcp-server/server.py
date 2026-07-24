#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
OUTPUT_ROOT = ROOT.parents[1] / "output"
mcp = FastMCP("CannonLab")


def _inside_root(raw: str | Path, *, must_exist: bool = True) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"path escapes CannonLab repository: {raw}")
    if must_exist and not path.exists():
        raise FileNotFoundError(path)
    return path


def _inside_runtime(raw: str | Path, *, must_exist: bool = True) -> Path:
    """Allow CannonLab repo files plus generated CannonLab evidence under workspace output/."""
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    allowed = path.is_relative_to(ROOT) or path.is_relative_to(OUTPUT_ROOT)
    if not allowed:
        raise ValueError(f"path escapes CannonLab repository/output roots: {raw}")
    if must_exist and not path.exists():
        raise FileNotFoundError(path)
    return path


def _run_json(args: list[str], *, timeout: int = 180) -> dict[str, Any]:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode not in (0, 2):
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout={result.stdout[-4000:]}\nstderr={result.stderr[-4000:]}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"tool returned non-JSON output: {result.stdout[-4000:]}") from exc
    payload["_exit_code"] = result.returncode
    return payload


def _reference_args(reference_paths: list[str] | None) -> list[str]:
    args: list[str] = []
    for raw in reference_paths or []:
        reference = _inside_root(raw)
        args += ["--reference", str(reference)]
    return args


@mcp.tool()
def inspect_cannon(path: str, chunk_limit: int = 160) -> dict[str, Any]:
    """Decode a Sponge/Litematica cannon, audit EC limits, and map structural modules."""
    source = _inside_root(path)
    audit = _run_json([
        sys.executable,
        str(SCRIPTS / "schem-audit.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])
    paste_alignment = _run_json([
        sys.executable,
        str(SCRIPTS / "paste-alignment-audit.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])
    static_map = _run_json([
        sys.executable,
        str(SCRIPTS / "cannon-static-map.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])
    module_map = _run_json([
        sys.executable,
        str(SCRIPTS / "cannon-module-map.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])
    ec160_architecture = _run_json([
        sys.executable,
        str(SCRIPTS / "ec160_architecture_advisor.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])
    return {
        "audit": audit,
        "paste_alignment": paste_alignment,
        "static_map": static_map,
        "module_map": module_map,
        "ec160_architecture": ec160_architecture,
    }


@mcp.tool()
def fast_cannon_intake(
    path: str,
    reference_paths: list[str] | None = None,
    intent: str = "modern-raid",
    chunk_limit: int = 160,
) -> dict[str, Any]:
    """One fast call for SHA-safe intake, EC audit, structural map, and anti-pancake comparison."""
    if intent not in {"calibration", "modern-raid"}:
        raise ValueError("intent must be calibration or modern-raid")
    source = _inside_root(path)
    audit = _run_json([
        sys.executable,
        str(SCRIPTS / "schem-audit.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])
    paste_alignment = _run_json([
        sys.executable,
        str(SCRIPTS / "paste-alignment-audit.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])
    static_map = _run_json([
        sys.executable,
        str(SCRIPTS / "cannon-static-map.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])
    module_map = _run_json([
        sys.executable,
        str(SCRIPTS / "cannon-module-map.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])
    ec160_architecture = _run_json([
        sys.executable,
        str(SCRIPTS / "ec160_architecture_advisor.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])
    profile = _run_json([
        sys.executable,
        str(SCRIPTS / "cannon-geometry-profile.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
        "--intent",
        intent,
        *_reference_args(reference_paths),
    ])
    return {
        "audit": audit,
        "paste_alignment": paste_alignment,
        "static_map": static_map,
        "module_map": module_map,
        "ec160_architecture": ec160_architecture,
        "geometry_profile": profile,
        "next_action": (
            "Use a proven reference as the edit base. Do not generate a modern raid "
            "candidate from flat dispenser rows when the profile fails."
        ),
    }


@mcp.tool()
def audit_paste_alignment(
    path: str,
    chunk_limit: int = 160,
    block_entity_limit: int | None = None,
) -> dict[str, Any]:
    """Convert schematic-minimum alignment into the actual WorldEdit player paste-point frame."""
    source = _inside_root(path)
    args = [
        sys.executable,
        str(SCRIPTS / "paste-alignment-audit.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ]
    if block_entity_limit is not None:
        args += ["--block-entity-limit", str(block_entity_limit)]
    return _run_json(args)


@mcp.tool()
def advise_ec160_architecture(path: str, chunk_limit: int = 160) -> dict[str, Any]:
    """Find legal X/Z placements first, then map bank-level reconstruction pressure without rewriting the cannon."""
    source = _inside_root(path)
    return _run_json([
        sys.executable,
        str(SCRIPTS / "ec160_architecture_advisor.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])


@mcp.tool()
def compare_reference_physics(
    events_path: str,
    kind: str = "tnt",
    profile: str = "modern-java",
    entity_index: int = 0,
    entity_uuid: str | None = None,
    water_flow_x: float = 0.0,
    water_flow_y: float = 0.0,
    water_flow_z: float = 0.0,
    position_tolerance: float = 1.0e-5,
    velocity_tolerance: float = 1.0e-5,
    fuse_tolerance: int = 0,
) -> dict[str, Any]:
    """Compare one recorded TNT/falling-block trajectory to the independent reference model and diagnose first drift."""
    if kind not in {"tnt", "falling_block"}:
        raise ValueError("kind must be tnt or falling_block")
    if profile not in {"modern-java", "legacy-java-1.8"}:
        raise ValueError("profile must be modern-java or legacy-java-1.8")
    events = _inside_root(events_path)
    args = [
        sys.executable,
        str(SCRIPTS / "cannon_physics_reference.py"),
        "compare-events",
        str(events),
        "--kind",
        kind,
        "--profile",
        profile,
        "--entity-index",
        str(entity_index),
        "--water-flow",
        str(water_flow_x),
        str(water_flow_y),
        str(water_flow_z),
        "--position-tolerance",
        str(position_tolerance),
        "--velocity-tolerance",
        str(velocity_tolerance),
        "--fuse-tolerance",
        str(fuse_tolerance),
    ]
    if entity_uuid:
        args += ["--uuid", entity_uuid]
    return _run_json(args)


@mcp.tool()
def audit_scenario_integrity(
    scenario_path: str,
    require_field_candidate: bool = False,
    require_readiness: bool = False,
) -> dict[str, Any]:
    """Expose lab assists and weak gates before a run is promoted as cannon evidence."""
    scenario = _inside_root(scenario_path)
    args = [
        sys.executable,
        str(SCRIPTS / "scenario-integrity-audit.py"),
        str(scenario),
    ]
    if require_field_candidate:
        args.append("--require-field-candidate")
    if require_readiness:
        args.append("--require-readiness")
    return _run_json(args)


@mcp.tool()
def map_cannon_modules(
    path: str,
    chunk_limit: int = 160,
    assignment_radius: int = 6,
) -> dict[str, Any]:
    """Map dispenser-bank modules, repeated lanes, controls, timing parts, and conservative role candidates."""
    source = _inside_root(path)
    return _run_json([
        sys.executable,
        str(SCRIPTS / "cannon-module-map.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
        "--assignment-radius",
        str(assignment_radius),
    ])


@mcp.tool()
def check_cannon_preservation(
    reference_path: str,
    candidate_path: str,
    chunk_limit: int = 160,
    max_structural_change_ratio: float = 0.03,
    max_functional_change_ratio: float = 0.05,
    max_modules_touched: int = 1,
    max_unexpected_critical_changes: int = 0,
    allowed_types: list[str] | None = None,
    allowed_modules: list[str] | None = None,
    allow_dimension_change: bool = False,
    allow_block_entity_topology_change: bool = False,
    allow_ambiguous_alignment: bool = False,
    minimum_alignment_confidence: str = "medium",
    alignment_mode: str = "translate",
) -> dict[str, Any]:
    """Reject broad rebuilds by proving a candidate stayed within an explicit reference-preservation policy."""
    reference = _inside_root(reference_path)
    candidate = _inside_root(candidate_path)
    args = [
        sys.executable,
        str(SCRIPTS / "cannon-preservation-check.py"),
        str(reference),
        str(candidate),
        "--chunk-limit",
        str(chunk_limit),
        "--max-structural-change-ratio",
        str(max_structural_change_ratio),
        "--max-functional-change-ratio",
        str(max_functional_change_ratio),
        "--max-modules-touched",
        str(max_modules_touched),
        "--max-unexpected-critical-changes",
        str(max_unexpected_critical_changes),
        "--alignment-mode",
        alignment_mode,
        "--minimum-alignment-confidence",
        minimum_alignment_confidence,
    ]
    for block_type in allowed_types or []:
        args += ["--allow-type", block_type]
    for module_id in allowed_modules or []:
        args += ["--allow-module", module_id]
    if allow_dimension_change:
        args.append("--allow-dimension-change")
    if allow_block_entity_topology_change:
        args.append("--allow-block-entity-topology-change")
    if allow_ambiguous_alignment:
        args.append("--allow-ambiguous-alignment")
    return _run_json(args)


@mcp.tool()
def compare_cannon_modules(
    first_path: str,
    second_path: str,
    chunk_limit: int = 160,
    assignment_radius: int = 6,
    near_match_threshold: float = 0.82,
    minimum_shared_core_components: int = 8,
) -> dict[str, Any]:
    """Find exact translated module families and conservative near matches between two real cannons."""
    first = _inside_root(first_path)
    second = _inside_root(second_path)
    return _run_json([
        sys.executable,
        str(SCRIPTS / "compare-cannon-modules.py"),
        str(first),
        str(second),
        "--chunk-limit",
        str(chunk_limit),
        "--assignment-radius",
        str(assignment_radius),
        "--near-match-threshold",
        str(near_match_threshold),
        "--minimum-shared-core-components",
        str(minimum_shared_core_components),
    ])


@mcp.tool()
def compare_cannon_cores(
    first_path: str,
    second_path: str,
    anchor_radius: int = 2,
    minimum_anchor_neighbours: int = 3,
    max_anchor_instances: int = 48,
    top_translations: int = 32,
    minimum_shared_functional: int = 16,
    minimum_connected_functional: int = 8,
    minimum_shared_non_dispenser: int = 8,
    minimum_mechanism_diversity: int = 2,
) -> dict[str, Any]:
    """Find an exact translated partial cannon core even when inferred whole-module boundaries differ."""
    first = _inside_root(first_path)
    second = _inside_root(second_path)
    return _run_json([
        sys.executable,
        str(SCRIPTS / "compare-cannon-cores.py"),
        str(first),
        str(second),
        "--anchor-radius",
        str(anchor_radius),
        "--minimum-anchor-neighbours",
        str(minimum_anchor_neighbours),
        "--max-anchor-instances",
        str(max_anchor_instances),
        "--top-translations",
        str(top_translations),
        "--minimum-shared-functional",
        str(minimum_shared_functional),
        "--minimum-connected-functional",
        str(minimum_connected_functional),
        "--minimum-shared-non-dispenser",
        str(minimum_shared_non_dispenser),
        "--minimum-mechanism-diversity",
        str(minimum_mechanism_diversity),
    ])


@mcp.tool()
def analyze_module_trace(
    schematic_path: str,
    trace_path: str,
    chunk_limit: int = 160,
    assignment_radius: int = 6,
    correlation_ticks: int = 2,
    spawn_radius: float = 3.0,
) -> dict[str, Any]:
    """Join exact schematic modules to a causal trace and recover observed firing phases and entity correlations."""
    schematic = _inside_root(schematic_path)
    trace = _inside_root(trace_path)
    return _run_json([
        sys.executable,
        str(SCRIPTS / "analyze-module-trace.py"),
        str(schematic),
        str(trace),
        "--chunk-limit",
        str(chunk_limit),
        "--assignment-radius",
        str(assignment_radius),
        "--correlation-ticks",
        str(correlation_ticks),
        "--spawn-radius",
        str(spawn_radius),
    ])


@mcp.tool()
def compare_module_traces(
    reference_schematic: str,
    reference_trace: str,
    candidate_schematic: str,
    candidate_trace: str,
    chunk_limit: int = 160,
    assignment_radius: int = 6,
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
    allowed_reference_modules: list[str] | None = None,
    allowed_candidate_modules: list[str] | None = None,
    max_extra_active_candidate_modules: int = 0,
    allow_entity_physics_changes: bool = False,
    allow_shared_component_cohort_changes: bool = False,
    allow_joint_entity_cohort_changes: bool = False,
) -> dict[str, Any]:
    """Fail when untouched exact-geometry modules stop replaying their reference runtime contract."""
    reference_cannon = _inside_root(reference_schematic)
    reference_events = _inside_root(reference_trace)
    candidate_cannon = _inside_root(candidate_schematic)
    candidate_events = _inside_root(candidate_trace)
    args = [
        sys.executable,
        str(SCRIPTS / "compare-module-traces.py"),
        str(reference_cannon),
        str(reference_events),
        str(candidate_cannon),
        str(candidate_events),
        "--chunk-limit",
        str(chunk_limit),
        "--assignment-radius",
        str(assignment_radius),
        "--max-timing-delta",
        str(max_timing_delta),
        "--max-spawn-position-delta",
        str(max_spawn_position_delta),
        "--max-spawn-velocity-delta",
        str(max_spawn_velocity_delta),
        "--max-fuse-delta",
        str(max_fuse_delta),
        "--max-explosion-position-delta",
        str(max_explosion_position_delta),
        "--minimum-component-event-coverage",
        str(minimum_component_event_coverage),
        "--minimum-entity-correlation-coverage",
        str(minimum_entity_correlation_coverage),
        "--minimum-entity-source-accounting-coverage",
        str(minimum_entity_source_accounting_coverage),
        "--minimum-shared-component-accounting-coverage",
        str(minimum_shared_component_accounting_coverage),
        "--minimum-joint-entity-accounting-coverage",
        str(minimum_joint_entity_accounting_coverage),
        "--minimum-module-entity-profile-coverage",
        str(minimum_module_entity_profile_coverage),
        "--max-ambiguous-component-events",
        str(max_ambiguous_component_events),
        "--minimum-pairing-confidence",
        minimum_pairing_confidence,
        "--max-pairing-residual-distance",
        str(max_pairing_residual_distance),
        "--minimum-unchanged-runtime-contracts",
        str(minimum_unchanged_runtime_contracts),
        "--max-extra-active-candidate-modules",
        str(max_extra_active_candidate_modules),
    ]
    for module_id in allowed_reference_modules or []:
        args += ["--allow-reference-module", module_id]
    for module_id in allowed_candidate_modules or []:
        args += ["--allow-candidate-module", module_id]
    if allow_entity_physics_changes:
        args.append("--allow-entity-physics-changes")
    if allow_shared_component_cohort_changes:
        args.append("--allow-shared-component-cohort-changes")
    if allow_joint_entity_cohort_changes:
        args.append("--allow-joint-entity-cohort-changes")
    if allow_ambiguous_pairing:
        args.append("--allow-ambiguous-pairing")
    return _run_json(args)


@mcp.tool()
def compare_entity_trajectories(
    reference_events: str,
    candidate_events: str,
    reference_uuid: str = "",
    candidate_uuid: str = "",
    entity_index: int = 0,
    infer_translation: bool = True,
    position_tolerance: float = 1.0e-6,
    velocity_tolerance: float = 1.0e-6,
    fuse_tolerance: int = 0,
    spawn_tick_tolerance: int = 0,
    explosion_position_tolerance: float = 1.0e-6,
    explosion_tick_tolerance: int = 0,
    nearby_explosion_tick_window: int = 0,
    nearby_explosion_radius: float = 16.0,
) -> dict[str, Any]:
    """Pinpoint the first per-tick TNT position, velocity, fuse, or landing divergence."""
    reference = _inside_runtime(reference_events)
    candidate = _inside_runtime(candidate_events)
    args = [
        sys.executable,
        str(SCRIPTS / "compare-entity-trajectories.py"),
        str(reference),
        str(candidate),
        "--entity-index",
        str(entity_index),
        "--position-tolerance",
        str(position_tolerance),
        "--velocity-tolerance",
        str(velocity_tolerance),
        "--fuse-tolerance",
        str(fuse_tolerance),
        "--spawn-tick-tolerance",
        str(spawn_tick_tolerance),
        "--explosion-position-tolerance",
        str(explosion_position_tolerance),
        "--explosion-tick-tolerance",
        str(explosion_tick_tolerance),
        "--nearby-explosion-tick-window",
        str(nearby_explosion_tick_window),
        "--nearby-explosion-radius",
        str(nearby_explosion_radius),
    ]
    if reference_uuid:
        args += ["--reference-uuid", reference_uuid]
    if candidate_uuid:
        args += ["--candidate-uuid", candidate_uuid]
    if not infer_translation:
        args.append("--no-infer-translation")
    return _run_json(args)


@mcp.tool()
def analyze_breach_evidence(
    results: str,
    min_embedded_payload_explosions: int = 1,
    max_unembedded_water_explosions: int = 0,
    min_contiguous_layers_before_first_regen: int = 1,
    require_all_layers_before_first_regen: bool = False,
) -> dict[str, Any]:
    """Fail closed unless runtime evidence shows falling-payload overlap and regen-race progress."""
    run = _inside_runtime(results)
    args = [
        sys.executable,
        str(SCRIPTS / "analyze-breach-evidence.py"),
        str(run),
        "--min-embedded-payload-explosions",
        str(min_embedded_payload_explosions),
        "--max-unembedded-water-explosions",
        str(max_unembedded_water_explosions),
        "--min-contiguous-layers-before-first-regen",
        str(min_contiguous_layers_before_first_regen),
    ]
    if require_all_layers_before_first_regen:
        args.append("--require-all-layers-before-first-regen")
    return _run_json(args)


@mcp.tool()
def analyze_wall_breach(
    results: str,
    profile: str = "diagnostic",
    min_shots: int | None = None,
    expected_hits_to_break: int | None = None,
    min_target_breaks: int | None = None,
    require_direct_durability_sequence: bool = False,
    min_embedded_payload_explosions: int | None = None,
    max_unembedded_water_explosions: int | None = None,
    require_falling_payload: bool = False,
    min_connected_opening: int | None = None,
    min_contiguous_layers: int | None = None,
    require_regeneration: bool = False,
    require_positive_regen_margin: bool = False,
    max_self_damage_blocks: int | None = None,
    min_dispenser_survival_ratio: float | None = None,
    min_usable_breach_rate: float | None = None,
    min_lane_repeatability: float | None = None,
) -> dict[str, Any]:
    """Reject fake greens and diagnose durable, watered, regen, and raid-course wall breaches."""
    if profile not in {
        "diagnostic", "dry-obsidian", "watered-obsidian", "regen-course", "raid-course"
    }:
        raise ValueError("unsupported wall-breach profile")
    run = _inside_runtime(results)
    args = [
        sys.executable,
        str(SCRIPTS / "wall-breach-intelligence.py"),
        str(run),
        "--profile",
        profile,
    ]
    optional = {
        "--min-shots": min_shots,
        "--expected-hits-to-break": expected_hits_to_break,
        "--min-target-breaks": min_target_breaks,
        "--min-embedded-payload-explosions": min_embedded_payload_explosions,
        "--max-unembedded-water-explosions": max_unembedded_water_explosions,
        "--min-connected-opening": min_connected_opening,
        "--min-contiguous-layers": min_contiguous_layers,
        "--max-self-damage-blocks": max_self_damage_blocks,
        "--min-dispenser-survival-ratio": min_dispenser_survival_ratio,
        "--min-usable-breach-rate": min_usable_breach_rate,
        "--min-lane-repeatability": min_lane_repeatability,
    }
    for flag, value in optional.items():
        if value is not None:
            args += [flag, str(value)]
    if require_direct_durability_sequence:
        args.append("--require-direct-durability-sequence")
    if require_falling_payload:
        args.append("--require-falling-payload")
    if require_regeneration:
        args.append("--require-regeneration")
    if require_positive_regen_margin:
        args.append("--require-positive-regen-margin")
    return _run_json(args, timeout=300)


@mcp.tool()
def analyze_repair_family(
    reference_schematic: str,
    reference_summary: str,
    candidate_roots: list[str],
    cannon_directories: list[str],
    chunk_limit: int = 160,
    include_pattern: str = "",
    max_runtime_contract_runs: int = 3,
    max_geometry_candidates: int = 24,
    max_runtime_candidates: int = 8,
    minimum_dispenser_survival: float = 0.95,
    minimum_self_damage_reduction: float = 0.10,
    minimum_target_retention: float = 0.80,
    maximum_structural_change_ratio: float = 0.03,
) -> dict[str, Any]:
    """Screen every repair cheaply, then replay the strongest bounded candidates for collateral drift."""
    reference_cannon = _inside_root(reference_schematic)
    reference_run = _inside_root(reference_summary)
    roots = [_inside_root(path) for path in candidate_roots]
    cannon_dirs = [_inside_root(path) for path in cannon_directories]
    if not roots:
        raise ValueError("candidate_roots must contain at least one path")
    if not cannon_dirs:
        raise ValueError("cannon_directories must contain at least one path")
    args = [
        sys.executable,
        str(SCRIPTS / "analyze-repair-family.py"),
        str(reference_cannon),
        str(reference_run),
        *(str(path) for path in roots),
    ]
    for directory in cannon_dirs:
        args += ["--cannon-directory", str(directory)]
    args += [
        "--chunk-limit",
        str(chunk_limit),
        "--include-pattern",
        include_pattern,
        "--max-runtime-contract-runs",
        str(max_runtime_contract_runs),
        "--max-geometry-candidates",
        str(max_geometry_candidates),
        "--max-runtime-candidates",
        str(max_runtime_candidates),
        "--minimum-dispenser-survival",
        str(minimum_dispenser_survival),
        "--minimum-self-damage-reduction",
        str(minimum_self_damage_reduction),
        "--minimum-target-retention",
        str(minimum_target_retention),
        "--maximum-structural-change-ratio",
        str(maximum_structural_change_ratio),
    ]
    return _run_json(args, timeout=900)


@mcp.tool()
def extend_repair_family_runtime(
    source_report: str,
    runtime_rank_from: int = 1,
    runtime_count: int = 4,
    max_runtime_contract_runs: int = 1,
    include_existing: bool = False,
) -> dict[str, Any]:
    """Add causal replay to a prior repair tournament rank window without rerunning geometry."""
    report = _inside_root(source_report)
    args = [
        sys.executable,
        str(SCRIPTS / "extend-repair-family-runtime.py"),
        str(report),
        "--runtime-rank-from",
        str(runtime_rank_from),
        "--runtime-count",
        str(runtime_count),
        "--max-runtime-contract-runs",
        str(max_runtime_contract_runs),
    ]
    if include_existing:
        args.append("--include-existing")
    return _run_json(args, timeout=900)



@mcp.tool()
def profile_cannon(
    path: str,
    reference_paths: list[str] | None = None,
    intent: str = "modern-raid",
    chunk_limit: int = 160,
) -> dict[str, Any]:
    """Compare a candidate with real reference cannons and reject fake-modern geometry in seconds."""
    if intent not in {"calibration", "modern-raid"}:
        raise ValueError("intent must be calibration or modern-raid")
    source = _inside_root(path)
    return _run_json([
        sys.executable,
        str(SCRIPTS / "cannon-geometry-profile.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
        "--intent",
        intent,
        *_reference_args(reference_paths),
    ])


@mcp.tool()
def prepare_reference_cannon(
    source_path: str,
    output_path: str,
    reference_paths: list[str] | None = None,
    intent: str = "calibration",
    chunk_limit: int = 160,
    data_version: int = 3465,
) -> dict[str, Any]:
    """Convert a proven source to deterministic Sponge v2, then audit and profile the exact output."""
    if intent not in {"calibration", "modern-raid"}:
        raise ValueError("intent must be calibration or modern-raid")
    source = _inside_root(source_path)
    output = _inside_root(output_path, must_exist=False)
    if output.suffix.lower() != ".schem":
        raise ValueError("output_path must end in .schem")
    if output.exists():
        raise FileExistsError(output)

    conversion = _run_json([
        sys.executable,
        str(SCRIPTS / "schem-audit.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
        "--convert-sponge-out",
        str(output),
        "--output-data-version",
        str(data_version),
        "--allow-data-version-retag",
    ])
    if not output.exists():
        return {
            "status": "FAIL",
            "conversion": conversion,
            "error": "conversion did not produce the requested output",
        }

    output_audit = _run_json([
        sys.executable,
        str(SCRIPTS / "schem-audit.py"),
        str(output),
        "--chunk-limit",
        str(chunk_limit),
        "--expect-format",
        "sponge-v2",
    ])
    static_map = _run_json([
        sys.executable,
        str(SCRIPTS / "cannon-static-map.py"),
        str(output),
        "--chunk-limit",
        str(chunk_limit),
    ])
    profile = _run_json([
        sys.executable,
        str(SCRIPTS / "cannon-geometry-profile.py"),
        str(output),
        "--chunk-limit",
        str(chunk_limit),
        "--intent",
        intent,
        *_reference_args(reference_paths),
    ])
    return {
        "status": (
            "PASS"
            if output_audit.get("status") == "PASS"
            and profile.get("status") == "PASS"
            else "FAIL"
        ),
        "source": str(source.relative_to(ROOT)),
        "output": str(output.relative_to(ROOT)),
        "conversion": conversion,
        "output_audit": output_audit,
        "static_map": static_map,
        "geometry_profile": profile,
        "truth_boundary": (
            "Conversion preserves decoded geometry. It does not prove the source's "
            "runtime sequence or ExtremeCraft readiness."
        ),
    }


@mcp.tool()
def audit_cannon_corpus(
    directory: str,
    chunk_limit: int = 160,
    minimum_shared_core_components: int = 8,
    minimum_shared_functional: int = 16,
    minimum_connected_functional: int = 8,
    minimum_shared_non_dispenser: int = 8,
    minimum_mechanism_diversity: int = 2,
    skip_partial_core_overlap: bool = False,
) -> dict[str, Any]:
    """Batch-audit a private cannon directory, including whole-module and translated partial-core overlap."""
    source = _inside_root(directory)
    args = [
        sys.executable,
        str(SCRIPTS / "audit-cannon-corpus.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
        "--minimum-shared-core-components",
        str(minimum_shared_core_components),
        "--minimum-shared-functional",
        str(minimum_shared_functional),
        "--minimum-connected-functional",
        str(minimum_connected_functional),
        "--minimum-shared-non-dispenser",
        str(minimum_shared_non_dispenser),
        "--minimum-mechanism-diversity",
        str(minimum_mechanism_diversity),
    ]
    if skip_partial_core_overlap:
        args.append("--skip-partial-core-overlap")
    return _run_json(args)


@mcp.tool()
def explain_shot(trace_path: str) -> dict[str, Any]:
    """Explain one causal-events.csv trace without inventing cannon subsystem labels."""
    trace = _inside_root(trace_path)
    return _run_json([
        sys.executable,
        str(SCRIPTS / "explain-causal-trace.py"),
        str(trace),
    ])


@mcp.tool()
def analyze_shot_quality(
    trace_or_results: str,
    impact_window: float = 12.0,
    max_trigger_to_first_dispense: int | None = None,
    min_largest_dispense_cohort: int | None = None,
    max_target_impact_radius: float | None = None,
    max_self_damage: int | None = None,
    require_falling_block: bool = False,
) -> dict[str, Any]:
    """Score firing latency, synchronized cohorts, target convergence, falling payload and cannon self-damage."""
    source = _inside_root(trace_or_results)
    args = [
        sys.executable,
        str(SCRIPTS / "analyze-causal-quality.py"),
        str(source),
        "--impact-window",
        str(impact_window),
    ]
    if max_trigger_to_first_dispense is not None:
        args += ["--max-trigger-to-first-dispense", str(max_trigger_to_first_dispense)]
    if min_largest_dispense_cohort is not None:
        args += ["--min-largest-dispense-cohort", str(min_largest_dispense_cohort)]
    if max_target_impact_radius is not None:
        args += ["--max-target-impact-radius", str(max_target_impact_radius)]
    if max_self_damage is not None:
        args += ["--max-self-damage", str(max_self_damage)]
    if require_falling_block:
        args.append("--require-falling-block")
    return _run_json(args)


@mcp.tool()
def audit_ec_calibration(evidence_path: str) -> dict[str, Any]:
    """Validate whether a live ExtremeCraft calibration evidence pack is complete enough to claim EC calibration."""
    evidence = _inside_root(evidence_path)
    return _run_json([
        sys.executable,
        str(SCRIPTS / "audit-ec-calibration.py"),
        str(evidence),
    ])


@mcp.tool()
def query_timeline(
    trace_path: str,
    event: str = "",
    start_tick: int = 0,
    end_tick: int = 10_000,
    limit: int = 500,
) -> list[dict[str, str]]:
    """Return filtered causal events from one shot."""
    import csv

    trace = _inside_root(trace_path)
    wanted = event.strip().upper()
    output: list[dict[str, str]] = []
    with trace.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            tick = int(row.get("tick") or 0)
            if tick < start_tick or tick > end_tick:
                continue
            if wanted and (row.get("event") or "").upper() != wanted:
                continue
            output.append(dict(row))
            if len(output) >= max(1, min(limit, 5000)):
                break
    return output


@mcp.tool()
def list_shot_traces(results_root: str = "lab-artifacts/results") -> list[str]:
    """List causal traces currently available in CannonLab artifacts."""
    root = _inside_root(results_root, must_exist=False)
    if not root.exists():
        return []
    return [
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in sorted(root.rglob("causal-events.csv"))
    ]


@mcp.tool()
def compare_shots(first_trace: str, second_trace: str) -> dict[str, Any]:
    """Compare two shot explanations by cohorts, event counts, timing, and confidence."""
    first = explain_shot(first_trace)
    second = explain_shot(second_trace)
    keys = [
        "event_counts",
        "dispense_cohorts",
        "entity_cohorts",
        "piston_cohorts",
        "explosion_ticks",
        "trace_confidence",
    ]
    return {
        "first": {key: first.get(key) for key in keys},
        "second": {key: second.get(key) for key in keys},
    }


@mcp.tool()
def list_cannon_sources(compact: bool = True) -> dict[str, Any]:
    """List the durable cannon source registry with evidence levels and truth boundaries."""
    args = [
        sys.executable,
        str(SCRIPTS / "cannon-forge.py"),
        "sources",
    ]
    if compact:
        args.append("--compact")
    return _run_json(args)


@mcp.tool()
def stage_cannon_forge(
    candidate_path: str,
    fire_input_x: int,
    fire_input_y: int,
    fire_input_z: int,
    base: str,
    specializations: list[str] | None = None,
    payload_mode: str = "auto",
    control_states_json: list[str] | None = None,
    reference_paths: list[str] | None = None,
    job: str = "",
    intent: str = "modern-raid",
    chunk_limit: int = 160,
    origin_x: int = 0,
    origin_y: int = 0,
    origin_z: int = 0,
    fire_mode: str = "button",
    direction: str = "north",
    distance: int = 160,
    width: int = 17,
    height: int = 32,
    shots: int = 10,
) -> dict[str, Any]:
    """Run static intake and stage a fail-closed dry/watered/regen/mixed/endurance campaign."""
    if intent not in {"calibration", "modern-raid"}:
        raise ValueError("intent must be calibration or modern-raid")
    if fire_mode not in {"button", "redstone"}:
        raise ValueError("fire_mode must be button or redstone")
    if direction not in {"north", "south", "east", "west"}:
        raise ValueError("direction must be north, south, east, or west")
    if payload_mode not in {"auto", "falling-block-required", "tnt-only"}:
        raise ValueError("invalid payload_mode")
    candidate = _inside_runtime(candidate_path)
    references = [_inside_runtime(path) for path in reference_paths or []]
    args = [
        sys.executable,
        str(SCRIPTS / "cannon-forge.py"),
        "stage",
        str(candidate),
        "--intent",
        intent,
        "--base",
        base,
        "--payload-mode",
        payload_mode,
        "--chunk-limit",
        str(chunk_limit),
        "--origin",
        f"{origin_x},{origin_y},{origin_z}",
        "--fire-input",
        f"{fire_input_x},{fire_input_y},{fire_input_z}",
        "--fire-mode",
        fire_mode,
        "--direction",
        direction,
        "--distance",
        str(distance),
        "--width",
        str(width),
        "--height",
        str(height),
        "--shots",
        str(shots),
    ]
    if job:
        args += ["--job", job]
    for specialization in specializations or []:
        args += ["--specialization", specialization]
    for control_state in control_states_json or []:
        args += ["--control-state-json", control_state]
    for reference in references:
        args += ["--reference", str(reference)]
    return _run_json(args, timeout=900)


@mcp.tool()
def audit_general_cannon_readiness(requirement: str = "") -> dict[str, Any]:
    """Audit CannonLab's general modern-cannon knowledge, runtime gates, and operator integration."""
    allowed = {"", "diagnostic-prototype", "local-candidate", "ec-ready", "operator-ready"}
    if requirement not in allowed:
        raise ValueError(
            "requirement must be empty, diagnostic-prototype, local-candidate, ec-ready, or operator-ready"
        )
    args = [
        sys.executable,
        str(SCRIPTS / "general-cannon-intelligence.py"),
        "audit",
    ]
    if requirement:
        args += ["--require", requirement]
    return _run_json(args, timeout=300)


@mcp.tool()
def plan_general_cannon(
    base: str,
    specializations: list[str] | None = None,
    lifecycle: str = "diagnostic-prototype",
) -> dict[str, Any]:
    """Build a fail-closed experiment plan for one modern cannon base plus selected specializations."""
    if lifecycle not in {"diagnostic-prototype", "local-candidate", "ec-ready"}:
        raise ValueError("invalid lifecycle")
    args = [
        sys.executable,
        str(SCRIPTS / "general-cannon-intelligence.py"),
        "plan",
        "--base",
        base,
        "--lifecycle",
        lifecycle,
    ]
    for specialization in specializations or []:
        args += ["--specialization", specialization]
    return _run_json(args, timeout=300)


@mcp.tool()
def diagnose_general_cannon(symptoms: list[str]) -> dict[str, Any]:
    """Rank the next cannon modules and measurements to inspect from observed failure symptoms."""
    cleaned = [symptom.strip() for symptom in symptoms if symptom.strip()]
    if not cleaned:
        raise ValueError("at least one non-empty symptom is required")
    args = [
        sys.executable,
        str(SCRIPTS / "general-cannon-intelligence.py"),
        "diagnose",
    ]
    for symptom in cleaned:
        args += ["--symptom", symptom]
    return _run_json(args, timeout=300)


@mcp.tool()
def mutate_cannon_bounded(plan_path: str) -> dict[str, Any]:
    """Apply one reviewed, deterministic, reference-preserving schematic mutation plan."""
    plan = _inside_runtime(plan_path)
    return _run_json(
        [sys.executable, str(SCRIPTS / "cannon-mutator.py"), str(plan)],
        timeout=1200,
    )


@mcp.tool()
def generate_cannon_variants(spec_path: str, apply: bool = True) -> dict[str, Any]:
    """Enumerate every declared bounded variant without random sampling, then apply static gates."""
    spec = _inside_runtime(spec_path)
    args = [
        sys.executable,
        str(SCRIPTS / "cannon-variant-search.py"),
        "generate",
        str(spec),
    ]
    if not apply:
        args.append("--no-apply")
    return _run_json(args, timeout=3600)


@mcp.tool()
def rank_cannon_variants(manifest_path: str, runtime_scorecard_path: str) -> dict[str, Any]:
    """Rank statically safe variants using predeclared runtime metrics, weights, and hard limits."""
    manifest = _inside_runtime(manifest_path)
    scorecard = _inside_runtime(runtime_scorecard_path)
    return _run_json(
        [
            sys.executable,
            str(SCRIPTS / "cannon-variant-search.py"),
            "rank",
            str(manifest),
            str(scorecard),
        ],
        timeout=1200,
    )


@mcp.tool()
def extract_cannon_variant_scorecard(
    manifest_path: str,
    result_map_path: str,
) -> dict[str, Any]:
    """Extract conservative per-variant runtime metrics from supplied CannonLab run summaries."""
    manifest = _inside_runtime(manifest_path)
    result_map = _inside_runtime(result_map_path)
    return _run_json(
        [
            sys.executable,
            str(SCRIPTS / "cannon-variant-scorecard.py"),
            str(manifest),
            str(result_map),
        ],
        timeout=1200,
    )


@mcp.tool()
def prepare_cannon_operator(
    candidate_path: str,
    architecture_manifest_path: str,
    fire_input_x: int,
    fire_input_y: int,
    fire_input_z: int,
    base: str,
    specializations: list[str] | None = None,
    lifecycle: str = "diagnostic-prototype",
    payload_mode: str = "auto",
    control_states_json: list[str] | None = None,
    reference_paths: list[str] | None = None,
    mutation_plan_path: str = "",
    job: str = "",
    intent: str = "modern-raid",
    chunk_limit: int = 160,
    origin_x: int = 0,
    origin_y: int = 0,
    origin_z: int = 0,
    fire_mode: str = "button",
    direction: str = "north",
    distance: int = 160,
    width: int = 17,
    height: int = 32,
    shots: int = 10,
) -> dict[str, Any]:
    """Bind general planning, optional bounded mutation, architecture policy, and Cannon Forge into one job."""
    if lifecycle not in {"diagnostic-prototype", "local-candidate", "ec-ready"}:
        raise ValueError("invalid lifecycle")
    if intent not in {"calibration", "modern-raid"}:
        raise ValueError("intent must be calibration or modern-raid")
    if fire_mode not in {"button", "redstone"}:
        raise ValueError("fire_mode must be button or redstone")
    if direction not in {"north", "south", "east", "west"}:
        raise ValueError("direction must be north, south, east, or west")
    if payload_mode not in {"auto", "falling-block-required", "tnt-only"}:
        raise ValueError("invalid payload_mode")
    if min(chunk_limit, distance, width, height, shots) < 1:
        raise ValueError("chunk limit, dimensions, distance, and shots must be positive")

    candidate = _inside_runtime(candidate_path)
    architecture_manifest = _inside_runtime(architecture_manifest_path)
    references = [_inside_runtime(path) for path in reference_paths or []]
    mutation_plan = _inside_runtime(mutation_plan_path) if mutation_plan_path else None
    args = [
        sys.executable,
        str(SCRIPTS / "cannon-operator.py"),
        "prepare",
        str(candidate),
        "--architecture-manifest",
        str(architecture_manifest),
        "--base",
        base,
        "--lifecycle",
        lifecycle,
        "--payload-mode",
        payload_mode,
        "--intent",
        intent,
        "--chunk-limit",
        str(chunk_limit),
        "--origin",
        f"{origin_x},{origin_y},{origin_z}",
        "--fire-input",
        f"{fire_input_x},{fire_input_y},{fire_input_z}",
        "--fire-mode",
        fire_mode,
        "--direction",
        direction,
        "--distance",
        str(distance),
        "--width",
        str(width),
        "--height",
        str(height),
        "--shots",
        str(shots),
    ]
    if job:
        args += ["--job", job]
    if mutation_plan is not None:
        args += ["--mutation-plan", str(mutation_plan)]
    for specialization in specializations or []:
        args += ["--specialization", specialization]
    for control_state in control_states_json or []:
        args += ["--control-state-json", control_state]
    for reference in references:
        args += ["--reference", str(reference)]
    return _run_json(args, timeout=1800)


@mcp.tool()
def run_cannon_operator(manifest_path: str, execute: bool = False) -> dict[str, Any]:
    """Show the exact staged local campaign command, or execute it when explicitly requested."""
    manifest = _inside_runtime(manifest_path)
    args = [
        sys.executable,
        str(SCRIPTS / "cannon-operator.py"),
        "run",
        str(manifest),
    ]
    if execute:
        args.append("--execute")
    return _run_json(args, timeout=3600)


@mcp.tool()
def audit_private_cannon_corpus(
    directory_path: str,
    job: str = "",
    chunk_limit: int = 160,
    baseline_manifest_path: str = "",
    require_unchanged_sources: bool = False,
) -> dict[str, Any]:
    """Hash and structurally regression-check a private schematic corpus without publishing its binaries."""
    if chunk_limit < 1:
        raise ValueError("chunk_limit must be positive")
    directory = _inside_runtime(directory_path)
    if not directory.is_dir():
        raise ValueError("directory_path must identify a directory")
    baseline = _inside_runtime(baseline_manifest_path) if baseline_manifest_path else None
    args = [
        sys.executable,
        str(SCRIPTS / "private-corpus-regression.py"),
        str(directory),
        "--chunk-limit",
        str(chunk_limit),
    ]
    if job:
        args += ["--job", job]
    if baseline is not None:
        args += ["--baseline-manifest", str(baseline)]
    if require_unchanged_sources:
        args.append("--require-unchanged-sources")
    return _run_json(args, timeout=1800)



def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
