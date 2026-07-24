#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "scripts" / "scenario-integrity-audit.py"


def load_audit_module():
    spec = importlib.util.spec_from_file_location("cannonlab_scenario_integrity", AUDIT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {AUDIT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report_for(module, text: str):
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "scenario.yml"
        path.write_text(text, encoding="utf-8")
        values, sequences, raw = module.load_scenario(path)
        return module.audit_scenario(values, sequences, raw, path)


def main() -> int:
    module = load_audit_module()
    valid = report_for(module, """
name: valid-control-state
cannon:
  file: probe-button-field.schem
  fire-mode: button
  control-states:
    - name: mode
      at: {x: 2, y: 1, z: 1}
      phase: after-fill
      apply-tick: 2
      settle-ticks: 3
      apply-physics: false
      expected-before: minecraft:dispenser[facing=east,triggered=false]
      block-data: minecraft:dispenser[facing=east,triggered=true]
limits:
  enforce-dispenser-limit: true
target:
  type: dry
  distance: 5
  layers: 1
""")
    assert valid["control_state_count"] == 1, valid
    state = valid["control_states"][0]
    assert state["name"] == "mode" and state["phase"] == "after-fill", state
    assert state["apply_tick"] == 2 and state["settle_ticks"] == 3, state
    assert any(item["code"] == "control-state-physics-suppressed" for item in valid["assists"]), valid

    invalid = report_for(module, """
name: invalid-control-state
cannon:
  file: probe-button-field.schem
  control-states:
    - name: duplicate
      phase: sideways
      apply-tick: -1
      block-data: ''
    - name: duplicate
      settle-ticks: -2
      block-data: minecraft:lever[powered=true]
limits:
  enforce-dispenser-limit: true
target:
  type: dry
""")
    codes = {item["code"] for item in invalid["blockers"]}
    assert "invalid-control-state-phase" in codes, invalid
    assert "negative-control-state-timing" in codes, invalid
    assert "missing-control-state-block-data" in codes, invalid
    assert "duplicate-control-state-name" in codes, invalid

    print("Pre-fire control-state scenario audit tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
