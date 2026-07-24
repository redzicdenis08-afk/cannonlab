#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import functools
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT.parents[1] / "output"
MUTATOR = ROOT / "scripts" / "cannon-mutator.py"
VARIANT_ROOT = ROOT / "variant-jobs"
CACHE_ROOT = OUTPUT_ROOT / "cannonlab-variant-cache" / "v1"
OPERATIONS = {"set-repeater-delay", "set-block-state", "translate-region"}
LIMIT_OPS = {"<=", ">=", "<", ">", "=="}


def slugify(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:72] or "variant-search"


def allowed_path(raw: str | Path, *, must_exist: bool = True) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not (path.is_relative_to(ROOT) or path.is_relative_to(OUTPUT_ROOT)):
        raise ValueError(f"path escapes CannonLab roots: {raw}")
    if must_exist and not path.exists():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def run_json(command: list[str], timeout: int = 1200) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=timeout)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"status": "ERROR", "error": result.stderr[-3000:] or result.stdout[-3000:]}
    return result.returncode, payload


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


@functools.lru_cache(maxsize=1)
def tool_fingerprint() -> dict[str, str]:
    dependencies = [
        MUTATOR,
        ROOT / "scripts" / "schem-audit.py",
        ROOT / "scripts" / "paste-alignment-audit.py",
        ROOT / "scripts" / "cannon-preservation-check.py",
        ROOT / "scripts" / "cannon-module-map.py",
    ]
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path)
        for path in dependencies
        if path.is_file()
    }


