#!/usr/bin/env python3
# ABOUTME: Reads, appends to, and writes NitroSystem texture sets (the TEX0 block of an NSBTX, or one embedded in an NSBMD).
# ABOUTME: Appending keeps every existing byte where it is and adds new textures and palettes after them.

"""
Layout of a TEX0 block as written by the retail tools (all offsets relative to
the block):

    0x00  'TEX0', u32 block size
    0x08  texInfo     { u32 vramKey; u16 sizeTex /8; u16 ofsDict; u16 flag; u16 pad; u32 ofsTex; }
    0x18  tex4x4Info  { u32 vramKey; u16 sizeTex /8; u16 ofsDict; u16 flag; u16 pad; u32 ofsTex; u32 ofsTexPlttIdx; }
    0x2C  plttInfo    { u32 vramKey; u16 sizePltt /8; u16 flag; u16 ofsDict; u16 pad; u32 ofsPlttData; }
    0x3C  texture dictionary, palette dictionary, texture data, palette data

A dictionary (NNSG3dResDict) is a Patricia tree over the 16-byte names, used by
NNS_G3dGetResDictIdxByName when it has 16 or more entries, followed by one data
unit per entry and then the names. Texture units are {u32 texImageParam; u32
extraParam;}, where texImageParam holds the data address in 8-byte units.
Palette units are {u16 offset /8; u16 flag;}; flag bit 0 marks a 4-colour
palette, the only kind addressed in 8-byte units by the hardware. Every other
palette must start on a 16-byte boundary (bindMdlPltt_Internal_ in NitroSystem's
kernel.c), so appended palettes start on one.

Texture and palette data can be shared by several names. Palette sizes are not
stored; a palette is taken to run to the next palette's data or the end.
"""

import struct
from typing import NamedTuple

GX_TEXFMT_NONE = 0
GX_TEXFMT_A3I5 = 1
GX_TEXFMT_PLTT4 = 2
GX_TEXFMT_PLTT16 = 3
GX_TEXFMT_PLTT256 = 4
GX_TEXFMT_COMP4x4 = 5
GX_TEXFMT_A5I3 = 6
GX_TEXFMT_DIRECT = 7

BITS_PER_TEXEL = {
    GX_TEXFMT_A3I5: 8,
    GX_TEXFMT_PLTT4: 2,
    GX_TEXFMT_PLTT16: 4,
    GX_TEXFMT_PLTT256: 8,
    GX_TEXFMT_A5I3: 8,
    GX_TEXFMT_DIRECT: 16,
}

TEXIMAGE_ADDR_MASK = 0xFFFF
PLTT_FLAG_FOUR_COLOUR = 0x0001
PLTT_INFO_USE_PLTT4 = 0x8000

NAME_SIZE = 16
MAX_DICT_ENTRIES = 255
# The u16 NitroSystem calls dummy_ in NNSG3dResDict is the offset of the tree, always 8.
DICT_TREE_OFFSET = 8
TEX0_HEADER_SIZE = 0x3C
BTX0_VERSION = 1
BOM = 0xFEFF


class Texture(NamedTuple):
    name: str
    param: int  # texImageParam; the address bits are ignored when appending
    extra: int  # extraParam
    data: bytes


class Palette(NamedTuple):
    name: str
    flag: int
    data: bytes


class TextureEntry(NamedTuple):
    name: str
    param: int
    extra: int


class PaletteEntry(NamedTuple):
    name: str
    offset: int  # in bytes
    flag: int


class TextureSet:
    def __init__(self, texture_entries, palette_entries, texture_data, palette_data, pltt_flag):
        self.texture_entries = list(texture_entries)
        self.palette_entries = list(palette_entries)
        self.texture_data = bytes(texture_data)
        self.palette_data = bytes(palette_data)
        self.pltt_flag = pltt_flag

    def textures(self) -> list[Texture]:
        return [Texture(e.name, e.param, e.extra, self.texture_bytes(e)) for e in self.texture_entries]

    def palettes(self) -> list[Palette]:
        return [Palette(e.name, e.flag, self.palette_bytes(e)) for e in self.palette_entries]

    def texture_bytes(self, entry: TextureEntry) -> bytes:
        start = (entry.param & TEXIMAGE_ADDR_MASK) * 8
        return self.texture_data[start:start + texture_size(entry.param)]

    def palette_bytes(self, entry: PaletteEntry) -> bytes:
        later = [e.offset for e in self.palette_entries if e.offset > entry.offset]
        end = min(later) if later else len(self.palette_data)
        return self.palette_data[entry.offset:end]

    def palette_offset(self, name: str) -> int:
        return next(e.offset for e in self.palette_entries if e.name == name)


