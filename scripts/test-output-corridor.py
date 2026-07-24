#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze-output-corridor.py"


def load_module():
    spec = importlib.util.spec_from_file_location("cannonlab_output_corridor", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_run(
    root: Path,
    paths: list[list[tuple[int, float, float, float]]],
    direction: str = "EAST",
) -> Path:
    run = root / "run"
    run.mkdir(parents=True)
    (run / "run-summary.json").write_text(
        (
            '{"scenario":"corridor-fixture","cannon_file":"fixture.schem",'
            f'"target_direction":"{direction}"}}\n'
        ),
        encoding="utf-8",
    )
    for shot_number, samples in enumerate(paths, start=1):
        shot = run / f"shot-{shot_number:03d}"
        shot.mkdir()
        with (shot / "events.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["tick", "event", "type", "uuid", "x", "y", "z", "vx", "vy", "vz", "fuse", "affected_blocks"]
            )
            for tick, x, y, z in samples:
                writer.writerow([tick, "ENTITY", "TNT", f"shot-{shot_number}", x, y, z, 0, 0, 0, 80 - tick, 0])
    return run


def args_for(run: Path) -> argparse.Namespace:
    return argparse.Namespace(
        results=run,
        expected_direction=None,
        entity_type=["TNT", "FALLING_BLOCK"],
        min_shots=5,
        min_entities_per_shot=1,
        max_entity_details=100,
        min_forward=15.0,
        half_width=1.0,
        vertical_tolerance=1.0,
        max_abs_angle=3.0,
        max_angular_spread=3.0,
        max_forward_relative_spread=0.05,
        max_lateral_center_spread=0.8,
        json_out=None,
    )


def stable_paths() -> list[list[tuple[int, float, float, float]]]:
    paths = []
    for shot, lateral in enumerate((-0.20, -0.10, 0.0, 0.10, 0.20), start=1):
        paths.append(
            [
                (0, 0.0, 100.0, 0.0),
                (1, 10.0, 100.0, lateral / 2.0),
                (2, 20.0, 100.0, lateral),
            ]
        )
    return paths


def main() -> int:
    module = load_module()
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)

        stable = write_run(base / "stable", stable_paths())
        stable_report = module.build_report(args_for(stable))
        assert stable_report["status"] == "PASS", stable_report
        assert stable_report["dominant-output-direction"] == "EAST", stable_report
        assert stable_report["direction-repeatability"]["shots_observed"] == 5, stable_report
        assert stable_report["direction-repeatability"]["angular-spread"] < 3.0, stable_report
        assert stable_report["output-corridor"]["corridor_violations"] == 0, stable_report

        north_paths = [
            [(tick, z, y, -x) for tick, x, y, z in path]
            for path in stable_paths()
        ]
        north = write_run(base / "north", north_paths, direction="NORTH")
        north_report = module.build_report(args_for(north))
        assert north_report["status"] == "PASS", north_report
        assert north_report["dominant-output-direction"] == "NORTH", north_report

        wide_paths = stable_paths()
        wide_paths[-1] = [
            (0, 0.0, 100.0, 0.0),
            (1, 10.0, 100.0, 2.0),
            (2, 20.0, 100.0, 4.0),
        ]
        wide = write_run(base / "wide", wide_paths)
        wide_report = module.build_report(args_for(wide))
        assert wide_report["status"] == "FAIL", wide_report
        assert any("failed_shots" in item for item in wide_report["failures"]), wide_report
        assert wide_report["output-corridor"]["corridor_violations"] == 1, wide_report

        reverse_paths = stable_paths()
        reverse_paths[-1] = [
            (0, 0.0, 100.0, 0.0),
            (1, -10.0, 100.0, 0.0),
            (2, -20.0, 100.0, 0.0),
        ]
        reverse = write_run(base / "reverse", reverse_paths)
        reverse_report = module.build_report(args_for(reverse))
        assert reverse_report["status"] == "FAIL", reverse_report
        assert reverse_report["shots"][-1]["qualifying_entities"] == 0, reverse_report

        missing = base / "missing"
        missing.mkdir()
        (missing / "run-summary.json").write_text(
            '{"target_direction":"EAST"}\n', encoding="utf-8"
        )
        missing_report = module.build_report(args_for(missing))
        assert missing_report["status"] == "FAIL", missing_report
        assert any("shots=0<5" in item for item in missing_report["failures"]), missing_report

    print("Output-corridor direction repeatability tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
