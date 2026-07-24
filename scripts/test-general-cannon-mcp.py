#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "mcp-server" / "server.py"


class _FakeFastMCP:
    def __init__(self, _name: str) -> None:
        self.tools: list[object] = []

    def tool(self):
        def decorate(function):
            self.tools.append(function)
            return function
        return decorate

    def run(self) -> None:
        raise AssertionError("test must not start an MCP server")


if "mcp.server.fastmcp" not in sys.modules:
    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fastmcp_module.FastMCP = _FakeFastMCP
    sys.modules["mcp"] = mcp_module
    sys.modules["mcp.server"] = server_module
    sys.modules["mcp.server.fastmcp"] = fastmcp_module

SPEC = importlib.util.spec_from_file_location("cannonlab_general_mcp", SERVER_PATH)
assert SPEC and SPEC.loader
server = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = server
SPEC.loader.exec_module(server)


class GeneralCannonMcpTests(unittest.TestCase):
    def test_general_readiness_is_exposed(self) -> None:
        result = server.audit_general_cannon_readiness()
        self.assertEqual(result["schema"], "cannonlab-general-intelligence-audit-v2")
        self.assertEqual(result["operator"]["readiness"]["operator-ready"]["status"], "PASS")

    def test_general_plan_is_exposed(self) -> None:
        result = server.plan_general_cannon(
            "hammered-stacker",
            ["hybrid"],
            "diagnostic-prototype",
        )
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["base"]["id"], "hammered-stacker")

    def test_general_diagnosis_is_exposed(self) -> None:
        result = server.diagnose_general_cannon(["regen wins", "sand one block wrong"])
        ranked = [item["id"] for item in result["ranked_candidates"]]
        self.assertIn("osrb", ranked[:5])

    def test_forge_tool_binds_archetype_payload_and_control_states(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            candidate = Path(directory) / "candidate.schem"
            reference = Path(directory) / "reference.schem"
            candidate.write_bytes(b"candidate")
            reference.write_bytes(b"reference")
            control = '{"name":"mode","at":{"x":1,"y":2,"z":3},"block_data":"minecraft:lever[powered=true]"}'
            with patch.object(server, "_run_json", return_value={"status": "PASS"}) as mocked:
                result = server.stage_cannon_forge(
                    str(candidate),
                    1,
                    2,
                    3,
                    "rev-worm",
                    specializations=["efficient-nuke"],
                    payload_mode="tnt-only",
                    control_states_json=[control],
                    reference_paths=[str(reference)],
                )
            self.assertEqual(result["status"], "PASS")
            command = mocked.call_args.args[0]
            self.assertIn("--base", command)
            self.assertIn("rev-worm", command)
            self.assertIn("--payload-mode", command)
            self.assertIn("tnt-only", command)
            self.assertIn("--control-state-json", command)
            self.assertIn(control, command)

    def test_invalid_lifecycle_fails_before_subprocess(self) -> None:
        with self.assertRaises(ValueError):
            server.plan_general_cannon("hammered-stacker", [], "magic-ready")

    def test_bounded_mutation_tool_uses_reviewed_plan(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            plan = Path(directory) / "plan.json"
            plan.write_text("{}\n", encoding="utf-8")
            with patch.object(server, "_run_json", return_value={"status": "PASS"}) as mocked:
                result = server.mutate_cannon_bounded(str(plan))
            self.assertEqual(result["status"], "PASS")
            command = mocked.call_args.args[0]
            self.assertIn("cannon-mutator.py", command[1])
            self.assertEqual(Path(command[2]), plan.resolve())

    def test_wall_breach_tool_binds_strict_profile(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            run = Path(directory) / "run"
            run.mkdir()
            (run / "run-summary.json").write_text("{}\n", encoding="utf-8")
            with patch.object(server, "_run_json", return_value={"status": "PASS"}) as mocked:
                result = server.analyze_wall_breach(
                    str(run),
                    profile="watered-obsidian",
                    min_shots=5,
                    require_direct_durability_sequence=True,
                    require_falling_payload=True,
                    max_unembedded_water_explosions=0,
                    min_connected_opening=1,
                    min_contiguous_layers=2,
                    max_self_damage_blocks=0,
                    min_dispenser_survival_ratio=0.99,
                )
            self.assertEqual(result["status"], "PASS")
            command = mocked.call_args.args[0]
            self.assertIn("wall-breach-intelligence.py", " ".join(command))
            self.assertIn("watered-obsidian", command)
            self.assertIn("--require-direct-durability-sequence", command)
            self.assertIn("--require-falling-payload", command)
            self.assertIn("--max-unembedded-water-explosions", command)
            self.assertIn("0", command)

    def test_variant_generation_tool_is_exposed(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            spec_path = Path(directory) / "search.json"
            spec_path.write_text("{}\n", encoding="utf-8")
            with patch.object(server, "_run_json", return_value={"status": "PASS"}) as mocked:
                result = server.generate_cannon_variants(str(spec_path), apply=False)
            self.assertEqual(result["status"], "PASS")
            command = mocked.call_args.args[0]
            self.assertIn("cannon-variant-search.py", command[1])
            self.assertIn("generate", command)
            self.assertIn("--no-apply", command)

    def test_variant_runtime_ranking_tool_is_exposed(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            manifest = Path(directory) / "manifest.json"
            scorecard = Path(directory) / "scorecard.json"
            manifest.write_text("{}\n", encoding="utf-8")
            scorecard.write_text("{}\n", encoding="utf-8")
            with patch.object(server, "_run_json", return_value={"status": "PASS"}) as mocked:
                result = server.rank_cannon_variants(str(manifest), str(scorecard))
            self.assertEqual(result["status"], "PASS")
            command = mocked.call_args.args[0]
            self.assertIn("cannon-variant-search.py", command[1])
            self.assertIn("rank", command)

    def test_variant_scorecard_extraction_tool_is_exposed(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            manifest = Path(directory) / "manifest.json"
            result_map = Path(directory) / "result-map.json"
            manifest.write_text("{}\n", encoding="utf-8")
            result_map.write_text("{}\n", encoding="utf-8")
            with patch.object(server, "_run_json", return_value={"status": "PASS"}) as mocked:
                result = server.extract_cannon_variant_scorecard(str(manifest), str(result_map))
            self.assertEqual(result["status"], "PASS")
            command = mocked.call_args.args[0]
            self.assertIn("cannon-variant-scorecard.py", command[1])

    def test_operator_tool_binds_mutation_references_and_specializations(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            candidate = root / "candidate.schem"
            architecture = root / "architecture.json"
            mutation = root / "mutation.json"
            reference = root / "reference.schem"
            for path in (candidate, architecture, mutation, reference):
                path.write_bytes(b"fixture")
            with patch.object(server, "_run_json", return_value={"status": "PASS"}) as mocked:
                result = server.prepare_cannon_operator(
                    str(candidate),
                    str(architecture),
                    1,
                    2,
                    3,
                    "hammered-stacker",
                    specializations=["overstack", "osrb"],
                    payload_mode="falling-block-required",
                    control_states_json=['{"name":"mode","at":{"x":1,"y":2,"z":3},"block_data":"minecraft:lever[powered=true]"}'],
                    reference_paths=[str(reference)],
                    mutation_plan_path=str(mutation),
                    job="mcp-operator-proof",
                )
            self.assertEqual(result["status"], "PASS")
            command = mocked.call_args.args[0]
            self.assertIn("cannon-operator.py", command[1])
            self.assertIn("--mutation-plan", command)
            self.assertEqual(command.count("--specialization"), 2)
            self.assertEqual(command.count("--reference"), 1)
            self.assertIn("--payload-mode", command)
            self.assertIn("falling-block-required", command)
            self.assertIn("--control-state-json", command)
            self.assertIn("1,2,3", command)

    def test_operator_run_defaults_to_dry_mode(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text("{}\n", encoding="utf-8")
            with patch.object(server, "_run_json", return_value={"status": "READY"}) as mocked:
                result = server.run_cannon_operator(str(manifest))
            self.assertEqual(result["status"], "READY")
            command = mocked.call_args.args[0]
            self.assertNotIn("--execute", command)

    def test_private_corpus_regression_tool_is_exposed(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            corpus = Path(directory) / "corpus"
            corpus.mkdir()
            baseline = Path(directory) / "baseline.json"
            baseline.write_text("{}\n", encoding="utf-8")
            with patch.object(server, "_run_json", return_value={"status": "PASS"}) as mocked:
                result = server.audit_private_cannon_corpus(
                    str(corpus),
                    job="corpus-proof",
                    baseline_manifest_path=str(baseline),
                    require_unchanged_sources=True,
                )
            self.assertEqual(result["status"], "PASS")
            command = mocked.call_args.args[0]
            self.assertIn("private-corpus-regression.py", command[1])
            self.assertIn("--require-unchanged-sources", command)


if __name__ == "__main__":
    unittest.main(verbosity=2)
