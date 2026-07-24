#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cannon-variant-scorecard.py"
SPEC = importlib.util.spec_from_file_location("cannon_variant_scorecard", SCRIPT)
assert SPEC and SPEC.loader
scorecard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scorecard
SPEC.loader.exec_module(scorecard)


class CannonVariantScorecardTests(unittest.TestCase):
    def summaries(self) -> list[dict]:
        return [
            {
                "shots": [
                    {
                        "target_blocks_destroyed": 20,
                        "target_peak_destroyed": 25,
                        "target_ever_destroyed": 30,
                        "embedded_payload_explosions": 4,
                        "unembedded_water_explosions": 0,
                        "self_damage_blocks": 1,
                        "maximum_forward_distance": 100,
                        "maximum_falling_blocks": 384,
                        "regen_race_margin_ticks": 3,
                        "contiguous_layers_breached_before_first_regen": 4,
                        "cannon_initial_dispensers": 500,
                        "cannon_remaining_dispensers": 499,
                        "dominant_output_direction": "NORTH",
                        "contract_pass": True,
                        "all_layers_breached_before_first_regen": True,
                    },
                    {
                        "target_blocks_destroyed": 15,
                        "target_peak_destroyed": 22,
                        "target_ever_destroyed": 28,
                        "embedded_payload_explosions": 3,
                        "unembedded_water_explosions": 1,
                        "self_damage_blocks": 4,
                        "maximum_forward_distance": 90,
                        "maximum_falling_blocks": 380,
                        "regen_race_margin_ticks": 1,
                        "contiguous_layers_breached_before_first_regen": 3,
                        "cannon_initial_dispensers": 500,
                        "cannon_remaining_dispensers": 495,
                        "dominant_output_direction": "NORTH",
                        "contract_pass": False,
                        "all_layers_breached_before_first_regen": False,
                    },
                ]
            }
        ]

    def test_conservative_aggregation_uses_worst_shot(self) -> None:
        metrics, evidence, blockers = scorecard.aggregate(self.summaries())
        self.assertEqual(blockers, [])
        self.assertEqual(metrics["target_destroyed"], 15)
        self.assertEqual(metrics["embedded_payload_explosions"], 3)
        self.assertEqual(metrics["self_damage_blocks"], 4)
        self.assertEqual(metrics["maximum_forward_distance"], 90)
        self.assertEqual(metrics["remaining_dispenser_ratio"], 0.99)
        self.assertEqual(evidence["shot_count"], 2)

    def test_direction_repeatability_uses_agreement_fraction(self) -> None:
        summaries = self.summaries()
        summaries[0]["shots"][1]["dominant_output_direction"] = "SOUTH"
        metrics, _evidence, _blockers = scorecard.aggregate(summaries)
        self.assertEqual(metrics["direction_repeatability"], 0.5)

    def test_explicit_direction_repeatability_is_conservative(self) -> None:
        summaries = [{"direction_repeatability": 0.9, "shots": [{"explosions": 1}]}, {"direction_repeatability": 0.8, "shots": [{"explosions": 1}]}]
        metrics, _evidence, _blockers = scorecard.aggregate(summaries)
        self.assertEqual(metrics["direction_repeatability"], 0.8)

    def test_missing_field_stays_missing(self) -> None:
        metrics, evidence, blockers = scorecard.aggregate([{"shots": [{"target_blocks_destroyed": 1}, {"explosions": 2}]}])
        self.assertEqual(blockers, [])
        self.assertNotIn("target_destroyed", metrics)
        self.assertEqual(evidence["metric_shot_coverage"]["target_destroyed"], 1)

    def test_no_shots_blocks(self) -> None:
        metrics, evidence, blockers = scorecard.aggregate([{"shots": []}])
        self.assertEqual(metrics, {})
        self.assertEqual(evidence["shot_count"], 0)
        self.assertIn("no-shot-evidence", {item["code"] for item in blockers})

    def write_manifest(self, root: Path) -> Path:
        manifest = {
            "schema": "cannonlab-variant-search-manifest-v1",
            "job": "scorecard-test",
            "candidates": [
                {"variant_id": "v000-a", "static_score": 900},
                {"variant_id": "v001-b", "static_score": 910},
            ],
        }
        path = root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_extract_records_hashes_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest = self.write_manifest(root)
            run_a = root / "run-a.json"
            run_b = root / "run-b.json"
            run_a.write_text(json.dumps(self.summaries()[0]), encoding="utf-8")
            run_b.write_text(json.dumps(self.summaries()[0]), encoding="utf-8")
            mapping = root / "map.json"
            mapping.write_text(json.dumps({
                "schema": "cannonlab-variant-result-map-v1",
                "variants": {"v000-a": [str(run_a)], "v001-b": {"run_summaries": [str(run_b)]}},
            }), encoding="utf-8")
            result = scorecard.extract(str(manifest), str(mapping))
            self.assertEqual(result["status"], "PASS", result)
            self.assertEqual(result["variants"]["v000-a"]["metrics"]["target_destroyed"], 15)
            self.assertEqual(len(result["variants"]["v000-a"]["evidence"]["run_summaries"][0]["sha256"]), 64)

    def test_extract_fails_when_static_candidate_has_no_results(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest = self.write_manifest(root)
            run_a = root / "run-a.json"
            run_a.write_text(json.dumps(self.summaries()[0]), encoding="utf-8")
            mapping = root / "map.json"
            mapping.write_text(json.dumps({
                "schema": "cannonlab-variant-result-map-v1",
                "variants": {"v000-a": [str(run_a)]},
            }), encoding="utf-8")
            result = scorecard.extract(str(manifest), str(mapping))
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("variant-results-missing", {item["code"] for item in result["blockers"]})

    def test_unknown_variant_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest = self.write_manifest(root)
            mapping = root / "map.json"
            mapping.write_text(json.dumps({
                "schema": "cannonlab-variant-result-map-v1",
                "variants": {"v999-x": []},
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                scorecard.extract(str(manifest), str(mapping))


if __name__ == "__main__":
    unittest.main(verbosity=2)
