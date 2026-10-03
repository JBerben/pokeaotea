# ABOUTME: Decodes NSBTX textures (every format the game's map and prop sets use) to RGBA arrays.
# ABOUTME: Colour and alpha expansion repeat the bit pattern, as the hardware and nitrobtx do.

import numpy as np

from .. import maps  # noqa: F401  (puts tools/scripts on sys.path)

import nitro_textures as nt  # noqa: E402

TRANSPARENT_COLOUR_0 = 1 << 29   # texImageParam bit: palette entry 0 is transparent


def expand(values: np.ndarray, bits: int) -> np.ndarray:
    """Widens bits-wide channel values to 8 bits by repeating the bit pattern."""
    values = values.astype(np.uint32)
    multiplier, filled = 1, bits
    while filled < 8:
        multiplier = (multiplier << bits) | 1
        filled += bits
    return ((values * multiplier) >> (filled - 8)).astype(np.uint8)


def rgb555_to_rgb888(colours: np.ndarray) -> np.ndarray:
    colours = np.asarray(colours, dtype=np.uint32)
    return np.stack([expand(colours & 31, 5), expand((colours >> 5) & 31, 5), expand((colours >> 10) & 31, 5)], axis=-1)


def palette_rgb(palette) -> np.ndarray:
    return rgb555_to_rgb888(np.frombuffer(palette.data[:len(palette.data) // 2 * 2], dtype='<u2'))


def size(texture) -> tuple[int, int]:
    return 8 << ((texture.param >> 20) & 7), 8 << ((texture.param >> 23) & 7)


def decode_indices(texture) -> np.ndarray:
    """Per-texel palette indices (or raw texel values for direct colour), shape (height, width)."""
    width, height = size(texture)
    fmt = nt.texture_format(texture.param)
    raw = np.frombuffer(texture.data, dtype=np.uint8)
    if fmt == nt.GX_TEXFMT_PLTT4:
        values = np.stack([(raw >> shift) & 3 for shift in (0, 2, 4, 6)], axis=1).reshape(-1)
    elif fmt == nt.GX_TEXFMT_PLTT16:
        values = np.stack([raw & 15, raw >> 4], axis=1).reshape(-1)
    elif fmt in (nt.GX_TEXFMT_PLTT256, nt.GX_TEXFMT_A3I5, nt.GX_TEXFMT_A5I3):
        values = raw
    elif fmt == nt.GX_TEXFMT_DIRECT:
        values = np.frombuffer(texture.data, dtype='<u2')
    else:
        raise ValueError(f'texture {texture.name!r} has unsupported format {fmt}')
    return values[:width * height].reshape(height, width)


def decode(texture, palette_data: bytes) -> np.ndarray:
    """RGBA texels, shape (height, width, 4)."""
    fmt = nt.texture_format(texture.param)
    if fmt == nt.GX_TEXFMT_COMP4x4:
        raise ValueError(f'texture {texture.name!r} is 4x4 compressed, which the renderer does not support')
    texels = decode_indices(texture)

    if fmt == nt.GX_TEXFMT_DIRECT:
        rgb = rgb555_to_rgb888(texels)
        alpha = np.where(texels & 0x8000, 255, 0).astype(np.uint8)
        return np.dstack([rgb, alpha])

    colours = rgb555_to_rgb888(np.frombuffer(palette_data[:len(palette_data) // 2 * 2], dtype='<u2'))
    if fmt == nt.GX_TEXFMT_A3I5:
        indices, alpha = texels & 31, expand(texels >> 5, 3)
    elif fmt == nt.GX_TEXFMT_A5I3:
        indices, alpha = texels & 7, expand(texels >> 3, 5)
    else:
        indices = texels
        alpha = np.full(texels.shape, 255, dtype=np.uint8)
        if texture.param & TRANSPARENT_COLOUR_0:
            alpha[indices == 0] = 0
    indices = np.minimum(indices, len(colours) - 1)
    return np.dstack([colours[indices], alpha])
