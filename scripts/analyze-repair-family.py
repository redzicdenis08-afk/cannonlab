#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

TEST_CONTRACT_FIELDS = (
    "target_type",
    "target_direction",
    "target_material",
    "target_alternate_material",
    "target_distance",
    "target_layers",
    "target_spacing",
    "target_bounds",
    "arena_origin",
    "regeneration",
)
REQUIRED_TEST_CONTRACT_FIELDS = (
    "target_type",
    "target_direction",
    "target_distance",
    "target_layers",
    "target_bounds",
    "arena_origin",
    "regeneration",
    "target_blocks_total",
)

def load_script(name: str, filename: str) -> Any:
    script = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mean(values: Iterable[float]) -> float:
    rows = list(values)
    return statistics.fmean(rows) if rows else 0.0


def stability(values: Iterable[float]) -> float:
    rows = list(values)
    if len(rows) < 2:
        return 1.0
    average = mean(rows)
    if average == 0:
        return 1.0 if all(value == 0 for value in rows) else 0.0
    coefficient = statistics.pstdev(rows) / abs(average)
    return max(0.0, 1.0 - min(1.0, coefficient))


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def discover_summaries(roots: list[Path]) -> list[Path]:
    output: set[Path] = set()
    for root in roots:
        if root.is_file() and root.name == "run-summary.json":
            output.add(root.resolve())
        elif root.exists():
            output.update(path.resolve() for path in root.rglob("run-summary.json"))
    return sorted(output)


def unique_summary_paths(paths: Iterable[Path]) -> list[Path]:
    selected: dict[str, Path] = {}
    fingerprints: dict[str, str] = {}
    for path in sorted(path.resolve() for path in paths):
        payload = read_json(path)
        run_id = str(payload.get("run_id") or path)
        fingerprint = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if run_id in fingerprints and fingerprints[run_id] != fingerprint:
            raise ValueError(f"conflicting run-summary payloads share run_id {run_id!r}")
        fingerprints[run_id] = fingerprint
        current = selected.get(run_id)
        if current is None:
            selected[run_id] = path
            continue
        current_has_trace = shot_trace(current) is not None
        candidate_has_trace = shot_trace(path) is not None
        if candidate_has_trace and not current_has_trace:
            selected[run_id] = path
        elif candidate_has_trace == current_has_trace and len(str(path)) < len(str(current)):
            selected[run_id] = path
    return sorted(selected.values())


def resolve_schematic(
    cannon_file: str,
    directories: list[Path],
) -> Path | None:
    raw = Path(cannon_file)
    if raw.is_absolute() and raw.is_file():
        return raw.resolve()
    candidates: list[Path] = []
    for directory in directories:
        direct = directory / raw.name
        if direct.is_file():
            candidates.append(direct.resolve())
        candidates.extend(
            path.resolve()
            for path in directory.rglob(raw.name)
            if path.is_file()
        )
    unique = sorted(set(candidates))
    return unique[0] if len(unique) == 1 else None


def shot_trace(summary_path: Path, shot_number: int = 1) -> Path | None:
    direct = summary_path.parent / f"shot-{shot_number:03d}" / "causal-events.csv"
    if direct.is_file():
        return direct
    if shot_number != 1:
        return None
    candidates = sorted(summary_path.parent.glob("shot-*/causal-events.csv"))
    return candidates[0] if candidates else None


def shot_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    shots = summary.get("shots")
    return [row for row in shots if isinstance(row, dict)] if isinstance(shots, list) else []


def test_contract(summary: dict[str, Any]) -> dict[str, Any]:
    rows = shot_rows(summary)
    return {
        **{field: summary.get(field) for field in TEST_CONTRACT_FIELDS},
        "target_blocks_total": sorted({
            int(row.get("target_blocks_total") or 0)
            for row in rows
        }),
    }


def contract_differences(
    reference: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        key: {"reference": reference.get(key), "candidate": candidate.get(key)}
        for key in sorted(set(reference) | set(candidate))
        if reference.get(key) != candidate.get(key)
    }


