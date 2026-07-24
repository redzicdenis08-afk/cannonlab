#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("cannon-archetype-engine.py")
SPEC = importlib.util.spec_from_file_location("cannon_archetype_engine", SCRIPT)
assert SPEC and SPEC.loader
engine = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = engine
SPEC.loader.exec_module(engine)


class CannonArchetypeEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = engine.load_registry(engine.DEFAULT_REGISTRY)
        cls.worm = engine.archetype_by_id(cls.registry, "rev-worm-383-v4")
        cls.hash = cls.worm["reference_hashes"][0]

    def all_pass_capabilities(self) -> dict:
        ids = engine.BASE_REQUIRED_CAPABILITIES + engine.PROMOTION_REQUIRED_CAPABILITIES
        return {
            "schema": "cannonlab-archetype-capability-audit-v1",
            "status": "PASS",
            "capabilities": [
                {"id": capability_id, "status": "PASS", "evidence": ["test"], "missing": []}
                for capability_id in ids
            ],
        }

    def write_causal(self, rows: list[dict[str, str]]) -> Path:
        temp = tempfile.NamedTemporaryFile("w", suffix=".csv", encoding="utf-8", newline="", delete=False)
        path = Path(temp.name)
        fieldnames = ["tick", "event", "item", "details"]
        writer = csv.DictWriter(temp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        temp.close()
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def cohort_rows(self, *, count_delta: int = 0, shift: int = 0) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        specs = [
            (183 + shift, {"north": 229 + count_delta, "south": 308}),
            (185 + shift, {"south": 216, "north": 108, "east": 12}),
            (186 + shift, {"north": 144}),
        ]
        for tick, facings in specs:
            for facing, count in facings.items():
                rows.extend(
                    {
                        "tick": str(tick),
                        "event": "DISPENSE",
                        "item": "TNT",
                        "details": f"amount=1;block_data=minecraft:dispenser[facing={facing},triggered=true]",
                    }
                    for _ in range(count)
                )
        return rows

    def test_registry_ids_are_unique(self) -> None:
        ids = [item["id"] for item in self.registry["archetypes"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("rev-worm-383-v4", ids)

    def test_unknown_archetype_fails_closed(self) -> None:
        with self.assertRaises(engine.ArchetypeError):
            engine.archetype_by_id(self.registry, "flat-pancake-9000")

    def test_correct_reference_diagnostic_plan_passes(self) -> None:
        plan = engine.build_plan(
            self.registry,
            self.worm,
            "diagnostic-prototype",
            self.hash,
            self.all_pass_capabilities(),
            field_canary_report=None,
        )
        self.assertEqual(plan["status"], "PASS")
        self.assertEqual(plan["archetype"]["promotion_ceiling"], "diagnostic-prototype")

    def test_wrong_reference_hash_is_blocked(self) -> None:
        plan = engine.build_plan(
            self.registry,
            self.worm,
            "diagnostic-prototype",
            "0" * 64,
            self.all_pass_capabilities(),
            field_canary_report=None,
        )
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("reference-hash-mismatch", {item["code"] for item in plan["blockers"]})

    def test_local_candidate_is_blocked_by_current_worm_evidence_ceiling(self) -> None:
        plan = engine.build_plan(
            self.registry,
            self.worm,
            "local-candidate",
            self.hash,
            self.all_pass_capabilities(),
            field_canary_report=None,
        )
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("archetype-evidence-ceiling", {item["code"] for item in plan["blockers"]})

    def test_missing_promotion_capability_blocks_local_candidate(self) -> None:
        capabilities = self.all_pass_capabilities()
        for item in capabilities["capabilities"]:
            if item["id"] == "output-corridor-acceptance":
                item["status"] = "MISSING"
        plan = engine.build_plan(
            self.registry,
            self.worm,
            "local-candidate",
            self.hash,
            capabilities,
            field_canary_report=None,
        )
        messages = [item["message"] for item in plan["blockers"] if item["code"] == "missing-capability"]
        self.assertTrue(any("output-corridor-acceptance" in message for message in messages))

    def test_architecture_template_does_not_invent_impulse_mechanisms(self) -> None:
        template = engine.architecture_template(self.worm, "diagnostic-prototype", self.hash)
        edges = template["architecture"]["impulse_edges"]
        self.assertTrue(edges)
        self.assertTrue(all(edge["mechanism"] == "unknown" for edge in edges))
        self.assertTrue(all(edge["status"] == "hypothesis" for edge in edges))

    def test_exact_worm_cohort_fingerprint_passes(self) -> None:
        path = self.write_causal(self.cohort_rows())
        verdict = engine.verify_cohorts(self.worm, path, tick_tolerance=0, count_tolerance=0)
        self.assertEqual(verdict["status"], "PASS")
        self.assertEqual(verdict["best_match"]["anchor_tick"], 183)

    def test_shifted_worm_cohort_fingerprint_keeps_relative_timing(self) -> None:
        path = self.write_causal(self.cohort_rows(shift=40))
        verdict = engine.verify_cohorts(self.worm, path, tick_tolerance=0, count_tolerance=0)
        self.assertEqual(verdict["status"], "PASS")
        self.assertEqual(verdict["best_match"]["anchor_tick"], 223)

    def test_worm_cohort_count_mismatch_fails(self) -> None:
        path = self.write_causal(self.cohort_rows(count_delta=-1))
        verdict = engine.verify_cohorts(self.worm, path, tick_tolerance=0, count_tolerance=0)
        self.assertEqual(verdict["status"], "FAIL")
        self.assertTrue(any("major-cohort-a" in failure for failure in verdict["failures"]))

    def test_count_tolerance_can_accept_small_measurement_gap(self) -> None:
        path = self.write_causal(self.cohort_rows(count_delta=-1))
        verdict = engine.verify_cohorts(self.worm, path, tick_tolerance=0, count_tolerance=1)
        self.assertEqual(verdict["status"], "PASS")

    def test_no_tnt_dispenses_fails(self) -> None:
        path = self.write_causal([
            {"tick": "1", "event": "DISPENSE", "item": "ARROW", "details": "block_data=minecraft:dispenser[facing=north]"}
        ])
        verdict = engine.verify_cohorts(self.worm, path, tick_tolerance=0, count_tolerance=0)
        self.assertEqual(verdict["status"], "FAIL")
        self.assertEqual(verdict["reason"], "no TNT dispense events")

    def test_facing_extraction(self) -> None:
        details = "amount=1;block_data=minecraft:dispenser[facing=south,triggered=false]"
        self.assertEqual(engine.extract_facing(details), "south")

    def test_current_capability_audit_has_expected_schema(self) -> None:
        report = engine.audit_capabilities()
        self.assertEqual(report["schema"], "cannonlab-archetype-capability-audit-v1")
        ids = {item["id"] for item in report["capabilities"]}
        self.assertTrue(set(engine.BASE_REQUIRED_CAPABILITIES).issubset(ids))
        self.assertTrue(set(engine.PROMOTION_REQUIRED_CAPABILITIES).issubset(ids))


if __name__ == "__main__":
    unittest.main(verbosity=2)
