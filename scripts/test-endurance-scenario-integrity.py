#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).with_name("scenario-integrity-audit.py")


def load_module() -> Any:
    spec = importlib.util.spec_from_file_location("scenario_integrity", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit(module: Any, text: str, name: str) -> dict:
    values, sequences = module.minimal_yaml_paths(text)
    return module.audit_scenario(values, sequences, text.encode(), Path(name))


def scenario(lifecycle_line: str) -> str:
    return f"""
name: probe-redstone-endurance
cannon:
  file: probe.schem
  fire-mode: redstone
limits:
  enforce-dispenser-limit: true
target:
  type: dry
  distance: 32
  layers: 1
acceptance:
  require-payload: true
  min-target-destroyed: 1
  min-forward-distance: 1
  min-remaining-dispenser-ratio: 1.0
  max-cannon-missing-blocks: 0
  max-cannon-replaced-type-blocks: 0
  max-cannon-unexpected-blocks: 0
  max-self-damage-blocks: 0
run:
  shots: 100
{lifecycle_line}
""".strip()


def main() -> None:
    module = load_module()

    implicit = audit(module, scenario(""), "implicit.yml")
    implicit_codes = {item["code"] for item in implicit["warnings"]}
    blocker_codes = {item["code"] for item in implicit["blockers"]}
    assert "multi-shot-lifecycle-implicit" in implicit_codes, implicit
    assert "endurance-rebuilds-cannon" in blocker_codes, implicit
    assert implicit["status"] == "FAIL", implicit

    rebuilt = audit(
        module,
        scenario("  rebuild-cannon-between-shots: true"),
        "rebuilt.yml",
    )
    blocker_codes = {item["code"] for item in rebuilt["blockers"]}
    assert "endurance-rebuilds-cannon" in blocker_codes, rebuilt
    assert rebuilt["cannon_lifecycle"] == "REBUILD_EACH_SHOT", rebuilt

    cumulative = audit(
        module,
        scenario("  rebuild-cannon-between-shots: false"),
        "cumulative.yml",
    )
    blocker_codes = {item["code"] for item in cumulative["blockers"]}
    warning_codes = {item["code"] for item in cumulative["warnings"]}
    assert "endurance-rebuilds-cannon" not in blocker_codes, cumulative
    assert "multi-shot-lifecycle-implicit" not in warning_codes, cumulative
    assert cumulative["cannon_lifecycle"] == "PRESERVE_ACROSS_SHOTS", cumulative
    assert cumulative["rebuild_cannon_between_shots"] is False, cumulative

    print(
        "Scenario integrity rejects endurance labels backed by fresh rebuilds and "
        "recognizes explicit preserve-across-shots lifecycle evidence."
    )


if __name__ == "__main__":
    main()
