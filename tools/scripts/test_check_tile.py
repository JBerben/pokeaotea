#!/usr/bin/env python3
# ABOUTME: Tests for check_tile.py's tile classification, shared with the mapedit tile grid.
# ABOUTME: Run with `python3 -m unittest tools.scripts.test_check_tile` from the repo root.

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import check_tile as ct  # noqa: E402

NAMES = ct.tile_behavior_names()


def behavior(name):
    return NAMES.index(name)


class ClassifyTileTest(unittest.TestCase):
    def test_plain_ground_is_walkable(self):
        self.assertEqual(ct.classify_tile(0, behavior('TILE_BEHAVIOR_NONE'), NAMES), ct.TILE_WALKABLE)

    def test_collision_is_blocked(self):
        self.assertEqual(ct.classify_tile(1, behavior('TILE_BEHAVIOR_NONE'), NAMES), ct.TILE_BLOCKED)

    def test_blocked_door_is_a_door(self):
        self.assertEqual(ct.classify_tile(1, behavior('TILE_BEHAVIOR_DOOR'), NAMES), ct.TILE_DOOR)

    def test_water_behaviors_are_water(self):
        water = next(name for name in NAMES if 'WATER' in name)

        self.assertEqual(ct.classify_tile(0, behavior(water), NAMES), ct.TILE_WATER)

    def test_other_behaviors_are_special(self):
        self.assertEqual(ct.classify_tile(0, behavior('TILE_BEHAVIOR_TALL_GRASS'), NAMES), ct.TILE_SPECIAL)

    def test_symbols_match_the_map_legend(self):
        self.assertEqual([ct.TILE_SYMBOLS[kind] for kind in (ct.TILE_WALKABLE, ct.TILE_BLOCKED, ct.TILE_WATER, ct.TILE_DOOR, ct.TILE_SPECIAL)],
                         ['.', '#', '~', 'D', '+'])


if __name__ == '__main__':
    unittest.main()
