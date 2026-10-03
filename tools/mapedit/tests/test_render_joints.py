# ABOUTME: Tests for NSBCA joint animations: decoding every retail animation, posing models, and jointed props
# ABOUTME: moving on maps. Doors (a known 90 degree hinge swing) and windmills are the reference animations.

import unittest

import numpy as np

from mapedit import maps
from mapedit.render import animation, map_render
from mapedit.render import model as nsbmd

R = maps.REPO
ANIMATIONS = R / 'res/field/props/animations'
MODELS = R / 'res/field/props/models'


def points(model):
    return np.concatenate([p.positions for draw in model.draws for p in draw.primitives])


class DecodeTest(unittest.TestCase):
    def test_every_retail_joint_animation_decodes_to_rotations(self):
        files = sorted(ANIMATIONS.glob('*.nsbca'))
        self.assertGreater(len(files), 20)
        for path in files:
            anim = animation.load_joint_animation(path.read_bytes())
            with self.subTest(animation=path.name):
                self.assertGreater(anim.num_frames, 0)
                for frame in range(0, anim.num_frames, max(1, anim.num_frames // 8)):
                    for srt in anim.srts_at(frame).values():
                        if srt.rotation is None:
                            continue
                        rows = np.array(srt.rotation).reshape(3, 3)
                        np.testing.assert_allclose(np.linalg.norm(rows, axis=1), 1, atol=0.05)
                        self.assertLess(abs(rows[0] @ rows[1]), 0.05)


class PoseTest(unittest.TestCase):
    def test_doors_swing_open_and_shut_on_a_vertical_hinge(self):
        # prop_animation_007/008 open and close doors over 8 frames; 009/010 do it over 6.
        for number, start_angle, end_angle in ((7, 0, 90), (8, 90, 0), (9, 0, 90), (10, 90, 0)):
            anim = animation.load_joint_animation((ANIMATIONS / f'prop_animation_{number:03}.nsbca').read_bytes())
            angles = []
            for frame in range(anim.num_frames):
                rows = np.array(anim.srts_at(frame)[0].rotation).reshape(3, 3)
                np.testing.assert_allclose(rows[1], [0, 1, 0], atol=1e-3)        # turning about Y only
                angles.append(np.degrees(np.arctan2(rows[0, 2], rows[0, 0])))
            with self.subTest(animation=number):
                self.assertAlmostEqual(angles[0], start_angle, delta=0.5)
                self.assertAlmostEqual(angles[-1], end_angle, delta=0.5)
                np.testing.assert_allclose(np.diff(angles), np.diff(angles).mean(), atol=0.5)   # an even swing

    def test_posing_a_door_turns_its_geometry(self):
        data = (MODELS / 'door01.nsbmd').read_bytes()
        anim = animation.load_joint_animation((ANIMATIONS / 'prop_animation_007.nsbca').read_bytes())

        shut = points(nsbmd.load_model(data, pose=anim.pose_at(0, data)))
        open_ = points(nsbmd.load_model(data, pose=anim.pose_at(anim.num_frames - 1, data)))

        # A 90 degree turn about Y swaps the door's width (X) and thickness (Z).
        self.assertAlmostEqual(np.ptp(shut[:, 0]), np.ptp(open_[:, 2]), delta=0.05)
        self.assertAlmostEqual(np.ptp(shut[:, 2]), np.ptp(open_[:, 0]), delta=0.05)

    def test_windmill_blades_turn(self):
        data = (MODELS / 'prop_model_146.nsbmd').read_bytes()
        anim = animation.load_joint_animation((ANIMATIONS / 'prop_animation_025.nsbca').read_bytes())

        first = points(nsbmd.load_model(data, pose=anim.pose_at(0, data)))
        later = points(nsbmd.load_model(data, pose=anim.pose_at(anim.num_frames // 3, data)))

        self.assertEqual(first.shape, later.shape)
        self.assertGreater(np.abs(first - later).max(), 1)


class JointedMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = maps.MapRepository(R)
        cls.animations = map_render.Animations(R)

    def test_windmills_turn_on_the_map(self):
        first = map_render.render_map(self.repository, 'MAP_HEADER_VALLEY_WINDWORKS_OUTSIDE', view='angled', size=160,
                                      tick=0, animations=self.animations).image
        later = map_render.render_map(self.repository, 'MAP_HEADER_VALLEY_WINDWORKS_OUTSIDE', view='angled', size=160,
                                      tick=20, animations=self.animations).image

        self.assertTrue(np.any(first != later))

    def test_baked_playback_matches_direct_renders_with_moving_joints(self):
        baked = map_render.bake_map(self.repository, 'MAP_HEADER_VALLEY_WINDWORKS_OUTSIDE', view='angled', size=160,
                                    animations=self.animations)
        for tick in (0, 20):
            direct = map_render.render_map(self.repository, 'MAP_HEADER_VALLEY_WINDWORKS_OUTSIDE', view='angled', size=160,
                                           tick=tick, animations=self.animations).image
            mismatched = np.any(np.abs(baked.frame(tick).astype(int) - direct.astype(int)) > 2, axis=2).mean()
            with self.subTest(tick=tick):
                self.assertLess(mismatched, 0.003)
        self.assertTrue(baked.animated)


if __name__ == '__main__':
    unittest.main()
