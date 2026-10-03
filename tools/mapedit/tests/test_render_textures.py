# ABOUTME: Tests for mapedit.render.textures, the NSBTX texture decoder.
# ABOUTME: The oracle is nitrobtx's dump: indexed PNGs + JASC palettes for palette formats, RGBA for alpha formats.

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from mapedit import maps
from mapedit.render import textures

NITROBTX = maps.REPO / 'build/tools/nitrobtx/nitrobtx'
TEXTURE_SETS = [
    maps.REPO / 'res/field/props/texture_sets/prop_texture_set_000.nsbtx',
    maps.REPO / 'res/field/props/texture_sets/prop_texture_set_002.nsbtx',
    maps.REPO / 'res/field/maps/texture_sets/map_texture_set_074.nsbtx',
]


def read_jasc(path: Path) -> np.ndarray:
    lines = path.read_text().split('\n')
    count = int(lines[2])
    return np.array([[int(v) for v in line.split()] for line in lines[3:3 + count]], dtype=np.uint8)


class FormatTest(unittest.TestCase):
    def test_rgb555_expands_like_the_hardware(self):
        np.testing.assert_array_equal(textures.rgb555_to_rgb888(np.array([0x7FFF, 0x0009, 0x001A])),
                                      [[255, 255, 255], [74, 0, 0], [214, 0, 0]])

    def test_compressed_textures_are_refused(self):
        texture = textures.nt.Texture('rock', textures.nt.GX_TEXFMT_COMP4x4 << 26, 0, bytes(8))

        with self.assertRaisesRegex(ValueError, "texture 'rock' is 4x4 compressed"):
            textures.decode(texture, bytes(32))


class NitroBtxOracleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not NITROBTX.exists():
            raise unittest.SkipTest(f'nitrobtx not built at {NITROBTX}; run `make` first')

    def test_every_texture_matches_the_nitrobtx_dump(self):
        checked = 0
        for path in TEXTURE_SETS:
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run([str(NITROBTX), 'dump', str(path), tmp], check=True, capture_output=True)
                texture_set = textures.nt.read_texture_set(path.read_bytes())
                palettes = {p.name: p for p in texture_set.palettes()}
                for texture in texture_set.textures():
                    dumped = Path(tmp) / f'{texture.name}.png'
                    palette = palettes.get(f'{texture.name}_pl') or palettes.get(texture.name)
                    if not dumped.exists() or palette is None:
                        continue
                    image = Image.open(dumped)
                    with self.subTest(set=path.name, texture=texture.name):
                        if image.mode == 'P':
                            np.testing.assert_array_equal(textures.decode_indices(texture), np.array(image))
                            colours = read_jasc(Path(tmp) / f'{palette.name}.pal')
                            np.testing.assert_array_equal(textures.palette_rgb(palette)[:len(colours)], colours)
                        else:
                            np.testing.assert_array_equal(textures.decode(texture, palette.data), np.array(image.convert('RGBA')))
                        checked += 1
        self.assertGreater(checked, 100)

    def test_colour_zero_is_transparent_when_the_texture_says_so(self):
        texture_set = textures.nt.read_texture_set(TEXTURE_SETS[0].read_bytes())
        palettes = {p.name: p for p in texture_set.palettes()}
        transparent = [t for t in texture_set.textures()
                       if t.param & textures.TRANSPARENT_COLOUR_0 and textures.nt.texture_format(t.param) in (2, 3, 4)]
        self.assertTrue(transparent)
        texture = transparent[0]
        palette = palettes.get(f'{texture.name}_pl') or palettes[texture.name]

        rgba = textures.decode(texture, palette.data)

        indices = textures.decode_indices(texture)
        self.assertTrue(np.all(rgba[indices == 0, 3] == 0))
        self.assertTrue(np.all(rgba[indices != 0, 3] == 255))
