#!/usr/bin/env python3
# ABOUTME: Validates res/field/texture_animations and packs it into fldtanime.narc, the field texture animation archive.
# ABOUTME: Member 0 is the animation table; member i+1 is the NSBTX holding the frames for animation i.

"""
The runtime side lives in src/overlay005/texture_resource_manager.c. On map
load, every animation whose texture name exists in the area's map texture set
is bound to that texture; each field tick the texels of the current frame are
copied over it in VRAM. Palettes are never swapped, so frames must be drawn
against the base texture's palette.

Table layout (little-endian):

    u32 count
    struct {
        char name[16];        // zero padded, not necessarily terminated
        u8   steps[18][2];    // {frame, hold}; 0xFF frame ends the list, rest padded with 0xFF
    } animations[count];
"""

import argparse
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

NAME_SIZE = 16
MAX_STEP_SLOTS = 18
MAX_STEPS = MAX_STEP_SLOTS - 1  # one slot is needed for the 0xFF terminator
ENTRY_SIZE = NAME_SIZE + MAX_STEP_SLOTS * 2
END_OF_SEQUENCE = 0xFF

GX_TEXFMT_NONE = 0
GX_TEXFMT_A3I5 = 1
GX_TEXFMT_PLTT4 = 2
GX_TEXFMT_PLTT16 = 3
GX_TEXFMT_PLTT256 = 4
GX_TEXFMT_COMP4x4 = 5
GX_TEXFMT_A5I3 = 6
GX_TEXFMT_DIRECT = 7

# Formats whose size CalcTextureDataSize (src/billboard_vram_transfer.c) knows how to compute.
SUPPORTED_FORMATS = {
    GX_TEXFMT_A3I5: 'A3I5',
    GX_TEXFMT_PLTT4: 'PLTT4',
    GX_TEXFMT_PLTT16: 'PLTT16',
    GX_TEXFMT_PLTT256: 'PLTT256',
    GX_TEXFMT_A5I3: 'A5I3',
}


class TextureInfo(NamedTuple):
    name: str
    format: int
    width: int
    height: int


def read_nsbtx_textures(data: bytes) -> list[TextureInfo]:
    if data[0:4] != b'BTX0':
        raise ValueError(f'not an NSBTX file: magic is {data[0:4]!r}, expected BTX0')

    tex0 = data[struct.unpack_from('<I', data, 0x10)[0]:]
    if tex0[0:4] != b'TEX0':
        raise ValueError(f'NSBTX first block is {tex0[0:4]!r}, expected TEX0')

    dict_offset = struct.unpack_from('<H', tex0, 0x0E)[0]
    count = tex0[dict_offset + 1]
    entries_offset = dict_offset + struct.unpack_from('<H', tex0, dict_offset + 6)[0]
    unit_size, names_offset = struct.unpack_from('<HH', tex0, entries_offset)

    textures = []
    for i in range(count):
        param = struct.unpack_from('<I', tex0, entries_offset + 4 + unit_size * i)[0]
        name_start = entries_offset + names_offset + NAME_SIZE * i
        name = tex0[name_start:name_start + NAME_SIZE].rstrip(b'\0').decode('ascii')
        textures.append(TextureInfo(
            name=name,
            format=(param >> 26) & 7,
            width=8 << ((param >> 20) & 7),
            height=8 << ((param >> 23) & 7),
        ))

    return textures


def encode_table(animations: list[dict]) -> bytes:
    table = bytearray(len(animations).to_bytes(4, 'little'))

    for anim in animations:
        table += anim['texture'].encode('ascii').ljust(NAME_SIZE, b'\0')
        steps = bytearray()
        for step in anim['sequence']:
            steps += bytes([step['frame'], step['hold']])
        table += steps.ljust(MAX_STEP_SLOTS * 2, bytes([END_OF_SEQUENCE]))

    return bytes(table)


