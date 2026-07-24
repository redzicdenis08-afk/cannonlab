#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = load_script("test_causal_repair_generator", REPO_ROOT / "scripts" / "generate-causal-repair-family.py")
AUDIT = load_script("test_causal_repair_audit", REPO_ROOT / "scripts" / "schem-audit.py")
MODULE_MAP = load_script("test_causal_repair_module_map", REPO_ROOT / "scripts" / "cannon-module-map.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_schematic(
    path: Path,
    dimensions: tuple[int, int, int],
    occupied: dict[tuple[int, int, int], str],
) -> None:
    width, height, length = dimensions
    blocks = {
        (x, y, z): occupied.get((x, y, z), "minecraft:air")
        for y in range(height)
        for z in range(length)
        for x in range(width)
    }
    entities = [
        {
            "pos": pos,
            "id": "minecraft:dispenser",
            "raw": {"Id": "minecraft:dispenser", "Pos": list(pos)},
        }
        for pos, state in occupied.items()
        if state.startswith("minecraft:dispenser")
    ]
    AUDIT.write_sponge_v2(
        path,
        {
            "format": "sponge-v2",
            "version": 2,
            "data_version": 3465,
            "blocks": blocks,
            "block_entities": entities,
            "source_dimensions": {
                "width": width,
                "height": height,
                "length": length,
            },
        },
        3465,
    )


