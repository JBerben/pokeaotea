#!/usr/bin/env python3
# ABOUTME: Lists, adds, moves and removes the map props placed in a map's land data (res/field/maps/data/map_data_NNN.bin).
# ABOUTME: Works in world tile coordinates, defaults heights to the BDHC ground, and checks the prop can load in that area.

"""List, add, move and remove the props placed on a map.

    python3 tools/scripts/map_props.py list MAP_HEADER_TWINLEAF_TOWN
    python3 tools/scripts/map_props.py add MAP_HEADER_TWINLEAF_TOWN waterfall --x 105 --z 875 --dry-run
    python3 tools/scripts/map_props.py move MAP_HEADER_TWINLEAF_TOWN 000:3 --x 106 --z 875
    python3 tools/scripts/map_props.py remove MAP_HEADER_TWINLEAF_TOWN 000:3

Coordinates are world tiles, the same ones events and check_tile.py use; a
whole number is the centre of that tile, and fractions are allowed. Heights
are in tiles (16 units) above the block's base, and default to the BDHC ground
at that point. Props are named <land data>:<index>, as `list` prints them.

The game only uses the position, model and scale of a placed prop.
MapPropManager_Render draws land-data props without rotation, so the rotation
stored in the file is kept as it is but has no effect; rotate the model itself.

A land data file can be shared by several maps (every Poké Mart uses the same
one, for example). Edits apply to all of them, and the tool lists them.
"""

import argparse
import json
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[2]
MAP_HEADERS = Path('include/data/map_headers.h')
MATRICES = Path('res/field/matrices')
LAND_DATA = Path('res/field/maps/data')
AREA_DATA = Path('res/field/area_data')
MODEL_SETS = Path('res/field/props/model_sets')
MODELS_ORDER = Path('res/field/props/models/map_prop_models.order')

FX32_SHIFT = 12
FX32_ONE = 1 << FX32_SHIFT
TILE = 16 * FX32_ONE          # MAP_OBJECT_TILE_SIZE
TILES_PER_BLOCK = 32          # MAP_TILES_COUNT_X / MAP_TILES_COUNT_Z
MAX_LOADED_MAP_PROPS = 32
MAP_PROP_SIZE = 0x30
HEADER_SIZE = 0x10
NO_LAND_DATA = 'MAP_NONE'


class MapPropError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__('\n'.join(errors))
        self.errors = errors


class MapPropRecord(NamedTuple):
    model_id: int
    position: tuple[int, int, int]
    rotation: tuple[int, int, int]
    scale: tuple[int, int, int]
    dummy: tuple[int, int]

    def encode(self) -> bytes:
        return struct.pack('<I3i3i3i2I', self.model_id, *self.position, *self.rotation, *self.scale, *self.dummy)

    @classmethod
    def decode(cls, data: bytes) -> 'MapPropRecord':
        values = struct.unpack('<I3i3i3i2I', data)
        return cls(values[0], values[1:4], values[4:7], values[7:10], values[10:12])


@dataclass
class LandData:
    terrain: bytes
    props: list[MapPropRecord]
    model: bytes
    bdhc: bytes
    # Bytes after the last whole prop record. MapPropManager_Load divides the section size by the record
    # size, so they are ignored; retail map_data_506 ends its props with a stray CRLF.
    props_trailer: bytes = b''


def read_land_data(data: bytes) -> LandData:
    terrain_size, props_size, model_size, bdhc_size = struct.unpack_from('<4I', data)
    if HEADER_SIZE + terrain_size + props_size + model_size + bdhc_size != len(data):
        raise ValueError('section sizes do not add up to the file size')

    offset = HEADER_SIZE
    terrain = data[offset:offset + terrain_size]
    offset += terrain_size
    whole = props_size - props_size % MAP_PROP_SIZE
    props = [MapPropRecord.decode(data[offset + i:offset + i + MAP_PROP_SIZE]) for i in range(0, whole, MAP_PROP_SIZE)]
    trailer = data[offset + whole:offset + props_size]
    offset += props_size
    model = data[offset:offset + model_size]
    offset += model_size
    return LandData(terrain, props, model, data[offset:offset + bdhc_size], trailer)


