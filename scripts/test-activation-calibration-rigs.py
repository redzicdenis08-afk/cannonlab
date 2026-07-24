#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("generate-activation-calibration-rigs.py")
spec = importlib.util.spec_from_file_location("activation_calibration", SCRIPT)
assert spec and spec.loader
calibration = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = calibration
spec.loader.exec_module(calibration)


def profile() -> dict:
    return {
        "schema_version": 1,
        "id": "activation-test",
        "mode": "from-scratch",
        "data_version": 3465,
        "chunk_limit": 160,
        "shots_per_candidate": 10,
        "controls": ["direct", "dust"],
        "repeater": {
            "facings": ["east", "west"],
            "delays": [1, 2, 3, 4],
        },
    }


class ActivationCalibrationTests(unittest.TestCase):
    def test_rejects_source_schematic(self):
        payload = profile()
        payload["source_schematic"] = "legacy.schem"
        with self.assertRaisesRegex(calibration.CalibrationError, "source_schematic is forbidden"):
            calibration.validate_profile(payload)

    def test_requires_complete_orientation_matrix(self):
        payload = profile()
        payload["repeater"]["facings"] = ["east"]
        with self.assertRaisesRegex(calibration.CalibrationError, "east and west"):
            calibration.validate_profile(payload)

    def test_generates_two_controls_and_eight_repeater_hypotheses(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = calibration.generate(profile(), Path(directory))
            self.assertEqual("STATIC_ACTIVATION_CALIBRATION_ONLY", manifest["status"])
            self.assertEqual(10, manifest["candidate_count"])
            ids = {row["id"] for row in manifest["candidates"]}
            self.assertEqual(
                {
                    "activation-direct",
                    "activation-dust",
                    "activation-repeater-east-d1",
                    "activation-repeater-east-d2",
                    "activation-repeater-east-d3",
                    "activation-repeater-east-d4",
                    "activation-repeater-west-d1",
                    "activation-repeater-west-d2",
                    "activation-repeater-west-d3",
                    "activation-repeater-west-d4",
                },
                ids,
            )
            self.assertFalse(manifest["truth_boundary"]["repeater_orientation_proven"])

    def test_every_candidate_has_one_protected_dispenser(self):
        audit = calibration.RIGS.load_audit()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = calibration.generate(profile(), root)
            for row in manifest["candidates"]:
                root_name, nbt_root, trailing, _size, diagnostics = audit.load(root / row["file"])
                self.assertFalse(trailing)
                self.assertTrue(diagnostics["strict_gzip_valid"])
                model = audit.decode_any(root_name, nbt_root)
                dispenser = tuple(row["dispenser"])
                water = tuple(row["water_cell"])
                self.assertEqual(
                    "minecraft:dispenser",
                    calibration.RIGS.base_state(model["blocks"][dispenser]),
                )
                self.assertEqual(
                    "minecraft:water",
                    calibration.RIGS.base_state(model["blocks"][water]),
                )
                self.assertEqual(dispenser[0] + 1, water[0])
                self.assertEqual(1, row["dispenser_count"])
                self.assertEqual(256, row["chunk_pressure"]["safe_alignment_count"])
                self.assertTrue(row["chunk_pressure"]["all_alignments_safe"])

    def test_driver_geometry_matches_declared_kind(self):
        audit = calibration.RIGS.load_audit()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = calibration.generate(profile(), root)
            for row in manifest["candidates"]:
                root_name, nbt_root, _trailing, _size, _diagnostics = audit.load(root / row["file"])
                model = audit.decode_any(root_name, nbt_root)
                kind = row["kind"]
                if kind == "direct":
                    self.assertEqual("minecraft:air", model["blocks"][(0, 1, 1)])
                    self.assertEqual("minecraft:dispenser", calibration.RIGS.base_state(model["blocks"][(1, 1, 1)]))
                elif kind == "dust":
                    self.assertEqual("minecraft:redstone_wire", calibration.RIGS.base_state(model["blocks"][(1, 1, 1)]))
                else:
                    self.assertEqual("minecraft:repeater", calibration.RIGS.base_state(model["blocks"][(1, 1, 1)]))
                    state = model["blocks"][(1, 1, 1)]
                    self.assertIn(f"delay={row['driver']['delay']}", state)
                    self.assertIn(f"facing={row['driver']['facing']}", state)

    def test_generation_is_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = calibration.generate(profile(), Path(first_dir))
            second = calibration.generate(profile(), Path(second_dir))
            self.assertEqual(
                {row["id"]: row["sha256"] for row in first["candidates"]},
                {row["id"]: row["sha256"] for row in second["candidates"]},
            )

    def test_manifest_file_matches_return_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = calibration.generate(profile(), root)
            written = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest, written)


if __name__ == "__main__":
    unittest.main()
