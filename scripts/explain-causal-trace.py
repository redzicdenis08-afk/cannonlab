#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def integer(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(row.get(key) or default)
    except ValueError:
        return default


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key) or default)
    except ValueError:
        return default


def read_trace(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"tick", "sequence", "event", "component_id", "entity_uuid", "entity_type"}
    missing = required - set(rows[0] if rows else {})
    if missing:
        raise ValueError(f"trace is missing columns: {sorted(missing)}")
    rows.sort(key=lambda row: (integer(row, "tick"), integer(row, "sequence")))
    return rows


def group_ticks(rows: list[dict[str, str]], events: set[str]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("event") in events:
            grouped[integer(row, "tick")].append(row)
    output = []
    for tick, cohort in sorted(grouped.items()):
        output.append({
            "tick": tick,
            "count": len(cohort),
            "events": dict(Counter(row.get("event", "") for row in cohort)),
            "items": dict(Counter(row.get("item", "") for row in cohort if row.get("item"))),
            "entity_types": dict(Counter(row.get("entity_type", "") for row in cohort if row.get("entity_type"))),
            "components": sorted({row.get("component_id", "") for row in cohort if row.get("component_id")}),
        })
    return output


def redstone_edges(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    edges = []
    for row in rows:
        if row.get("event") != "REDSTONE_CHANGE":
            continue
        old = integer(row, "old_power", -1)
        new = integer(row, "new_power", -1)
        edges.append({
            "tick": integer(row, "tick"),
            "component": row.get("component_id", ""),
            "old": old,
            "new": new,
            "edge": "rise" if new > old else "fall" if new < old else "flat",
        })
    return edges


def piston_cohorts(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("event") not in {"PISTON_EXTEND", "PISTON_RETRACT"}:
            continue
        grouped[(integer(row, "tick"), row.get("event", ""))].append(row)
    output = []
    for (tick, event), cohort in sorted(grouped.items()):
        output.append({
            "tick": tick,
            "event": event,
            "pistons": len(cohort),
            "moved_blocks": sum(integer(row, "moved_blocks") for row in cohort),
            "directions": dict(Counter(row.get("direction", "") for row in cohort if row.get("direction"))),
            "components": sorted(row.get("component_id", "") for row in cohort),
        })
    return output


def entity_spawn_cohorts(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("event") != "ENTITY_ADD":
            continue
        grouped[(integer(row, "tick"), row.get("entity_type", "UNKNOWN"))].append(row)
    output = []
    for (tick, entity_type), cohort in sorted(grouped.items()):
        fuses = [integer(row, "fuse", -1) for row in cohort if integer(row, "fuse", -1) >= 0]
        speeds = [
            math.sqrt(number(row, "vx") ** 2 + number(row, "vy") ** 2 + number(row, "vz") ** 2)
            for row in cohort
        ]
        output.append({
            "tick": tick,
            "entity_type": entity_type,
            "count": len(cohort),
            "fuse_min": min(fuses) if fuses else None,
            "fuse_max": max(fuses) if fuses else None,
            "speed_mean": round(statistics.fmean(speeds), 8) if speeds else 0.0,
            "uuids": [row.get("entity_uuid", "") for row in cohort],
        })
    return output


def correlate_dispense_to_spawn(
    dispense: list[dict[str, Any]],
    entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output = []
    for cohort in dispense:
        candidates = [
            entity for entity in entities
            if 0 <= entity["tick"] - cohort["tick"] <= 2
        ]
        output.append({
            "dispense_tick": cohort["tick"],
            "dispensers": cohort["count"],
            "items": cohort["items"],
            "spawn_candidates": [
                {
                    "tick": candidate["tick"],
                    "entity_type": candidate["entity_type"],
                    "count": candidate["count"],
                }
                for candidate in candidates
            ],
            "correlation": "timing-near" if candidates else "unmatched",
        })
    return output


def explosion_ticks(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("event") in {"EXPLOSION", "BLOCK_EXPLOSION"}:
            grouped[integer(row, "tick")].append(row)
    return [
        {
            "tick": tick,
            "count": len(cohort),
            "entity_types": dict(Counter(row.get("entity_type", "") for row in cohort if row.get("entity_type"))),
        }
        for tick, cohort in sorted(grouped.items())
    ]


def candidate_roles(
    dispense: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    pistons: list[dict[str, Any]],
    explosions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    roles = []
    tnt_cohorts = [cohort for cohort in entities if cohort["entity_type"] in {"PRIMED_TNT", "TNT"}]
    falling_cohorts = [cohort for cohort in entities if cohort["entity_type"] == "FALLING_BLOCK"]
    if tnt_cohorts:
        first = min(tnt_cohorts, key=lambda cohort: cohort["tick"])
        roles.append({
            "candidate": "early-tnt-stage",
            "confidence": "medium",
            "evidence": f"first TNT entity cohort has {first['count']} entities at tick {first['tick']}",
            "not_proven": "Whether it is charge, hammer or another TNT stage requires motion/impact interpretation.",
        })
    if falling_cohorts:
        first = min(falling_cohorts, key=lambda cohort: cohort["tick"])
        roles.append({
            "candidate": "falling-block-payload-stage",
            "confidence": "high",
            "evidence": f"first falling-block cohort has {first['count']} entities at tick {first['tick']}",
            "not_proven": "Whether the payload is stacking, slab-busting, nuking or bypassing requires target behavior.",
        })
    if pistons:
        first = min(pistons, key=lambda cohort: cohort["tick"])
        roles.append({
            "candidate": "mechanical-alignment-or-mode-stage",
            "confidence": "low",
            "evidence": f"piston cohort begins at tick {first['tick']}",
            "not_proven": "Piston motion alone cannot identify alignment, reset, OSRB or mode selection.",
        })
    if explosions and tnt_cohorts:
        first_spawn = min(cohort["tick"] for cohort in tnt_cohorts)
        first_explosion = min(cohort["tick"] for cohort in explosions)
        roles.append({
            "candidate": "observed-tnt-lifetime",
            "confidence": "medium",
            "evidence": f"first TNT cohort to first explosion delta is {first_explosion - first_spawn} recorded ticks",
            "not_proven": "Multiple TNT cohorts can make this delta differ from an individual entity lifetime.",
        })
    return roles


def trace_confidence(rows: list[dict[str, str]], counts: Counter[str]) -> dict[str, Any]:
    requirements = {
        "redstone": counts["REDSTONE_CHANGE"] > 0,
        "dispense": counts["DISPENSE"] > 0,
        "entity_spawn": counts["ENTITY_ADD"] > 0,
        "explosion": counts["EXPLOSION"] + counts["BLOCK_EXPLOSION"] > 0,
    }
    present = sum(requirements.values())
    level = "high" if present == len(requirements) else "medium" if present >= 2 else "low"
    return {
        "level": level,
        "requirements": requirements,
        "note": "High trace confidence means the causal stages were observed, not that subsystem slang labels are proven.",
    }


def compact_timeline(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[integer(row, "tick")].append(row)
    timeline = []
    for tick, cohort in sorted(grouped.items()):
        counts = Counter(row.get("event", "") for row in cohort)
        if set(counts) == {"ENTITY"}:
            continue
        timeline.append({
            "tick": tick,
            "events": dict(counts),
            "components": sorted({row.get("component_id", "") for row in cohort if row.get("component_id")})[:30],
        })
    return timeline


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Cannon causal timeline",
        "",
        f"Trace confidence: **{report['trace_confidence']['level']}**",
        "",
        "## Event counts",
        "",
    ]
    for event, count in sorted(report["event_counts"].items()):
        lines.append(f"- `{event}`: {count}")
    lines.extend(["", "## Timeline", ""])
    for item in report["timeline"]:
        rendered = ", ".join(f"{event} x{count}" for event, count in item["events"].items())
        lines.append(f"- Tick {item['tick']}: {rendered}")
    lines.extend(["", "## Candidate interpretations", ""])
    for role in report["candidate_roles"]:
        lines.append(
            f"- **{role['candidate']}** ({role['confidence']}): {role['evidence']} "
            f"Not proven: {role['not_proven']}"
        )
    lines.extend([
        "",
        "Static names such as charge, hammer, booster, nuke, bypass and OSRB are never assigned from shape or filename alone.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain CannonLab causal-events.csv without inventing subsystem roles")
    parser.add_argument("trace", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()

    rows = read_trace(args.trace)
    counts = Counter(row.get("event", "") for row in rows)
    dispense = group_ticks(rows, {"DISPENSE"})
    entities = entity_spawn_cohorts(rows)
    pistons = piston_cohorts(rows)
    explosions = explosion_ticks(rows)
    report = {
        "status": "PASS",
        "trace": str(args.trace),
        "rows": len(rows),
        "tick_min": min((integer(row, "tick") for row in rows), default=0),
        "tick_max": max((integer(row, "tick") for row in rows), default=0),
        "event_counts": dict(sorted(counts.items())),
        "redstone_edges": redstone_edges(rows),
        "dispense_cohorts": dispense,
        "entity_cohorts": entities,
        "piston_cohorts": pistons,
        "dispense_spawn_correlation": correlate_dispense_to_spawn(dispense, entities),
        "explosion_ticks": explosions,
        "candidate_roles": candidate_roles(dispense, entities, pistons, explosions),
        "trace_confidence": trace_confidence(rows, counts),
        "timeline": compact_timeline(rows),
    }
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown(report), encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, indent=2), file=sys.stderr)
        raise SystemExit(3)
