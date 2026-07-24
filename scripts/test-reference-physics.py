#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("cannon_physics_reference.py")
SPEC = importlib.util.spec_from_file_location("cannon_physics_reference", MODULE_PATH)
assert SPEC and SPEC.loader
physics = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = physics
SPEC.loader.exec_module(physics)


class ReferencePhysicsTests(unittest.TestCase):
    def test_modern_tnt_tick_order(self) -> None:
        state = physics.BodyState("tnt", physics.Vec3(0.0, 10.0, 0.0), physics.Vec3(1.0, 1.0, -2.0), 80)
        result = physics.tick_body(state)
        self.assertEqual(result.state.fuse_or_age, 79)
        self.assertFalse(result.detonated)
        self.assertAlmostEqual(result.state.position.x, 1.0)
        self.assertAlmostEqual(result.state.position.y, 10.96)
        self.assertAlmostEqual(result.state.position.z, -2.0)
        self.assertAlmostEqual(result.state.velocity.x, 0.98)
        self.assertAlmostEqual(result.state.velocity.y, 0.96 * 0.98)
        self.assertAlmostEqual(result.state.velocity.z, -1.96)

    def test_falling_block_ground_before_drag(self) -> None:
        state = physics.BodyState("falling_block", physics.Vec3(0.0, 2.0, 0.0), physics.Vec3(1.0, -1.0, 1.0), 5, True)
        result = physics.tick_body(state)
        self.assertTrue(result.landed)
        self.assertEqual(result.state.fuse_or_age, 6)
        self.assertAlmostEqual(result.state.velocity.x, 1.0 * 0.7 * 0.98)
        self.assertAlmostEqual(result.state.velocity.y, (-1.0 - 0.04) * -0.5 * 0.98)
        self.assertAlmostEqual(result.state.velocity.z, 1.0 * 0.7 * 0.98)

    def test_water_push_applies_to_tnt_not_falling_block(self) -> None:
        flow = physics.Vec3(3.0, 0.0, 4.0)
        tnt = physics.tick_body(physics.BodyState("tnt", physics.ZERO, physics.ZERO, 80), water_flow=flow)
        falling = physics.tick_body(physics.BodyState("falling_block", physics.ZERO, physics.ZERO, 0), water_flow=flow)
        self.assertAlmostEqual(tnt.applied_water_push.length(), 0.014)
        self.assertEqual(falling.applied_water_push, physics.ZERO)

    def test_modern_fuse_detonates_after_decrement(self) -> None:
        result = physics.tick_body(physics.BodyState("tnt", physics.ZERO, physics.ZERO, 1))
        self.assertTrue(result.detonated)
        self.assertEqual(result.state.fuse_or_age, 0)

    def test_explosion_impulse_uses_tnt_feet(self) -> None:
        impulse = physics.explosion_impulse(physics.ZERO, physics.Vec3(4.0, 0.0, 0.0), power=4.0, exposure=1.0, target_is_tnt=True)
        self.assertAlmostEqual(impulse.x, 0.5)
        self.assertAlmostEqual(impulse.y, 0.0)
        self.assertAlmostEqual(impulse.z, 0.0)

    def test_explosion_count_sums_impulse(self) -> None:
        one = physics.explosion_impulse(physics.ZERO, physics.Vec3(2.0, 0.0, 0.0), count=1)
        four = physics.explosion_impulse(physics.ZERO, physics.Vec3(2.0, 0.0, 0.0), count=4)
        self.assertAlmostEqual(four.x, one.x * 4.0)

    def test_comparison_matches_synthetic_modern_trace(self) -> None:
        initial = physics.BodyState("tnt", physics.Vec3(0.0, 4.0, 0.0), physics.Vec3(0.5, 0.2, 0.0), 80)
        observations = [physics.Observation(10, initial.position, initial.velocity, initial.fuse_or_age, "u", "TNT")]
        state = initial
        for tick in range(11, 16):
            result = physics.tick_body(state)
            state = result.state
            observations.append(physics.Observation(tick, state.position, state.velocity, state.fuse_or_age, "u", "TNT"))
        report = physics.compare_observations(observations)
        self.assertEqual(report["status"], "MATCH")
        self.assertIsNone(report["summary"]["first_divergence"])

    def test_comparison_detects_fuse_divergence(self) -> None:
        first = physics.Observation(1, physics.Vec3(0.0, 3.0, 0.0), physics.ZERO, 80, "u", "TNT")
        predicted = physics.tick_body(physics.BodyState("tnt", first.position, first.velocity, first.fuse)).state
        second = physics.Observation(2, predicted.position, predicted.velocity, predicted.fuse_or_age - 1, "u", "TNT")
        report = physics.compare_observations([first, second])
        self.assertEqual(report["status"], "DIVERGED")
        codes = [item["code"] for item in report["summary"]["first_divergence"]["diagnoses"]]
        self.assertIn("fuse-order-or-tick-phase-divergence", codes)

    def test_event_reader_selects_first_spawned_tnt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.csv"
            fields = ["tick", "event", "type", "uuid", "x", "y", "z", "vx", "vy", "vz", "fuse"]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"tick": 5, "event": "ENTITY", "type": "TNT", "uuid": "later", "x": 2, "y": 0, "z": 0, "vx": 0, "vy": 0, "vz": 0, "fuse": 80})
                writer.writerow({"tick": 4, "event": "ENTITY", "type": "TNT", "uuid": "first", "x": 1, "y": 0, "z": 0, "vx": 0, "vy": 0, "vz": 0, "fuse": 80})
                writer.writerow({"tick": 5, "event": "ENTITY", "type": "TNT", "uuid": "first", "x": 1, "y": -0.04, "z": 0, "vx": 0, "vy": -0.0392, "vz": 0, "fuse": 79})
            rows = physics.read_cannonlab_events(path)
            self.assertEqual(rows[0].uuid, "first")
            self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
