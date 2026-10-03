#!/usr/bin/env python3
# ABOUTME: Tests for check_warps.py's data layer (check_warps), which the CLI and mapedit share.
# ABOUTME: Run with `python3 -m unittest tools.scripts.test_check_warps` from the repo root.

import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import check_warps  # noqa: E402


class CheckWarpsTest(unittest.TestCase):
    def test_checks_only_the_named_maps(self):
        report = check_warps.check_warps(['twinleaf_town'])

        self.assertEqual(report.total, 4)
        self.assertEqual(report.findings, [])

    def test_accepts_events_prefixed_names(self):
        self.assertEqual(check_warps.check_warps(['events_twinleaf_town']).total, 4)

    def test_one_way_warps_are_only_listed_when_asked(self):
        quiet = check_warps.check_warps(one_way=False)
        loud = check_warps.check_warps(one_way=True)

        self.assertEqual(quiet.one_way, [])
        self.assertTrue(loud.one_way)
        self.assertEqual(quiet.total, loud.total)

    def test_command_line_reports_the_same_findings(self):
        report = check_warps.check_warps(one_way=True)

        result = subprocess.run([sys.executable, str(HERE / 'check_warps.py'), '--one-way'], capture_output=True, text=True)

        self.assertEqual(result.returncode, 1 if report.findings else 0)
        self.assertEqual(result.stderr, f'\n{report.total} warp(s) checked, {len(report.findings)} finding(s)\n')
        for line in report.findings + report.one_way:
            self.assertIn(line, result.stdout)


if __name__ == '__main__':
    unittest.main()
