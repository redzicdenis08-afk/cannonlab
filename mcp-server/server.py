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
    return {"audit": audit, "static_map": static_map, "module_map": module_map}


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
        "static_map": static_map,
        "module_map": module_map,
        "geometry_profile": profile,
        "next_action": (
            "Use a proven reference as the edit base. Do not generate a modern raid "
            "candidate from flat dispenser rows when the profile fails."
        ),
    }


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
def analyze_repair_family(
    reference_schematic: str,
    reference_summary: str,
    candidate_roots: list[str],
    cannon_directories: list[str],
    chunk_limit: int = 160,
    include_pattern: str = "",
    max_runtime_contract_runs: int = 3,
    minimum_dispenser_survival: float = 0.95,
    minimum_self_damage_reduction: float = 0.10,
    minimum_target_retention: float = 0.80,
    maximum_structural_change_ratio: float = 0.03,
) -> dict[str, Any]:
    """Rank bounded repair variants by survival, self-damage, target retention, repeatability, and collateral drift."""
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