def decode_table(data: bytes) -> list[dict]:
    count = struct.unpack_from('<I', data)[0]
    expected_size = 4 + count * ENTRY_SIZE
    if len(data) != expected_size:
        raise ValueError(f'table has {count} animations, so expected {expected_size} bytes, got {len(data)}')

    animations = []
    for i in range(count):
        entry = data[4 + i * ENTRY_SIZE:4 + (i + 1) * ENTRY_SIZE]
        sequence = []
        for slot in range(MAX_STEP_SLOTS):
            frame, hold = entry[NAME_SIZE + slot * 2:NAME_SIZE + slot * 2 + 2]
            if frame == END_OF_SEQUENCE:
                break
            sequence.append({'frame': frame, 'hold': hold})
        animations.append({
            'texture': entry[:NAME_SIZE].rstrip(b'\0').decode('ascii'),
            'sequence': sequence,
        })

    return animations


def validate(animations: list[dict], frame_textures: dict[str, list[TextureInfo]]) -> list[str]:
    errors = []
    first_use = {}

    for i, anim in enumerate(animations):
        name = anim['texture']
        where = f'animation {i} {name!r}'

        if not (1 <= len(name) <= NAME_SIZE and name.isascii()):
            errors.append(f'{where}: texture name must be 1-{NAME_SIZE} ASCII characters')

        if name in first_use:
            errors.append(f'{where}: texture name is already used by animation {first_use[name]}')
        else:
            first_use[name] = i

        frames_file = anim['frames']
        textures = frame_textures.get(frames_file)
        if textures is None:
            errors.append(f"{where}: frames file {frames_file} is not listed in res/field/texture_animations/meson.build")
        else:
            shapes = {(t.format, t.width, t.height) for t in textures}
            if len(shapes) > 1:
                errors.append(f'{where}: all textures in {frames_file} must have the same format and size, found {sorted(shapes)}')
            unsupported = {t.format for t in textures if t.format not in SUPPORTED_FORMATS}
            if unsupported:
                errors.append(f'{where}: {frames_file} uses unsupported texture format(s) {sorted(unsupported)}; '
                              f'use one of {", ".join(SUPPORTED_FORMATS.values())}')

        sequence = anim['sequence']
        if not 1 <= len(sequence) <= MAX_STEPS:
            errors.append(f'{where}: sequence must have 1 to {MAX_STEPS} steps, has {len(sequence)}')

        for s, step in enumerate(sequence):
            if textures is not None and not 0 <= step['frame'] < len(textures):
                errors.append(f"{where}: step {s} uses frame {step['frame']}, but {frames_file} only has {len(textures)} textures")
            if not 0 <= step['hold'] <= 0xFF:
                errors.append(f"{where}: step {s} hold {step['hold']} is outside 0-255")

    used = {anim['frames'] for anim in animations}
    for frames_file in frame_textures:
        if frames_file not in used:
            errors.append(f'frames file {frames_file} is not used by any animation')

    return errors


def pack(animations: list[dict], frame_paths: dict[str, Path], nitroarc: Path, staging: Path, output: Path):
    members_dir = staging / 'members'
    if members_dir.exists():
        shutil.rmtree(members_dir)
    members_dir.mkdir(parents=True)

    member_names = ['00000.bin']
    (members_dir / member_names[0]).write_bytes(encode_table(animations))
    for i, anim in enumerate(animations, start=1):
        member_names.append(f'{i:05}.nsbtx')
        shutil.copyfile(frame_paths[anim['frames']], members_dir / member_names[-1])

    order_file = staging / 'members.order'
    order_file.write_text(''.join(f'{name}\n' for name in member_names))

    subprocess.run(
        [str(nitroarc), '--create', '--files-from', str(order_file), '--file', str(output), str(members_dir)],
        check=True,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument('--nitroarc', type=Path, required=True)
    parser.add_argument('--staging', type=Path, required=True, help='scratch directory for archive members')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('animations', type=Path, help='texture_animations.json')
    parser.add_argument('frames', type=Path, nargs='*', help='every frames NSBTX the JSON refers to')
    args = parser.parse_args(argv)

    animations = json.loads(args.animations.read_text(encoding='utf-8'))['animations']
    frame_paths = {path.name: path for path in args.frames}
    frame_textures = {name: read_nsbtx_textures(path.read_bytes()) for name, path in frame_paths.items()}

    errors = validate(animations, frame_textures)
    if errors:
        print(f'{args.animations}: invalid texture animations:', file=sys.stderr)
        for error in errors:
            print(f'  {error}', file=sys.stderr)
        return 1

    pack(animations, frame_paths, args.nitroarc, args.staging, args.output)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
