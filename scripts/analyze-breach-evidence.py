#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


def latest_summary(path: Path) -> Path:
    if path.is_file():
        return path
    summaries = sorted(
        path.rglob("run-summary.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not summaries:
        raise FileNotFoundError(f"no run-summary.json below {path}")
    return summaries[0]


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def read_breach_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def shot_directory(summary_path: Path, number: int) -> Path:
    return summary_path.parent / f"shot-{number:03d}"


def audit_shot(
    summary_path: Path,
    shot: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    number = int(shot.get("shot", 0))
    breach_path = shot_directory(summary_path, number) / "breach-events.csv"
    rows = read_breach_rows(breach_path)

    failures: list[str] = []
    warnings: list[str] = []
    impact_gate_requested = args.min_embedded_payload_explosions > 0
    if not breach_path.is_file():
        failures.append("breach_events_missing")

    tnt_rows = [
        row
        for row in rows
        if str(row.get("entity_type", "")).upper()
        in {"TNT", "PRIMED_TNT", "TNT_PRIMED"}
    ]
    if impact_gate_requested and rows and not tnt_rows:
        failures.append("tnt_breach_events_missing")
    target_tnt_rows = [row for row in tnt_rows if as_bool(row.get("target_contact"))]
    if impact_gate_requested and tnt_rows and not target_tnt_rows:
        failures.append("target_tnt_breach_events_missing")

    embedded = sum(
        as_bool(row.get("center_water_contact"))
        and as_bool(row.get("falling_overlap_evidence"))
        for row in target_tnt_rows
    )
    water_contact = sum(
        as_bool(row.get("center_water_contact")) for row in target_tnt_rows
    )
    unembedded_water = sum(
        as_bool(row.get("center_water_contact"))
        and not as_bool(row.get("falling_overlap_evidence"))
        for row in target_tnt_rows
    )

    reported_embedded = shot.get("embedded_payload_explosions")
    reported_water = shot.get("water_contact_explosions")
    reported_unembedded = shot.get("unembedded_water_explosions")
    for label, reported, observed in (
        ("embedded_payload_explosions", reported_embedded, embedded),
        ("water_contact_explosions", reported_water, water_contact),
        ("unembedded_water_explosions", reported_unembedded, unembedded_water),
    ):
        if reported is None:
            failures.append(f"summary_field_missing:{label}")
        elif int(reported) != observed:
            failures.append(f"summary_csv_mismatch:{label}:{reported}!={observed}")

    contiguous = shot.get("contiguous_layers_breached_before_first_regen")
    total_layers = shot.get("target_layer_count")
    all_layers = shot.get("all_layers_breached_before_first_regen")
    if contiguous is None:
        failures.append("summary_field_missing:contiguous_layers_breached_before_first_regen")
        contiguous_value = 0
    else:
        contiguous_value = int(contiguous)
    if total_layers is None:
        failures.append("summary_field_missing:target_layer_count")
        total_layers_value = 0
    else:
        total_layers_value = int(total_layers)
    if all_layers is None:
        failures.append("summary_field_missing:all_layers_breached_before_first_regen")
        all_layers_value = False
    else:
        all_layers_value = as_bool(all_layers)

    if embedded < args.min_embedded_payload_explosions:
        failures.append(
            f"embedded_payload_explosions={embedded}"
            f"<{args.min_embedded_payload_explosions}"
        )
    if unembedded_water > args.max_unembedded_water_explosions:
        failures.append(
            f"unembedded_water_explosions={unembedded_water}"
            f">{args.max_unembedded_water_explosions}"
        )
    if contiguous_value < args.min_contiguous_layers_before_first_regen:
        failures.append(
            f"contiguous_layers_before_first_regen={contiguous_value}"
            f"<{args.min_contiguous_layers_before_first_regen}"
        )
    if args.require_all_layers_before_first_regen and not all_layers_value:
        failures.append(
            f"all_layers_not_breached_before_first_regen="
            f"{contiguous_value}/{total_layers_value}"
        )

    if embedded > 0 and water_contact == 0:
        warnings.append(
            "falling overlap was measured, but no explosion center occupied a water cell"
        )
    if total_layers_value == 0:
        warnings.append("target layer count is zero; regen-race evidence is not meaningful")

    return {
        "shot": number,
        "status": "PASS" if not failures else "FAIL",
        "breach_events": str(breach_path),
        "explosion_evidence": {
            "events": len(target_tnt_rows),
            "all_tnt_explosion_events": len(tnt_rows),
            "all_explosion_events": len(rows),
            "embedded_payload_explosions": embedded,
            "water_contact_explosions": water_contact,
            "unembedded_water_explosions": unembedded_water,
        },
        "regen_race": {
            "first_target_damage_tick": shot.get("first_target_damage_tick", -1),
            "first_regen_restore_tick": shot.get("first_regen_restore_tick", -1),
            "layers_breached_before_first_regen": shot.get(
                "layers_breached_before_first_regen", 0
            ),
            "contiguous_layers_breached_before_first_regen": contiguous_value,
            "max_layer_breached_before_first_regen": shot.get(
                "max_layer_breached_before_first_regen", 0
            ),
            "target_layer_count": total_layers_value,
            "all_layers_breached_before_first_regen": all_layers_value,
            "all_layers_breached_tick": shot.get("all_layers_breached_tick", -1),
            "regen_race_margin_ticks": shot.get("regen_race_margin_ticks", -1),
        },
        "failures": failures,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed post-run audit for falling-payload explosion overlap and "
            "wall-layer progress before the first actual regeneration restore."
        )
    )
    parser.add_argument("results", type=Path)
    parser.add_argument("--min-embedded-payload-explosions", type=int, default=1)
    parser.add_argument("--max-unembedded-water-explosions", type=int, default=0)
    parser.add_argument(
        "--min-contiguous-layers-before-first-regen", type=int, default=0
    )
    parser.add_argument("--require-all-layers-before-first-regen", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    if args.min_embedded_payload_explosions < 0:
        parser.error("--min-embedded-payload-explosions cannot be negative")
    if args.max_unembedded_water_explosions < 0:
        parser.error("--max-unembedded-water-explosions cannot be negative")
    if args.min_contiguous_layers_before_first_regen < 0:
        parser.error("--min-contiguous-layers-before-first-regen cannot be negative")

    try:
        summary_path = latest_summary(args.results)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        print(f"CannonLab breach audit failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    shots = summary.get("shots")
    if not isinstance(shots, list) or not shots:
        report = {
            "schema": "cannonlab-breach-evidence-v1",
            "status": "FAIL",
            "summary": str(summary_path),
            "failures": ["run_summary_has_no_shots"],
            "shots": [],
        }
    else:
        shot_reports = [audit_shot(summary_path, shot, args) for shot in shots]
        failures = [
            f"shot-{item['shot']:03d}:{failure}"
            for item in shot_reports
            for failure in item["failures"]
        ]
        report = {
            "schema": "cannonlab-breach-evidence-v1",
            "status": "PASS" if not failures else "FAIL",
            "summary": str(summary_path),
            "scenario": summary.get("scenario"),
            "thresholds": {
                "min_embedded_payload_explosions": args.min_embedded_payload_explosions,
                "max_unembedded_water_explosions": args.max_unembedded_water_explosions,
                "min_contiguous_layers_before_first_regen": (
                    args.min_contiguous_layers_before_first_regen
                ),
                "require_all_layers_before_first_regen": (
                    args.require_all_layers_before_first_regen
                ),
            },
            "failures": failures,
            "shots": shot_reports,
            "truth_boundary": {
                "runtime_engine_confirmed": True,
                "private_extremecraft_parity_confirmed": False,
                "falling_overlap_is_direct_runtime_evidence": True,
                "breach_counts_are_target_scoped": True,
                "falling_overlap_alone_proves_water_bypass": False,
                "regen_race_uses_first_actual_restore": True,
            },
        }

    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    raise SystemExit(0 if report["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
