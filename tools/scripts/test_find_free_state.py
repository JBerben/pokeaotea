#!/usr/bin/env python3
# ABOUTME: Tests for find_free_state.py's data layer (free_summary, reserved_ranges, check_name), shared with mapedit.
# ABOUTME: Run with `python3 -m unittest tools.scripts.test_find_free_state` from the repo root.

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import find_free_state as ffs  # noqa: E402


class FreeStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = ffs.scan()

    def test_summary_covers_flags_and_variables(self):
        summary = ffs.free_summary(self.state)

        self.assertEqual([s.kind for s in summary], ['flag', 'var'])
        flags = summary[0]
        self.assertEqual(flags.defined, flags.reserved + flags.general)
        self.assertTrue(flags.free)
        self.assertTrue(all(entry.reserved_reason is None for entry in flags.free))
        self.assertTrue(all(entry.name not in self.state.used for entry in flags.free))

    def test_free_names_prefer_ones_marked_unused(self):
        free = ffs.free_summary(self.state)[0].free

        self.assertIn('UNUSED', free[0].name)

    def test_reserved_ranges_explain_themselves(self):
        ranges = ffs.reserved_ranges(self.state)

        trainer = next(r for r in ranges if 'trainer id' in r.reason)
        self.assertGreater(trainer.count, 100)

    def test_check_name_reports_free_reserved_used_and_unknown(self):
        free = ffs.free_summary(self.state)[0].free[0].name
        reserved = next(e.name for e in self.state.entries if e.reserved_reason)
        used = next(e.name for e in self.state.entries if not e.reserved_reason and e.name in self.state.used)

        self.assertEqual(ffs.check_name(self.state, free).status, ffs.FREE)
        self.assertEqual(ffs.check_name(self.state, reserved).status, ffs.RESERVED_NAME)
        self.assertEqual(ffs.check_name(self.state, used).status, ffs.IN_USE)
        unknown = ffs.check_name(self.state, 'FLAG_NOPE')
        self.assertEqual(unknown.status, ffs.UNKNOWN)
        self.assertEqual(unknown.message, 'FLAG_NOPE is not in generated/vars_flags.txt')


if __name__ == '__main__':
    unittest.main()
