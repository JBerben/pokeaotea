# ABOUTME: Weather fog as the DS draws it: per-weather fog settings from the field weather code, the settled
# ABOUTME: density table, and the depth-indexed density lookup applied to a rendered image.

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FogSettings:
    slope: int              # GX_FOGSLOPE index: each density table entry spans 0x400 >> slope depth units
    offset: int             # 15-bit depth where the table starts
    colour555: tuple        # GX_RGB components, 0-31

    @property
    def colour(self) -> np.ndarray:
        return np.array(self.colour555, dtype=float) / 31


# From each weather's task in src/overlay005/ov5_021D5EB8.c (its ov5_021D7308 call).
WEATHER_FOG = {
    'OVERWORLD_WEATHER_RAINING': FogSettings(3, 0x6F6F + 0x300, (26, 26, 26)),
    'OVERWORLD_WEATHER_SNOWING': FogSettings(3, 0x6F6F + 0x300, (26, 26, 26)),
    'OVERWORLD_WEATHER_HEAVY_SNOW': FogSettings(3, 0x6F6F - 0x200, (24, 24, 24)),
    'OVERWORLD_WEATHER_BLIZZARD': FogSettings(3, 0x6F6F - 0x400, (24, 24, 24)),
    'OVERWORLD_WEATHER_CLEAR_8': FogSettings(5, 0x6F6F + 0xAA0, (31, 31, 31)),
    'OVERWORLD_WEATHER_SLOW_ASHFALL': FogSettings(3, 0x6F6F - 0x40, (20, 20, 14)),
    'OVERWORLD_WEATHER_SANDSTORM': FogSettings(3, 28399, (26, 20, 5)),
    'OVERWORLD_WEATHER_HAILING': FogSettings(3, 0x6F6F + 0x200, (26, 26, 26)),
    'OVERWORLD_WEATHER_FOG': FogSettings(6, 30037, (31, 31, 31)),
    'OVERWORLD_WEATHER_DEEP_FOG': FogSettings(7, 30287, (0, 0, 0)),
    'OVERWORLD_WEATHER_23': FogSettings(3, 0x6F6F - 1600, (31, 31, 31)),
}

# The table once the weather's fade-in (ov5_021D7534) has finished.
DENSITY_TABLE = [min(4 * i, 127) for i in range(32)]


def density(depth15: np.ndarray, settings: FogSettings) -> np.ndarray:
    """Fog density 0-1 at 15-bit depths, interpolating between table entries as the hardware does."""
    span = 0x400 >> settings.slope
    position = np.clip((depth15 - settings.offset) / span, 0, len(DENSITY_TABLE) - 1)
    index = np.floor(position).astype(int)
    upper = np.minimum(index + 1, len(DENSITY_TABLE) - 1)
    fraction = position - index
    table = np.array(DENSITY_TABLE, dtype=float)
    return (table[index] * (1 - fraction) + table[upper] * fraction) / 128


def depth15(ndc_z: np.ndarray) -> np.ndarray:
    """The 15-bit depth the fog unit sees for a normalised device depth (-1 near, 1 far)."""
    return np.clip(ndc_z * 0x4000 + 0x3FFF, 0, 0x7FFF)


def apply(colour: np.ndarray, depth: np.ndarray, settings: FogSettings):
    """Blends drawn pixels (finite depth) toward the fog colour, in place on a 0-1 float image."""
    drawn = np.isfinite(depth)
    amount = density(depth15(depth[drawn]), settings)[:, None]
    colour[drawn, :3] = colour[drawn, :3] * (1 - amount) + settings.colour * amount
