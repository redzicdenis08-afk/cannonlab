#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {number}: {exc}") from exc
        if isinstance(row, dict):
            rows.append(row)
    if not rows:
        raise ValueError("Session contains no JSON objects")
    return rows


def state_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("type") == "probe_tick" and isinstance(row.get("state"), dict)]


def first_separation(ticks: list[dict[str, Any]]) -> dict[str, Any] | None:
    previously_mounted = False
    for row in ticks:
        state = row["state"]
        mounted = bool(state.get("mounted"))
        if previously_mounted and not mounted:
            return row
        previously_mounted = mounted
    return None


def cancellation_transitions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    transitions: list[dict[str, Any]] = []
    for row in rows:
        if row.get("type") != "event_priority_stage" or not row.get("cancel_transition"):
            continue
        transitions.append({
            "server_tick": row.get("server_tick"),
            "age_ticks": row.get("age_ticks"),
            "event": row.get("event"),
            "priority": row.get("priority"),
            "candidate_plugins": row.get("candidate_plugins_at_priority", []),
            "details": {key: row.get(key) for key in ("vehicle", "target", "cause", "distance_squared") if key in row},
        })
    return transitions


def summarize(path: Path) -> dict[str, Any]:
    rows = load_rows(path)
    ticks = state_rows(rows)
    separation = first_separation(ticks)
    transitions = cancellation_transitions(rows)

    claim_counts = Counter()
    vehicle_claim_counts = Counter()
    mounted_ticks = 0
    collision_materials: Counter[str] = Counter()
    for row in ticks:
        state = row["state"]
        claim_counts[str(state.get("player_claim"))] += 1
        vehicle_claim_counts[str(state.get("vehicle_claim"))] += 1
        mounted_ticks += int(bool(state.get("mounted")))
        collision = state.get("vehicle_collision") or state.get("player_collision") or {}
        for material in collision.get("materials", []) if isinstance(collision, dict) else []:
            collision_materials[str(material)] += 1

    listener_candidates: dict[str, set[str]] = defaultdict(set)
    for transition in transitions:
        key = f"{transition.get('event')}@{transition.get('priority')}"
        listener_candidates[key].update(str(name) for name in transition.get("candidate_plugins", []))

    first_state = ticks[0]["state"] if ticks else {}
    last_state = ticks[-1]["state"] if ticks else {}
    result: dict[str, Any] = {
        "session_file": str(path),
        "session_id": rows[0].get("session_id"),
        "label": rows[0].get("label"),
        "rows": len(rows),
        "tick_samples": len(ticks),
        "mounted_ticks": mounted_ticks,
        "claims": dict(claim_counts),
        "vehicle_claims": dict(vehicle_claim_counts),
        "collision_materials": dict(collision_materials.most_common()),
        "cancellation_transitions": transitions,
        "listener_candidates": {key: sorted(value) for key, value in listener_candidates.items()},
        "start": {
            "player": [first_state.get("player_x"), first_state.get("player_y"), first_state.get("player_z")],
            "claim": first_state.get("player_claim"),
            "mounted": first_state.get("mounted"),
            "vehicle": first_state.get("vehicle_uuid"),
        },
        "end": {
            "player": [last_state.get("player_x"), last_state.get("player_y"), last_state.get("player_z")],
            "claim": last_state.get("player_claim"),
            "mounted": last_state.get("mounted"),
            "vehicle": last_state.get("vehicle_uuid"),
        },
    }

    if separation:
        state = separation["state"]
        result["first_separation"] = {
            "server_tick": separation.get("server_tick"),
            "age_ticks": separation.get("age_ticks"),
            "player": [state.get("player_x"), state.get("player_y"), state.get("player_z")],
            "player_claim": state.get("player_claim"),
            "vehicle_claim": state.get("vehicle_claim"),
            "player_collision": state.get("player_collision"),
            "vehicle_collision": state.get("vehicle_collision"),
        }
    else:
        result["first_separation"] = None

    likely: list[str] = []
    if transitions:
        likely.append("A cancellable Bukkit event changed from allowed to cancelled during the session.")
    if separation and not transitions:
        likely.append("Rider separation occurred without a captured Bukkit cancellation transition; inspect Sakura movement reconciliation or packet-level correction paths.")
    if separation:
        state = separation["state"]
        collision = state.get("vehicle_collision") or state.get("player_collision") or {}
        if collision.get("water_blocks", 0):
            likely.append("Separation happened while the rider/vehicle bounding box intersected water.")
        if collision.get("lava_blocks", 0):
            likely.append("Separation happened while the rider/vehicle bounding box intersected lava.")
        if collision.get("solid_blocks", 0):
            likely.append("Separation happened while the rider/vehicle bounding box intersected solid blocks.")
    result["interpretation"] = likely or ["No separation or cancellation transition was observed in the captured window."]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a PhaseGuardProbe JSONL session")
    parser.add_argument("session", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = summarize(args.session)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
