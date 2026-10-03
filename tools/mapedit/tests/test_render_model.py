# ABOUTME: Tests for mapedit.render.model, the NSBMD geometry decoder (render commands, node matrices, display lists).
# ABOUTME: The oracle is each retail model's own header: decoded triangle/quad counts and bounds must match it.

import struct
import unittest

import numpy as np

from mapedit import maps
from mapedit.render import model as nsbmd

MODELS = maps.REPO / 'res/field/props/models'
LAND_DATA = maps.REPO / 'res/field/maps/data'


# Models whose header bounding box does not match their geometry. None is ever placed in land data:
# door01 is only spawned at runtime (its animations are hinge rotations, which do not account for its box
# offset either); the others are unused, and their boxes are offset along Z by their own depth (a converter
# quirk). Their triangle and quad counts still match their headers.
BOX_EXCEPTIONS = {'door01.nsbmd', 'prop_model_001.nsbmd', 'prop_model_002.nsbmd', 'prop_model_006.nsbmd',
                  'prop_model_018.nsbmd', 'prop_model_019.nsbmd', 'prop_model_021.nsbmd'}


def map_model(number: int) -> bytes:
    return maps.map_props.read_land_data((LAND_DATA / f'map_data_{number:03}.bin').read_bytes()).model


def gx_list(*commands) -> bytes:
    """Packs (opcode, [params]) into a GX display list: four opcodes per word, then their parameters."""
    out = b''
    for start in range(0, len(commands), 4):
        group = commands[start:start + 4]
        opcodes = [op for op, _ in group] + [0] * (4 - len(group))
        out += bytes(opcodes)
        for _, params in group:
            out += b''.join(struct.pack('<I', p & 0xFFFFFFFF) for p in params)
    return out


def vtx16(x, y, z):
    fx = [round(v * 4096) & 0xFFFF for v in (x, y, z)]
    return (0x23, [fx[0] | (fx[1] << 16), fx[2]])


class DisplayListTest(unittest.TestCase):
    def test_separate_triangles(self):
        dl = gx_list((0x40, [0]), vtx16(0, 0, 0), vtx16(1, 0, 0), vtx16(0, 1, 0), (0x41, []))

        primitives = nsbmd.decode_display_list(dl, np.eye(4), {})

        self.assertEqual(len(primitives), 1)
        self.assertEqual(primitives[0].kind, nsbmd.TRIANGLES)
        np.testing.assert_allclose(primitives[0].positions, [[0, 0, 0], [1, 0, 0], [0, 1, 0]])

    def test_strips_triangulate_with_alternating_winding(self):
        dl = gx_list((0x40, [2]), vtx16(0, 0, 0), vtx16(1, 0, 0), vtx16(0, 1, 0), vtx16(1, 1, 0), (0x41, []))

        triangles = nsbmd.decode_display_list(dl, np.eye(4), {})[0].triangles()

        self.assertEqual(triangles, [(0, 1, 2), (2, 1, 3)])

    def test_quads_and_quad_strips_split_into_two_triangles_each(self):
        quad = gx_list((0x40, [1]), *[vtx16(*v) for v in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))], (0x41, []))
        strip = gx_list((0x40, [3]), *[vtx16(*v) for v in ((0, 0, 0), (0, 1, 0), (1, 0, 0), (1, 1, 0), (2, 0, 0), (2, 1, 0))], (0x41, []))

        self.assertEqual(nsbmd.decode_display_list(quad, np.eye(4), {})[0].triangles(), [(0, 1, 2), (0, 2, 3)])
        self.assertEqual(len(nsbmd.decode_display_list(strip, np.eye(4), {})[0].triangles()), 4)

    def test_compact_vertex_commands_reuse_the_previous_vertex(self):
        dl = gx_list((0x40, [0]), vtx16(1, 2, 3),
                     (0x25, [(round(4 * 4096) & 0xFFFF) | ((round(5 * 4096) & 0xFFFF) << 16)]),   # VTX_XY
                     (0x28, [8 | (0 << 10) | ((-8 & 0x3FF) << 20)]),                               # VTX_DIFF
                     (0x41, []))

        positions = nsbmd.decode_display_list(dl, np.eye(4), {})[0].positions

        np.testing.assert_allclose(positions, [[1, 2, 3], [4, 5, 3], [4 + 8 / 4096, 5, 3 - 8 / 4096]])

    def test_texcoords_and_colours_attach_to_following_vertices(self):
        dl = gx_list((0x40, [0]), (0x22, [(16 * 3) | ((16 * 5) << 16)]), (0x20, [0x7C00]), vtx16(0, 0, 0),
                     vtx16(1, 0, 0), vtx16(0, 1, 0), (0x41, []))

        primitive = nsbmd.decode_display_list(dl, np.eye(4), {})[0]

        np.testing.assert_allclose(primitive.uvs[0], [3, 5])
        np.testing.assert_allclose(primitive.colours[2], [0, 0, 1])

    def test_vertices_are_transformed_by_the_current_matrix(self):
        matrix = np.eye(4)
        matrix[3, :3] = [10, 0, 0]

        positions = nsbmd.decode_display_list(gx_list((0x40, [0]), vtx16(1, 0, 0), vtx16(0, 0, 0), vtx16(0, 1, 0), (0x41, [])),
                                              matrix, {})[0].positions

        np.testing.assert_allclose(positions[0], [11, 0, 0])

    def test_unknown_commands_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unknown display list command 0x99'):
            nsbmd.decode_display_list(bytes([0x99, 0, 0, 0]), np.eye(4), {})


