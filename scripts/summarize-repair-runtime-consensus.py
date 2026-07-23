#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def completed_runtime_reports(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in candidate.get("runtime_contracts") or []
        if row.get("status") in {"PASS", "FAIL"}
    ]


def candidate_runtime_rank(candidate: dict[str, Any]) -> int | None:
    extension_rank = candidate.get("runtime_rank")
    if isinstance(extension_rank, int):
        return extension_rank
    rank = (candidate.get("runtime_screening") or {}).get("rank")
    return int(rank) if isinstance(rank, int) else None


def candidate_record(candidate: dict[str, Any], *, source: str) -> dict[str, Any]:
    runtime = completed_runtime_reports(candidate)
    drift = candidate.get("runtime_drift_summary") or {}
    promotion = candidate.get("promotion") or {}
    performance = candidate.get("performance") or {}
    geometry = candidate.get("geometry") or {}
    return {
        "cannon_file": str(candidate.get("cannon_file") or ""),
        "runtime_rank": candidate_runtime_rank(candidate),
        "source": source,
        "runtime_reports": len(runtime),
        "runtime_passes": sum(row.get("status") == "PASS" for row in runtime),
        "runtime_failures": sum(row.get("status") == "FAIL" for row in runtime),
        "promotion_ready": bool(promotion.get("promotion_ready")),
        "verdict": promotion.get("verdict"),
        "blockers": promotion.get("blockers") or [],
        "repair_score": candidate.get("repair_score"),
        "mean_dispenser_survival": performance.get("mean_dispenser_survival"),
        "mean_self_damage": performance.get("mean_self_damage"),
        "mean_target_destroyed": performance.get("mean_target_destroyed"),
        "structural_change_ratio": geometry.get("structural_change_ratio"),
        "module_drift": drift.get("modules") or [],
        "shared_drift": drift.get("shared_component_cohorts") or [],
        "joint_drift": drift.get("joint_entity_cohorts") or [],
    }


