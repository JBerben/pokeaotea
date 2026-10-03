#!/usr/bin/env python3
# ABOUTME: Tests for make_prop_tables.py, which builds the map prop animation lists and material/shape draw lists.
# ABOUTME: Run with `python3 -m unittest tools.scripts.test_make_prop_tables` from the repo root.

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import make_prop_tables as mpt  # noqa: E402

PROPS_DIR = REPO / 'res' / 'field' / 'props'
MODELS_DIR = PROPS_DIR / 'models'
MODELS_ORDER = MODELS_DIR / 'map_prop_models.order'
ANIMATIONS_ORDER = PROPS_DIR / 'animations' / 'prop_animations.order'
ANIMATION_LISTS_JSON = PROPS_DIR / 'animations' / 'prop_animation_lists.json'
DRAW_ORDER_JSON = MODELS_DIR / 'draw_order_overrides.json'
NITROARC = Path(os.environ.get('NITROARC', REPO / 'build' / 'tools' / 'nitroarc' / 'nitroarc'))

RET = 0x01
MAT = 0x04
SHP = 0x05


def read_narc_members(data: bytes) -> list[bytes]:
    assert data[0:4] == b'NARC'
    fat_offset = 0x10
    assert data[fat_offset:fat_offset + 4] == b'BTAF'
    fat_size, count = struct.unpack_from('<IH', data, fat_offset + 4)
    ranges = [struct.unpack_from('<II', data, fat_offset + 12 + 8 * i) for i in range(count)]
    fnt_offset = fat_offset + fat_size
    assert data[fnt_offset:fnt_offset + 4] == b'BTNF'
    img_offset = fnt_offset + struct.unpack_from('<I', data, fnt_offset + 4)[0]
    assert data[img_offset:img_offset + 4] == b'GMIF'
    base = img_offset + 8
    return [data[base + start:base + end] for start, end in ranges]


def model_info(materials, shapes, draws):
    return mpt.ModelDrawInfo(materials=list(materials), shapes=list(shapes), draws=list(draws))


class ReadDrawCommandsTest(unittest.TestCase):
    def test_pairs_each_shape_with_the_material_set_before_it(self):
        sbc = bytes([MAT, 2, SHP, 0, SHP, 1, MAT, 0, SHP, 2, RET])

        self.assertEqual(mpt.read_draw_commands(sbc), [(2, 0), (2, 1), (0, 2)])

    def test_material_variants_with_option_flags_still_set_the_material(self):
        sbc = bytes([0x24, 3, SHP, 0, 0x44, 1, SHP, 1, RET])

        self.assertEqual(mpt.read_draw_commands(sbc), [(3, 0), (1, 1)])

    def test_skips_other_commands_using_the_nitrosystem_lengths(self):
        sbc = bytes([
            0x00,                    # NOP
            0x02, 0, 1,              # NODE node, visible
            0x03, 0,                 # MTX
            0x06, 0, 0, 0,           # NODEDESC
            0x26, 1, 0, 0, 0,        # NODEDESC with store
            0x66, 2, 0, 0, 0, 0,     # NODEDESC with store and restore
            0x09, 0, 2, 0, 0, 128, 1, 1, 128,  # NODEMIX with two blends
            0x0B,                    # POSSCALE
            MAT, 0, SHP, 0,
            RET,
        ])

        self.assertEqual(mpt.read_draw_commands(sbc), [(0, 0)])

    def test_shape_before_any_material_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'before any material'):
            mpt.read_draw_commands(bytes([SHP, 0, RET]))

    def test_unknown_command_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r'unknown render command 0x0e'):
            mpt.read_draw_commands(bytes([MAT, 0, 0x0E, RET]))

    def test_missing_return_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'ends without'):
            mpt.read_draw_commands(bytes([MAT, 0, SHP, 0]))


class ReadModelDrawInfoTest(unittest.TestCase):
    def test_reads_retail_model_names_and_render_order(self):
        info = mpt.read_model_draw_info((MODELS_DIR / 'prop_model_005.nsbmd').read_bytes())

        self.assertEqual(info.materials, ['h_kage', 'lambert2', 'lambert4', 'light2'])
        self.assertEqual(info.shapes, ['polygon0', 'polygon1', 'polygon2', 'polygon3'])
        self.assertEqual(info.draws, [(0, 3), (3, 2), (2, 1), (1, 0)])

    def test_rejects_files_that_are_not_nsbmd(self):
        with self.assertRaisesRegex(ValueError, 'not an NSBMD'):
            mpt.read_model_draw_info(b'BTX0' + bytes(60))


