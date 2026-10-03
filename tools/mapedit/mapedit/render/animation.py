# ABOUTME: Texture animations for the renderer: NSBTA (texture matrix tracks), NSBTP (texture swaps) and fldtanime.
# ABOUTME: Track sampling and the texture matrix follow NitroSystem's nsbta.c and cgtool/maya.c.

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np

from .textures import nt

FX = 4096.0
ELEM_FX16, ELEM_CONST = 0x10000000, 0x20000000
STEP_MASK, STEP_2 = 0xC0000000, 0x40000000
LAST_INTERP_MASK = 0x0000FFFF


def read_dict(data: bytes, offset: int) -> tuple[list[str], list[bytes]]:
    count = data[offset + 1]
    entries = offset + struct.unpack_from('<H', data, offset + 6)[0]
    unit_size, names_offset = struct.unpack_from('<HH', data, entries)
    units = [data[entries + 4 + unit_size * i:entries + 4 + unit_size * (i + 1)] for i in range(count)]
    names = [data[entries + names_offset + 16 * i:entries + names_offset + 16 * (i + 1)].rstrip(b'\0').decode('ascii')
             for i in range(count)]
    return names, units


def first_animation(data: bytes, magic: bytes) -> int:
    """Offset of the first animation in an NSBTA/NSBTP file's animation set."""
    block = struct.unpack_from('<I', data, 0x10)[0]
    if data[block:block + 4] != magic:
        raise ValueError(f'expected a {magic.decode()} block, found {data[block:block + 4]!r}')
    _, units = read_dict(data, block + 8)
    return block + struct.unpack('<I', units[0])[0]


class Srt(NamedTuple):
    scale_s: float
    scale_t: float
    sin: float
    cos: float
    trans_s: float
    trans_t: float


def sample(data: bytes, anim: int, info: int, value: int, frame: int, element_size: int) -> list[int]:
    """Raw track samples at a frame, following GetTexSRTAnmVectorVal_ (element_size 2 or 4; 4 also covers sin/cos)."""
    if info & ELEM_CONST:
        return [value]
    head = anim + value
    fmt = '<h' if element_size == 2 else '<i'

    def at(index):
        return struct.unpack_from(fmt, data, head + index * element_size)[0]

    if not info & STEP_MASK:
        return [at(frame)]
    last = info & LAST_INTERP_MASK
    if info & STEP_2:
        if frame & 1:
            if frame > last:
                return [at((last >> 1) + 1)]
            return [at(frame >> 1), at((frame >> 1) + 1), 'half']
        return [at(frame >> 1)]
    if frame & 3:
        if frame > last:
            return [at((last >> 2) + (frame & 3))]
        if frame & 1:
            if frame & 2:
                return [at((frame >> 2) + 1), at(frame >> 2), 'quarter']
            return [at(frame >> 2), at((frame >> 2) + 1), 'quarter']
        return [at(frame >> 2), at((frame >> 2) + 1), 'half']
    return [at(frame >> 2)]


def blend(samples) -> float:
    if len(samples) == 1:
        return samples[0]
    a, b, kind = samples
    return (a + b) >> 1 if kind == 'half' else (a + a + a + b) >> 2


def vector_value(data, anim, info, value, frame) -> float:
    if info & ELEM_CONST:
        return struct.unpack('<i', struct.pack('<I', value))[0] / FX
    return blend(sample(data, anim, info, value, frame, 2 if info & ELEM_FX16 else 4)) / FX


def sin_cos_value(data, anim, info, value, frame) -> tuple[float, float]:
    if info & ELEM_CONST:
        packed = value
        return struct.unpack('<h', struct.pack('<H', packed & 0xFFFF))[0] / FX, struct.unpack('<h', struct.pack('<H', packed >> 16))[0] / FX
    samples = sample(data, anim, info, value, frame, 4)
    pairs = [(struct.unpack('<h', struct.pack('<H', s & 0xFFFF))[0], struct.unpack('<h', struct.pack('<H', (s >> 16) & 0xFFFF))[0])
             if isinstance(s, int) else s for s in samples]
    if len(pairs) == 1:
        return pairs[0][0] / FX, pairs[0][1] / FX
    (s0, c0), (s1, c1), kind = pairs
    if kind == 'half':
        return ((s0 + s1) >> 1) / FX, ((c0 + c1) >> 1) / FX
    return ((s0 * 3 + s1) >> 2) / FX, ((c0 * 3 + c1) >> 2) / FX


@dataclass
class TextureSrtAnimation:
    data: bytes
    anim: int
    num_frames: int
    materials: dict           # material name -> 10 raw u32s

    def at(self, material: str, frame: int) -> Srt:
        tracks = self.materials[material]
        frame %= max(self.num_frames, 1)
        scale_s = vector_value(self.data, self.anim, tracks[0], tracks[1], frame)
        scale_t = vector_value(self.data, self.anim, tracks[2], tracks[3], frame)
        sin, cos = sin_cos_value(self.data, self.anim, tracks[4], tracks[5], frame)
        trans_s = vector_value(self.data, self.anim, tracks[6], tracks[7], frame)
        trans_t = vector_value(self.data, self.anim, tracks[8], tracks[9], frame)
        return Srt(scale_s, scale_t, sin, cos, trans_s, trans_t)


