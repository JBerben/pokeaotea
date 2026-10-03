# ABOUTME: Tests for map rendering (map model + props + the area's textures) and the mapedit-render CLI.
# ABOUTME: Twinleaf Town (one block) and Route 201 (two blocks) are the reference maps.

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from mapedit import maps
from mapedit.render import map_render

TWINLEAF = 'MAP_HEADER_TWINLEAF_TOWN'


class MapRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = maps.MapRepository(maps.REPO)

    def test_renders_the_map_model_and_props_with_the_areas_textures(self):
        result = map_render.render_map(self.repository, TWINLEAF, view='top', size=256)

        self.assertEqual(result.image.shape, (256, 256, 4))
        self.assertEqual(result.blocks, ['000'])
        self.assertEqual(result.props, 8)
        self.assertEqual(result.missing_textures, [])
        drawn = result.image[result.image[..., 3] > 0][:, :3]
        self.assertGreater(len(drawn) / (256 * 256), 0.9)
        self.assertGreater(len(np.unique(drawn, axis=0)), 100)

    def test_props_appear_where_the_land_data_places_them(self):
        with_props = map_render.render_map(self.repository, TWINLEAF, view='top', size=256).image
        without = map_render.render_map(self.repository, TWINLEAF, view='top', size=256, props=False).image

        changed = np.any(with_props != without, axis=2)
        # The first house is at world tile (106, 873.5): column 10.5, row 9.5 of the block's 32x32 tiles.
        self.assertTrue(changed[int(9.5 / 32 * 256), int(10.5 / 32 * 256)])
        self.assertLess(changed.mean(), 0.5)

    def test_multi_block_maps_are_laid_out_by_the_matrix(self):
        result = map_render.render_map(self.repository, 'MAP_HEADER_ROUTE_201', view='top', size=256)

        self.assertEqual(len(result.blocks), 2)
        height, width = result.image.shape[:2]
        self.assertAlmostEqual(width / height, 2.0, delta=0.15)

    def test_missing_prop_textures_are_reported(self):
        result = map_render.render_map(self.repository, TWINLEAF, view='top', size=64, prop_texture_set='prop_model_set_001')

        self.assertTrue(result.missing_textures)

    def test_markers_mark_events_on_the_top_view(self):
        plain = map_render.render_map(self.repository, TWINLEAF, view='top', size=256).image
        marked = map_render.render_map(self.repository, TWINLEAF, view='top', size=256, markers=True).image

        self.assertTrue(np.any(plain != marked))

    def test_angled_view_renders(self):
        result = map_render.render_map(self.repository, TWINLEAF, view='angled', size=128)

        self.assertGreater((result.image[..., 3] > 0).mean(), 0.3)


class CommandLineTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'mapedit.render', *args], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[1])

    def test_map_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'twinleaf.png'

            result = self.run_cli('map', TWINLEAF, '--view', 'top', '--size', '128', '-o', str(output), '--json')

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['output'], str(output))
            self.assertEqual(report['blocks'], ['000'])
            self.assertEqual(Image.open(output).size, (128, 128))

    def test_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'house.png'
            model = maps.REPO / 'res/field/props/models/prop_model_022.nsbmd'

            result = self.run_cli('model', str(model), '--area-set', '000', '--size', '96', '-o', str(output), '--json')

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['missing_textures'], [])
            self.assertEqual(max(Image.open(output).size), 96)

    def test_unknown_map_is_an_error(self):
        result = self.run_cli('map', 'MAP_HEADER_NOWHERE', '-o', '/tmp/never.png', '--json')

        self.assertEqual(result.returncode, 1)
        self.assertIn('MAP_HEADER_NOWHERE', json.loads(result.stdout)['errors'][0])


if __name__ == '__main__':
    unittest.main()
