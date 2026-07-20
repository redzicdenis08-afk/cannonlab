#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def stability(values: list[float]) -> float:
    if len(values) < 2:
        return 1.0
    average = mean(values)
    if average == 0:
        return 1.0 if all(value == 0 for value in values) else 0.0
    coefficient = statistics.pstdev(values) / abs(average)
    return max(0.0, 1.0 - min(1.0, coefficient))


def score_run(summary_path: Path) -> dict[str, object]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    shots = summary.get("shots", []) if isinstance(summary.get("shots"), list) else []
    requested = max(1, int(summary.get("shots_requested", len(shots) or 1)))
    completed = len(shots)

    errors = sum(1 for shot in shots if shot.get("error") is not None)
    payloads = sum(1 for shot in shots if shot.get("saw_payload"))
    explosions = [float(shot.get("explosions", 0)) for shot in shots]
    target_ratios = []
    target_destroyed = []
    for shot in shots:
        destroyed = float(shot.get("target_blocks_destroyed", 0))
        total = float(shot.get("target_blocks_total", 0))
        target_destroyed.append(destroyed)
        target_ratios.append(destroyed / total if total > 0 else 0.0)

    completion_rate = completed / requested
    payload_rate = payloads / requested
    error_rate = errors / requested
    average_target_ratio = mean(target_ratios)
    average_explosions = mean(explosions)
    target_stability = stability(target_destroyed)
    explosion_stability = stability(explosions)

    # Reliability dominates. Penetration then separates reliable designs.
    score = (
        completion_rate * 30.0
        + payload_rate * 25.0
        + (1.0 - error_rate) * 20.0
        + min(1.0, average_target_ratio) * 15.0
        + target_stability * 5.0
        + explosion_stability * 5.0
    )

    return {
        "scenario": summary.get("scenario", summary_path.parent.name),
        "summary": str(summary_path),
        "score": round(score, 6),
        "shots_requested": requested,
        "shots_completed": completed,
        "completion_rate": completion_rate,
        "payload_rate": payload_rate,
        "error_rate": error_rate,
        "average_explosions": average_explosions,
        "average_target_destroyed": mean(target_destroyed),
        "average_target_ratio": average_target_ratio,
        "target_stability": target_stability,
        "explosion_stability": explosion_stability,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank CannonLab run summaries")
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    summaries: list[Path] = []
    for root in args.roots:
        if root.is_file() and root.name == "run-summary.json":
            summaries.append(root)
        elif root.exists():
            summaries.extend(root.rglob("run-summary.json"))
    unique = sorted(set(path.resolve() for path in summaries))
    if not unique:
        raise SystemExit("No run-summary.json files found")

    ranking = sorted((score_run(path) for path in unique), key=lambda item: item["score"], reverse=True)
    report = {"status": "PASS", "runs": len(ranking), "ranking": ranking}
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
