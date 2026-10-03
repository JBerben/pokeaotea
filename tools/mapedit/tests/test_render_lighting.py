# ABOUTME: Tests for DS-style lighting: time-slot selection from the area lighting sets, the per-vertex lighting
# ABOUTME: formula, normals in the geometry decoder, and lit map renders at different times of day.

import unittest

import numpy as np

from mapedit import maps
from mapedit.render import lighting, map_render
from mapedit.render import model as nsbmd

from .test_render_model import gx_list, vtx16

R = maps.REPO


def normal(x, y, z):
    values = [round(v * 511) & 0x3FF for v in (x, y, z)]
    return (0x21, [values[0] | (values[1] << 10) | (values[2] << 20)])


class TimeSlotTest(unittest.TestCase):
    def setUp(self):
        self.outdoor = lighting.load_set(R, 'lighting_set_000')

    def test_the_game_picks_the_first_slot_ending_after_the_time(self):
        # AreaLightManager_New: endTime is in units of 2 seconds; the active slot is the first with endTime > seconds / 2.
        self.assertEqual(self.outdoor.slot_index(0), 1)                  # midnight: slot 0 ends at 0, so it never applies
        self.assertEqual(self.outdoor.slot_index(3 * 3600), 1)           # 03:00 -> ends 04:00 (7200)
        self.assertEqual(self.outdoor.slot_index(12 * 3600), 7)          # noon (21600) -> the slot ending at 27000
        self.assertEqual(self.outdoor.slot_index(24 * 3600 - 1), 14)

    def test_times_parse_as_hours_and_minutes(self):
        self.assertEqual(lighting.parse_time('06:30'), 6 * 3600 + 30 * 60)
        with self.assertRaisesRegex(ValueError, "time must be HH:MM"):
            lighting.parse_time('noon')

    def test_outdoor_sets_override_material_colours(self):
        self.assertTrue(lighting.load_set(R, 'lighting_set_000').outdoor)
        self.assertFalse(lighting.load_set(R, 'lighting_set_001').outdoor)


class FormulaTest(unittest.TestCase):
    def test_a_light_straight_onto_a_surface(self):
        light = lighting.Light(colour=np.array([1.0, 1.0, 1.0]), direction=np.array([0.0, -1.0, 0.0]))
        material = lighting.Reflection(diffuse=np.array([0.5, 0.5, 0.5]), ambient=np.array([0.25, 0.0, 0.0]),
                                       specular=np.zeros(3), emission=np.array([0.0, 0.0, 0.25]))

        colour = lighting.vertex_colours(np.array([[0.0, 1.0, 0.0]]), material, [light], light_mask=1,
                                         view=np.array([0.0, 0.0, -1.0]))

        np.testing.assert_allclose(colour, [[0.75, 0.5, 0.75]])

    def test_surfaces_facing_away_get_only_ambient_and_emission(self):
        light = lighting.Light(colour=np.ones(3), direction=np.array([0.0, -1.0, 0.0]))
        material = lighting.Reflection(diffuse=np.ones(3), ambient=np.full(3, 0.1), specular=np.zeros(3), emission=np.zeros(3))

        colour = lighting.vertex_colours(np.array([[0.0, -1.0, 0.0]]), material, [light], 1, np.array([0.0, 0.0, -1.0]))

        np.testing.assert_allclose(colour, [[0.1, 0.1, 0.1]])

    def test_disabled_lights_do_nothing_and_results_clamp(self):
        light = lighting.Light(colour=np.ones(3), direction=np.array([0.0, -1.0, 0.0]))
        material = lighting.Reflection(diffuse=np.ones(3), ambient=np.ones(3), specular=np.zeros(3), emission=np.full(3, 0.5))

        lit = lighting.vertex_colours(np.array([[0.0, 1.0, 0.0]]), material, [light], 1, np.array([0.0, 0.0, -1.0]))
        unlit = lighting.vertex_colours(np.array([[0.0, 1.0, 0.0]]), material, [light], 0, np.array([0.0, 0.0, -1.0]))

        np.testing.assert_allclose(lit, [[1.0, 1.0, 1.0]])
        np.testing.assert_allclose(unlit, [[0.5, 0.5, 0.5]])


