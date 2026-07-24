#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit-ec-calibration.py"
RULES = ROOT / "profiles" / "parity" / "extremecraft-evidence-rules-v1.json"
spec = importlib.util.spec_from_file_location("audit_ec_calibration", SCRIPT)
if spec is None or spec.loader is None:
    raise RuntimeError(f"unable to import {SCRIPT}")
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_audit(evidence: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(evidence), "--rules", str(RULES), *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if not result.stdout:
        raise AssertionError(result.stderr)
    return result.returncode, json.loads(result.stdout)


def sample_for(dimension: str, index: int, labels: dict[str, Any]) -> dict[str, Any]:
    sample: dict[str, Any] = {"sample_id": f"{dimension}-{index:04d}"}
    if dimension == "tnt.spawn.horizontal_kick":
        sample.update(spawn_tick=index, initial_velocity=[0.0, 0.2, 0.0])
    elif dimension == "tnt.fuse.distribution":
        sample.update(spawn_tick=index, explosion_tick=index + 79, initial_fuse=79)
    elif dimension == "redstone.dispenser.activation_order":
        sample.update(sequence=["WEST", "EAST", "NORTH", "SOUTH", "DOWN", "UP"])
    elif dimension == "entity.collision.axis_order":
        sample.update(
            orientation=labels["orientation"],
            initial_state={"position": [0, 100, 0], "velocity": [1, 0, 0]},
            final_displacement=[1.0, 0.0, 0.0],
            outcome="survived",
        )
    elif dimension == "tnt.water_motion":
        sample.update(
            environment=labels["environment"],
            initial_state={"position": [0, 100, 0], "velocity": [1, 0, 0]},
            positions=[[0, 100, 0], [1, 100, 0]],
            outcome="survived",
        )
    elif dimension == "tnt.velocity_and_despawn_limits":
        sample.update(
            requested_velocity=[float(index + 1), 0, 0],
            observed_velocity=[float(index + 1), 0, 0],
            outcome="survived",
            removal_tick=None,
        )
    elif dimension == "explosion.batch_and_per_tick_limits":
        count = 16 + index
        sample.update(
            cohort_size=count,
            due_tick=100,
            due_count=count,
            observed_count=count,
            processing_tick_count=1,
        )
    elif dimension == "falling_block.tick_and_collision":
        sample.update(
            material="minecraft:sand",
            spawn_tick=index,
            positions=[[0, 100, 0], [0, 99, 0]],
            collision_layout="air-to-solid",
            outcome="landed",
        )
    elif dimension == "piston_chain_and_observer_updates":
        sample.update(
            chain_length=8,
            tnt_load=index % 4,
            input_tick=0,
            event_order=["observer", "piston-extend", "piston-retract"],
            outcome="completed",
        )
    elif dimension == "chunk_loading_and_crossing":
        sample.update(
            boundary_type="chunk-x",
            player_position=[0, 100, 0],
            positions=[[15.5, 100, 0], [16.5, 100, 0]],
            outcome="continuous",
        )
    elif dimension == "limits.dispensers_per_chunk":
        amount = 155 if index % 2 == 0 else 161
        sample.update(
            dispensers=amount,
            block_entities=amount,
            offset_x=index % 16,
            offset_z=(index // 16) % 16,
            paste_result="pass" if amount <= 160 else "fail",
        )
    elif dimension == "limits.fawe_block_entities":
        amount = 100 if index % 2 == 0 else 200
        sample.update(
            dispensers=0,
            block_entities=amount,
            block_entity_types={"minecraft:chest": amount},
            offset_x=index % 16,
            offset_z=(index // 16) % 16,
            paste_result="pass" if amount == 100 else "fail",
        )
    elif dimension == "durability.material_hit_contract":
        sample.update(
            material="minecraft:obsidian",
            hit_number=(index % 4) + 1,
            source_position=[0.5, 100.5, 1.5],
            water_state="watered" if index % 2 else "dry",
            damage_tick=100 + index,
            outcome_tick=101 + index,
            outcome="damaged",
        )
    elif dimension == "regeneration.algorithm":
        sample.update(
            structure_hash="a" * 64,
            damage_tick=100 + index,
            damaged_cells=[[0, 100, 0]],
            replacement_events=[{"tick": 105 + index, "cell": [0, 100, 0]}],
            outcome="restored",
        )
    elif dimension == "osrb.clip_and_restack":
        sample.update(
            ratio_profile_id="public-0.7-384-osrb-1-above-barrel",
            target_layout_hash="b" * 64,
            payload_order=["sand", "osrb-sand", "osrb-hammer"],
            clip_result="clipped",
            restack_position=[0, 100, 0],
            outcome="restacked",
        )
    elif dimension == "full_cannon.field_workflow":
        sample.update(
            paste_time=f"2026-07-24T00:00:{index % 60:02d}Z",
            settle_ticks=120,
            fill_time=f"2026-07-24T00:01:{index % 60:02d}Z",
            fire_input="button@0,101,0",
            prefire_activations=0,
            survival_snapshot={"remaining_dispenser_ratio": 1.0},
            outcome="completed",
        )
    else:
        raise AssertionError(dimension)
    return sample


def build_complete_pack(root: Path) -> None:
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    fixture = root / "fixture.schem"
    artifact = root / "raw-evidence.txt"
    fixture.write_bytes(b"fixture-v1")
    artifact.write_text("raw evidence\n", encoding="utf-8")
    fixture_ref = {"id": "fixture-v1", "path": fixture.name, "sha256": digest(fixture)}
    artifact_ref = {"path": artifact.name, "sha256": digest(artifact)}

    for dimension, rule in rules["dimensions"].items():
        required = rule.get("required_labels")
        label_values = list(required.get("values", [])) if isinstance(required, dict) else []
        samples = []
        for index in range(int(rule["minimum_samples"])):
            labels = {}
            if isinstance(required, dict):
                labels[required["field"]] = label_values[index % len(label_values)]
            samples.append(sample_for(dimension, index, labels))
        payload = {
            "kind": "ec-parity-evidence",
            "schema_version": 1,
            "dimension": dimension,
            "server": "ExtremeCraft Cannoning",
            "captured_at": "2026-07-24T00:00:00Z",
            "server_date": "2026-07-24",
            "client_version": "1.21.11",
            "paste_origin": {"x": 0, "y": 100, "z": 0},
            "chunk_origin_confirmed": True,
            "fixture": fixture_ref,
            "raw_artifacts": [artifact_ref],
            "samples": samples,
        }
        if dimension == "tnt.spawn.horizontal_kick":
            payload["claimed_classification"] = "zero-horizontal-kick"
        elif dimension == "tnt.fuse.distribution":
            payload["claimed_classification"] = "fixed-lifetime-79"
        elif dimension == "redstone.dispenser.activation_order":
            payload["claimed_classification"] = "fixed-order"
        elif dimension == "explosion.batch_and_per_tick_limits":
            payload["claimed_classification"] = "no-observed-cap-within-tested-range"
        (root / f"{dimension.replace('.', '_')}.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )


def test_complete_hash_backed_pack_passes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        build_complete_pack(root)
        code, report = run_audit(root)
        assert code == 0, report
        assert report["status"] == "PASS", report
        assert report["ec_calibrated"] is True, report
        assert report["required_dimension_count"] == 16, report
        assert report["valid_dimension_count"] == 16, report
        assert report["missing_dimensions"] == [], report
        assert report["invalid_file_count"] == 0, report
        by_id = {row["dimension"]: row for row in report["dimension_reports"]}
        assert by_id["tnt.spawn.horizontal_kick"]["analysis"]["classification"] == "zero-horizontal-kick"
        assert by_id["tnt.fuse.distribution"]["analysis"]["classification"] == "fixed-lifetime-79"
        assert by_id["redstone.dispenser.activation_order"]["analysis"]["classification"] == "fixed-order"
        assert (
            by_id["explosion.batch_and_per_tick_limits"]["analysis"]["classification"]
            == "no-observed-cap-within-tested-range"
        )


def test_legacy_incomplete_pack_stays_compatible_and_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "fuse.json").write_text(
            json.dumps({
                "server": "ExtremeCraft Cannoning",
                "captured_at": "2026-07-22T00:00:00Z",
                "client_version": "1.21.11",
                "probe": "single-dispenser-fuse",
                "paste_origin": {"x": 0, "y": 100, "z": 0},
                "chunk_origin_confirmed": True,
                "samples": [],
            }),
            encoding="utf-8",
        )
        code, report = run_audit(root)
        assert code == 2, report
        assert report["status"] == "INCOMPLETE", report
        assert report["ec_calibrated"] is False, report
        assert "chunk-paste-limits" in report["missing_probes"], report
        assert "tnt.fuse.distribution" in report["missing_dimensions"], report
        assert report["legacy_compatibility"]["legacy_files_do_not_promote_v2_dimensions"] is True


def test_hash_mismatch_invalidates_file_and_dimension() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        build_complete_pack(root)
        artifact = root / "raw-evidence.txt"
        artifact.write_text("tampered\n", encoding="utf-8")
        code, report = run_audit(root)
        assert code == 2, report
        assert report["invalid_file_count"] == 16, report
        assert report["valid_dimension_count"] == 0, report
        assert all(
            any("sha256 mismatch" in error for error in file["errors"])
            for file in report["files"]
        ), report


def test_secret_like_keys_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        build_complete_pack(root)
        target = next(root.glob("tnt_spawn_horizontal_kick.json"))
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["metadata"] = {"access_token": "do-not-store-this"}
        target.write_text(json.dumps(payload), encoding="utf-8")
        code, report = run_audit(root)
        assert code == 2, report
        bad = next(row for row in report["files"] if row["file"] == str(target))
        assert any("forbidden credential-like keys" in error for error in bad["errors"]), bad


def test_claim_conflict_fails_dimension() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        build_complete_pack(root)
        target = next(root.glob("tnt_fuse_distribution.json"))
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["claimed_classification"] = "distributed-lifetime"
        target.write_text(json.dumps(payload), encoding="utf-8")
        code, report = run_audit(root)
        assert code == 2, report
        fuse = next(
            row for row in report["dimension_reports"]
            if row["dimension"] == "tnt.fuse.distribution"
        )
        assert any("conflicts with derived" in error for error in fuse["errors"]), fuse


def test_duplicate_sample_ids_across_files_fail_dimension() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        build_complete_pack(root)
        target = next(root.glob("tnt_spawn_horizontal_kick.json"))
        payload = json.loads(target.read_text(encoding="utf-8"))
        split = payload["samples"][:50]
        payload["samples"] = payload["samples"][50:]
        target.write_text(json.dumps(payload), encoding="utf-8")
        duplicate = dict(payload)
        duplicate["samples"] = split + [payload["samples"][0]]
        duplicate["claimed_classification"] = "zero-horizontal-kick"
        (root / "horizontal-extra.json").write_text(json.dumps(duplicate), encoding="utf-8")
        code, report = run_audit(root)
        assert code == 2, report
        horizontal = next(
            row for row in report["dimension_reports"]
            if row["dimension"] == "tnt.spawn.horizontal_kick"
        )
        assert any("duplicate sample_ids across files" in error for error in horizontal["errors"]), horizontal


def test_path_escape_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        build_complete_pack(root)
        target = next(root.glob("tnt_spawn_horizontal_kick.json"))
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["raw_artifacts"][0]["path"] = "../outside.log"
        target.write_text(json.dumps(payload), encoding="utf-8")
        code, report = run_audit(root)
        assert code == 2, report
        bad = next(row for row in report["files"] if row["file"] == str(target))
        assert any("path escapes evidence root" in error for error in bad["errors"]), bad


def main() -> None:
    tests = [
        test_complete_hash_backed_pack_passes,
        test_legacy_incomplete_pack_stays_compatible_and_fails_closed,
        test_hash_mismatch_invalidates_file_and_dimension,
        test_secret_like_keys_are_rejected,
        test_claim_conflict_fails_dimension,
        test_duplicate_sample_ids_across_files_fail_dimension,
        test_path_escape_is_rejected,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")


if __name__ == "__main__":
    main()