def missing_test_contract_fields(contract: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_TEST_CONTRACT_FIELDS:
        value = contract.get(field)
        if value is None or value == [] or value == {}:
            missing.append(field)
        elif field == "target_blocks_total" and not any(int(item) > 0 for item in value):
            missing.append(field)
    return missing


def available_shot_traces(summary_path: Path) -> list[tuple[int, Path]]:
    payload = read_json(summary_path)
    output: list[tuple[int, Path]] = []
    for index, row in enumerate(shot_rows(payload), start=1):
        shot_number = int(row.get("shot") or index)
        trace = shot_trace(summary_path, shot_number)
        if trace is not None:
            output.append((shot_number, trace))
    if not output:
        fallback = shot_trace(summary_path)
        if fallback is not None:
            output.append((1, fallback))
    return output


def summarize_performance(summary_paths: list[Path]) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    shots: list[dict[str, Any]] = []
    for path in unique_summary_paths(summary_paths):
        payload = read_json(path)
        rows = shot_rows(payload)
        shots.extend(rows)
        runs.append({
            "run_id": payload.get("run_id", path.parent.name),
            "scenario": payload.get("scenario"),
            "summary": str(path),
            "trace": str(shot_trace(path)) if shot_trace(path) else None,
            "shots_requested": int(payload.get("shots_requested") or len(rows) or 1),
            "shots_completed": int(payload.get("shots_completed") or len(rows)),
            "finish_reason": payload.get("finish_reason"),
        })

    requested = sum(int(run["shots_requested"]) for run in runs)
    completed = len(shots)
    errors = sum(1 for shot in shots if shot.get("error") is not None)
    contract_passes = sum(bool(shot.get("contract_pass")) for shot in shots)
    dispenser_ratios = [
        float(shot.get("cannon_remaining_dispensers") or 0)
        / max(1.0, float(shot.get("cannon_initial_dispensers") or 0))
        for shot in shots
    ]
    self_damage = [float(shot.get("self_damage_blocks") or 0) for shot in shots]
    target_destroyed = [float(shot.get("target_blocks_destroyed") or 0) for shot in shots]
    target_ratios = [
        float(shot.get("target_blocks_destroyed") or 0)
        / max(1.0, float(shot.get("target_blocks_total") or 0))
        for shot in shots
    ]
    explosions = [float(shot.get("explosions") or 0) for shot in shots]
    spawns = [
        float(((shot.get("cohorts") or {}).get("global") or {}).get("spawns") or 0)
        for shot in shots
    ]
    forward = [float(shot.get("maximum_forward_distance") or 0) for shot in shots]
    missing_blocks = [float(shot.get("cannon_missing_blocks") or 0) for shot in shots]
    replaced_blocks = [float(shot.get("cannon_replaced_type_blocks") or 0) for shot in shots]

    return {
        "run_count": len(runs),
        "shot_count": completed,
        "shots_requested": requested,
        "completion_rate": completed / max(1, requested),
        "error_rate": errors / max(1, requested),
        "contract_pass_rate": contract_passes / max(1, requested),
        "mean_dispenser_survival": mean(dispenser_ratios),
        "minimum_dispenser_survival": min(dispenser_ratios, default=0.0),
        "mean_self_damage": mean(self_damage),
        "maximum_self_damage": max(self_damage, default=0.0),
        "self_damage_stability": stability(self_damage),
        "mean_target_destroyed": mean(target_destroyed),
        "minimum_target_destroyed": min(target_destroyed, default=0.0),
        "target_damage_stability": stability(target_destroyed),
        "mean_target_ratio": mean(target_ratios),
        "mean_explosions": mean(explosions),
        "explosion_stability": stability(explosions),
        "mean_spawns": mean(spawns),
        "spawn_stability": stability(spawns),
        "mean_forward_distance": mean(forward),
        "mean_missing_blocks": mean(missing_blocks),
        "mean_replaced_type_blocks": mean(replaced_blocks),
        "runs": runs,
    }


def permissive_preservation(
    checker: Any,
    reference: Path,
    candidate: Path,
    chunk_limit: int,
) -> dict[str, Any]:
    return checker.build_report(
        reference,
        candidate,
        chunk_limit=chunk_limit,
        max_structural_change_ratio=1.0,
        max_functional_change_ratio=1.0,
        max_modules_touched=100_000,
        max_unexpected_critical_changes=100_000,
        allowed_types={"minecraft:dispenser"},
        allow_dimension_change=True,
        allow_block_entity_topology_change=True,
        allow_ambiguous_alignment=True,
        minimum_alignment_confidence="low",
    )


def compact_runtime_contract(report: dict[str, Any]) -> dict[str, Any]:
    failed = [
        {
            "first_module_id": row.get("first_module_id"),
            "second_module_id": row.get("second_module_id"),
            "failures": row.get("failures") or [],
            "timing": row.get("timing"),
            "physics_max_observed": (row.get("entity_physics") or {}).get("max_observed"),
        }
        for row in report.get("module_runtime_contracts") or []
        if row.get("status") == "FAIL"
    ]
    shared_contract = report.get("shared_component_cohort_contract") or {}
    shared_failures = [
        {
            "module_ids": row.get("module_ids") or [],
            "failures": row.get("failures") or [],
            "component_ids": row.get("component_ids") or {},
            "event_counts": row.get("event_counts") or {},
            "event_tick_max_deltas": {
                event: details.get("max_absolute_delta")
                for event, details in (row.get("event_ticks") or {}).items()
            },
        }
        for row in shared_contract.get("comparisons") or []
        if row.get("status") == "FAIL"
    ]
    joint_contract = report.get("joint_entity_cohort_contract") or {}
    joint_failures = [
        {
            "module_ids": row.get("module_ids") or [],
            "entity_type": row.get("entity_type"),
            "failures": row.get("failures") or [],
            "pairs": [
                {
                    "failures": pair.get("failures") or [],
                    "spawn_tick_delta": (pair.get("spawn_tick") or {}).get("delta"),
                    "spawn_position_delta": (pair.get("spawn_point") or {}).get("distance"),
                    "source_components": pair.get("source_components") or {},
                    "explosion_tick_delta": (pair.get("explosion_timing") or {}).get("max_absolute_delta"),
                    "physics_max_observed": (pair.get("physics") or {}).get("max_observed"),
                }
                for pair in row.get("pairs") or []
                if pair.get("status") == "FAIL"
            ],
        }
        for row in joint_contract.get("comparisons") or []
        if row.get("status") == "FAIL"
    ]
    return {
        "status": report.get("status"),
        "failures": report.get("failures") or [],
        "summary": report.get("summary") or {},
        "failed_modules": failed,
        "shared_component_cohort_status": shared_contract.get("status"),
        "failed_shared_component_cohorts": shared_failures,
        "joint_entity_cohort_status": joint_contract.get("status"),
        "failed_joint_entity_cohorts": joint_failures,
    }


def runtime_contracts(
    contract_tool: Any,
    comparison: dict[str, Any],
    reference_schematic: Path,
    reference_trace: Path | None,
    candidate_schematic: Path,
    candidate_summaries: list[Path],
    *,
    chunk_limit: int,
    max_runs: int,
) -> list[dict[str, Any]]:
    if reference_trace is None:
        return []
    allowed_reference = {
        str(row.get("module_id"))
        for row in comparison.get("unmatched_first_modules") or []
    }
    allowed_candidate = {
        str(row.get("module_id"))
        for row in comparison.get("unmatched_second_modules") or []
    }
    reports: list[dict[str, Any]] = []
    selected_summaries = sorted(
        unique_summary_paths(candidate_summaries),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    trace_candidates: list[tuple[Path, int, Path]] = []
    summaries_without_traces: list[Path] = []
    for summary_path in selected_summaries:
        traces = available_shot_traces(summary_path)
        if not traces:
            summaries_without_traces.append(summary_path)
            continue
        trace_candidates.extend(
            (summary_path, shot_number, trace)
            for shot_number, trace in traces
        )

    for summary_path in summaries_without_traces[:max_runs]:
        reports.append({
            "status": "NO_TRACE",
            "summary": str(summary_path),
            "shot": None,
            "trace": None,
        })
    remaining = max(0, max_runs - len(reports))
    for summary_path, shot_number, trace in trace_candidates[:remaining]:
        if trace is None:
            reports.append({
                "status": "NO_TRACE",
                "summary": str(summary_path),
                "shot": shot_number,
                "trace": None,
            })
            continue
        report = contract_tool.build_report(
            reference_schematic,
            reference_trace,
            candidate_schematic,
            trace,
            chunk_limit=chunk_limit,
            allowed_reference_modules=allowed_reference,
            allowed_candidate_modules=allowed_candidate,
        )
        reports.append({
            "summary": str(summary_path),
            "shot": shot_number,
            "trace": str(trace),
            **compact_runtime_contract(report),
        })
    return reports




def aggregate_runtime_drift(runtime_reports: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [
        report
        for report in runtime_reports
        if report.get("status") in {"PASS", "FAIL"}
    ]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    shared_grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    joint_grouped: dict[tuple[tuple[str, ...], str], list[dict[str, Any]]] = defaultdict(list)
    for report in completed:
        for row in report.get("failed_modules") or []:
            key = (
                str(row.get("first_module_id") or ""),
                str(row.get("second_module_id") or ""),
            )
            grouped[key].append(row)
        for row in report.get("failed_shared_component_cohorts") or []:
            shared_grouped[
                tuple(str(value) for value in row.get("module_ids") or [])
            ].append(row)
        for row in report.get("failed_joint_entity_cohorts") or []:
            joint_grouped[(
                tuple(str(value) for value in row.get("module_ids") or []),
                str(row.get("entity_type") or "UNKNOWN"),
            )].append(row)

    modules = []
    for (first_id, second_id), rows in sorted(grouped.items()):
        failure_sets = [tuple(sorted(str(value) for value in row.get("failures") or [])) for row in rows]
        timing_deltas: dict[str, list[int]] = defaultdict(list)
        physics_values: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            for field, timing in (row.get("timing") or {}).items():
                delta = timing.get("delta") if isinstance(timing, dict) else None
                if delta is not None:
                    timing_deltas[field].append(int(delta))
            for field, value in (row.get("physics_max_observed") or {}).items():
                if isinstance(value, (int, float)):
                    physics_values[field].append(float(value))
        modules.append({
            "first_module_id": first_id,
            "second_module_id": second_id,
            "reports_failed": len(rows),
            "reports_checked": len(completed),
            "occurrence_rate": len(rows) / max(1, len(completed)),
            "consistent_failure_set": len(set(failure_sets)) <= 1,
            "consistent_across_all_reports": (
                len(rows) == len(completed)
                and len(set(failure_sets)) <= 1
            ),
            "failure_counts": dict(sorted(Counter(
                failure
                for failures in failure_sets
                for failure in failures
            ).items())),
            "timing_delta_ranges": {
                field: {
                    "min": min(values),
                    "max": max(values),
                    "mean": mean(values),
                }
                for field, values in sorted(timing_deltas.items())
            },
            "physics_ranges": {
                field: {
                    "min": min(values),
                    "max": max(values),
                    "mean": mean(values),
                }
                for field, values in sorted(physics_values.items())
            },
        })
    shared_cohorts = [
        {
            "module_ids": list(module_ids),
            "reports_failed": len(rows),
            "reports_checked": len(completed),
            "occurrence_rate": len(rows) / max(1, len(completed)),
            "consistent_across_all_reports": len(rows) == len(completed),
            "failure_counts": dict(sorted(Counter(
                failure
                for row in rows
                for failure in row.get("failures") or []
            ).items())),
            "examples": rows[:1],
        }
        for module_ids, rows in sorted(shared_grouped.items())
    ]
    joint_cohorts = [
        {
            "module_ids": list(key[0]),
            "entity_type": key[1],
            "reports_failed": len(rows),
            "reports_checked": len(completed),
            "occurrence_rate": len(rows) / max(1, len(completed)),
            "consistent_across_all_reports": len(rows) == len(completed),
            "failure_counts": dict(sorted(Counter(
                failure
                for row in rows
                for failure in row.get("failures") or []
            ).items())),
            "examples": rows[:1],
        }
        for key, rows in sorted(joint_grouped.items())
    ]
    return {
        "reports_checked": len(completed),
        "reports_passed": sum(report.get("status") == "PASS" for report in completed),
        "reports_failed": sum(report.get("status") == "FAIL" for report in completed),
        "drifting_module_count": len(modules),
        "deterministic_drifting_modules": sum(
            bool(row["consistent_across_all_reports"])
            for row in modules
        ),
        "modules": modules,
        "drifting_shared_cohort_count": len(shared_cohorts),
        "deterministic_shared_cohorts": sum(
            bool(row["consistent_across_all_reports"])
            for row in shared_cohorts
        ),
        "shared_component_cohorts": shared_cohorts,
        "drifting_joint_cohort_count": len(joint_cohorts),
        "deterministic_joint_cohorts": sum(
            bool(row["consistent_across_all_reports"])
            for row in joint_cohorts
        ),
        "joint_entity_cohorts": joint_cohorts,
    }

def repair_score(
    performance: dict[str, Any],
    baseline: dict[str, Any],
    structural_change_ratio: float,
    runtime_reports: list[dict[str, Any]],
) -> tuple[float, dict[str, float]]:
    baseline_self = float(baseline.get("mean_self_damage") or 0.0)
    baseline_target = float(baseline.get("mean_target_destroyed") or 0.0)
    self_reduction = (
        (baseline_self - float(performance.get("mean_self_damage") or 0.0))
        / max(1.0, baseline_self)
    )
    target_retention = (
        float(performance.get("mean_target_destroyed") or 0.0)
        / max(1.0, baseline_target)
    )
    protected = sum(
        int((report.get("summary") or {}).get("protected_runtime_contracts") or 0)
        for report in runtime_reports
        if report.get("status") in {"PASS", "FAIL"}
    )
    failed = sum(
        int((report.get("summary") or {}).get("failed_runtime_contracts") or 0)
        for report in runtime_reports
        if report.get("status") in {"PASS", "FAIL"}
    )
    collateral = 1.0 - failed / protected if protected > 0 else 0.0
    repeatability = mean([
        float(performance.get("self_damage_stability") or 0.0),
        float(performance.get("target_damage_stability") or 0.0),
        float(performance.get("explosion_stability") or 0.0),
        float(performance.get("spawn_stability") or 0.0),
    ])
    components = {
        "reliability": max(0.0, min(1.0, mean([
            float(performance.get("completion_rate") or 0.0),
            1.0 - float(performance.get("error_rate") or 0.0),
            float(performance.get("contract_pass_rate") or 0.0),
        ]))),
        "dispenser_survival": max(0.0, min(1.0, float(performance.get("mean_dispenser_survival") or 0.0))),
        "self_damage_reduction": max(0.0, min(1.0, self_reduction)),
        "target_retention": max(0.0, min(1.0, target_retention)),
        "collateral_preservation": max(0.0, min(1.0, collateral)),
        "repeatability": max(0.0, min(1.0, repeatability)),
        "structural_preservation": max(0.0, min(1.0, 1.0 - structural_change_ratio)),
    }
    weights = {
        "reliability": 0.20,
        "dispenser_survival": 0.25,
        "self_damage_reduction": 0.20,
        "target_retention": 0.15,
        "collateral_preservation": 0.10,
        "repeatability": 0.07,
        "structural_preservation": 0.03,
    }
    score = sum(components[key] * weights[key] for key in weights) * 100.0
    return round(score, 6), {key: round(value, 6) for key, value in components.items()}


def screening_score(
    performance: dict[str, Any],
    baseline: dict[str, Any],
    structural_change_ratio: float,
    comparison: dict[str, Any],
) -> tuple[float, dict[str, float]]:
    baseline_self = float(baseline.get("mean_self_damage") or 0.0)
    baseline_target = float(baseline.get("mean_target_destroyed") or 0.0)
    self_reduction = (
        baseline_self - float(performance.get("mean_self_damage") or 0.0)
    ) / max(1.0, baseline_self)
    target_retention = (
        float(performance.get("mean_target_destroyed") or 0.0)
        / max(1.0, baseline_target)
    )
    repeatability = mean([
        float(performance.get("self_damage_stability") or 0.0),
        float(performance.get("target_damage_stability") or 0.0),
        float(performance.get("explosion_stability") or 0.0),
        float(performance.get("spawn_stability") or 0.0),
    ])
    comparison_summary = comparison.get("summary") or {}
    exact_coverage = float(
        comparison_summary.get("first_exact_component_coverage") or 0.0
    )
    components = {
        "reliability": max(0.0, min(1.0, mean([
            float(performance.get("completion_rate") or 0.0),
            1.0 - float(performance.get("error_rate") or 0.0),
            float(performance.get("contract_pass_rate") or 0.0),
        ]))),
        "dispenser_survival": max(
            0.0,
            min(1.0, float(performance.get("mean_dispenser_survival") or 0.0)),
        ),
        "self_damage_reduction": max(0.0, min(1.0, self_reduction)),
        "target_retention": max(0.0, min(1.0, target_retention)),
        "repeatability": max(0.0, min(1.0, repeatability)),
        "structural_preservation": max(
            0.0,
            min(1.0, 1.0 - structural_change_ratio),
        ),
        "exact_module_coverage": max(0.0, min(1.0, exact_coverage)),
    }
    weights = {
        "reliability": 0.25,
        "dispenser_survival": 0.25,
        "self_damage_reduction": 0.20,
        "target_retention": 0.15,
        "repeatability": 0.08,
        "structural_preservation": 0.04,
        "exact_module_coverage": 0.03,
    }
    score = sum(components[key] * weights[key] for key in weights) * 100.0
    return round(score, 6), {
        key: round(value, 6)
        for key, value in components.items()
    }


def metric_screening_score(
    performance: dict[str, Any],
    baseline: dict[str, Any],
) -> tuple[float, dict[str, float]]:
    baseline_self = float(baseline.get("mean_self_damage") or 0.0)
    baseline_target = float(baseline.get("mean_target_destroyed") or 0.0)
    self_reduction = (
        baseline_self - float(performance.get("mean_self_damage") or 0.0)
    ) / max(1.0, baseline_self)
    target_retention = (
        float(performance.get("mean_target_destroyed") or 0.0)
        / max(1.0, baseline_target)
    )
    repeatability = mean([
        float(performance.get("self_damage_stability") or 0.0),
        float(performance.get("target_damage_stability") or 0.0),
        float(performance.get("explosion_stability") or 0.0),
        float(performance.get("spawn_stability") or 0.0),
    ])
    components = {
        "reliability": max(0.0, min(1.0, mean([
            float(performance.get("completion_rate") or 0.0),
            1.0 - float(performance.get("error_rate") or 0.0),
            float(performance.get("contract_pass_rate") or 0.0),
        ]))),
        "dispenser_survival": max(
            0.0,
            min(1.0, float(performance.get("mean_dispenser_survival") or 0.0)),
        ),
        "self_damage_reduction": max(0.0, min(1.0, self_reduction)),
        "target_retention": max(0.0, min(1.0, target_retention)),
        "repeatability": max(0.0, min(1.0, repeatability)),
    }
    weights = {
        "reliability": 0.30,
        "dispenser_survival": 0.30,
        "self_damage_reduction": 0.20,
        "target_retention": 0.15,
        "repeatability": 0.05,
    }
    score = sum(components[key] * weights[key] for key in weights) * 100.0
    return round(score, 6), {
        key: round(value, 6)
        for key, value in components.items()
    }


def passes_metric_screen(
    performance: dict[str, Any],
    baseline: dict[str, Any],
    *,
    minimum_dispenser_survival: float,
    minimum_self_damage_reduction: float,
    minimum_target_retention: float,
) -> bool:
    self_reduction = (
        float(baseline.get("mean_self_damage") or 0.0)
        - float(performance.get("mean_self_damage") or 0.0)
    ) / max(1.0, float(baseline.get("mean_self_damage") or 0.0))
    target_retention = (
        float(performance.get("mean_target_destroyed") or 0.0)
        / max(1.0, float(baseline.get("mean_target_destroyed") or 0.0))
    )
    return all((
        int(performance.get("shot_count") or 0) > 0,
        float(performance.get("completion_rate") or 0.0) >= 1.0,
        float(performance.get("error_rate") or 0.0) <= 0.0,
        float(performance.get("contract_pass_rate") or 0.0) >= 1.0,
        float(performance.get("mean_dispenser_survival") or 0.0)
        >= minimum_dispenser_survival,
        self_reduction >= minimum_self_damage_reduction,
        target_retention >= minimum_target_retention,
    ))


def passes_runtime_screen(
    performance: dict[str, Any],
    baseline: dict[str, Any],
    structural_change_ratio: float,
    *,
    minimum_dispenser_survival: float,
    minimum_self_damage_reduction: float,
    minimum_target_retention: float,
    maximum_structural_change_ratio: float,
) -> bool:
    self_reduction = (
        float(baseline.get("mean_self_damage") or 0.0)
        - float(performance.get("mean_self_damage") or 0.0)
    ) / max(1.0, float(baseline.get("mean_self_damage") or 0.0))
    target_retention = (
        float(performance.get("mean_target_destroyed") or 0.0)
        / max(1.0, float(baseline.get("mean_target_destroyed") or 0.0))
    )
    return all((
        int(performance.get("shot_count") or 0) > 0,
        float(performance.get("completion_rate") or 0.0) >= 1.0,
        float(performance.get("error_rate") or 0.0) <= 0.0,
        float(performance.get("contract_pass_rate") or 0.0) >= 1.0,
        float(performance.get("mean_dispenser_survival") or 0.0)
        >= minimum_dispenser_survival,
        self_reduction >= minimum_self_damage_reduction,
        target_retention >= minimum_target_retention,
        structural_change_ratio <= maximum_structural_change_ratio,
    ))


def dominates(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_metrics = first["decision_metrics"]
    second_metrics = second["decision_metrics"]
    maximize = (
        "mean_dispenser_survival",
        "self_damage_reduction",
        "target_retention",
        "runtime_contract_pass_rate",
    )
    minimize = (
        "structural_change_ratio",
        "failed_protected_modules",
    )
    no_worse = all(first_metrics[key] >= second_metrics[key] for key in maximize) and all(
        first_metrics[key] <= second_metrics[key] for key in minimize
    )
    strictly_better = any(first_metrics[key] > second_metrics[key] for key in maximize) or any(
        first_metrics[key] < second_metrics[key] for key in minimize
    )
    return no_worse and strictly_better




def promotion_verdict(
    performance: dict[str, Any],
    baseline: dict[str, Any],
    runtime_reports: list[dict[str, Any]],
    structural_change_ratio: float,
    *,
    has_geometry_evidence: bool,
    minimum_dispenser_survival: float,
    minimum_self_damage_reduction: float,
    minimum_target_retention: float,
    maximum_structural_change_ratio: float,
) -> dict[str, Any]:
    self_reduction = (
        float(baseline.get("mean_self_damage") or 0.0)
        - float(performance.get("mean_self_damage") or 0.0)
    ) / max(1.0, float(baseline.get("mean_self_damage") or 0.0))
    target_retention = (
        float(performance.get("mean_target_destroyed") or 0.0)
        / max(1.0, float(baseline.get("mean_target_destroyed") or 0.0))
    )
    completed_contracts = [
        report
        for report in runtime_reports
        if report.get("status") in {"PASS", "FAIL"}
    ]
    blockers: list[str] = []
    if not has_geometry_evidence:
        blockers.append("no_geometry_evidence")
    if int(performance.get("shot_count") or 0) <= 0:
        blockers.append("no_completed_shots")
    if float(performance.get("completion_rate") or 0.0) < 1.0:
        blockers.append("incomplete_runs")
    if float(performance.get("error_rate") or 0.0) > 0.0:
        blockers.append("runtime_errors")
    if float(performance.get("contract_pass_rate") or 0.0) < 1.0:
        blockers.append("scenario_contract_failures")
    if float(performance.get("mean_dispenser_survival") or 0.0) < minimum_dispenser_survival:
        blockers.append("dispenser_survival_below_minimum")
    if self_reduction < minimum_self_damage_reduction:
        blockers.append("self_damage_reduction_below_minimum")
    if target_retention < minimum_target_retention:
        blockers.append("target_retention_below_minimum")
    if (
        has_geometry_evidence
        and structural_change_ratio > maximum_structural_change_ratio
    ):
        blockers.append("structural_change_ratio_above_maximum")
    if not completed_contracts:
        blockers.append("no_runtime_contract_evidence")
    elif any(report.get("status") != "PASS" for report in completed_contracts):
        blockers.append("protected_module_runtime_drift")

    promotion_ready = not blockers
    non_contract_blockers = [
        blocker
        for blocker in blockers
        if blocker not in {
            "protected_module_runtime_drift",
            "no_runtime_contract_evidence",
            "no_geometry_evidence",
        }
    ]
    if promotion_ready:
        verdict = "PROMOTION_READY_BOUNDED_REPAIR"
    elif set(blockers).issubset({"no_geometry_evidence", "no_runtime_contract_evidence"}):
        verdict = "INSUFFICIENT_RUNTIME_EVIDENCE"
    elif not non_contract_blockers and "protected_module_runtime_drift" in blockers:
        verdict = "PERFORMANCE_WIN_WITH_COLLATERAL_DRIFT"
    else:
        verdict = "REJECT_OR_REWORK"
    return {
        "promotion_ready": promotion_ready,
        "verdict": verdict,
        "blockers": blockers,
        "observed": {
            "mean_dispenser_survival": performance.get("mean_dispenser_survival"),
            "self_damage_reduction": self_reduction,
            "target_retention": target_retention,
            "structural_change_ratio": structural_change_ratio,
            "runtime_contract_reports": len(completed_contracts),
            "runtime_contract_passes": sum(
                report.get("status") == "PASS"
                for report in completed_contracts
            ),
        },
        "thresholds": {
            "minimum_dispenser_survival": minimum_dispenser_survival,
            "minimum_self_damage_reduction": minimum_self_damage_reduction,
            "minimum_target_retention": minimum_target_retention,
            "maximum_structural_change_ratio": maximum_structural_change_ratio,
        },
    }


def validate_configuration(
    *,
    chunk_limit: int,
    max_runtime_contract_runs: int,
    max_geometry_candidates: int,
    max_runtime_candidates: int,
    minimum_dispenser_survival: float,
    minimum_self_damage_reduction: float,
    minimum_target_retention: float,
    maximum_structural_change_ratio: float,
) -> None:
    if chunk_limit <= 0:
        raise ValueError("chunk_limit must be positive")
    if max_runtime_contract_runs <= 0:
        raise ValueError("max_runtime_contract_runs must be positive")
    if max_geometry_candidates < 0:
        raise ValueError("max_geometry_candidates must be zero or positive")
    if max_runtime_candidates < 0:
        raise ValueError("max_runtime_candidates must be zero or positive")
    for name, value in (
        ("minimum_dispenser_survival", minimum_dispenser_survival),
        ("minimum_self_damage_reduction", minimum_self_damage_reduction),
        ("minimum_target_retention", minimum_target_retention),
        ("maximum_structural_change_ratio", maximum_structural_change_ratio),
    ):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1")


def build_report(
    reference_schematic: Path,
    reference_summary: Path,
    candidate_roots: list[Path],
    cannon_directories: list[Path],
    *,
    chunk_limit: int = 160,
    include_pattern: str = "",
    max_runtime_contract_runs: int = 3,
    max_geometry_candidates: int = 0,
    max_runtime_candidates: int = 0,
    minimum_dispenser_survival: float = 0.95,
    minimum_self_damage_reduction: float = 0.10,
    minimum_target_retention: float = 0.80,
    maximum_structural_change_ratio: float = 0.03,
) -> dict[str, Any]:
    total_started = time.perf_counter()
    validate_configuration(
        chunk_limit=chunk_limit,
        max_runtime_contract_runs=max_runtime_contract_runs,
        max_geometry_candidates=max_geometry_candidates,
        max_runtime_candidates=max_runtime_candidates,
        minimum_dispenser_survival=minimum_dispenser_survival,
        minimum_self_damage_reduction=minimum_self_damage_reduction,
        minimum_target_retention=minimum_target_retention,
        maximum_structural_change_ratio=maximum_structural_change_ratio,
    )
    checker = load_script("cannonlab_preservation", "cannon-preservation-check.py")
    comparator = load_script("cannonlab_module_compare", "compare-cannon-modules.py")
    contract_tool = load_script("cannonlab_module_contract", "compare-module-traces.py")

    reference_payload = read_json(reference_summary)
    reference_contract = test_contract(reference_payload)
    missing_reference_contract = missing_test_contract_fields(reference_contract)
    if missing_reference_contract:
        raise ValueError(
            "reference run summary lacks required test-contract evidence: "
            + ", ".join(missing_reference_contract)
        )
    baseline = summarize_performance([reference_summary])
    reference_trace = shot_trace(reference_summary)
    discovered_summaries = discover_summaries(candidate_roots)
    summaries = unique_summary_paths(discovered_summaries)
    regex = re.compile(include_pattern, re.IGNORECASE) if include_pattern else None
    grouped: dict[str, list[Path]] = defaultdict(list)
    skipped: list[dict[str, Any]] = []
    for path in summaries:
        payload = read_json(path)
        cannon_file = str(payload.get("cannon_file") or "")
        if not cannon_file:
            skipped.append({
                "summary": str(path),
                "reason": "missing_cannon_file",
            })
            continue
        if regex and not regex.search(cannon_file) and not regex.search(str(payload.get("scenario") or "")):
            continue
        differences = contract_differences(reference_contract, test_contract(payload))
        if differences:
            skipped.append({
                "summary": str(path),
                "cannon_file": cannon_file,
                "reason": "test_contract_mismatch",
                "differences": differences,
            })
            continue
        grouped[cannon_file].append(path)

    discovery_finished = time.perf_counter()
    metric_candidates: list[dict[str, Any]] = []
    for cannon_file, paths in sorted(grouped.items()):
        schematic = resolve_schematic(cannon_file, cannon_directories)
        if schematic is None:
            skipped.append({
                "cannon_file": cannon_file,
                "run_count": len(paths),
                "reason": "schematic_not_resolved_uniquely",
            })
            continue
        if schematic.resolve() == reference_schematic.resolve():
            continue

        performance = summarize_performance(paths)
        metric_score, metric_components = metric_screening_score(
            performance,
            baseline,
        )
        metric_candidates.append({
            "cannon_file": cannon_file,
            "schematic": schematic,
            "summary_paths": paths,
            "performance": performance,
            "metric_screening_score": metric_score,
            "metric_screening_components": metric_components,
            "passes_metric_screen": passes_metric_screen(
                performance,
                baseline,
                minimum_dispenser_survival=minimum_dispenser_survival,
                minimum_self_damage_reduction=minimum_self_damage_reduction,
                minimum_target_retention=minimum_target_retention,
            ),
        })

    metric_candidates.sort(key=lambda row: (
        not bool(row["passes_metric_screen"]),
        -float(row["metric_screening_score"]),
        str(row["cannon_file"]),
    ))
    metric_screening_finished = time.perf_counter()
    geometry_candidate_count = (
        len(metric_candidates)
        if max_geometry_candidates == 0
        else min(max_geometry_candidates, len(metric_candidates))
    )

    prepared: list[dict[str, Any]] = []
    for metric_rank, metric_candidate in enumerate(metric_candidates, start=1):
        selected_for_geometry = metric_rank <= geometry_candidate_count
        performance = metric_candidate["performance"]
        schematic = metric_candidate["schematic"]
        if selected_for_geometry:
            preservation = permissive_preservation(
                checker,
                reference_schematic,
                schematic,
                chunk_limit,
            )
            comparison = comparator.build_report(
                reference_schematic,
                schematic,
                chunk_limit=chunk_limit,
            )
            structural_ratio = float(
                (preservation.get("summary") or {}).get("structural_change_ratio")
                or 0.0
            )
            screen_score, screen_components = screening_score(
                performance,
                baseline,
                structural_ratio,
                comparison,
            )
            passes_runtime = passes_runtime_screen(
                performance,
                baseline,
                structural_ratio,
                minimum_dispenser_survival=minimum_dispenser_survival,
                minimum_self_damage_reduction=minimum_self_damage_reduction,
                minimum_target_retention=minimum_target_retention,
                maximum_structural_change_ratio=maximum_structural_change_ratio,
            )
        else:
            preservation = {}
            comparison = {}
            structural_ratio = 1.0
            screen_score = None
            screen_components = {}
            passes_runtime = False
        prepared.append({
            **metric_candidate,
            "metric_rank": metric_rank,
            "selected_for_geometry": selected_for_geometry,
            "preservation": preservation,
            "comparison": comparison,
            "structural_ratio": structural_ratio,
            "screening_score": screen_score,
            "screening_components": screen_components,
            "passes_runtime_screen": passes_runtime,
        })

    static_screening_finished = time.perf_counter()
    runtime_order = sorted(
        [row for row in prepared if row["selected_for_geometry"]],
        key=lambda row: (
        not bool(row["passes_runtime_screen"]),
        -float(row["screening_score"] or 0.0),
        float(row["structural_ratio"]),
        str(row["cannon_file"]),
        ),
    )
    runtime_rank = {
        str(row["cannon_file"]): index
        for index, row in enumerate(runtime_order, start=1)
    }
    runtime_candidate_count = (
        len(runtime_order)
        if max_runtime_candidates == 0
        else min(max_runtime_candidates, len(runtime_order))
    )

    candidates: list[dict[str, Any]] = []
    runtime_replay_started = time.perf_counter()
    for prepared_candidate in prepared:
        cannon_file = str(prepared_candidate["cannon_file"])
        schematic = prepared_candidate["schematic"]
        paths = prepared_candidate["summary_paths"]
        performance = prepared_candidate["performance"]
        preservation = prepared_candidate["preservation"]
        comparison = prepared_candidate["comparison"]
        structural_ratio = float(prepared_candidate["structural_ratio"])
        screening_rank = runtime_rank.get(cannon_file)
        selected_for_runtime = (
            screening_rank is not None
            and screening_rank <= runtime_candidate_count
        )
        runtime = runtime_contracts(
            contract_tool,
            comparison,
            reference_schematic,
            reference_trace,
            schematic,
            paths,
            chunk_limit=chunk_limit,
            max_runs=max_runtime_contract_runs,
        ) if selected_for_runtime else []
        runtime_drift = aggregate_runtime_drift(runtime)
        score, score_components = repair_score(
            performance,
            baseline,
            structural_ratio,
            runtime,
        )
        promotion = promotion_verdict(
            performance,
            baseline,
            runtime,
            structural_ratio,
            has_geometry_evidence=bool(prepared_candidate["selected_for_geometry"]),
            minimum_dispenser_survival=minimum_dispenser_survival,
            minimum_self_damage_reduction=minimum_self_damage_reduction,
            minimum_target_retention=minimum_target_retention,
            maximum_structural_change_ratio=maximum_structural_change_ratio,
        )
        contract_reports = [row for row in runtime if row.get("status") in {"PASS", "FAIL"}]
        failed_protected = sum(
            int((row.get("summary") or {}).get("failed_runtime_contracts") or 0)
            for row in contract_reports
        )
        protected = sum(
            int((row.get("summary") or {}).get("protected_runtime_contracts") or 0)
            for row in contract_reports
        )
        runtime_pass_rate = sum(row.get("status") == "PASS" for row in contract_reports) / max(1, len(contract_reports))
        self_reduction = (
            float(baseline.get("mean_self_damage") or 0.0)
            - float(performance.get("mean_self_damage") or 0.0)
        ) / max(1.0, float(baseline.get("mean_self_damage") or 0.0))
        target_retention = (
            float(performance.get("mean_target_destroyed") or 0.0)
            / max(1.0, float(baseline.get("mean_target_destroyed") or 0.0))
        )
        candidate = {
            "cannon_file": cannon_file,
            "schematic": str(schematic),
            "repair_score": score,
            "promotion": promotion,
            "geometry_screening": {
                "rank": prepared_candidate["metric_rank"],
                "selected_for_geometry": prepared_candidate[
                    "selected_for_geometry"
                ],
                "metric_screening_score": prepared_candidate[
                    "metric_screening_score"
                ],
                "metric_screening_components": prepared_candidate[
                    "metric_screening_components"
                ],
                "passes_metric_promotion_thresholds": prepared_candidate[
                    "passes_metric_screen"
                ],
                "selection_reason": (
                    "selected_by_geometry_candidate_budget"
                    if prepared_candidate["selected_for_geometry"]
                    else "not_selected_by_geometry_candidate_budget"
                ),
            },
            "runtime_screening": {
                "rank": screening_rank,
                "selected_for_runtime": selected_for_runtime,
                "screening_score": prepared_candidate["screening_score"],
                "screening_components": prepared_candidate["screening_components"],
                "passes_non_runtime_promotion_thresholds": prepared_candidate[
                    "passes_runtime_screen"
                ],
                "selection_reason": (
                    "selected_by_runtime_candidate_budget"
                    if selected_for_runtime
                    else (
                        "not_geometry_screened"
                        if not prepared_candidate["selected_for_geometry"]
                        else "not_selected_by_runtime_candidate_budget"
                    )
                ),
            },
            "score_components": score_components,
            "performance": performance,
            "geometry": {
                "evidence_available": bool(
                    prepared_candidate["selected_for_geometry"]
                ),
                "structural_changes": (preservation.get("summary") or {}).get("structural_changes"),
                "structural_change_ratio": structural_ratio,
                "functional_changes": (preservation.get("summary") or {}).get("functional_changes"),
                "functional_change_ratio": (preservation.get("summary") or {}).get("functional_change_ratio"),
                "modules_touched": (preservation.get("summary") or {}).get("modules_touched"),
                "block_entity_topology_changed": (preservation.get("summary") or {}).get("block_entity_topology_changed"),
                "changed_type_counts": preservation.get("changed_type_counts") or {},
                "impacted_modules": preservation.get("impacted_modules") or [],
            },
            "module_comparison": {
                "evidence_available": bool(
                    prepared_candidate["selected_for_geometry"]
                ),
                "summary": comparison.get("summary") or {},
                "translation_alignment": comparison.get("translation_alignment") or {},
                "unmatched_reference_modules": comparison.get("unmatched_first_modules") or [],
                "unmatched_candidate_modules": comparison.get("unmatched_second_modules") or [],
            },
            "runtime_contracts": runtime,
            "runtime_drift_summary": runtime_drift,
            "pareto_eligible": bool(contract_reports),
            "decision_metrics": {
                "mean_dispenser_survival": float(performance.get("mean_dispenser_survival") or 0.0),
                "self_damage_reduction": self_reduction,
                "target_retention": target_retention,
                "runtime_contract_pass_rate": runtime_pass_rate,
                "structural_change_ratio": structural_ratio,
                "failed_protected_modules": failed_protected,
                "protected_modules_checked": protected,
            },
        }
        candidates.append(candidate)

    runtime_replay_finished = time.perf_counter()

    pareto_candidates = [
        candidate
        for candidate in candidates
        if candidate["pareto_eligible"]
    ]
    for candidate in candidates:
        candidate["pareto_front"] = bool(candidate["pareto_eligible"]) and not any(
            other is not candidate and dominates(other, candidate)
            for other in pareto_candidates
        )
    candidates.sort(key=lambda row: (
        not bool((row.get("promotion") or {}).get("promotion_ready")),
        not bool(row["pareto_front"]),
        -float(row["repair_score"]),
        str(row["cannon_file"]),
    ))

    failures = [] if candidates else ["no_candidate_repairs_resolved"]
    return {
        "status": "PASS" if not failures else "FAIL",
        "schema": "cannonlab-repair-family-v3",
        "reference": {
            "schematic": str(reference_schematic),
            "run_summary": str(reference_summary),
            "cannon_file": reference_payload.get("cannon_file"),
            "scenario": reference_payload.get("scenario"),
            "test_contract": reference_contract,
            "trace": str(reference_trace) if reference_trace else None,
            "performance": baseline,
        },
        "configuration": {
            "chunk_limit": chunk_limit,
            "candidate_roots": [str(path) for path in candidate_roots],
            "discovered_summary_count": len(discovered_summaries),
            "unique_run_count": len(summaries),
            "cannon_directories": [str(path) for path in cannon_directories],
            "include_pattern": include_pattern,
            "max_runtime_contract_runs": max_runtime_contract_runs,
            "max_geometry_candidates": max_geometry_candidates,
            "geometry_candidates_selected": geometry_candidate_count,
            "geometry_candidates_not_selected": max(
                0,
                len(metric_candidates) - geometry_candidate_count,
            ),
            "max_runtime_candidates": max_runtime_candidates,
            "runtime_candidates_selected": runtime_candidate_count,
            "runtime_candidates_not_selected": max(
                0,
                len(prepared) - runtime_candidate_count,
            ),
            "phase_timings_seconds": {
                "discovery_and_contract_filtering": round(
                    discovery_finished - total_started,
                    6,
                ),
                "metric_screening": round(
                    metric_screening_finished - discovery_finished,
                    6,
                ),
                "static_geometry_screening": round(
                    static_screening_finished - metric_screening_finished,
                    6,
                ),
                "causal_runtime_replay": round(
                    runtime_replay_finished - runtime_replay_started,
                    6,
                ),
                "total": round(runtime_replay_finished - total_started, 6),
            },
            "promotion_thresholds": {
                "minimum_dispenser_survival": minimum_dispenser_survival,
                "minimum_self_damage_reduction": minimum_self_damage_reduction,
                "minimum_target_retention": minimum_target_retention,
                "maximum_structural_change_ratio": maximum_structural_change_ratio,
            },
            "score_weights": {
                "reliability": 0.20,
                "dispenser_survival": 0.25,
                "self_damage_reduction": 0.20,
                "target_retention": 0.15,
                "collateral_preservation": 0.10,
                "repeatability": 0.07,
                "structural_preservation": 0.03,
            },
            "screening_score_weights": {
                "reliability": 0.25,
                "dispenser_survival": 0.25,
                "self_damage_reduction": 0.20,
                "target_retention": 0.15,
                "repeatability": 0.08,
                "structural_preservation": 0.04,
                "exact_module_coverage": 0.03,
            },
            "metric_screening_score_weights": {
                "reliability": 0.30,
                "dispenser_survival": 0.30,
                "self_damage_reduction": 0.20,
                "target_retention": 0.15,
                "repeatability": 0.05,
            },
        },
        "candidate_count": len(candidates),
        "pareto_front_count": sum(bool(row["pareto_front"]) for row in candidates),
        "failures": failures,
        "candidates": candidates,
        "skipped": skipped,
        "truth_boundary": (
            "The ranking compares local run summaries, exact decoded geometry, and local causal traces. "
            "Candidates outside the geometry or runtime replay budgets remain visible but cannot be promoted. "
            "The balanced score is transparent but value-dependent; Pareto-front labels avoid pretending one "
            "weighting is universal. Local Paper or Sakura evidence does not prove private ExtremeCraft parity."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank bounded cannon repair variants against one exact reference and its runtime trace"
    )
    parser.add_argument("reference_schematic", type=Path)
    parser.add_argument("reference_summary", type=Path)
    parser.add_argument("candidate_roots", nargs="+", type=Path)
    parser.add_argument("--cannon-directory", action="append", type=Path, required=True)
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--include-pattern", default="")
    parser.add_argument("--max-runtime-contract-runs", type=int, default=3)
    parser.add_argument(
        "--max-geometry-candidates",
        type=int,
        default=0,
        help="0 analyzes exact geometry for every candidate; positive values analyze only the strongest metric-screened candidates",
    )
    parser.add_argument(
        "--max-runtime-candidates",
        type=int,
        default=0,
        help="0 replays every candidate; positive values replay only the strongest screened candidates",
    )
    parser.add_argument("--minimum-dispenser-survival", type=float, default=0.95)
    parser.add_argument("--minimum-self-damage-reduction", type=float, default=0.10)
    parser.add_argument("--minimum-target-retention", type=float, default=0.80)
    parser.add_argument("--maximum-structural-change-ratio", type=float, default=0.03)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_report(
        args.reference_schematic,
        args.reference_summary,
        args.candidate_roots,
        args.cannon_directory,
        chunk_limit=args.chunk_limit,
        include_pattern=args.include_pattern,
        max_runtime_contract_runs=args.max_runtime_contract_runs,
        max_geometry_candidates=args.max_geometry_candidates,
        max_runtime_candidates=args.max_runtime_candidates,
        minimum_dispenser_survival=args.minimum_dispenser_survival,
        minimum_self_damage_reduction=args.minimum_self_damage_reduction,
        minimum_target_retention=args.minimum_target_retention,
        maximum_structural_change_ratio=args.maximum_structural_change_ratio,
    )
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