def merge_candidates(
    tournament: dict[str, Any],
    extensions: Iterable[tuple[str, dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for candidate in tournament.get("candidates") or []:
        name = str(candidate.get("cannon_file") or "")
        if not name:
            continue
        record = candidate_record(candidate, source="tournament")
        if record["runtime_reports"]:
            merged[name] = record

    for source, payload in extensions:
        for candidate in payload.get("results") or []:
            name = str(candidate.get("cannon_file") or "")
            if not name:
                continue
            record = candidate_record(candidate, source=source)
            existing = merged.get(name)
            if existing is not None and existing != record:
                conflicts.append({
                    "cannon_file": name,
                    "existing_source": existing["source"],
                    "replacement_source": source,
                })
            merged[name] = record

    records = sorted(
        merged.values(),
        key=lambda row: (
            row["runtime_rank"] is None,
            row["runtime_rank"] if row["runtime_rank"] is not None else 10**9,
            row["cannon_file"],
        ),
    )
    return records, conflicts


def update_numeric_range(
    target: dict[str, list[float]],
    values: dict[str, Any],
) -> None:
    for field, summary in values.items():
        if not isinstance(summary, dict):
            continue
        value = summary.get("mean")
        if isinstance(value, (int, float)):
            target.setdefault(str(field), []).append(float(value))


def numeric_ranges(values: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    return {
        field: {
            "min": min(samples),
            "max": max(samples),
            "mean": sum(samples) / len(samples),
        }
        for field, samples in sorted(values.items())
        if samples
    }


def module_consensus(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        for drift in record["module_drift"]:
            module_id = str(drift.get("first_module_id") or "UNKNOWN")
            state = grouped.setdefault(module_id, {
                "candidates": set(),
                "failure_counts": Counter(),
                "timing": {},
                "physics": {},
            })
            state["candidates"].add(record["cannon_file"])
            state["failure_counts"].update(drift.get("failure_counts") or {})
            update_numeric_range(state["timing"], drift.get("timing_delta_ranges") or {})
            update_numeric_range(state["physics"], drift.get("physics_ranges") or {})

    total = len(records)
    output = []
    for module_id, state in grouped.items():
        candidates = sorted(state["candidates"])
        output.append({
            "module_id": module_id,
            "candidate_count": len(candidates),
            "candidate_share": len(candidates) / max(1, total),
            "universal_across_tested_candidates": len(candidates) == total and total > 0,
            "failure_counts": dict(sorted(state["failure_counts"].items())),
            "timing_delta_ranges": numeric_ranges(state["timing"]),
            "physics_ranges": numeric_ranges(state["physics"]),
            "candidates": candidates,
        })
    output.sort(key=lambda row: (-row["candidate_count"], row["module_id"]))
    return output


def cohort_key(row: dict[str, Any]) -> tuple[tuple[str, ...], str]:
    modules = tuple(sorted(str(value) for value in row.get("module_ids") or []))
    entity_type = str(row.get("entity_type") or "")
    return modules, entity_type


def cohort_consensus(
    records: list[dict[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
    for record in records:
        for drift in record[field]:
            key = cohort_key(drift)
            state = grouped.setdefault(key, {
                "candidates": set(),
                "failure_counts": Counter(),
            })
            state["candidates"].add(record["cannon_file"])
            state["failure_counts"].update(drift.get("failure_counts") or {})

    total = len(records)
    output = []
    for (modules, entity_type), state in grouped.items():
        candidates = sorted(state["candidates"])
        row = {
            "module_ids": list(modules),
            "candidate_count": len(candidates),
            "candidate_share": len(candidates) / max(1, total),
            "universal_across_tested_candidates": len(candidates) == total and total > 0,
            "failure_counts": dict(sorted(state["failure_counts"].items())),
            "candidates": candidates,
        }
        if entity_type:
            row["entity_type"] = entity_type
        output.append(row)
    output.sort(key=lambda row: (
        -row["candidate_count"],
        row["module_ids"],
        row.get("entity_type", ""),
    ))
    return output


def cleanest_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        total_drift = (
            len(record["module_drift"])
            + len(record["shared_drift"])
            + len(record["joint_drift"])
        )
        rows.append({
            "cannon_file": record["cannon_file"],
            "runtime_rank": record["runtime_rank"],
            "promotion_ready": record["promotion_ready"],
            "verdict": record["verdict"],
            "repair_score": record["repair_score"],
            "total_drift_groups": total_drift,
            "module_drift_groups": len(record["module_drift"]),
            "shared_drift_groups": len(record["shared_drift"]),
            "joint_drift_groups": len(record["joint_drift"]),
            "mean_dispenser_survival": record["mean_dispenser_survival"],
            "mean_self_damage": record["mean_self_damage"],
            "mean_target_destroyed": record["mean_target_destroyed"],
            "structural_change_ratio": record["structural_change_ratio"],
        })
    rows.sort(key=lambda row: (
        not row["promotion_ready"],
        row["total_drift_groups"],
        -(float(row["repair_score"]) if isinstance(row["repair_score"], (int, float)) else -1.0),
        row["runtime_rank"] if row["runtime_rank"] is not None else 10**9,
        row["cannon_file"],
    ))
    return rows


def build_report(
    tournament_path: Path,
    extension_paths: list[Path],
) -> dict[str, Any]:
    tournament = read_json(tournament_path)
    extensions = [(str(path), read_json(path)) for path in extension_paths]
    records, conflicts = merge_candidates(tournament, extensions)
    modules = module_consensus(records)
    shared = cohort_consensus(records, "shared_drift")
    joint = cohort_consensus(records, "joint_drift")
    promotion_ready = [row for row in records if row["promotion_ready"]]
    universal_modules = [row for row in modules if row["universal_across_tested_candidates"]]
    universal_shared = [row for row in shared if row["universal_across_tested_candidates"]]
    universal_joint = [row for row in joint if row["universal_across_tested_candidates"]]

    failures = [] if records else ["no_runtime_evidence_found"]
    return {
        "status": "PASS" if not failures else "FAIL",
        "schema": "cannonlab-repair-runtime-consensus-v1",
        "tournament": str(tournament_path),
        "extensions": [str(path) for path in extension_paths],
        "failures": failures,
        "summary": {
            "runtime_tested_candidates": len(records),
            "promotion_ready_candidates": len(promotion_ready),
            "candidates_with_runtime_failures": sum(
                bool(row["runtime_failures"])
                for row in records
            ),
            "module_drift_families": len(modules),
            "shared_drift_families": len(shared),
            "joint_drift_families": len(joint),
            "universal_module_drifts": len(universal_modules),
            "universal_shared_drifts": len(universal_shared),
            "universal_joint_drifts": len(universal_joint),
        },
        "promotion_ready": promotion_ready,
        "universal_module_drifts": universal_modules,
        "universal_shared_drifts": universal_shared,
        "universal_joint_drifts": universal_joint,
        "module_consensus": modules,
        "shared_component_consensus": shared,
        "joint_entity_consensus": joint,
        "cleanest_candidates": cleanest_candidates(records),
        "tested_candidates": records,
        "source_conflicts": conflicts,
        "truth_boundary": (
            "Consensus summarizes local runtime contracts already present in the tournament and extension reports. "
            "It does not prove private ExtremeCraft parity or live EC readiness."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge repair tournament runtime evidence and identify universal versus variant-specific drift"
    )
    parser.add_argument("tournament", type=Path)
    parser.add_argument("extensions", nargs="*", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_report(args.tournament, args.extensions)
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