def write_land_data(land: LandData) -> bytes:
    props = b''.join(prop.encode() for prop in land.props) + land.props_trailer
    return (struct.pack('<4I', len(land.terrain), len(props), len(land.model), len(land.bdhc))
            + land.terrain + props + land.model + land.bdhc)


def fx_mul(a: int, b: int) -> int:
    return (a * b + 0x800) >> FX32_SHIFT


def fx_div(numer: int, denom: int) -> int:
    # FX_Div: the hardware divides (numer << 32) by denom, truncating toward zero, then rounds >> 20.
    quotient = abs(numer << 32) // abs(denom)
    if (numer < 0) != (denom < 0):
        quotient = -quotient
    return (quotient + (1 << 19)) >> 20


def ground_heights(bdhc: bytes, x: int, z: int) -> list[int]:
    """Every height the BDHC data gives at (x, z), as CalculateObjectHeight computes them (src/overlay005/bdhc.c)."""
    if bdhc[0:4] != b'BDHC':
        return []
    points_count, normals_count, constants_count, plates_count = struct.unpack_from('<4H', bdhc, 4)
    offset = 0x10
    points = [struct.unpack_from('<2i', bdhc, offset + 8 * i) for i in range(points_count)]
    offset += 8 * points_count
    normals = [struct.unpack_from('<3i', bdhc, offset + 12 * i) for i in range(normals_count)]
    offset += 12 * normals_count
    constants = [struct.unpack_from('<i', bdhc, offset + 4 * i)[0] for i in range(constants_count)]
    offset += 4 * constants_count

    heights = []
    for i in range(plates_count):
        first, second, normal_index, constant_index = struct.unpack_from('<4H', bdhc, offset + 8 * i)
        (x1, z1), (x2, z2) = points[first], points[second]
        if not (min(x1, x2) <= x <= max(x1, x2) and min(z1, z2) <= z <= max(z1, z2)):
            continue
        nx, ny, nz = normals[normal_index]
        if ny == 0:
            continue
        height = fx_div(-(fx_mul(nx, x) + fx_mul(nz, z) + constants[constant_index]), ny)
        if height not in heights:
            heights.append(height)
    return sorted(heights)


