#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parity = load("parity_planner", "plan-cannon-parity-campaign.py")
    modules = load("module_planner", "plan-cannon-module-campaign.py")

    public = {"id": "sakura-26.1.2-cannon-contract"}
    private = {
        "id": "extremecraft-private-parity-required-v1",
        "dimensions": [
            {"id": "a", "status": "unknown", "canary": "A", "hypotheses": ["x"], "required_evidence": ["trace"]},
            {"id": "b", "status": "field-verified", "canary": "B", "hypotheses": ["y"], "required_evidence": ["trace"]},
        ],
        "promotion_gate": {"minimum_repeat_count_per_stochastic_dimension": 100},
    }
    catalog = {
        "id": "extremecraft-parity-probe-priorities-v1",
        "probes": [
            {"dimension": "a", "priority": 100, "risk": "safe", "phase": "one", "public_probe": "pa", "public_baseline": "ba", "minimum_repeats": 3, "paired_comparison": "ca"},
            {"dimension": "b", "priority": 50, "risk": "controlled-destructive", "phase": "two", "public_probe": "pb", "public_baseline": "bb", "minimum_repeats": 2, "paired_comparison": "cb"}
        ]
    }
    plan = parity.build_plan(public, private, catalog, "safe")
    assert [row["dimension"] for row in plan["stages"]] == ["a", "b"], plan
    assert plan["stages"][0]["action"] == "MEASURE", plan
    assert plan["stages"][1]["action"] == "REUSE_EVIDENCE", plan
    assert plan["truth_boundary"]["plan_is_measurement"] is False

    grammar = json.loads((ROOT / "profiles/grammar/modern-factions-cannon-grammar-v1.json").read_text(encoding="utf-8"))
    request = {
        "id": "fixture",
        "target_modules": ["one-shot-cycle", "guider-realignment"],
        "desired_level": "LOCAL_CAUSAL",
        "available_evidence": {"charge-force": "LOCAL_CAUSAL"},
        "constraints": {"minimum_clear_flight_blocks": 20}
    }
    campaign = modules.build_campaign(grammar, request)
    order = [row["module"] for row in campaign["stages"]]
    for required in ("charge-force", "payload", "sand-release", "hammer", "hybrid-fusion", "slab-bust", "one-shot-cycle", "guider-realignment"):
        assert required in order, (required, order)
    assert order.index("charge-force") < order.index("payload") < order.index("one-shot-cycle"), order
    charge = next(row for row in campaign["stages"] if row["module"] == "charge-force")
    assert charge["action"] == "REUSE_EVIDENCE", charge
    assert campaign["prove_count"] == campaign["stage_count"] - 1, campaign

    broken = json.loads(json.dumps(grammar))
    broken["modules"][0]["requires"] = [broken["modules"][0]["id"]]
    try:
        modules.build_campaign(broken, {"target_modules": [broken["modules"][0]["id"]]})
    except modules.CampaignError as exc:
        assert "cycle" in str(exc), exc
    else:
        raise AssertionError("dependency cycle unexpectedly passed")

    print("cannon parity planners: 3 regression groups passed")


if __name__ == "__main__":
    main()
