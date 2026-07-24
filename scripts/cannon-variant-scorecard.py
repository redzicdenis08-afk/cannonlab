#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT.parents[1] / "output"
VARIANT_ROOT = ROOT / "variant-jobs"


def slugify(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:72] or "variant-scorecard"


def allowed_path(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not (path.is_relative_to(ROOT) or path.is_relative_to(OUTPUT_ROOT)):
        raise ValueError(f"path escapes CannonLab roots: {raw}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def numeric_values(shots: list[dict[str, Any]], key: str) -> list[float]:
    output = []
    for shot in shots:
        number = finite_number(shot.get(key))
        if number is not None:
            output.append(number)
    return output


def boolean_rate(shots: list[dict[str, Any]], key: str) -> float | None:
    values = [shot.get(key) for shot in shots if isinstance(shot.get(key), bool)]
    if len(values) != len(shots) or not values:
        return None
    return sum(1 for value in values if value) / len(values)


def direction_repeatability(summaries: list[dict[str, Any]], shots: list[dict[str, Any]]) -> float | None:
    direct = []
    for summary in summaries:
        number = finite_number(summary.get("direction_repeatability"))
        if number is not None:
            direct.append(number)
    if direct:
        return min(direct)
    per_shot = numeric_values(shots, "direction_repeatability")
    if len(per_shot) == len(shots) and per_shot:
        return min(per_shot)
    directions = [
        str(shot.get("dominant_output_direction"))
        for shot in shots
        if str(shot.get("dominant_output_direction", "")).strip()
    ]
    if len(directions) != len(shots) or not directions:
        return None
    count = Counter(directions).most_common(1)[0][1]
    return count / len(directions)


def aggregate(summaries: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, Any], list[dict[str, str]]]:
    shots: list[dict[str, Any]] = []
    for summary in summaries:
        raw = summary.get("shots")
        if isinstance(raw, list):
            shots.extend(item for item in raw if isinstance(item, dict))
        elif any(key in summary for key in ("target_blocks_destroyed", "self_damage_blocks", "explosions")):
            shots.append(summary)
    blockers: list[dict[str, str]] = []
    if not shots:
        blockers.append({"code": "no-shot-evidence", "message": "no shot objects found in supplied run summaries"})
        return {}, {"shot_count": 0}, blockers

    metrics: dict[str, float] = {}
    rules = {
        "target_destroyed": ("target_blocks_destroyed", min),
        "target_destroyed_mean": ("target_blocks_destroyed", mean),
        "target_peak_destroyed": ("target_peak_destroyed", min),
        "target_ever_destroyed": ("target_ever_destroyed", min),
        "embedded_payload_explosions": ("embedded_payload_explosions", min),
        "unembedded_water_explosions": ("unembedded_water_explosions", max),
        "self_damage_blocks": ("self_damage_blocks", max),
        "maximum_forward_distance": ("maximum_forward_distance", min),
        "maximum_falling_blocks": ("maximum_falling_blocks", min),
        "regen_race_margin_ticks": ("regen_race_margin_ticks", min),
        "contiguous_layers_before_first_regen": ("contiguous_layers_breached_before_first_regen", min),
    }
    coverage: dict[str, int] = {}
    for output_name, (source_name, reducer) in rules.items():
        values = numeric_values(shots, source_name)
        coverage[output_name] = len(values)
        if len(values) == len(shots) and values:
            metrics[output_name] = float(reducer(values))

    ratios = []
    for shot in shots:
        initial = finite_number(shot.get("cannon_initial_dispensers"))
        remaining = finite_number(shot.get("cannon_remaining_dispensers"))
        if initial is None or remaining is None or initial <= 0:
            continue
        ratios.append(remaining / initial)
    coverage["remaining_dispenser_ratio"] = len(ratios)
    if len(ratios) == len(shots) and ratios:
        metrics["remaining_dispenser_ratio"] = min(ratios)

    repeatability = direction_repeatability(summaries, shots)
    coverage["direction_repeatability"] = len(shots) if repeatability is not None else 0
    if repeatability is not None:
        metrics["direction_repeatability"] = repeatability

    contract_rate = boolean_rate(shots, "contract_pass")
    coverage["contract_pass_rate"] = len(shots) if contract_rate is not None else 0
    if contract_rate is not None:
        metrics["contract_pass_rate"] = contract_rate

    all_layers_rate = boolean_rate(shots, "all_layers_breached_before_first_regen")
    coverage["all_layers_before_first_regen_rate"] = len(shots) if all_layers_rate is not None else 0
    if all_layers_rate is not None:
        metrics["all_layers_before_first_regen_rate"] = all_layers_rate

    return metrics, {
        "shot_count": len(shots),
        "metric_shot_coverage": coverage,
        "aggregation_policy": {
            "benefit_metrics": "minimum across shots unless explicitly named mean",
            "damage_and_failure_metrics": "maximum across shots",
            "remaining_dispenser_ratio": "minimum across shots",
            "direction_repeatability": "minimum explicit value or dominant-direction agreement fraction",
        },
    }, blockers


def variant_sources(result_map: dict[str, Any], variant_id: str) -> list[Path]:
    variants = result_map.get("variants")
    if not isinstance(variants, dict):
        raise ValueError("result map variants must be an object")
    raw = variants.get(variant_id)
    if isinstance(raw, dict):
        raw = raw.get("run_summaries")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [allowed_path(item) for item in raw]


def extract(manifest_raw: str, result_map_raw: str) -> dict[str, Any]:
    manifest_path = allowed_path(manifest_raw)
    result_map_path = allowed_path(result_map_raw)
    manifest = load_json(manifest_path)
    result_map = load_json(result_map_path)
    if manifest.get("schema") != "cannonlab-variant-search-manifest-v1":
        raise ValueError("unsupported variant manifest")
    if result_map.get("schema") != "cannonlab-variant-result-map-v1":
        raise ValueError("unsupported result-map schema")
    candidates = [item for item in manifest.get("candidates", []) if isinstance(item, dict)]
    known_ids = {str(item.get("variant_id", "")) for item in candidates}
    supplied = result_map.get("variants") if isinstance(result_map.get("variants"), dict) else {}
    unknown = sorted(set(str(key) for key in supplied) - known_ids)
    if unknown:
        raise ValueError(f"result map contains unknown variants: {unknown}")

    rows: dict[str, Any] = {}
    blockers: list[dict[str, str]] = []
    require_all = result_map.get("require_all_static_candidates", True) is not False
    for candidate in candidates:
        variant_id = str(candidate.get("variant_id", ""))
        if candidate.get("static_score") is None:
            continue
        sources = variant_sources(result_map, variant_id)
        if not sources:
            if require_all:
                blockers.append({"code": "variant-results-missing", "message": variant_id})
            continue
        summaries = [load_json(path) for path in sources]
        metrics, evidence, row_blockers = aggregate(summaries)
        if row_blockers:
            blockers.extend({"code": item["code"], "message": f"{variant_id}:{item['message']}"} for item in row_blockers)
        rows[variant_id] = {
            "metrics": metrics,
            "evidence": {
                **evidence,
                "run_summaries": [
                    {"path": str(path), "sha256": sha256(path)}
                    for path in sources
                ],
            },
        }
    payload = {
        "schema": "cannonlab-variant-runtime-scorecard-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not blockers else "BLOCKED",
        "truth_boundary": (
            "Metrics are conservative aggregates of supplied local run summaries. Missing fields stay missing, "
            "so the variant ranker fails closed instead of inventing evidence."
        ),
        "search_manifest": str(manifest_path),
        "result_map": str(result_map_path),
        "variants": rows,
        "blockers": blockers,
    }
    job = slugify(str(manifest.get("job") or manifest_path.parent.name))
    output = VARIANT_ROOT / job / "runtime-scorecard.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload["scorecard_report"] = str(output.relative_to(ROOT)).replace("\\", "/")
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract conservative variant scorecards from CannonLab run summaries")
    parser.add_argument("manifest")
    parser.add_argument("result_map")
    args = parser.parse_args()
    result = extract(args.manifest, args.result_map)
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
