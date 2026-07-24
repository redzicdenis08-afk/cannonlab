#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "general-cannon-intelligence.py"
SPEC = importlib.util.spec_from_file_location("general_cannon_intelligence", SCRIPT)
assert SPEC and SPEC.loader
engine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine
SPEC.loader.exec_module(engine)


class GeneralCannonIntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = engine.load_catalog()
        cls.families, cls.specializations = engine.index_catalog(cls.catalog)

    def test_catalog_audit_passes(self) -> None:
        result = engine.validate_catalog(self.catalog)
        self.assertEqual(result["status"], "PASS", result)
        self.assertGreaterEqual(result["family_count"], 7)
        self.assertGreaterEqual(result["specialization_count"], 18)

    def test_runtime_diagnostic_surface_is_ready(self) -> None:
        result = engine.audit_runtime()
        self.assertEqual(result["readiness"]["diagnostic-prototype"]["status"], "PASS", result)

    def test_runtime_local_candidate_has_no_infrastructure_gaps(self) -> None:
        result = engine.audit_runtime()
        missing = set(result["readiness"]["local-candidate"]["missing"])
        self.assertEqual(missing, set(), result)
        self.assertEqual(result["readiness"]["local-candidate"]["status"], "PASS", result)

    def test_runtime_ec_ready_has_bounded_variant_search(self) -> None:
        result = engine.audit_runtime()
        self.assertNotIn("automated-bounded-variant-search", result["readiness"]["ec-ready"]["missing"])

    def test_full_audit_passes_when_runtime_and_operator_are_complete(self) -> None:
        result = engine.build_audit()
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["schema"], "cannonlab-general-intelligence-audit-v2")
        self.assertIn("must never be described as fully automatic", result["truth_boundary"])

    def test_diagnostic_requirement_can_pass_without_overclaiming_operator_readiness(self) -> None:
        result = engine.build_audit("diagnostic-prototype")
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["required_level"], "diagnostic-prototype")

    def test_operator_requirement_passes_after_full_operator_integration(self) -> None:
        result = engine.build_audit("operator-ready")
        missing = set(result["operator"]["readiness"]["operator-ready"]["missing"])
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(missing, set())

    def test_hammered_hybrid_diagnostic_plan_passes(self) -> None:
        plan = engine.build_plan("hammered-stacker", ["hybrid"], "diagnostic-prototype")
        self.assertEqual(plan["status"], "PASS", plan)
        self.assertEqual(plan["base"]["payload_mode"], "falling-block-required")

    def test_hammerless_osrb_diagnostic_plan_passes(self) -> None:
        plan = engine.build_plan("hammerless-stacker", ["overstack", "osrb"], "diagnostic-prototype")
        self.assertEqual(plan["status"], "PASS", plan)

    def test_rev_worm_osrb_is_blocked_by_payload_interface(self) -> None:
        plan = engine.build_plan("rev-worm", ["osrb"], "diagnostic-prototype")
        codes = {item["code"] for item in plan["blockers"]}
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("worm-payload-interface-unproven", codes)

    def test_asser_worm_mix_is_blocked(self) -> None:
        plan = engine.build_plan("asser-multiwave", ["worm-route"], "diagnostic-prototype")
        codes = {item["code"] for item in plan["blockers"]}
        self.assertIn("family-mix-unproven", codes)

    def test_calibration_cannon_cannot_inherit_raid_modules(self) -> None:
        plan = engine.build_plan("compact-calibration-stacker", ["efficient-nuke"], "diagnostic-prototype")
        codes = {item["code"] for item in plan["blockers"]}
        self.assertIn("calibration-scope", codes)

    def test_unknown_push_nuke_fails_closed(self) -> None:
        plan = engine.build_plan("hammered-stacker", ["push-nuke"], "diagnostic-prototype")
        codes = {item["code"] for item in plan["blockers"]}
        self.assertIn("unresolved-terminology", codes)
        self.assertIn("unknown-specialization-output", codes)

    def test_alien_probe_fails_closed(self) -> None:
        plan = engine.build_plan("force-or-counter", ["alien-probe"], "diagnostic-prototype")
        codes = {item["code"] for item in plan["blockers"]}
        self.assertIn("unresolved-terminology", codes)

    def test_local_candidate_plan_passes_when_runtime_gaps_are_closed(self) -> None:
        plan = engine.build_plan("hammered-stacker", ["hybrid"], "local-candidate")
        self.assertEqual(plan["status"], "PASS", plan)
        self.assertEqual(plan["blockers"], [], plan)

    def test_static_asser_ceiling_blocks_local_promotion(self) -> None:
        plan = engine.build_plan("asser-multiwave", [], "local-candidate")
        codes = {item["code"] for item in plan["blockers"]}
        self.assertIn("base-evidence-ceiling", codes)

    def test_rev_worm_ceiling_blocks_local_promotion(self) -> None:
        plan = engine.build_plan("rev-worm", [], "local-candidate")
        codes = {item["code"] for item in plan["blockers"]}
        self.assertIn("base-evidence-ceiling", codes)

    def test_double_tap_complexity_budget(self) -> None:
        plan = engine.build_plan(
            "hammered-stacker",
            ["hybrid", "slab-bust", "anti-patch", "double-tap"],
            "diagnostic-prototype",
        )
        codes = {item["code"] for item in plan["blockers"]}
        self.assertIn("complexity-budget", codes)

    def test_osrb_plus_efficient_nuke_requires_shared_ooe_proof(self) -> None:
        plan = engine.build_plan("hammered-stacker", ["osrb", "efficient-nuke"], "diagnostic-prototype")
        codes = {item["code"] for item in plan["blockers"]}
        self.assertIn("ooe-composition-proof", codes)

    def test_diagnosis_ranks_leftshoot_for_wrong_side(self) -> None:
        result = engine.diagnose(["the payload went to the wrong side and hit the backboard"])
        ids = [item["id"] for item in result["ranked_candidates"][:3]]
        self.assertIn("left-right-shoot", ids)

    def test_diagnosis_ranks_osrb_for_regen_loss(self) -> None:
        result = engine.diagnose(["regen wins and the sand is one block wrong"])
        ids = [item["id"] for item in result["ranked_candidates"][:5]]
        self.assertIn("osrb", ids)

    def test_diagnosis_has_truth_boundary(self) -> None:
        result = engine.diagnose(["self damage"])
        self.assertIn("does not identify", result["truth_boundary"])

    def test_research_gaps_prioritize_unknown_labels(self) -> None:
        result = engine.research_gaps()
        top_ids = {item["id"] for item in result["items"][:6]}
        self.assertTrue({"push-nuke", "alien-probe"} & top_ids)

    def test_matrix_contains_every_catalog_item(self) -> None:
        result = engine.matrix()
        expected = len(self.families) + len(self.specializations)
        self.assertEqual(len(result["rows"]), expected)

    def test_every_specialization_has_acceptance(self) -> None:
        for item_id, item in self.specializations.items():
            self.assertTrue(item.get("acceptance"), item_id)

    def test_unknown_outputs_use_do_not_invent(self) -> None:
        for item_id, item in self.specializations.items():
            if item.get("output") == "unknown-until-proven":
                self.assertEqual(item.get("acceptance"), ["do-not-invent"], item_id)

    def test_duplicate_catalog_id_is_rejected(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        catalog["families"].append(copy.deepcopy(catalog["families"][0]))
        result = engine.validate_catalog(catalog)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("duplicate-id", {item["code"] for item in result["errors"]})

    def test_weak_universal_contract_is_rejected(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        catalog["universal_physics_contract"]["required_layers"] = ["redstone"]
        result = engine.validate_catalog(catalog)
        self.assertIn("weak-universal-contract", {item["code"] for item in result["errors"]})

    def test_unknown_base_raises(self) -> None:
        with self.assertRaises(ValueError):
            engine.build_plan("flat-pancake-9000", [], "diagnostic-prototype")

    def test_unknown_specialization_raises(self) -> None:
        with self.assertRaises(ValueError):
            engine.build_plan("hammered-stacker", ["magic-nuke"], "diagnostic-prototype")

    def test_plan_contains_general_evidence_phases(self) -> None:
        plan = engine.build_plan("hammered-stacker", ["slab-bust"], "diagnostic-prototype")
        ids = [phase["id"] for phase in plan["phases"]]
        self.assertEqual(ids[:4], ["source-intake", "baseline-grammar", "module-isolation", "bounded-composition"])
        self.assertIn("defense-campaign", ids)
        self.assertIn("ec160-redesign", ids)

    def test_ec_ready_plan_adds_live_canary_phase(self) -> None:
        plan = engine.build_plan("hammered-stacker", ["hybrid"], "ec-ready")
        self.assertIn("live-ec-canary", [phase["id"] for phase in plan["phases"]])

    def test_capability_none_token_check_works(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_root = engine.ROOT
            try:
                engine.ROOT = Path(directory)
                path = engine.ROOT / "sample.py"
                path.write_text("safe = True\n", encoding="utf-8")
                passed, _ = engine.capability_check({"type": "none-token", "path": "sample.py", "tokens": ["forbidden"]})
                self.assertTrue(passed)
                path.write_text("forbidden = True\n", encoding="utf-8")
                passed, _ = engine.capability_check({"type": "none-token", "path": "sample.py", "tokens": ["forbidden"]})
                self.assertFalse(passed)
            finally:
                engine.ROOT = original_root


if __name__ == "__main__":
    unittest.main(verbosity=2)
