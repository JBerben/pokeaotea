#!/usr/bin/env python3
# ABOUTME: Tests for map_matrices.py, the library and CLI for viewing and editing map matrices and adding land data.
# ABOUTME: Read-only tests use the repo; edits run on a temp copy of the matrix and land data sources.

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import map_matrices as mm  # noqa: E402

FILES = [
    'include/data/map_headers.h',
    'generated/maps.txt',
    'generated/map_headers.txt',
    'res/field/maps/data/meson.build',
    'res/field/maps/data/map_data.order',
]
LAND_DATA = ['000', '177', '180', '190'] + [str(n) for n in range(338, 347)]


class FormatTest(unittest.TestCase):
    def test_every_retail_matrix_writes_back_unchanged(self):
        for path in sorted((REPO / mm.MATRICES).glob('*.json')):
            with self.subTest(path=path.name):
                self.assertEqual(mm.format_matrix(mm.read_matrix(REPO, path.stem)), path.read_text(encoding='utf-8'))


class ReadTest(unittest.TestCase):
    def test_describes_a_single_header_matrix(self):
        info = mm.describe_matrix(REPO, 'map_matrix_007')

        self.assertEqual((info['width'], info['height']), (3, 3))
        self.assertTrue(info['single_header'])
        self.assertEqual(info['owners'], ['MAP_HEADER_ETERNA_FOREST'])
        self.assertEqual(info['cells'][0], {'row': 0, 'col': 0, 'header': None, 'land': 'MAP_338', 'altitude': None})

    def test_describes_the_overworld_with_per_cell_headers(self):
        info = mm.describe_matrix(REPO, 'map_matrix_000')

        self.assertFalse(info['single_header'])
        twinleaf = next(c for c in info['cells'] if c['header'] == 'MAP_HEADER_TWINLEAF_TOWN')
        self.assertEqual((twinleaf['row'], twinleaf['col'], twinleaf['land']), (27, 3, 'MAP_000'))

    def test_resolves_a_header_to_its_matrix(self):
        self.assertEqual(mm.resolve_matrix(REPO, 'MAP_HEADER_ETERNA_FOREST'), 'map_matrix_007')
        self.assertEqual(mm.resolve_matrix(REPO, 'map_matrix_007'), 'map_matrix_007')

    def test_land_users_lists_every_cell_that_uses_a_land_data_file(self):
        users = mm.land_users(REPO, 'MAP_190')

        self.assertEqual(users, [('map_matrix_122', 0, 0)])
        self.assertGreater(len(mm.land_users(REPO, 'MAP_177')), 10)


class EditTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for relative in FILES:
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / relative, self.root / relative)
        shutil.copytree(REPO / mm.MATRICES, self.root / mm.MATRICES)
        for number in LAND_DATA:
            name = f'map_data_{int(number):03}.bin'
            shutil.copyfile(REPO / mm.LAND_DATA / name, self.root / mm.LAND_DATA / name)

    def tearDown(self):
        self.tmp.cleanup()

    def matrix(self, matrix_id):
        return json.loads((self.root / mm.MATRICES / f'{matrix_id}.json').read_text())

    def errors(self, function, *args, **kwargs):
        with self.assertRaises(mm.MatrixError) as raised:
            function(*args, **kwargs)
        return raised.exception.errors


