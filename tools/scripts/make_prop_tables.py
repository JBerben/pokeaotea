#!/usr/bin/env python3
# ABOUTME: Validates and builds the two per-model map prop tables: bm_anime_list.narc and build_model_matshp.dat.
# ABOUTME: Both have one entry per model in map_prop_models.order; the draw lists are derived from the models themselves.

"""
Both tables are indexed by map prop model ID, which is the model's position in
res/field/props/models/map_prop_models.order. Models are named here the way
the model sets name them: file name with the dot replaced, e.g. honey_tree_nsbmd.

Animation lists (arc/bm_anime_list.narc, src/overlay005/map_prop_animation.c)
say which members of the prop animation archive play on each model. One
20-byte member per model, little-endian:

    u8  hasAnimations;           // 1, or 0xFF when the model has none
    u8  flags;                   // bit 0: deferredLoading, bit 1: deferredAddToRenderObj
    u8  isBicycleSlope;
    u8  dummy;
    s32 animeArchiveIDs[4];      // -1 for unused slots; the loader stops at the first -1

Models without animations use the retail placeholder FF FF 00 00 followed by
four -1s. The 0xFF in hasAnimations is the "BUG" noted in
MapPropAnimationManager_LoadPropAnimations; it is kept so the archive stays
identical to retail.

Material/shape draw lists (fielddata/build_model/build_model_matshp.dat,
src/overlay005/map_prop_material_shape.c) let the renderer draw an unanimated
prop one (material, shape) pair at a time, resending a material only when it
changes. Layout:

    u16 locatorCount;            // one per model
    u16 pairCount;
    struct { u16 count; u16 index; } locators[locatorCount];   // index 0xFFFF when count is 0
    struct { u16 materialID; u16 shapeID; } pairs[pairCount];

Animated models get an empty list, which makes the renderer draw the whole
model so its animations apply. Every other model draws each shape its render
commands draw, sorted by material ID (keeping render order within a material).
draw_order_overrides.json can replace that order for a model; retail uses this
for three Twinleaf houses whose door is drawn last.
"""

import argparse
import json
import shutil
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

# include/overlay005/area_data.h: model files are kept in an array indexed by model ID.
MAX_MAP_PROP_MODEL_FILES = 768

ANIMATIONS_PER_MODEL = 4
NO_ANIMATION = -1
HAS_ANIMATIONS = 1
FLAG_DEFERRED_LOADING = 1 << 0
FLAG_DEFERRED_ADD_TO_RENDER_OBJ = 1 << 1
NO_ANIMATIONS_ENTRY = bytes([0xFF, 0xFF, 0, 0]) + struct.pack('<4i', *[NO_ANIMATION] * ANIMATIONS_PER_MODEL)

ANIMATION_LIST_FIELDS = {'animations', 'deferredLoading', 'deferredAddToRenderObj', 'bicycleSlope'}
ANIMATION_LIST_FLAGS = ('deferredLoading', 'deferredAddToRenderObj', 'bicycleSlope')

NO_DRAW_LIST_INDEX = 0xFFFF

NAME_SIZE = 16

# Render command (SBC) lengths in bytes, indexed by opcode, from NNS_G3dSbcCmdLen in
# subprojects/NitroSystem-*/libraries/g3d/src/util.c. 0 means variable length (NODEMIX);
# opcodes missing from the table are invalid.
SBC_COMMAND_LENGTHS = {
    0x00: 1, 0x01: 1, 0x02: 3, 0x03: 2, 0x04: 2, 0x05: 2, 0x06: 4, 0x07: 2,
    0x08: 2, 0x09: 0, 0x0A: 9, 0x0B: 1, 0x0C: 3, 0x0D: 3,
    0x24: 2, 0x26: 5, 0x27: 3, 0x28: 3, 0x29: 0, 0x2B: 1,
    0x44: 2, 0x46: 5, 0x47: 3, 0x48: 3,
    0x66: 6, 0x67: 4, 0x68: 4,
}
SBC_COMMAND_MASK = 0x1F
SBC_RET = 0x01
SBC_MAT = 0x04
SBC_SHP = 0x05
SBC_NODEMIX = 0x09


class ModelDrawInfo(NamedTuple):
    materials: list[str]
    shapes: list[str]
    draws: list[tuple[int, int]]  # (material, shape) in render command order


def archive_name(file_name: str) -> str:
    """The name nitroarc gives a member in its .naix, which is what the model sets use."""
    return file_name.replace('.', '_')


