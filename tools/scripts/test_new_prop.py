#!/usr/bin/env python3
# ABOUTME: Tests for new_prop.py, which registers a custom map prop (model, animations, textures) in one step.
# ABOUTME: Each test works on a copy of the prop sources in a temp dir, using a retail waterfall as the "new" prop.

import json
import shutil
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
import new_prop as np  # noqa: E402
import nitro_textures as nt  # noqa: E402

PROPS = Path('res/field/props')
COPIED = [
    PROPS / 'models' / 'meson.build',
    PROPS / 'models' / 'map_prop_models.order',
    PROPS / 'models' / 'draw_order_overrides.json',
    PROPS / 'animations' / 'meson.build',
    PROPS / 'animations' / 'prop_animations.order',
    PROPS / 'animations' / 'prop_animation_lists.json',
    PROPS / 'model_sets' / 'prop_model_sets.order',
    PROPS / 'model_sets' / 'prop_model_set_000.json',
    PROPS / 'model_sets' / 'prop_model_set_001.json',
    PROPS / 'texture_sets' / 'prop_texture_sets.order',
    PROPS / 'texture_sets' / 'prop_texture_set_000.nsbtx',
    PROPS / 'texture_sets' / 'prop_texture_set_001.nsbtx',
]
WATERFALL_MODEL = REPO / PROPS / 'models' / 'prop_model_305.nsbmd'
WATERFALL_ANIMATION = REPO / PROPS / 'animations' / 'prop_animation_018.nsbta'
WATERFALL_TEXTURES = ['kemuri', 'taki', 'taki_top']


def without_textures(nsbmd: bytes) -> bytes:
    """The model block of an NSBMD on its own, as a converter writes it when textures go to a separate NSBTX."""
    mdl0 = struct.unpack_from('<I', nsbmd, 0x10)[0]
    block = nsbmd[mdl0:mdl0 + struct.unpack_from('<I', nsbmd, mdl0 + 4)[0]]
    header_size, block_offset = 0x10, 0x14
    return (nsbmd[0:8] + struct.pack('<IHH', block_offset + len(block), header_size, 1)
            + struct.pack('<I', block_offset) + block)


class PropTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'repo'
        for relative in COPIED:
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / relative, self.root / relative)
        shutil.copytree(REPO / 'res' / 'field' / 'area_data', self.root / 'res' / 'field' / 'area_data')

        self.inputs = Path(self.tmp.name) / 'inputs'
        self.inputs.mkdir()
        self.model = self.inputs / 'waterfall.nsbmd'
        shutil.copyfile(WATERFALL_MODEL, self.model)
        self.animation = self.inputs / 'waterfall.nsbta'
        shutil.copyfile(WATERFALL_ANIMATION, self.animation)

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, **overrides):
        fields = dict(name='waterfall', model=self.model, textures=None, animations=[self.animation],
                      deferred_loading=False, deferred_add_to_render_obj=False, bicycle_slope=False,
                      model_sets=['000'])
        fields.update(overrides)
        return np.PropRequest(**fields)

    def apply(self, **overrides):
        plan = np.build_plan(self.root, self.request(**overrides))
        plan.apply()
        return plan

    def errors(self, **overrides):
        with self.assertRaises(np.PropError) as raised:
            np.build_plan(self.root, self.request(**overrides))
        return raised.exception.errors

    def read(self, relative):
        return (self.root / relative).read_text(encoding='utf-8')

    def snapshot(self):
        return {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}


class RegisterModelTest(PropTestCase):
    def test_copies_the_model_and_appends_it_to_meson_and_the_order(self):
        self.apply()

        self.assertEqual((self.root / PROPS / 'models' / 'waterfall.nsbmd').read_bytes(), self.model.read_bytes())
        self.assertIn("    'waterfall.nsbmd',\n)", self.read(PROPS / 'models' / 'meson.build'))
        order = self.read(PROPS / 'models' / 'map_prop_models.order').splitlines()
        self.assertEqual(order[-1], 'waterfall.nsbmd')
        self.assertEqual(order[:-1], (REPO / PROPS / 'models' / 'map_prop_models.order').read_text().splitlines())

    def test_adds_the_model_to_each_chosen_model_set(self):
        self.apply(model_sets=['000', '1'])

        for set_id in ('000', '001'):
            models = json.loads(self.read(PROPS / 'model_sets' / f'prop_model_set_{set_id}.json'))['mapPropModels']
            self.assertEqual(models[-1], 'waterfall_nsbmd')

    def test_model_set_json_keeps_its_format(self):
        self.apply()

        text = self.read(PROPS / 'model_sets' / 'prop_model_set_000.json')
        self.assertEqual(json.dumps(json.loads(text), indent=4) + '\n', text)