class SetCellsTest(EditTestCase):
    def test_sets_header_land_and_altitude_on_the_overworld(self):
        change = mm.set_cells(self.root, 'map_matrix_000', [(27, 3)], header='MAP_HEADER_ROUTE_201', land='MAP_177', altitude=3)
        self.assertEqual(self.matrix('map_matrix_000')['headers'][27][3], 'MAP_HEADER_TWINLEAF_TOWN')

        change.apply()

        matrix = self.matrix('map_matrix_000')
        self.assertEqual(matrix['headers'][27][3], 'MAP_HEADER_ROUTE_201')
        self.assertEqual(matrix['maps'][27][3], 'MAP_177')
        self.assertEqual(matrix['altitudes'][27][3], 3)

    def test_only_the_named_cells_change(self):
        before = self.matrix('map_matrix_000')

        mm.set_cells(self.root, 'map_matrix_000', [(0, 0), (0, 1)], altitude=7).apply()

        after = self.matrix('map_matrix_000')
        self.assertEqual(after['altitudes'][0][:2], [7, 7])
        after['altitudes'][0][:2] = before['altitudes'][0][:2]
        self.assertEqual(after, before)

    def test_sharing_land_data_is_a_warning(self):
        change = mm.set_cells(self.root, 'map_matrix_000', [(27, 3)], land='MAP_177')

        self.assertTrue(any('MAP_177 is also used by' in warning for warning in change.warnings), change.warnings)

    def test_altitudes_are_created_when_a_matrix_has_none(self):
        mm.set_cells(self.root, 'map_matrix_007', [(1, 1)], altitude=2).apply()

        self.assertEqual(self.matrix('map_matrix_007')['altitudes'], [[0, 0, 0], [0, 2, 0], [0, 0, 0]])

    def test_a_single_header_matrix_has_no_cell_headers(self):
        errors = self.errors(mm.set_cells, self.root, 'map_matrix_007', [(0, 0)], header='MAP_HEADER_ROUTE_201')

        self.assertEqual(errors, ['map_matrix_007 is a single-header matrix (every cell belongs to MAP_HEADER_ETERNA_FOREST); '
                                  'it has no per-cell headers to set'])

    def test_values_are_checked(self):
        errors = self.errors(mm.set_cells, self.root, 'map_matrix_000', [(30, 0)], header='MAP_HEADER_NOWHERE',
                             land='MAP_999', altitude=300)

        self.assertEqual(errors, [
            'cell (30, 0) is outside map_matrix_000 (30 rows x 30 columns)',
            'no MAP_HEADER_NOWHERE in generated/map_headers.txt',
            'no land data MAP_999 in generated/maps.txt',
            'altitude 300 is outside 0-255',
        ])

    def test_nothing_to_set_is_an_error(self):
        self.assertEqual(self.errors(mm.set_cells, self.root, 'map_matrix_000', [(0, 0)]),
                         ['nothing to set: give a header, land data or altitude'])

    def test_unknown_matrix_is_an_error(self):
        self.assertEqual(self.errors(mm.set_cells, self.root, 'map_matrix_999', [(0, 0)], altitude=1),
                         ['no matrix map_matrix_999 in res/field/matrices'])


class AddLandDataTest(EditTestCase):
    def test_unshare_copies_the_cells_land_data_to_a_new_file(self):
        change = mm.unshare_cell(self.root, 'map_matrix_122', 0, 0)
        change.apply()

        self.assertEqual(self.matrix('map_matrix_122')['maps'][0][0], 'MAP_666')
        self.assertEqual((self.root / mm.LAND_DATA / 'map_data_666.bin').read_bytes(),
                         (REPO / mm.LAND_DATA / 'map_data_190.bin').read_bytes())
        self.assertEqual((self.root / mm.LAND_DATA / 'map_data.order').read_text().splitlines()[-1], 'map_data_666.bin')
        maps = (self.root / 'generated/maps.txt').read_text().splitlines()
        self.assertEqual(maps[-2:], ['MAP_666', 'MAP_NONE = 65535'])
        meson = (self.root / mm.LAND_DATA / 'meson.build').read_text()
        self.assertIn("    'map_data_665.bin',\n    'map_data_666.bin',\n))", meson)

    def test_two_new_land_data_files_in_one_plan_get_consecutive_ids(self):
        workspace = mm.Workspace(self.root)
        first = mm.add_land_data(workspace, 'MAP_338')
        second = mm.add_land_data(workspace, 'MAP_339')

        self.assertEqual((first, second), ('MAP_666', 'MAP_667'))

    def test_unshare_needs_land_data(self):
        self.assertEqual(self.errors(mm.unshare_cell, self.root, 'map_matrix_000', 0, 0),
                         ['cell (0, 0) of map_matrix_000 has no land data (MAP_NONE) to copy'])


