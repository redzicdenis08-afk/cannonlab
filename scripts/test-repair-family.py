#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def load_subject() -> Any:
    script = Path(__file__).resolve().with_name("analyze-repair-family.py")
    spec = importlib.util.spec_from_file_location("cannonlab_repair_family_test", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_run(
    root: Path,
    *,
    run_id: str,
    cannon_file: str,
    self_damage: int,
    target_destroyed: int,
    initial_dispensers: int,
    remaining_dispensers: int,
    contract_pass: bool,
    target_distance: int = 64,
) -> Path:
    run = root / run_id
    shot = run / "shot-001"
    shot.mkdir(parents=True, exist_ok=True)
    (shot / "causal-events.csv").write_text(
        "tick,sequence,event,component_id,entity_uuid,entity_type\n",
        encoding="utf-8",
    )
    summary = run / "run-summary.json"
    summary.write_text(
        json.dumps({
            "run_id": run_id,
            "scenario": "repair-family-test",
            "cannon_file": cannon_file,
            "target_type": "DRY",
            "target_direction": "NORTH",
            "target_material": "COBBLESTONE",
            "target_alternate_material": "OBSIDIAN",
            "target_distance": target_distance,
            "target_layers": 1,
            "target_spacing": 16,
            "target_bounds": {"min_x": -10, "min_y": 0, "min_z": -64, "max_x": 10, "max_y": 20, "max_z": -64},
            "arena_origin": {"x": 0, "y": 100, "z": 0},
            "regeneration": {"enabled": False},
            "shots_requested": 1,
            "shots_completed": 1,
            "finish_reason": "complete",
            "shots": [
                {
                    "shot": 1,
                    "finish_reason": "quiet",
                    "contract_pass": contract_pass,
                    "error": None,
                    "cannon_initial_dispensers": initial_dispensers,
                    "cannon_remaining_dispensers": remaining_dispensers,
                    "cannon_missing_blocks": max(0, initial_dispensers - remaining_dispensers),
                    "cannon_replaced_type_blocks": 0,
                    "self_damage_blocks": self_damage,
                    "target_blocks_destroyed": target_destroyed,
                    "target_blocks_total": 100,
                    "explosions": 100,
                    "maximum_forward_distance": 64,
                    "cohorts": {"global": {"spawns": 100}},
                },
            ],
        }, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    subject = load_subject()
    try:
        subject.validate_configuration(
            chunk_limit=160,
            max_runtime_contract_runs=0,
            max_geometry_candidates=0,
            max_runtime_candidates=0,
            minimum_dispenser_survival=0.95,
            minimum_self_damage_reduction=0.10,
            minimum_target_retention=0.80,
            maximum_structural_change_ratio=0.03,
        )
    except ValueError as exc:
        assert "max_runtime_contract_runs" in str(exc)
    else:
        raise AssertionError("invalid runtime-contract count was accepted")

    try:
        subject.validate_configuration(
            chunk_limit=160,
            max_runtime_contract_runs=1,
            max_geometry_candidates=-1,
            max_runtime_candidates=0,
            minimum_dispenser_survival=0.95,
            minimum_self_damage_reduction=0.10,
            minimum_target_retention=0.80,
            maximum_structural_change_ratio=0.03,
        )
    except ValueError as exc:
        assert "max_geometry_candidates" in str(exc)
    else:
        raise AssertionError("negative geometry-candidate budget was accepted")

    try:
        subject.validate_configuration(
            chunk_limit=160,
            max_runtime_contract_runs=1,
            max_geometry_candidates=0,
            max_runtime_candidates=-1,
            minimum_dispenser_survival=0.95,
            minimum_self_damage_reduction=0.10,
            minimum_target_retention=0.80,
            maximum_structural_change_ratio=0.03,
        )
    except ValueError as exc:
        assert "max_runtime_candidates" in str(exc)
    else:
        raise AssertionError("negative runtime-candidate budget was accepted")

    with tempfile.TemporaryDirectory(prefix="cannonlab-repair-family-") as temporary:
        root = Path(temporary)
        cannons = root / "cannons"
        results = root / "results"
        cannons.mkdir()
        results.mkdir()
        reference_schematic = cannons / "reference.schem"
        good_schematic = cannons / "repair-good.schem"
        bad_schematic = cannons / "repair-bad.schem"
        flashy_schematic = cannons / "repair-flashy.schem"
        mismatch_schematic = cannons / "repair-easy-target.schem"
        for path in (
            reference_schematic,
            good_schematic,
            bad_schematic,
            flashy_schematic,
            mismatch_schematic,
        ):
            path.write_bytes(path.name.encode("utf-8"))

        reference_summary = write_run(
            results,
            run_id="reference-run",
            cannon_file=reference_schematic.name,
            self_damage=100,
            target_destroyed=100,
            initial_dispensers=100,
            remaining_dispensers=95,
            contract_pass=True,
        )
        good_summary_one = write_run(
            results,
            run_id="good-run-1",
            cannon_file=good_schematic.name,
            self_damage=50,
            target_destroyed=92,
            initial_dispensers=100,
            remaining_dispensers=99,
            contract_pass=True,
        )
        write_run(
            results,
            run_id="good-run-2",
            cannon_file=good_schematic.name,
            self_damage=52,
            target_destroyed=90,
            initial_dispensers=100,
            remaining_dispensers=98,
            contract_pass=True,
        )
        write_run(
            results,
            run_id="bad-run",
            cannon_file=bad_schematic.name,
            self_damage=130,
            target_destroyed=45,
            initial_dispensers=100,
            remaining_dispensers=75,
            contract_pass=False,
        )
        write_run(
            results,
            run_id="flashy-run",
            cannon_file=flashy_schematic.name,
            self_damage=20,
            target_destroyed=100,
            initial_dispensers=100,
            remaining_dispensers=100,
            contract_pass=True,
        )
        write_run(
            results,
            run_id="easy-target-run",
            cannon_file=mismatch_schematic.name,
            self_damage=0,
            target_destroyed=100,
            initial_dispensers=100,
            remaining_dispensers=100,
            contract_pass=True,
            target_distance=32,
        )
        mirror = results / "mirrored-good-run-1"
        shutil.copytree(good_summary_one.parent, mirror)

        preservation_calls: list[str] = []
        comparison_calls: list[str] = []

        def preservation(reference: Path, candidate: Path, **kwargs: Any) -> dict[str, Any]:
            preservation_calls.append(candidate.name)
            good = "good" in candidate.name
            ratio = 0.01 if good else 0.08
            return {
                "summary": {
                    "structural_changes": 10 if good else 80,
                    "structural_change_ratio": ratio,
                    "functional_changes": 2 if good else 30,
                    "functional_change_ratio": ratio,
                    "modules_touched": 1 if good else 5,
                    "block_entity_topology_changed": not good,
                },
                "changed_type_counts": {},
                "impacted_modules": [],
            }

        def comparison(reference: Path, candidate: Path, **kwargs: Any) -> dict[str, Any]:
            comparison_calls.append(candidate.name)
            return {
                "summary": {"exact_module_matches": 2},
                "translation_alignment": {
                    "selected": [0, 0, 0],
                    "pairing_confidence": "high",
                },
                "unmatched_first_modules": [{"module_id": "R-EDIT"}],
                "unmatched_second_modules": [{"module_id": "C-EDIT"}],
            }

        runtime_calls: list[str] = []

        def runtime_contract(
            reference: Path,
            reference_trace: Path,
            candidate: Path,
            candidate_trace: Path,
            **kwargs: Any,
        ) -> dict[str, Any]:
            runtime_calls.append(candidate.name)
            good = "good" in candidate.name
            if good:
                return {
                    "status": "PASS",
                    "failures": [],
                    "summary": {
                        "protected_runtime_contracts": 2,
                        "failed_runtime_contracts": 0,
                    },
                    "module_runtime_contracts": [],
                    "shared_component_cohort_contract": {"status": "PASS"},
                    "joint_entity_cohort_contract": {"status": "PASS"},
                }
            return {
                "status": "FAIL",
                "failures": ["unchanged_module_runtime_contract_failed"],
                "summary": {
                    "protected_runtime_contracts": 2,
                    "failed_runtime_contracts": 1,
                },
                "module_runtime_contracts": [
                    {
                        "status": "FAIL",
                        "first_module_id": "R-PROTECTED",
                        "second_module_id": "C-PROTECTED",
                        "failures": ["first_dispense_tick_delta_exceeded"],
                        "timing": {
                            "first_dispense_tick": {"delta": 4},
                        },
                        "entity_physics": {
                            "max_observed": {"spawn_velocity_delta": 0.5},
                        },
                    },
                ],
                "shared_component_cohort_contract": {
                    "status": "FAIL",
                    "comparisons": [
                        {
                            "status": "FAIL",
                            "module_ids": ["R-PROTECTED", "R-EDIT"],
                            "failures": ["shared_redstone_change_ticks_changed"],
                            "component_ids": {
                                "first": ["W[1,1,1]"],
                                "second": ["W[1,1,1]"],
                            },
                            "event_counts": {
                                "first": {"REDSTONE_CHANGE": 1},
                                "second": {"REDSTONE_CHANGE": 1},
                            },
                            "event_ticks": {
                                "REDSTONE_CHANGE": {"max_absolute_delta": 4},
                            },
                        },
                    ],
                },
                "joint_entity_cohort_contract": {
                    "status": "FAIL",
                    "comparisons": [
                        {
                            "status": "FAIL",
                            "module_ids": ["R-PROTECTED", "R-EDIT"],
                            "entity_type": "TNT",
                            "failures": ["joint_spawn_velocity_delta_exceeded"],
                            "pairs": [
                                {
                                    "status": "FAIL",
                                    "failures": ["joint_spawn_velocity_delta_exceeded"],
                                    "spawn_tick": {"delta": 0},
                                    "spawn_point": {"distance": 0.0},
                                    "source_components": {
                                        "first": ["D[1,1,1]"],
                                        "second": ["D[1,1,1]"],
                                    },
                                    "explosion_timing": {"max_absolute_delta": 0},
                                    "physics": {
                                        "max_observed": {"spawn_velocity_delta": 0.5},
                                    },
                                },
                            ],
                        },
                    ],
                },
            }

        fake_tools = {
            "cannon-preservation-check.py": SimpleNamespace(build_report=preservation),
            "compare-cannon-modules.py": SimpleNamespace(build_report=comparison),
            "compare-module-traces.py": SimpleNamespace(build_report=runtime_contract),
        }
        original_loader = subject.load_script
        subject.load_script = lambda name, filename: fake_tools[filename]
        try:
            report = subject.build_report(
                reference_schematic,
                reference_summary,
                [results],
                [cannons],
                max_runtime_contract_runs=3,
            )
        finally:
            subject.load_script = original_loader

        assert report["status"] == "PASS", report
        assert report["candidate_count"] == 3, report
        assert report["configuration"]["discovered_summary_count"] == 7, report
        assert report["configuration"]["unique_run_count"] == 6, report
        assert any(
            row.get("cannon_file") == mismatch_schematic.name
            and row.get("reason") == "test_contract_mismatch"
            for row in report["skipped"]
        ), report
        candidates_by_file = {
            row["cannon_file"]: row
            for row in report["candidates"]
        }
        good = candidates_by_file[good_schematic.name]
        bad = candidates_by_file[bad_schematic.name]
        flashy = candidates_by_file[flashy_schematic.name]
        assert good["cannon_file"] == good_schematic.name, report
        assert good["promotion"]["promotion_ready"] is True, good
        assert good["promotion"]["verdict"] == "PROMOTION_READY_BOUNDED_REPAIR", good
        assert good["performance"]["run_count"] == 2, good
        assert good["pareto_front"] is True, good
        assert good["decision_metrics"]["runtime_contract_pass_rate"] == 1.0, good
        assert bad["cannon_file"] == bad_schematic.name, report
        assert bad["promotion"]["promotion_ready"] is False, bad
        assert "protected_module_runtime_drift" in bad["promotion"]["blockers"], bad
        assert bad["runtime_drift_summary"]["deterministic_drifting_modules"] == 1, bad
        assert bad["runtime_drift_summary"]["deterministic_shared_cohorts"] == 1, bad
        assert bad["runtime_drift_summary"]["deterministic_joint_cohorts"] == 1, bad
        assert bad["pareto_front"] is False, bad
        assert flashy["promotion"]["promotion_ready"] is False, flashy
        assert "structural_change_ratio_above_maximum" in flashy["promotion"]["blockers"], flashy

        runtime_calls.clear()
        preservation_calls.clear()
        comparison_calls.clear()
        subject.load_script = lambda name, filename: fake_tools[filename]
        try:
            screened_report = subject.build_report(
                reference_schematic,
                reference_summary,
                [results],
                [cannons],
                max_runtime_contract_runs=1,
                max_geometry_candidates=2,
                max_runtime_candidates=1,
            )
        finally:
            subject.load_script = original_loader
        assert screened_report["status"] == "PASS", screened_report
        assert screened_report["configuration"]["runtime_candidates_selected"] == 1
        assert screened_report["configuration"]["runtime_candidates_not_selected"] == 2
        assert screened_report["configuration"]["geometry_candidates_selected"] == 2
        assert screened_report["configuration"]["geometry_candidates_not_selected"] == 1
        screened_by_file = {
            row["cannon_file"]: row
            for row in screened_report["candidates"]
        }
        screened_good = screened_by_file[good_schematic.name]
        screened_bad = screened_by_file[bad_schematic.name]
        screened_flashy = screened_by_file[flashy_schematic.name]
        assert screened_good["cannon_file"] == good_schematic.name, screened_report
        assert screened_good["geometry_screening"]["selected_for_geometry"] is True
        assert screened_good["runtime_screening"]["selected_for_runtime"] is True
        assert screened_good["promotion"]["promotion_ready"] is True
        assert screened_bad["cannon_file"] == bad_schematic.name, screened_report
        assert screened_bad["geometry_screening"]["selected_for_geometry"] is False
        assert screened_bad["geometry"]["evidence_available"] is False
        assert screened_bad["runtime_screening"]["selected_for_runtime"] is False
        assert screened_bad["runtime_contracts"] == []
        assert screened_bad["pareto_eligible"] is False
        assert screened_bad["pareto_front"] is False
        assert "no_runtime_contract_evidence" in screened_bad["promotion"]["blockers"]
        assert "no_geometry_evidence" in screened_bad["promotion"]["blockers"]
        assert screened_flashy["geometry_screening"]["selected_for_geometry"] is True
        assert screened_flashy["runtime_screening"]["selected_for_runtime"] is False
        assert "structural_change_ratio_above_maximum" in screened_flashy[
            "promotion"
        ]["blockers"]
        assert set(preservation_calls) == {
            good_schematic.name,
            flashy_schematic.name,
        }, preservation_calls
        assert set(comparison_calls) == {
            good_schematic.name,
            flashy_schematic.name,
        }, comparison_calls
        assert runtime_calls == [good_schematic.name], runtime_calls

        multi_summary = write_run(
            results,
            run_id="multi-shot-trace-run",
            cannon_file=good_schematic.name,
            self_damage=50,
            target_destroyed=90,
            initial_dispensers=100,
            remaining_dispensers=99,
            contract_pass=True,
        )
        multi_payload = json.loads(multi_summary.read_text(encoding="utf-8"))
        second_shot = dict(multi_payload["shots"][0])
        second_shot["shot"] = 2
        multi_payload["shots"].append(second_shot)
        multi_payload["shots_requested"] = 2
        multi_payload["shots_completed"] = 2
        multi_summary.write_text(json.dumps(multi_payload, indent=2), encoding="utf-8")
        second_trace = multi_summary.parent / "shot-002" / "causal-events.csv"
        second_trace.parent.mkdir(parents=True, exist_ok=True)
        second_trace.write_text(
            "tick,sequence,event,component_id,entity_uuid,entity_type\n",
            encoding="utf-8",
        )
        assert [shot for shot, _ in subject.available_shot_traces(multi_summary)] == [1, 2]

        empty_results = root / "empty-results"
        empty_results.mkdir()
        subject.load_script = lambda name, filename: fake_tools[filename]
        try:
            empty_report = subject.build_report(
                reference_schematic,
                reference_summary,
                [empty_results],
                [cannons],
                max_runtime_contract_runs=1,
            )
        finally:
            subject.load_script = original_loader
        assert empty_report["status"] == "FAIL", empty_report
        assert empty_report["candidate_count"] == 0, empty_report
        assert "no_candidate_repairs_resolved" in empty_report["failures"], empty_report

    print(
        "Repair-family ranking screens cheaply, replays only top candidates, promotes the bounded stable fix, rejects destructive drift, and fails closed when no candidates resolve."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
