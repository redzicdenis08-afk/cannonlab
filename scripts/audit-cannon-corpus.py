#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
EXTENSIONS = {".schem", ".litematic"}


def run_json(args: list[str]) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {
            "status": "ERROR",
            "error": result.stderr[-2000:] or result.stdout[-2000:],
        }
    return result.returncode, payload


def classify(
    dispensers: int,
    height: int,
    functional_height: int,
    morphology: dict[str, Any] | None,
) -> list[str]:
    labels: list[str] = []
    if dispensers == 0:
        labels.append("non-cannon-or-incomplete")
    if height < 16 or functional_height < 8:
        labels.append("low-profile-shape")
    if height >= 32 and functional_height >= 24:
        labels.append("vertical-complex-shape")
    if dispensers >= 384:
        labels.append("large-dispenser-system")
    elif dispensers >= 128:
        labels.append("medium-dispenser-system")
    else:
        labels.append("small-dispenser-system")
    if morphology:
        labels.append(
            "modern-raid-morphology-pass"
            if morphology.get("verdict") == "PASS"
            else "modern-raid-morphology-fail"
        )
    return labels


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Batch audit and structurally compare a private cannon corpus"
    )
    parser.add_argument("directory", type=Path)
    parser.add_argument("--chunk-limit", type=int, default=160)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    files = sorted(
        path
        for path in args.directory.rglob("*")
        if path.is_file() and path.suffix.lower() in EXTENSIONS
    )
    if not files:
        raise SystemExit(f"no .schem or .litematic files under {args.directory}")

    designs: list[dict[str, Any]] = []
    for path in files:
        audit_code, audit = run_json([
            sys.executable,
            str(SCRIPTS / "schem-audit.py"),
            str(path),
            "--chunk-limit",
            str(args.chunk_limit),
        ])
        map_code, static_map = run_json([
            sys.executable,
            str(SCRIPTS / "cannon-static-map.py"),
            str(path),
            "--chunk-limit",
            str(args.chunk_limit),
        ])
        profile_code, profile = run_json([
            sys.executable,
            str(SCRIPTS / "cannon-geometry-profile.py"),
            str(path),
            "--chunk-limit",
            str(args.chunk_limit),
            "--intent",
            "calibration",
        ])

        dimensions = audit.get("dimensions") or static_map.get("dimensions") or {}
        dispenser_report = audit.get("dispensers") or {}
        dispensers = int(dispenser_report.get("count", 0))
        bounds = static_map.get("functional_bounds") or {}
        bounds_dimensions = bounds.get("dimensions") or {}
        functional_height = int(bounds_dimensions.get("y", 0))
        controls = static_map.get("controls") if isinstance(static_map.get("controls"), list) else []
        profile_candidate = profile.get("candidate") if isinstance(profile.get("candidate"), dict) else {}
        morphology = (
            profile_candidate.get("modern_raid_morphology")
            if isinstance(profile_candidate, dict)
            else None
        )

        designs.append({
            "file": str(path),
            "audit_status": audit.get("status", "ERROR"),
            "audit_exit_code": audit_code,
            "map_status": static_map.get("status", "ERROR"),
            "map_exit_code": map_code,
            "profile_status": profile.get("status", "ERROR"),
            "profile_exit_code": profile_code,
            "format": audit.get("format") or static_map.get("format"),
            "dimensions": dimensions,
            "dispensers": dispensers,
            "aligned_max_per_chunk": dispenser_report.get("aligned_max"),
            "safe_alignment_count": dispenser_report.get("safe_alignment_count"),
            "best_alignment": dispenser_report.get("best_alignment"),
            "worst_alignment": dispenser_report.get("worst_alignment"),
            "block_entities": audit.get("block_entities"),
            "functional_bounds": bounds,
            "functional_height": functional_height,
            "control_count": len(controls),
            "controls": controls,
            "largest_dispenser_bank": static_map.get("largest_dispenser_bank"),
            "geometry_profile": profile_candidate,
            "modern_raid_morphology": morphology,
            "shape_labels": classify(
                dispensers,
                int(dimensions.get("height", 0)),
                functional_height,
                morphology,
            ),
            "errors": audit.get("errors", []),
            "warnings": audit.get("warnings", []),
            "truth_boundary": (
                "Shape labels and morphology are structural only. Runtime traces are "
                "required before naming charge, hammer, booster, nuke, rev-worm or OSRB roles."
            ),
        })

    report = {
        "status": "PASS",
        "directory": str(args.directory),
        "chunk_limit": args.chunk_limit,
        "design_count": len(designs),
        "designs": designs,
    }
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
