#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def load_subject() -> Any:
    script = Path(__file__).resolve().with_name("compare-module-traces.py")
    spec = importlib.util.spec_from_file_location("cannonlab_runtime_contract_v3_test", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def module_runtime(module_id: str) -> dict[str, Any]:
    return {
        "module_id": module_id,
        "signature": "shared-signature",
        "active": True,
        "first_tick": 0,
        "last_tick": 2,
        "first_dispense_tick": 2,
        "first_piston_tick": None,
        "first_falling_spawn_tick": None,
        "first_tnt_spawn_tick": 3,
        "exclusive_event_counts": {"DISPENSE": 1},
        "event_counts": {"DISPENSE": 1},
        "items_dispensed": {"TNT": 1},
        "correlated_entity_types": {},
        "attributed_explosions": [],
        "correlated_entity_profiles": [],
        "entity_profile_coverage": 0.0,
    }


def entity_profile(shift: int = 0) -> dict[str, Any]:
    return {
        "entity_uuid": "00000000-0000-0000-0000-000000000001",
        "entity_type": "PRIMED_TNT",
        "spawn_tick": 3,
        "spawn_point": [1.5 + shift, 1.5, 1.5],
        "spawn_velocity": [0.1, 0.2, -0.3],
        "fuse": 79,
        "explosions": [
            {"tick": 80, "point": [20.0 + shift, 1.0, -40.0]},
        ],
    }


def joint_cohort(
    first_module: str,
    second_module: str,
    shift: int = 0,
) -> dict[str, Any]:
    first_x = 1 + shift
    second_x = 2 + shift
    profile = entity_profile(shift)
    return {
        "spawn_tick": 3,
        "entity_type": "PRIMED_TNT",
        "spawn_point": [1.5 + shift, 1.5, 1.5],
        "entity_count": 1,
        "candidate_module_ids": [first_module, second_module],
        "candidate_dispense_components": [
            f"D[{first_x},1,1]",
            f"D[{second_x},1,1]",
        ],
        "candidate_dispense_events": [
            {
                "tick": 2,
                "component_id": f"D[{first_x},1,1]",
                "module_id": first_module,
                "item": "TNT",
            },
            {
                "tick": 2,
                "component_id": f"D[{second_x},1,1]",
                "module_id": second_module,
                "item": "TNT",
            },
        ],
        "mean_velocity": [0.1, 0.2, -0.3],
        "fuse_counts": {"79": 1},
        "explosion_event_count": 1,
        "explosion_ticks": {"80": 1},
        "entity_profiles": [profile],
    }


def runtime(prefix: str, shift: int = 0) -> dict[str, Any]:
    first = f"{prefix}1"
    second = f"{prefix}2"
    return {
        "schematic_sha256": f"sha-{prefix}",
        "summary": {
            "component_event_coverage": 1.0,
            "ambiguous_component_events": 1,
            "entity_spawns": 1,
            "unambiguous_entity_correlations": 0,
            "ambiguous_entity_correlations": 1,
            "mapped_entity_correlations": 1,
        },
        "modules": [module_runtime(first), module_runtime(second)],
        "shared_component_event_cohorts": [
            {
                "module_ids": [first, second],
                "event_counts": {"DISPENSE": 1},
                "event_ticks": {"DISPENSE": [2]},
            },
        ],
        "joint_entity_source_cohorts": [joint_cohort(first, second, shift)],
    }


def geometry() -> dict[str, Any]:
    return {
        "summary": {"exact_module_matches": 2},
        "translation_alignment": {
            "selected": [5, 0, 0],
            "pairing_confidence": "high",
            "max_residual_distance": 0,
            "ambiguous_top_vote": False,
        },
        "exact_module_matches": [
            {
                "pairs": [
                    {
                        "first_module_id": "R1",
                        "second_module_id": "C1",
                        "translation_vector": [5, 0, 0],
                    },
                    {
                        "first_module_id": "R2",
                        "second_module_id": "C2",
                        "translation_vector": [5, 0, 0],
                    },
                ],
            },
        ],
    }


def build_with_fake_inputs(
    subject: Any,
    reference_runtime: dict[str, Any],
    candidate_runtime: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    reports = iter([reference_runtime, candidate_runtime])
    fake_comparator = SimpleNamespace(build_report=lambda *args, **kwargs: geometry())
    fake_analyzer = SimpleNamespace(build_report=lambda *args, **kwargs: next(reports))
    original_loader = subject.load_script

    def fake_loader(name: str, filename: str) -> Any:
        if filename == "compare-cannon-modules.py":
            return fake_comparator
        if filename == "analyze-module-trace.py":
            return fake_analyzer
        return original_loader(name, filename)

    subject.load_script = fake_loader
    try:
        with tempfile.TemporaryDirectory(prefix="cannonlab-runtime-v3-") as temporary:
            root = Path(temporary)
            paths = [
                root / "reference.schem",
                root / "reference.csv",
                root / "candidate.schem",
                root / "candidate.csv",
            ]
            for path in paths:
                path.write_text(path.name, encoding="utf-8")
            return subject.build_report(*paths, **overrides)
    finally:
        subject.load_script = original_loader


def assert_failure(report: dict[str, Any], failure: str) -> None:
    assert report["status"] == "FAIL", report
    assert failure in report["failures"], report


def main() -> int:
    subject = load_subject()
    assert subject.candidate_module_in_reference_frame(
        "MODULE-011",
        candidate_to_reference={},
        allowed_reference_modules={"MODULE-011"},
        allowed_candidate_modules={"MODULE-011"},
    ) == "MODULE-011"
    assert subject.candidate_module_in_reference_frame(
        "RENAMED-EDIT",
        candidate_to_reference={},
        allowed_reference_modules={"MODULE-011"},
        allowed_candidate_modules={"RENAMED-EDIT"},
    ) == "candidate:RENAMED-EDIT"
    reference = runtime("R", shift=0)
    candidate = runtime("C", shift=5)

    baseline = build_with_fake_inputs(subject, reference, candidate)
    assert baseline["status"] == "PASS", baseline
    assert baseline["schema"] == "cannonlab-module-runtime-contract-v3", baseline
    assert baseline["summary"]["reference_entity_correlation_coverage"] == 0.0, baseline
    assert baseline["summary"]["reference_entity_source_accounting_coverage"] == 1.0, baseline
    assert baseline["summary"]["reference_shared_component_accounting_coverage"] == 1.0, baseline
    assert baseline["summary"]["reference_joint_entity_accounting_coverage"] == 1.0, baseline
    assert baseline["summary"]["shared_component_cohort_contract_status"] == "PASS", baseline
    assert baseline["summary"]["joint_entity_cohort_contract_status"] == "PASS", baseline

    unmapped = copy.deepcopy(candidate)
    unmapped["summary"]["mapped_entity_correlations"] = 0
    report = build_with_fake_inputs(subject, reference, unmapped)
    assert_failure(report, "candidate_entity_source_accounting_coverage_too_low")

    missing_shared = copy.deepcopy(candidate)
    missing_shared["shared_component_event_cohorts"] = []
    report = build_with_fake_inputs(subject, reference, missing_shared)
    assert_failure(report, "candidate_shared_component_accounting_coverage_too_low")
    assert "shared_component_cohort_contract_failed" in report["failures"], report

    delayed_shared = copy.deepcopy(candidate)
    delayed_shared["shared_component_event_cohorts"][0]["event_ticks"]["DISPENSE"] = [10]
    report = build_with_fake_inputs(subject, reference, delayed_shared)
    assert_failure(report, "shared_component_cohort_contract_failed")

    missing_joint = copy.deepcopy(candidate)
    missing_joint["joint_entity_source_cohorts"] = []
    report = build_with_fake_inputs(subject, reference, missing_joint)
    assert_failure(report, "candidate_joint_entity_accounting_coverage_too_low")
    assert "joint_entity_cohort_contract_failed" in report["failures"], report

    changed_source = copy.deepcopy(candidate)
    changed_source["joint_entity_source_cohorts"][0]["candidate_dispense_components"][0] = "D[99,1,1]"
    changed_source["joint_entity_source_cohorts"][0]["candidate_dispense_events"][0]["component_id"] = "D[99,1,1]"
    report = build_with_fake_inputs(subject, reference, changed_source)
    assert_failure(report, "joint_entity_cohort_contract_failed")
    joint_failures = report["joint_entity_cohort_contract"]["failures"]
    assert "joint_candidate_dispenser_sources_changed" in joint_failures, report

    delayed_source = copy.deepcopy(candidate)
    delayed_source["joint_entity_source_cohorts"][0]["candidate_dispense_events"][0]["tick"] = 20
    report = build_with_fake_inputs(subject, reference, delayed_source)
    assert_failure(report, "joint_entity_cohort_contract_failed")
    assert "joint_candidate_dispense_timing_changed" in report["joint_entity_cohort_contract"]["failures"], report

    changed_velocity = copy.deepcopy(candidate)
    changed_velocity["joint_entity_source_cohorts"][0]["mean_velocity"] = [0.8, 0.2, -0.3]
    changed_velocity["joint_entity_source_cohorts"][0]["entity_profiles"][0]["spawn_velocity"] = [0.8, 0.2, -0.3]
    report = build_with_fake_inputs(subject, reference, changed_velocity)
    assert_failure(report, "joint_entity_cohort_contract_failed")
    assert "joint_spawn_velocity_delta_exceeded" in report["joint_entity_cohort_contract"]["failures"], report

    changed_fuse_count = copy.deepcopy(candidate)
    changed_fuse_count["joint_entity_source_cohorts"][0]["fuse_counts"] = {"79": 2}
    report = build_with_fake_inputs(subject, reference, changed_fuse_count)
    assert_failure(report, "joint_entity_cohort_contract_failed")
    assert "joint_fuse_distribution_changed" in report["joint_entity_cohort_contract"]["failures"], report

    changed_explosion = copy.deepcopy(candidate)
    changed_explosion["joint_entity_source_cohorts"][0]["explosion_ticks"] = {"90": 1}
    changed_explosion["joint_entity_source_cohorts"][0]["entity_profiles"][0]["explosions"][0]["tick"] = 90
    report = build_with_fake_inputs(subject, reference, changed_explosion)
    assert_failure(report, "joint_entity_cohort_contract_failed")
    assert "joint_explosion_tick_distribution_changed" in report["joint_entity_cohort_contract"]["failures"], report

    mixed_exempt = build_with_fake_inputs(
        subject,
        reference,
        changed_velocity,
        allowed_candidate_modules={"C1"},
        minimum_unchanged_runtime_contracts=1,
    )
    assert_failure(mixed_exempt, "joint_entity_cohort_contract_failed")

    mixed_shared = build_with_fake_inputs(
        subject,
        reference,
        delayed_shared,
        allowed_candidate_modules={"C1"},
        minimum_unchanged_runtime_contracts=1,
    )
    assert_failure(mixed_shared, "shared_component_cohort_contract_failed")

    fully_exempt = build_with_fake_inputs(
        subject,
        reference,
        changed_velocity,
        allowed_candidate_modules={"C1", "C2"},
        minimum_unchanged_runtime_contracts=0,
    )
    assert fully_exempt["status"] == "PASS", fully_exempt

    print(
        "Runtime contract v3 accounts for shared sources, rejects mixed-cohort waiver laundering, and fails closed on timing, source, physics, fuse, and explosion drift."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
