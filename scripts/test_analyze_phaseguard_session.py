#!/usr/bin/env python3
import json
import tempfile
from pathlib import Path

from analyze_phaseguard_session import summarize


def row(kind, tick, state=None, **extra):
    data = {"type": kind, "server_tick": tick, "age_ticks": tick, "session_id": "s", "label": "test"}
    if state is not None:
        data["state"] = state
    data.update(extra)
    return data


def main():
    mounted = {
        "mounted": True,
        "player_x": 1.0,
        "player_y": 65.0,
        "player_z": 1.0,
        "player_claim": "Attackers",
        "vehicle_claim": "Attackers",
        "vehicle_uuid": "v",
        "vehicle_collision": {"solid_blocks": 0, "water_blocks": 0, "lava_blocks": 0, "materials": ["AIR"]},
    }
    separated = {
        **{key: value for key, value in mounted.items() if key != "vehicle_collision"},
        "mounted": False,
        "player_x": 17.0,
        "player_claim": "Victims",
        "vehicle_claim": None,
        "vehicle_uuid": None,
        "player_collision": {"solid_blocks": 1, "water_blocks": 1, "lava_blocks": 0, "materials": ["OBSIDIAN", "WATER"]},
    }
    rows = [
        row("session_start", 0),
        row("probe_tick", 1, mounted),
        row("event_priority_stage", 2, event="vehicle_exit", priority="NORMAL", cancelled=True, previous_cancelled=False, cancel_transition=True, candidate_plugins_at_priority=["FactionsUUID"]),
        row("probe_tick", 2, separated),
        row("session_stop", 3),
    ]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "session.jsonl"
        path.write_text("\n".join(json.dumps(value) for value in rows) + "\n")
        result = summarize(path)
    assert result["first_separation"]["age_ticks"] == 2
    assert result["listener_candidates"]["vehicle_exit@NORMAL"] == ["FactionsUUID"]
    assert any("water" in line.lower() for line in result["interpretation"])
    print("phaseguard analyzer tests passed")


if __name__ == "__main__":
    main()
