#!/usr/bin/env python3
# ABOUTME: Tests for map_info.py's data layer (summarize) and its text formatting, which the CLI and mapedit share.
# ABOUTME: Run with `python3 -m unittest tools.scripts.test_map_info` from the repo root.

import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fieldscript as fs  # noqa: E402
import map_info  # noqa: E402


class SummarizeTest(unittest.TestCase):
    def setUp(self):
        self.summary = map_info.summarize('twinleaf_town')

    def test_names_the_header_and_its_resources(self):
        self.assertEqual(self.summary.header, 'MAP_HEADER_TWINLEAF_TOWN')
        self.assertEqual(self.summary.stem, 'scripts_twinleaf_town')
        self.assertEqual(self.summary.fields['eventsArchiveID'], 'events_twinleaf_town')

    def test_lists_every_entry_with_what_references_it(self):
        script = fs.parse_script(fs.script_path('scripts_twinleaf_town'))

        self.assertEqual([entry.label for entry in self.summary.entries], list(script.entries))
        self.assertIn('LOCALID_POKEMON_BREEDER_F', self.summary.entries[5].references)
        self.assertEqual(self.summary.next_free_index, len(script.entries) + 1)

    def test_counts_events(self):
        self.assertEqual(self.summary.event_counts, {'object_events': 9, 'coord_events': 2, 'bg_events': 1, 'warp_events': 4})

    def test_lists_flags_and_variables_used(self):
        self.assertIn('VAR_TWINLEAF_TOWN_GUITARIST_TRIGGER_STATE', self.summary.variables)

    def test_accepts_the_scripts_prefix(self):
        self.assertEqual(map_info.summarize('scripts_twinleaf_town').header, 'MAP_HEADER_TWINLEAF_TOWN')

    def test_unknown_map_is_an_error(self):
        with self.assertRaises(map_info.MapInfoError) as raised:
            map_info.summarize('nowhere_town')

        self.assertEqual(str(raised.exception), 'no scripts_nowhere_town.s in res/field/scripts')

    def test_header_for_finds_the_scripts_a_header_uses(self):
        self.assertEqual(map_info.script_stem_for_header('MAP_HEADER_TWINLEAF_TOWN'), 'scripts_twinleaf_town')
        self.assertIsNone(map_info.script_stem_for_header('MAP_HEADER_NOWHERE'))


class FormatTest(unittest.TestCase):
    def test_command_line_prints_the_formatted_summary(self):
        result = subprocess.run([sys.executable, str(HERE / 'map_info.py'), 'twinleaf_town', '--state'],
                                capture_output=True, text=True)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, map_info.format_summary(map_info.summarize('twinleaf_town'), state=True) + '\n')

    def test_state_section_is_optional(self):
        text = map_info.format_summary(map_info.summarize('twinleaf_town'), state=False)

        self.assertNotIn('flags used', text)


if __name__ == '__main__':
    unittest.main()
