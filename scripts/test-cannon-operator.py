#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cannon-operator.py"
SPEC = importlib.util.spec_from_file_location("cannon_operator", SCRIPT)
assert SPEC and SPEC.loader
operator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = operator
SPEC.loader.exec_module(operator)


class CannonOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scripts = self.root / "scripts"
        self.scripts.mkdir(parents=True)
        self.output = self.root / "output"
        self.output.mkdir()
        self.jobs = self.root / "operator-jobs"
        self.candidate = self.root / "candidate.schem"
        self.candidate.write_bytes(b"candidate")
        self.reference = self.root / "reference.schem"
        self.reference.write_bytes(b"reference")
        self.architecture = self.root / "architecture.json"
        self.architecture.write_text(json.dumps({
            "schema": "cannonlab-architecture-manifest-v1",
            "candidate": {
                "file": str(self.candidate),
                "intent": "modern-raid",
                "lifecycle": "diagnostic-prototype",
                "claims": ["diagnostic"],
            },
            "source": {"mode": "reference-repair", "reference_sha256": ["0" * 64]},
            "architecture": {"stages": [], "impulse_edges": []},
            "change_budget": {},
            "runtime": {},
            "extremecraft": {},
        }) + "\n", encoding="utf-8")

        self.originals = {
            "ROOT": operator.ROOT,
            "OUTPUT_ROOT": operator.OUTPUT_ROOT,
            "SCRIPTS": operator.SCRIPTS,
            "OPERATOR_JOBS": operator.OPERATOR_JOBS,
            "GENERAL_ENGINE": operator.GENERAL_ENGINE,
            "ARCHITECTURE_VALIDATOR": operator.ARCHITECTURE_VALIDATOR,
            "CANNON_FORGE": operator.CANNON_FORGE,
            "CANNON_MUTATOR": operator.CANNON_MUTATOR,
            "GEOMETRY_PROFILE": operator.GEOMETRY_PROFILE,
            "FORGE_RUNNER": operator.FORGE_RUNNER,
        }
        operator.ROOT = self.root
        operator.OUTPUT_ROOT = self.output
        operator.SCRIPTS = self.scripts
        operator.OPERATOR_JOBS = self.jobs
        operator.GENERAL_ENGINE = self.scripts / "general-cannon-intelligence.py"
        operator.ARCHITECTURE_VALIDATOR = self.scripts / "validate-cannon-architecture.py"
        operator.CANNON_FORGE = self.scripts / "cannon-forge.py"
        operator.CANNON_MUTATOR = self.scripts / "cannon-mutator.py"
        operator.GEOMETRY_PROFILE = self.scripts / "cannon-geometry-profile.py"
        operator.FORGE_RUNNER = self.scripts / "run-forge-campaign.ps1"
        for path in (
            operator.GENERAL_ENGINE,
            operator.ARCHITECTURE_VALIDATOR,
            operator.CANNON_FORGE,
            operator.CANNON_MUTATOR,
            operator.GEOMETRY_PROFILE,
            operator.FORGE_RUNNER,
        ):
            path.write_text("# fixture\n", encoding="utf-8")
        self.addCleanup(self.restore)

    def restore(self) -> None:
        for name, value in self.originals.items():
            setattr(operator, name, value)

    def args(self, **updates: object) -> argparse.Namespace:
        values: dict[str, object] = {
            "candidate": str(self.candidate),
            "architecture_manifest": str(self.architecture),
            "mutation_plan": "",
            "base": "hammered-stacker",
            "specialization": ["hybrid"],
            "lifecycle": "diagnostic-prototype",
            "reference": [str(self.reference)],
            "job": "operator-test",
            "intent": "modern-raid",
            "chunk_limit": 160,
            "origin": "0,0,0",
            "fire_input": "1,2,3",
            "fire_mode": "button",
            "direction": "north",
            "distance": 160,
            "width": 17,
            "height": 32,
            "shots": 10,
        }
        values.update(updates)
        return argparse.Namespace(**values)

    def engine(self, plan: dict[str, object]) -> mock.Mock:
        result = mock.Mock()
        result.build_plan.return_value = plan
        return result

    def test_path_escape_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            operator.allowed_input(Path(self.temp.name).parent / "outside.schem", must_exist=False)

    def test_slugify_is_bounded(self) -> None:
        value = operator.slugify("A Modern / Cannon " * 20)
        self.assertLessEqual(len(value), 72)
        self.assertNotIn(" ", value)

    def test_blocked_general_plan_stops_before_architecture_and_forge(self) -> None:
        plan = {"status": "BLOCKED", "blockers": [{"code": "bad-composition", "message": "blocked"}]}
        with mock.patch.object(operator, "load_general_engine", return_value=self.engine(plan)), mock.patch.object(
            operator, "run_json"
        ) as run_json:
            result = operator.prepare_job(self.args())
        self.assertEqual(result["status"], "BLOCKED")
        run_json.assert_not_called()
        self.assertTrue((self.jobs / "operator-test" / "manifest.json").is_file())

    def test_architecture_failure_stops_before_forge(self) -> None:
        plan = {"status": "PASS", "blockers": []}
        architecture = {"status": "FAIL", "errors": [{"code": "missing-edge"}], "_exit_code": 2}
        with mock.patch.object(operator, "load_general_engine", return_value=self.engine(plan)), mock.patch.object(
            operator, "run_json", return_value=architecture
        ) as run_json:
            result = operator.prepare_job(self.args())
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(run_json.call_count, 1)
        self.assertEqual(result["forge"]["result"]["status"], "SKIPPED")

    def test_pass_binds_plan_architecture_and_forge(self) -> None:
        plan = {"status": "PASS", "blockers": [], "schema": "plan"}
        architecture = {"status": "PASS", "schema": "architecture", "_exit_code": 0}
        forge = {"status": "PASS", "schema": "forge", "_exit_code": 0}
        with mock.patch.object(operator, "load_general_engine", return_value=self.engine(plan)), mock.patch.object(
            operator, "run_json", side_effect=[architecture, forge]
        ) as run_json:
            result = operator.prepare_job(self.args())
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(run_json.call_count, 2)
        self.assertEqual(result["general_plan"]["schema"], "plan")
        self.assertEqual(result["architecture_policy"]["schema"], "architecture")
        self.assertEqual(result["forge"]["result"]["schema"], "forge")
        self.assertEqual(result["candidate"]["sha256"], operator.sha256(self.candidate))
        self.assertIn("cannon-operator.py run", result["next_command"])

    def test_optional_mutation_runs_before_architecture_and_forge(self) -> None:
        mutation_plan = self.root / "mutation.json"
        mutation_plan.write_text("{}\n", encoding="utf-8")
        mutated = self.root / "mutated.schem"
        mutated.write_bytes(b"mutated")
        plan = {"status": "PASS", "blockers": []}
        mutation = {
            "status": "PASS",
            "output": {"path": str(mutated), "sha256": operator.sha256(mutated)},
            "_exit_code": 0,
        }
        passed = {"status": "PASS", "_exit_code": 0}
        with mock.patch.object(operator, "load_general_engine", return_value=self.engine(plan)), mock.patch.object(
            operator, "run_json", side_effect=[mutation, passed, passed, passed]
        ) as run_json:
            result = operator.prepare_job(self.args(mutation_plan=str(mutation_plan)))
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(run_json.call_count, 4)
        self.assertEqual(Path(run_json.call_args_list[0].args[0][1]).name, "cannon-mutator.py")
        self.assertEqual(Path(run_json.call_args_list[1].args[0][1]).name, "cannon-geometry-profile.py")
        self.assertEqual(result["source_candidate"]["sha256"], operator.sha256(self.candidate))
        self.assertEqual(result["candidate"]["sha256"], operator.sha256(mutated))
        self.assertEqual(result["bounded_mutation"]["status"], "PASS")
        derived = json.loads((self.jobs / "operator-test" / "architecture-derived.json").read_text(encoding="utf-8"))
        self.assertEqual(operator.allowed_input(derived["candidate"]["file"]), mutated)
        self.assertEqual(derived["source"]["mode"], "bounded-variant")
        self.assertEqual(derived["candidate"]["candidate_sha256"], operator.sha256(mutated))

    def test_failed_mutation_stops_before_architecture_and_forge(self) -> None:
        mutation_plan = self.root / "mutation.json"
        mutation_plan.write_text("{}\n", encoding="utf-8")
        plan = {"status": "PASS", "blockers": []}
        mutation = {"status": "BLOCKED", "blockers": [{"code": "budget"}], "_exit_code": 2}
        with mock.patch.object(operator, "load_general_engine", return_value=self.engine(plan)), mock.patch.object(
            operator, "run_json", return_value=mutation
        ) as run_json:
            result = operator.prepare_job(self.args(mutation_plan=str(mutation_plan)))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(run_json.call_count, 1)
        self.assertIn("mutation-failed", {item["code"] for item in result["blockers"]})

    def test_architecture_candidate_mismatch_fails_before_policy(self) -> None:
        other = self.root / "other.schem"
        other.write_bytes(b"other")
        payload = json.loads(self.architecture.read_text(encoding="utf-8"))
        payload["candidate"]["file"] = str(other)
        self.architecture.write_text(json.dumps(payload), encoding="utf-8")
        plan = {"status": "PASS", "blockers": []}
        with mock.patch.object(operator, "load_general_engine", return_value=self.engine(plan)), mock.patch.object(
            operator, "run_json"
        ) as run_json:
            result = operator.prepare_job(self.args())
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("architecture-candidate-mismatch", {item["code"] for item in result["blockers"]})
        run_json.assert_not_called()


    def test_manifest_records_reference_hashes(self) -> None:
        plan = {"status": "PASS", "blockers": []}
        passed = {"status": "PASS", "_exit_code": 0}
        with mock.patch.object(operator, "load_general_engine", return_value=self.engine(plan)), mock.patch.object(
            operator, "run_json", side_effect=[passed, passed]
        ):
            result = operator.prepare_job(self.args())
        saved = json.loads((self.jobs / "operator-test" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["references"][0]["sha256"], operator.sha256(self.reference))
        self.assertEqual(saved["architecture_manifest"]["sha256"], operator.sha256(self.architecture))
        self.assertEqual(saved["status"], result["status"])

    def test_run_refuses_blocked_manifest(self) -> None:
        manifest = self.root / "blocked.json"
        manifest.write_text(
            json.dumps({"schema": "cannonlab-operator-job-v1", "status": "BLOCKED"}),
            encoding="utf-8",
        )
        result = operator.run_job(str(manifest), execute=False)
        self.assertEqual(result["status"], "BLOCKED")

    def test_run_dry_mode_returns_command_without_execution(self) -> None:
        forge_dir = self.root / "forge-jobs" / "ready"
        forge_dir.mkdir(parents=True)
        forge_manifest = forge_dir / "manifest.json"
        forge_manifest.write_text("{}\n", encoding="utf-8")
        manifest = self.root / "ready.json"
        manifest.write_text(
            json.dumps({
                "schema": "cannonlab-operator-job-v1",
                "status": "PASS",
                "forge": {"manifest_path": str(forge_manifest)},
            }),
            encoding="utf-8",
        )
        with mock.patch.object(operator.subprocess, "run") as run:
            result = operator.run_job(str(manifest), execute=False)
        self.assertEqual(result["status"], "READY")
        self.assertFalse(result["executed"])
        self.assertIn(str(operator.FORGE_RUNNER), result["command"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
