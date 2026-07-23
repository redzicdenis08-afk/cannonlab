#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from itertools import combinations
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
    parser.add_argument("--minimum-shared-core-components", type=int, default=8)
    parser.add_argument("--minimum-shared-functional", type=int, default=16)
    parser.add_argument("--minimum-connected-functional", type=int, default=8)
    parser.add_argument("--minimum-shared-non-dispenser", type=int, default=8)
    parser.add_argument("--minimum-mechanism-diversity", type=int, default=2)
    parser.add_argument("--skip-partial-core-overlap", action="store_true")
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
    module_reports: dict[str, dict[str, Any]] = {}
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
        module_code, module_map = run_json([
            sys.executable,
            str(SCRIPTS / "cannon-module-map.py"),
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
        module_reports[str(path)] = module_map

        designs.append({
            "file": str(path),
            "audit_status": audit.get("status", "ERROR"),
            "audit_exit_code": audit_code,
            "map_status": static_map.get("status", "ERROR"),
            "map_exit_code": map_code,
            "module_map_status": module_map.get("status", "ERROR"),
            "module_map_exit_code": module_code,
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
            "module_summary": module_map.get("architecture_summary"),
            "repeated_module_families": len(module_map.get("repeated_module_families") or []),
            "repeated_slice_families": len(module_map.get("repeated_slice_families") or []),
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

    signature_occurrences: dict[str, list[dict[str, Any]]] = defaultdict(list)
    signature_counts_by_file: dict[str, Counter[str]] = {}
    signature_components: dict[str, int] = {}
    signature_dispensers: dict[str, int] = {}
    module_component_totals: dict[str, int] = {}
    for file_name, module_report in module_reports.items():
        counts: Counter[str] = Counter()
        total_components = 0
        for module in module_report.get("modules") or []:
            signature = str(module.get("signature"))
            component_count = int(module.get("component_count") or 0)
            dispenser_count = int(module.get("seed_dispenser_count") or 0)
            counts[signature] += 1
            total_components += component_count
            signature_components[signature] = component_count
            signature_dispensers[signature] = dispenser_count
            signature_occurrences[signature].append({
                "file": file_name,
                "module_id": module.get("module_id"),
                "kind": module.get("kind"),
                "component_count": component_count,
                "seed_dispenser_count": dispenser_count,
                "seed_facing": module.get("seed_facing"),
                "bounds": module.get("bounds"),
            })
        signature_counts_by_file[file_name] = counts
        module_component_totals[file_name] = total_components

    shared_module_families = []
    for signature, occurrences in signature_occurrences.items():
        files_present = sorted({str(row["file"]) for row in occurrences})
        if len(files_present) < 2:
            continue
        component_count = signature_components.get(signature, 0)
        shared_module_families.append({
            "signature": signature,
            "design_count": len(files_present),
            "instance_count": len(occurrences),
            "component_count_per_instance": component_count,
            "seed_dispenser_count_per_instance": signature_dispensers.get(signature, 0),
            "shared_core_candidate": component_count >= args.minimum_shared_core_components,
            "files": files_present,
            "occurrences": occurrences,
            "evidence": (
                "exact canonical block-state geometry after translation across multiple corpus designs; "
                "runtime role remains unconfirmed"
            ),
        })
    shared_module_families.sort(
        key=lambda row: (
            -row["component_count_per_instance"] * row["design_count"],
            -row["seed_dispenser_count_per_instance"],
            row["signature"],
        )
    )

    pairwise_module_overlap = []
    for first_file, second_file in combinations(sorted(module_reports), 2):
        first_counts = signature_counts_by_file[first_file]
        second_counts = signature_counts_by_file[second_file]
        shared_signatures = sorted(set(first_counts) & set(second_counts))
        shared_instances = sum(
            min(first_counts[signature], second_counts[signature])
            for signature in shared_signatures
        )
        shared_components = sum(
            min(first_counts[signature], second_counts[signature])
            * signature_components.get(signature, 0)
            for signature in shared_signatures
        )
        pairwise_module_overlap.append({
            "first": first_file,
            "second": second_file,
            "exact_signature_families": len(shared_signatures),
            "exact_module_instances": shared_instances,
            "exact_shared_components": shared_components,
            "first_component_coverage": round(
                shared_components / max(1, module_component_totals[first_file]), 6
            ),
            "second_component_coverage": round(
                shared_components / max(1, module_component_totals[second_file]), 6
            ),
        })
    pairwise_module_overlap.sort(
        key=lambda row: (
            -row["exact_shared_components"],
            row["first"],
            row["second"],
        )
    )

    pairwise_partial_core_overlap = []
    if not args.skip_partial_core_overlap:
        for first_file, second_file in combinations(sorted(module_reports), 2):
            code, overlap = run_json([
                sys.executable,
                str(SCRIPTS / "compare-cannon-cores.py"),
                first_file,
                second_file,
                "--minimum-shared-functional",
                str(args.minimum_shared_functional),
                "--minimum-connected-functional",
                str(args.minimum_connected_functional),
                "--minimum-shared-non-dispenser",
                str(args.minimum_shared_non_dispenser),
                "--minimum-mechanism-diversity",
                str(args.minimum_mechanism_diversity),
            ])
            selected = overlap.get("selected_overlap") or {}
            pairwise_partial_core_overlap.append({
                "first": first_file,
                "second": second_file,
                "exit_code": code,
                "status": overlap.get("status", "ERROR"),
                "shared_core_candidate": overlap.get("shared_core_candidate", False),
                "confidence": overlap.get("confidence", "none"),
                "reasons": overlap.get("reasons", []),
                "translation": selected.get("translation"),
                "exact_functional": selected.get("exact_functional", 0),
                "largest_support_connected_functional": selected.get(
                    "largest_support_connected_functional", 0
                ),
                "exact_non_air": selected.get("exact_non_air", 0),
                "first_functional_coverage": selected.get("first_functional_coverage", 0.0),
                "second_functional_coverage": selected.get("second_functional_coverage", 0.0),
                "overlap_categories": selected.get("overlap_categories", {}),
                "error": overlap.get("error"),
            })
        pairwise_partial_core_overlap.sort(
            key=lambda row: (
                not row["shared_core_candidate"],
                -int(row["exact_functional"] or 0),
                row["first"],
                row["second"],
            )
        )

    report = {
        "status": "PASS",
        "directory": str(args.directory),
        "chunk_limit": args.chunk_limit,
        "design_count": len(designs),
        "module_intelligence": {
            "minimum_shared_core_components": args.minimum_shared_core_components,
            "unique_module_signatures": len(signature_occurrences),
            "shared_module_families": len(shared_module_families),
            "shared_core_candidate_families": sum(
                bool(row["shared_core_candidate"])
                for row in shared_module_families
            ),
            "pairwise_comparisons": len(pairwise_module_overlap),
            "pairwise_partial_core_comparisons": len(pairwise_partial_core_overlap),
            "partial_core_candidates": sum(
                bool(row["shared_core_candidate"])
                for row in pairwise_partial_core_overlap
            ),
        },
        "shared_module_families": shared_module_families,
        "pairwise_module_overlap": pairwise_module_overlap,
        "pairwise_partial_core_overlap": pairwise_partial_core_overlap,
        "designs": designs,
        "truth_boundary": (
            "Corpus families prove exact translated static geometry only. Runtime traces and live evidence "
            "are required before treating a family as a shared functional subsystem."
        ),
    }
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
