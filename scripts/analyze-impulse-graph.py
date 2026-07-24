#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

EVENT_REQUIRED = {"tick", "event", "type", "uuid", "x", "y", "z", "vx", "vy", "vz", "fuse"}
CAUSAL_REQUIRED = {
    "tick", "sequence", "event", "component_id", "world_x", "world_y", "world_z",
    "item", "entity_uuid", "entity_type", "vx", "vy", "vz", "fuse",
}
FALLING_ITEMS = {"SAND", "RED_SAND", "GRAVEL"}


def read_rows(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing columns: {sorted(missing)}")
        rows = []
        for line, row in enumerate(reader, 2):
            clean = {key: (value or "").strip() for key, value in row.items()}
            clean["_line"] = str(line)
            rows.append(clean)
        return rows


def num(row: dict[str, str], key: str, default: float | None = None) -> float:
    raw = row.get(key, "")
    if raw == "" and default is not None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"line {row.get('_line', '?')}: invalid {key}={raw!r}") from exc


def integer(row: dict[str, str], key: str, default: int | None = None) -> int:
    raw = row.get(key, "")
    if raw == "" and default is not None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"line {row.get('_line', '?')}: invalid {key}={raw!r}") from exc


Vec = tuple[float, float, float]


def position(row: dict[str, str], causal: bool = False) -> Vec:
    prefix = "world_" if causal else ""
    return num(row, prefix + "x"), num(row, prefix + "y"), num(row, prefix + "z")


def velocity(row: dict[str, str]) -> Vec:
    return num(row, "vx", 0.0), num(row, "vy", 0.0), num(row, "vz", 0.0)


def sub(a: Vec, b: Vec) -> Vec:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def add(a: Vec, b: Vec) -> Vec:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def scale(v: Vec, value: float) -> Vec:
    return v[0] * value, v[1] * value, v[2] * value


def norm(v: Vec) -> float:
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def dist(a: Vec, b: Vec) -> float:
    return norm(sub(a, b))


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def rv(v: Vec, digits: int = 8) -> list[float]:
    return [round(value, digits) for value in v]


def entity_type(value: str) -> str:
    value = value.strip().upper()
    if value in {"TNT", "TNT_PRIMED", "PRIMED_TNT"}:
        return "PRIMED_TNT"
    return value or "UNKNOWN"


def item_matches(kind: str, item: str) -> bool:
    item = item.strip().upper()
    if entity_type(kind) == "PRIMED_TNT":
        return item == "TNT"
    if entity_type(kind) == "FALLING_BLOCK":
        return item in FALLING_ITEMS or item.endswith("_CONCRETE_POWDER")
    return True


def passive_prediction(kind: str, before: Vec, ticks: int, model: str, gravity: float, drag: float) -> Vec:
    if model == "none" or entity_type(kind) not in {"PRIMED_TNT", "FALLING_BLOCK"}:
        return before
    if model != "nominal-air":
        raise ValueError(f"unsupported motion model: {model}")
    value = before
    for _ in range(ticks):
        value = value[0] * drag, (value[1] - gravity) * drag, value[2] * drag
    return value


def source_for(
    add_row: dict[str, str] | None,
    dispenses: list[dict[str, str]],
    window: int,
    radius: float,
) -> dict[str, Any]:
    if add_row is None:
        return {"confidence": "missing-entity-add", "candidates": []}
    tick = integer(add_row, "tick")
    spawn = position(add_row, True)
    kind = entity_type(add_row.get("entity_type", ""))
    found = []
    for row in dispenses:
        delta = tick - integer(row, "tick")
        if not 0 <= delta <= window or not item_matches(kind, row.get("item", "")):
            continue
        source = position(row, True)
        gap = dist(spawn, source)
        if gap > radius:
            continue
        found.append({
            "component_id": row.get("component_id", ""),
            "item": row.get("item", ""),
            "dispense_tick": integer(row, "tick"),
            "spawn_tick": tick,
            "tick_delta": delta,
            "distance": round(gap, 8),
            "position": rv(source),
            "score": round(delta * 10.0 + gap, 8),
        })
    found.sort(key=lambda row: (row["score"], row["component_id"]))
    confidence = (
        "unmatched" if not found else
        "high" if len(found) == 1 else
        "medium" if found[1]["score"] - found[0]["score"] >= 0.5 else
        "ambiguous"
    )
    return {"confidence": confidence, "candidates": found}


