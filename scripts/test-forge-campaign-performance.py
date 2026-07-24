#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run-forge-campaign.ps1"


def powershell() -> str:
    return "powershell" if sys.platform.startswith("win") else "pwsh"


def manifest() -> dict:
    scenarios = []
    layout = [
        ("smoke-gate", "smoke", 0, 1),
        ("dry-baseline", "qualify", 1, 3),
        ("watered-payload", "qualify", 1, 5),
        ("regen-race", "full", 2, 10),
        ("mixed-gauntlet", "full", 2, 10),
        ("endurance", "full", 2, 25),
    ]
    for name, tier, rank, shots in layout:
        scenarios.append({
            "name": f"forge-performance-{name}",
            "path": f"scenarios/{name}.yml",
            "sha256": f"sha-{name}",
            "expected_shots": shots,
            "tier": tier,
            "tier_rank": rank,
            "assert_args": ["--expected-shots", str(shots)],
            "corridor_args": [],
            "wall_breach_args": [],
            "integrity": {"status": "PASS"},
        })
    return {
        "schema": "cannonlab-forge-job-v1",
        "job": "performance-contract",
        "status": "PASS",
        "candidate": {"sha256": "candidate-sha"},
        "configuration": {"intent": "calibration"},
        "scenarios": scenarios,
    }


def plan(manifest_path: Path, tier: str) -> dict:
    relative = manifest_path.relative_to(ROOT)
    completed = subprocess.run([
        powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(RUNNER),
        "-Manifest", str(relative), "-MaxTier", tier, "-PlanOnly",
    ], cwd=ROOT, text=True, capture_output=True, check=False, timeout=60)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def main() -> None:
    with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
        path = Path(temporary) / "manifest.json"
        path.write_text(json.dumps(manifest()), encoding="utf-8")
        smoke = plan(path, "smoke")
        qualify = plan(path, "qualify")
        full = plan(path, "full")
        assert smoke["status"] == "PLANNED", smoke
        assert smoke["selected_scenarios"] == 1, smoke
        assert [item["tier"] for item in smoke["planned"]] == ["smoke"], smoke
        assert qualify["selected_scenarios"] == 3, qualify
        assert sum(item["expected_shots"] for item in qualify["planned"]) == 9, qualify
        assert full["selected_scenarios"] == 6, full
        assert sum(item["expected_shots"] for item in full["planned"]) == 54, full
        assert full["executed_count"] == 0, full
        assert full["failure_count"] == 0, full
        assert full["wall_clock_budget_seconds"] == 0, full
    print(json.dumps({"status": "PASS", "tests": 3}))


if __name__ == "__main__":
    main()