class RetailModelTest(unittest.TestCase):
    def check(self, data: bytes, label: str, check_box: bool = True):
        model = nsbmd.load_model(data)
        triangles = sum(p.count_triangles() for draw in model.draws for p in draw.primitives)
        quads = sum(p.count_quads() for draw in model.draws for p in draw.primitives)
        with self.subTest(model=label):
            self.assertEqual((triangles, quads), (model.info.num_triangles, model.info.num_quads))
            if model.draws and check_box:
                points = np.concatenate([p.positions for draw in model.draws for p in draw.primitives])
                low, high = model.info.box
                slack = 1 / 64 + 1e-3 * np.abs(high - low).max()
                self.assertTrue(np.all(points >= low - slack) and np.all(points <= high + slack),
                                (points.min(axis=0), points.max(axis=0), low, high))

    def test_every_prop_model_matches_its_header(self):
        for path in sorted(MODELS.glob('*.nsbmd')):
            self.check(path.read_bytes(), path.name, check_box=path.name not in BOX_EXCEPTIONS)

    def test_map_models_match_their_headers(self):
        for number in (0, 177, 180, 190, 338, 506):
            self.check(map_model(number), f'map_data_{number:03}')

    def test_placed_buildings_stand_on_their_collision(self):
        # Twinleaf's houses: their decoded footprints overlap the blocked tiles under them more than the same
        # footprint shifted by its depth would - the error an axis or offset bug produces. (Eaves and shadows
        # overhang the collision, so the overlap itself is not 100%.)
        land = maps.map_props.read_land_data((LAND_DATA / 'map_data_000.bin').read_bytes())
        order = (MODELS / 'map_prop_models.order').read_text().split()
        blocked = (np.frombuffer(land.terrain, dtype='<u2').reshape(32, 32) >> 15) & 1
        houses = [p for p in land.props if order[p.model_id] in ('prop_model_022.nsbmd', 'prop_model_023.nsbmd', 'prop_model_236.nsbmd')]
        self.assertEqual(len(houses), 4)
        for prop in houses:
            model = nsbmd.load_model((MODELS / order[prop.model_id]).read_bytes())
            points = np.concatenate([p.positions for draw in model.draws for p in draw.primitives]) / 16
            centre = np.array(prop.position) / 65536 + 16
            x0, x1 = (int(v) for v in np.floor(centre[0] + [points[:, 0].min(), points[:, 0].max()]))
            depth = points[:, 2].max() - points[:, 2].min()

            def overlap(shift):
                z0, z1 = (int(v) for v in np.floor(centre[2] + shift + [points[:, 2].min(), points[:, 2].max()]))
                return blocked[max(z0, 0):max(z1 + 1, 0), x0:x1 + 1].mean()

            with self.subTest(model=order[prop.model_id], at=(x0, centre[2])):
                self.assertGreater(overlap(0), 0.5)
                self.assertGreater(overlap(0), overlap(depth))
                self.assertGreater(overlap(0), overlap(-depth))

    def test_materials_name_their_texture_and_palette(self):
        model = nsbmd.load_model((MODELS / 'prop_model_305.nsbmd').read_bytes())

        textures = {material.texture for material in model.materials}
        self.assertEqual(textures, {'kemuri', 'taki', 'taki_top'})
        self.assertTrue(all(material.palette for material in model.materials))