def explosion_sources(
    entity_uuid: str,
    before_pos: Vec,
    after_pos: Vec,
    residual: Vec,
    residual_size: float,
    before_tick: int,
    after_tick: int,
    explosions_by_tick: dict[int, list[dict[str, str]]],
    tick_slack: int,
    radius: float,
    min_cosine: float,
) -> list[dict[str, Any]]:
    midpoint = scale(add(before_pos, after_pos), 0.5)
    candidates = []
    for tick in range(before_tick - tick_slack, after_tick + tick_slack + 1):
        for row in explosions_by_tick.get(tick, []):
            source_uuid = row.get("entity_uuid", "")
            if source_uuid and source_uuid == entity_uuid:
                continue
            source = position(row, True)
            gap = dist(midpoint, source)
            if gap > radius:
                continue
            outward = sub(midpoint, source)
            outward_size = norm(outward)
            radial = cosine = None
            support = "spatial-overlap"
            if outward_size > 1.0e-9 and residual_size > 1.0e-12:
                radial = dot(residual, scale(outward, 1.0 / outward_size))
                cosine = radial / residual_size
                if radial <= 0 or cosine < min_cosine:
                    continue
                support = "outward"
            source_tick = integer(row, "tick")
            temporal = max(before_tick - source_tick, source_tick - after_tick, 0)
            score = temporal * 20.0 + gap + (0.0 if cosine is None else (1.0 - cosine) * 4.0)
            candidates.append({
                "source_event": row.get("event", ""),
                "source_uuid": source_uuid or None,
                "source_tick": source_tick,
                "source_sequence": integer(row, "sequence", 0),
                "source_position": rv(source),
                "distance": round(gap, 8),
                "directional_support": support,
                "radial_velocity_delta": None if radial is None else round(radial, 8),
                "alignment_cosine": None if cosine is None else round(cosine, 8),
                "score": round(score, 8),
            })
    candidates.sort(key=lambda row: (row["score"], row["source_tick"], row["source_sequence"]))
    return candidates


