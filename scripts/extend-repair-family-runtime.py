#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


def load_script(name: str, filename: str) -> Any:
    script = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def completed_runtime_reports(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in candidate.get("runtime_contracts") or []
        if row.get("status") in {"PASS", "FAIL"}
    ]


def geometry_comparison_stub(candidate: dict[str, Any]) -> dict[str, Any]:
    comparison = candidate.get("module_comparison") or {}
    return {
        "unmatched_first_modules": comparison.get("unmatched_reference_modules") or [],
        "unmatched_second_modules": comparison.get("unmatched_candidate_modules") or [],
    }


def summary_paths(candidate: dict[str, Any]) -> list[Path]:
    paths = {
        Path(str(row["summary"])).resolve()
        for row in (candidate.get("performance") or {}).get("runs") or []
        if row.get("summary")
    }
    return sorted(paths)


def extension_result(
    family: Any,
    candidate: dict[str, Any],
    runtime: list[dict[str, Any]],
    baseline: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    performance = candidate.get("performance") or {}
    structural_ratio = float(
        (candidate.get("geometry") or {}).get("structural_change_ratio") or 0.0
    )
    score, score_components = family.repair_score(
        performance,
        baseline,
        structural_ratio,
        runtime,
    )
    promotion = family.promotion_verdict(
        performance,
        baseline,
        runtime,
        structural_ratio,
        has_geometry_evidence=bool(
            (candidate.get("geometry") or {}).get("evidence_available")
        ),
        minimum_dispenser_survival=float(
            thresholds.get("minimum_dispenser_survival", 0.95)
        ),
        minimum_self_damage_reduction=float(
            thresholds.get("minimum_self_damage_reduction", 0.10)
        ),
        minimum_target_retention=float(
            thresholds.get("minimum_target_retention", 0.80)
        ),
        maximum_structural_change_ratio=float(
            thresholds.get("maximum_structural_change_ratio", 0.03)
        ),
    )
    return {
        "cannon_file": candidate.get("cannon_file"),
        "schematic": candidate.get("schematic"),
        "runtime_rank": (candidate.get("runtime_screening") or {}).get("rank"),
        "repair_score": score,
        "score_components": score_components,
        "promotion": promotion,
        "runtime_contracts": runtime,
        "runtime_drift_summary": family.aggregate_runtime_drift(runtime),
        "performance": performance,
        "geometry": candidate.get("geometry") or {},
        "module_comparison": candidate.get("module_comparison") or {},
    }


def build_report(
    source_report: Path,
    *,
    runtime_rank_from: int = 1,
    runtime_count: int = 4,
    max_runtime_contract_runs: int = 1,
    include_existing: bool = False,
    contract_tool: Any | None = None,
) -> dict[str, Any]:
    if runtime_rank_from <= 0:
        raise ValueError("runtime_rank_from must be positive")
    if runtime_count <= 0:
        raise ValueError("runtime_count must be positive")
    if max_runtime_contract_runs <= 0:
        raise ValueError("max_runtime_contract_runs must be positive")

    family = load_script("cannonlab_repair_family_extension", "analyze-repair-family.py")
    payload = family.read_json(source_report)
    reference = payload.get("reference") or {}
    reference_schematic = Path(str(reference.get("schematic") or ""))
    reference_trace_raw = reference.get("trace")
    if not reference_schematic.is_file():
        raise FileNotFoundError(reference_schematic)
    if not reference_trace_raw:
        raise ValueError("source report lacks a reference trace")
    reference_trace = Path(str(reference_trace_raw))
    if not reference_trace.is_file():
        raise FileNotFoundError(reference_trace)

    eligible = []
    skipped = []
    rank_to = runtime_rank_from + runtime_count - 1
    for candidate in payload.get("candidates") or []:
        runtime_screening = candidate.get("runtime_screening") or {}
        rank = runtime_screening.get("rank")
        if not isinstance(rank, int) or not runtime_rank_from <= rank <= rank_to:
            continue
        if not bool((candidate.get("geometry") or {}).get("evidence_available")):
            skipped.append({
                "cannon_file": candidate.get("cannon_file"),
                "runtime_rank": rank,
                "reason": "geometry_evidence_unavailable",
            })
            continue
        if completed_runtime_reports(candidate) and not include_existing:
            skipped.append({
                "cannon_file": candidate.get("cannon_file"),
                "runtime_rank": rank,
                "reason": "runtime_evidence_already_present",
            })
            continue
        summaries = summary_paths(candidate)
        if not summaries:
            skipped.append({
                "cannon_file": candidate.get("cannon_file"),
                "runtime_rank": rank,
                "reason": "candidate_run_summaries_unavailable",
            })
            continue
        schematic = Path(str(candidate.get("schematic") or ""))
        if not schematic.is_file():
            skipped.append({
                "cannon_file": candidate.get("cannon_file"),
                "runtime_rank": rank,
                "reason": "candidate_schematic_unavailable",
            })
            continue
        eligible.append((rank, candidate, schematic, summaries))

    eligible.sort(key=lambda row: (row[0], str(row[1].get("cannon_file"))))
    tool = contract_tool or family.load_script(
        "cannonlab_repair_family_extension_contract",
        "compare-module-traces.py",
    )
    chunk_limit = int((payload.get("configuration") or {}).get("chunk_limit") or 160)
    thresholds = (payload.get("configuration") or {}).get("promotion_thresholds") or {}
    baseline = reference.get("performance") or {}
    results = []
    for rank, candidate, schematic, summaries in eligible:
        runtime = family.runtime_contracts(
            tool,
            geometry_comparison_stub(candidate),
            reference_schematic,
            reference_trace,
            schematic,
            summaries,
            chunk_limit=chunk_limit,
            max_runs=max_runtime_contract_runs,
        )
        result = extension_result(
            family,
            candidate,
            runtime,
            baseline,
            thresholds,
        )
        result["runtime_rank"] = rank
        results.append(result)

    failures = [] if results else ["no_runtime_candidates_extended"]
    return {
        "status": "PASS" if not failures else "FAIL",
        "schema": "cannonlab-repair-runtime-extension-v1",
        "source_report": str(source_report),
        "source_schema": payload.get("schema"),
        "configuration": {
            "runtime_rank_from": runtime_rank_from,
            "runtime_rank_to": rank_to,
            "runtime_count": runtime_count,
            "max_runtime_contract_runs": max_runtime_contract_runs,
            "include_existing": include_existing,
            "chunk_limit": chunk_limit,
        },
        "failures": failures,
        "extended_count": len(results),
        "results": results,
        "skipped": skipped,
        "truth_boundary": (
            "This extension reuses a prior tournament's metric and geometry evidence and adds local causal replay. "
            "It does not prove private ExtremeCraft parity or live EC readiness."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extend a repair-family tournament with additional causal runtime ranks without rerunning geometry"
    )
    parser.add_argument("source_report", type=Path)
    parser.add_argument("--runtime-rank-from", type=int, default=1)
    parser.add_argument("--runtime-count", type=int, default=4)
    parser.add_argument("--max-runtime-contract-runs", type=int, default=1)
    parser.add_argument("--include-existing", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_report(
        args.source_report,
        runtime_rank_from=args.runtime_rank_from,
        runtime_count=args.runtime_count,
        max_runtime_contract_runs=args.max_runtime_contract_runs,
        include_existing=args.include_existing,
    )
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
