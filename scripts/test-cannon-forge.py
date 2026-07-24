#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().with_name("cannon-forge.py")
SPEC = importlib.util.spec_from_file_location("cannon_forge", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
forge = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = forge
SPEC.loader.exec_module(forge)


def test_vec3() -> None:
    vector = forge.parse_vec3("4, 11, -13")
    assert vector.yaml() == "{x: 4, y: 11, z: -13}"


def test_registry() -> None:
    registry = forge.load_registry()
    assert registry["schema"] == "cannonlab-source-registry-v1"
    ids = {source["id"] for source in registry["sources"]}
    assert "historical-2019-1.12.2-cannon-guide" in ids
    assert "extremecraft-calibration-contract" in ids
    assert "cannoning-video-concept-corpus" in ids
    for source in registry["sources"]:
        paths = source.get("paths") or [source["path"]]
        assert paths, source
        for raw in paths:
            assert (forge.ROOT / raw).is_file(), (source["id"], raw)


def test_archetype_payload_contracts() -> None:
    hammered = forge.resolve_payload_contract("hammered-stacker", ["hybrid"], "auto")
    assert hammered["mode"] == "falling-block-required", hammered
    assert hammered["require_falling_block"] is True, hammered

    worm = forge.resolve_payload_contract("rev-worm", ["efficient-nuke"], "auto")
    assert worm["mode"] == "tnt-only", worm
    assert worm["watered_promotion_allowed"] is False, worm

    explicit = forge.resolve_payload_contract("force-or-counter", [], "tnt-only")
    assert explicit["source"] == "explicit-operator-selection", explicit

    for base, specializations, mode in (
        ("force-or-counter", [], "auto"),
        ("rev-worm", ["hybrid"], "tnt-only"),
        ("rev-worm", ["push-nuke"], "auto"),
    ):
        try:
            forge.resolve_payload_contract(base, specializations, mode)
        except ValueError:
            pass
        else:
            raise AssertionError((base, specializations, mode))


def test_scenario_pack() -> None:
    scenarios = forge.render_scenarios(
        slug="fixture",
        staged_name="forge-fixture.schem",
        origin=forge.Vec3(0, 0, 0),
        fire_input=forge.Vec3(4, 11, 13),
        fire_mode="button",
        direction="north",
        distance=160,
        width=17,
        height=32,
        shots=10,
    )
    assert len(scenarios) == 5
    joined = "\n".join(scenario["text"] for scenario in scenarios)
    assert "type: watered" in joined
    assert "type: slab-filter" in joined
    assert "type: hotdog" in joined
    assert "type: pillars" in joined
    assert "min-embedded-payload-explosions: 1" in joined
    assert "suppress-paste-side-effects: false" in joined
    assert "rebuild-cannon-between-shots: false" in joined
    assert all(scenario["assert_args"] for scenario in scenarios)
    assert all(scenario["wall_breach_args"] for scenario in scenarios)
    assert all("--require-cumulative-cannon" in scenario["assert_args"] for scenario in scenarios)


def test_tnt_only_scenario_pack() -> None:
    contract = forge.resolve_payload_contract("rev-worm", ["efficient-nuke"], "auto")
    scenarios = forge.render_scenarios(
        slug="tnt-only",
        staged_name="forge-tnt-only.schem",
        origin=forge.Vec3(0, 0, 0),
        fire_input=forge.Vec3(4, 11, 13),
        fire_mode="button",
        direction="east",
        distance=120,
        width=17,
        height=32,
        shots=10,
        payload_contract=contract,
    )
    assert len(scenarios) == 5, scenarios
    joined = "\n".join(scenario["text"] for scenario in scenarios)
    assert "type: watered" not in joined
    assert "min-falling-blocks: 0" in joined
    assert "min-embedded-payload-explosions: 0" in joined
    assert "rebuild-cannon-between-shots: false" in joined
    assert sum(bool(scenario["corridor_args"]) for scenario in scenarios) == 4
    assert all(scenario["wall_breach_args"] for scenario in scenarios)
    assert all("--require-cumulative-cannon" in scenario["assert_args"] for scenario in scenarios)


def test_control_state_rendering() -> None:
    state = forge.parse_control_state_json(
        json.dumps(
            {
                "name": "nuke-mode",
                "at": {"x": 4, "y": 2, "z": 1},
                "phase": "before-fill",
                "apply_tick": 1,
                "settle_ticks": 2,
                "apply_physics": True,
                "expected_material": "lever",
                "expected_before": "minecraft:lever[face=wall,facing=west,powered=false]",
                "block_data": "minecraft:lever[face=wall,facing=west,powered=true]",
            }
        )
    )
    scenarios = forge.render_scenarios(
        slug="control-state",
        staged_name="forge-control-state.schem",
        origin=forge.Vec3(0, 0, 0),
        fire_input=forge.Vec3(4, 11, 13),
        fire_mode="button",
        direction="north",
        distance=160,
        width=17,
        height=32,
        shots=10,
        control_states=[state],
    )
    for scenario in scenarios:
        assert "control-states:" in scenario["text"]
        assert 'name: "nuke-mode"' in scenario["text"]
        assert 'block-data: "minecraft:lever[face=wall,facing=west,powered=true]"' in scenario["text"]


def test_stage_round_trip() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "fixture.schem"
        source.write_bytes(b"fixture-schematic-bytes")
        staged, runtime_name = forge.stage_candidate(source, "round-trip")
        try:
            assert runtime_name == "forge-round-trip.schem"
            import base64

            assert base64.b64decode(staged.read_text(encoding="ascii")) == source.read_bytes()
        finally:
            staged.unlink(missing_ok=True)


def test_scenario_integrity() -> None:
    scenarios = forge.render_scenarios(
        slug="integrity-fixture",
        staged_name="forge-integrity-fixture.schem",
        origin=forge.Vec3(0, 0, 0),
        fire_input=forge.Vec3(4, 11, 13),
        fire_mode="button",
        direction="north",
        distance=160,
        width=17,
        height=32,
        shots=10,
    )
    for scenario in scenarios:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yml",
            dir=forge.ROOT / "scenarios",
            encoding="utf-8",
            newline="\n",
            delete=False,
        ) as handle:
            handle.write(scenario["text"])
            scenario_path = Path(handle.name)
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(forge.SCRIPTS / "scenario-integrity-audit.py"),
                    str(scenario_path),
                    "--require-field-candidate",
                ],
                cwd=forge.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            payload = json.loads(result.stdout)
            assert payload["status"] == "PASS", payload
            assert payload["assists"] == [], payload
        finally:
            scenario_path.unlink(missing_ok=True)


def main() -> None:
    test_vec3()
    test_registry()
    test_archetype_payload_contracts()
    test_scenario_pack()
    test_tnt_only_scenario_pack()
    test_control_state_rendering()
    test_stage_round_trip()
    test_scenario_integrity()
    print(json.dumps({"status": "PASS", "tests": 8}))


if __name__ == "__main__":
    main()