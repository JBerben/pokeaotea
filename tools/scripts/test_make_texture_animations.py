#!/usr/bin/env python3
# ABOUTME: Tests for make_texture_animations.py, the packer for field texture animations (fldtanime.narc).
# ABOUTME: Run with `python3 -m unittest tools.scripts.test_make_texture_animations` from the repo root.

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

import make_texture_animations as mta  # noqa: E402

ANIM_DIR = REPO / 'res' / 'field' / 'texture_animations'
ANIM_JSON = ANIM_DIR / 'texture_animations.json'
FRAMES_DIR = ANIM_DIR / 'frames'
NITROARC = Path(os.environ.get('NITROARC', REPO / 'build' / 'tools' / 'nitroarc' / 'nitroarc'))

PLTT16_16 = mta.TextureInfo('x', mta.GX_TEXFMT_PLTT16, 16, 16)


def animation(texture='wf_fall.1', frames='wf_fall_1.nsbtx', sequence=((0, 9), (1, 9))):
    return {
        'texture': texture,
        'frames': frames,
        'sequence': [{'frame': f, 'hold': h} for f, h in sequence],
    }


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


class ReadNsbtxTexturesTest(unittest.TestCase):
    def test_reads_names_formats_and_sizes_from_retail_sea_frames(self):
        textures = mta.read_nsbtx_textures((FRAMES_DIR / 'sea.nsbtx').read_bytes())

        self.assertEqual([t.name for t in textures], [f'sea.{i}' for i in range(1, 9)])
        for t in textures:
            self.assertEqual((t.format, t.width, t.height), (mta.GX_TEXFMT_PLTT16, 16, 16))

    def test_reads_non_square_retail_textures(self):
        textures = mta.read_nsbtx_textures((FRAMES_DIR / 'azt_wall02_1.nsbtx').read_bytes())

        self.assertEqual({(t.width, t.height) for t in textures}, {(32, 64)})

    def test_rejects_files_that_are_not_nsbtx(self):
        with self.assertRaisesRegex(ValueError, 'BTX0'):
            mta.read_nsbtx_textures(b'NARC' + bytes(60))


class EncodeTableTest(unittest.TestCase):
    def test_encodes_count_zero_padded_name_and_ff_padded_frames(self):
        table = mta.encode_table([animation(texture='sea', sequence=((0, 9), (1, 9)))])

        self.assertEqual(len(table), 4 + 52)
        self.assertEqual(table[0:4], (1).to_bytes(4, 'little'))
        self.assertEqual(table[4:20], b'sea' + bytes(13))
        self.assertEqual(table[20:24], bytes([0, 9, 1, 9]))
        self.assertEqual(table[24:56], b'\xff' * 32)

    def test_sixteen_character_names_fill_the_field_without_terminator(self):
        table = mta.encode_table([animation(texture='abcdefghijklmnop')])

        self.assertEqual(table[4:20], b'abcdefghijklmnop')

    def test_decode_inverts_encode(self):
        animations = [
            animation(texture='sea', sequence=((0, 9), (1, 9), (2, 9))),
            animation(texture='c1_lamp01', sequence=((0, 18), (1, 6), (4, 27))),
        ]

        decoded = mta.decode_table(mta.encode_table(animations))

        self.assertEqual(decoded, [{'texture': a['texture'], 'sequence': a['sequence']} for a in animations])

    def test_decode_rejects_truncated_tables(self):
        with self.assertRaisesRegex(ValueError, 'expected 108 bytes'):
            mta.decode_table((2).to_bytes(4, 'little') + bytes(52))


