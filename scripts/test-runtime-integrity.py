#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent


def load_script(name: str, filename: str) -> Any:
    path = SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


paste = load_script("paste_alignment", "paste-alignment-audit.py")
scenario = load_script("scenario_integrity", "scenario-integrity-audit.py")


class FakeAuditor:
    @staticmethod
    def base(state: str) -> str:
        return state.split("[", 1)[0]


def prove_worldedit_offset_translation() -> None:
    assert paste.effective_min_corner(7, 6, 0, -17) == (7, 5)
    assert paste.paste_point_for_min_corner(7, 5, 0, -17) == (7, 6)
    for x in range(16):
        for z in range(16):
            effective = paste.effective_min_corner(x, z, 3, -5)
            restored = paste.paste_point_for_min_corner(*effective, 3, -5)
            assert restored == (x, z), (x, z, effective, restored)

    model = {
        "format": "sponge-v2",
        "data_version": 3465,
        "source_dimensions": {"width": 18, "height": 1, "length": 1},
        "offset": [0, 0, 0],
        "metadata": {"WEOffsetX": 0, "WEOffsetY": -1, "WEOffsetZ": -17},
        "blocks": {
            (0, 0, 0): "minecraft:dispenser[facing=north]",
            (17, 0, 0): "minecraft:dispenser[facing=north]",
        },
        "block_entities": [
            {"pos": (0, 0, 0), "id": "minecraft:dispenser"},
            {"pos": (17, 0, 0), "id": "minecraft:dispenser"},
        ],
    }
    report = paste.build_report(model, FakeAuditor(), Path("probe.schem"), 1, None)
    minimum = report["dispensers"]["minimum_corner_alignment"]
    player = report["dispensers"]["worldedit_paste_point_alignment"]
    assert minimum["safe_count"] == player["safe_count"], report
    safe_min = {
        (row["offset_x"], row["offset_z"])
        for row in minimum["safe_offsets"]
    }
    safe_player_as_min = {
        (row["effective_min_corner_x"], row["effective_min_corner_z"])
        for row in player["safe_offsets"]
    }
    assert safe_min == safe_player_as_min, report
    assert report["worldedit_metadata_offset"] == {"x": 0, "y": -1, "z": -17}
    assert report["warnings"], report

    impossible = dict(model)
    impossible["blocks"] = {
        (x, 0, 0): "minecraft:dispenser[facing=north]"
        for x in range(17)
    }
    impossible["block_entities"] = [
        {"pos": (x, 0, 0), "id": "minecraft:dispenser"}
        for x in range(17)
    ]
    impossible_report = paste.build_report(
        impossible,
        FakeAuditor(),
        Path("impossible.schem"),
        1,
        None,
    )
    assert impossible_report["status"] == "FAIL", impossible_report
    assert impossible_report["errors"], impossible_report