class DecoderNormalTest(unittest.TestCase):
    def test_normal_lights_the_vertices_after_it_and_colour_ends_that(self):
        dl = gx_list((0x40, [0]), normal(0, 1, 0), vtx16(0, 0, 0), vtx16(1, 0, 0), (0x20, [0x001F]), vtx16(0, 1, 0), (0x41, []))

        primitive = nsbmd.decode_display_list(dl, np.eye(4), {})[0]

        self.assertEqual(list(primitive.lit), [True, True, False])
        np.testing.assert_allclose(primitive.normals[0], [0, 511 / 512, 0], atol=1e-6)

    def test_normals_turn_with_the_model_but_do_not_scale(self):
        rotate = np.eye(4)
        rotate[:3, :3] = [[0, 0, 2], [0, 2, 0], [-2, 0, 0]]     # 90 degrees about Y, scaled by 2
        dl = gx_list((0x40, [0]), normal(1, 0, 0), vtx16(0, 0, 0), vtx16(1, 0, 0), vtx16(0, 1, 0), (0x41, []))

        primitive = nsbmd.decode_display_list(dl, rotate, {})[0]

        # A 10-bit normal of "1.0" is 511/512; the hardware keeps that length, only the direction turns.
        np.testing.assert_allclose(primitive.normals[0], [0, 0, 511 / 512], atol=1e-6)

    def test_materials_carry_their_reflection_colours_and_light_mask(self):
        model = nsbmd.load_model((R / 'res/field/props/models/prop_model_022.nsbmd').read_bytes())

        material = model.materials[0]
        self.assertEqual(material.light_mask, material.poly_attr & 0xF)
        self.assertEqual(len(material.ambient), 3)


class LitRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = maps.MapRepository(R)

    def brightness(self, image):
        drawn = image[image[..., 3] > 0][:, :3]
        return drawn.mean()

    def test_night_is_darker_than_noon_where_the_lighting_set_changes(self):
        # Only lighting_set_000 varies through the day; Route 210 North (area_data_010) uses it.
        noon = map_render.render_map(self.repository, 'MAP_HEADER_ROUTE_210_NORTH', size=96, time=12 * 3600).image
        night = map_render.render_map(self.repository, 'MAP_HEADER_ROUTE_210_NORTH', size=96, time=23 * 3600).image

        self.assertLess(self.brightness(night), self.brightness(noon) * 0.9)

    def test_areas_on_a_constant_lighting_set_look_the_same_all_day(self):
        # Twinleaf Town uses lighting_set_001, whose 15 time slots are identical.
        noon = map_render.render_map(self.repository, 'MAP_HEADER_TWINLEAF_TOWN', size=64, time=12 * 3600).image
        night = map_render.render_map(self.repository, 'MAP_HEADER_TWINLEAF_TOWN', size=64, time=23 * 3600).image

        np.testing.assert_array_equal(noon, night)

    def test_lighting_is_applied(self):
        lit = map_render.render_map(self.repository, 'MAP_HEADER_TWINLEAF_TOWN', size=64).image
        unlit = map_render.render_map(self.repository, 'MAP_HEADER_TWINLEAF_TOWN', size=64, time=None).image

        self.assertFalse(np.array_equal(lit, unlit))


if __name__ == '__main__':
    unittest.main()


class TimeCommandLineTest(unittest.TestCase):
    def run_cli(self, *args):
        import subprocess
        import sys
        from pathlib import Path
        return subprocess.run([sys.executable, '-m', 'mapedit.render', *args], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[1])

    def test_time_is_reported_and_bad_times_are_errors(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            good = self.run_cli('map', 'MAP_HEADER_ROUTE_208', '--time', '18:30', '--size', '48',
                                '-o', str(Path(tmp) / 'dusk.png'), '--json')
            bad = self.run_cli('map', 'MAP_HEADER_ROUTE_208', '--time', 'dusk', '-o', str(Path(tmp) / 'x.png'), '--json')

        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(json.loads(good.stdout)['time'], '18:30')
        self.assertEqual(bad.returncode, 1)
        self.assertIn('time must be HH:MM', json.loads(bad.stdout)['errors'][0])
