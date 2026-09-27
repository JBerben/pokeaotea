#!/usr/bin/env python3
# ABOUTME: One-off migration that unpacks a prebuilt fldtanime.narc into res/field/texture_animations/.
# ABOUTME: Writes texture_animations.json plus one frames NSBTX per animation, named after its texture.

"""
This is a standalone script for turning the prebuilt field texture animation
archive (data/fldtanime.narc) into the sources that
tools/scripts/make_texture_animations.py packs. Users who have hand-edited
their fldtanime.narc can run it on their copy after merging, then rebuild.

    python3 tools/scripts/migration/texture_animations.py path/to/fldtanime.narc res/field/texture_animations
"""

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import make_texture_animations as mta  # noqa: E402


def read_narc_members(data: bytes) -> list[bytes]:
    fat_size, count = struct.unpack_from('<IH', data, 0x14)
    ranges = [struct.unpack_from('<II', data, 0x1C + 8 * i) for i in range(count)]
    fnt_offset = 0x10 + fat_size
    base = fnt_offset + struct.unpack_from('<I', data, fnt_offset + 4)[0] + 8
    return [data[base + start:base + end] for start, end in ranges]


def frames_file_name(texture: str) -> str:
    return texture.replace('.', '_') + '.nsbtx'


def format_json(animations: list[dict]) -> str:
    # One step per line keeps sequences readable and diffs small.
    blocks = []
    for anim in animations:
        steps = ',\n'.join(f'                {{ "frame": {s["frame"]}, "hold": {s["hold"]} }}' for s in anim['sequence'])
        blocks.append(
            '        {\n'
            f'            "texture": {json.dumps(anim["texture"])},\n'
            f'            "frames": {json.dumps(anim["frames"])},\n'
            '            "sequence": [\n'
            f'{steps}\n'
            '            ]\n'
            '        }'
        )
    return '{\n    "animations": [\n' + ',\n'.join(blocks) + '\n    ]\n}\n'


def main(narc_path: Path, out_dir: Path):
    members = read_narc_members(narc_path.read_bytes())
    animations = mta.decode_table(members[0])

    frames_dir = out_dir / 'frames'
    frames_dir.mkdir(parents=True, exist_ok=True)
    for anim, frames in zip(animations, members[1:], strict=True):
        anim['frames'] = frames_file_name(anim['texture'])
        (frames_dir / anim['frames']).write_bytes(frames)

    ordered = [{'texture': a['texture'], 'frames': a['frames'], 'sequence': a['sequence']} for a in animations]
    (out_dir / 'texture_animations.json').write_text(format_json(ordered), encoding='utf-8')


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