class DefaultDrawOrderTest(unittest.TestCase):
    def test_sorts_by_material_keeping_render_order_within_a_material(self):
        draws = [(2, 0), (0, 3), (2, 1), (0, 2), (1, 4)]

        self.assertEqual(mpt.default_draw_order(draws), [(0, 3), (0, 2), (1, 4), (2, 0), (2, 1)])


class AnimationListEntryTest(unittest.TestCase):
    ANIMATION_IDS = {'a_nsbta': 0, 'b_nsbca': 1, 'c_nsbca': 2, 'd_nsbtp': 3}

    def test_model_without_animations_gets_the_retail_placeholder(self):
        self.assertEqual(mpt.encode_animation_list_entry(None, self.ANIMATION_IDS),
                         bytes([0xFF, 0xFF, 0, 0]) + b'\xff' * 16)

    def test_encodes_flags_and_pads_unused_slots_with_minus_one(self):
        entry = {'animations': ['b_nsbca', 'c_nsbca', 'd_nsbtp'], 'deferredAddToRenderObj': True}

        self.assertEqual(mpt.encode_animation_list_entry(entry, self.ANIMATION_IDS),
                         bytes([1, 0b10, 0, 0]) + struct.pack('<4i', 1, 2, 3, -1))

    def test_encodes_deferred_loading_and_bicycle_slope(self):
        entry = {'animations': ['a_nsbta'], 'deferredLoading': True, 'bicycleSlope': True}

        self.assertEqual(mpt.encode_animation_list_entry(entry, self.ANIMATION_IDS)[:4], bytes([1, 0b01, 1, 0]))

    def test_decode_inverts_encode(self):
        names = list(self.ANIMATION_IDS)
        for entry in [
            None,
            {'animations': ['a_nsbta']},
            {'animations': ['a_nsbta', 'b_nsbca', 'c_nsbca', 'd_nsbtp'], 'deferredLoading': True,
             'deferredAddToRenderObj': True, 'bicycleSlope': True},
        ]:
            encoded = mpt.encode_animation_list_entry(entry, self.ANIMATION_IDS)
            self.assertEqual(mpt.decode_animation_list_entry(encoded, names), entry)


class MaterialShapeTableTest(unittest.TestCase):
    def test_encodes_locators_then_pairs_with_empty_lists_pointing_nowhere(self):
        data = mpt.encode_material_shape_table([[(0, 1)], [], [(2, 3), (4, 5)]])

        self.assertEqual(data, struct.pack('<HH', 3, 3)
                         + struct.pack('<HHHHHH', 1, 0, 0, 0xFFFF, 2, 1)
                         + struct.pack('<HHHHHH', 0, 1, 2, 3, 4, 5))

    def test_decode_inverts_encode(self):
        draw_lists = [[(0, 1)], [], [(2, 3), (4, 5)], []]

        self.assertEqual(mpt.decode_material_shape_table(mpt.encode_material_shape_table(draw_lists)), draw_lists)


class BuildDrawListsTest(unittest.TestCase):
    INFOS = {
        'house_nsbmd': model_info(['door', 'roof', 'wall'], ['polygon0', 'polygon1', 'polygon2'],
                                  [(2, 0), (0, 1), (1, 2)]),
        'fall_nsbmd': model_info(['water'], ['polygon0'], [(0, 0)]),
    }
    MODELS = ['house_nsbmd', 'fall_nsbmd']

    def test_unanimated_models_draw_by_material(self):
        draw_lists = mpt.build_draw_lists(self.MODELS, self.INFOS, {}, {})

        self.assertEqual(draw_lists, [[(0, 1), (1, 2), (2, 0)], [(0, 0)]])

    def test_animated_models_have_an_empty_draw_list(self):
        draw_lists = mpt.build_draw_lists(self.MODELS, self.INFOS, {'fall_nsbmd': {'animations': ['x']}}, {})

        self.assertEqual(draw_lists[1], [])

    def test_override_sets_the_order_by_material_and_shape_name(self):
        overrides = {'house_nsbmd': [
            {'material': 'roof', 'shape': 'polygon2'},
            {'material': 'wall', 'shape': 'polygon0'},
            {'material': 'door', 'shape': 'polygon1'},
        ]}

        draw_lists = mpt.build_draw_lists(self.MODELS, self.INFOS, {}, overrides)

        self.assertEqual(draw_lists[0], [(1, 2), (2, 0), (0, 1)])


