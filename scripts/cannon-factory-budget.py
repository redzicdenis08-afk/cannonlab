#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT.parents[1] / "output"
TIERS = ("smoke", "qualify", "full")


def allowed(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not (path.is_relative_to(ROOT) or path.is_relative_to(OUTPUT_ROOT)):
        raise ValueError(f"path escapes CannonLab roots: {raw}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def execution_tiers(forge: dict[str, Any]) -> dict[str, dict[str, int]]:
    rows = (forge.get("execution_plan") or {}).get("tiers")
    if not isinstance(rows, list):
        raise ValueError("forge manifest has no execution_plan tiers")
    output, previous_shots, previous_scenarios = {}, 0, 0
    for row in rows:
        tier = str(row.get("id", "")) if isinstance(row, dict) else ""
        if tier not in TIERS:
            continue
        shots = int(row.get("cumulative_shots", 0))
        scenarios = int(row.get("cumulative_scenarios", 0))
        output[tier] = {
            "incremental_shots": shots - previous_shots,
            "incremental_scenarios": scenarios - previous_scenarios,
        }
        previous_shots, previous_scenarios = shots, scenarios
    if set(output) != set(TIERS):
        raise ValueError("execution plan must contain smoke, qualify and full")
    return output


def history_costs(paths: list[Path]) -> dict[str, float]:
    values: dict[str, list[float]] = {tier: [] for tier in TIERS}
    for path in paths:
        row = load(path)
        tier = str(row.get("max_tier", ""))
        if tier not in values or str(row.get("status", "")).upper() != "PASS":
            continue
        if int(row.get("executed_count", 0)) != int(row.get("selected_scenarios", -1)):
            continue
        if int(row.get("skipped_count", 0)) != 0:
            continue
        elapsed = float(row.get("elapsed_seconds", 0))
        if elapsed > 0:
            values[tier].append(elapsed)
    medians = {tier: statistics.median(rows) for tier, rows in values.items() if rows}
    output, previous = {}, 0.0
    for tier in TIERS:
        if tier in medians:
            output[tier] = max(1.0, medians[tier] - previous)
            previous = medians[tier]
    return output


def costs(tiers: dict[str, dict[str, int]], shot: float, overhead: float, history: dict[str, float]) -> dict[str, float]:
    return {
        tier: round(history.get(tier, tiers[tier]["incremental_shots"] * shot + tiers[tier]["incremental_scenarios"] * overhead), 3)
        for tier in TIERS
    }


def stage_seconds(count: int, workers: int, cost: float) -> float:
    return math.ceil(count / workers) * cost if count else 0.0


def choose(
    eligible: int,
    budget: float,
    workers: int,
    caps: dict[str, int],
    cost: dict[str, float],
    target: str,
) -> tuple[dict[str, int] | None, float | None]:
    best = None
    for smoke in range(1, min(eligible, caps["smoke"]) + 1):
        for qualify in range(0 if target == "smoke" else 1, min(smoke, caps["qualify"]) + 1):
            for full in range(1 if target == "full" else 0, min(qualify, caps["full"]) + 1):
                if target == "smoke" and (qualify or full) or target == "qualify" and full:
                    continue
                wall = sum(stage_seconds({"smoke": smoke, "qualify": qualify, "full": full}[tier], workers, cost[tier]) for tier in TIERS)
                if wall <= budget:
                    item = ((full, qualify, smoke, -wall), {"smoke": smoke, "qualify": qualify, "full": full}, wall)
                    if best is None or item[0] > best[0]:
                        best = item
    return (None, None) if best is None else (best[1], best[2])


def candidate_path(row: dict[str, Any]) -> str | None:
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    output = result.get("output") if isinstance(result.get("output"), dict) else {}
    return str(output.get("path")) if output.get("path") else None


def build(search_path: Path, forge_path: Path, *, budget: float, workers: int, target: str, caps: dict[str, int], shot: float, overhead: float, history: list[Path]):
    if budget <= 0 or workers < 1:
        raise ValueError("budget and workers must be positive")
    if target not in TIERS:
        raise ValueError(f"unsupported target tier: {target}")
    if any(value < 0 for value in caps.values()):
        raise ValueError("candidate caps cannot be negative")
    if shot <= 0 or overhead < 0:
        raise ValueError("seconds per shot must be positive and scenario overhead cannot be negative")
    search, forge = load(search_path), load(forge_path)
    if search.get("schema") != "cannonlab-variant-search-manifest-v1" or forge.get("schema") != "cannonlab-forge-job-v1":
        raise ValueError("unsupported input manifest")
    candidates = [row for row in search.get("candidates", []) if isinstance(row, dict) and row.get("static_score") is not None]
    candidates.sort(key=lambda row: (-float(row["static_score"]), str(row.get("variant_id", ""))))
    model = costs(execution_tiers(forge), shot, overhead, history_costs(history))
    counts, estimated = choose(len(candidates), budget, workers, caps, model, target)
    blockers = []
    if not candidates:
        blockers.append({"code": "no-static-candidate-passed"})
    if counts is None:
        blockers.append({"code": "runtime-budget-insufficient", "message": f"cannot reach {target} within {budget}s"})
        counts, estimated = {tier: 0 for tier in TIERS}, 0.0
    stages = []
    for tier in TIERS:
        selected = candidates[: counts[tier]]
        stages.append({
            "tier": tier,
            "candidate_count": counts[tier],
            "estimated_stage_wall_seconds": stage_seconds(counts[tier], workers, model[tier]),
            "selection_rule": "top static candidates" if tier == "smoke" else "top runtime survivors; static order only breaks ties",
            "candidates": [{"variant_id": row.get("variant_id"), "static_score": row.get("static_score"), "candidate_path": candidate_path(row)} for row in selected],
        })
    payload = {
        "schema": "cannonlab-factory-budget-plan-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not blockers else "BLOCKED",
        "truth_boundary": "This allocates local runtime time only. Later tiers re-rank real survivors; EC proof remains separate.",
        "budget_seconds": budget, "runtime_workers": workers, "target_tier": target,
        "eligible_static_candidates": len(candidates), "caps": caps,
        "incremental_seconds_per_candidate": model, "selected_counts": counts,
        "estimated_wall_seconds": round(float(estimated), 3),
        "budget_utilization": round(float(estimated) / budget, 6),
        "stages": stages, "blockers": blockers,
    }
    output = search_path.parent / "factory-budget-plan.json"
    payload["plan_path"] = str(output)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Allocate CannonLab candidate tiers under a wall-clock budget")
    parser.add_argument("search_manifest"); parser.add_argument("forge_manifest")
    parser.add_argument("--budget-seconds", type=float, required=True); parser.add_argument("--runtime-workers", type=int, default=1)
    parser.add_argument("--target-tier", choices=TIERS, default="full")
    parser.add_argument("--max-smoke", type=int, default=16); parser.add_argument("--max-qualify", type=int, default=4); parser.add_argument("--max-full", type=int, default=1)
    parser.add_argument("--seconds-per-shot", type=float, default=25.0); parser.add_argument("--scenario-overhead-seconds", type=float, default=30.0)
    parser.add_argument("--historical-summary", action="append", default=[])
    args = parser.parse_args()
    if args.budget_seconds <= 0 or args.runtime_workers < 1:
        parser.error("budget and workers must be positive")
    caps = {"smoke": args.max_smoke, "qualify": args.max_qualify, "full": args.max_full}
    result = build(allowed(args.search_manifest), allowed(args.forge_manifest), budget=args.budget_seconds, workers=args.runtime_workers, target=args.target_tier, caps=caps, shot=args.seconds_per_shot, overhead=args.scenario_overhead_seconds, history=[allowed(path) for path in args.historical_summary])
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS": raise SystemExit(2)


if __name__ == "__main__": main()
