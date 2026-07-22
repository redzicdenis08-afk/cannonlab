#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
mcp = FastMCP("CannonLab")


def _inside_root(raw: str | Path, *, must_exist: bool = True) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"path escapes CannonLab repository: {raw}")
    if must_exist and not path.exists():
        raise FileNotFoundError(path)
    return path


def _run_json(args: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode not in (0, 2):
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout={result.stdout[-4000:]}\nstderr={result.stderr[-4000:]}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"tool returned non-JSON output: {result.stdout[-4000:]}") from exc
    payload["_exit_code"] = result.returncode
    return payload


@mcp.tool()
def inspect_cannon(path: str, chunk_limit: int = 160) -> dict[str, Any]:
    """Decode a Sponge/Litematica cannon, audit EC limits, and map structural components."""
    source = _inside_root(path)
    audit = _run_json([
        sys.executable,
        str(SCRIPTS / "schem-audit.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])
    static_map = _run_json([
        sys.executable,
        str(SCRIPTS / "cannon-static-map.py"),
        str(source),
        "--chunk-limit",
        str(chunk_limit),
    ])
    return {"audit": audit, "static_map": static_map}


@mcp.tool()
def explain_shot(trace_path: str) -> dict[str, Any]:
    """Explain one causal-events.csv trace without inventing cannon subsystem labels."""
    trace = _inside_root(trace_path)
    return _run_json([
        sys.executable,
        str(SCRIPTS / "explain-causal-trace.py"),
        str(trace),
    ])


@mcp.tool()
def analyze_shot_quality(
    trace_or_results: str,
    impact_window: float = 12.0,
    max_trigger_to_first_dispense: int | None = None,
    min_largest_dispense_cohort: int | None = None,
    max_target_impact_radius: float | None = None,
    max_self_damage: int | None = None,
    require_falling_block: bool = False,
) -> dict[str, Any]:
    """Score firing latency, synchronized cohorts, target convergence, falling payload and cannon self-damage."""
    source = _inside_root(trace_or_results)
    args = [
        sys.executable,
        str(SCRIPTS / "analyze-causal-quality.py"),
        str(source),
        "--impact-window",
        str(impact_window),
    ]
    if max_trigger_to_first_dispense is not None:
        args += ["--max-trigger-to-first-dispense", str(max_trigger_to_first_dispense)]
    if min_largest_dispense_cohort is not None:
        args += ["--min-largest-dispense-cohort", str(min_largest_dispense_cohort)]
    if max_target_impact_radius is not None:
        args += ["--max-target-impact-radius", str(max_target_impact_radius)]
    if max_self_damage is not None:
        args += ["--max-self-damage", str(max_self_damage)]
    if require_falling_block:
        args.append("--require-falling-block")
    return _run_json(args)


@mcp.tool()
def audit_ec_calibration(evidence_path: str) -> dict[str, Any]:
    """Validate whether a live ExtremeCraft calibration evidence pack is complete enough to claim EC calibration."""
    evidence = _inside_root(evidence_path)
    return _run_json([
        sys.executable,
        str(SCRIPTS / "audit-ec-calibration.py"),
        str(evidence),
    ])


@mcp.tool()
def query_timeline(
    trace_path: str,
    event: str = "",
    start_tick: int = 0,
    end_tick: int = 10_000,
    limit: int = 500,
) -> list[dict[str, str]]:
    """Return filtered causal events from one shot."""
    import csv

    trace = _inside_root(trace_path)
    wanted = event.strip().upper()
    output: list[dict[str, str]] = []
    with trace.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            tick = int(row.get("tick") or 0)
            if tick < start_tick or tick > end_tick:
                continue
            if wanted and (row.get("event") or "").upper() != wanted:
                continue
            output.append(dict(row))
            if len(output) >= max(1, min(limit, 5000)):
                break
    return output


@mcp.tool()
def list_shot_traces(results_root: str = "lab-artifacts/results") -> list[str]:
    """List causal traces currently available in CannonLab artifacts."""
    root = _inside_root(results_root, must_exist=False)
    if not root.exists():
        return []
    return [
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in sorted(root.rglob("causal-events.csv"))
    ]


@mcp.tool()
def compare_shots(first_trace: str, second_trace: str) -> dict[str, Any]:
    """Compare two shot explanations by cohorts, event counts, timing, and confidence."""
    first = explain_shot(first_trace)
    second = explain_shot(second_trace)
    keys = [
        "event_counts",
        "dispense_cohorts",
        "entity_cohorts",
        "piston_cohorts",
        "explosion_ticks",
        "trace_confidence",
    ]
    return {
        "first": {key: first.get(key) for key in keys},
        "second": {key: second.get(key) for key in keys},
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