def confidence_for(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "unexplained"
    if len(candidates) == 1:
        cosine = candidates[0]["alignment_cosine"]
        return "high" if cosine is not None and cosine >= 0.8 else "medium"
    return "medium" if candidates[1]["score"] - candidates[0]["score"] >= 1.0 else "ambiguous"


def terminal(entity_uuid: str, explosions: list[dict[str, str]]) -> dict[str, Any] | None:
    for row in explosions:
        if row.get("entity_uuid", "") == entity_uuid:
            return {
                "tick": integer(row, "tick"),
                "sequence": integer(row, "sequence", 0),
                "position": rv(position(row, True)),
                "entity_type": entity_type(row.get("entity_type", "")),
                "details": row.get("details", ""),
            }
    return None


def match_keys(entities: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in entities:
        groups[(row["entity_type"], row["spawn_tick"])].append(row)
    for (kind, tick), rows in groups.items():
        rows.sort(key=lambda row: (
            tuple(row["initial_position"]),
            tuple(row["initial_velocity"]),
            row["initial_fuse"],
            tuple(item["component_id"] for item in row["source"]["candidates"]),
            row["uuid"],
        ))
        for ordinal, row in enumerate(rows, 1):
            row["match_key"] = f"{kind}@{tick}|{ordinal:04d}"


def cohorts(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in entities:
        groups[(row["entity_type"], row["spawn_tick"])].append(row)
    output = []
    for (kind, tick), rows in sorted(groups.items()):
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            counts[row["source"]["confidence"]] += 1
        output.append({
            "entity_type": kind,
            "spawn_tick": tick,
            "count": len(rows),
            "source_confidence": dict(sorted(counts.items())),
            "match_keys": sorted(row["match_key"] for row in rows),
        })
    return output


def build_graph(
    events_path: Path,
    causal_path: Path,
    *,
    source_window_ticks: int = 2,
    max_source_distance: float = 2.5,
    explosion_tick_slack: int = 1,
    max_explosion_distance: float = 8.0,
    min_velocity_residual: float = 0.05,
    min_alignment_cosine: float = 0.25,
    motion_model: str = "nominal-air",
    gravity: float = 0.04,
    drag: float = 0.98,
) -> dict[str, Any]:
    events = read_rows(events_path, EVENT_REQUIRED)
    causal = read_rows(causal_path, CAUSAL_REQUIRED)
    trajectories: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in events:
        if row.get("event", "").upper() == "ENTITY":
            if not row.get("uuid"):
                raise ValueError(f"line {row.get('_line')}: ENTITY row lacks uuid")
            trajectories[row["uuid"]].append(row)
    if not trajectories:
        raise ValueError(f"{events_path} contains no ENTITY trajectories")
    for entity_uuid, rows in trajectories.items():
        rows.sort(key=lambda row: integer(row, "tick"))
        ticks = [integer(row, "tick") for row in rows]
        if len(ticks) != len(set(ticks)):
            raise ValueError(f"duplicate trajectory sample for {entity_uuid}")

    adds: dict[str, dict[str, str]] = {}
    dispenses = []
    explosions = []
    explosions_by_tick: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in causal:
        event = row.get("event", "").upper()
        if event == "ENTITY_ADD":
            uuid = row.get("entity_uuid", "")
            if not uuid or uuid in adds:
                raise ValueError(f"invalid or duplicate ENTITY_ADD at line {row.get('_line')}")
            adds[uuid] = row
        elif event == "DISPENSE":
            dispenses.append(row)
        elif event in {"EXPLOSION", "BLOCK_EXPLOSION"}:
            explosions.append(row)
            explosions_by_tick[integer(row, "tick")].append(row)
    explosions.sort(key=lambda row: (integer(row, "tick"), integer(row, "sequence", 0)))

    entities = []
    for uuid, rows in sorted(trajectories.items()):
        first, last = rows[0], rows[-1]
        add_row = adds.get(uuid)
        kind = entity_type(add_row.get("entity_type", "") if add_row else first.get("type", ""))
        source = source_for(add_row, dispenses, source_window_ticks, max_source_distance)
        changes = []
        for before, after in zip(rows, rows[1:]):
            before_tick, after_tick = integer(before, "tick"), integer(after, "tick")
            if after_tick <= before_tick:
                raise ValueError(f"non-increasing trajectory ticks for {uuid}")
            tick_gap = after_tick - before_tick
            before_velocity, after_velocity = velocity(before), velocity(after)
            predicted = passive_prediction(kind, before_velocity, tick_gap, motion_model, gravity, drag)
            residual = sub(after_velocity, predicted)
            residual_size = norm(residual)
            if residual_size < min_velocity_residual:
                continue
            candidates = explosion_sources(
                uuid, position(before), position(after), residual, residual_size,
                before_tick, after_tick, explosions_by_tick, explosion_tick_slack,
                max_explosion_distance, min_alignment_cosine,
            )
            raw_delta = sub(after_velocity, before_velocity)
            changes.append({
                "before_tick": before_tick,
                "after_tick": after_tick,
                "tick_gap": tick_gap,
                "before_position": rv(position(before)),
                "after_position": rv(position(after)),
                "before_velocity": rv(before_velocity),
                "after_velocity": rv(after_velocity),
                "observed_velocity_delta": rv(raw_delta),
                "observed_delta_magnitude": round(norm(raw_delta), 8),
                "passive_motion_model": motion_model,
                "passive_predicted_velocity": rv(predicted),
                "passive_velocity_residual": rv(residual),
                "passive_residual_magnitude": round(residual_size, 8),
                "confidence": confidence_for(candidates),
                "source_candidates": candidates,
            })
        spawn_tick = integer(add_row, "tick") if add_row else integer(first, "tick")
        initial_pos = position(add_row, True) if add_row else position(first)
        initial_vel = velocity(add_row) if add_row else velocity(first)
        speeds = [norm(velocity(row)) for row in rows]
        entities.append({
            "uuid": uuid,
            "entity_type": kind,
            "spawn_tick": spawn_tick,
            "sample_count": len(rows),
            "first_sample_tick": integer(first, "tick"),
            "last_sample_tick": integer(last, "tick"),
            "initial_position": rv(initial_pos),
            "final_position": rv(position(last)),
            "initial_velocity": rv(initial_vel),
            "final_velocity": rv(velocity(last)),
            "initial_fuse": integer(add_row, "fuse", -1) if add_row else integer(first, "fuse", -1),
            "maximum_speed": round(max(speeds, default=0.0), 8),
            "displacement": round(dist(position(first), position(last)), 8),
            "source": source,
            "impulse_edges": [row for row in changes if row["source_candidates"]],
            "unexplained_abrupt_changes": [row for row in changes if not row["source_candidates"]],
            "terminal_explosion": terminal(uuid, explosions),
        })

    match_keys(entities)
    entities.sort(key=lambda row: row["match_key"])
    ambiguous = sum(
        edge["confidence"] == "ambiguous"
        for row in entities for edge in row["impulse_edges"]
    )
    unexplained = sum(len(row["unexplained_abrupt_changes"]) for row in entities)
    source_counts: dict[str, int] = defaultdict(int)
    for row in entities:
        source_counts[row["source"]["confidence"]] += 1
    return {
        "schema_version": 1,
        "status": "WARN" if ambiguous or unexplained else "PASS",
        "events": str(events_path),
        "causal_events": str(causal_path),
        "parameters": {
            "source_window_ticks": source_window_ticks,
            "max_source_distance": max_source_distance,
            "explosion_tick_slack": explosion_tick_slack,
            "max_explosion_distance": max_explosion_distance,
            "min_velocity_residual": min_velocity_residual,
            "min_alignment_cosine": min_alignment_cosine,
            "motion_model": motion_model,
            "gravity": gravity,
            "drag": drag,
        },
        "summary": {
            "entity_count": len(entities),
            "trajectory_sample_count": sum(row["sample_count"] for row in entities),
            "explosion_count": len(explosions),
            "impulse_edge_count": sum(len(row["impulse_edges"]) for row in entities),
            "ambiguous_impulse_edge_count": ambiguous,
            "unexplained_abrupt_change_count": unexplained,
            "source_confidence": dict(sorted(source_counts.items())),
        },
        "cohorts": cohorts(entities),
        "entities": entities,
        "truth_boundary": {
            "observed_velocity_delta_is_recorded": True,
            "exact_vanilla_push_recreated": False,
            "passive_motion_baseline_is_declared_not_parity_proof": True,
            "block_exposure_or_occlusion_recreated": False,
            "collision_and_fluid_causes_fully_observed": False,
            "multiple_explosion_sources_may_remain_ambiguous": True,
            "private_server_parity_confirmed": False,
            "note": (
                "Edges are conservative candidates for abrupt passive-motion residuals. "
                "They do not exclude collisions, fluids, pistons, server patches or plugins."
            ),
        },
    }


def vector_gap(left: Iterable[float], right: Iterable[float]) -> float:
    values = tuple(float(a) - float(b) for a, b in zip(left, right))
    return norm(values)  # type: ignore[arg-type]


def relative(point: Iterable[float], origin: Iterable[float]) -> list[float]:
    values = tuple(float(a) - float(b) for a, b in zip(point, origin))
    return rv(values)  # type: ignore[arg-type]


def compare_graphs(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    *,
    max_timing_delta: int = 1,
    max_velocity_delta: float = 0.05,
    max_position_delta: float = 0.5,
) -> dict[str, Any]:
    left_map = {row["match_key"]: row for row in reference["entities"]}
    right_map = {row["match_key"]: row for row in candidate["entities"]}
    drift = []
    for key in sorted(set(left_map) | set(right_map)):
        left, right = left_map.get(key), right_map.get(key)
        if left is None or right is None:
            present = right if left is None else left
            drift.append({
                "tick": present["spawn_tick"],
                "match_key": key,
                "kind": "extra_candidate_entity" if left is None else "missing_candidate_entity",
            })
            continue
        left_sources = [row["component_id"] for row in left["source"]["candidates"]]
        right_sources = [row["component_id"] for row in right["source"]["candidates"]]
        if left_sources != right_sources:
            drift.append({
                "tick": min(left["spawn_tick"], right["spawn_tick"]),
                "match_key": key, "kind": "source_candidate_drift",
                "reference": left_sources, "candidate": right_sources,
            })
        if abs(left["spawn_tick"] - right["spawn_tick"]) > max_timing_delta:
            drift.append({
                "tick": min(left["spawn_tick"], right["spawn_tick"]),
                "match_key": key, "kind": "spawn_timing_drift",
                "reference": left["spawn_tick"], "candidate": right["spawn_tick"],
            })
        left_edges, right_edges = left["impulse_edges"], right["impulse_edges"]
        if len(left_edges) != len(right_edges):
            drift.append({
                "tick": min(
                    left_edges[0]["before_tick"] if left_edges else left["spawn_tick"],
                    right_edges[0]["before_tick"] if right_edges else right["spawn_tick"],
                ),
                "match_key": key, "kind": "impulse_edge_count_drift",
                "reference": len(left_edges), "candidate": len(right_edges),
            })
        for index, (left_edge, right_edge) in enumerate(zip(left_edges, right_edges), 1):
            timing = max(
                abs(left_edge["before_tick"] - right_edge["before_tick"]),
                abs(left_edge["after_tick"] - right_edge["after_tick"]),
            )
            if timing > max_timing_delta:
                drift.append({
                    "tick": min(left_edge["before_tick"], right_edge["before_tick"]),
                    "match_key": key, "kind": "impulse_timing_drift", "edge": index,
                    "reference": [left_edge["before_tick"], left_edge["after_tick"]],
                    "candidate": [right_edge["before_tick"], right_edge["after_tick"]],
                })
            velocity_drift = vector_gap(
                left_edge["passive_velocity_residual"],
                right_edge["passive_velocity_residual"],
            )
            if velocity_drift > max_velocity_delta:
                drift.append({
                    "tick": min(left_edge["after_tick"], right_edge["after_tick"]),
                    "match_key": key, "kind": "impulse_velocity_drift", "edge": index,
                    "distance": round(velocity_drift, 8),
                    "reference": left_edge["passive_velocity_residual"],
                    "candidate": right_edge["passive_velocity_residual"],
                    "reference_raw_delta": left_edge["observed_velocity_delta"],
                    "candidate_raw_delta": right_edge["observed_velocity_delta"],
                })
        left_terminal, right_terminal = left["terminal_explosion"], right["terminal_explosion"]
        if (left_terminal is None) != (right_terminal is None):
            value = left_terminal or right_terminal
            drift.append({
                "tick": value["tick"], "match_key": key,
                "kind": "terminal_explosion_presence_drift",
                "reference": left_terminal is not None,
                "candidate": right_terminal is not None,
            })
        elif left_terminal and right_terminal:
            if abs(left_terminal["tick"] - right_terminal["tick"]) > max_timing_delta:
                drift.append({
                    "tick": min(left_terminal["tick"], right_terminal["tick"]),
                    "match_key": key, "kind": "terminal_explosion_timing_drift",
                    "reference": left_terminal["tick"], "candidate": right_terminal["tick"],
                })
            left_pos = relative(left_terminal["position"], left["initial_position"])
            right_pos = relative(right_terminal["position"], right["initial_position"])
            position_drift = vector_gap(left_pos, right_pos)
            if position_drift > max_position_delta:
                drift.append({
                    "tick": min(left_terminal["tick"], right_terminal["tick"]),
                    "match_key": key, "kind": "terminal_explosion_position_drift",
                    "distance": round(position_drift, 8),
                    "reference_relative": left_pos, "candidate_relative": right_pos,
                })
    drift.sort(key=lambda row: (row["tick"], row["match_key"], row["kind"]))
    return {
        "status": "FAIL" if drift else "PASS",
        "thresholds": {
            "max_timing_delta": max_timing_delta,
            "max_velocity_delta": max_velocity_delta,
            "max_position_delta": max_position_delta,
        },
        "matched_entities": len(set(left_map) & set(right_map)),
        "reference_entities": len(left_map),
        "candidate_entities": len(right_map),
        "divergence_count": len(drift),
        "first_divergence": drift[0] if drift else None,
        "divergences": drift,
        "truth_boundary": {
            "matching_uses_entity_type_spawn_tick_and_stable_ordinal": True,
            "global_translation_normalized_for_terminal_position": True,
            "module_semantics_proven": False,
            "private_server_parity_proven": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an evidence-first CannonLab explosion-to-entity impulse graph."
    )
    parser.add_argument("events", type=Path)
    parser.add_argument("causal_events", type=Path)
    parser.add_argument("--compare-events", type=Path)
    parser.add_argument("--compare-causal-events", type=Path)
    parser.add_argument("--source-window-ticks", type=int, default=2)
    parser.add_argument("--max-source-distance", type=float, default=2.5)
    parser.add_argument("--explosion-tick-slack", type=int, default=1)
    parser.add_argument("--max-explosion-distance", type=float, default=8.0)
    parser.add_argument("--min-velocity-residual", type=float, default=0.05)
    parser.add_argument("--min-alignment-cosine", type=float, default=0.25)
    parser.add_argument("--motion-model", choices=("nominal-air", "none"), default="nominal-air")
    parser.add_argument("--gravity", type=float, default=0.04)
    parser.add_argument("--drag", type=float, default=0.98)
    parser.add_argument("--max-timing-delta", type=int, default=1)
    parser.add_argument("--max-velocity-delta", type=float, default=0.05)
    parser.add_argument("--max-position-delta", type=float, default=0.5)
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (args.compare_events is None) != (args.compare_causal_events is None):
        raise ValueError("--compare-events and --compare-causal-events must be supplied together")
    if args.source_window_ticks < 0 or args.explosion_tick_slack < 0:
        raise ValueError("tick windows must be non-negative")
    if args.max_source_distance <= 0 or args.max_explosion_distance <= 0:
        raise ValueError("distance limits must be positive")
    if args.min_velocity_residual < 0 or args.max_velocity_delta < 0:
        raise ValueError("velocity thresholds must be non-negative")
    if args.gravity < 0 or not 0 < args.drag <= 1:
        raise ValueError("gravity/drag values are invalid")
    options = {
        "source_window_ticks": args.source_window_ticks,
        "max_source_distance": args.max_source_distance,
        "explosion_tick_slack": args.explosion_tick_slack,
        "max_explosion_distance": args.max_explosion_distance,
        "min_velocity_residual": args.min_velocity_residual,
        "min_alignment_cosine": args.min_alignment_cosine,
        "motion_model": args.motion_model,
        "gravity": args.gravity,
        "drag": args.drag,
    }
    reference = build_graph(args.events, args.causal_events, **options)
    if args.compare_events is None:
        report = reference
    else:
        candidate = build_graph(args.compare_events, args.compare_causal_events, **options)
        comparison = compare_graphs(
            reference, candidate,
            max_timing_delta=args.max_timing_delta,
            max_velocity_delta=args.max_velocity_delta,
            max_position_delta=args.max_position_delta,
        )
        report = {
            "schema_version": 1,
            "status": comparison["status"],
            "reference": reference,
            "candidate": candidate,
            "comparison": comparison,
        }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 2 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, csv.Error, json.JSONDecodeError) as exc:
        print(f"analyze-impulse-graph: {exc}", file=sys.stderr)
        raise SystemExit(3)
