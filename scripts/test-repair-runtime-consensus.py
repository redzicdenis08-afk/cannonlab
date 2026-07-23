#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any


def load_subject() -> Any:
    script = Path(__file__).resolve().with_name("summarize-repair-runtime-consensus.py")
    spec = importlib.util.spec_from_file_location("cannonlab_consensus_test", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def module_drift(module_id: str, failure: str, value: float) -> dict[str, Any]:
    return {
        "first_module_id": module_id,
        "second_module_id": module_id,
        "reports_failed": 1,
        "reports_checked": 1,
        "occurrence_rate": 1.0,
        "consistent_failure_set": True,
        "consistent_across_all_reports": True,
        "failure_counts": {failure: 1},
        "timing_delta_ranges": {},
        "physics_ranges": {
            "explosion_position_delta": {
                "min": value,
                "max": value,
                "mean": value,
            },
        },
    }


def shared_drift(modules: list[str]) -> dict[str, Any]:
    return {
        "module_ids": modules,
        "reports_failed": 1,
        "reports_checked": 1,
        "occurrence_rate": 1.0,
        "consistent_across_all_reports": True,
        "failure_counts": {"shared_redstone_change_ticks_changed": 1},
    }


def candidate(
    name: str,
    rank: int,
    *,
    modules: list[dict[str, Any]],
    shared: list[dict[str, Any]],
    ready: bool = False,
) -> dict[str, Any]:
    return {
        "cannon_file": name,
        "runtime_rank": rank,
        "repair_score": 90.0 - rank,
        "promotion": {
            "promotion_ready": ready,
            "verdict": "PROMOTION_READY_BOUNDED_REPAIR" if ready else "PERFORMANCE_WIN_WITH_COLLATERAL_DRIFT",
            "blockers": [] if ready else ["protected_module_runtime_drift"],
        },
        "runtime_contracts": [{"status": "PASS" if ready else "FAIL"}],
        "runtime_drift_summary": {
            "modules": modules,
            "shared_component_cohorts": shared,
            "joint_entity_cohorts": [],
        },
        "performance": {
            "mean_dispenser_survival": 1.0,
            "mean_self_damage": 100.0 + rank,
            "mean_target_destroyed": 40.0,
        },
        "geometry": {
            "structural_change_ratio": 0.01,
        },
    }


def main() -> int:
    subject = load_subject()
    with tempfile.TemporaryDirectory(prefix="cannonlab-runtime-consensus-") as temporary:
        root = Path(temporary)
        tournament = root / "tournament.json"
        extension = root / "extension.json"
        tournament.write_text(
            json.dumps({
                "schema": "cannonlab-repair-family-v3",
                "candidates": [
                    candidate(
                        "a.schem",
                        1,
                        modules=[module_drift("MODULE-007", "impact", 1.8)],
                        shared=[shared_drift(["MODULE-001", "MODULE-011"])],
                    ),
                    {
                        "cannon_file": "untested.schem",
                        "runtime_screening": {"rank": 2},
                        "runtime_contracts": [],
                        "runtime_drift_summary": {},
                        "promotion": {"promotion_ready": False},
                        "performance": {},
                        "geometry": {},
                    },
                ],
            }),
            encoding="utf-8",
        )
        extension.write_text(
            json.dumps({
                "schema": "cannonlab-repair-runtime-extension-v1",
                "results": [
                    candidate(
                        "b.schem",
                        2,
                        modules=[
                            module_drift("MODULE-007", "impact", 1.9),
                            module_drift("MODULE-018", "timing", 0.0),
                        ],
                        shared=[shared_drift(["MODULE-001", "MODULE-011"])],
                    ),
                    candidate(
                        "c.schem",
                        3,
                        modules=[module_drift("MODULE-007", "impact", 1.9)],
                        shared=[],
                    ),
                ],
            }),
            encoding="utf-8",
        )

        report = subject.build_report(tournament, [extension])
        assert report["status"] == "PASS", report
        assert report["summary"]["runtime_tested_candidates"] == 3, report
        assert report["summary"]["promotion_ready_candidates"] == 0, report
        assert report["summary"]["universal_module_drifts"] == 1, report
        universal = report["universal_module_drifts"][0]
        assert universal["module_id"] == "MODULE-007", universal
        assert universal["candidate_count"] == 3, universal
        assert universal["physics_ranges"]["explosion_position_delta"]["min"] == 1.8
        assert universal["physics_ranges"]["explosion_position_delta"]["max"] == 1.9
        module_18 = next(
            row for row in report["module_consensus"]
            if row["module_id"] == "MODULE-018"
        )
        assert module_18["candidate_count"] == 1, module_18
        assert report["summary"]["universal_shared_drifts"] == 0, report
        assert report["shared_component_consensus"][0]["candidate_count"] == 2
        assert [row["cannon_file"] for row in report["cleanest_candidates"]] == [
            "c.schem",
            "a.schem",
            "b.schem",
        ]

        empty = root / "empty.json"
        empty.write_text(json.dumps({"candidates": []}), encoding="utf-8")
        empty_report = subject.build_report(empty, [])
        assert empty_report["status"] == "FAIL", empty_report
        assert "no_runtime_evidence_found" in empty_report["failures"], empty_report

    print(
        "Repair runtime consensus identifies universal and variant-specific drift while excluding untested candidates."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