class MatrixFromTemplateTest(EditTestCase):
    def test_copies_a_single_header_template_and_its_blocks(self):
        workspace = mm.Workspace(self.root)

        matrix_id = mm.matrix_from_template(workspace, 'MAP_HEADER_ETERNA_FOREST')
        workspace.apply()

        self.assertEqual(matrix_id, 'map_matrix_289')
        matrix = self.matrix('map_matrix_289')
        self.assertEqual(matrix['headers'], [])
        self.assertEqual(matrix['maps'], [[f'MAP_{n}' for n in range(666 + r * 3, 669 + r * 3)] for r in range(3)])
        self.assertEqual(matrix['name'], 'm_dun0301_')
        self.assertIn('map_matrix_289', (self.root / mm.MATRICES / 'map_matrices.order').read_text().split())
        self.assertIn("    'map_matrix_288.json',\n    'map_matrix_289.json',\n)", (self.root / mm.MATRICES / 'meson.build').read_text())

    def test_crops_an_overworld_template_to_the_headers_own_cells(self):
        workspace = mm.Workspace(self.root)

        matrix_id = mm.matrix_from_template(workspace, 'MAP_HEADER_TWINLEAF_TOWN')
        workspace.apply()

        matrix = self.matrix(matrix_id)
        self.assertEqual(matrix['maps'], [['MAP_666']])
        self.assertEqual(matrix['altitudes'], [[0]])
        self.assertEqual((self.root / mm.LAND_DATA / 'map_data_666.bin').read_bytes(),
                         (REPO / mm.LAND_DATA / 'map_data_000.bin').read_bytes())

    def test_matrix_ids_that_wrap_to_the_overworld_are_refused(self):
        order = self.root / mm.MATRICES / 'map_matrices.order'
        order.write_text(''.join(f'map_matrix_{n:03}\n' for n in range(512)))

        errors = self.errors(mm.matrix_from_template, mm.Workspace(self.root), 'MAP_HEADER_ETERNA_FOREST')

        self.assertEqual(errors, ['the next matrix would be number 512, which the game stores in a u8 as 0 - '
                                  'the overworld (see MapMatrix_RevealSpringPath); add a placeholder matrix first'])


class CommandLineTest(EditTestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(HERE / 'map_matrices.py'), '--root', str(self.root), *args],
                              capture_output=True, text=True)

    def test_show_json(self):
        result = self.run_cli('show', 'MAP_HEADER_ETERNA_FOREST', '--json')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['id'], 'map_matrix_007')

    def test_show_text_draws_the_grid(self):
        result = self.run_cli('show', 'map_matrix_007')

        self.assertRegex(result.stdout, r'\n   0 +338 +339 +340')
        self.assertIn('owned by MAP_HEADER_ETERNA_FOREST', result.stdout)

    def test_set_dry_run_json_reports_the_plan_and_writes_nothing(self):
        before = self.matrix('map_matrix_000')

        result = self.run_cli('set', 'map_matrix_000', '--cell', '27,3', '--altitude', '4', '--dry-run', '--json')

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report['applied'])
        self.assertEqual(report['files'], [{'path': 'res/field/matrices/map_matrix_000.json', 'action': 'edit'}])
        self.assertEqual(self.matrix('map_matrix_000'), before)

    def test_set_rect_applies(self):
        result = self.run_cli('set', 'map_matrix_000', '--rect', '0,0:1,1', '--altitude', '9')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([row[:2] for row in self.matrix('map_matrix_000')['altitudes'][:2]], [[9, 9], [9, 9]])

    def test_errors_json(self):
        result = self.run_cli('set', 'map_matrix_000', '--cell', '0,0', '--land', 'MAP_999', '--json')

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout), {'errors': ['no land data MAP_999 in generated/maps.txt']})

    def test_users(self):
        result = self.run_cli('users', 'MAP_190', '--json')

        self.assertEqual(json.loads(result.stdout), [{'matrix': 'map_matrix_122', 'row': 0, 'col': 0}])


if __name__ == '__main__':
    unittest.main()
