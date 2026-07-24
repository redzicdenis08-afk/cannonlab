#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import nbtlib
from nbtlib import Compound, IntArray, List, String


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cannon-mutator.py"
SPEC = importlib.util.spec_from_file_location("cannon_mutator", SCRIPT)
assert SPEC and SPEC.loader
mutator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mutator
SPEC.loader.exec_module(mutator)


class CannonMutatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output_root = self.root / "output"
        self.output_root.mkdir()
        self.originals = {
            "ROOT": mutator.ROOT,
            "OUTPUT_ROOT": mutator.OUTPUT_ROOT,
            "MUTATION_ROOT": mutator.MUTATION_ROOT,
        }
        mutator.ROOT = self.root
        mutator.OUTPUT_ROOT = self.output_root
        mutator.MUTATION_ROOT = self.root / "mutation-jobs"
        self.addCleanup(self.restore)

        self.parent = self.root / "parent.schem"
        blocks = {
            (1, 1, 1): "minecraft:repeater[delay=1,facing=north,locked=false,powered=false]",
            (2, 1, 1): "minecraft:dispenser[facing=east,triggered=false]",
            (4, 1, 1): "minecraft:obsidian",
        }
        entity = Compound({
            "Id": String("minecraft:dispenser"),
            "Pos": IntArray([2, 1, 1]),
            "Items": List[Compound]([]),
            "CustomName": String('{"text":"payload"}'),
        })
        mutator.write_sponge_v2(
            self.parent,
            blocks=blocks,
            dimensions={"width": 6, "height": 3, "length": 3},
            entities={(2, 1, 1): entity},
            data_version=3465,
        )
        self.parent_hash = mutator.sha256(self.parent)

    def restore(self) -> None:
        for name, value in self.originals.items():
            setattr(mutator, name, value)

    def plan(self, operations: list[dict[str, object]], *, budget: int = 4, job: str = "test") -> Path:
        plan = self.root / f"{job}.json"
        plan.write_text(json.dumps({
            "schema": "cannonlab-bounded-mutation-plan-v1",
            "job": job,
            "parent": str(self.parent),
            "output": str(self.root / f"{job}.schem"),
            "declared_variable": "one reviewed test variable",
            "max_changed_blocks": budget,
            "chunk_limit": 160,
            "operations": operations,
            "preservation": {
                "max_structural_change_ratio": 0.5,
                "max_functional_change_ratio": 0.5,
                "max_modules_touched": 1,
            },
        }, indent=2), encoding="utf-8")
        return plan

    def passing_run_json(self, command: list[str], timeout: int = 600):
        name = Path(command[1]).name
        if name == "paste-alignment-audit.py":
            return 0, {"status": "PASS", "safe_alignment_count": 256}
        return 0, {"status": "PASS", "preserved": True}

    def test_set_repeater_delay_preserves_other_properties(self) -> None:
        expected = "minecraft:repeater[delay=1,facing=north,locked=false,powered=false]"
        plan = self.plan([{
            "type": "set-repeater-delay",
            "position": [1, 1, 1],
            "expected_state": expected,
            "delay": 3,
        }], budget=1, job="delay")
        with mock.patch.object(mutator, "run_json", side_effect=self.passing_run_json):
            result = mutator.apply_plan(str(plan))
        self.assertEqual(result["status"], "PASS", result)
        model = mutator.read_model(self.root / "delay.schem")
        self.assertEqual(
            model["blocks"][(1, 1, 1)],
            "minecraft:repeater[delay=3,facing=north,locked=false,powered=false]",
        )
        self.assertEqual(mutator.sha256(self.parent), self.parent_hash)

    def test_expected_state_mismatch_fails_closed(self) -> None:
        plan = self.plan([{
            "type": "set-repeater-delay",
            "position": [1, 1, 1],
            "expected_state": "minecraft:repeater[delay=4,facing=north,locked=false,powered=false]",
            "delay": 2,
        }], job="mismatch")
        with self.assertRaisesRegex(ValueError, "expected"):
            mutator.apply_plan(str(plan))

    def test_translate_region_moves_block_entity_and_preserves_nbt(self) -> None:
        plan = self.plan([{
            "type": "translate-region",
            "min": [2, 1, 1],
            "max": [2, 1, 1],
            "delta": [1, 0, 0],
            "expected_non_air": 1,
        }], budget=2, job="move")
        with mock.patch.object(mutator, "run_json", side_effect=self.passing_run_json):
            result = mutator.apply_plan(str(plan))
        self.assertEqual(result["block_entities_before"], 1)
        self.assertEqual(result["block_entities_after"], 1)
        model = mutator.read_model(self.root / "move.schem")
        self.assertEqual(model["blocks"][(2, 1, 1)], "minecraft:air")
        self.assertEqual(mutator.AUDITOR.base(model["blocks"][(3, 1, 1)]), "minecraft:dispenser")
        output = nbtlib.load(self.root / "move.schem")
        entities = list(output["BlockEntities"])
        self.assertEqual(tuple(map(int, entities[0]["Pos"])), (3, 1, 1))
        self.assertEqual(str(entities[0]["CustomName"]), '{"text":"payload"}')
        self.assertIn("Items", entities[0])

    def test_translate_collision_is_rejected(self) -> None:
        plan = self.plan([{
            "type": "translate-region",
            "min": [2, 1, 1],
            "max": [2, 1, 1],
            "delta": [2, 0, 0],
            "expected_non_air": 1,
        }], job="collision")
        with self.assertRaisesRegex(ValueError, "collision"):
            mutator.apply_plan(str(plan))

    def test_change_budget_counts_source_and_target(self) -> None:
        plan = self.plan([{
            "type": "translate-region",
            "min": [2, 1, 1],
            "max": [2, 1, 1],
            "delta": [1, 0, 0],
            "expected_non_air": 1,
        }], budget=1, job="budget")
        with self.assertRaisesRegex(ValueError, "budget"):
            mutator.apply_plan(str(plan))

    def test_deletion_operation_is_not_supported(self) -> None:
        plan = self.plan([{"type": "delete-region", "min": [1, 1, 1], "max": [1, 1, 1]}], job="delete")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            mutator.apply_plan(str(plan))

    def test_set_block_cannot_remove_tile_entity(self) -> None:
        expected = "minecraft:dispenser[facing=east,triggered=false]"
        plan = self.plan([{
            "type": "set-block-state",
            "position": [2, 1, 1],
            "expected_state": expected,
            "new_state": "minecraft:obsidian",
        }], job="tile")
        with self.assertRaisesRegex(ValueError, "block-entity"):
            mutator.apply_plan(str(plan))

    def test_require_ec160_safe_blocks_failed_alignment(self) -> None:
        plan = json.loads(self.plan([{
            "type": "set-repeater-delay",
            "position": [1, 1, 1],
            "expected_state": "minecraft:repeater[delay=1,facing=north,locked=false,powered=false]",
            "delay": 2,
        }], budget=1, job="ec160").read_text(encoding="utf-8"))
        plan["require_ec160_safe"] = True
        plan_path = self.root / "ec160.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")

        def failing_alignment(command: list[str], timeout: int = 600):
            if Path(command[1]).name == "paste-alignment-audit.py":
                return 2, {"status": "FAIL", "safe_alignment_count": 0}
            return 0, {"status": "PASS"}

        with mock.patch.object(mutator, "run_json", side_effect=failing_alignment):
            result = mutator.apply_plan(str(plan_path))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("ec160-alignment-failed", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
