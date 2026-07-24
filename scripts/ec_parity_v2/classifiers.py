from __future__ import annotations

import json
from collections import Counter
from typing import Any

def vector3(value: Any) -> tuple[float, float, float]:
    if isinstance(value, dict):
        raw = value.get("x"), value.get("y"), value.get("z")
    elif isinstance(value, (list, tuple)) and len(value) == 3:
        raw = tuple(value)
    else:
        raise ValueError("expected a three-component vector")
    if not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in raw):
        raise ValueError("vector components must be numbers")
    return float(raw[0]), float(raw[1]), float(raw[2])


def classify_horizontal_kick(samples: list[dict[str, Any]]) -> dict[str, Any]:
    magnitudes = []
    for sample in samples:
        x, _, z = vector3(sample["initial_velocity"])
        magnitudes.append((x * x + z * z) ** 0.5)
    tolerance = 1.0e-9
    zeros = sum(value <= tolerance for value in magnitudes)
    classification = (
        "zero-horizontal-kick" if zeros == len(magnitudes)
        else "nonzero-horizontal-kick"
    )
    return {
        "classification": classification,
        "confidence": "high" if len(samples) >= 100 else "limited",
        "metrics": {
            "samples": len(samples),
            "zero_fraction": zeros / len(samples) if samples else 0.0,
            "mean_horizontal_speed": sum(magnitudes) / len(magnitudes) if magnitudes else 0.0,
            "max_horizontal_speed": max(magnitudes, default=0.0),
        },
    }


def classify_fuse(samples: list[dict[str, Any]]) -> dict[str, Any]:
    lifetimes = [
        int(sample["explosion_tick"]) - int(sample["spawn_tick"])
        for sample in samples
    ]
    initial_fuses = [int(sample["initial_fuse"]) for sample in samples]
    lifetime_counts = Counter(lifetimes)
    classification = (
        f"fixed-lifetime-{lifetimes[0]}" if len(lifetime_counts) == 1
        else "distributed-lifetime"
    )
    return {
        "classification": classification,
        "confidence": "high" if len(samples) >= 100 else "limited",
        "metrics": {
            "samples": len(samples),
            "lifetime_counts": dict(sorted(lifetime_counts.items())),
            "initial_fuse_counts": dict(sorted(Counter(initial_fuses).items())),
            "minimum_lifetime": min(lifetimes),
            "maximum_lifetime": max(lifetimes),
        },
    }


def classify_sequence(samples: list[dict[str, Any]]) -> dict[str, Any]:
    sequences = []
    for sample in samples:
        value = sample["sequence"]
        if not isinstance(value, list) or not value:
            raise ValueError("sequence must be a non-empty array")
        sequences.append(json.dumps(value, separators=(",", ":"), sort_keys=True))
    counts = Counter(sequences)
    fixed = len(counts) == 1
    return {
        "classification": "fixed-order" if fixed else "variable-order",
        "confidence": "high" if len(samples) >= 100 else "limited",
        "metrics": {
            "samples": len(samples),
            "unique_sequences": len(counts),
            "most_common_sequence": json.loads(counts.most_common(1)[0][0]),
            "most_common_fraction": counts.most_common(1)[0][1] / len(samples),
        },
    }


def classify_explosion_batch(samples: list[dict[str, Any]]) -> dict[str, Any]:
    deficits = [
        int(sample["due_count"]) - int(sample["observed_count"])
        for sample in samples
    ]
    multi_tick = [
        int(sample["processing_tick_count"]) > 1 for sample in samples
    ]
    if not any(value > 0 for value in deficits):
        classification = "no-observed-cap-within-tested-range"
    elif any(multi_tick):
        classification = "batched-or-carried-over"
    else:
        classification = "missing-or-removed-explosions"
    return {
        "classification": classification,
        "confidence": "descriptive",
        "metrics": {
            "samples": len(samples),
            "maximum_cohort": max(int(sample["cohort_size"]) for sample in samples),
            "maximum_deficit": max(deficits),
            "multi_tick_fraction": sum(multi_tick) / len(samples),
        },
    }


def paste_pass(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"pass", "passed", "success", "true", "accepted"}:
            return True
        if lowered in {"fail", "failed", "error", "false", "rejected"}:
            return False
    return None


def classify_paste(samples: list[dict[str, Any]], dimension: str) -> dict[str, Any]:
    field = "dispensers" if dimension == "limits.dispensers_per_chunk" else "block_entities"
    passed, failed, unknown = [], [], 0
    for sample in samples:
        result = paste_pass(sample["paste_result"])
        value = int(sample[field])
        if result is True:
            passed.append(value)
        elif result is False:
            failed.append(value)
        else:
            unknown += 1
    return {
        "classification": "bounded-threshold-evidence" if passed and failed else "one-sided-threshold-evidence",
        "confidence": "descriptive",
        "metrics": {
            "samples": len(samples),
            "field": field,
            "highest_pass": max(passed) if passed else None,
            "lowest_fail": min(failed) if failed else None,
            "unknown_results": unknown,
        },
    }


def classify(
    classifier: str,
    samples: list[dict[str, Any]],
    dimension: str,
) -> dict[str, Any]:
    try:
        if classifier == "horizontal-kick":
            return classify_horizontal_kick(samples)
        if classifier == "fuse-lifetime":
            return classify_fuse(samples)
        if classifier == "sequence-order":
            return classify_sequence(samples)
        if classifier == "explosion-batch":
            return classify_explosion_batch(samples)
        if classifier == "paste-threshold":
            return classify_paste(samples, dimension)
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "classification": "classification-error",
            "confidence": "none",
            "error": str(exc),
            "metrics": {"samples": len(samples)},
        }
    return {
        "classification": "not-automatically-classified",
        "confidence": "manual-review-required",
        "metrics": {"samples": len(samples)},
    }
