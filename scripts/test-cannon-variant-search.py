#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cannon-variant-search.py"
SPEC = importlib.util.spec_from_file_location("cannon_variant_search", SCRIPT)
assert SPEC and SPEC.loader
search = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = search
SPEC.loader.exec_module(search)


class CannonVariantSearchTests(unittest.TestCase):
    def spec(self, parent: Path) -> dict:
        return {
            "schema": "cannonlab-variant-search-v1",
            "job": "delay-sweep-test",
            "parent": str(parent),
            "max_candidates": 4,
            "max_changed_blocks": 1,
            "variables": [
                {
                    "id": "delay",
                    "values": [1, 2, 3, 4],
                    "declared_variable": "repeater delay=$value",
                    "operation": {
                        "type": "set-repeater-delay",
                        "position": [1, 2, 3],
                        "expected_state": "minecraft:repeater[delay=2,facing=east,locked=false,powered=false]",
                        "delay": "$value",
                    },
                }
            ],
            "runtime_contract": {
                "required_metrics": ["target_destroyed", "self_damage", "repeatability"],
                "hard_limits": [{"metric": "self_damage", "op": "<=", "value": 10}],
                "objectives": [
                    {"metric": "target_destroyed", "direction": "max", "weight": 5},
                    {"metric": "self_damage", "direction": "min", "weight": 3},
                    {"metric": "repeatability", "direction": "max", "weight": 4},
                ],
            },
        }

    def test_cartesian_search_is_deterministic(self) -> None:
        variables = [
            {"id": "a", "values": [1, 2], "operation": {"type": "set-block-state", "position": [0, 0, 0], "state": "$value"}},
            {"id": "b", "values": ["x", "y"], "operation": {"type": "set-block-state", "position": [1, 0, 0], "state": "$value"}},
        ]
        first = search.combinations(variables)
        second = search.combinations(variables)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)

    def test_search_refuses_random_overflow(self) -> None:
        spec = {
            "schema": "cannonlab-variant-search-v1",
            "max_candidates": 3,
            "variables": [{"id": "delay", "values": [1, 2, 3, 4], "operation": {"type": "set-repeater-delay"}}],
        }
        with self.assertRaises(ValueError):
            search.validate_spec(spec)

    def test_render_preserves_non_placeholder_values(self) -> None:
        template = {"delay": "$value", "position": [1, 2, 3], "label": "delay=${value}"}
        self.assertEqual(search.render(template, 4), {"delay": 4, "position": [1, 2, 3], "label": "delay=4"})

    def test_generate_writes_every_declared_plan(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            parent = root / "parent.schem"
            parent.write_bytes(b"schematic-fixture")
            spec_path = root / "search.json"
            spec_path.write_text(json.dumps(self.spec(parent)), encoding="utf-8")
            result = search.generate(str(spec_path), apply=False)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["candidate_count"], 4)
            self.assertEqual(len({item["variant_id"] for item in result["candidates"]}), 4)
            for candidate in result["candidates"]:
                self.assertTrue((ROOT / candidate["mutation_plan"]).is_file())

    def test_generate_ranks_static_passes_only(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            parent = root / "parent.schem"
            parent.write_bytes(b"schematic-fixture")
            spec_path = root / "search.json"
            spec = self.spec(parent)
            spec["variables"][0]["values"] = [1, 2]
            spec["max_candidates"] = 2
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            passing = {
                "status": "PASS",
                "changed_blocks": 1,
                "preservation": {"summary": {"risk_score": 1, "structural_change_ratio": 0.001, "functional_change_ratio": 0.001}},
                "alignment": {"dispensers": {"worldedit_paste_point_alignment": {"safe_count": 2, "best": {"max": 155}}}},
            }
            with patch.object(search, "run_json", side_effect=[(0, passing), (2, {"status": "BLOCKED"})]):
                result = search.generate(str(spec_path), apply=True, use_cache=False)
            self.assertEqual(result["status"], "PASS")
            self.assertIsNotNone(result["candidates"][0]["static_score"])
            self.assertIsNone(result["candidates"][1]["static_score"])

    def test_parallel_static_mutations_use_multiple_workers(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            parent = root / "parent.schem"
            parent.write_bytes(b"parallel-parent")
            spec_path = root / "search.json"
            spec_path.write_text(json.dumps(self.spec(parent)), encoding="utf-8")
            lock = threading.Lock()
            active = 0
            maximum_active = 0

            def fake_run(_command: list[str], timeout: int = 1200):
                nonlocal active, maximum_active
                with lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                time.sleep(0.05)
                with lock:
                    active -= 1
                return 0, {
                    "status": "PASS",
                    "changed_blocks": 1,
                    "preservation": {"summary": {}},
                    "alignment": {"dispensers": {"worldedit_paste_point_alignment": {"safe_count": 1, "best": {"max": 1}}}},
                }

            with patch.object(search, "run_json", side_effect=fake_run):
                result = search.generate(
                    str(spec_path),
                    apply=True,
                    workers=4,
                    use_cache=False,
                )
            self.assertEqual(result["status"], "PASS", result)
            self.assertGreaterEqual(maximum_active, 2)
            self.assertEqual(result["performance"]["workers"], 4)
            self.assertEqual(result["performance"]["unique_mutation_plans"], 4)

    def test_identical_rendered_mutations_are_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            parent = root / "parent.schem"
            parent.write_bytes(b"dedupe-parent")
            spec = self.spec(parent)
            spec["variables"][0]["values"] = [2, 2]
            spec["max_candidates"] = 2
            spec_path = root / "search.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            passing = {
                "status": "PASS",
                "changed_blocks": 1,
                "preservation": {"summary": {}},
                "alignment": {"dispensers": {"worldedit_paste_point_alignment": {"safe_count": 1, "best": {"max": 1}}}},
            }
            with patch.object(search, "run_json", return_value=(0, passing)) as mocked:
                result = search.generate(str(spec_path), apply=True, workers=4, use_cache=False)
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(result["performance"]["deduplicated_candidates"], 1)
            duplicate = next(item for item in result["candidates"] if item["deduplicated_from"])
            self.assertEqual(duplicate["deduplicated_from"], result["candidates"][0]["variant_id"])

    def test_content_addressed_cache_skips_repeated_mutation(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            parent = root / "parent.schem"
            parent.write_bytes(b"cache-parent")
            spec = self.spec(parent)
            spec["variables"][0]["values"] = [2]
            spec["max_candidates"] = 1
            spec_path = root / "search.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")

            def fake_run(command: list[str], timeout: int = 1200):
                plan = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
                output = Path(plan["output"])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"cached-candidate")
                return 0, {
                    "status": "PASS",
                    "changed_blocks": 1,
                    "output": {"path": str(output)},
                    "preservation": {"summary": {}},
                    "alignment": {"dispensers": {"worldedit_paste_point_alignment": {"safe_count": 1, "best": {"max": 1}}}},
                }

            with (
                patch.object(search, "OUTPUT_ROOT", root / "output"),
                patch.object(search, "VARIANT_ROOT", root / "variant-jobs"),
                patch.object(search, "CACHE_ROOT", root / "cache"),
                patch.object(search, "run_json", side_effect=fake_run) as mocked,
            ):
                first = search.generate(str(spec_path), apply=True, workers=1, use_cache=True)
                second = search.generate(str(spec_path), apply=True, workers=1, use_cache=True)
            self.assertEqual(first["performance"]["cache_hits"], 0)
            self.assertEqual(second["performance"]["cache_hits"], 1)
            self.assertEqual(mocked.call_count, 1)
            self.assertTrue(second["candidates"][0]["cache_hit"])

    def write_manifest_and_scorecard(self, root: Path) -> tuple[Path, Path]:
        manifest = {
            "schema": "cannonlab-variant-search-manifest-v1",
            "job": "runtime-rank-test",
            "runtime_contract": self.spec(root / "unused.schem")["runtime_contract"],
            "candidates": [
                {"variant_id": "v000-a", "selected": {"delay": 1}, "static_score": 900},
                {"variant_id": "v001-b", "selected": {"delay": 2}, "static_score": 910},
                {"variant_id": "v002-c", "selected": {"delay": 3}, "static_score": 920},
            ],
        }
        scorecard = {
            "schema": "cannonlab-variant-runtime-scorecard-v1",
            "variants": {
                "v000-a": {"metrics": {"target_destroyed": 20, "self_damage": 2, "repeatability": 0.9}},
                "v001-b": {"metrics": {"target_destroyed": 30, "self_damage": 20, "repeatability": 1.0}},
                "v002-c": {"metrics": {"target_destroyed": 25, "self_damage": 4, "repeatability": 0.95}},
            },
        }
        manifest_path = root / "manifest.json"
        scorecard_path = root / "scorecard.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        scorecard_path.write_text(json.dumps(scorecard), encoding="utf-8")
        return manifest_path, scorecard_path

    def test_runtime_ranking_rejects_self_damage_cheat(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            manifest, scorecard = self.write_manifest_and_scorecard(Path(directory))
            result = search.rank(str(manifest), str(scorecard))
            self.assertEqual(result["status"], "PASS")
            rejected = next(item for item in result["ranking"] if item["variant_id"] == "v001-b")
            self.assertFalse(rejected["eligible"])
            self.assertIn("runtime-hard-limit-failed", {item["code"] for item in rejected["blockers"]})
            self.assertEqual(result["winner"]["variant_id"], "v002-c")

    def test_runtime_ranking_fails_closed_on_missing_metrics(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest, scorecard = self.write_manifest_and_scorecard(root)
            payload = json.loads(scorecard.read_text())
            payload["variants"] = {"v000-a": {"metrics": {"target_destroyed": 1}}}
            scorecard.write_text(json.dumps(payload), encoding="utf-8")
            result = search.rank(str(manifest), str(scorecard))
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIsNone(result["winner"])

    def test_output_truth_boundary_never_promotes_ec(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            manifest, scorecard = self.write_manifest_and_scorecard(Path(directory))
            result = search.rank(str(manifest), str(scorecard))
            self.assertIn("not automatically EC-ready", result["truth_boundary"])

    def test_runtime_winner_is_materialized_for_handoff(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest, scorecard = self.write_manifest_and_scorecard(root)
            winner_source = root / "winner-source.schem"
            winner_source.write_bytes(b"winner-schematic")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            candidate = next(row for row in payload["candidates"] if row["variant_id"] == "v002-c")
            candidate["result"] = {"output": {"path": str(winner_source)}}
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(search, "VARIANT_ROOT", root / "variant-jobs"):
                result = search.rank(str(manifest), str(scorecard))
            handoff = result["winner_handoff"]
            self.assertEqual(handoff["status"], "READY", handoff)
            copied = Path(handoff["schematic"]["path"])
            self.assertTrue(copied.is_file())
            self.assertEqual(copied.read_bytes(), winner_source.read_bytes())
            self.assertTrue(Path(handoff["handoff_path"]).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