class RegisterAnimationsTest(PropTestCase):
    def test_copies_each_animation_and_lists_it_for_the_model(self):
        self.apply()

        self.assertEqual((self.root / PROPS / 'animations' / 'waterfall_0.nsbta').read_bytes(), self.animation.read_bytes())
        self.assertIn("    'waterfall_0.nsbta',\n))", self.read(PROPS / 'animations' / 'meson.build'))
        self.assertEqual(self.read(PROPS / 'animations' / 'prop_animations.order').splitlines()[-1], 'waterfall_0.nsbta')

        text = self.read(PROPS / 'animations' / 'prop_animation_lists.json')
        lists = json.loads(text)
        self.assertEqual(lists['waterfall_nsbmd'], {'animations': ['waterfall_0_nsbta']})
        self.assertEqual(mpt.format_animation_lists(lists), text)

    def test_records_the_requested_flags(self):
        self.apply(deferred_loading=True, deferred_add_to_render_obj=True, bicycle_slope=True)

        entry = json.loads(self.read(PROPS / 'animations' / 'prop_animation_lists.json'))['waterfall_nsbmd']
        self.assertEqual(entry, {'animations': ['waterfall_0_nsbta'], 'deferredLoading': True,
                                 'deferredAddToRenderObj': True, 'bicycleSlope': True})

    def test_animation_extension_comes_from_the_file_magic(self):
        renamed = self.inputs / 'flow.bin'
        shutil.copyfile(self.animation, renamed)

        self.apply(animations=[renamed])

        self.assertTrue((self.root / PROPS / 'animations' / 'waterfall_0.nsbta').exists())

    def test_a_prop_without_animations_gets_no_list_entry(self):
        self.apply(animations=[])

        self.assertNotIn('waterfall_nsbmd', json.loads(self.read(PROPS / 'animations' / 'prop_animation_lists.json')))
        self.assertEqual(self.read(PROPS / 'animations' / 'prop_animations.order'),
                         (REPO / PROPS / 'animations' / 'prop_animations.order').read_text())


class MergeTexturesTest(PropTestCase):
    def texture_set(self, set_id):
        return nt.read_texture_set((self.root / PROPS / 'texture_sets' / f'prop_texture_set_{set_id}.nsbtx').read_bytes())

    def test_appends_the_models_textures_after_the_existing_ones(self):
        before = self.texture_set('000')

        self.apply()

        after = self.texture_set('000')
        self.assertEqual(after.textures()[:len(before.textures())], before.textures())
        self.assertEqual(after.palettes()[:len(before.palettes())], before.palettes())
        self.assertEqual(after.texture_data[:len(before.texture_data)], before.texture_data)
        textures, palettes = mpt.read_model_texture_references(self.model.read_bytes())
        self.assertTrue(set(textures) <= {t.name for t in after.textures()})
        self.assertTrue(set(palettes) <= {p.name for p in after.palettes()})

    def test_a_separate_texture_file_is_used_instead_of_the_embedded_textures(self):
        separate = self.inputs / 'waterfall.nsbtx'
        separate.write_bytes(nt.write_nsbtx(nt.read_texture_set(self.model.read_bytes())))

        self.apply(textures=separate)

        self.assertTrue(set(WATERFALL_TEXTURES) <= {t.name for t in self.texture_set('000').textures()})

    def test_textures_already_in_the_set_are_shared(self):
        self.apply()
        once = (self.root / PROPS / 'texture_sets' / 'prop_texture_set_000.nsbtx').read_bytes()

        self.apply(name='waterfall_copy')

        self.assertEqual((self.root / PROPS / 'texture_sets' / 'prop_texture_set_000.nsbtx').read_bytes(), once)


