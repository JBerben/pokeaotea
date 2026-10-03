#!/usr/bin/env python3
# ABOUTME: One-off migration that turns prebuilt bm_anime_list.narc and build_model_matshp.dat into JSON sources.
# ABOUTME: Writes prop_animation_lists.json and draw_order_overrides.json, and refuses unless they rebuild the input exactly.

"""
This is a standalone script for turning the prebuilt map prop animation lists
(arc/bm_anime_list.narc) and material/shape draw lists
(fielddata/build_model/build_model_matshp.dat) into the sources that
tools/scripts/make_prop_tables.py builds. Users who have hand-edited either
file can run it on their copies after merging, then rebuild.

    python3 tools/scripts/migration/prop_tables.py path/to/bm_anime_list.narc path/to/build_model_matshp.dat

Draw lists that match the order derived from the model are dropped; only the
ones that differ are written as overrides.
"""

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import make_prop_tables as mpt  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
PROPS_DIR = REPO / 'res' / 'field' / 'props'
MODELS_DIR = PROPS_DIR / 'models'
ANIMATIONS_DIR = PROPS_DIR / 'animations'


def read_narc_members(data: bytes) -> list[bytes]:
    fat_size, count = struct.unpack_from('<IH', data, 0x14)
    ranges = [struct.unpack_from('<II', data, 0x1C + 8 * i) for i in range(count)]
    fnt_offset = 0x10 + fat_size
    base = fnt_offset + struct.unpack_from('<I', data, fnt_offset + 4)[0] + 8
    return [data[base + start:base + end] for start, end in ranges]


def format_animation_lists(animation_lists: dict) -> str:
    # One model per line keeps the file scannable and diffs small.
    lines = [f'    {json.dumps(model)}: {json.dumps(entry)}' for model, entry in animation_lists.items()]
    return '{\n' + ',\n'.join(lines) + '\n}\n'


def format_draw_orders(overrides: dict) -> str:
    blocks = []
    for model, draws in overrides.items():
        rows = ',\n'.join(f'        {json.dumps(draw)}' for draw in draws)
        blocks.append(f'    {json.dumps(model)}: [\n{rows}\n    ]')
    return '{\n' + ',\n'.join(blocks) + '\n}\n'


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    anime_list_members = read_narc_members(Path(argv[0]).read_bytes())
    retail_draw_lists = mpt.decode_material_shape_table(Path(argv[1]).read_bytes())

    model_files = mpt.read_order(MODELS_DIR / 'map_prop_models.order')
    models = [mpt.archive_name(name) for name in model_files]
    animations = [mpt.archive_name(name) for name in mpt.read_order(ANIMATIONS_DIR / 'prop_animations.order')]
    infos = {model: mpt.read_model_draw_info((MODELS_DIR / name).read_bytes()) for name, model in zip(model_files, models)}

    if not len(anime_list_members) == len(retail_draw_lists) == len(models):
        print(f'expected {len(models)} entries in both files, found {len(anime_list_members)} and {len(retail_draw_lists)}', file=sys.stderr)
        return 1

    animation_lists = {}
    for model, member in zip(models, anime_list_members):
        entry = mpt.decode_animation_list_entry(member, animations)
        if entry is not None:
            animation_lists[model] = entry

    overrides = {}
    for model, draws in zip(models, retail_draw_lists):
        if model in animation_lists or draws == mpt.default_draw_order(infos[model].draws):
            continue
        info = infos[model]
        overrides[model] = [{'material': info.materials[m], 'shape': info.shapes[s]} for m, s in draws]

    errors = mpt.validate(models, animations, infos, animation_lists, overrides)
    if errors:
        print('extracted data does not validate:', file=sys.stderr)
        for error in errors:
            print(f'  {error}', file=sys.stderr)
        return 1

    animation_ids = {name: i for i, name in enumerate(animations)}
    rebuilt_members = [mpt.encode_animation_list_entry(animation_lists.get(model), animation_ids) for model in models]
    rebuilt_draw_lists = mpt.build_draw_lists(models, infos, animation_lists, overrides)
    if rebuilt_members != anime_list_members or rebuilt_draw_lists != retail_draw_lists:
        print('extracted data does not rebuild the input exactly; nothing written', file=sys.stderr)
        return 1

    (ANIMATIONS_DIR / 'prop_animation_lists.json').write_text(format_animation_lists(animation_lists), encoding='utf-8')
    (MODELS_DIR / 'draw_order_overrides.json').write_text(format_draw_orders(overrides), encoding='utf-8')
    print(f'{len(animation_lists)} animated models, {len(overrides)} draw order overrides')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
