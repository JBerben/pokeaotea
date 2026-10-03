# ABOUTME: Command line for the renderer: `mapedit-render map MAP_HEADER_X -o out.png` and `mapedit-render model x.nsbmd`.
# ABOUTME: --json prints what was rendered (and any textures the area is missing) for scripts and the AI.

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

from .. import maps
from . import map_render, scene


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='mapedit-render', description='Render maps and models to PNG.')
    parser.add_argument('--root', type=Path, default=maps.REPO, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest='command', required=True)

    map_parser = commands.add_parser('map', help="render a map's blocks, props included")
    map_parser.add_argument('header', help='e.g. MAP_HEADER_TWINLEAF_TOWN')
    map_parser.add_argument('--block', action='append', help='only this land data block (e.g. 005); repeatable')
    map_parser.add_argument('--no-props', action='store_true')
    map_parser.add_argument('--markers', action='store_true', help='dot events on the top view')

    model_parser = commands.add_parser('model', help='render one model')
    model_parser.add_argument('model', type=Path, help='an .nsbmd')
    model_parser.add_argument('--textures', type=Path, action='append', default=[], help='an .nsbtx; repeatable')
    model_parser.add_argument('--area-set', help='use this prop texture set, e.g. 000')
    model_parser.add_argument('--no-embedded', action='store_true', help="ignore the model's own textures, as the game does")

    for command in (map_parser, model_parser):
        command.add_argument('-o', '--output', type=Path, required=True, help='PNG to write')
        command.add_argument('--view', choices=('top', 'angled'), default='angled' if command is model_parser else 'top')
        command.add_argument('--size', type=int, default=1024, help='longest side in pixels')
        command.add_argument('--json', action='store_true', help='machine-readable report')

    args = parser.parse_args(argv)

    def fail(message: str) -> int:
        if args.json:
            print(json.dumps({'errors': [message]}))
        else:
            print(f'error: {message}', file=sys.stderr)
        return 1

    try:
        if args.command == 'map':
            result = map_render.render_map(maps.MapRepository(args.root), args.header, view=args.view, size=args.size,
                                           props=not args.no_props, markers=args.markers, blocks=args.block)
            image, report = result.image, {'blocks': result.blocks, 'props': result.props,
                                           'missing_textures': result.missing_textures}
        else:
            texture_sets = [path.read_bytes() for path in args.textures]
            if args.area_set:
                name = f'prop_texture_set_{int(args.area_set):03}.nsbtx'
                texture_sets.append((args.root / map_render.PROP_TEXTURE_SETS / name).read_bytes())
            library_probe = scene.TextureLibrary(*texture_sets)
            image = scene.render_model(args.model.read_bytes(), *texture_sets, view=args.view, size=args.size,
                                       use_embedded=not args.no_embedded, library=library_probe)
            report = {'missing_textures': sorted(library_probe.missing)}
    except (maps.map_props.MapPropError, KeyError, ValueError, FileNotFoundError) as error:
        message = '; '.join(error.errors) if isinstance(error, maps.map_props.MapPropError) else str(error)
        return fail(message)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(args.output)
    report = {'output': str(args.output), 'width': image.shape[1], 'height': image.shape[0], **report}
    print(json.dumps(report) if args.json else f"wrote {args.output} ({image.shape[1]}x{image.shape[0]})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