class ValidationTest(PropTestCase):
    def test_nothing_is_written_until_apply(self):
        before = self.snapshot()

        np.build_plan(self.root, self.request(model_sets=['000', '001']))

        self.assertEqual(self.snapshot(), before)

    def test_invalid_requests_write_nothing(self):
        before = self.snapshot()

        self.errors(model_sets=['999'])

        self.assertEqual(self.snapshot(), before)

    def test_name_must_be_lower_snake_case(self):
        self.assertEqual(self.errors(name='Waterfall'), ["name 'Waterfall' must be lower snake_case, e.g. route_201_waterfall"])

    def test_model_must_not_already_exist(self):
        self.assertIn("model 'honey_tree.nsbmd' already exists in map_prop_models.order", self.errors(name='honey_tree'))

    def test_model_must_be_an_nsbmd(self):
        self.model.write_bytes(b'BTX0' + bytes(60))

        self.assertIn('waterfall.nsbmd: not an NSBMD file: magic is ' + repr(b'BTX0') + ', expected BMD0',
                      self.errors())

    def test_model_set_must_exist(self):
        self.assertEqual(self.errors(model_sets=['999']), ["model set '999': no prop_model_set_999 in prop_model_sets.order"])

    def test_model_must_not_already_be_in_the_set(self):
        self.apply()
        model_set = self.root / PROPS / 'model_sets' / 'prop_model_set_001.json'
        data = json.loads(model_set.read_text())
        data['mapPropModels'].append('waterfall_two_nsbmd')
        model_set.write_text(json.dumps(data, indent=4) + '\n')

        self.assertIn("model set '001': already contains waterfall_two_nsbmd", self.errors(name='waterfall_two', model_sets=['001']))

    def test_at_least_one_model_set_is_required(self):
        self.assertEqual(self.errors(model_sets=[]), ['choose at least one model set (--model-set) so the prop can be placed'])

    def test_at_most_four_animations(self):
        self.assertEqual(self.errors(animations=[self.animation] * 5),
                         ['a prop has at most 4 animations, got 5'])

    def test_flags_need_animations(self):
        self.assertEqual(self.errors(animations=[], deferred_loading=True),
                         ['animation flags (--deferred-loading, --deferred-add-to-render-obj, --bicycle-slope) need at least one --animation'])

    def test_animation_must_be_a_nitro_animation(self):
        self.animation.write_bytes(b'BMD0' + bytes(60))

        self.assertEqual(self.errors(),
                         ["waterfall.nsbta: not a prop animation (magic b'BMD0'; expected one of BCA0, BMA0, BTA0, BTP0, BVA0)"])

    def test_model_without_textures_needs_a_texture_file(self):
        self.model.write_bytes(without_textures(WATERFALL_MODEL.read_bytes()))

        errors = self.errors(animations=[])

        self.assertEqual(len(errors), 1)
        self.assertRegex(errors[0], r"^waterfall\.nsbmd has no embedded textures; pass --textures with an NSBTX holding: ")

    def test_model_that_binds_no_textures_needs_none(self):
        shutil.copyfile(REPO / PROPS / 'models' / 'prop_model_028.nsbmd', self.model)
        before = (self.root / PROPS / 'texture_sets' / 'prop_texture_set_000.nsbtx').read_bytes()

        self.apply(animations=[])

        self.assertEqual((self.root / PROPS / 'texture_sets' / 'prop_texture_set_000.nsbtx').read_bytes(), before)

    def test_texture_file_must_hold_every_texture_the_model_binds(self):
        partial = self.inputs / 'partial.nsbtx'
        embedded = nt.read_texture_set(self.model.read_bytes())
        partial.write_bytes(nt.write_nsbtx(nt.build_texture_set(embedded.textures()[1:], embedded.palettes())))

        errors = self.errors(textures=partial)

        self.assertEqual(errors, [f'partial.nsbtx is missing texture {embedded.textures()[0].name!r}, which waterfall.nsbmd binds'])

    def test_a_texture_name_clash_in_a_set_is_reported_for_that_set(self):
        clash = self.inputs / 'clash.nsbtx'
        embedded = nt.read_texture_set(self.model.read_bytes())
        first = embedded.textures()[0]
        clash_textures = [first._replace(name='h_kage')] + embedded.textures()
        clash.write_bytes(nt.write_nsbtx(nt.build_texture_set(clash_textures, embedded.palettes())))

        errors = self.errors(textures=clash)

        self.assertEqual(errors, ["texture set 000: texture 'h_kage' already exists in the set with different data"])

    def test_every_problem_is_reported_at_once(self):
        errors = self.errors(name='honey_tree', model_sets=['999'], animations=[self.animation] * 5)

        self.assertEqual(len(errors), 3)


class BuildIntegrationTest(PropTestCase):
    def test_result_passes_the_prop_table_builder_validation(self):
        self.apply(model_sets=['000', '001'])

        models_dir = self.root / PROPS / 'models'
        model_paths = sorted((REPO / PROPS / 'models').glob('*.nsbmd')) + [models_dir / 'waterfall.nsbmd']
        inputs = mpt.load_inputs(models_dir / 'map_prop_models.order',
                                 self.root / PROPS / 'animations' / 'prop_animations.order',
                                 self.root / PROPS / 'animations' / 'prop_animation_lists.json',
                                 models_dir / 'draw_order_overrides.json',
                                 model_paths)

        self.assertEqual(mpt.validate(*inputs), [])

    def test_command_line_dry_run_prints_the_plan_and_writes_nothing(self):
        before = self.snapshot()

        result = self.run_cli('--dry-run')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn('create  res/field/props/models/waterfall.nsbmd', result.stdout)
        self.assertIn('edit    res/field/props/texture_sets/prop_texture_set_000.nsbtx', result.stdout)
        self.assertIn('Nothing written (--dry-run).', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_command_line_applies_the_plan(self):
        result = self.run_cli()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / PROPS / 'models' / 'waterfall.nsbmd').exists())

    def test_command_line_reports_errors_and_exits_1(self):
        result = self.run_cli('--model-set', '999')

        self.assertEqual(result.returncode, 1)
        self.assertIn("model set '999'", result.stderr)

    def run_cli(self, *extra):
        args = list(extra)
        if '--model-set' not in args:
            args += ['--model-set', '000']
        return subprocess.run(
            [sys.executable, str(HERE / 'new_prop.py'), 'waterfall',
             '--root', str(self.root),
             '--model', str(self.model),
             '--animation', str(self.animation),
             *args],
            capture_output=True, text=True,
        )


if __name__ == '__main__':
    unittest.main()
