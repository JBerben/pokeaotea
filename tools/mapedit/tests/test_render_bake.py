# ABOUTME: Tests for baked animation playback: rasterise once, then re-texture animated surfaces each frame.
# ABOUTME: The oracle is a full direct render at the same tick; baked frames must match it.

import time
import unittest

import numpy as np

from mapedit import maps
from mapedit.render import map_render

R = maps.REPO


class BakedMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = maps.MapRepository(R)
        cls.animations = map_render.Animations(R)

    def assert_frames_match(self, header, view, ticks, size=160):
        baked = map_render.bake_map(self.repository, header, view=view, size=size, animations=self.animations)
        for tick in ticks:
            direct = map_render.render_map(self.repository, header, view=view, size=size, tick=tick,
                                           animations=self.animations).image
            frame = baked.frame(tick)
            mismatched = np.any(np.abs(frame.astype(int) - direct.astype(int)) > 2, axis=2).mean()
            with self.subTest(header=header, view=view, tick=tick):
                self.assertLess(mismatched, 0.002)

    def test_waterfalls_match_direct_renders(self):
        self.assert_frames_match('MAP_HEADER_ROUTE_210_NORTH', 'top', (0, 13, 40))
        self.assert_frames_match('MAP_HEADER_ROUTE_208', 'angled', (0, 7))

    def test_ground_tiles_match_direct_renders(self):
        self.assert_frames_match('MAP_HEADER_SANDGEM_TOWN', 'top', (0, 37, 79))

    def test_animated_surfaces_change_and_static_ones_do_not(self):
        baked = map_render.bake_map(self.repository, 'MAP_HEADER_ROUTE_210_NORTH', size=160, animations=self.animations)

        self.assertTrue(baked.animated)
        self.assertFalse(np.array_equal(baked.frame(0), baked.frame(15)))

    def test_a_map_without_animations_says_so(self):
        baked = map_render.bake_map(self.repository, 'MAP_HEADER_TWINLEAF_TOWN', size=96, animations=self.animations)

        self.assertFalse(baked.animated)
        np.testing.assert_array_equal(baked.frame(0), baked.frame(31))

    def test_frames_are_much_cheaper_than_renders(self):
        baked = map_render.bake_map(self.repository, 'MAP_HEADER_ROUTE_210_NORTH', size=256, animations=self.animations)
        start = time.perf_counter()
        map_render.render_map(self.repository, 'MAP_HEADER_ROUTE_210_NORTH', size=256, tick=5, animations=self.animations)
        render_time = time.perf_counter() - start

        start = time.perf_counter()
        for tick in range(10):
            baked.frame(tick)
        frame_time = (time.perf_counter() - start) / 10

        self.assertLess(frame_time, render_time / 5)


if __name__ == '__main__':
    unittest.main()