def mutation_cache_key(plan: dict[str, Any], parent_sha256: str) -> str:
    payload = {
        "schema": "cannonlab-variant-cache-key-v1",
        "parent_sha256": parent_sha256,
        "data_version": plan.get("data_version"),
        "max_changed_blocks": plan.get("max_changed_blocks"),
        "chunk_limit": plan.get("chunk_limit"),
        "require_ec160_safe": plan.get("require_ec160_safe"),
        "operations": plan.get("operations"),
        "preservation": plan.get("preservation"),
        "tool_fingerprint": tool_fingerprint(),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def clone_result_for_output(
    result: dict[str, Any],
    output: Path,
    *,
    cache_key: str,
    cache_hit: bool,
    deduplicated_from: str | None = None,
) -> dict[str, Any]:
    cloned = copy.deepcopy(result)
    output_payload = cloned.get("output")
    if not isinstance(output_payload, dict):
        output_payload = {}
        cloned["output"] = output_payload
    output_payload["path"] = str(output)
    if output.is_file():
        output_payload["sha256"] = sha256(output)
    cloned["cache"] = {
        "schema": "cannonlab-variant-cache-result-v1",
        "key": cache_key,
        "hit": cache_hit,
        "deduplicated_from": deduplicated_from,
        "truth_boundary": (
            "A cache hit reuses exact static mutation evidence only when parent, operations, "
            "preservation policy and tool hashes are identical. It never reuses runtime proof."
        ),
    }
    return cloned


def load_cached_result(cache_dir: Path, output: Path, cache_key: str) -> dict[str, Any] | None:
    result_path = cache_dir / "result.json"
    schematic_path = cache_dir / "candidate.schem"
    if not result_path.is_file() or not schematic_path.is_file():
        return None
    try:
        envelope = load_json(result_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if envelope.get("schema") != "cannonlab-variant-cache-entry-v1":
        return None
    if envelope.get("cache_key") != cache_key:
        return None
    expected_sha = str(envelope.get("candidate_sha256", ""))
    if not expected_sha or sha256(schematic_path) != expected_sha:
        return None
    result = envelope.get("result")
    if not isinstance(result, dict):
        return None
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(schematic_path, output)
    return clone_result_for_output(result, output, cache_key=cache_key, cache_hit=True)


def store_cached_result(cache_dir: Path, output: Path, cache_key: str, result: dict[str, Any]) -> None:
    if not output.is_file():
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    schematic_path = cache_dir / "candidate.schem"
    shutil.copy2(output, schematic_path)
    envelope = {
        "schema": "cannonlab-variant-cache-entry-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "cache_key": cache_key,
        "candidate_sha256": sha256(schematic_path),
        "result": copy.deepcopy(result),
        "truth_boundary": "Static evidence cache only. Runtime evidence is never stored here.",
    }
    temporary = cache_dir / "result.json.tmp"
    temporary.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    temporary.replace(cache_dir / "result.json")


def apply_unique_plan(
    plan_path: Path,
    plan: dict[str, Any],
    *,
    parent_sha256: str,
    use_cache: bool,
    timeout_seconds: int,
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    output = Path(str(plan["output"])).resolve()
    cache_key = mutation_cache_key(plan, parent_sha256)
    cache_dir = CACHE_ROOT / cache_key[:2] / cache_key
    if use_cache:
        cached = load_cached_result(cache_dir, output, cache_key)
        if cached is not None:
            return 0, cached, {
                "cache_key": cache_key,
                "cache_hit": True,
                "elapsed_seconds": round(time.perf_counter() - started, 6),
            }
    try:
        code, result = run_json(
            [sys.executable, str(MUTATOR), str(plan_path)],
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        code, result = 124, {
            "status": "ERROR",
            "error": f"bounded mutation exceeded timeout_seconds={timeout_seconds}",
        }
    result = clone_result_for_output(result, output, cache_key=cache_key, cache_hit=False)
    if use_cache and output.is_file() and str(result.get("status", "")).upper() in {"PASS", "BLOCKED"}:
        store_cached_result(cache_dir, output, cache_key, result)
    return code, result, {
        "cache_key": cache_key,
        "cache_hit": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }


def render(value: Any, selected: Any) -> Any:
    if isinstance(value, str) and value in {"$value", "${value}"}:
        return copy.deepcopy(selected)
    if isinstance(value, str):
        return value.replace("${value}", str(selected)).replace("$value", str(selected))
    if isinstance(value, list):
        return [render(item, selected) for item in value]
    if isinstance(value, dict):
        return {key: render(item, selected) for key, item in value.items()}
    return copy.deepcopy(value)


def operations_for(variable: dict[str, Any], selected: Any) -> list[dict[str, Any]]:
    if "operation" in variable and "operations" in variable:
        raise ValueError(f"{variable.get('id')} defines both operation and operations")
    templates = variable.get("operations")
    if templates is None:
        templates = [variable.get("operation")]
    if not isinstance(templates, list) or not templates or any(not isinstance(item, dict) for item in templates):
        raise ValueError(f"{variable.get('id')} requires operation or operations")
    output = [render(item, selected) for item in templates]
    for operation in output:
        if operation.get("type") not in OPERATIONS:
            raise ValueError(f"unsupported operation: {operation.get('type')}")
    return output


def validate_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    if spec.get("schema") != "cannonlab-variant-search-v1":
        raise ValueError("unsupported variant-search schema")
    variables = spec.get("variables")
    if not isinstance(variables, list) or not variables:
        raise ValueError("variables must be non-empty")
    ids: list[str] = []
    total = 1
    for index, variable in enumerate(variables):
        if not isinstance(variable, dict):
            raise ValueError(f"variables[{index}] must be an object")
        variable_id = str(variable.get("id", "")).strip()
        values = variable.get("values")
        if not variable_id or not isinstance(values, list) or not values:
            raise ValueError(f"invalid variable at index {index}")
        if len(values) > 32:
            raise ValueError(f"{variable_id} exceeds 32 values")
        ids.append(variable_id)
        total *= len(values)
        for value in values:
            operations_for(variable, value)
    if len(ids) != len(set(ids)):
        raise ValueError("variable ids must be unique")
    maximum = int(spec.get("max_candidates", 32))
    if maximum < 1 or maximum > 128:
        raise ValueError("max_candidates must be 1..128")
    if total > maximum:
        raise ValueError(f"declared Cartesian search has {total} candidates, above max_candidates={maximum}")
    return variables


def combinations(variables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = [str(item["id"]) for item in variables]
    domains = [item["values"] for item in variables]
    return [dict(zip(ids, values, strict=True)) for values in itertools.product(*domains)]


def variant_id(index: int, selected: dict[str, Any]) -> str:
    raw = json.dumps(selected, sort_keys=True, separators=(",", ":"), default=str)
    return f"v{index:03d}-{hashlib.sha256(raw.encode()).hexdigest()[:10]}"


def mutation_plan(spec: dict[str, Any], parent: Path, job: str, identity: str,
                  selected: dict[str, Any], variables: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(item["id"]): item for item in variables}
    operations: list[dict[str, Any]] = []
    labels: list[str] = []
    for key, value in selected.items():
        variable = by_id[key]
        operations.extend(operations_for(variable, value))
        labels.append(str(render(variable.get("declared_variable", f"{key}=$value"), value)))
    output = OUTPUT_ROOT / "cannonlab-variant-search" / job / f"{identity}.schem"
    return {
        "schema": "cannonlab-bounded-mutation-plan-v1",
        "job": f"{job}-{identity}",
        "parent": str(parent),
        "output": str(output),
        "data_version": int(spec.get("data_version", 3465)),
        "declared_variable": "; ".join(labels),
        "max_changed_blocks": int(spec.get("max_changed_blocks", max(1, len(operations)))),
        "chunk_limit": int(spec.get("chunk_limit", 160)),
        "require_ec160_safe": spec.get("require_ec160_safe") is True,
        "operations": operations,
        "preservation": copy.deepcopy(spec.get("preservation", {})),
    }


def static_score(result: dict[str, Any]) -> float | None:
    if str(result.get("status", "")).upper() != "PASS":
        return None
    preservation = result.get("preservation") or {}
    summary = preservation.get("summary") or {}
    alignment = result.get("alignment") or {}
    paste = ((alignment.get("dispensers") or {}).get("worldedit_paste_point_alignment") or {})
    best = paste.get("best") or {}
    return round(
        1000.0
        + min(256.0, float(paste.get("safe_count") or 0)) * 0.5
        - float(best.get("max") or 10000) * 0.25
        - float(summary.get("risk_score") or 0) * 10
        - float(result.get("changed_blocks") or 0) * 2
        - float(summary.get("structural_change_ratio") or 0) * 1000
        - float(summary.get("functional_change_ratio") or 0) * 500,
        6,
    )


def generate(
    spec_raw: str,
    *,
    apply: bool = True,
    workers: int | None = None,
    use_cache: bool = True,
    timeout_seconds: int = 1200,
) -> dict[str, Any]:
    started = time.perf_counter()
    spec_path = allowed_path(spec_raw)
    spec = load_json(spec_path)
    variables = validate_spec(spec)
    parent = allowed_path(spec.get("parent", ""))
    if not parent.is_file() or parent.suffix.lower() not in {".schem", ".litematic"}:
        raise ValueError("parent must be a .schem or .litematic")
    job = slugify(str(spec.get("job") or spec_path.stem))
    job_dir = VARIANT_ROOT / job
    plans = job_dir / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    parent_sha256 = sha256(parent)
    requested_workers = workers if workers is not None else int(spec.get("workers", min(4, os.cpu_count() or 1)))
    resolved_workers = max(1, min(16, requested_workers))
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    candidates: list[dict[str, Any]] = []
    prepared: list[dict[str, Any]] = []
    for index, selected in enumerate(combinations(variables)):
        identity = variant_id(index, selected)
        plan = mutation_plan(spec, parent, job, identity, selected, variables)
        plan_path = plans / f"{identity}.json"
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        prepared.append({
            "variant_id": identity,
            "selected": selected,
            "plan": plan,
            "plan_path": plan_path,
            "mutation_plan": str(plan_path.relative_to(ROOT)).replace("\\", "/"),
        })

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in prepared:
        key = mutation_cache_key(row["plan"], parent_sha256)
        row["cache_key"] = key
        groups.setdefault(key, []).append(row)

    unique_rows = [rows[0] for rows in groups.values()]
    outcomes: dict[str, tuple[int, dict[str, Any], dict[str, Any]]] = {}
    if apply:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(resolved_workers, len(unique_rows) or 1)) as pool:
            future_map = {
                pool.submit(
                    apply_unique_plan,
                    row["plan_path"],
                    row["plan"],
                    parent_sha256=parent_sha256,
                    use_cache=use_cache,
                    timeout_seconds=timeout_seconds,
                ): row["cache_key"]
                for row in unique_rows
            }
            for future in concurrent.futures.as_completed(future_map):
                key = future_map[future]
                try:
                    outcomes[key] = future.result()
                except Exception as exc:  # fail closed while preserving every candidate row
                    outcomes[key] = (
                        1,
                        {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"},
                        {"cache_key": key, "cache_hit": False, "elapsed_seconds": 0.0},
                    )
    else:
        for row in unique_rows:
            key = row["cache_key"]
            outcomes[key] = (
                0,
                {"status": "PLANNED", "output": {"path": row["plan"]["output"]}},
                {"cache_key": key, "cache_hit": False, "elapsed_seconds": 0.0},
            )

    for key, rows in groups.items():
        primary = rows[0]
        code, primary_result, performance = outcomes[key]
        primary_output = Path(str(primary["plan"]["output"])).resolve()
        for group_index, row in enumerate(rows):
            output = Path(str(row["plan"]["output"])).resolve()
            deduplicated_from = None if group_index == 0 else primary["variant_id"]
            if group_index > 0 and primary_output.is_file():
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(primary_output, output)
            result = clone_result_for_output(
                primary_result,
                output,
                cache_key=key,
                cache_hit=bool(performance.get("cache_hit")),
                deduplicated_from=deduplicated_from,
            )
            result["job"] = row["plan"].get("job")
            result["declared_variable"] = row["plan"].get("declared_variable")
            candidates.append({
                "variant_id": row["variant_id"],
                "selected": row["selected"],
                "mutation_plan": row["mutation_plan"],
                "mutation_exit_code": code,
                "mutation_status": result.get("status"),
                "static_score": static_score(result),
                "cache_key": key,
                "cache_hit": bool(performance.get("cache_hit")),
                "deduplicated_from": deduplicated_from,
                "elapsed_seconds": performance.get("elapsed_seconds", 0.0) if group_index == 0 else 0.0,
                "result": result,
            })
    candidates.sort(key=lambda row: (row["static_score"] is None, -float(row["static_score"] or -math.inf), row["variant_id"]))
    blockers = []
    if apply and not any(row["static_score"] is not None for row in candidates):
        blockers.append({"code": "no-static-candidate-passed", "message": "all bounded mutations failed"})
    payload = {
        "schema": "cannonlab-variant-search-manifest-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not blockers else "BLOCKED",
        "truth_boundary": "Static ranking measures preservation and placement pressure only, never cannon performance.",
        "job": job,
        "source_spec": str(spec_path.relative_to(ROOT)).replace("\\", "/"),
        "parent": {"path": str(parent), "sha256": parent_sha256},
        "candidate_count": len(candidates),
        "applied": apply,
        "performance": {
            "schema": "cannonlab-variant-search-performance-v1",
            "workers": resolved_workers,
            "timeout_seconds_per_unique_plan": timeout_seconds,
            "cache_enabled": use_cache,
            "cache_hits": sum(1 for key in groups if outcomes[key][2].get("cache_hit")),
            "cache_misses": sum(1 for key in groups if not outcomes[key][2].get("cache_hit")),
            "unique_mutation_plans": len(groups),
            "deduplicated_candidates": len(candidates) - len(groups),
            "avoided_mutator_invocations": (
                len(candidates) - len(groups)
                + sum(1 for key in groups if outcomes[key][2].get("cache_hit"))
            ),
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "truth_boundary": (
                "Parallelism and cache reuse reduce repeated static work only. Runtime campaigns still require "
                "fresh evidence unless their separate runtime fingerprint matches."
            ),
        },
        "runtime_contract": copy.deepcopy(spec.get("runtime_contract", {})),
        "candidates": candidates,
        "blockers": blockers,
    }
    manifest = job_dir / "manifest.json"
    payload["manifest"] = str(manifest.relative_to(ROOT)).replace("\\", "/")
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload



def compare_limit(value: float, operator: str, threshold: float) -> bool:
    return {
        "<=": value <= threshold,
        ">=": value >= threshold,
        "<": value < threshold,
        ">": value > threshold,
        "==": value == threshold,
    }[operator]


def runtime_contract(raw: Any) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        raise ValueError("runtime_contract is required")
    required = [str(item) for item in raw.get("required_metrics", [])]
    objectives = raw.get("objectives")
    limits = raw.get("hard_limits", [])
    if not required or not isinstance(objectives, list) or not objectives:
        raise ValueError("runtime_contract requires metrics and objectives")
    if not isinstance(limits, list):
        raise ValueError("hard_limits must be a list")
    normalized_objectives = []
    for item in objectives:
        if not isinstance(item, dict):
            raise ValueError("objective must be an object")
        metric = str(item.get("metric", ""))
        direction = str(item.get("direction", ""))
        weight = float(item.get("weight", 0))
        if metric not in required or direction not in {"min", "max"} or weight <= 0 or not math.isfinite(weight):
            raise ValueError(f"invalid objective: {item}")
        normalized_objectives.append({"metric": metric, "direction": direction, "weight": weight})
    normalized_limits = []
    for item in limits:
        if not isinstance(item, dict):
            raise ValueError("hard limit must be an object")
        metric = str(item.get("metric", ""))
        operator = str(item.get("op", ""))
        threshold = float(item.get("value"))
        if metric not in required or operator not in LIMIT_OPS:
            raise ValueError(f"invalid hard limit: {item}")
        normalized_limits.append({"metric": metric, "op": operator, "value": threshold})
    return required, normalized_objectives, normalized_limits


def materialize_winner(
    manifest: dict[str, Any],
    winner: dict[str, Any],
    output_directory: Path,
) -> dict[str, Any]:
    identity = str(winner.get("variant_id", "winner"))
    source_candidate = next(
        (
            row for row in manifest.get("candidates", [])
            if str(row.get("variant_id", "")) == identity
        ),
        {},
    )
    result = source_candidate.get("result") if isinstance(source_candidate, dict) else None
    result_output = result.get("output") if isinstance(result, dict) else None
    raw_path = result_output.get("path") if isinstance(result_output, dict) else None
    source_path: Path | None = None
    if raw_path:
        try:
            source_path = allowed_path(str(raw_path))
        except (ValueError, FileNotFoundError):
            source_path = None

    output_directory.mkdir(parents=True, exist_ok=True)
    copied_path: Path | None = None
    if source_path is not None and source_path.is_file() and source_path.suffix.lower() == ".schem":
        copied_path = output_directory / f"{identity}.schem"
        shutil.copy2(source_path, copied_path)

    handoff = {
        "schema": "cannonlab-variant-winner-handoff-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "READY" if copied_path is not None else "METADATA_ONLY",
        "winner": {
            "variant_id": identity,
            "selected": winner.get("selected", {}),
            "static_score": winner.get("static_score"),
            "runtime_score": winner.get("runtime_score"),
        },
        "source_candidate": (
            {"path": str(source_path), "sha256": sha256(source_path)}
            if source_path is not None else None
        ),
        "schematic": (
            {"path": str(copied_path), "sha256": sha256(copied_path)}
            if copied_path is not None else None
        ),
        "truth_boundary": (
            "This is the best local candidate under the declared runtime scorecard only. "
            "It is not automatically full-campaign-passed or ExtremeCraft-ready."
        ),
    }
    handoff_path = output_directory / "winner-handoff.json"
    handoff["handoff_path"] = str(handoff_path)
    handoff_path.write_text(json.dumps(handoff, indent=2) + "\n", encoding="utf-8")
    return handoff


def rank(manifest_raw: str, scorecard_raw: str) -> dict[str, Any]:
    manifest_path = allowed_path(manifest_raw)
    scorecard_path = allowed_path(scorecard_raw)
    manifest = load_json(manifest_path)
    scorecard = load_json(scorecard_path)
    if manifest.get("schema") != "cannonlab-variant-search-manifest-v1":
        raise ValueError("unsupported search manifest")
    if scorecard.get("schema") != "cannonlab-variant-runtime-scorecard-v1":
        raise ValueError("unsupported runtime scorecard")
    required, objectives, limits = runtime_contract(manifest.get("runtime_contract"))
    measurements = scorecard.get("variants")
    if not isinstance(measurements, dict):
        raise ValueError("scorecard variants must be an object")
    rows = []
    for candidate in manifest.get("candidates", []):
        identity = str(candidate.get("variant_id", ""))
        entry = measurements.get(identity)
        metrics_raw = entry.get("metrics") if isinstance(entry, dict) and isinstance(entry.get("metrics"), dict) else {}
        blockers = []
        if candidate.get("static_score") is None:
            blockers.append({"code": "static-gate-failed", "message": "candidate failed static gates"})
        missing = [metric for metric in required if metric not in metrics_raw]
        if missing:
            blockers.append({"code": "runtime-metrics-missing", "message": ",".join(missing)})
        metrics: dict[str, float] = {}
        for metric in required:
            if metric not in metrics_raw:
                continue
            try:
                value = float(metrics_raw[metric])
            except (TypeError, ValueError):
                blockers.append({"code": "runtime-metric-nonnumeric", "message": metric})
                continue
            if not math.isfinite(value):
                blockers.append({"code": "runtime-metric-nonfinite", "message": metric})
                continue
            metrics[metric] = value
        for limit in limits:
            metric = limit["metric"]
            if metric in metrics and not compare_limit(metrics[metric], limit["op"], limit["value"]):
                blockers.append({
                    "code": "runtime-hard-limit-failed",
                    "message": f"{metric}={metrics[metric]} not {limit['op']} {limit['value']}",
                })
        rows.append({
            "variant_id": identity,
            "selected": candidate.get("selected", {}),
            "static_score": candidate.get("static_score"),
            "metrics": metrics,
            "eligible": not blockers,
            "blockers": blockers,
        })
    eligible = [row for row in rows if row["eligible"]]
    ranges = {
        objective["metric"]: (
            min(row["metrics"][objective["metric"]] for row in eligible),
            max(row["metrics"][objective["metric"]] for row in eligible),
        )
        for objective in objectives
        if eligible
    }
    total_weight = sum(item["weight"] for item in objectives)
    for row in eligible:
        score = 0.0
        contributions = []
        for objective in objectives:
            metric = objective["metric"]
            value = row["metrics"][metric]
            minimum, maximum = ranges[metric]
            if minimum == maximum:
                normalized = 1.0
            elif objective["direction"] == "max":
                normalized = (value - minimum) / (maximum - minimum)
            else:
                normalized = (maximum - value) / (maximum - minimum)
            contribution = normalized * objective["weight"]
            score += contribution
            contributions.append({**objective, "value": value, "normalized": round(normalized, 9), "contribution": round(contribution, 9)})
        row["runtime_score"] = round(score / total_weight, 9)
        row["objective_contributions"] = contributions
    rows.sort(key=lambda row: (
        not row["eligible"],
        -float(row.get("runtime_score", -math.inf)),
        -float(row.get("static_score") or -math.inf),
        row["variant_id"],
    ))
    winner = next((row for row in rows if row["eligible"]), None)
    blockers = [] if winner else [{"code": "no-runtime-eligible-candidate", "message": "no candidate passed runtime gates"}]
    output = VARIANT_ROOT / slugify(str(manifest.get("job") or manifest_path.parent.name)) / "runtime-ranking.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    handoff = materialize_winner(manifest, winner, output.parent / "winner") if winner else None
    payload = {
        "schema": "cannonlab-variant-runtime-ranking-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if winner else "BLOCKED",
        "truth_boundary": "The winner is best only under the declared local metrics and is not automatically EC-ready.",
        "search_manifest": str(manifest_path),
        "runtime_scorecard": str(scorecard_path),
        "required_metrics": required,
        "objectives": objectives,
        "hard_limits": limits,
        "winner": winner,
        "winner_handoff": handoff,
        "ranking": rows,
        "blockers": blockers,
    }
    payload["ranking_report"] = str(output.relative_to(ROOT)).replace("\\", "/")
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic bounded variant search and runtime ranking")
    sub = parser.add_subparsers(dest="command", required=True)
    generate_parser = sub.add_parser("generate")
    generate_parser.add_argument("spec")
    generate_parser.add_argument("--no-apply", action="store_true")
    generate_parser.add_argument("--workers", type=int, default=None)
    generate_parser.add_argument("--no-cache", action="store_true")
    generate_parser.add_argument("--timeout-seconds", type=int, default=1200)
    rank_parser = sub.add_parser("rank")
    rank_parser.add_argument("manifest")
    rank_parser.add_argument("scorecard")
    args = parser.parse_args()
    result = (
        generate(
            args.spec,
            apply=not args.no_apply,
            workers=args.workers,
            use_cache=not args.no_cache,
            timeout_seconds=args.timeout_seconds,
        )
        if args.command == "generate"
        else rank(args.manifest, args.scorecard)
    )
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
