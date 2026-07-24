#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("ec160_architecture_advisor.py")
SPEC = importlib.util.spec_from_file_location("ec160_architecture_advisor", MODULE_PATH)
assert SPEC and SPEC.loader
advisor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = advisor
SPEC.loader.exec_module(advisor)


class EC160ArchitectureAdvisorTests(unittest.TestCase):
    def test_groups_dense_same_facing_panel(self) -> None:
        dispensers = {
            (0, y, z): "east"
            for y in range(10)
            for z in range(17)
        }
        banks = advisor.group_dispenser_banks(dispensers)
        self.assertEqual(len(banks), 1)
        self.assertEqual(banks[0]["count"], 170)
        self.assertEqual(banks[0]["facing"], "east")

    def test_keeps_opposite_panels_separate_and_pairs_them(self) -> None:
        dispensers = {}
        for y in range(8):
            for z in range(12):
                dispensers[(0, y, z)] = "east"
                dispensers[(5, y, z)] = "west"
        banks = advisor.group_dispenser_banks(dispensers)
        self.assertEqual(len(banks), 2)
        pairs = advisor.opposing_pairs(banks)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["confidence"], "high")
        self.assertEqual(sorted(pairs[0]["counts"]), [96, 96])

    def test_east_west_bank_splits_across_z(self) -> None:
        dispensers = {
            (0, y, z): "east"
            for y in range(10)
            for z in range(20)
        }
        bank = advisor.group_dispenser_banks(dispensers)[0]
        plan = advisor.bank_segmentation(bank, 160)
        self.assertEqual(plan["preferred_split_axis"], "z")
        self.assertEqual(plan["minimum_chunk_columns"], 2)
        self.assertEqual(plan["segment_count"], 2)
        self.assertTrue(all(segment["dispensers"] <= 160 for segment in plan["proposed_coordinate_segments"]))

    def test_north_south_bank_splits_across_x(self) -> None:
        dispensers = {
            (x, y, 0): "north"
            for x in range(20)
            for y in range(10)
        }
        bank = advisor.group_dispenser_banks(dispensers)[0]
        plan = advisor.bank_segmentation(bank, 160)
        self.assertEqual(plan["preferred_split_axis"], "x")
        self.assertEqual(plan["segment_count"], 2)

    def test_single_coordinate_overflow_is_not_hidden(self) -> None:
        counts = {0: 170, 1: 10}
        segments, warnings = advisor.greedy_coordinate_segments(counts, 160)
        self.assertTrue(segments[0]["requires_secondary_axis_split"])
        self.assertTrue(warnings)

    def test_chunk_distribution_uses_paste_origin_residue(self) -> None:
        dispensers = {(0, 0, 0): "east", (15, 0, 0): "east"}
        aligned = advisor.chunk_distribution(dispensers, 0, 0)
        shifted = advisor.chunk_distribution(dispensers, 1, 0)
        self.assertEqual(len(aligned), 1)
        self.assertEqual(len(shifted), 2)

    def test_worldedit_offset_converts_minimum_corner_to_player_paste(self) -> None:
        player = advisor.paste_point_for_min_corner(7, 5, 0, -17)
        self.assertEqual(player, (7, 6))

    def test_placement_fragility_distinguishes_illegal_from_fragile(self) -> None:
        self.assertEqual(advisor.placement_fragility(0), "none-legal")
        self.assertEqual(advisor.placement_fragility(2), "extreme")



if __name__ == "__main__":
    unittest.main(verbosity=2)
