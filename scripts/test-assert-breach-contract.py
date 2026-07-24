#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("assert-results.py")


def write_run(root: Path, *, embedded: int, unembedded: int, layers: int, all_layers: bool) -> Path:
    run = root / "run"
    shot = run / "shot-001"
    shot.mkdir(parents=True)
    summary = {
        "finish_reason": "complete",
        "shots_requested": 1,
        "shots_completed": 1,
        "scenario": "synthetic-assert-breach",
        "cannon_file": "synthetic.schem",
        "target_type": "WATERED",
        "target_direction": "EAST",
        "target_bounds": {
            "min_x": 2,
            "min_y": 63,
            "min_z": 1,
            "max_x": 3,
            "max_y": 65,
            "max_z": 3,
        },
        "regeneration": {"enabled": True},
        "shots": [
            {
                "shot": 1,
                "finish_reason": "quiet",
                "saw_payload": True,
                "explosions": 1,
                "maximum_tnt_entities": 1,
                "target_peak_destroyed": 3,
                "regen_blocks_restored": 1,
                "max_layer_breached": 3,
                "embedded_payload_explosions": embedded,
                "unembedded_water_explosions": unembedded,
                "contiguous_layers_breached_before_first_regen": layers,
                "all_layers_breached_before_first_regen": all_layers,
                "regen_race_margin_ticks": 4 if all_layers else -1,
                "self_damage_blocks": 0,
                "durability_hits": 0,
                "durability_breaks": 0,
                "companion_cells_missing": 0,
                "companion_cells_restored": 0,
                "error": None,
            }
        ],
    }
    (run / "run-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (shot / "events.csv").write_text(
        "tick,event,type,uuid,x,y,z,vx,vy,vz,fuse,affected_blocks\n"
        "0,ENTITY,TNT,tnt,0,64,2,1,0,0,2,0\n"
        "1,ENTITY,TNT,tnt,1,64,2,1,0,0,1,0\n"
        "2,EXPLOSION,TNT,tnt,2,64,2,0,0,0,-1,3\n",
        encoding="utf-8",
    )
    return root


def invoke(results: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(results),
            "--expected-shots",
            "1",
            "--min-embedded-payload-explosions",
            "1",
            "--max-unembedded-water-explosions",
            "0",
            "--min-contiguous-layers-before-first-regen",
            "3",
            "--require-all-layers-before-first-regen",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        pass_code, pass_report = invoke(
            write_run(root / "pass", embedded=1, unembedded=0, layers=3, all_layers=True)
        )
        assert pass_code == 0, pass_report
        assert pass_report["status"] == "PASS", pass_report
        assert pass_report["embedded_payload_explosions"]["min"] == 1
        assert pass_report["regen_race_margin_ticks"]["min"] == 4

        fail_code, fail_report = invoke(
            write_run(root / "fail", embedded=0, unembedded=1, layers=2, all_layers=False)
        )
        assert fail_code == 1, fail_report
        assert fail_report["status"] == "FAIL", fail_report
        errors = "\n".join(fail_report["errors"])
        assert "embedded_payload_explosions=0 below 1" in errors, fail_report
        assert "unembedded_water_explosions=1 above 0" in errors, fail_report
        assert "contiguous_layers_breached_before_first_regen=2 below 3" in errors, fail_report
        assert "all_layers_breached_before_first_regen=false" in errors, fail_report

    print("assert-results enforces hybrid-overlap and regen-race contracts fail closed.")


if __name__ == "__main__":
    main()
