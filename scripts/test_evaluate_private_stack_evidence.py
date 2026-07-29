#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import evaluate_private_stack_evidence as evaluator


def snapshot(label: str, xp: float, *, item: str = "DIAMOND_SWORDx1", fragility: int = 1):
    return {
        "type": "snapshot",
        "label": label,
        "attacker_enchanting_xp": xp,
        "grindstone_input_0": item,
        "grindstone_input_fragility": fragility,
    }


def click(cancelled: bool, xp: float):
    return {
        "type": "grindstone_result_click",
        "cancelled": cancelled,
        "enchanting_xp_monitor": xp,
    }


def confirmed_rows():
    rows = []
    xp = 0.0
    for run in range(1, 4):
        rows.append(snapshot(f"grindstone-before-{run}", xp))
        xp += 12.0
        rows.append(click(True, xp))
        rows.append(snapshot(f"grindstone-after-{run}", xp))
    return rows


def confirmed_terraform_rows():
    rows = []
    for run in range(1, 4):
        rows.append({
            "type": "snapshot",
            "label": f"aura-terraform-before-{run}",
            "terraform_target_1": "DIRT",
            "terraform_target_2": "DIRT",
            "terraform_target_3": "DIRT",
        })
        rows.append({
            "type": "snapshot",
            "label": f"aura-terraform-after-{run}",
            "terraform_target_1": "AIR",
            "terraform_target_2": "AIR",
            "terraform_target_3": "AIR",
        })
    return rows


def main() -> int:
    finding = evaluator.grindstone_xp(confirmed_rows())
    assert finding["status"] == "confirmed", finding
    assert finding["evidence"]["confirmed_attempts"] == 3, finding

    no_persistence = confirmed_rows()
    no_persistence[-1]["grindstone_input_0"] = "AIR"
    no_persistence[-1]["grindstone_input_fragility"] = 0
    finding = evaluator.grindstone_xp(no_persistence)
    assert finding["status"] == "inconclusive", finding

    rejected = []
    for run in range(1, 4):
        rejected.append(snapshot(f"grindstone-before-{run}", 0.0))
        rejected.append(click(True, 0.0))
        rejected.append(snapshot(f"grindstone-after-{run}", 0.0))
    finding = evaluator.grindstone_xp(rejected)
    assert finding["status"] == "rejected", finding

    finding = evaluator.aura_terraform(confirmed_terraform_rows())
    assert finding["status"] == "confirmed", finding
    assert finding["evidence"]["confirmed_attempts"] == 3, finding

    alchemy_rows = [
        *[
            {
                "type": "brew_event",
                "cancelled": False,
            }
            for _ in range(5)
        ],
        {
            "type": "snapshot",
            "label": "alchemy-before-take",
            "attacker_alchemy_xp": 0.0,
            "alchemy_chest_potions": 15,
        },
        {
            "type": "alchemy_result_click",
            "slot": 0,
            "alchemy_xp_monitor": 50.0,
        },
        {
            "type": "snapshot",
            "label": "alchemy-after-take",
            "attacker_alchemy_xp": 50.0,
            "alchemy_chest_potions": 15,
        },
    ]
    finding = evaluator.alchemy_amplifier(alchemy_rows)
    assert finding["status"] == "confirmed", finding
    assert finding["evidence"]["xp_gain"] == 50.0, finding

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "evidence.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in confirmed_rows()) + "\n", encoding="utf-8")
        assert len(evaluator.read_rows(path)) == 9

    print("Private-stack evidence evaluator regressions passed: 6")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())