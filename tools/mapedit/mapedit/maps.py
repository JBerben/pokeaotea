# ABOUTME: Plain-data layer for mapedit: map headers, a map's blocks, tiles, events and props, read through tools/scripts.
# ABOUTME: Nothing here draws or writes; screens call it to get what to show and the scripts' own Change objects to apply.

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'tools' / 'scripts'))

import check_tile  # noqa: E402
import map_props  # noqa: E402

TILE_WALKABLE = check_tile.TILE_WALKABLE
TILE_BLOCKED = check_tile.TILE_BLOCKED
TILE_WATER = check_tile.TILE_WATER
TILE_DOOR = check_tile.TILE_DOOR
TILE_SPECIAL = check_tile.TILE_SPECIAL
TILE_SYMBOLS = check_tile.TILE_SYMBOLS

EVENTS = Path('res/field/events')
BLOCK_TILES = map_props.TILES_PER_BLOCK


class Tile(NamedTuple):
    x: int
    z: int
    collision: bool
    behavior: int
    behavior_name: str
    kind: str


class Marker(NamedTuple):
    kind: str   # 'prop', 'warp', 'npc', 'sign' or 'trigger'
    x: float
    z: float
    label: str


def tile_of(coordinate: float) -> int:
    """The world tile a coordinate falls on; tile t spans [t - 0.5, t + 0.5) in tile-centre units."""
    return math.floor(coordinate + 0.5)


class MapRepository:
    def __init__(self, root: Path):
        self.root = root
        self.context = map_props.MapContext(root)
        self.behavior_names = check_tile.tile_behavior_names()

    def headers(self) -> list[str]:
        return sorted(self.context.headers())

    def search(self, query: str) -> list[str]:
        words = query.upper().split()
        return [header for header in self.headers() if all(word in header for word in words)]

    def load(self, header: str) -> 'MapView':
        area, model_set, models = self.context.model_set(header)
        return MapView(self, header, self.context.blocks(header), area, model_set, models)


@dataclass
class MapView:
    repository: MapRepository
    header: str
    blocks: list
    area: str
    model_set: str
    models: list[str]

    @property
    def context(self) -> map_props.MapContext:
        return self.repository.context

    def tiles(self, block) -> list[list[Tile]]:
        """Rows (z) of tiles (x), in world coordinates."""
        land = self.context.read_block(block)
        values = [int.from_bytes(land.terrain[i:i + 2], 'little') for i in range(0, len(land.terrain), 2)]
        names = self.repository.behavior_names
        rows = []
        for local_z in range(BLOCK_TILES):
            row = []
            for local_x in range(BLOCK_TILES):
                value = values[local_z * BLOCK_TILES + local_x]
                collision = (value >> check_tile.COLLISION_SHIFT) & 1
                behavior = value & check_tile.BEHAVIOR_MASK
                name = names[behavior] if behavior < len(names) else f'behavior {behavior}'
                row.append(Tile(block.base_x + local_x, block.base_z + local_z, bool(collision), behavior, name,
                                check_tile.classify_tile(collision, behavior, names)))
            rows.append(row)
        return rows

    def tile_at(self, block, x: int, z: int) -> Tile:
        return self.tiles(block)[z - block.base_z][x - block.base_x]

    def events(self, block) -> list[Marker]:
        events_id = self.context.header(self.header).get('eventsArchiveID', 'events_empty')
        path = self.repository.root / EVENTS / f'{events_id}.json'
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding='utf-8'))
        markers = []
        for event in data.get('warp_events', []):
            markers.append(Marker('warp', event['x'], event['z'], event['dest_header_id']))
        for event in data.get('object_events', []):
            markers.append(Marker('npc', event['x'], event['z'], str(event['id'])))
        for event in data.get('bg_events', []):
            markers.append(Marker('sign', event['x'], event['z'], f"script {event['script']}"))
        for event in data.get('coord_events', []):
            markers.append(Marker('trigger', event['x'], event['z'], f"script {event['script']}"))
        return [m for m in markers if block.contains(m.x, m.z)]

    def props(self, block) -> list[map_props.PropRow]:
        prefix = f'{block.land_data}:'
        return [row for row in map_props.list_props(self.context, self.header) if row.prop_id.startswith(prefix)]

    def markers(self, block) -> list[Marker]:
        props = [Marker('prop', row.x, row.z, row.prop_id) for row in self.props(block)]
        return props + self.events(block)

    def markers_at(self, block, x: int, z: int) -> list[Marker]:
        return [m for m in self.markers(block) if (tile_of(m.x), tile_of(m.z)) == (x, z)]