def texture_format(param: int) -> int:
    return (param >> 26) & 7


def texture_size(param: int) -> int:
    fmt = texture_format(param)
    if fmt not in BITS_PER_TEXEL:
        raise ValueError(f'texture format {fmt} has no fixed size')
    width = 8 << ((param >> 20) & 7)
    height = 8 << ((param >> 23) & 7)
    return width * height * BITS_PER_TEXEL[fmt] // 8


def encode_name(name: str) -> bytes:
    if not (1 <= len(name) <= NAME_SIZE and name.isascii()):
        raise ValueError(f'name {name!r} must be 1-{NAME_SIZE} ASCII characters')
    return name.encode('ascii').ljust(NAME_SIZE, b'\0')


def decode_name(raw: bytes) -> str:
    return raw.rstrip(b'\0').decode('ascii')


def dict_tree(names: list[bytes]) -> bytes:
    """Builds the Patricia tree of an NNSG3dResDict the way the retail converter does.

    A port of MakeTreeFromResNames in tools/nitrobtx/src/ns/resource_tree.c. Bits
    are numbered from the least significant bit of the first byte; insertion
    walks from bit 127 down. Node 0 is a fixed root; the others are numbered
    in depth-first order, left before right.
    """

    def bit(entry, index):
        name = bytes(NAME_SIZE) if entry is None else names[entry]
        return (name[index // 8] >> (index % 8)) & 1

    def first_difference(a, b, start, stop):
        for index in range(start, stop - 1, -1):
            if bit(a, index) != bit(b, index):
                return index
        return None

    class Node:
        def __init__(self, entry, bit_index=None, left=None, right=None):
            self.entry = entry
            self.bit_index = bit_index
            self.left = left
            self.right = right

        @property
        def is_leaf(self):
            return self.bit_index is None

    holder = {'root': Node(None)}
    for entry in range(len(names)):
        parent, side = holder, 'root'
        current_bit = 127
        while True:
            node = parent[side] if parent is holder else getattr(parent, side)
            stop = 0 if node.is_leaf else node.bit_index + 1
            difference = first_difference(entry, node.entry, current_bit, stop)
            if difference is None and node.is_leaf:
                raise ValueError(f'duplicate name {decode_name(names[entry])!r}')
            if difference is not None:
                leaf = Node(entry)
                if bit(entry, difference):
                    new = Node(entry, difference, node, leaf)
                else:
                    new = Node(entry, difference, leaf, node)
                if parent is holder:
                    holder[side] = new
                else:
                    setattr(parent, side, new)
                break
            current_bit = node.bit_index
            parent, side = node, ('right' if bit(entry, node.bit_index) else 'left')

    ordered = []
    stack = [] if holder['root'].is_leaf else [holder['root']]
    while stack:
        node = stack.pop()
        ordered.append(node)
        if not node.right.is_leaf:
            stack.append(node.right)
        if not node.left.is_leaf:
            stack.append(node.left)

    index_of_node = {id(node): i + 1 for i, node in enumerate(ordered)}
    index_of_entry = {node.entry: i + 1 for i, node in enumerate(ordered)}

    def child_index(child):
        if not child.is_leaf:
            return index_of_node[id(child)]
        return 0 if child.entry is None else index_of_entry[child.entry]

    tree = bytearray([127, 1, 0, 0])
    for node in ordered:
        tree += bytes([node.bit_index, child_index(node.left), child_index(node.right), node.entry])
    return bytes(tree)


def encode_dict(names: list[str], units: list[bytes], unit_size: int) -> bytes:
    encoded = [encode_name(name) for name in names]
    tree = dict_tree(encoded)
    entries_offset = 8 + len(tree)
    size = entries_offset + 4 + unit_size * len(names) + NAME_SIZE * len(names)
    return (struct.pack('<BBHHH', 0, len(names), size, DICT_TREE_OFFSET, entries_offset)
            + tree
            + struct.pack('<HH', unit_size, 4 + unit_size * len(names))
            + b''.join(units)
            + b''.join(encoded))


def read_dict(data: bytes, offset: int) -> tuple[list[bytes], list[bytes], bytes]:
    """Returns the raw names, data units and tree of the dictionary at offset."""
    count = data[offset + 1]
    entries = offset + struct.unpack_from('<H', data, offset + 6)[0]
    unit_size, names_offset = struct.unpack_from('<HH', data, entries)
    units = [data[entries + 4 + unit_size * i:entries + 4 + unit_size * (i + 1)] for i in range(count)]
    names = [data[entries + names_offset + NAME_SIZE * i:entries + names_offset + NAME_SIZE * (i + 1)] for i in range(count)]
    tree = data[offset + 8:entries]
    return names, units, tree


def read_dict_names_and_tree(data: bytes, offset: int) -> tuple[list[bytes], bytes]:
    names, _, tree = read_dict(data, offset)
    return names, tree


def find_tex0(data: bytes) -> int | None:
    """Offset of the TEX0 block in an NSBTX or NSBMD file, or None if it has none."""
    if data[0:4] not in (b'BTX0', b'BMD0'):
        return None
    block_count = struct.unpack_from('<H', data, 0x0E)[0]
    for i in range(block_count):
        offset = struct.unpack_from('<I', data, 0x10 + 4 * i)[0]
        if data[offset:offset + 4] == b'TEX0':
            return offset
    return None


def dict_offsets(data: bytes, tex0: int) -> tuple[int, int]:
    texture_dict = tex0 + struct.unpack_from('<H', data, tex0 + 0x0E)[0]
    palette_dict = tex0 + struct.unpack_from('<H', data, tex0 + 0x34)[0]
    return texture_dict, palette_dict


def read_texture_set(data: bytes) -> TextureSet:
    tex0 = find_tex0(data)
    if tex0 is None:
        raise ValueError('file has no TEX0 block (no textures)')

    texture_size_8, _, _, _, texture_offset = struct.unpack_from('<HHHHI', data, tex0 + 0x0C)
    tex4x4_size_8 = struct.unpack_from('<H', data, tex0 + 0x1C)[0]
    palette_size_8, pltt_flag, _, _, palette_offset = struct.unpack_from('<HHHHI', data, tex0 + 0x30)
    if tex4x4_size_8:
        raise ValueError('texture set has 4x4 compressed textures, which are not supported')

    texture_dict, palette_dict = dict_offsets(data, tex0)
    names, units, _ = read_dict(data, texture_dict)
    texture_entries = [TextureEntry(decode_name(n), *struct.unpack('<II', u)) for n, u in zip(names, units)]
    names, units, _ = read_dict(data, palette_dict)
    palette_entries = []
    for name, unit in zip(names, units):
        offset_8, flag = struct.unpack('<HH', unit)
        palette_entries.append(PaletteEntry(decode_name(name), offset_8 * 8, flag))

    texture_data = data[tex0 + texture_offset:tex0 + texture_offset + texture_size_8 * 8]
    palette_data = data[tex0 + palette_offset:tex0 + palette_offset + palette_size_8 * 8]
    return TextureSet(texture_entries, palette_entries, texture_data, palette_data, pltt_flag)


def encode_tex0(texture_set: TextureSet) -> bytes:
    texture_dict = encode_dict(
        [e.name for e in texture_set.texture_entries],
        [struct.pack('<II', e.param, e.extra) for e in texture_set.texture_entries],
        8,
    )
    palette_dict = encode_dict(
        [e.name for e in texture_set.palette_entries],
        [struct.pack('<HH', e.offset // 8, e.flag) for e in texture_set.palette_entries],
        4,
    )

    texture_dict_offset = TEX0_HEADER_SIZE
    palette_dict_offset = texture_dict_offset + len(texture_dict)
    texture_offset = palette_dict_offset + len(palette_dict)
    palette_offset = texture_offset + len(texture_set.texture_data)
    size = palette_offset + len(texture_set.palette_data)

    header = (b'TEX0' + struct.pack('<I', size)
              + struct.pack('<IHHHHI', 0, len(texture_set.texture_data) // 8, texture_dict_offset, 0, 0, texture_offset)
              + struct.pack('<IHHHHII', 0, 0, texture_dict_offset, 0, 0, palette_offset, palette_offset)
              + struct.pack('<IHHHHI', 0, len(texture_set.palette_data) // 8, texture_set.pltt_flag, palette_dict_offset, 0, palette_offset))
    return header + texture_dict + palette_dict + texture_set.texture_data + texture_set.palette_data


def write_nsbtx(texture_set: TextureSet) -> bytes:
    tex0 = encode_tex0(texture_set)
    header_size = 0x10
    tex0_offset = header_size + 4
    return (b'BTX0' + struct.pack('<HHIHH', BOM, BTX0_VERSION, tex0_offset + len(tex0), header_size, 1)
            + struct.pack('<I', tex0_offset) + tex0)


def empty_texture_set() -> TextureSet:
    return TextureSet([], [], b'', b'', 0)


def append_textures(base: TextureSet, textures: list[Texture], palettes: list[Palette]) -> tuple[TextureSet, list[str]]:
    """Adds textures and palettes after the existing data, which is left untouched.

    A texture or palette whose name is already in the set is skipped if it is
    identical, and is an error otherwise. Data identical to data already in the
    set is shared rather than stored twice. Returns the new set and the names
    that were skipped.
    """
    skipped = []
    texture_entries = list(base.texture_entries)
    texture_data = bytearray(base.texture_data)
    existing_textures = {t.name: t for t in base.textures()}

    for texture in textures:
        encode_name(texture.name)
        if texture_format(texture.param) == GX_TEXFMT_COMP4x4:
            raise ValueError(f'texture {texture.name!r} is 4x4 compressed, which is not supported')
        if texture_format(texture.param) not in BITS_PER_TEXEL:
            raise ValueError(f'texture {texture.name!r} has no texture format')

        shape = texture.param & ~TEXIMAGE_ADDR_MASK
        existing = existing_textures.get(texture.name)
        if existing is not None:
            if (existing.param & ~TEXIMAGE_ADDR_MASK, existing.extra, existing.data) == (shape, texture.extra, texture.data):
                skipped.append(texture.name)
                continue
            raise ValueError(f'texture {texture.name!r} already exists in the set with different data')

        address = find_shared(texture_data, texture.data, 8, [(t.param & TEXIMAGE_ADDR_MASK) * 8 for t in texture_entries])
        if address is None:
            address = len(texture_data)
            texture_data += texture.data
        if address // 8 > TEXIMAGE_ADDR_MASK:
            raise ValueError(f'texture {texture.name!r} does not fit: texture data would exceed {TEXIMAGE_ADDR_MASK * 8} bytes')

        entry = TextureEntry(texture.name, shape | (address // 8), texture.extra)
        texture_entries.append(entry)
        existing_textures[texture.name] = Texture(texture.name, entry.param, texture.extra, texture.data)

    palette_entries = list(base.palette_entries)
    palette_data = bytearray(base.palette_data)
    existing_palettes = {p.name: p for p in base.palettes()}
    pltt_flag = base.pltt_flag

    for palette in palettes:
        encode_name(palette.name)
        existing = existing_palettes.get(palette.name)
        if existing is not None:
            if existing.flag == palette.flag and same_palette(existing.data, palette.data):
                skipped.append(palette.name)
                continue
            raise ValueError(f'palette {palette.name!r} already exists in the set with different data')

        four_colour = palette.flag & PLTT_FLAG_FOUR_COLOUR
        alignment = 8 if four_colour else 16
        offset = find_shared(palette_data, palette.data, alignment, [e.offset for e in palette_entries])
        if offset is None:
            if len(palette_data) % alignment:
                palette_data += bytes(alignment - len(palette_data) % alignment)
            offset = len(palette_data)
            palette_data += palette.data
        if four_colour:
            pltt_flag |= PLTT_INFO_USE_PLTT4

        palette_entries.append(PaletteEntry(palette.name, offset, palette.flag))
        existing_palettes[palette.name] = palette

    if len(texture_entries) > MAX_DICT_ENTRIES:
        raise ValueError(f'a texture set holds at most {MAX_DICT_ENTRIES} textures, this would have {len(texture_entries)}')
    if len(palette_entries) > MAX_DICT_ENTRIES:
        raise ValueError(f'a texture set holds at most {MAX_DICT_ENTRIES} palettes, this would have {len(palette_entries)}')

    if len(palette_data) % 8:
        palette_data += bytes(8 - len(palette_data) % 8)

    return TextureSet(texture_entries, palette_entries, texture_data, palette_data, pltt_flag), skipped


def find_shared(data: bytes, wanted: bytes, alignment: int, starts: list[int]) -> int | None:
    """Start of an existing entry whose data begins with exactly `wanted`, if any."""
    for start in starts:
        if start % alignment == 0 and data[start:start + len(wanted)] == wanted:
            return start
    return None


def same_palette(a: bytes, b: bytes) -> bool:
    # Palette sizes are inferred from where the next palette starts, so one copy
    # may carry alignment padding the other does not.
    shorter = min(len(a), len(b))
    return a[:shorter] == b[:shorter] and not any(a[shorter:]) and not any(b[shorter:])


def build_texture_set(textures: list[Texture], palettes: list[Palette]) -> TextureSet:
    return append_textures(empty_texture_set(), textures, palettes)[0]