def prove_scenario_integrity_classification() -> None:
    assisted_text = """
name: guided-shot
cannon:
  file: example.schem
  fire-mode: button
limits:
  enforce-dispenser-limit: true
tracking:
  collision-guides:
    - {axis: z, coordinate: 12}
target:
  type: dry
  distance: 64
  layers: 1
acceptance:
  require-payload: false
  min-target-destroyed: 0
  min-forward-distance: 0
  min-remaining-dispenser-ratio: 0
  max-cannon-missing-blocks: 9999
  max-cannon-replaced-type-blocks: 9999
  max-self-damage-blocks: 9999
""".strip()
    values, sequences = scenario.minimal_yaml_paths(assisted_text)
    assisted = scenario.audit_scenario(
        values,
        sequences,
        assisted_text.encode(),
        Path("guided.yml"),
    )
    assert assisted["status"] == "DIAGNOSTIC", assisted
    assert assisted["field_candidate_eligible"] is False, assisted
    assert {item["code"] for item in assisted["assists"]} == {
        "external-collision-guides"
    }

    weak_text = assisted_text.replace(
        "tracking:\n  collision-guides:\n    - {axis: z, coordinate: 12}\n",
        "",
    )
    values, sequences = scenario.minimal_yaml_paths(weak_text)
    weak = scenario.audit_scenario(
        values,
        sequences,
        weak_text.encode(),
        Path("weak.yml"),
    )
    assert weak["status"] == "INCOMPLETE", weak
    assert weak["field_candidate_eligible"] is False, weak
    assert "payload-not-required" in {item["code"] for item in weak["warnings"]}

    blocked_text = assisted_text.replace(
        "enforce-dispenser-limit: true",
        "enforce-dispenser-limit: false",
    ).replace("  collision-guides:\n    - {axis: z, coordinate: 12}\n", "")
    values, sequences = scenario.minimal_yaml_paths(blocked_text)
    blocked = scenario.audit_scenario(
        values,
        sequences,
        blocked_text.encode(),
        Path("blocked.yml"),
    )
    assert blocked["status"] == "FAIL", blocked
    assert {item["code"] for item in blocked["blockers"]} == {
        "dispenser-limit-disabled"
    }

    strict_text = """
name: strict-candidate
cannon:
  file: example.schem
  fire-mode: button
limits:
  enforce-dispenser-limit: true
target:
  type: watered
  distance: 64
  layers: 4
acceptance:
  require-payload: true
  min-target-destroyed: 1
  min-forward-distance: 32
  min-remaining-dispenser-ratio: 0.99
  max-cannon-missing-blocks: 20
  max-cannon-replaced-type-blocks: 10
  max-self-damage-blocks: 20
""".strip()
    values, sequences = scenario.minimal_yaml_paths(strict_text)
    strict = scenario.audit_scenario(
        values,
        sequences,
        strict_text.encode(),
        Path("strict.yml"),
    )
    assert strict["status"] == "PASS", strict
    assert strict["field_candidate_eligible"] is True, strict
    assert strict["readiness_eligible"] is True, strict
    assert strict["warnings"] == [], strict

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "strict.yml"
        path.write_text(strict_text, encoding="utf-8")
        loaded_values, loaded_sequences, raw = scenario.load_scenario(path)
        round_trip = scenario.audit_scenario(
            loaded_values,
            loaded_sequences,
            raw,
            path,
        )
        assert round_trip["readiness_eligible"] is True, json.dumps(round_trip, indent=2)


def prove_local_runner_fails_closed() -> None:
    runner = (SCRIPTS / "run-lab.ps1").read_text(encoding="utf-8")
    assert "Remove-Item $ResultsRoot -Recurse -Force" in runner, runner
    assert "'server.jar'" in runner, runner
    assert "Run summary scenario mismatch" in runner, runner
    assert "Run summary predates this launch" in runner, runner
    assert "$Process.WaitForExit()" in runner, runner
    assert "$ServerExitCode -ne 0" in runner, runner
    assert "-Dcannonlab.fresh-world=" in runner, runner

    cloud = (SCRIPTS / "cloud-smoke.sh").read_text(encoding="utf-8")
    assert "scenario-integrity-audit.py" in cloud, cloud
    assert "-Dcannonlab.fresh-world=true" in cloud, cloud


def prove_java_runtime_contract_is_wired() -> None:
    java_root = SCRIPTS.parent / "src" / "main" / "java" / "io" / "github" \
        / "redzicdenis08afk" / "cannonlab"
    scenario_source = (java_root / "LabScenario.java").read_text(encoding="utf-8")
    controller_source = (java_root / "LabRunController.java").read_text(encoding="utf-8")
    recorder_source = (java_root / "ShotRecorder.java").read_text(encoding="utf-8")

    for path in (
        "acceptance.require-payload",
        "acceptance.min-target-destroyed",
        "acceptance.min-forward-distance",
        "acceptance.min-remaining-dispenser-ratio",
        "acceptance.max-cannon-missing-blocks",
        "acceptance.max-cannon-replaced-type-blocks",
        "acceptance.max-self-damage-blocks",
    ):
        assert path in scenario_source, path
    assert "record AcceptanceConfig" in scenario_source, scenario_source
    assert 'finishRun(contractPass ? "complete" : "contract_failed")' in controller_source
    assert "writeIntegrityDiff" in controller_source
    assert '"contract_failures"' in controller_source
    assert "maximumForwardDistance" in recorder_source
    assert "minimumForwardDistance" in recorder_source


def main() -> None:
    prove_worldedit_offset_translation()
    prove_scenario_integrity_classification()
    prove_local_runner_fails_closed()
    prove_java_runtime_contract_is_wired()
    print("WorldEdit paste offsets and scenario evidence gates fail closed as intended.")


if __name__ == "__main__":
    main()
