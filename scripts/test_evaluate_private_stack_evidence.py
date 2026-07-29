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

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "evidence.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in confirmed_rows()) + "\n", encoding="utf-8")
        assert len(evaluator.read_rows(path)) == 9

    print("Private-stack evidence evaluator regressions passed: 4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())