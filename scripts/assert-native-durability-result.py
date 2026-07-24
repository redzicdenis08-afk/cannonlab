#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class NativeDurabilityEvidenceError(ValueError):
    pass


def integer(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise NativeDurabilityEvidenceError(f"{label} must be an integer, got {value!r}") from exc


def latest_summary(results_root: Path) -> Path:
    summaries = sorted(
        results_root.rglob("run-summary.json"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not summaries:
        raise NativeDurabilityEvidenceError(f"no run-summary.json below {results_root}")
    return summaries[0]


def reconcile_shot(shot: dict[str, Any]) -> dict[str, Any]:
    number = integer(shot.get("shot", 0), "shot")
    final_destroyed = max(
        0,
        integer(shot.get("target_blocks_destroyed", 0), f"shot {number} target_blocks_destroyed"),
    )
    reported_peak = max(
        0,
        integer(shot.get("target_peak_destroyed", 0), f"shot {number} target_peak_destroyed"),
    )
    reported_ever = max(
        0,
        integer(shot.get("target_ever_destroyed", 0), f"shot {number} target_ever_destroyed"),
    )
    reported_layer = max(
        0,
        integer(shot.get("max_layer_breached", 0), f"shot {number} max_layer_breached"),
    )

    # A block absent at shot completion must also have been absent at the peak and at least once.
    # Final state proves only that one or more target cells are gone. It cannot identify a deeper
    # layer than the first without an observed layer metric from the runtime monitor.
    effective_peak = max(reported_peak, final_destroyed)
    effective_ever = max(reported_ever, final_destroyed)
    final_state_layer_lower_bound = 1 if final_destroyed > 0 else 0
    effective_layer = max(reported_layer, final_state_layer_lower_bound)

    return {
        "shot": number,
        "contract_pass": bool(shot.get("contract_pass", False)),
        "error": shot.get("error"),
        "reported": {
            "target_blocks_destroyed_final": final_destroyed,
            "target_peak_destroyed": reported_peak,
            "target_ever_destroyed": reported_ever,
            "max_layer_breached": reported_layer,
        },
        "effective_lower_bounds": {
            "target_peak_destroyed": effective_peak,
            "target_ever_destroyed": effective_ever,
            "max_layer_breached": effective_layer,
        },
        "reconciled": {
            "target_peak_destroyed": effective_peak != reported_peak,
            "target_ever_destroyed": effective_ever != reported_ever,
            "max_layer_breached": effective_layer != reported_layer,
        },
    }


def audit_results(
    results_root: Path,
    *,
    expected_shots: int,
    min_final_destroyed: int,
    min_effective_peak_destroyed: int,
    min_effective_layer_breached: int,
) -> dict[str, Any]:
    if expected_shots < 1:
        raise NativeDurabilityEvidenceError("expected_shots must be positive")
    for label, value in (
        ("min_final_destroyed", min_final_destroyed),
        ("min_effective_peak_destroyed", min_effective_peak_destroyed),
        ("min_effective_layer_breached", min_effective_layer_breached),
    ):
        if value < 0:
            raise NativeDurabilityEvidenceError(f"{label} cannot be negative")

    summary_path = latest_summary(results_root)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise NativeDurabilityEvidenceError("run-summary.json must contain an object")

    failures: list[str] = []
    if summary.get("finish_reason") != "complete":
        failures.append(f"finish_reason={summary.get('finish_reason')!r} expected='complete'")
    if integer(summary.get("shots_requested", 0), "shots_requested") != expected_shots:
        failures.append(
            f"shots_requested={summary.get('shots_requested')!r} expected={expected_shots}"
        )
    if integer(summary.get("shots_completed", 0), "shots_completed") != expected_shots:
        failures.append(
            f"shots_completed={summary.get('shots_completed')!r} expected={expected_shots}"
        )

    durability = summary.get("durability") or {}
    if not isinstance(durability, dict):
        failures.append("durability summary is missing")
        durability = {}
    if durability.get("effective_mode") != "NATIVE":
        failures.append(
            f"durability.effective_mode={durability.get('effective_mode')!r} expected='NATIVE'"
        )

    raw_shots = summary.get("shots")
    if not isinstance(raw_shots, list) or len(raw_shots) != expected_shots:
        failures.append(
            f"shot list length={len(raw_shots) if isinstance(raw_shots, list) else 'missing'} "
            f"expected={expected_shots}"
        )
        raw_shots = []

    reconciled_shots: list[dict[str, Any]] = []
    for raw in raw_shots:
        if not isinstance(raw, dict):
            failures.append("shot entry is not an object")
            continue
        shot = reconcile_shot(raw)
        reconciled_shots.append(shot)
        number = shot["shot"]
        if shot["error"] is not None:
            failures.append(f"shot {number}: error={shot['error']!r}")
        if not shot["contract_pass"]:
            failures.append(f"shot {number}: contract_pass=false")

        reported = shot["reported"]
        effective = shot["effective_lower_bounds"]
        final_destroyed = int(reported["target_blocks_destroyed_final"])
        effective_peak = int(effective["target_peak_destroyed"])
        effective_layer = int(effective["max_layer_breached"])
        if final_destroyed < min_final_destroyed:
            failures.append(
                f"shot {number}: target_blocks_destroyed_final={final_destroyed} "
                f"below {min_final_destroyed}"
            )
        if effective_peak < min_effective_peak_destroyed:
            failures.append(
                f"shot {number}: effective_target_peak_destroyed={effective_peak} "
                f"below {min_effective_peak_destroyed}"
            )
        if effective_layer < min_effective_layer_breached:
            failures.append(
                f"shot {number}: effective_max_layer_breached={effective_layer} "
                f"below {min_effective_layer_breached}"
            )

    return {
        "schema_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "summary": str(summary_path),
        "scenario": summary.get("scenario"),
        "durability": durability,
        "requirements": {
            "expected_shots": expected_shots,
            "min_final_destroyed": min_final_destroyed,
            "min_effective_peak_destroyed": min_effective_peak_destroyed,
            "min_effective_layer_breached": min_effective_layer_breached,
        },
        "shots": reconciled_shots,
        "reconciliation_count": sum(
            any(bool(value) for value in shot["reconciled"].values())
            for shot in reconciled_shots
        ),
        "failures": failures,
        "truth_boundary": {
            "final_target_state_is_direct_end_of_shot_evidence": True,
            "final_destroyed_lower_bounds_peak_and_ever_destroyed": True,
            "any_final_destroyed_cell_lower_bounds_breached_layers_to_one": True,
            "final_state_infers_layers_beyond_first": False,
            "raw_runtime_metrics_are_overwritten": False,
            "private_extremecraft_parity_confirmed": False,
            "ec_ready": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate native Sakura durability using final target state as an explicit, "
            "one-layer-bounded reconciliation source"
        )
    )
    parser.add_argument("results_root", type=Path)
    parser.add_argument("--expected-shots", type=int, required=True)
    parser.add_argument("--min-final-destroyed", type=int, default=1)
    parser.add_argument("--min-effective-peak-destroyed", type=int, default=1)
    parser.add_argument("--min-effective-layer-breached", type=int, default=1)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    try:
        report = audit_results(
            args.results_root.resolve(),
            expected_shots=args.expected_shots,
            min_final_destroyed=args.min_final_destroyed,
            min_effective_peak_destroyed=args.min_effective_peak_destroyed,
            min_effective_layer_breached=args.min_effective_layer_breached,
        )
    except (OSError, json.JSONDecodeError, NativeDurabilityEvidenceError) as exc:
        report = {
            "schema_version": 1,
            "status": "FAIL",
            "error": str(exc),
            "truth_boundary": {
                "private_extremecraft_parity_confirmed": False,
                "ec_ready": False,
            },
        }

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
