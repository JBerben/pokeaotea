# ABOUTME: Builds a throwaway copy of the repo files mapedit reads and writes, so UI tests never touch the real tree.
# ABOUTME: Only the land data files a test names are copied; everything else mapedit needs is small and copied whole.

import shutil
import tempfile
from pathlib import Path

from mapedit import maps

REPO = maps.REPO

FILES = [
    'include/data/map_headers.h',
    'include/constants/field/map_tile_behaviors.h',
    # Matrix editing: header and land data names, and the land data registry.
    'generated/map_headers.txt',
    'generated/maps.txt',
    'res/field/maps/data/meson.build',
    'res/field/maps/data/map_data.order',
]
TREES = [
    'res/field/matrices',
    'res/field/area_data',
    'res/field/events',
    'res/field/props/model_sets',
]
PROP_SOURCES = [
    'res/field/props/models/meson.build',
    'res/field/props/models/map_prop_models.order',
    'res/field/props/models/draw_order_overrides.json',
    'res/field/props/animations/meson.build',
    'res/field/props/animations/prop_animations.order',
    'res/field/props/animations/prop_animation_lists.json',
    'res/field/props/texture_sets/prop_texture_sets.order',
]


# What new_map.py reads and writes, on top of the map files above.
MAP_SOURCES = [
    'res/field/scripts/meson.build',
    'res/field/scripts/scripts.order',
    'generated/text_banks.txt',
]


class Sandbox:
    def __init__(self, land_data=('000',), texture_sets=('000',), map_sources=False):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for relative in FILES + PROP_SOURCES:
            self.copy(relative)
        for relative in TREES:
            shutil.copytree(REPO / relative, self.root / relative)
        for name in land_data:
            self.copy(f'res/field/maps/data/map_data_{name}.bin')
        for name in texture_sets:
            self.copy(f'res/field/props/texture_sets/prop_texture_set_{name}.nsbtx')
        if map_sources:
            for relative in MAP_SOURCES:
                self.copy(relative)
            shutil.copytree(REPO / 'res/text', self.root / 'res/text')

    def copy(self, relative: str):
        (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, self.root / relative)

    def land(self, name='000'):
        return maps.map_props.read_land_data(self.path(f'res/field/maps/data/map_data_{name}.bin').read_bytes())

    def path(self, relative: str) -> Path:
        return self.root / relative

    def cleanup(self):
        self._tmp.cleanup()
