#!/usr/bin/env python3
# ABOUTME: Tests for nitro_textures.py, which reads, appends to, and writes NitroSystem texture sets (TEX0 blocks).
# ABOUTME: Retail prop texture sets are the oracle: rebuilt dictionaries and round trips must match them byte for byte.

import struct
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import nitro_textures as nt  # noqa: E402

TEXTURE_SETS_DIR = REPO / 'res' / 'field' / 'props' / 'texture_sets'
MODELS_DIR = REPO / 'res' / 'field' / 'props' / 'models'
RETAIL_TEXTURE_SETS = sorted(TEXTURE_SETS_DIR.glob('*.nsbtx'))


def name16(text: str) -> bytes:
    return text.encode('ascii').ljust(16, b'\0')


def pltt16_param(width=16, height=16) -> int:
    return (nt.GX_TEXFMT_PLTT16 << 26) | ((width.bit_length() - 4) << 20) | ((height.bit_length() - 4) << 23)


def texture(name, fill=0x11, width=16, height=16):
    return nt.Texture(name, pltt16_param(width, height), 0, bytes([fill]) * (width * height // 2))


def palette(name, fill=0x22, size=32, four_colour=False):
    return nt.Palette(name, nt.PLTT_FLAG_FOUR_COLOUR if four_colour else 0, bytes([fill]) * size)


class DictTreeTest(unittest.TestCase):
    def test_rebuilds_every_retail_texture_and_palette_dictionary_tree(self):
        self.assertTrue(RETAIL_TEXTURE_SETS)
        for path in RETAIL_TEXTURE_SETS:
            data = path.read_bytes()
            tex0 = nt.find_tex0(data)
            for dict_offset in nt.dict_offsets(data, tex0):
                names, tree = nt.read_dict_names_and_tree(data, dict_offset)
                with self.subTest(path=path.name, dict_offset=dict_offset):
                    self.assertEqual(nt.dict_tree(names), tree)

    def test_single_entry_tree_branches_on_the_highest_set_bit(self):
        # 'a' is 0x61; bit 6 is the highest bit that differs from the all-zero name.
        self.assertEqual(nt.dict_tree([name16('a')]), bytes([127, 1, 0, 0, 6, 0, 1, 0]))

    def test_duplicate_names_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            nt.dict_tree([name16('a'), name16('a')])


class RoundTripTest(unittest.TestCase):
    def test_every_retail_texture_set_writes_back_unchanged(self):
        for path in RETAIL_TEXTURE_SETS:
            data = path.read_bytes()
            with self.subTest(path=path.name):
                self.assertEqual(nt.write_nsbtx(nt.read_texture_set(data)), data)

    def test_rejects_files_without_textures(self):
        with self.assertRaisesRegex(ValueError, 'no TEX0'):
            nt.read_texture_set(b'BTX0' + bytes(60))


class ReadTexturesTest(unittest.TestCase):
    def test_decodes_names_formats_and_data(self):
        texture_set = nt.read_texture_set((TEXTURE_SETS_DIR / 'prop_texture_set_000.nsbtx').read_bytes())

        textures = texture_set.textures()
        self.assertEqual(textures[0].name, 'h_kage')
        self.assertEqual(len(textures[0].data), 64)
        self.assertEqual(textures[1].name, 'pcloof')
        self.assertEqual(len(textures[1].data), 2048)

        palettes = texture_set.palettes()
        self.assertEqual(palettes[0].name, 'h_kage_pl')
        self.assertTrue(palettes[0].flag & nt.PLTT_FLAG_FOUR_COLOUR)

    def test_reads_the_textures_embedded_in_a_model(self):
        texture_set = nt.read_texture_set((MODELS_DIR / 'prop_model_005.nsbmd').read_bytes())

        self.assertIn('h_kage', [t.name for t in texture_set.textures()])

    def test_model_without_embedded_textures_has_none(self):
        models = [p for p in sorted(MODELS_DIR.glob('*.nsbmd')) if nt.find_tex0(p.read_bytes()) is None]
        self.assertTrue(models)

        with self.assertRaisesRegex(ValueError, 'no TEX0'):
            nt.read_texture_set(models[0].read_bytes())


class AppendTest(unittest.TestCase):
    def base(self):
        return nt.build_texture_set([texture('wall', 0x11)], [palette('wall_pl', 0x22)])

    def test_splitting_a_retail_set_and_appending_the_rest_restores_it(self):
        data = (TEXTURE_SETS_DIR / 'prop_texture_set_000.nsbtx').read_bytes()
        whole = nt.read_texture_set(data)
        textures, palettes = whole.textures(), whole.palettes()

        first = nt.build_texture_set(textures[:-1], palettes[:-1])
        merged, skipped = nt.append_textures(first, [textures[-1]], [palettes[-1]])

        self.assertEqual(skipped, [])
        self.assertEqual(nt.write_nsbtx(merged), data)

    def test_appending_a_models_own_textures_to_its_area_set_changes_nothing(self):
        area_set = (TEXTURE_SETS_DIR / 'prop_texture_set_000.nsbtx').read_bytes()
        model = nt.read_texture_set((MODELS_DIR / 'prop_model_005.nsbmd').read_bytes())

        merged, skipped = nt.append_textures(nt.read_texture_set(area_set), model.textures(), model.palettes())

        self.assertEqual(nt.write_nsbtx(merged), area_set)
        self.assertEqual(sorted(skipped), sorted([t.name for t in model.textures()] + [p.name for p in model.palettes()]))

    def test_appended_texture_addresses_follow_the_existing_data(self):
        merged, _ = nt.append_textures(self.base(), [texture('fall', 0x33)], [])

        textures = merged.textures()
        self.assertEqual([t.name for t in textures], ['wall', 'fall'])
        self.assertEqual(textures[1].data, bytes([0x33]) * 128)
        self.assertEqual(merged.textures()[1].param & nt.TEXIMAGE_ADDR_MASK, 128 // 8)

    def test_non_four_colour_palettes_start_on_a_16_byte_boundary(self):
        base = nt.build_texture_set([], [palette('shadow_pl', 0x44, size=8, four_colour=True)])

        merged, _ = nt.append_textures(base, [], [palette('fall_pl', 0x55)])

        fall = merged.palettes()[1]
        self.assertEqual(fall.data, bytes([0x55]) * 32)
        self.assertEqual(merged.palette_offset('fall_pl') % 16, 0)

    def test_four_colour_palettes_set_the_use_pltt4_flag(self):
        merged, _ = nt.append_textures(self.base(), [], [palette('glow_pl', size=8, four_colour=True)])

        self.assertEqual(merged.pltt_flag, nt.PLTT_INFO_USE_PLTT4)

    def test_identical_textures_and_palettes_with_the_same_name_are_shared(self):
        merged, skipped = nt.append_textures(self.base(), [texture('wall', 0x11)], [palette('wall_pl', 0x22)])

        self.assertEqual(skipped, ['wall', 'wall_pl'])
        self.assertEqual(nt.write_nsbtx(merged), nt.write_nsbtx(self.base()))

    def test_a_different_texture_with_an_existing_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "texture 'wall' already exists in the set with different data"):
            nt.append_textures(self.base(), [texture('wall', 0x99)], [])

    def test_a_different_palette_with_an_existing_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "palette 'wall_pl' already exists in the set with different data"):
            nt.append_textures(self.base(), [], [palette('wall_pl', 0x99)])

    def test_compressed_textures_cannot_be_appended(self):
        compressed = nt.Texture('rock', (nt.GX_TEXFMT_COMP4x4 << 26), 0, bytes(8))

        with self.assertRaisesRegex(ValueError, "texture 'rock' is 4x4 compressed"):
            nt.append_textures(self.base(), [compressed], [])

    def test_a_set_holds_at_most_255_textures(self):
        many = [texture(f't{i}') for i in range(255)]

        with self.assertRaisesRegex(ValueError, 'at most 255 textures'):
            nt.append_textures(self.base(), many, [])

    def test_names_must_fit_in_16_ascii_characters(self):
        with self.assertRaisesRegex(ValueError, 'must be 1-16 ASCII characters'):
            nt.append_textures(self.base(), [texture('a_very_long_texture_name')], [])


if __name__ == '__main__':
    unittest.main()