class ValidateTest(unittest.TestCase):
    def frames(self, count=2, texture=PLTT16_16):
        return {'wf_fall_1.nsbtx': [texture] * count}

    def test_valid_animation_has_no_errors(self):
        self.assertEqual(mta.validate([animation()], self.frames()), [])

    def test_texture_name_must_be_1_to_16_ascii_characters(self):
        for name in ['', 'abcdefghijklmnopq', 'wasserfall_ü']:
            with self.subTest(name=name):
                errors = mta.validate([animation(texture=name)], self.frames())
                self.assertEqual(len(errors), 1)
                self.assertIn('texture name', errors[0])

    def test_texture_names_must_be_unique(self):
        errors = mta.validate([animation(), animation()], self.frames())

        self.assertEqual(errors, ["animation 1 'wf_fall.1': texture name is already used by animation 0"])

    def test_sequence_must_have_1_to_17_steps(self):
        for steps in [0, 18]:
            with self.subTest(steps=steps):
                errors = mta.validate([animation(sequence=[(0, 1)] * steps)], self.frames())
                self.assertEqual(len(errors), 1)
                self.assertIn('1 to 17 steps', errors[0])

    def test_seventeen_steps_is_allowed(self):
        self.assertEqual(mta.validate([animation(sequence=[(0, 1)] * 17)], self.frames()), [])

    def test_frame_must_index_a_texture_in_the_frames_file(self):
        errors = mta.validate([animation(sequence=((0, 9), (2, 9)))], self.frames(count=2))

        self.assertEqual(errors, ["animation 0 'wf_fall.1': step 1 uses frame 2, but wf_fall_1.nsbtx only has 2 textures"])

    def test_hold_must_fit_in_a_byte(self):
        errors = mta.validate([animation(sequence=((0, 256),))], self.frames())

        self.assertEqual(errors, ["animation 0 'wf_fall.1': step 0 hold 256 is outside 0-255"])

    def test_frame_textures_must_share_format_and_size(self):
        mixed = {'wf_fall_1.nsbtx': [PLTT16_16, mta.TextureInfo('y', mta.GX_TEXFMT_PLTT16, 32, 32)]}

        errors = mta.validate([animation()], mixed)

        self.assertEqual(len(errors), 1)
        self.assertIn('same format and size', errors[0])

    def test_compressed_and_direct_colour_formats_are_rejected(self):
        for fmt in [mta.GX_TEXFMT_COMP4x4, mta.GX_TEXFMT_DIRECT]:
            with self.subTest(fmt=fmt):
                frames = self.frames(texture=mta.TextureInfo('x', fmt, 16, 16))
                errors = mta.validate([animation()], frames)
                self.assertEqual(len(errors), 1)
                self.assertIn('unsupported texture format', errors[0])

    def test_referenced_frames_file_must_be_provided(self):
        errors = mta.validate([animation(frames='missing.nsbtx')], self.frames())

        self.assertIn("animation 0 'wf_fall.1': frames file missing.nsbtx is not listed in res/field/texture_animations/meson.build", errors)

    def test_provided_frames_files_must_be_referenced(self):
        frames = self.frames() | {'orphan.nsbtx': [PLTT16_16]}

        errors = mta.validate([animation()], frames)

        self.assertEqual(errors, ['frames file orphan.nsbtx is not used by any animation'])

    def test_committed_animations_are_valid(self):
        animations = json.loads(ANIM_JSON.read_text(encoding='utf-8'))['animations']
        frames = {p.name: mta.read_nsbtx_textures(p.read_bytes()) for p in FRAMES_DIR.glob('*.nsbtx')}

        self.assertEqual(mta.validate(animations, frames), [])


class PackIntegrationTest(unittest.TestCase):
    """Runs the script as meson does, with the real nitroarc and the committed data."""

    def setUp(self):
        self.assertTrue(NITROARC.is_file(), f'nitroarc not built at {NITROARC}; run `make` first')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)

    def pack(self, json_path: Path, frame_paths: list[Path]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable, str(HERE / 'make_texture_animations.py'),
                '--nitroarc', str(NITROARC),
                '--staging', str(self.tmpdir / 'staging'),
                '--output', str(self.tmpdir / 'out.narc'),
                str(json_path), *map(str, frame_paths),
            ],
            capture_output=True, text=True,
        )

    def test_packs_committed_data_into_table_plus_frames_in_json_order(self):
        animations = json.loads(ANIM_JSON.read_text(encoding='utf-8'))['animations']

        result = self.pack(ANIM_JSON, sorted(FRAMES_DIR.glob('*.nsbtx')))

        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        members = read_narc_members((self.tmpdir / 'out.narc').read_bytes())
        self.assertEqual(len(members), 1 + len(animations))
        self.assertEqual(members[0], mta.encode_table(animations))
        for i, anim in enumerate(animations):
            self.assertEqual(members[i + 1], (FRAMES_DIR / anim['frames']).read_bytes(), anim['texture'])

    def test_invalid_data_fails_with_every_error_on_stderr_and_no_output(self):
        bad_json = self.tmpdir / 'bad.json'
        bad_json.write_text(json.dumps({'animations': [
            animation(texture='sea', frames='sea.nsbtx', sequence=((8, 9),)),
            animation(texture='sea', frames='sea.nsbtx', sequence=((0, 300),)),
        ]}))

        result = self.pack(bad_json, [FRAMES_DIR / 'sea.nsbtx'])

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr.splitlines(), [
            f'{bad_json}: invalid texture animations:',
            "  animation 0 'sea': step 0 uses frame 8, but sea.nsbtx only has 8 textures",
            "  animation 1 'sea': texture name is already used by animation 0",
            "  animation 1 'sea': step 0 hold 300 is outside 0-255",
        ])
        self.assertFalse((self.tmpdir / 'out.narc').exists())


if __name__ == '__main__':
    unittest.main()
