#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def load_subject() -> Any:
    script = Path(__file__).resolve().with_name("extend-repair-family-runtime.py")
    spec = importlib.util.spec_from_file_location("cannonlab_runtime_extension_test", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def performance(*, self_damage: float, target: float, survival: float) -> dict[str, Any]:
    return {
        "run_count": 1,
        "shot_count": 1,
        "shots_requested": 1,
        "completion_rate": 1.0,
        "error_rate": 0.0,
        "contract_pass_rate": 1.0,
        "mean_dispenser_survival": survival,
        "minimum_dispenser_survival": survival,
        "mean_self_damage": self_damage,
        "maximum_self_damage": self_damage,
        "self_damage_stability": 1.0,
        "mean_target_destroyed": target,
        "minimum_target_destroyed": target,
        "target_damage_stability": 1.0,
        "mean_target_ratio": target / 100.0,
        "mean_explosions": 100.0,
        "explosion_stability": 1.0,
        "mean_spawns": 100.0,
        "spawn_stability": 1.0,
        "mean_forward_distance": 64.0,
        "mean_missing_blocks": 0.0,
        "mean_replaced_type_blocks": 0.0,
        "runs": [],
    }


def main() -> int:
    subject = load_subject()
    with tempfile.TemporaryDirectory(prefix="cannonlab-runtime-extension-") as temporary:
        root = Path(temporary)
        reference_schematic = root / "reference.schem"
        candidate_schematic = root / "candidate.schem"
        skipped_schematic = root / "skipped.schem"
        for path in (reference_schematic, candidate_schematic, skipped_schematic):
            path.write_bytes(path.name.encode("utf-8"))

        reference_trace = root / "reference-trace.csv"
        reference_trace.write_text(
            "tick,sequence,event,component_id,entity_uuid,entity_type\n",
            encoding="utf-8",
        )
        candidate_run = root / "candidate-run"
        candidate_trace = candidate_run / "shot-001" / "causal-events.csv"
        candidate_trace.parent.mkdir(parents=True)
        candidate_trace.write_text(
            "tick,sequence,event,component_id,entity_uuid,entity_type\n",
            encoding="utf-8",
        )
        candidate_summary = candidate_run / "run-summary.json"
        candidate_summary.write_text(
            json.dumps({
                "run_id": "candidate-run",
                "shots": [{"shot": 1}],
            }),
            encoding="utf-8",
        )

        baseline = performance(self_damage=100.0, target=100.0, survival=0.95)
        candidate_performance = performance(
            self_damage=40.0,
            target=95.0,
            survival=0.99,
        )
        candidate_performance["runs"] = [{
            "summary": str(candidate_summary),
            "trace": str(candidate_trace),
        }]
        source_report = root / "family.json"
        source_report.write_text(
            json.dumps({
                "status": "PASS",
                "schema": "cannonlab-repair-family-v3",
                "reference": {
                    "schematic": str(reference_schematic),
                    "trace": str(reference_trace),
                    "performance": baseline,
                },
                "configuration": {
                    "chunk_limit": 160,
                    "promotion_thresholds": {
                        "minimum_dispenser_survival": 0.95,
                        "minimum_self_damage_reduction": 0.10,
                        "minimum_target_retention": 0.80,
                        "maximum_structural_change_ratio": 0.03,
                    },
                },
                "candidates": [
                    {
                        "cannon_file": "already-tested.schem",
                        "schematic": str(skipped_schematic),
                        "runtime_screening": {"rank": 1},
                        "runtime_contracts": [{"status": "PASS"}],
                        "geometry": {
                            "evidence_available": True,
                            "structural_change_ratio": 0.01,
                        },
                        "performance": candidate_performance,
                        "module_comparison": {
                            "unmatched_reference_modules": [],
                            "unmatched_candidate_modules": [],
                        },
                    },
                    {
                        "cannon_file": candidate_schematic.name,
                        "schematic": str(candidate_schematic),
                        "runtime_screening": {"rank": 2},
                        "runtime_contracts": [],
                        "geometry": {
                            "evidence_available": True,
                            "structural_change_ratio": 0.01,
                        },
                        "performance": candidate_performance,
                        "module_comparison": {
                            "unmatched_reference_modules": [
                                {"module_id": "R-EDIT"},
                            ],
                            "unmatched_candidate_modules": [
                                {"module_id": "C-EDIT"},
                            ],
                        },
                    },
                    {
                        "cannon_file": "no-geometry.schem",
                        "schematic": str(skipped_schematic),
                        "runtime_screening": {"rank": 3},
                        "runtime_contracts": [],
                        "geometry": {"evidence_available": False},
                        "performance": candidate_performance,
                        "module_comparison": {},
                    },
                ],
            }, indent=2),
            encoding="utf-8",
        )

        calls: list[dict[str, Any]] = []

        def fake_contract(*args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {
                "status": "PASS",
                "failures": [],
                "summary": {
                    "protected_runtime_contracts": 2,
                    "failed_runtime_contracts": 0,
                },
                "module_runtime_contracts": [],
                "shared_component_cohort_contract": {
                    "status": "PASS",
                    "comparisons": [],
                },
                "joint_entity_cohort_contract": {
                    "status": "PASS",
                    "comparisons": [],
                },
            }

        report = subject.build_report(
            source_report,
            runtime_rank_from=1,
            runtime_count=3,
            max_runtime_contract_runs=1,
            contract_tool=SimpleNamespace(build_report=fake_contract),
        )
        assert report["status"] == "PASS", report
        assert report["extended_count"] == 1, report
        assert report["results"][0]["cannon_file"] == candidate_schematic.name
        assert report["results"][0]["runtime_rank"] == 2
        assert report["results"][0]["promotion"]["promotion_ready"] is True
        assert len(calls) == 1, calls
        assert calls[0]["allowed_reference_modules"] == {"R-EDIT"}
        assert calls[0]["allowed_candidate_modules"] == {"C-EDIT"}
        reasons = {row["reason"] for row in report["skipped"]}
        assert reasons == {
            "runtime_evidence_already_present",
            "geometry_evidence_unavailable",
        }, report

        empty = subject.build_report(
            source_report,
            runtime_rank_from=9,
            runtime_count=2,
            max_runtime_contract_runs=1,
            contract_tool=SimpleNamespace(build_report=fake_contract),
        )
        assert empty["status"] == "FAIL", empty
        assert "no_runtime_candidates_extended" in empty["failures"], empty

    print(
        "Repair runtime extension reuses prior geometry, skips existing or missing evidence, and replays only the requested rank window."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
