#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-cannon-architecture.py"
POLICY = ROOT / "policy" / "modern-cannon-architecture-policy.json"


class ArchitecturePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "cannons").mkdir(parents=True)
        (self.root / "output").mkdir(parents=True)
        (self.root / "cannons" / "candidate.schem").write_bytes(b"fixture")
        self.write_json(
            "output/geometry.json",
            {
                "status": "PASS",
                "intent": "modern-raid",
                "candidate": {"modern_raid_morphology": {"verdict": "PASS"}},
            },
        )
        self.write_json("output/preservation.json", {"status": "PASS"})
        self.write_json("output/trace.json", {"status": "PASS"})
        self.write_json("output/edge.json", {"status": "PASS"})
        self.write_json("output/acceptance.json", {"status": "PASS", "contract_pass": True})
        self.write_json("output/canary.json", {"status": "PASS", "field_verified": True})

    def write_json(self, relative: str, payload: dict) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def modern_manifest(self) -> dict:
        return {
            "schema": "cannonlab-architecture-manifest-v1",
            "candidate": {
                "file": "cannons/candidate.schem",
                "intent": "modern-raid",
                "lifecycle": "local-candidate",
                "claims": ["local-runtime"],
            },
            "source": {
                "mode": "reference-repair",
                "reference_sha256": ["a" * 64],
                "geometry_profile": "output/geometry.json",
                "preservation_report": "output/preservation.json",
            },
            "architecture": {
                "stages": [
                    {
                        "id": "power",
                        "role": "power",
                        "role_status": "confirmed",
                        "role_evidence": "runtime",
                        "runtime_evidence": "output/trace.json",
                    },
                    {
                        "id": "payload",
                        "role": "payload-package",
                        "role_status": "confirmed",
                        "role_evidence": "runtime",
                        "runtime_evidence": "output/trace.json",
                    },
                ],
                "impulse_edges": [
                    {
                        "from": "power",
                        "to": "payload",
                        "mechanism": "explosion-push",
                        "status": "verified",
                        "expected_axis": "forward",
                        "runtime_evidence": "output/edge.json",
                    }
                ],
            },
            "change_budget": {
                "declared_variable": "one mapped timing delay",
                "modules_touched": 1,
                "override_approved": False,
                "override_reason": "",
            },
            "runtime": {
                "native_redstone": True,
                "direct_dispense": False,
                "forced_velocity": False,
                "tnt_probe": False,
                "simulated_durability": False,
                "suppressed_paste_side_effects": False,
                "acceptance_report": "output/acceptance.json",
            },
            "extremecraft": {
                "field_verified": False,
                "live_canary_report": None,
            },
        }

    def run_manifest(self, manifest: dict) -> tuple[int, dict]:
        manifest_path = self.write_json("manifest.json", manifest)
        result = subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                str(manifest_path),
                "--policy",
                str(POLICY),
                "--repo-root",
                str(self.root),
                "--output-root",
                str(self.root / "output"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"validator returned non-JSON output\nstdout={result.stdout}\nstderr={result.stderr}\n{exc}")
        return result.returncode, payload

    @staticmethod
    def error_codes(payload: dict) -> set[str]:
        return {str(item.get("code")) for item in payload.get("errors", [])}

    def test_reference_repair_local_candidate_passes(self) -> None:
        code, payload = self.run_manifest(self.modern_manifest())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(payload["errors"])

    def test_diagnostic_prototype_from_scratch_passes_without_promotion(self) -> None:
        manifest = {
            "schema": "cannonlab-architecture-manifest-v1",
            "candidate": {
                "file": "cannons/candidate.schem",
                "intent": "diagnostic-prototype",
                "lifecycle": "diagnostic-prototype",
                "claims": ["diagnostic"],
            },
            "source": {"mode": "from-scratch", "reference_sha256": []},
            "architecture": {
                "stages": [
                    {"id": "source", "role_status": "candidate", "role_evidence": "static"},
                    {"id": "payload", "role_status": "unknown", "role_evidence": "unknown"},
                ],
                "impulse_edges": [
                    {
                        "from": "source",
                        "to": "payload",
                        "mechanism": "explosion-push",
                        "status": "planned",
                    }
                ],
            },
            "change_budget": {"declared_variable": "", "modules_touched": 0},
            "runtime": {},
            "extremecraft": {},
        }
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")

    def test_modern_raid_from_scratch_is_rejected(self) -> None:
        manifest = self.modern_manifest()
        manifest["source"]["mode"] = "from-scratch"
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 2)
        self.assertIn("modern_raid_from_scratch_forbidden", self.error_codes(payload))

    def test_flat_morphology_is_rejected(self) -> None:
        self.write_json(
            "output/geometry.json",
            {
                "status": "PASS",
                "intent": "modern-raid",
                "candidate": {"modern_raid_morphology": {"verdict": "FAIL"}},
            },
        )
        code, payload = self.run_manifest(self.modern_manifest())
        self.assertEqual(code, 2)
        self.assertIn("flat_morphology_rejected", self.error_codes(payload))

    def test_static_role_cannot_be_confirmed(self) -> None:
        manifest = self.modern_manifest()
        manifest["architecture"]["stages"][0]["role_evidence"] = "static"
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 2)
        self.assertIn("static_role_promotion_forbidden", self.error_codes(payload))

    def test_direct_dispense_cannot_promote_candidate(self) -> None:
        manifest = self.modern_manifest()
        manifest["runtime"]["direct_dispense"] = True
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 2)
        self.assertIn("diagnostic_assist_promotion", self.error_codes(payload))

    def test_unverified_impulse_edge_cannot_promote_candidate(self) -> None:
        manifest = self.modern_manifest()
        manifest["architecture"]["impulse_edges"][0]["status"] = "observed"
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 2)
        self.assertIn("unverified_promoted_edge", self.error_codes(payload))

    def test_multi_module_rewrite_requires_explicit_override(self) -> None:
        manifest = self.modern_manifest()
        manifest["change_budget"]["modules_touched"] = 4
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 2)
        self.assertIn("unbounded_multi_module_change", self.error_codes(payload))

    def test_ec_ready_requires_field_canary(self) -> None:
        manifest = self.modern_manifest()
        manifest["candidate"]["lifecycle"] = "ec-ready"
        manifest["candidate"]["claims"] = ["ec-ready"]
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 2)
        codes = self.error_codes(payload)
        self.assertIn("ec_field_verification_required", codes)
        self.assertIn("ec_live_canary_required", codes)

    def test_ec_ready_passes_with_field_canary(self) -> None:
        manifest = self.modern_manifest()
        manifest["candidate"]["lifecycle"] = "ec-ready"
        manifest["candidate"]["claims"] = ["ec-ready"]
        manifest["extremecraft"] = {
            "field_verified": True,
            "live_canary_report": "output/canary.json",
        }
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")

    def test_candidate_path_escape_is_rejected(self) -> None:
        outside = self.root.parent / "outside.schem"
        outside.write_bytes(b"outside")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        manifest = self.modern_manifest()
        manifest["candidate"]["file"] = str(outside)
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 2)
        self.assertIn("evidence_path_escape", self.error_codes(payload))

    def test_missing_impulse_chain_is_rejected(self) -> None:
        manifest = self.modern_manifest()
        manifest["architecture"]["impulse_edges"] = []
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 2)
        codes = self.error_codes(payload)
        self.assertIn("insufficient_impulse_edges", codes)
        self.assertIn("missing_explosion_push", codes)

    def test_calibration_does_not_require_modern_impulse_graph(self) -> None:
        manifest = {
            "schema": "cannonlab-architecture-manifest-v1",
            "candidate": {
                "file": "cannons/candidate.schem",
                "intent": "calibration",
                "lifecycle": "diagnostic-prototype",
                "claims": ["diagnostic"],
            },
            "source": {"mode": "from-scratch", "reference_sha256": []},
            "architecture": {"stages": [], "impulse_edges": []},
            "change_budget": {"modules_touched": 0},
            "runtime": {},
            "extremecraft": {},
        }
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")

    def test_simulated_durability_cannot_promote_candidate(self) -> None:
        manifest = self.modern_manifest()
        manifest["runtime"]["simulated_durability"] = True
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 2)
        self.assertIn("diagnostic_assist_promotion", self.error_codes(payload))

    def test_one_shot_claim_requires_explicit_contract(self) -> None:
        manifest = self.modern_manifest()
        manifest["candidate"]["claims"] = ["one-shot"]
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 2)
        self.assertIn("one_shot_contract_required", self.error_codes(payload))

        self.write_json(
            "output/acceptance.json",
            {"status": "PASS", "contract_pass": True, "one_shot_contract_pass": True},
        )
        code, payload = self.run_manifest(manifest)
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
