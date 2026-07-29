#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("generate-first-principles-rigs.py")
spec = importlib.util.spec_from_file_location("first_principles_rigs", SCRIPT)
assert spec and spec.loader
rigs = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rigs
spec.loader.exec_module(rigs)


def profile() -> dict:
    return {
        "schema_version": 1,
        "id": "test-rigs",
        "mode": "from-scratch",
        "data_version": 3465,
        "chunk_limit": 160,
        "families": [
            {"id": "protected-charge-cell", "cell_counts": [1, 2, 3, 4]},
            {"id": "payload-injector", "repeater_delays": [1, 2, 3, 4]},
            {"id": "guider", "lengths": [4, 8, 12, 16], "repeater_delay": 1},
        ],
    }


def decode(audit, path: Path) -> dict:
    root_name, root, trailing, _size, diagnostics = audit.load(path)
    if trailing:
        raise AssertionError(f"unexpected trailing bytes in {path}")
    if diagnostics.get("strict_gzip_valid") is not True:
        raise AssertionError(f"non-strict gzip in {path}")
    return audit.decode_any(root_name, root)


class FirstPrinciplesRigTests(unittest.TestCase):
    def test_profile_rejects_source_schematic(self):
        payload = profile()
        payload["source_schematic"] = "old-cannon.schem"
        with self.assertRaisesRegex(rigs.RigGenerationError, "source_schematic is forbidden"):
            rigs.validate_profile(payload)

    def test_profile_rejects_unknown_family(self):
        payload = profile()
        payload["families"] = [{"id": "instant-goated-cannon", "lengths": [1]}]
        with self.assertRaisesRegex(rigs.RigGenerationError, "unsupported family"):
            rigs.validate_profile(payload)

    def test_generates_exact_bounded_family(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = rigs.generate(profile(), Path(directory))
            self.assertEqual("STATIC_EXPERIMENT_FAMILY_ONLY", manifest["status"])
            self.assertFalse(manifest["source_schematic_used"])
            self.assertEqual(12, manifest["candidate_count"])
            self.assertEqual(
                {
                    "charge-c01", "charge-c02", "charge-c03", "charge-c04",
                    "payload-d1", "payload-d2", "payload-d3", "payload-d4",
                    "guider-l004-d1", "guider-l008-d1", "guider-l012-d1", "guider-l016-d1",
                },
                {row["id"] for row in manifest["candidates"]},
            )
            self.assertFalse(manifest["truth_boundary"]["static_rig_is_proven_primitive"])
            self.assertFalse(manifest["truth_boundary"]["static_rig_is_raid_cannon"])

    def test_every_candidate_round_trips_and_is_ec160_safe(self):
        audit = rigs.load_audit()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = rigs.generate(profile(), root)
            for row in manifest["candidates"]:
                path = root / row["file"]
                self.assertTrue(path.is_file())
                model = decode(audit, path)
                self.assertEqual(3465, model["data_version"])
                self.assertEqual(row["dispenser_count"], sum(
                    rigs.base_state(state) == "minecraft:dispenser"
                    for state in model["blocks"].values()
                ))
                self.assertEqual(256, row["chunk_pressure"]["safe_alignment_count"])
                self.assertTrue(row["chunk_pressure"]["all_alignments_safe"])
                for raw_input in row["fire_inputs"]:
                    self.assertEqual("minecraft:air", model["blocks"].get(tuple(raw_input)))

    def test_charge_cells_are_individually_water_enclosed(self):
        audit = rigs.load_audit()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = rigs.generate(profile(), root)
            for row in manifest["candidates"]:
                if row["family"] != "protected-charge-cell":
                    continue
                model = decode(audit, root / row["file"])
                self.assertEqual(row["dispenser_count"], row["water_source_count"])
                self.assertEqual(4 * row["variant"]["cell_count"], row["dispenser_count"])
                for position, state in model["blocks"].items():
                    if rigs.base_state(state) != "minecraft:dispenser":
                        continue
                    x, y, z = position
                    self.assertEqual("minecraft:water", rigs.base_state(model["blocks"][(x + 1, y, z)]))
                self.assertFalse(row["experiment_contract"]["combined_impulse_claimed"])

    def test_payload_delays_are_exact_and_supported(self):
        audit = rigs.load_audit()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = rigs.generate(profile(), root)
            for row in manifest["candidates"]:
                if row["family"] != "payload-injector":
                    continue
                model = decode(audit, root / row["file"])
                delay = row["variant"]["repeater_delay"]
                self.assertEqual(
                    f"minecraft:repeater[delay={delay},facing=east,locked=false,powered=false]",
                    model["blocks"][(1, 1, 1)],
                )
                self.assertEqual("minecraft:obsidian", model["blocks"][(1, 0, 1)])
                self.assertFalse(row["experiment_contract"]["payload_role_proven"])

    def test_guider_lengths_change_only_the_declared_lane(self):
        audit = rigs.load_audit()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = rigs.generate(profile(), root)
            for row in manifest["candidates"]:
                if row["family"] != "guider":
                    continue
                model = decode(audit, root / row["file"])
                length = row["variant"]["guider_length"]
                self.assertEqual(3 + length, row["dimensions"][0])
                for x in range(3, 3 + length):
                    self.assertEqual("minecraft:obsidian", model["blocks"][(x, 1, 0)])
                    self.assertEqual("minecraft:obsidian", model["blocks"][(x, 1, 2)])
                    self.assertEqual("minecraft:air", model["blocks"][(x, 1, 1)])
                self.assertFalse(row["experiment_contract"]["guider_role_proven"])

    def test_generation_is_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = rigs.generate(profile(), Path(first_dir))
            second = rigs.generate(profile(), Path(second_dir))
            self.assertEqual(
                {row["id"]: row["sha256"] for row in first["candidates"]},
                {row["id"]: row["sha256"] for row in second["candidates"]},
            )

    def test_manifest_file_matches_returned_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = rigs.generate(profile(), root)
            written = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest, written)


if __name__ == "__main__":
    unittest.main()