class ValidateTest(unittest.TestCase):
    MODELS = ['house_nsbmd', 'fall_nsbmd']
    ANIMATIONS = ['fall_flow_nsbta', 'fall_mist_nsbta']
    INFOS = BuildDrawListsTest.INFOS

    def errors(self, animation_lists=None, overrides=None, models=None, infos=None):
        return mpt.validate(
            models or self.MODELS,
            self.ANIMATIONS,
            infos or self.INFOS,
            animation_lists or {},
            overrides or {},
        )

    def test_valid_data_has_no_errors(self):
        self.assertEqual(self.errors({'fall_nsbmd': {'animations': ['fall_flow_nsbta']}}), [])

    def test_animated_model_must_exist(self):
        errors = self.errors({'waterfall_nsbmd': {'animations': ['fall_flow_nsbta']}})

        self.assertEqual(errors, ["animation list for 'waterfall_nsbmd': no such model in map_prop_models.order"])

    def test_animations_must_exist(self):
        errors = self.errors({'fall_nsbmd': {'animations': ['fall_foam_nsbta']}})

        self.assertEqual(errors, ["animation list for 'fall_nsbmd': no such animation 'fall_foam_nsbta' in prop_animations.order"])

    def test_must_have_one_to_four_animations(self):
        self.assertEqual(self.errors({'fall_nsbmd': {'animations': []}}),
                         ["animation list for 'fall_nsbmd': must have 1 to 4 animations, has 0"])
        self.assertEqual(self.errors({'fall_nsbmd': {'animations': ['fall_flow_nsbta'] * 5}}),
                         ["animation list for 'fall_nsbmd': must have 1 to 4 animations, has 5"])

    def test_unknown_fields_are_rejected(self):
        errors = self.errors({'fall_nsbmd': {'animations': ['fall_flow_nsbta'], 'bicycleslope': True}})

        self.assertEqual(errors, ["animation list for 'fall_nsbmd': unknown field 'bicycleslope'"])

    def test_flags_must_be_booleans(self):
        errors = self.errors({'fall_nsbmd': {'animations': ['fall_flow_nsbta'], 'deferredLoading': 1}})

        self.assertEqual(errors, ["animation list for 'fall_nsbmd': 'deferredLoading' must be true or false"])

    def test_overridden_model_must_exist(self):
        errors = self.errors(overrides={'shed_nsbmd': []})

        self.assertEqual(errors, ["draw order for 'shed_nsbmd': no such model in map_prop_models.order"])

    def test_animated_model_cannot_have_a_draw_order(self):
        errors = self.errors({'fall_nsbmd': {'animations': ['fall_flow_nsbta']}},
                             {'fall_nsbmd': [{'material': 'water', 'shape': 'polygon0'}]})

        self.assertEqual(errors, ["draw order for 'fall_nsbmd': animated models are drawn whole, so a draw order would be ignored"])

    def test_draw_order_must_list_exactly_the_models_draws(self):
        errors = self.errors(overrides={'house_nsbmd': [
            {'material': 'roof', 'shape': 'polygon2'},
            {'material': 'door', 'shape': 'polygon1'},
        ]})

        self.assertEqual(errors, ["draw order for 'house_nsbmd': must list each of the model's draws exactly once; "
                                  "missing wall/polygon0"])

    def test_draw_order_rejects_pairs_the_model_does_not_draw(self):
        errors = self.errors(overrides={'house_nsbmd': [
            {'material': 'roof', 'shape': 'polygon2'},
            {'material': 'wall', 'shape': 'polygon0'},
            {'material': 'door', 'shape': 'polygon1'},
            {'material': 'door', 'shape': 'polygon0'},
        ]})

        self.assertEqual(errors, ["draw order for 'house_nsbmd': must list each of the model's draws exactly once; "
                                  "extra door/polygon0"])

    def test_unreadable_models_are_reported(self):
        errors = self.errors(infos={'house_nsbmd': ValueError('not an NSBMD file'), 'fall_nsbmd': self.INFOS['fall_nsbmd']})

        self.assertEqual(errors, ["model 'house_nsbmd': not an NSBMD file"])

    def test_model_count_is_limited_by_the_area_loader(self):
        models = [f'm{i}_nsbmd' for i in range(mpt.MAX_MAP_PROP_MODEL_FILES + 1)]
        infos = {m: self.INFOS['fall_nsbmd'] for m in models}

        self.assertEqual(self.errors(models=models, infos=infos),
                         [f'{len(models)} models in map_prop_models.order, but the area loader '
                          f'(MAX_MAP_PROP_MODEL_FILES) only has room for {mpt.MAX_MAP_PROP_MODEL_FILES}'])


