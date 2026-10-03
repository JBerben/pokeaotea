#!/usr/bin/env python3
# ABOUTME: Tests for new_map.py's plan builder, run against a temp copy of the files it reads and writes.
# ABOUTME: Run with `python3 -m unittest tools.scripts.test_new_map` from the repo root.

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import new_map  # noqa: E402

FILES = [
    'res/field/scripts/meson.build',
    'res/field/scripts/scripts.order',
    'res/field/scripts/scripts_twinleaf_town.s',
    'res/field/events/meson.build',
    'res/field/events/zone_event.order',
    'res/field/events/events_twinleaf_town.json',
    'generated/text_banks.txt',
    'generated/map_headers.txt',
    'include/data/map_headers.h',
]


class NewMapTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for relative in FILES:
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / relative, self.root / relative)
        shutil.copytree(REPO / 'res/text', self.root / 'res/text')

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, relative):
        with open(self.root / relative, encoding='utf-8', newline='') as handle:
            return handle.read()


class BuildPlanTest(NewMapTestCase):
    def test_plans_every_file_without_writing(self):
        plan = new_map.build_plan('my_new_town', 'my new town', False, new_map.DEFAULT_TEMPLATE, root=self.root)

        self.assertIn('  create  res/field/scripts/scripts_my_new_town.s', plan.lines())
        self.assertIn('  edit    res/field/events/zone_event.order  (+1 entry (CRLF))', plan.lines())
        self.assertFalse((self.root / 'res/field/scripts/scripts_my_new_town.s').exists())

    def test_apply_writes_and_wires_the_map(self):
        new_map.build_plan('my_new_town', 'my new town', False, new_map.DEFAULT_TEMPLATE, root=self.root).apply()

        self.assertTrue((self.root / 'res/field/scripts/scripts_init_my_new_town.s').exists())
        self.assertTrue(self.read('res/field/events/zone_event.order').endswith('events_my_new_town\r\n'))
        self.assertIn('TEXT_BANK_MY_NEW_TOWN', self.read('generated/text_banks.txt'))

    def test_header_copies_the_templates_geometry(self):
        new_map.build_plan('my_new_town', 'my new town', True, 'MAP_HEADER_TWINLEAF_TOWN', root=self.root).apply()

        headers = self.read('include/data/map_headers.h')
        self.assertIn('[MAP_HEADER_MY_NEW_TOWN] = {', headers)
        block = headers[headers.index('[MAP_HEADER_MY_NEW_TOWN]'):]
        self.assertIn('.mapMatrixID = map_matrix_000', block)
        self.assertIn('.scriptsArchiveID = scripts_my_new_town,', block)
        self.assertIn('MAP_HEADER_MY_NEW_TOWN\nMAP_HEADER_COUNT', self.read('generated/map_headers.txt'))

    def test_existing_files_are_an_error(self):
        with self.assertRaises(new_map.NewMapError) as raised:
            new_map.build_plan('twinleaf_town', 'twinleaf', False, new_map.DEFAULT_TEMPLATE, root=self.root)

        self.assertIn('these already exist, refusing to overwrite', str(raised.exception))
        self.assertIn('res/field/scripts/scripts_twinleaf_town.s', str(raised.exception))

    def test_unknown_template_is_an_error(self):
        with self.assertRaises(new_map.NewMapError) as raised:
            new_map.build_plan('my_new_town', 'x', True, 'MAP_HEADER_NOPE', root=self.root)

        self.assertEqual(str(raised.exception), 'no template header MAP_HEADER_NOPE')

    def test_invalid_names_are_an_error(self):
        with self.assertRaises(new_map.NewMapError) as raised:
            new_map.build_plan('My Town', 'x', False, new_map.DEFAULT_TEMPLATE, root=self.root)

        self.assertEqual(str(raised.exception), 'name must be lower snake_case')


class CommandLineTest(NewMapTestCase):
    def test_dry_run_on_the_real_repo_writes_nothing(self):
        result = subprocess.run([sys.executable, str(HERE / 'new_map.py'), 'my_new_town', '--dry-run'],
                                capture_output=True, text=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Nothing written (--dry-run).', result.stdout)
        self.assertFalse((REPO / 'res/field/scripts/scripts_my_new_town.s').exists())

    def test_errors_go_to_stderr_with_exit_1(self):
        result = subprocess.run([sys.executable, str(HERE / 'new_map.py'), 'twinleaf_town', '--dry-run'],
                                capture_output=True, text=True)

        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.startswith('error: these already exist'))


if __name__ == '__main__':
    unittest.main()
