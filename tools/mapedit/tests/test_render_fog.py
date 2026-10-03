# ABOUTME: Tests for weather fog and the game camera view: the fog table (checked against the weather source),
# ABOUTME: the DS fog density ramp, the overworld camera's framing, and fogged renders of Route 210 North.

import re
import unittest

import numpy as np

from mapedit import maps
from mapedit.render import fog, map_render, scene

R = maps.REPO
ROUTE_210 = 'MAP_HEADER_ROUTE_210_NORTH'


class FogTableTest(unittest.TestCase):
    def test_weather_fog_matches_the_weather_code(self):
        # Each weather's task in ov5_021D5EB8.c calls ov5_021D7308(..., slope, offset, colour, ...).
        source = (R / 'src/overlay005/ov5_021D5EB8.c').read_text()
        for weather, function in (('OVERWORLD_WEATHER_FOG', 'ov5_021DAEC0'), ('OVERWORLD_WEATHER_DEEP_FOG', 'ov5_021DAD38'),
                                  ('OVERWORLD_WEATHER_SANDSTORM', 'ov5_021D8D08')):
            # The definition (followed by its body), not the prototype near the top of the file.
            body = source[re.search(rf'static void {function}\(SysTask[^;{{]*\)\s*\{{', source).start():]
            slope, offset, colour = re.search(r'ov5_021D7308\([^,]+,[^,]+,[^,]+,\s*([^,]+),\s*([^,]+),\s*\(?GX_RGB\(([^)]*)\)', body).groups()
            expected = fog.WEATHER_FOG[weather]
            with self.subTest(weather=weather):
                self.assertEqual(expected.slope, eval(slope))
                self.assertEqual(expected.offset, eval(offset))
                self.assertEqual(expected.colour555, tuple(int(c) for c in colour.split(',')))

    def test_the_settled_density_table_ramps_to_full(self):
        # ov5_021D7534 at the end of its fade-in: entry i is min(4 * i, 127).
        self.assertEqual(fog.DENSITY_TABLE[:4], [0, 4, 8, 12])
        self.assertEqual(fog.DENSITY_TABLE[-1], 124)

    def test_density_steps_through_the_table_by_slope(self):
        settings = fog.WEATHER_FOG['OVERWORLD_WEATHER_FOG']
        span = 0x400 >> settings.slope

        self.assertEqual(fog.density(np.array([settings.offset - 10]), settings)[0], 0)
        self.assertAlmostEqual(fog.density(np.array([settings.offset + 5 * span]), settings)[0], 20 / 128)
        self.assertAlmostEqual(fog.density(np.array([0x7FFF]), settings)[0], 124 / 128)


class GameCameraTest(unittest.TestCase):
    def test_the_target_tile_is_in_the_middle_of_a_4_by_3_image(self):
        target = np.array([100.0, 0.0, 200.0])
        camera = scene.game_camera(target, 256)

        self.assertEqual((camera.width, camera.height), (256, 192))
        from mapedit.render import raster
        x, y, _, _ = raster.project(camera, target[None])
        self.assertAlmostEqual(x[0], 128, delta=0.5)
        self.assertAlmostEqual(y[0], 96, delta=0.5)


class FoggedRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = maps.MapRepository(R)
        block = cls.repository.context.blocks(ROUTE_210)[1]
        cls.at = (block.base_x + 16, block.base_z + 16)

    def test_fog_whitens_the_distance_more_than_the_foreground(self):
        clear = map_render.render_map(self.repository, ROUTE_210, view='game', at=self.at, size=128, weather=None).image
        fogged = map_render.render_map(self.repository, ROUTE_210, view='game', at=self.at, size=128).image

        def whiteness(image, rows):
            return image[rows, :, :3].astype(float).mean()

        far, near = slice(0, 20), slice(-20, None)
        self.assertGreater(whiteness(fogged, far) - whiteness(clear, far), 10)
        self.assertGreater(whiteness(fogged, far) - whiteness(clear, far), whiteness(fogged, near) - whiteness(clear, near))

    def test_the_maps_own_weather_is_the_default(self):
        result = map_render.render_map(self.repository, ROUTE_210, view='game', at=self.at, size=64)

        self.assertEqual(result.weather, 'OVERWORLD_WEATHER_FOG')

    def test_fog_only_applies_to_the_game_view(self):
        top = map_render.render_map(self.repository, ROUTE_210, size=64)
        plain = map_render.render_map(self.repository, ROUTE_210, size=64, weather=None)

        np.testing.assert_array_equal(top.image, plain.image)


if __name__ == '__main__':
    unittest.main()


class GameViewCommandLineTest(unittest.TestCase):
    def test_game_view_at_a_tile_with_the_maps_fog(self):
        import json
        import subprocess
        import sys
        import tempfile
        from pathlib import Path
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'player.png'
            result = subprocess.run([sys.executable, '-m', 'mapedit.render', 'map', ROUTE_210, '--view', 'game',
                                     '--at', '528,528', '--size', '128', '-o', str(output), '--json'],
                                    capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['weather'], 'OVERWORLD_WEATHER_FOG')
            with Image.open(output) as image:
                self.assertEqual(image.size, (128, 96))