class CommittedDataTest(unittest.TestCase):
    def test_committed_data_is_valid(self):
        inputs = mpt.load_inputs(MODELS_ORDER, ANIMATIONS_ORDER, ANIMATION_LISTS_JSON, DRAW_ORDER_JSON,
                                 sorted(MODELS_DIR.glob('*.nsbmd')))

        self.assertEqual(mpt.validate(*inputs), [])


class BuildIntegrationTest(unittest.TestCase):
    def setUp(self):
        if not NITROARC.exists():
            self.skipTest(f'nitroarc not built at {NITROARC}; run `make` first or set NITROARC')
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, animation_lists=ANIMATION_LISTS_JSON, draw_order=DRAW_ORDER_JSON):
        return subprocess.run(
            [sys.executable, str(HERE / 'make_prop_tables.py'),
             '--nitroarc', str(NITROARC),
             '--staging', str(self.out / 'staging'),
             '--animation-lists-output', str(self.out / 'lists.narc'),
             '--material-shapes-output', str(self.out / 'matshp.bin'),
             '--models-order', str(MODELS_ORDER),
             '--animations-order', str(ANIMATIONS_ORDER),
             '--animation-lists', str(animation_lists),
             '--draw-order', str(draw_order),
             *map(str, sorted(MODELS_DIR.glob('*.nsbmd')))],
            capture_output=True, text=True,
        )

    def test_builds_one_entry_per_model_in_model_order(self):
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

        models = MODELS_ORDER.read_text().split()
        members = read_narc_members((self.out / 'lists.narc').read_bytes())
        draw_lists = mpt.decode_material_shape_table((self.out / 'matshp.bin').read_bytes())
        self.assertEqual(len(members), len(models))
        self.assertEqual(len(draw_lists), len(models))

        honey_tree = models.index('honey_tree.nsbmd')
        animations = ANIMATIONS_ORDER.read_text().split()
        self.assertEqual(
            mpt.decode_animation_list_entry(members[honey_tree], [mpt.archive_name(a) for a in animations]),
            {'animations': ['prop_animation_001_nsbca', 'prop_animation_002_nsbca', 'prop_animation_003_nsbca'],
             'deferredAddToRenderObj': True},
        )
        self.assertEqual(draw_lists[honey_tree], [])

        # The Twinleaf houses draw their door material last.
        self.assertEqual(draw_lists[models.index('prop_model_022.nsbmd')], [(1, 2), (2, 1), (3, 0), (0, 3)])

    def test_invalid_data_fails_with_every_error_on_stderr_and_no_output(self):
        bad = self.out / 'bad.json'
        bad.write_text(json.dumps({'nowhere_nsbmd': {'animations': ['nothing_nsbta']},
                                   'honey_tree_nsbmd': {'animations': []}}))

        result = self.run_tool(animation_lists=bad)

        self.assertEqual(result.returncode, 1)
        self.assertIn("'nowhere_nsbmd': no such model", result.stderr)
        self.assertIn("'honey_tree_nsbmd': must have 1 to 4 animations", result.stderr)
        self.assertFalse((self.out / 'lists.narc').exists())
        self.assertFalse((self.out / 'matshp.bin').exists())


if __name__ == '__main__':
    unittest.main()