def read_draw_commands(sbc: bytes) -> list[tuple[int, int]]:
    draws = []
    material = None
    pos = 0

    while pos < len(sbc):
        op = sbc[pos]
        length = SBC_COMMAND_LENGTHS.get(op)
        if length is None:
            raise ValueError(f'unknown render command 0x{op:02x} at offset {pos}')
        if length == 0 and (op & SBC_COMMAND_MASK) == SBC_NODEMIX:
            length = 3 + 3 * sbc[pos + 2]

        command = op & SBC_COMMAND_MASK
        if command == SBC_RET:
            return draws
        if command == SBC_MAT:
            material = sbc[pos + 1]
        elif command == SBC_SHP:
            if material is None:
                raise ValueError(f'shape {sbc[pos + 1]} is drawn before any material is set')
            draws.append((material, sbc[pos + 1]))

        pos += length

    raise ValueError('render command list ends without a return command')


def read_dict_names(data: bytes, offset: int) -> list[str]:
    count = data[offset + 1]
    entries = offset + struct.unpack_from('<H', data, offset + 6)[0]
    names_offset = struct.unpack_from('<H', data, entries + 2)[0]
    names = []
    for i in range(count):
        start = entries + names_offset + NAME_SIZE * i
        names.append(data[start:start + NAME_SIZE].rstrip(b'\0').decode('ascii'))
    return names


def read_dict_offsets(data: bytes, offset: int) -> list[int]:
    count = data[offset + 1]
    entries = offset + struct.unpack_from('<H', data, offset + 6)[0]
    unit_size = struct.unpack_from('<H', data, entries)[0]
    return [struct.unpack_from('<I', data, entries + 4 + unit_size * i)[0] for i in range(count)]


def read_model_draw_info(data: bytes) -> ModelDrawInfo:
    """Reads the first model of an NSBMD, which is the one the field engine uses."""
    if data[0:4] != b'BMD0':
        raise ValueError(f'not an NSBMD file: magic is {data[0:4]!r}, expected BMD0')

    mdl0 = struct.unpack_from('<I', data, 0x10)[0]
    if data[mdl0:mdl0 + 4] != b'MDL0':
        raise ValueError(f'NSBMD first block is {data[mdl0:mdl0 + 4]!r}, expected MDL0')

    model_offsets = read_dict_offsets(data, mdl0 + 8)
    if not model_offsets:
        raise ValueError('NSBMD contains no models')

    model = mdl0 + model_offsets[0]
    ofs_sbc, ofs_mat, ofs_shp = struct.unpack_from('<III', data, model + 4)

    return ModelDrawInfo(
        materials=read_dict_names(data, model + ofs_mat + 4),
        shapes=read_dict_names(data, model + ofs_shp),
        draws=read_draw_commands(data[model + ofs_sbc:model + ofs_mat]),
    )


