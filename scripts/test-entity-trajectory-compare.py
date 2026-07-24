#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("compare-entity-trajectories.py")
HEADER = "tick,event,type,uuid,x,y,z,vx,vy,vz,fuse,affected_blocks\n"


def write_trace(path: Path, *, shift: float, drift: bool) -> None:
    rows = [
        f"10,ENTITY,TNT,tnt,{1 + shift},64,1,0.1,0.2,0.0,79,0",
        f"11,ENTITY,TNT,tnt,{1.1 + shift},64.2,1,0.1,0.16,0.0,78,0",
        (
            f"12,ENTITY,TNT,tnt,{1.7 + shift},64.36,1,0.6,0.12,0.0,77,0"
            if drift
            else f"12,ENTITY,TNT,tnt,{1.2 + shift},64.36,1,0.1,0.12,0.0,77,0"
        ),
        f"12,EXPLOSION,TNT,blast,{2 + shift},64,2,0,0,0,-1,8",
        (
            f"89,EXPLOSION,TNT,tnt,{4.5 + shift},63,2,0,0,0,-1,12"
            if drift
            else f"89,EXPLOSION,TNT,tnt,{4 + shift},63,2,0,0,0,-1,12"
        ),
    ]
    path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")


def invoke(reference: Path, candidate: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(reference),
            str(candidate),
            "--reference-uuid",
            "tnt",
            "--candidate-uuid",
            "tnt",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        reference = root / "reference.csv"
        translated = root / "translated.csv"
        drifted = root / "drifted.csv"
        write_trace(reference, shift=0.0, drift=False)
        write_trace(translated, shift=5.0, drift=False)
        write_trace(drifted, shift=5.0, drift=True)

        pass_code, pass_report = invoke(reference, translated)
        assert pass_code == 0, pass_report
        assert pass_report["status"] == "PASS", pass_report
        assert pass_report["normalization"]["translation"] == [5.0, 0.0, 0.0]
        assert pass_report["summary"]["first_divergence"] is None

        fail_code, fail_report = invoke(reference, drifted)
        assert fail_code == 2, fail_report
        assert fail_report["status"] == "FAIL", fail_report
        first = fail_report["summary"]["first_divergence"]
        assert first["age"] == 2, fail_report
        assert first["velocity_delta"] > 0.49, fail_report
        assert fail_report["explosion"]["position_delta"] == 0.5, fail_report
        assert fail_report["divergence_context"] is not None, fail_report

    print(
        "Entity trajectory comparison translation-normalizes exact clones and pinpoints "
        "the first position/velocity divergence with nearby explosion context."
    )


if __name__ == "__main__":
    main()
