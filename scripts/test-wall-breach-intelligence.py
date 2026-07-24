#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().with_name("wall-breach-intelligence.py")
SPEC = importlib.util.spec_from_file_location("wall_breach_intelligence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
breach = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = breach
SPEC.loader.exec_module(breach)

EVENT_HEADERS = [
    "tick", "event", "type", "uuid", "x", "y", "z", "vx", "vy", "vz", "fuse", "affected_blocks"
]
BREACH_HEADERS = [
    "tick", "event", "entity_uuid", "entity_type", "x", "y", "z", "target_contact",
    "center_block", "center_water_contact", "falling_overlap_evidence", "falling_uuid",
    "falling_material", "falling_distance", "affected_blocks"
]


def event(
    tick: int,
    kind: str,
    *,
    type_: str = "",
    uuid: str = "",
    x: float = 0.0,
    y: float = 100.0,
    z: float = 0.0,
    vx: float = 0.0,
    vy: float = 0.0,
    vz: float = 0.0,
    fuse: int = -1,
    affected: int = 0,
) -> dict[str, Any]:
    return {
        "tick": tick,
        "event": kind,
        "type": type_,
        "uuid": uuid,
        "x": x,
        "y": y,
        "z": z,
        "vx": vx,
        "vy": vy,
        "vz": vz,
        "fuse": fuse,
        "affected_blocks": affected,
    }


def breach_event(
    tick: int,
    *,
    x: float = 3.5,
    y: float = 101.5,
    z: float = 0.5,
    target: bool = True,
    water: bool = False,
    overlap: bool = False,
    falling_distance: float = -1.0,
) -> dict[str, Any]:
    return {
        "tick": tick,
        "event": "EXPLOSION",
        "entity_uuid": f"tnt-{tick}",
        "entity_type": "TNT",
        "x": x,
        "y": y,
        "z": z,
        "target_contact": str(target).lower(),
        "center_block": "WATER" if water else "AIR",
        "center_water_contact": str(water).lower(),
        "falling_overlap_evidence": str(overlap).lower(),
        "falling_uuid": "sand-1" if overlap else "",
        "falling_material": "SAND" if overlap else "",
        "falling_distance": falling_distance,
        "affected_blocks": 0,
    }


class RunFixture:
    def __init__(
        self,
        root: Path,
        *,
        target_type: str = "DRY",
        material: str = "OBSIDIAN",
        direction: str = "EAST",
        distance: int = 3,
        layers: int = 1,
        spacing: int = 3,
        regen: bool = False,
        durability_mode: str = "SIMULATE",
        contract_pass: bool = False,
        target_destroyed: int = 0,
        self_damage: int = 0,
        dispensers_initial: int = 4,
        dispensers_remaining: int = 4,
        regen_margin: int = -1,
    ) -> None:
        self.root = root
        self.events: list[dict[str, Any]] = []
        self.breach_rows: list[dict[str, Any]] = []
        self.summary = {
            "run_id": "fixture-run",
            "scenario": "fixture",
            "cannon_file": "fixture.schem",
            "target_type": target_type,
            "target_material": material,
            "target_direction": direction,
            "target_distance": distance,
            "target_layers": layers,
            "target_spacing": spacing,
            "target_bounds": {
                "min_x": distance if direction == "EAST" else -1,
                "min_y": 100,
                "min_z": -2,
                "max_x": distance if direction == "EAST" else 1,
                "max_y": 105,
                "max_z": 2,
            },
            "arena_origin": {"x": 0, "y": 100, "z": 0},
            "regeneration": {
                "enabled": regen,
                "delay_ticks": 20,
                "interval_ticks": 5,
                "max_blocks_per_cycle": 16,
            },
            "durability": {
                "configured_mode": durability_mode,
                "effective_mode": durability_mode,
                "expiration_ticks": 1200,
                "only_tnt": True,
                "hit_radius": 5.0,
            },
            "finish_reason": "complete",
            "shots_requested": 1,
            "shots_completed": 1,
            "shots": [{
                "shot": 1,
                "finish_reason": "quiet",
                "saw_payload": True,
                "explosions": 4,
                "target_blocks_destroyed": target_destroyed,
                "target_peak_destroyed": target_destroyed,
                "target_ever_destroyed": target_destroyed,
                "self_damage_blocks": self_damage,
                "cannon_initial_dispensers": dispensers_initial,
                "cannon_remaining_dispensers": dispensers_remaining,
                "maximum_forward_distance": float(distance),
                "regen_race_margin_ticks": regen_margin,
                "contract_pass": contract_pass,
                "error": None,
            }],
        }
        self.course = {
            "direction": direction,
            "stage_count": 1,
            "stages": [{
                "index": 0,
                "name": "legacy-target",
                "type": target_type,
                "start_distance": distance,
                "end_distance": distance + max(0, layers - 1) * spacing,
                "width": 5,
                "height": 6,
                "layers": layers,
                "spacing": spacing,
                "gap_after": 0,
                "regeneration": self.summary["regeneration"],
            }],
        }

    def write(self, *, include_breach: bool = True) -> Path:
        shot_dir = self.root / "shot-001"
        shot_dir.mkdir(parents=True, exist_ok=True)
        with (shot_dir / "events.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=EVENT_HEADERS)
            writer.writeheader()
            for row in self.events:
                writer.writerow(row)
        if include_breach:
            with (shot_dir / "breach-events.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=BREACH_HEADERS)
                writer.writeheader()
                for row in self.breach_rows:
                    writer.writerow(row)
        (self.root / "run-summary.json").write_text(
            json.dumps(self.summary, indent=2) + "\n", encoding="utf-8"
        )
        (self.root / "target-course.json").write_text(
            json.dumps(self.course, indent=2) + "\n", encoding="utf-8"
        )
        return self.root / "run-summary.json"


class WallBreachIntelligenceTests(unittest.TestCase):
    def analyze(self, fixture: RunFixture, contract: Any, *, include_breach: bool = True) -> dict[str, Any]:
        summary = fixture.write(include_breach=include_breach)
        return breach.analyze(summary, contract)

    def test_direct_four_hit_obsidian_sequence_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = RunFixture(Path(raw), target_destroyed=1, contract_pass=True)
            for tick, remaining in ((100, 3), (200, 2), (300, 1)):
                fixture.events.append(event(
                    tick, "DURABILITY_HIT", type_=f"legacy-target:OBSIDIAN:remaining={remaining}/4",
                    x=3, y=101, z=0,
                ))
            fixture.events.extend([
                event(400, "DURABILITY_BREAK", type_="legacy-target:OBSIDIAN:hits=4", x=3, y=101, z=0, affected=1),
                event(401, "TARGET_DESTROYED", type_="legacy-target:OBSIDIAN", x=3, y=101, z=0, affected=1),
            ])
            contract = replace(
                breach.PROFILES["dry-obsidian"],
                require_direct_durability_sequence=True,
            )
            report = self.analyze(fixture, contract)
            self.assertEqual(report["status"], "PASS", report)
            shot = report["shots"][0]
            self.assertEqual(shot["evidence_grade"], "direct-durability-sequence")
            self.assertEqual(shot["durability"]["direct_complete_sequences"], 1)

    def test_fake_green_zero_damage_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = RunFixture(Path(raw), contract_pass=True, target_destroyed=0)
            report = self.analyze(fixture, breach.PROFILES["dry-obsidian"])
            self.assertEqual(report["status"], "FAIL")
            shot = report["shots"][0]
            self.assertIn("fake-green-contract", shot["diagnosis_codes"])
            self.assertIn("target_damage=0", shot["failures"])

    def test_scattered_durability_hits_do_not_prove_four_hit_break(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = RunFixture(Path(raw), target_destroyed=1)
            for index, x in enumerate((3, 4, 5, 6), start=1):
                fixture.events.append(event(
                    100 * index, "DURABILITY_HIT",
                    type_="legacy-target:OBSIDIAN:remaining=3/4",
                    x=x, y=101, z=0,
                ))
            fixture.events.append(event(
                500, "TARGET_DESTROYED", type_="legacy-target:OBSIDIAN", x=3, y=101, z=0, affected=1,
            ))
            contract = replace(
                breach.PROFILES["dry-obsidian"],
                require_direct_durability_sequence=True,
            )
            report = self.analyze(fixture, contract)
            shot = report["shots"][0]
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("durability-hit-scatter", shot["diagnosis_codes"])
            self.assertIn("direct_durability_sequence_missing", shot["failures"])

    def test_watered_obsidian_requires_embedded_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = RunFixture(
                Path(raw), target_type="WATERED", target_destroyed=1, contract_pass=True,
            )
            fixture.events.append(event(
                401, "TARGET_DESTROYED", type_="legacy-target:OBSIDIAN", x=3, y=101, z=0, affected=1,
            ))
            fixture.breach_rows.append(breach_event(400, water=True, overlap=False))
            report = self.analyze(fixture, breach.PROFILES["watered-obsidian"])
            shot = report["shots"][0]
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("tnt-only-target-contact", shot["diagnosis_codes"])
            self.assertTrue(any(item.startswith("embedded_payload_explosions=0<1") for item in shot["failures"]))
            self.assertTrue(any(item.startswith("unembedded_water_explosions=1>0") for item in shot["failures"]))

    def test_two_layer_same_lane_beats_regen(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = RunFixture(
                Path(raw), material="COBBLESTONE", layers=2, spacing=3,
                regen=True, target_destroyed=2, regen_margin=12,
            )
            fixture.events.extend([
                event(100, "TARGET_DESTROYED", type_="legacy-target:COBBLESTONE", x=3, y=101, z=0, affected=1),
                event(101, "TARGET_DESTROYED", type_="legacy-target:COBBLESTONE", x=6, y=101, z=0, affected=1),
                event(120, "REGEN_RESTORE", type_="legacy-target:COBBLESTONE", x=3, y=101, z=0, affected=1),
            ])
            report = self.analyze(fixture, breach.PROFILES["regen-course"])
            self.assertEqual(report["status"], "PASS", report)
            self.assertEqual(report["shots"][0]["target_geometry"]["best_contiguous_lane_layers"], 2)

    def test_damage_on_different_lanes_does_not_count_as_contiguous_breach(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = RunFixture(
                Path(raw), material="COBBLESTONE", layers=2, spacing=3,
                regen=True, target_destroyed=2, regen_margin=12,
            )
            fixture.events.extend([
                event(100, "TARGET_DESTROYED", type_="legacy-target:COBBLESTONE", x=3, y=101, z=0, affected=1),
                event(101, "TARGET_DESTROYED", type_="legacy-target:COBBLESTONE", x=6, y=102, z=0, affected=1),
                event(120, "REGEN_RESTORE", type_="legacy-target:COBBLESTONE", x=3, y=101, z=0, affected=1),
            ])
            report = self.analyze(fixture, breach.PROFILES["regen-course"])
            shot = report["shots"][0]
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(shot["target_geometry"]["best_contiguous_lane_layers"], 1)
            self.assertIn("no-contiguous-breach-lane", shot["diagnosis_codes"])

    def test_wrong_axis_falling_payload_is_diagnosed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = RunFixture(Path(raw), distance=15)
            fixture.events.extend([
                event(10, "ENTITY", type_="FALLING_BLOCK", uuid="sand-1", x=2.5, y=104, z=5.5),
                event(11, "ENTITY", type_="FALLING_BLOCK", uuid="sand-1", x=2.5, y=104, z=1.5, vz=-4.0),
                event(11, "EXPLOSION", type_="TNT", uuid="tnt-1", x=2.5, y=104, z=5.5),
            ])
            report = self.analyze(fixture, breach.PROFILES["diagnostic"])
            shot = report["shots"][0]
            self.assertEqual(report["status"], "PASS")
            self.assertIn("payload-axis-mismatch", shot["diagnosis_codes"])
            self.assertIn("falling-payload-stalled", shot["diagnosis_codes"])
            self.assertIn("propulsion-impulse-off-axis", shot["diagnosis_codes"])
            impulse = shot["falling_payload_motion"]["strongest_attributed_impulse"]
            self.assertEqual(impulse["nearest_source_explosion"]["tick"], 11)

    def test_native_final_break_is_not_direct_hit_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = RunFixture(
                Path(raw), durability_mode="NATIVE", target_destroyed=1,
            )
            fixture.events.append(event(
                401, "TARGET_DESTROYED", type_="legacy-target:OBSIDIAN", x=3, y=101, z=0, affected=1,
            ))
            contract = replace(
                breach.PROFILES["dry-obsidian"],
                require_direct_durability_sequence=True,
            )
            report = self.analyze(fixture, contract)
            shot = report["shots"][0]
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(shot["evidence_grade"], "native-final-break-only")
            self.assertIn("native-hit-sequence-unobserved", shot["diagnosis_codes"])

    def test_payload_reaches_wall_without_tnt_is_not_axis_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = RunFixture(Path(raw), distance=3)
            fixture.events.extend([
                event(10, "ENTITY", type_="FALLING_BLOCK", uuid="sand-1", x=0.5, y=104, z=0.5),
                event(11, "ENTITY", type_="FALLING_BLOCK", uuid="sand-1", x=3.5, y=103, z=0.5, vx=3.0),
            ])
            report = self.analyze(fixture, breach.PROFILES["diagnostic"])
            shot = report["shots"][0]
            self.assertIn("payload-at-wall-without-target-tnt", shot["diagnosis_codes"])
            self.assertNotIn("payload-axis-mismatch", shot["diagnosis_codes"])
            self.assertNotIn("falling-payload-stalled", shot["diagnosis_codes"])
            self.assertTrue(shot["summary_metrics"]["payload_reached_target"])
            self.assertEqual(shot["summary_metrics"]["payload_arrival_tick"], 11)

    def test_payload_and_tnt_arrival_gap_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = RunFixture(Path(raw), distance=3)
            fixture.events.extend([
                event(10, "ENTITY", type_="FALLING_BLOCK", uuid="sand-1", x=0.5, y=104, z=0.5),
                event(11, "ENTITY", type_="FALLING_BLOCK", uuid="sand-1", x=3.5, y=103, z=0.5, vx=3.0),
            ])
            fixture.breach_rows.append(breach_event(20, x=3.5, y=103, z=0.5, target=True))
            report = self.analyze(fixture, breach.PROFILES["diagnostic"])
            shot = report["shots"][0]
            self.assertIn("payload-tnt-arrival-desynchronized", shot["diagnosis_codes"])
            self.assertEqual(shot["summary_metrics"]["nearest_payload_tnt_tick_gap"], 9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