def tile_to_offset(tile: float, block_base: int) -> int:
    """Offset from a block's centre of the centre of a world tile."""
    return round((tile - block_base - TILES_PER_BLOCK // 2 + 0.5) * TILE)


def offset_to_tile(offset: int, block_base: int) -> float:
    return block_base + TILES_PER_BLOCK // 2 - 0.5 + offset / TILE


def format_number(value: float) -> str:
    return f'{value:.3f}'.rstrip('0').rstrip('.')


@dataclass
class Block:
    land_data: str      # e.g. '000'
    base_x: int         # world tile of the block's left edge
    base_z: int

    @property
    def name(self) -> str:
        return f'map_data_{self.land_data}'

    def contains(self, x: float, z: float) -> bool:
        return (self.base_x - 0.5 <= x < self.base_x + TILES_PER_BLOCK - 0.5
                and self.base_z - 0.5 <= z < self.base_z + TILES_PER_BLOCK - 0.5)

    def extent(self) -> str:
        return f'x {self.base_x}..{self.base_x + TILES_PER_BLOCK - 1}, z {self.base_z}..{self.base_z + TILES_PER_BLOCK - 1}'


class MapContext:
    """Reads how map headers, matrices, areas and land data fit together."""

    def __init__(self, root: Path):
        self.root = root
        self._headers = None
        self._matrices = {}

    def headers(self) -> dict[str, dict[str, str]]:
        if self._headers is None:
            text = (self.root / MAP_HEADERS).read_text(encoding='utf-8')
            self._headers = {}
            for name, body in re.findall(r'\[(MAP_HEADER_\w+)\]\s*=\s*\{(.*?)\n    \}', text, re.S):
                self._headers[name] = dict(re.findall(r'\.(\w+)\s*=\s*(\w+)', body))
        return self._headers

    def header(self, header: str) -> dict[str, str]:
        fields = self.headers().get(header)
        if fields is None:
            raise MapPropError([f'no {header} in {MAP_HEADERS.as_posix()}'])
        return fields

    def matrix(self, name: str) -> dict:
        if name not in self._matrices:
            self._matrices[name] = json.loads((self.root / MATRICES / f'{name}.json').read_text(encoding='utf-8'))
        return self._matrices[name]

    def blocks(self, header: str) -> list[Block]:
        matrix = self.matrix(self.header(header)['mapMatrixID'])
        blocks = []
        for row, maps in enumerate(matrix['maps']):
            for col, land_data in enumerate(maps):
                if land_data == NO_LAND_DATA:
                    continue
                if matrix['headers'] and matrix['headers'][row][col] != header:
                    continue
                blocks.append(Block(land_data.removeprefix('MAP_'), col * TILES_PER_BLOCK, row * TILES_PER_BLOCK))
        return blocks

    def block_at(self, header: str, x: float, z: float) -> Block:
        blocks = self.blocks(header)
        for block in blocks:
            if block.contains(x, z):
                return block
        extents = '; '.join(block.extent() for block in blocks) or 'nothing'
        raise MapPropError([f'tile ({format_number(x)}, {format_number(z)}) is not in a block of {header}; its blocks cover {extents}'])

    def block_named(self, header: str, land_data: str) -> Block:
        for block in self.blocks(header):
            if block.land_data == land_data:
                return block
        raise MapPropError([f'map_data_{land_data} is not a block of {header}'])

    def land_path(self, block: Block) -> Path:
        return self.root / LAND_DATA / f'{block.name}.bin'

    def read_block(self, block: Block) -> LandData:
        return read_land_data(self.land_path(block).read_bytes())

    def model_names(self) -> list[str]:
        return (self.root / MODELS_ORDER).read_text(encoding='utf-8').split()

    def model_set(self, header: str) -> tuple[str, str, list[str]]:
        area = self.header(header)['areaDataArchiveID']
        model_set = json.loads((self.root / AREA_DATA / f'{area}.json').read_text(encoding='utf-8'))['mapPropSet']
        models = json.loads((self.root / MODEL_SETS / f'{model_set}.json').read_text(encoding='utf-8'))['mapPropModels']
        return area, model_set, models

    def sharing(self, header: str, block: Block) -> list[str]:
        """Other places that use the same land data file."""
        wanted = f'MAP_{block.land_data}'
        users = []
        for matrix_path in sorted((self.root / MATRICES).glob('*.json')):
            matrix = self.matrix(matrix_path.stem)
            for row, maps in enumerate(matrix['maps']):
                for col, land_data in enumerate(maps):
                    if land_data != wanted:
                        continue
                    if matrix['headers']:
                        users.append(matrix['headers'][row][col])
                    else:
                        users += [name for name, fields in self.headers().items() if fields.get('mapMatrixID') == matrix_path.stem]
        return sorted(set(users) - {header})


@dataclass
class Change:
    path: Path
    content: bytes
    summary: str
    prop_id: str = ''
    warnings: list[str] = field(default_factory=list)

    def apply(self):
        self.path.write_bytes(self.content)


class PropRow(NamedTuple):
    prop_id: str
    model: str
    x: float
    y: float
    z: float
    scale: float


def resolve_model(maps: MapContext, model: str) -> int:
    names = maps.model_names()
    file_name = model if model.endswith('.nsbmd') else re.sub(r'_nsbmd$', '', model) + '.nsbmd'
    if file_name not in names:
        raise MapPropError([f'no model {model!r} in map_prop_models.order'])
    return names.index(file_name)


def parse_prop_id(prop_id: str) -> tuple[str, int]:
    match = re.fullmatch(r'(\d+):(\d+)', prop_id)
    if not match:
        raise MapPropError([f'prop id {prop_id!r} must look like 000:3 (land data, then index), as `list` prints it'])
    return match.group(1), int(match.group(2))


def sharing_warnings(maps: MapContext, header: str, block: Block) -> list[str]:
    others = maps.sharing(header, block)
    if not others:
        return []
    return [f'{block.name} is shared, so this also changes {len(others)} other map(s): {", ".join(others)}']


def list_props(maps: MapContext, header: str) -> list[PropRow]:
    names = maps.model_names()
    rows = []
    for block in maps.blocks(header):
        for index, prop in enumerate(maps.read_block(block).props):
            model = names[prop.model_id] if prop.model_id < len(names) else f'model {prop.model_id}'
            rows.append(PropRow(
                f'{block.land_data}:{index}', model,
                offset_to_tile(prop.position[0], block.base_x),
                prop.position[1] / TILE,
                offset_to_tile(prop.position[2], block.base_z),
                prop.scale[0] / FX32_ONE,
            ))
    return rows


def resolve_height(land: LandData, x_offset: int, z_offset: int, y: float | None) -> tuple[int, str]:
    if y is not None:
        return round(y * TILE), 'given'
    heights = ground_heights(land.bdhc, x_offset, z_offset)
    if len(heights) == 1:
        return heights[0], 'ground'
    if not heights:
        raise MapPropError(['there is no BDHC ground at that point; pass --y'])
    options = ', '.join(format_number(h / TILE) for h in heights)
    raise MapPropError([f'the BDHC has several heights at that point ({options}); pass --y with the one you want'])


def add_prop(maps: MapContext, header: str, model: str, x: float, z: float, y: float | None = None, scale: float = 1.0) -> Change:
    maps.header(header)
    errors = []
    model_id = None
    try:
        model_id = resolve_model(maps, model)
    except MapPropError as error:
        errors += error.errors

    if model_id is not None:
        area, model_set, models = maps.model_set(header)
        model_name = maps.model_names()[model_id]
        if model_name.replace('.', '_') not in models:
            set_id = model_set.removeprefix('prop_model_set_')
            errors.append(f'{model_name} is not in {model_set}, the model set of {area}; the game would draw the '
                          f'dummy box. Add it with new_prop.py --model-set {set_id}, or to {model_set}.json and its texture set')

    try:
        block = maps.block_at(header, x, z)
    except MapPropError as error:
        raise MapPropError(errors + error.errors)

    land = maps.read_block(block)
    if len(land.props) >= MAX_LOADED_MAP_PROPS:
        errors.append(f'{block.name} already has {len(land.props)} props, the most a block can load (MAX_LOADED_MAP_PROPS)')
    if errors:
        raise MapPropError(errors)

    x_offset, z_offset = tile_to_offset(x, block.base_x), tile_to_offset(z, block.base_z)
    y_offset, height_source = resolve_height(land, x_offset, z_offset, y)
    fx_scale = round(scale * FX32_ONE)
    land.props.append(MapPropRecord(model_id, (x_offset, y_offset, z_offset), (0, 0, 0), (fx_scale,) * 3, (0, 0)))

    prop_id = f'{block.land_data}:{len(land.props) - 1}'
    summary = (f'add {prop_id} {maps.model_names()[model_id]} at x {format_number(x)}, '
               f'y {format_number(y_offset / TILE)} ({height_source}), z {format_number(z)}, scale {format_number(scale)}')
    return Change(maps.land_path(block), write_land_data(land), summary, prop_id, sharing_warnings(maps, header, block))


def find_prop(maps: MapContext, header: str, prop_id: str) -> tuple[Block, LandData, int]:
    maps.header(header)
    land_data, index = parse_prop_id(prop_id)
    block = maps.block_named(header, land_data)
    land = maps.read_block(block)
    if index >= len(land.props):
        last = f'{land_data}:0 to {land_data}:{len(land.props) - 1}' if land.props else 'none'
        raise MapPropError([f'no prop {prop_id}; {block.name} has props {last}'])
    return block, land, index


def move_prop(maps: MapContext, header: str, prop_id: str, x: float | None = None, z: float | None = None,
              y: float | None = None, scale: float | None = None) -> Change:
    block, land, index = find_prop(maps, header, prop_id)
    prop = land.props[index]
    position = list(prop.position)

    new_x = offset_to_tile(position[0], block.base_x) if x is None else x
    new_z = offset_to_tile(position[2], block.base_z) if z is None else z
    if not block.contains(new_x, new_z):
        raise MapPropError([f'tile ({format_number(new_x)}, {format_number(new_z)}) is outside {block.name} ({block.extent()}); '
                            'remove the prop and add it in the other block'])

    position[0] = tile_to_offset(new_x, block.base_x)
    position[2] = tile_to_offset(new_z, block.base_z)
    if y is not None:
        position[1] = round(y * TILE)
    new_scale = prop.scale if scale is None else (round(scale * FX32_ONE),) * 3
    land.props[index] = prop._replace(position=tuple(position), scale=new_scale)

    summary = (f'move {prop_id} to x {format_number(new_x)}, y {format_number(position[1] / TILE)}, '
               f'z {format_number(new_z)}, scale {format_number(new_scale[0] / FX32_ONE)}')
    return Change(maps.land_path(block), write_land_data(land), summary, prop_id, sharing_warnings(maps, header, block))


def remove_prop(maps: MapContext, header: str, prop_id: str) -> Change:
    block, land, index = find_prop(maps, header, prop_id)
    removed = land.props.pop(index)
    model = maps.model_names()[removed.model_id]
    summary = f'remove {prop_id} ({model}); later props in {block.name} move up one index'
    return Change(maps.land_path(block), write_land_data(land), summary, prop_id, sharing_warnings(maps, header, block))


def print_rows(rows: list[PropRow]):
    if not rows:
        print('no props')
        return
    width = max(len(row.model) for row in rows)
    print(f'{"id":7}{"model":{width + 2}}{"x":>9}{"y":>9}{"z":>9}{"scale":>7}')
    for row in rows:
        print(f'{row.prop_id:7}{row.model:{width + 2}}{format_number(row.x):>9}{format_number(row.y):>9}'
              f'{format_number(row.z):>9}{format_number(row.scale):>7}')


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument('--root', type=Path, default=REPO, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest='command', required=True)

    list_parser = commands.add_parser('list', help='list the props on a map')
    list_parser.add_argument('header', help='e.g. MAP_HEADER_TWINLEAF_TOWN')

    add_parser = commands.add_parser('add', help='place a prop')
    add_parser.add_argument('header')
    add_parser.add_argument('model', help='model name, e.g. waterfall or prop_model_022')
    add_parser.add_argument('--x', type=float, required=True, help='world tile X')
    add_parser.add_argument('--z', type=float, required=True, help='world tile Z')
    add_parser.add_argument('--y', type=float, help='height in tiles; default: the BDHC ground')
    add_parser.add_argument('--scale', type=float, default=1.0)

    move_parser = commands.add_parser('move', help='move or rescale a prop')
    move_parser.add_argument('header')
    move_parser.add_argument('prop', help='prop id from `list`, e.g. 000:3')
    move_parser.add_argument('--x', type=float)
    move_parser.add_argument('--z', type=float)
    move_parser.add_argument('--y', type=float)
    move_parser.add_argument('--scale', type=float)

    remove_parser = commands.add_parser('remove', help='remove a prop')
    remove_parser.add_argument('header')
    remove_parser.add_argument('prop')

    for command in (add_parser, move_parser, remove_parser):
        command.add_argument('--dry-run', action='store_true', help='show the change and stop')

    args = parser.parse_args(argv)
    maps = MapContext(args.root)

    try:
        if args.command == 'list':
            print_rows(list_props(maps, args.header))
            return 0
        if args.command == 'add':
            change = add_prop(maps, args.header, args.model, args.x, args.z, args.y, args.scale)
        elif args.command == 'move':
            change = move_prop(maps, args.header, args.prop, args.x, args.z, args.y, args.scale)
        else:
            change = remove_prop(maps, args.header, args.prop)
    except MapPropError as error:
        for message in error.errors:
            print(f'error: {message}', file=sys.stderr)
        return 1

    print(f'{change.summary}\n  in {change.path.relative_to(args.root).as_posix()}')
    for warning in change.warnings:
        print(f'  warning: {warning}')
    if args.dry_run:
        print('\nNothing written (--dry-run).')
        return 0
    change.apply()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