def default_draw_order(draws: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return sorted(draws, key=lambda draw: draw[0])


def encode_animation_list_entry(entry: dict | None, animation_ids: dict[str, int]) -> bytes:
    if entry is None:
        return NO_ANIMATIONS_ENTRY

    flags = 0
    if entry.get('deferredLoading', False):
        flags |= FLAG_DEFERRED_LOADING
    if entry.get('deferredAddToRenderObj', False):
        flags |= FLAG_DEFERRED_ADD_TO_RENDER_OBJ

    ids = [animation_ids[name] for name in entry['animations']]
    ids += [NO_ANIMATION] * (ANIMATIONS_PER_MODEL - len(ids))

    return bytes([HAS_ANIMATIONS, flags, int(entry.get('bicycleSlope', False)), 0]) + struct.pack('<4i', *ids)


def decode_animation_list_entry(data: bytes, animation_names: list[str]) -> dict | None:
    if data == NO_ANIMATIONS_ENTRY:
        return None

    has_animations, flags, is_bicycle_slope, dummy = data[0:4]
    if has_animations != HAS_ANIMATIONS or dummy != 0 or flags & ~(FLAG_DEFERRED_LOADING | FLAG_DEFERRED_ADD_TO_RENDER_OBJ) \
            or is_bicycle_slope not in (0, 1):
        raise ValueError(f'unexpected animation list header {data[0:4].hex()}')

    ids = struct.unpack_from('<4i', data, 4)
    used = ids[:ids.index(NO_ANIMATION)] if NO_ANIMATION in ids else ids
    if any(i != NO_ANIMATION for i in ids[len(used):]):
        raise ValueError(f'animation slots {ids} have a gap; the loader stops at the first -1')

    entry = {'animations': [animation_names[i] for i in used]}
    if flags & FLAG_DEFERRED_LOADING:
        entry['deferredLoading'] = True
    if flags & FLAG_DEFERRED_ADD_TO_RENDER_OBJ:
        entry['deferredAddToRenderObj'] = True
    if is_bicycle_slope:
        entry['bicycleSlope'] = True
    return entry


def encode_material_shape_table(draw_lists: list[list[tuple[int, int]]]) -> bytes:
    locators = bytearray()
    pairs = bytearray()
    pair_count = 0

    for draws in draw_lists:
        locators += struct.pack('<HH', len(draws), pair_count if draws else NO_DRAW_LIST_INDEX)
        for material, shape in draws:
            pairs += struct.pack('<HH', material, shape)
        pair_count += len(draws)

    return struct.pack('<HH', len(draw_lists), pair_count) + locators + pairs


def decode_material_shape_table(data: bytes) -> list[list[tuple[int, int]]]:
    locator_count, pair_count = struct.unpack_from('<HH', data)
    expected_size = 4 + 4 * locator_count + 4 * pair_count
    if len(data) != expected_size:
        raise ValueError(f'table has {locator_count} models and {pair_count} pairs, so expected {expected_size} bytes, got {len(data)}')

    pairs_offset = 4 + 4 * locator_count
    draw_lists = []
    for i in range(locator_count):
        count, index = struct.unpack_from('<HH', data, 4 + 4 * i)
        draw_lists.append([struct.unpack_from('<HH', data, pairs_offset + 4 * (index + j)) for j in range(count)])
    return draw_lists


def override_draws(info: ModelDrawInfo, override: list[dict]) -> list[tuple[int, int]]:
    return [(info.materials.index(d['material']), info.shapes.index(d['shape'])) for d in override]


def build_draw_lists(models: list[str], infos: dict[str, ModelDrawInfo], animation_lists: dict, overrides: dict) -> list[list[tuple[int, int]]]:
    draw_lists = []
    for model in models:
        info = infos[model]
        if model in animation_lists:
            draw_lists.append([])
        elif model in overrides:
            draw_lists.append(override_draws(info, overrides[model]))
        else:
            draw_lists.append(default_draw_order(info.draws))
    return draw_lists


def validate_animation_list(model: str, entry, models: set[str], animations: set[str]) -> list[str]:
    where = f'animation list for {model!r}'
    if model not in models:
        return [f'{where}: no such model in map_prop_models.order']
    if not isinstance(entry, dict):
        return [f'{where}: must be an object with an "animations" list']

    errors = [f'{where}: unknown field {field!r}' for field in entry if field not in ANIMATION_LIST_FIELDS]

    names = entry.get('animations', [])
    if not 1 <= len(names) <= ANIMATIONS_PER_MODEL:
        errors.append(f'{where}: must have 1 to {ANIMATIONS_PER_MODEL} animations, has {len(names)}')
    for name in names:
        if name not in animations:
            errors.append(f'{where}: no such animation {name!r} in prop_animations.order')

    for flag in ANIMATION_LIST_FLAGS:
        if flag in entry and not isinstance(entry[flag], bool):
            errors.append(f'{where}: {flag!r} must be true or false')

    return errors


def describe_draws(info: ModelDrawInfo, draws) -> str:
    return ', '.join(f'{info.materials[m]}/{info.shapes[s]}' for m, s in sorted(draws))


def validate_draw_order(model: str, override, infos: dict, animation_lists: dict) -> list[str]:
    where = f'draw order for {model!r}'
    if model not in infos:
        return [f'{where}: no such model in map_prop_models.order']
    if model in animation_lists:
        return [f'{where}: animated models are drawn whole, so a draw order would be ignored']

    info = infos[model]
    if not isinstance(info, ModelDrawInfo):
        return []  # Already reported as an unreadable model.

    errors = []
    for i, draw in enumerate(override):
        if draw.get('material') not in info.materials:
            errors.append(f"{where}: draw {i} uses material {draw.get('material')!r}, which the model does not have")
        if draw.get('shape') not in info.shapes:
            errors.append(f"{where}: draw {i} uses shape {draw.get('shape')!r}, which the model does not have")
    if errors:
        return errors

    expected = Counter(info.draws)
    given = Counter(override_draws(info, override))
    problems = []
    if expected - given:
        problems.append(f'missing {describe_draws(info, (expected - given).elements())}')
    if given - expected:
        problems.append(f'extra {describe_draws(info, (given - expected).elements())}')
    if problems:
        errors.append(f"{where}: must list each of the model's draws exactly once; {'; '.join(problems)}")
    return errors


def validate(models: list[str], animations: list[str], infos: dict, animation_lists: dict, overrides: dict) -> list[str]:
    errors = []

    if len(models) > MAX_MAP_PROP_MODEL_FILES:
        errors.append(f'{len(models)} models in map_prop_models.order, but the area loader '
                      f'(MAX_MAP_PROP_MODEL_FILES) only has room for {MAX_MAP_PROP_MODEL_FILES}')

    for model in models:
        if isinstance(infos[model], Exception):
            errors.append(f'model {model!r}: {infos[model]}')

    for model, entry in animation_lists.items():
        errors += validate_animation_list(model, entry, set(models), set(animations))

    for model, override in overrides.items():
        errors += validate_draw_order(model, override, infos, animation_lists)

    if not errors:
        pair_count = sum(len(draws) for draws in build_draw_lists(models, infos, animation_lists, overrides))
        if pair_count >= NO_DRAW_LIST_INDEX:
            errors.append(f'{pair_count} material/shape pairs in total; the table indexes them with a u16 and must stay below {NO_DRAW_LIST_INDEX}')

    return errors


def read_order(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def load_inputs(models_order: Path, animations_order: Path, animation_lists_path: Path, draw_order_path: Path, model_paths: list[Path]):
    model_files = read_order(models_order)
    models = [archive_name(name) for name in model_files]
    animations = [archive_name(name) for name in read_order(animations_order)]

    paths = {path.name: path for path in model_paths}
    infos = {}
    for file_name, model in zip(model_files, models):
        if file_name not in paths:
            infos[model] = ValueError(f'{file_name} is not listed in res/field/props/models/meson.build')
            continue
        try:
            infos[model] = read_model_draw_info(paths[file_name].read_bytes())
        except (ValueError, struct.error, IndexError, UnicodeDecodeError) as error:
            infos[model] = error if isinstance(error, ValueError) else ValueError(f'cannot read {file_name}: {error}')

    animation_lists = json.loads(animation_lists_path.read_text(encoding='utf-8'))
    overrides = json.loads(draw_order_path.read_text(encoding='utf-8'))

    return models, animations, infos, animation_lists, overrides


def pack_animation_lists(members: list[bytes], nitroarc: Path, staging: Path, output: Path):
    members_dir = staging / 'members'
    if members_dir.exists():
        shutil.rmtree(members_dir)
    members_dir.mkdir(parents=True)

    names = [f'{i:05}.bin' for i in range(len(members))]
    for name, member in zip(names, members):
        (members_dir / name).write_bytes(member)

    order_file = staging / 'members.order'
    order_file.write_text(''.join(f'{name}\n' for name in names))

    subprocess.run(
        [str(nitroarc), '--create', '--files-from', str(order_file), '--file', str(output), str(members_dir)],
        check=True,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument('--nitroarc', type=Path, required=True)
    parser.add_argument('--staging', type=Path, required=True, help='scratch directory for archive members')
    parser.add_argument('--animation-lists-output', type=Path, required=True)
    parser.add_argument('--material-shapes-output', type=Path, required=True)
    parser.add_argument('--models-order', type=Path, required=True, help='map_prop_models.order')
    parser.add_argument('--animations-order', type=Path, required=True, help='prop_animations.order')
    parser.add_argument('--animation-lists', type=Path, required=True, help='prop_animation_lists.json')
    parser.add_argument('--draw-order', type=Path, required=True, help='draw_order_overrides.json')
    parser.add_argument('models', type=Path, nargs='*', help='every NSBMD in map_prop_models.order')
    args = parser.parse_args(argv)

    models, animations, infos, animation_lists, overrides = load_inputs(
        args.models_order, args.animations_order, args.animation_lists, args.draw_order, args.models)

    errors = validate(models, animations, infos, animation_lists, overrides)
    if errors:
        print('invalid map prop tables:', file=sys.stderr)
        for error in errors:
            print(f'  {error}', file=sys.stderr)
        return 1

    animation_ids = {name: i for i, name in enumerate(animations)}
    members = [encode_animation_list_entry(animation_lists.get(model), animation_ids) for model in models]
    pack_animation_lists(members, args.nitroarc, args.staging, args.animation_lists_output)

    draw_lists = build_draw_lists(models, infos, animation_lists, overrides)
    args.material_shapes_output.write_bytes(encode_material_shape_table(draw_lists))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