def load_texture_srt(data: bytes) -> TextureSrtAnimation:
    anim = first_animation(data, b'SRT0')
    num_frames = struct.unpack_from('<H', data, anim + 4)[0]
    names, units = read_dict(data, anim + 8)
    return TextureSrtAnimation(data, anim, num_frames, {n: struct.unpack('<10I', u) for n, u in zip(names, units)})


def apply_srt(uvs: np.ndarray, srt: Srt, width: int, height: int) -> np.ndarray:
    """The Maya-mode texture matrix (texmtxCalc_flag_ in cgtool/maya.c) applied to texel coordinates."""
    a, b, s, c = srt.scale_s, srt.scale_t, srt.sin, srt.cos
    u, v = uvs[..., 0], uvs[..., 1]
    new_u = u * a * c + v * a * s * width / height + width / 2 * (a - a * s - a * c) - width * a * srt.trans_s
    new_v = -u * b * s * height / width + v * b * c + height / 2 * (b * s - b * c - b + 2) + height * b * srt.trans_t
    return np.stack([new_u, new_v], axis=-1)


@dataclass
class TexturePatternAnimation:
    num_frames: int
    materials: dict           # material name -> [(frame, texture, palette)]

    def at(self, material: str, frame: int) -> tuple[str, str | None]:
        frame %= max(self.num_frames, 1)
        current = self.materials[material][0]
        for key in self.materials[material]:
            if key[0] <= frame:
                current = key
        return current[1], current[2]


def load_texture_pattern(data: bytes) -> TexturePatternAnimation:
    anim = first_animation(data, b'PAT0')
    num_frames, num_tex, num_pltt, ofs_tex, ofs_pltt = struct.unpack_from('<HBBHH', data, anim + 4)
    texture_names = [data[anim + ofs_tex + 16 * i:anim + ofs_tex + 16 * (i + 1)].rstrip(b'\0').decode('ascii') for i in range(num_tex)]
    palette_names = [data[anim + ofs_pltt + 16 * i:anim + ofs_pltt + 16 * (i + 1)].rstrip(b'\0').decode('ascii') for i in range(num_pltt)]
    names, units = read_dict(data, anim + 0x0C)
    materials = {}
    for name, unit in zip(names, units):
        count, flag, _ratio, offset = struct.unpack('<HHhH', unit)
        keys = []
        for i in range(count):
            frame, texture, palette = struct.unpack_from('<HBB', data, anim + offset + 4 * i)
            keys.append((frame, texture_names[texture], palette_names[palette] if palette < len(palette_names) else None))
        materials[name] = keys
    return TexturePatternAnimation(num_frames, materials)


@dataclass
class GroundAnimation:
    texture: str
    frames: list              # nt.Texture per frame, in frames-file order
    sequence: list            # [(frame, hold)]

    @property
    def period(self) -> int:
        return sum(hold + 1 for _, hold in self.sequence)

    def frame_at(self, tick: int) -> int:
        tick %= self.period
        for frame, hold in self.sequence:
            if tick <= hold:
                return frame
            tick -= hold + 1
        return self.sequence[-1][0]

    def texture_at(self, tick: int):
        frame = self.frames[self.frame_at(tick)]
        return nt.Texture(self.texture, frame.param, frame.extra, frame.data)


class GroundAnimations:
    """The field's ground-tile animations (res/field/texture_animations): sea, beaches, flowers, lamps."""

    def __init__(self, root: Path):
        directory = Path(root) / 'res/field/texture_animations'
        self.animations = {}
        for entry in json.loads((directory / 'texture_animations.json').read_text(encoding='utf-8'))['animations']:
            frames = nt.read_texture_set((directory / 'frames' / entry['frames']).read_bytes()).textures()
            sequence = [(step['frame'], step['hold']) for step in entry['sequence']]
            self.animations.setdefault(entry['texture'], GroundAnimation(entry['texture'], frames, sequence))


class PropAnimations:
    """The animations that play on their own for each prop model (not deferred, not bicycle slopes)."""

    def __init__(self, root: Path):
        root = Path(root)
        lists = json.loads((root / 'res/field/props/animations/prop_animation_lists.json').read_text(encoding='utf-8'))
        order = (root / 'res/field/props/animations/prop_animations.order').read_text().split()
        self.by_model = {}
        for model, entry in lists.items():
            if entry.get('deferredLoading') or entry.get('deferredAddToRenderObj') or entry.get('bicycleSlope'):
                continue
            loaded = []
            for name in entry['animations']:
                file_name = order[[n.replace('.', '_') for n in order].index(name)]
                data = (root / 'res/field/props/animations' / file_name).read_bytes()
                if data[:4] == b'BTA0':
                    loaded.append(load_texture_srt(data))
                elif data[:4] == b'BTP0':
                    loaded.append(load_texture_pattern(data))
            if loaded:
                self.by_model[model.removesuffix('_nsbmd') + '.nsbmd'] = loaded

    def for_model(self, file_name: str) -> list:
        return self.by_model.get(file_name, [])
