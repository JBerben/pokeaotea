#!/usr/bin/env python3
# ABOUTME: Registers a custom map prop in one step: model, animations, model sets, and the textures in those areas' texture sets.
# ABOUTME: Collects every change and every problem first; nothing is written unless the whole prop can be added.

"""Register a custom map prop (model + animations + textures) in one step.

    python3 tools/scripts/new_prop.py waterfall --model waterfall.nsbmd \\
        --animation waterfall.nsbta --model-set 012 --dry-run

Adding a prop by hand means touching up to nine places, and missing the
texture step fails silently: the game binds prop textures from the area's
prop texture set by name, so a prop whose textures are not there renders
white. This does all of it:

    res/field/props/models/<name>.nsbmd                       created
    res/field/props/models/meson.build, map_prop_models.order  registered
    res/field/props/animations/<name>_<i>.<ext>               created, one per --animation
    res/field/props/animations/meson.build, prop_animations.order   registered
    res/field/props/animations/prop_animation_lists.json      entry for the model
    res/field/props/model_sets/prop_model_set_NNN.json        model added, per --model-set
    res/field/props/texture_sets/prop_texture_set_NNN.nsbtx   textures appended, per --model-set

Textures come from --textures, or else from the textures embedded in the
model. They are appended after the existing ones, which are left untouched;
a texture or palette whose name is already in the set is shared if identical
and an error otherwise. Animations are numbered in the order given, which is
the animation index field code and scripts use.

The draw list (build_model_matshp.dat) needs no edit: it is derived from the
model at build time. Placing the prop on a map is a separate step.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_prop_tables as mpt  # noqa: E402
import nitro_textures as nt  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PROPS = Path('res/field/props')
MODELS = PROPS / 'models'
ANIMATIONS = PROPS / 'animations'
MODEL_SETS = PROPS / 'model_sets'
TEXTURE_SETS = PROPS / 'texture_sets'
AREA_DATA = Path('res/field/area_data')

MODELS_MESON_ANCHOR = 'map_prop_model_srcs = files('
ANIMATIONS_MESON_ANCHOR = 'prop_animation_files = copy_gen.process(files('

ANIMATION_EXTENSIONS = {
    b'BCA0': 'nsbca',
    b'BMA0': 'nsbma',
    b'BTA0': 'nsbta',
    b'BTP0': 'nsbtp',
    b'BVA0': 'nsbva',
}


class PropError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__('\n'.join(errors))
        self.errors = errors


@dataclass
class PropRequest:
    name: str
    model: Path
    textures: Path | None
    animations: list[Path]
    deferred_loading: bool
    deferred_add_to_render_obj: bool
    bicycle_slope: bool
    model_sets: list[str]


@dataclass
class Plan:
    """Every change, collected before anything is written."""

    root: Path
    creates: list = field(default_factory=list)   # (relative path, bytes)
    edits: list = field(default_factory=list)     # (relative path, description, bytes)
    notes: list = field(default_factory=list)

    def create(self, path: Path, content: bytes):
        self.creates.append((path, content))

    def edit(self, path: Path, description: str, content: bytes):
        self.edits.append((path, description, content))

    def describe(self) -> str:
        lines = [f'  create  {path.as_posix()}' for path, _ in self.creates]
        lines += [f'  edit    {path.as_posix()}  ({description})' for path, description, _ in self.edits]
        return '\n'.join(lines)

    def apply(self):
        for path, content in self.creates + [(path, content) for path, _, content in self.edits]:
            (self.root / path).write_bytes(content)


def read_text(path: Path) -> str:
    with open(path, encoding='utf-8', newline='') as handle:
        return handle.read()


def append_to_meson_list(text: str, anchor: str, entry: str) -> str:
    """Adds `    'entry',` as the last item of the files() list opened by `anchor`."""
    start = text.index(anchor)
    close = text.index('\n)', start)
    before = text[:close]
    if not before.rstrip().endswith((',', '(')):
        before = before.rstrip() + ','
    return before + f"\n    '{entry}'," + text[close:]


def append_line(text: str, line: str) -> str:
    if text and not text.endswith('\n'):
        text += '\n'
    return text + line + '\n'


def normalise_set_id(set_id: str) -> str:
    digits = set_id.removeprefix('prop_model_set_')
    return f'{int(digits):03}' if digits.isdigit() else set_id


def areas_using(root: Path, model_set: str) -> list[str]:
    areas = []
    for path in sorted((root / AREA_DATA).glob('area_data_*.json')):
        if json.loads(path.read_text(encoding='utf-8')).get('mapPropSet') == model_set:
            areas.append(path.stem)
    return areas


def build_plan(root: Path, request: PropRequest) -> Plan:
    errors = []
    plan = Plan(root)
    name = request.name
    model_file = f'{name}.nsbmd'
    model_name = mpt.archive_name(model_file)

    if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
        errors.append(f'name {name!r} must be lower snake_case, e.g. route_201_waterfall')

    # Model
    model_order = read_text(root / MODELS / 'map_prop_models.order')
    if model_file in model_order.split() or (root / MODELS / model_file).exists():
        errors.append(f'model {model_file!r} already exists in map_prop_models.order')

    model_data = request.model.read_bytes()
    model_readable = True
    try:
        mpt.read_model_draw_info(model_data)
        texture_refs, palette_refs = mpt.read_model_texture_references(model_data)
    except (ValueError, IndexError) as error:
        errors.append(f'{request.model.name}: {error}')
        model_readable = False

    # Animations
    if len(request.animations) > mpt.ANIMATIONS_PER_MODEL:
        errors.append(f'a prop has at most {mpt.ANIMATIONS_PER_MODEL} animations, got {len(request.animations)}')
    flags = {'deferredLoading': request.deferred_loading,
             'deferredAddToRenderObj': request.deferred_add_to_render_obj,
             'bicycleSlope': request.bicycle_slope}
    if any(flags.values()) and not request.animations:
        errors.append('animation flags (--deferred-loading, --deferred-add-to-render-obj, --bicycle-slope) need at least one --animation')

    animation_files = []
    for index, path in enumerate(request.animations):
        data = path.read_bytes()
        extension = ANIMATION_EXTENSIONS.get(data[0:4])
        if extension is None:
            errors.append(f'{path.name}: not a prop animation (magic {data[0:4]!r}; expected one of {", ".join(m.decode() for m in ANIMATION_EXTENSIONS)})')
            continue
        animation_files.append((f'{name}_{index}.{extension}', data))

    # Textures
    textures, palettes = [], []
    if model_readable:
        if request.textures is not None:
            source_name = request.textures.name
            source = nt.read_texture_set(request.textures.read_bytes())
        elif nt.find_tex0(model_data) is not None:
            source_name = request.model.name
            source = nt.read_texture_set(model_data)
        else:
            source = None
            if texture_refs or palette_refs:
                errors.append(f'{request.model.name} has no embedded textures; pass --textures with an NSBTX holding: '
                              f'{", ".join(texture_refs + palette_refs)}')
        if source is not None:
            textures, palettes = source.textures(), source.palettes()
            have_textures = {t.name for t in textures}
            have_palettes = {p.name for p in palettes}
            for ref in texture_refs:
                if ref not in have_textures:
                    errors.append(f'{source_name} is missing texture {ref!r}, which {request.model.name} binds')
            for ref in palette_refs:
                if ref not in have_palettes:
                    errors.append(f'{source_name} is missing palette {ref!r}, which {request.model.name} binds')

    # Model sets and their texture sets
    if not request.model_sets:
        errors.append('choose at least one model set (--model-set) so the prop can be placed')

    model_set_order = read_text(root / MODEL_SETS / 'prop_model_sets.order').split()
    texture_set_order = [Path(line).stem for line in read_text(root / TEXTURE_SETS / 'prop_texture_sets.order').split()]
    set_edits = []
    for raw_id in request.model_sets:
        set_id = normalise_set_id(raw_id)
        model_set = f'prop_model_set_{set_id}'
        if model_set not in model_set_order:
            errors.append(f'model set {raw_id!r}: no {model_set} in prop_model_sets.order')
            continue

        model_set_path = MODEL_SETS / f'{model_set}.json'
        model_set_data = json.loads(read_text(root / model_set_path))
        if model_name in model_set_data['mapPropModels']:
            errors.append(f'model set {set_id!r}: already contains {model_name}')
            continue
        model_set_data['mapPropModels'].append(model_name)

        texture_set = texture_set_order[model_set_order.index(model_set)]
        texture_set_path = TEXTURE_SETS / f'{texture_set}.nsbtx'
        try:
            merged, skipped = nt.append_textures(nt.read_texture_set((root / texture_set_path).read_bytes()), textures, palettes)
        except ValueError as error:
            errors.append(f'texture set {set_id}: {error}')
            continue

        added = len(textures) + len(palettes) - len(skipped)
        set_edits.append((model_set_path, f'add {model_name}', (json.dumps(model_set_data, indent=4) + '\n').encode('utf-8')))
        set_edits.append((texture_set_path, f'{added} textures/palettes appended, {len(skipped)} already present',
                          nt.write_nsbtx(merged)))
        areas = areas_using(root, model_set)
        plan.notes.append(f'{model_set} is used by {", ".join(areas) if areas else "no area data yet"}')

    if errors:
        raise PropError(errors)

    plan.create(MODELS / model_file, model_data)
    plan.edit(MODELS / 'meson.build', f'add {model_file}',
              append_to_meson_list(read_text(root / MODELS / 'meson.build'), MODELS_MESON_ANCHOR, model_file).encode('utf-8'))
    plan.edit(MODELS / 'map_prop_models.order', f'{model_file} is model {len(model_order.split())}',
              append_line(model_order, model_file).encode('utf-8'))

    if animation_files:
        meson = read_text(root / ANIMATIONS / 'meson.build')
        order = read_text(root / ANIMATIONS / 'prop_animations.order')
        for file_name, data in animation_files:
            plan.create(ANIMATIONS / file_name, data)
            meson = append_to_meson_list(meson, ANIMATIONS_MESON_ANCHOR, file_name)
            order = append_line(order, file_name)
        names = ', '.join(file_name for file_name, _ in animation_files)
        plan.edit(ANIMATIONS / 'meson.build', f'add {names}', meson.encode('utf-8'))
        plan.edit(ANIMATIONS / 'prop_animations.order', f'add {names}', order.encode('utf-8'))

        lists = json.loads(read_text(root / ANIMATIONS / 'prop_animation_lists.json'))
        entry = {'animations': [mpt.archive_name(file_name) for file_name, _ in animation_files]}
        entry.update({flag: True for flag, value in flags.items() if value})
        lists[model_name] = entry
        plan.edit(ANIMATIONS / 'prop_animation_lists.json', f'animations for {model_name}',
                  mpt.format_animation_lists(lists).encode('utf-8'))

    for path, description, content in set_edits:
        plan.edit(path, description, content)

    return plan


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument('name', help='lower snake_case prop name; the model becomes <name>.nsbmd')
    parser.add_argument('--model', type=Path, required=True, help='the NSBMD to add')
    parser.add_argument('--textures', type=Path, help='NSBTX with the textures; default: the ones embedded in the model')
    parser.add_argument('--animation', type=Path, action='append', default=[], dest='animations',
                        help='an NSBTA/NSBTP/NSBCA/NSBMA/NSBVA; repeat for up to 4, in animation index order')
    parser.add_argument('--model-set', action='append', default=[], dest='model_sets',
                        help='prop model set to add it to, e.g. 012; repeat for several areas')
    parser.add_argument('--deferred-loading', action='store_true', help='load the animations on demand (like doors)')
    parser.add_argument('--deferred-add-to-render-obj', action='store_true',
                        help='load the animations but let field code start them (like the honey tree)')
    parser.add_argument('--bicycle-slope', action='store_true', help='load the animation paused, to play once')
    parser.add_argument('--dry-run', action='store_true', help='show what would change and stop')
    parser.add_argument('--root', type=Path, default=REPO, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    request = PropRequest(args.name, args.model, args.textures, args.animations, args.deferred_loading,
                          args.deferred_add_to_render_obj, args.bicycle_slope, args.model_sets)
    try:
        plan = build_plan(args.root, request)
    except PropError as error:
        print(f'cannot add prop {args.name!r}:', file=sys.stderr)
        for message in error.errors:
            print(f'  {message}', file=sys.stderr)
        return 1

    print(f"{'Would apply' if args.dry_run else 'Applying'} for '{args.name}':\n")
    print(plan.describe())
    for note in plan.notes:
        print(f'\n  note: {note}')

    if args.dry_run:
        print('\nNothing written (--dry-run).')
        return 0

    plan.apply()
    print('\nDone. Next:')
    print('  - build with: make rom (make_prop_tables.py validates the prop tables)')
    print(f'  - place {args.name}_nsbmd on a map in one of those areas (mapProps in res/field/maps/data/map_data_NNN.bin)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
