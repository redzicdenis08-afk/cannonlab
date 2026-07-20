#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def fail(message: str) -> None:
    print(f"CannonLab assertion failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate CannonLab run evidence")
    parser.add_argument("results_root", type=Path)
    parser.add_argument("--expected-shots", type=int, required=True)
    args = parser.parse_args()

    summaries = sorted(
        args.results_root.rglob("run-summary.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not summaries:
        fail(f"no run-summary.json below {args.results_root}")

    summary_path = summaries[0]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    if summary.get("finish_reason") != "complete":
        fail(f"finish_reason={summary.get('finish_reason')!r}")
    if summary.get("shots_requested") != args.expected_shots:
        fail(
            f"shots_requested={summary.get('shots_requested')} expected={args.expected_shots}"
        )
    if summary.get("shots_completed") != args.expected_shots:
        fail(
            f"shots_completed={summary.get('shots_completed')} expected={args.expected_shots}"
        )

    shots = summary.get("shots")
    if not isinstance(shots, list) or len(shots) != args.expected_shots:
        fail("shot list is missing or has the wrong length")

    failures: list[str] = []
    for shot in shots:
        number = shot.get("shot")
        if shot.get("error") is not None:
            failures.append(f"shot {number}: error={shot.get('error')}")
        if not shot.get("saw_payload"):
            failures.append(f"shot {number}: no TNT/falling-block payload observed")
        if int(shot.get("explosions", 0)) < 1:
            failures.append(f"shot {number}: no explosion observed")
        if shot.get("finish_reason") not in {"quiet", "max_ticks"}:
            failures.append(
                f"shot {number}: unexpected finish_reason={shot.get('finish_reason')!r}"
            )

    event_files = list(summary_path.parent.rglob("events.csv"))
    if len(event_files) != args.expected_shots:
        failures.append(
            f"events.csv files={len(event_files)} expected={args.expected_shots}"
        )

    for event_file in event_files:
        line_count = sum(1 for _ in event_file.open("r", encoding="utf-8"))
        if line_count <= 1:
            failures.append(f"{event_file}: contains no telemetry rows")

    if failures:
        fail("; ".join(failures))

    total_explosions = sum(int(shot.get("explosions", 0)) for shot in shots)
    print(
        json.dumps(
            {
                "status": "PASS",
                "summary": str(summary_path),
                "shots": len(shots),
                "total_explosions": total_explosions,
                "telemetry_files": len(event_files),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
