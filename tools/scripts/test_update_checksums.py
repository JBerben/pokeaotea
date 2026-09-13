#!/usr/bin/env python3
# ABOUTME: Tests for update_checksums.py, the SHA-1 manifest blessing tool.
# ABOUTME: Run with `python3 -m unittest tools/scripts/test_update_checksums.py`.

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import update_checksums as uc  # noqa: E402

LSF = """\
Static main
{
\tAddress 0x02000000
\tObject main.nef.p/src_main.c.o
}

Overlay dummy1
{
\tAfter main
}

Overlay nintendo_wfc
{
\tAfter main
\tLibrary libvct.a
}
Overlay overlay5
{
\tAfter main
}
Overlay gts_application
{
\tAfter main
}
"""

CSV = """\
Source File,Target File
res/prebuilt/data/UTF16.dat,/data/UTF16.dat
res/field/lighting/lighting.narc,/data/arealight.narc
"""


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


class ListDerivationTests(unittest.TestCase):
    def test_overlay_sbins_follow_lsf_order_with_main_first(self):
        self.assertEqual(
            uc.overlay_sbins(LSF),
            ["main.sbin", "dummy1.sbin", "nintendo_wfc.sbin", "overlay5.sbin", "gts_application.sbin"],
        )

    def test_shared_sbins_exclude_revision_specific_ones(self):
        self.assertEqual(
            uc.shared_sbins(LSF),
            ["main.sbin", "dummy1.sbin", "nintendo_wfc.sbin", "overlay5.sbin"],
        )

    def test_revision_sbins_are_the_known_set(self):
        self.assertEqual(uc.revision_sbins(LSF), ["gts_application.sbin"])

    def test_revision_sbins_missing_from_lsf_is_an_error(self):
        with self.assertRaises(uc.ManifestError):
            uc.revision_sbins("Static main\n{\n}\nOverlay overlay5\n{\n}\n")

    def test_filesys_sources_are_first_csv_column_in_order(self):
        self.assertEqual(
            uc.filesys_sources(CSV),
            ["res/prebuilt/data/UTF16.dat", "res/field/lighting/lighting.narc"],
        )

    def test_filesys_sources_ignore_blank_lines(self):
        self.assertEqual(uc.filesys_sources(CSV + "\n\n"), uc.filesys_sources(CSV))


class FakeRepo:
    """A throwaway repo root + build dir laid out the way the script expects."""

    def __init__(self, root: Path, revision: str = "1"):
        self.root = root
        self.spec = root / "platinum.us"
        self.build = root / "build"
        self.spec.mkdir(parents=True)
        (self.spec / "main.lsf").write_text(LSF)
        (self.spec / "filesys.csv").write_text(CSV)
        info = self.build / "meson-info"
        info.mkdir(parents=True)
        (info / "intro-buildoptions.json").write_text(
            json.dumps([{"name": "revision", "value": revision}])
        )
        self.files = {
            "main.sbin": b"main",
            "dummy1.sbin": b"d1",
            "nintendo_wfc.sbin": b"wfc",
            "overlay5.sbin": b"ov5",
            "gts_application.sbin": b"gts",
            "res/prebuilt/data/UTF16.dat": b"utf16",
            "res/field/lighting/lighting.narc": b"light",
            "subprojects/NitroSDK-4.2.30001/components/ichneumon/ichneumon_sub.sbin": b"arm7",
            "pokeplatinum.us.nds": b"rom",
        }
        for rel, data in self.files.items():
            path = self.build / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def manifest(self, name: str) -> str:
        return (self.spec / name).read_text()


class BlessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = FakeRepo(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_bless_writes_every_manifest_for_the_configured_revision(self):
        uc.bless(self.repo.root, self.repo.build, revision="1", dry_run=False)
        f = self.repo.files
        self.assertEqual(
            self.repo.manifest("sbins_shared.sha1"),
            f"{sha1(f['main.sbin'])} *main.sbin\n"
            f"{sha1(f['dummy1.sbin'])} *dummy1.sbin\n"
            f"{sha1(f['nintendo_wfc.sbin'])} *nintendo_wfc.sbin\n"
            f"{sha1(f['overlay5.sbin'])} *overlay5.sbin\n",
        )
        self.assertEqual(
            self.repo.manifest("sbins_rev1.sha1"),
            f"{sha1(f['gts_application.sbin'])} *gts_application.sbin\n",
        )
        self.assertEqual(
            self.repo.manifest("rom_rev1.sha1"),
            f"{sha1(f['pokeplatinum.us.nds'])} *pokeplatinum.us.nds\n",
        )
        self.assertEqual(
            self.repo.manifest("sbins_arm7.sha1"),
            f"{sha1(f['subprojects/NitroSDK-4.2.30001/components/ichneumon/ichneumon_sub.sbin'])}"
            " *subprojects/NitroSDK-4.2.30001/components/ichneumon/ichneumon_sub.sbin\n",
        )
        self.assertEqual(
            self.repo.manifest("filesys.sha1"),
            f"{sha1(f['res/prebuilt/data/UTF16.dat'])} *res/prebuilt/data/UTF16.dat\n"
            f"{sha1(f['res/field/lighting/lighting.narc'])} *res/field/lighting/lighting.narc\n",
        )
        self.assertFalse((self.repo.spec / "sbins_rev0.sha1").exists())
        self.assertFalse((self.repo.spec / "rom_rev0.sha1").exists())

    def test_stale_entries_in_an_old_manifest_are_dropped(self):
        (self.repo.spec / "sbins_shared.sha1").write_text(
            "0000000000000000000000000000000000000000 *overlay88.sbin\n"
        )
        uc.bless(self.repo.root, self.repo.build, revision="1", dry_run=False)
        self.assertNotIn("overlay88", self.repo.manifest("sbins_shared.sha1"))
        self.assertIn("*main.sbin", self.repo.manifest("sbins_shared.sha1"))

    def test_dry_run_leaves_manifests_alone(self):
        uc.bless(self.repo.root, self.repo.build, revision="1", dry_run=True)
        self.assertFalse((self.repo.spec / "sbins_shared.sha1").exists())

    def test_missing_build_output_is_an_error(self):
        (self.repo.build / "overlay5.sbin").unlink()
        with self.assertRaises(uc.ManifestError):
            uc.bless(self.repo.root, self.repo.build, revision="1", dry_run=False)


class CommandLineTests(unittest.TestCase):
    """End-to-end: invoke the script the way the Makefile does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = FakeRepo(Path(self.tmp.name), revision="0")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *extra):
        return subprocess.run(
            [sys.executable, str(HERE / "update_checksums.py"),
             "--repo-root", str(self.repo.root), "-C", str(self.repo.build), *extra],
            capture_output=True, text=True,
        )

    def test_detects_revision_from_build_dir_and_blesses(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.repo.spec / "sbins_rev0.sha1").exists())
        self.assertFalse((self.repo.spec / "sbins_rev1.sha1").exists())
        self.assertIn("rev0", result.stdout)

    def test_reports_nonzero_when_the_build_is_incomplete(self):
        (self.repo.build / "pokeplatinum.us.nds").unlink()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pokeplatinum.us.nds", result.stderr)


if __name__ == "__main__":
    unittest.main()
