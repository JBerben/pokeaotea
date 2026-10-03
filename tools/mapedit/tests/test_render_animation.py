# ABOUTME: Tests for texture animations in the renderer: NSBTA texture-matrix tracks, NSBTP pattern swaps, and the
# ABOUTME: field ground-tile animations (fldtanime), plus animated map renders and GIF output.

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from mapedit import maps
from mapedit.render import animation, map_render
from mapedit.render import model as nsbmd

R = maps.REPO
ANIMATIONS = R / 'res/field/props/animations'
MODELS = R / 'res/field/props/models'


class TexSrtTest(unittest.TestCase):
    def setUp(self):
        self.anim = animation.load_texture_srt((ANIMATIONS / 'prop_animation_018.nsbta').read_bytes())

    def test_reads_the_waterfalls_tracks(self):
        model = nsbmd.load_model((MODELS / 'prop_model_305.nsbmd').read_bytes())

        self.assertGreater(self.anim.num_frames, 1)
        self.assertTrue(set(self.anim.materials) <= {m.name for m in model.materials})
        self.assertTrue(self.anim.materials)

    def test_the_water_moves_between_frames(self):
        material = next(iter(self.anim.materials))
        first = self.anim.at(material, 0)
        later = self.anim.at(material, self.anim.num_frames // 2)

        self.assertNotEqual((first.trans_s, first.trans_t), (later.trans_s, later.trans_t))

    def test_frames_wrap_around(self):
        material = next(iter(self.anim.materials))

        self.assertEqual(self.anim.at(material, 1), self.anim.at(material, 1 + self.anim.num_frames))


class SrtMatrixTest(unittest.TestCase):
    UVS = np.array([[0.0, 0.0], [32.0, 0.0], [0.0, 64.0]])

    def test_identity_leaves_texture_coordinates_alone(self):
        srt = animation.Srt(1.0, 1.0, 0.0, 1.0, 0.0, 0.0)

        np.testing.assert_allclose(animation.apply_srt(self.UVS, srt, 32, 64), self.UVS)

    def test_translation_scrolls_by_whole_textures(self):
        srt = animation.Srt(1.0, 1.0, 0.0, 1.0, 0.25, 0.5)

        moved = animation.apply_srt(self.UVS, srt, 32, 64)

        np.testing.assert_allclose(moved - self.UVS, [[-8, 32]] * 3)


class TexPatternTest(unittest.TestCase):
    def test_reads_frame_keyed_texture_swaps(self):
        pattern = animation.load_texture_pattern((ANIMATIONS / 'prop_animation_023.nsbtp').read_bytes())

        material = next(iter(pattern.materials))
        keys = pattern.materials[material]
        self.assertEqual(keys[0][0], 0)
        self.assertGreater(len({texture for _, texture, _ in keys}), 1)
        self.assertEqual(pattern.at(material, 0), keys[0][1:])


class GroundAnimationTest(unittest.TestCase):
    def setUp(self):
        self.ground = animation.GroundAnimations(R)

    def test_each_step_holds_for_hold_plus_one_ticks(self):
        sea = self.ground.animations['sea']
        hold = sea.sequence[0][1]

        self.assertEqual(sea.frame_at(0), sea.sequence[0][0])
        self.assertEqual(sea.frame_at(hold), sea.sequence[0][0])
        self.assertEqual(sea.frame_at(hold + 1), sea.sequence[1][0])
        self.assertEqual(sea.frame_at(sea.period), sea.frame_at(0))

    def test_frames_replace_texels_but_keep_the_base_texture_and_palette(self):
        sea = self.ground.animations['sea']
        texture = sea.texture_at(sea.period // 2)

        self.assertEqual(texture.name, 'sea')
        self.assertEqual(len(texture.data), len(sea.frames[0].data))


class AnimatedMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = maps.MapRepository(R)

    def test_route_208s_waterfall_and_water_move_over_time(self):
        first = map_render.render_map(self.repository, 'MAP_HEADER_ROUTE_208', size=192, tick=0).image
        later = map_render.render_map(self.repository, 'MAP_HEADER_ROUTE_208', size=192, tick=7).image

        self.assertTrue(np.any(first != later))

    def test_without_a_tick_the_map_is_drawn_unanimated(self):
        still = map_render.render_map(self.repository, 'MAP_HEADER_ROUTE_208', size=96).image
        again = map_render.render_map(self.repository, 'MAP_HEADER_ROUTE_208', size=96).image

        np.testing.assert_array_equal(still, again)

    def test_render_frames_returns_one_image_per_tick(self):
        frames = map_render.render_frames(self.repository, 'MAP_HEADER_ROUTE_208', ticks=range(0, 8, 2), size=64)

        self.assertEqual(len(frames), 4)
        self.assertEqual(frames[0].shape, frames[3].shape)


class AnimateCommandLineTest(unittest.TestCase):
    def test_animate_writes_a_gif(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'route_208.gif'

            result = subprocess.run([sys.executable, '-m', 'mapedit.render', 'map', 'MAP_HEADER_ROUTE_208', '--animate',
                                     '--frames', '6', '--size', '96', '-o', str(output), '--json'],
                                    capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['frames'], 6)
            # Pillow merges identical consecutive frames into longer ones; the total running time is kept.
            with Image.open(output) as gif:
                durations = []
                for index in range(gif.n_frames):
                    gif.seek(index)
                    durations.append(gif.info['duration'])
                self.assertGreater(gif.n_frames, 1)
            self.assertAlmostEqual(sum(durations), 6 * 1000 / 30, delta=6)


if __name__ == '__main__':
    unittest.main()
