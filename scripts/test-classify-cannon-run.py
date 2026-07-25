#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import sys
from pathlib import Path


def load_module():
    path = Path(__file__).with_name("classify-cannon-run.py")
    spec = importlib.util.spec_from_file_location("classify_cannon_run", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_fixture(root: Path, *, payload_z: float, sand_max_x: float, self_damage: int = 0) -> Path:
    run_dir = root / "run"
    shot_dir = run_dir / "shot-001"
    shot_dir.mkdir(parents=True)
    summary = {
        "run_id": "fixture",
        "scenario": "fixture",
        "cannon_file": "fixture.schem",
        "target_direction": "EAST",
        "target_bounds": {"min_x": 20, "max_x": 21, "min_y": 100, "max_y": 100, "min_z": 0, "max_z": 0},
        "arena_origin": {"x": 0, "y": 100, "z": 0},
        "durability": {"effective_mode": "SIMULATE"},
        "acceptance": {"max_self_damage_blocks": 0},
        "shots": [{
            "shot": 1,
            "contract_pass": payload_z == 0 and sand_max_x >= 20 and self_damage == 0,
            "target_peak_destroyed": 1 if payload_z == 0 and sand_max_x >= 20 else 0,
            "target_ever_destroyed": 1 if payload_z == 0 and sand_max_x >= 20 else 0,
            "durability_hits": 1 if payload_z == 0 and sand_max_x >= 20 else 0,
            "self_damage_blocks": self_damage,
            "cannon_initial_blocks": 100,
            "cannon_initial_dispensers": 3,
            "cannon_remaining_dispensers": 3 if self_damage == 0 else 2,
        }],
    }
    (run_dir / "run-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    rows = [
        "tick,event,type,uuid,x,y,z,vx,vy,vz,fuse,affected_blocks",
        "0,ENTITY,TNT,c1,5,100,0,0,0,0,79,0",
        "0,ENTITY,TNT,c2,6,100,0,0,0,0,79,0",
        "5,ENTITY,TNT,p1,8,100,0,0,0,0,79,0",
        f"8,ENTITY,TNT,p1,20.5,100,{payload_z},0,0,0,76,0",
        f"8,EXPLOSION,TNT,p1,20.5,100,{payload_z},0,0,0,-1,1",
        "6,ENTITY,FALLING_BLOCK,s1,8,100,0,0,0,0,-1,0",
        f"8,ENTITY,FALLING_BLOCK,s1,{sand_max_x},100,0,0,0,0,-1,0",
    ]
    (shot_dir / "events.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return run_dir / "run-summary.json"


def main() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        passed = module._classify_one(write_fixture(root / "pass", payload_z=0, sand_max_x=20.5), 2.0, 1.5, 1)
        assert passed["overall_status"] == "PASS", passed
        assert passed["shots"][0]["failures"] == []

        lane = module._classify_one(write_fixture(root / "lane", payload_z=8, sand_max_x=20.5), 2.0, 1.5, 1)
        assert lane["shots"][0]["primary_failure"] == "PAYLOAD_LANE_DIVERGENCE", lane

        sand = module._classify_one(write_fixture(root / "sand", payload_z=0, sand_max_x=12), 2.0, 1.5, 1)
        assert "SAND_RANGE_SHORT" in sand["shots"][0]["failures"], sand

        damage = module._classify_one(write_fixture(root / "damage", payload_z=0, sand_max_x=20.5, self_damage=10), 2.0, 1.5, 1)
        assert "CANNON_SELF_DAMAGE" in damage["shots"][0]["failures"], damage

    print("classify-cannon-run: 4 regression groups passed")


if __name__ == "__main__":
    main()