def reference_fixture(root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    reference = root / "reference.schem"
    occupied = {
        (0, 0, 1): "minecraft:stone",
        (1, 0, 1): "minecraft:stone",
        (2, 0, 1): "minecraft:stone",
        (3, 0, 1): "minecraft:stone",
        (0, 1, 1): "minecraft:stone_button[face=wall,facing=west,powered=false]",
        (1, 1, 1): "minecraft:repeater[delay=1,facing=east,locked=false,powered=false]",
        (2, 1, 1): "minecraft:repeater[delay=1,facing=east,locked=false,powered=false]",
        (3, 1, 1): "minecraft:dispenser[facing=east,triggered=false]",
        (25, 0, 1): "minecraft:stone",
        (25, 1, 1): "minecraft:dispenser[facing=west,triggered=false]",
    }
    write_schematic(reference, (30, 3, 3), occupied)
    report = MODULE_MAP.build_report(reference)
    modules = report["modules"]
    primary = min(modules, key=lambda row: row["bounds"]["min"][0])
    secondary = max(modules, key=lambda row: row["bounds"]["min"][0])
    assert primary["module_id"] != secondary["module_id"], modules
    return reference, primary, secondary


def divergence(path: Path, kind: str = "impulse_timing_drift") -> None:
    write_json(
        path,
        {
            "schema_version": 1,
            "comparison": {
                "first_divergence": {
                    "kind": kind,
                    "tick": 18,
                    "reference": 1.0,
                    "candidate": 0.5,
                }
            },
        },
    )


def policy_for(
    reference: Path,
    module: dict[str, Any],
    *,
    two_controls: bool = True,
) -> dict[str, Any]:
    controls = [
        {
            "id": "cohort-a",
            "kind": "repeater-delay",
            "module_id": module["module_id"],
            "positions": [[1, 1, 1]],
            "allowed_values": [1, 2],
            "divergence_kinds": ["impulse_timing_drift"],
            "justification": "Synthetic exact module trace maps this repeater to the divergent timing cohort.",
        }
    ]
    if two_controls:
        controls.append(
            {
                "id": "cohort-b",
                "kind": "repeater-delay",
                "module_id": module["module_id"],
                "positions": [[2, 1, 1]],
                "allowed_values": [1, 2],
                "divergence_kinds": ["impulse_timing_drift"],
                "justification": "Synthetic exact module trace maps this second repeater to the divergent timing cohort.",
            }
        )
    return {
        "schema_version": 1,
        "id": "synthetic-causal-repair-policy",
        "source_sha256": digest(reference),
        "controls": controls,
        "search": {
            "max_controls_per_candidate": 2 if two_controls else 1,
            "max_candidates": 16,
        },
        "preservation": {
            "chunk_limit": 160,
            "max_structural_change_ratio": 0.3,
            "max_functional_change_ratio": 0.5,
            "max_modules_touched": 1,
            "max_unexpected_critical_changes": 0,
            "allow_dimension_change": False,
            "allow_block_entity_topology_change": False,
            "minimum_alignment_confidence": "low",
            "alignment_mode": "exact",
        },
    }


def run_family(
    root: Path,
    reference: Path,
    module: dict[str, Any],
    *,
    kind: str = "impulse_timing_drift",
    policy_payload: dict[str, Any] | None = None,
    suffix: str = "one",
) -> dict[str, Any]:
    divergence_path = root / f"divergence-{suffix}.json"
    policy_path = root / f"policy-{suffix}.json"
    divergence(divergence_path, kind)
    write_json(policy_path, policy_payload or policy_for(reference, module))
    return GENERATOR.build_family(
        reference,
        divergence_path,
        policy_path,
        root / f"family-{suffix}",
        root / f"family-{suffix}.json",
        REPO_ROOT,
    )


def candidate_delays(path: Path) -> tuple[int, int]:
    root_name, root, _trailing, _size, _diagnostics = AUDIT.load(path)
    model = AUDIT.decode_any(root_name, root)
    return (
        int(AUDIT.properties(model["blocks"][(1, 1, 1)])["delay"]),
        int(AUDIT.properties(model["blocks"][(2, 1, 1)])["delay"]),
    )


def test_generates_minimal_and_paired_bounded_repairs() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        reference, module, _secondary = reference_fixture(root)
        report_a = run_family(root, reference, module, suffix="a")
        report_b = run_family(root, reference, module, suffix="b")
        assert report_a["status"] == "PASS"
        assert report_a["promotion"] == "GENERATED_BOUNDED_REPAIR_FAMILY"
        assert report_a["summary"]["generated_combinations"] == 3, report_a["summary"]
        assert report_a["summary"]["accepted_candidates"] == 3, report_a["rejected"]
        delays = {
            candidate_delays(Path(row["schematic"]["path"]))
            for row in report_a["candidates"]
        }
        assert delays == {(2, 1), (1, 2), (2, 2)}, delays
        assert all(row["preservation"]["status"] == "PASS" for row in report_a["candidates"])
        assert all(row["chunk_scan"]["safe_alignment_count"] == 256 for row in report_a["candidates"])
        hashes_a = sorted(row["schematic"]["sha256"] for row in report_a["candidates"])
        hashes_b = sorted(row["schematic"]["sha256"] for row in report_b["candidates"])
        assert hashes_a == hashes_b
        assert report_a["truth_boundary"]["runtime_improvement_confirmed"] is False
        assert report_a["truth_boundary"]["ec_ready"] is False


def test_source_hash_drift_fails() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        reference, module, _secondary = reference_fixture(root)
        policy = policy_for(reference, module)
        policy["source_sha256"] = "0" * 64
        try:
            run_family(root, reference, module, policy_payload=policy, suffix="hash")
        except GENERATOR.RepairGenerationError as exc:
            assert "reference hash mismatch" in str(exc)
        else:
            raise AssertionError("reference hash drift must fail")


def test_unmapped_divergence_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        reference, module, _secondary = reference_fixture(root)
        try:
            run_family(root, reference, module, kind="terminal_explosion_missing", suffix="kind")
        except GENERATOR.RepairGenerationError as exc:
            assert "no declared repair control matches" in str(exc)
        else:
            raise AssertionError("unmapped divergence must fail")


def test_position_outside_declared_module_fails() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        reference, module, secondary = reference_fixture(root)
        policy = policy_for(reference, module, two_controls=False)
        policy["controls"][0]["positions"] = [[25, 1, 1]]
        try:
            run_family(root, reference, module, policy_payload=policy, suffix="owner")
        except GENERATOR.RepairGenerationError as exc:
            assert "is not owned by declared module" in str(exc)
        else:
            raise AssertionError("cross-module repair position must fail")
        assert module["module_id"] != secondary["module_id"]


def test_invalid_repeater_delay_fails() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        reference, module, _secondary = reference_fixture(root)
        policy = policy_for(reference, module, two_controls=False)
        policy["controls"][0]["allowed_values"] = [0, 5]
        try:
            run_family(root, reference, module, policy_payload=policy, suffix="delay")
        except GENERATOR.RepairGenerationError as exc:
            assert "must be 1..4" in str(exc)
        else:
            raise AssertionError("invalid repeater delays must fail")


def test_state_choice_type_change_requires_explicit_permission() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        reference, module, _secondary = reference_fixture(root)
        policy = policy_for(reference, module, two_controls=False)
        policy["controls"] = [
            {
                "id": "state-choice",
                "kind": "block-state-choice",
                "module_id": module["module_id"],
                "positions": [[1, 1, 1]],
                "allowed_states": ["minecraft:comparator[facing=east,mode=compare,powered=false]"],
                "divergence_kinds": ["impulse_timing_drift"],
                "justification": "Synthetic negative fixture.",
            }
        ]
        try:
            run_family(root, reference, module, policy_payload=policy, suffix="state")
        except GENERATOR.RepairGenerationError as exc:
            assert "changes block type without allow_type_change" in str(exc)
        else:
            raise AssertionError("implicit block type changes must fail")


def main() -> None:
    tests = [
        test_generates_minimal_and_paired_bounded_repairs,
        test_source_hash_drift_fails,
        test_unmapped_divergence_fails_closed,
        test_position_outside_declared_module_fails,
        test_invalid_repeater_delay_fails,
        test_state_choice_type_change_requires_explicit_permission,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"All {len(tests)} causal repair generation regressions passed.")


if __name__ == "__main__":
    main()
