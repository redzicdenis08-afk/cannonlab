#!/usr/bin/env python3
from __future__ import annotations

import importlib.util, json, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cannon-factory-budget.py"
SPEC = importlib.util.spec_from_file_location("cannon_factory_budget", SCRIPT)
assert SPEC and SPEC.loader
budget = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = budget
SPEC.loader.exec_module(budget)


def write_inputs(root: Path, count: int = 10) -> tuple[Path, Path]:
    candidates = []
    for index in range(count):
        candidate = root / f"v{index}.schem"
        candidate.write_bytes(f"candidate-{index}".encode())
        candidates.append({
            "variant_id": f"v{index:03d}",
            "static_score": 1000 - index,
            "result": {"output": {"path": str(candidate)}},
        })
    candidates.append({"variant_id": "failed", "static_score": None})
    search = {
        "schema": "cannonlab-variant-search-manifest-v1",
        "candidates": candidates,
    }
    forge = {
        "schema": "cannonlab-forge-job-v1",
        "execution_plan": {"tiers": [
            {"id": "smoke", "cumulative_shots": 1, "cumulative_scenarios": 1},
            {"id": "qualify", "cumulative_shots": 9, "cumulative_scenarios": 3},
            {"id": "full", "cumulative_shots": 54, "cumulative_scenarios": 6},
        ]},
    }
    search_path, forge_path = root / "search.json", root / "forge.json"
    search_path.write_text(json.dumps(search), encoding="utf-8")
    forge_path.write_text(json.dumps(forge), encoding="utf-8")
    return search_path, forge_path


def main() -> None:
    with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
        root = Path(temporary)
        search, forge = write_inputs(root)
        plan = budget.build(
            search, forge, budget=1800, workers=2, target="full",
            caps={"smoke": 16, "qualify": 4, "full": 1},
            shot=25, overhead=30, history=[],
        )
        assert plan["status"] == "PASS", plan
        assert plan["selected_counts"] == {"smoke": 10, "qualify": 2, "full": 1}, plan
        assert plan["estimated_wall_seconds"] == 1750, plan
        assert plan["stages"][0]["candidates"][0]["variant_id"] == "v000", plan

        blocked = budget.build(
            search, forge, budget=900, workers=2, target="full",
            caps={"smoke": 16, "qualify": 4, "full": 1},
            shot=25, overhead=30, history=[],
        )
        assert blocked["status"] == "BLOCKED", blocked
        assert "runtime-budget-insufficient" in {row["code"] for row in blocked["blockers"]}

        history = root / "smoke-history.json"
        history.write_text(json.dumps({
            "status": "PASS", "max_tier": "smoke", "selected_scenarios": 1,
            "executed_count": 1, "skipped_count": 0, "elapsed_seconds": 12,
        }), encoding="utf-8")
        learned = budget.history_costs([history])
        assert learned == {"smoke": 12}, learned

        try:
            budget.build(
                search, forge, budget=1800, workers=2, target="full",
                caps={"smoke": -1, "qualify": 4, "full": 1},
                shot=25, overhead=30, history=[],
            )
        except ValueError as exc:
            assert "caps" in str(exc)
        else:
            raise AssertionError("negative candidate caps must fail closed")

    print(json.dumps({"status": "PASS", "tests": 4}))


if __name__ == "__main__":
    main()
