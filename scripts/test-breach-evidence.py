#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("analyze-breach-evidence.py")


def write_run(
    root: Path,
    *,
    overlap: bool,
    water_contact: bool = True,
    target_contact: bool = True,
    include_csv: bool = True,
    contiguous_layers: int = 3,
    target_layers: int = 3,
    all_layers: bool = True,
) -> Path:
    run = root / "run"
    shot = run / "shot-001"
    shot.mkdir(parents=True)
    summary = {
        "scenario": "synthetic-breach-contract",
        "shots": [
            {
                "shot": 1,
                "embedded_payload_explosions": (
                    1 if overlap and water_contact and target_contact else 0
                ),
                "water_contact_explosions": 1 if water_contact and target_contact else 0,
                "unembedded_water_explosions": (
                    1 if water_contact and target_contact and not overlap else 0
                ),
                "first_target_damage_tick": 40,
                "first_regen_restore_tick": 60,
                "layers_breached_before_first_regen": contiguous_layers,
                "contiguous_layers_breached_before_first_regen": contiguous_layers,
                "max_layer_breached_before_first_regen": contiguous_layers,
                "target_layer_count": target_layers,
                "all_layers_breached_before_first_regen": all_layers,
                "all_layers_breached_tick": 55 if all_layers else -1,
                "regen_race_margin_ticks": 5 if all_layers else -1,
            }
        ],
    }
    (run / "run-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    if include_csv:
        (shot / "breach-events.csv").write_text(
            "tick,event,entity_uuid,entity_type,x,y,z,target_contact,center_block,center_water_contact,"
            "falling_overlap_evidence,falling_uuid,falling_material,"
            "falling_distance,affected_blocks\n"
            f"55,EXPLOSION,tnt,PRIMED_TNT,10,64,10,{str(target_contact).lower()},"
            f"{'WATER' if water_contact else 'AIR'},{str(water_contact).lower()},"
            f"{str(overlap).lower()},"
            f"sand,SAND,{0.2 if overlap else -1.0},4\n",
            encoding="utf-8",
        )
    return run


def invoke(run: Path, *extra: str) -> tuple[int, dict]:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(run),
            "--min-embedded-payload-explosions",
            "1",
            "--max-unembedded-water-explosions",
            "0",
            "--min-contiguous-layers-before-first-regen",
            "3",
            "--require-all-layers-before-first-regen",
            *extra,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


def invoke_impact_only(run: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(run),
            "--min-embedded-payload-explosions",
            "1",
            "--max-unembedded-water-explosions",
            "0",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


def invoke_regen_only(run: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(run),
            "--min-embedded-payload-explosions",
            "0",
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
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)

        pass_code, pass_report = invoke(write_run(root / "pass", overlap=True))
        assert pass_code == 0, pass_report
        assert pass_report["status"] == "PASS", pass_report
        shot = pass_report["shots"][0]
        assert shot["explosion_evidence"]["embedded_payload_explosions"] == 1
        assert shot["regen_race"]["regen_race_margin_ticks"] == 5

        impact_code, impact_report = invoke_impact_only(
            write_run(
                root / "impact-only",
                overlap=True,
                contiguous_layers=0,
                target_layers=1,
                all_layers=False,
            )
        )
        assert impact_code == 0, impact_report
        assert impact_report["status"] == "PASS", impact_report
        assert (
            impact_report["thresholds"][
                "min_contiguous_layers_before_first_regen"
            ]
            == 0
        ), impact_report

        regen_code, regen_report = invoke_regen_only(
            write_run(root / "regen-only", overlap=True, target_contact=False)
        )
        assert regen_code == 0, regen_report
        assert regen_report["status"] == "PASS", regen_report

        fail_code, fail_report = invoke(write_run(root / "fail", overlap=False))
        assert fail_code == 2, fail_report
        assert fail_report["status"] == "FAIL", fail_report
        joined = "\n".join(fail_report["failures"])
        assert "embedded_payload_explosions=0<1" in joined, fail_report
        assert "unembedded_water_explosions=1>0" in joined, fail_report

        dry_code, dry_report = invoke(
            write_run(root / "dry-overlap", overlap=True, water_contact=False)
        )
        assert dry_code == 2, dry_report
        assert dry_report["status"] == "FAIL", dry_report
        assert "embedded_payload_explosions=0<1" in "\n".join(
            dry_report["failures"]
        ), dry_report

        internal_code, internal_report = invoke(
            write_run(
                root / "internal-water",
                overlap=True,
                water_contact=True,
                target_contact=False,
            )
        )
        assert internal_code == 2, internal_report
        internal_failures = "\n".join(internal_report["failures"])
        assert "target_tnt_breach_events_missing" in internal_failures, internal_report
        assert "embedded_payload_explosions=0<1" in internal_failures, internal_report

        missing_code, missing_report = invoke(
            write_run(root / "missing", overlap=True, include_csv=False)
        )
        assert missing_code == 2, missing_report
        assert "breach_events_missing" in "\n".join(missing_report["failures"])

    print(
        "Breach evidence audit passes measured falling-payload overlap and regen-race "
        "evidence, ignores internal-water overlap, rejects dry-only overlap and unembedded "
        "water explosions, and fails closed on missing telemetry."
    )


if __name__ == "__main__":
    main()
