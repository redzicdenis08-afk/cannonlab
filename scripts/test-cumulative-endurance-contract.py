#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("assert-results.py")


def write_run(
    root: Path,
    *,
    lifecycle: str,
    rebuild_between_shots: bool,
    pastes: int,
    rebuilt_flags: list[bool],
) -> Path:
    run = root / "run"
    run.mkdir(parents=True)
    shots = []
    for number, rebuilt in enumerate(rebuilt_flags, start=1):
        shot_dir = run / f"shot-{number:03d}"
        shot_dir.mkdir()
        uid = f"tnt-{number}"
        (shot_dir / "events.csv").write_text(
            "tick,event,type,uuid,x,y,z,vx,vy,vz,fuse\n"
            f"0,ENTITY,TNT,{uid},0,64,0,0,0,0,1\n"
            f"1,EXPLOSION,TNT,{uid},0,64,0,0,0,0,0\n",
            encoding="utf-8",
        )
        shots.append(
            {
                "shot": number,
                "cannon_rebuilt_before_shot": rebuilt,
                "finish_reason": "quiet",
                "saw_payload": True,
                "explosions": 1,
                "maximum_tnt_entities": 1,
                "maximum_falling_blocks": 0,
                "self_damage_blocks": 0,
                "target_peak_destroyed": 0,
                "regen_blocks_restored": 0,
                "max_layer_breached": 0,
                "embedded_payload_explosions": 0,
                "unembedded_water_explosions": 0,
                "contiguous_layers_breached_before_first_regen": 0,
                "all_layers_breached_before_first_regen": False,
                "regen_race_margin_ticks": -1,
                "durability_hits": 0,
                "durability_breaks": 0,
                "companion_cells_missing": 0,
                "companion_cells_restored": 0,
                "error": None,
            }
        )
    summary = {
        "finish_reason": "complete",
        "scenario": "synthetic-endurance",
        "cannon_file": "probe.schem",
        "cannon_lifecycle": lifecycle,
        "rebuild_cannon_between_shots": rebuild_between_shots,
        "cannon_pastes_performed": pastes,
        "target_type": "DRY",
        "target_direction": "EAST",
        "target_bounds": {
            "min_x": 10,
            "min_y": 60,
            "min_z": -1,
            "max_x": 10,
            "max_y": 70,
            "max_z": 1,
        },
        "shots_requested": len(shots),
        "shots_completed": len(shots),
        "regeneration": {"enabled": False},
        "shots": shots,
    }
    (run / "run-summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )
    return run


def invoke(
    run: Path,
    *,
    require_cumulative: bool,
    max_unexpected: int | None = None,
) -> tuple[int, dict]:
    args = [
        sys.executable,
        str(SCRIPT),
        str(run),
        "--expected-shots",
        "3",
        "--min-tnt-per-shot",
        "1",
        "--min-explosions-per-shot",
        "1",
    ]
    if require_cumulative:
        args.append("--require-cumulative-cannon")
    if max_unexpected is not None:
        args += ["--max-cannon-unexpected-blocks", str(max_unexpected)]
    completed = subprocess.run(
        args,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)

        good = write_run(
            root / "good",
            lifecycle="PRESERVE_ACROSS_SHOTS",
            rebuild_between_shots=False,
            pastes=1,
            rebuilt_flags=[True, False, False],
        )
        code, report = invoke(good, require_cumulative=True)
        assert code == 0, report
        assert report["status"] == "PASS", report
        assert report["cannon_pastes_performed"] == 1, report

        rebuilt = write_run(
            root / "rebuilt",
            lifecycle="REBUILD_EACH_SHOT",
            rebuild_between_shots=True,
            pastes=3,
            rebuilt_flags=[True, True, True],
        )
        code, report = invoke(rebuilt, require_cumulative=True)
        assert code == 1, report
        assert "expected='PRESERVE_ACROSS_SHOTS'" in "\n".join(report["errors"]), report

        forged_pastes = write_run(
            root / "forged-pastes",
            lifecycle="PRESERVE_ACROSS_SHOTS",
            rebuild_between_shots=False,
            pastes=3,
            rebuilt_flags=[True, False, False],
        )
        code, report = invoke(forged_pastes, require_cumulative=True)
        assert code == 1, report
        assert "reported 3 cannon pastes" in "\n".join(report["errors"]), report

        hidden_rebuild = write_run(
            root / "hidden-rebuild",
            lifecycle="PRESERVE_ACROSS_SHOTS",
            rebuild_between_shots=False,
            pastes=1,
            rebuilt_flags=[True, True, False],
        )
        code, report = invoke(hidden_rebuild, require_cumulative=True)
        assert code == 1, report
        assert "shot 2: cannon_rebuilt_before_shot=True" in "\n".join(
            report["errors"]
        ), report

        code, report = invoke(rebuilt, require_cumulative=False)
        assert code == 0, report
        assert report["status"] == "PASS", report

        unexpected = write_run(
            root / "unexpected",
            lifecycle="PRESERVE_ACROSS_SHOTS",
            rebuild_between_shots=False,
            pastes=1,
            rebuilt_flags=[True, False, False],
        )
        summary_path = unexpected / "run-summary.json"
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        payload["shots"][1]["cannon_unexpected_blocks"] = 1
        summary_path.write_text(json.dumps(payload), encoding="utf-8")
        code, report = invoke(
            unexpected,
            require_cumulative=True,
            max_unexpected=0,
        )
        assert code == 1, report
        assert "cannon_unexpected_blocks=1 above 0" in "\n".join(
            report["errors"]
        ), report

    print(
        "Cumulative endurance accepts one initial paste plus preserved later shots and "
        "rejects fresh-paste reliability, forged paste counts, hidden rebuilds, and "
        "unexpected blocks in originally-air cannon cells."
    )


if __name__ == "__main__":
    main()
