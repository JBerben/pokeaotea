# ABOUTME: Tests for the rasteriser and model rendering: triangle coverage, depth, textures, and whole retail props.
# ABOUTME: Uses properties (coverage, footprint, determinism, colour variety) rather than golden images of retail art.

import unittest

import numpy as np

from mapedit import maps
from mapedit.render import raster, scene

MODELS = maps.REPO / 'res/field/props/models'
PROP_SET = maps.REPO / 'res/field/props/texture_sets/prop_texture_set_000.nsbtx'


def flat_mesh(triangles, colour=(255, 0, 0, 255)):
    tris = np.array(triangles, dtype=float)
    return scene.Mesh(positions=tris, uvs=np.zeros(tris.shape[:2] + (2,)), colours=np.ones(tris.shape),
                      texture=np.array([[colour]], dtype=np.uint8), alpha=1.0, wrap=(False, False, False, False))


class RasterTest(unittest.TestCase):
    def test_a_triangle_covers_half_its_bounding_square(self):
        mesh = flat_mesh([[[0, 0, 0], [1, 0, 0], [0, 0, 1]]])
        camera = scene.top_camera(np.array([0, 0, 0]), np.array([1, 0, 1]), 64)

        image = raster.render([mesh], camera, shading=False)

        coverage = (image[..., 3] > 0).mean()
        self.assertAlmostEqual(coverage, 0.5, delta=0.05)
        self.assertTrue(np.all(image[image[..., 3] > 0][:, :3] == [255, 0, 0]))

    def test_nearer_triangles_hide_farther_ones(self):
        low = flat_mesh([[[0, 0, 0], [1, 0, 0], [0, 0, 1]], [[1, 0, 0], [1, 0, 1], [0, 0, 1]]], (0, 0, 255, 255))
        high = flat_mesh([[[0, 1, 0], [1, 1, 0], [0, 1, 1]], [[1, 1, 0], [1, 1, 1], [0, 1, 1]]], (0, 255, 0, 255))
        camera = scene.top_camera(np.array([0, 0, 0]), np.array([1, 1, 1]), 32)

        for meshes in ([low, high], [high, low]):
            image = raster.render(meshes, camera, shading=False)
            self.assertTrue(np.all(image[16, 16, :3] == [0, 255, 0]))

    def test_top_view_has_north_up(self):
        # A triangle in the north-west (low x, low z) appears in the top-left of the image.
        mesh = flat_mesh([[[0, 0, 0], [0.4, 0, 0], [0, 0, 0.4]]])
        camera = scene.top_camera(np.array([0, 0, 0]), np.array([1, 0, 1]), 40)

        image = raster.render([mesh], camera, shading=False)

        ys, xs = np.nonzero(image[..., 3])
        self.assertLess(xs.mean(), 20)
        self.assertLess(ys.mean(), 20)


class ModelRenderTest(unittest.TestCase):
    def render(self, name, view='top', size=128, **options):
        return scene.render_model((MODELS / name).read_bytes(), PROP_SET.read_bytes(), view=view, size=size, **options)

    def test_renders_are_deterministic(self):
        np.testing.assert_array_equal(self.render('prop_model_022.nsbmd'), self.render('prop_model_022.nsbmd'))

    def test_a_house_renders_textured_from_above_and_at_an_angle(self):
        for view in ('top', 'angled'):
            image = self.render('prop_model_022.nsbmd', view)
            untextured = self.render('prop_model_022.nsbmd', view, textured=False)
            drawn = image[image[..., 3] > 0][:, :3]
            with self.subTest(view=view):
                self.assertGreater(len(drawn) / (image.shape[0] * image.shape[1]), 0.2)
                # Textures add colour variety that shading alone does not.
                plain = untextured[untextured[..., 3] > 0][:, :3]
                self.assertGreater(len(np.unique(drawn, axis=0)), len(np.unique(plain, axis=0)))

    def test_top_view_footprint_matches_the_model(self):
        from mapedit.render import model as nsbmd
        model = nsbmd.load_model((MODELS / 'prop_model_022.nsbmd').read_bytes())
        points = np.concatenate([p.positions for d in model.draws for p in d.primitives])
        width, depth = np.ptp(points[:, 0]), np.ptp(points[:, 2])

        image = self.render('prop_model_022.nsbmd')

        ys, xs = np.nonzero(image[..., 3])
        self.assertAlmostEqual((np.ptp(xs) + 1) / (np.ptp(ys) + 1), width / depth, delta=0.1)

    def test_textures_missing_from_the_area_set_render_white_like_the_game(self):
        # The waterfall's textures are not in prop texture set 000.
        image = self.render('prop_model_305.nsbmd', size=64, shading=False, use_embedded=False)

        drawn = image[image[..., 3] > 0][:, :3]
        self.assertTrue(np.all(drawn == 255))

    def test_embedded_textures_can_fill_in_for_previews(self):
        image = self.render('prop_model_305.nsbmd', size=64, shading=False)

        drawn = image[image[..., 3] > 0][:, :3]
        self.assertFalse(np.all(drawn == 255))


if __name__ == '__main__':
    unittest.main()
