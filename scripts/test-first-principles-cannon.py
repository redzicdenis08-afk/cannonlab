#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("plan-first-principles-cannon.py")
spec = importlib.util.spec_from_file_location("first_principles", SCRIPT)
assert spec and spec.loader
planner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = planner
spec.loader.exec_module(planner)


def request(**overrides):
    payload = {
        "schema_version": 1,
        "id": "test",
        "mode": "from-scratch",
        "minimum_evidence": "local-runtime",
        "constraints": {
            "chunk_limit": 160,
            "min_chunk_margin": 8,
            "max_columns": 12,
            "max_total_dispensers": 1200,
            "max_candidate_count": 48,
        },
        "objective": {
            "range_blocks": 256,
            "watered_obsidian_hits": 4,
            "stack_height": 255,
            "regen_layers": 15,
            "shot_cadence_ticks": 40,
            "features": ["hybrid", "stacker", "slab-bust", "regen-bust", "nuke", "osrb", "campaign"],
        },
    }
    for key, value in overrides.items():
        payload[key] = value
    return payload


class FirstPrinciplesPlannerTests(unittest.TestCase):
    def test_full_program_is_source_free_and_dependency_complete(self):
        report = planner.build_report(request())
        self.assertEqual("RESEARCH_PROGRAM_ONLY", report["status"])
        self.assertFalse(report["source_schematic_used"])
        self.assertEqual("control-spine", report["required_primitives"][0])
        self.assertEqual("campaign-cycle", report["required_primitives"][-1])
        self.assertIn("falling-payload-fusion", report["required_primitives"])
        self.assertIn("hammer", report["required_primitives"])
        self.assertIn("osrb-sequence", report["required_primitives"])

    def test_source_schematic_is_rejected(self):
        payload = request(source_schematic="legacy.schem")
        with self.assertRaisesRegex(planner.PlanError, "forbids source_schematic"):
            planner.build_report(payload)

    def test_static_only_evidence_is_rejected(self):
        payload = request(minimum_evidence="static")
        with self.assertRaisesRegex(planner.PlanError, "at least local-runtime"):
            planner.build_report(payload)

    def test_unknown_feature_is_rejected(self):
        payload = request()
        payload["objective"]["features"].append("magic-wall-delete")
        with self.assertRaisesRegex(planner.PlanError, "unknown features"):
            planner.build_report(payload)

    def test_ec160_margin_is_enforced(self):
        report = planner.build_report(request())
        self.assertTrue(report["architecture_candidates"])
        for candidate in report["architecture_candidates"]:
            self.assertLessEqual(candidate["max_column_load"], 152)
            self.assertGreaterEqual(candidate["minimum_chunk_margin"], 8)
            self.assertLessEqual(candidate["column_count"], 12)
            self.assertLessEqual(candidate["total_dispensers"], 1200)

    def test_tight_column_budget_can_produce_no_architecture(self):
        payload = request()
        payload["constraints"]["max_columns"] = 1
        payload["constraints"]["max_total_dispensers"] = 1200
        report = planner.build_report(payload)
        self.assertEqual([], report["architecture_candidates"])
        self.assertIsNone(report["strongest_architecture"])

    def test_hybrid_request_does_not_pull_advanced_campaign_modules(self):
        payload = request()
        payload["objective"]["features"] = ["hybrid"]
        report = planner.build_report(payload)
        self.assertEqual(
            ["control-spine", "protected-charge-cell", "payload-injector", "guider", "falling-payload-fusion"],
            report["required_primitives"],
        )
        self.assertNotIn("hammer", report["required_primitives"])
        self.assertNotIn("campaign-cycle", report["required_primitives"])

    def test_plan_is_deterministic(self):
        first = planner.build_report(request())
        second = planner.build_report(request())
        self.assertEqual(first, second)

    def test_candidate_sampler_reaches_requested_budget(self):
        report = planner.build_report(request())
        self.assertEqual(48, len(report["architecture_candidates"]))
        totals = {row["total_dispensers"] for row in report["architecture_candidates"]}
        self.assertGreaterEqual(len(totals), 12)

    def test_cli_json_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            output_path = root / "plan.json"
            request_path.write_text(json.dumps(request()), encoding="utf-8")
            payload = planner.load_json(request_path)
            output_path.write_text(json.dumps(planner.build_report(payload)), encoding="utf-8")
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("RESEARCH_PROGRAM_ONLY", report["status"])


if __name__ == "__main__":
    unittest.main()
