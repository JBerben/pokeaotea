# ABOUTME: Decodes NSBMD models into transformed triangles: runs the render commands (SBC) and GX display lists.
# ABOUTME: Matrix maths follows the DS geometry engine: row vectors, and each new matrix multiplies onto the current one.

import struct
from dataclasses import dataclass, field

import numpy as np

FX = 4096.0

TRIANGLES, QUADS, TRIANGLE_STRIP, QUAD_STRIP = 0, 1, 2, 3

# SBC opcodes (NNS_G3D_SBC_*); option flags live in the top three bits.
SBC_NOP, SBC_RET, SBC_NODE, SBC_MTX, SBC_MAT, SBC_SHP, SBC_NODEDESC = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06
SBC_BB, SBC_BBY, SBC_NODEMIX, SBC_CALLDL, SBC_POSSCALE, SBC_ENVMAP, SBC_PRJMAP = 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D
SBC_LENGTHS = {
    0x00: 1, 0x01: 1, 0x02: 3, 0x03: 2, 0x04: 2, 0x05: 2, 0x06: 4, 0x07: 2,
    0x08: 2, 0x0A: 9, 0x0B: 1, 0x0C: 3, 0x0D: 3,
    0x24: 2, 0x26: 5, 0x27: 3, 0x28: 3, 0x2B: 1,
    0x44: 2, 0x46: 5, 0x47: 3, 0x48: 3,
    0x66: 6, 0x67: 4, 0x68: 4,
}

# GX geometry command parameter counts (GBATEK).
GX_PARAMS = {
    0x00: 0, 0x10: 1, 0x11: 0, 0x12: 1, 0x13: 1, 0x14: 1, 0x15: 0, 0x16: 16, 0x17: 12, 0x18: 16, 0x19: 12,
    0x1A: 9, 0x1B: 3, 0x1C: 3, 0x20: 1, 0x21: 1, 0x22: 1, 0x23: 2, 0x24: 1, 0x25: 1, 0x26: 1, 0x27: 1,
    0x28: 1, 0x29: 1, 0x2A: 1, 0x2B: 1, 0x30: 1, 0x31: 1, 0x32: 1, 0x33: 1, 0x34: 32, 0x40: 1, 0x41: 0,
    0x50: 1, 0x60: 1, 0x70: 3, 0x71: 2, 0x72: 1,
}

# NNS_G3D_SRTFLAG_*
SRT_TRANS_ZERO, SRT_ROT_ZERO, SRT_SCALE_ONE, SRT_PIVOT_EXIST = 0x0001, 0x0002, 0x0004, 0x0008
SRT_IDXPIVOT_MASK, SRT_IDXPIVOT_SHIFT, SRT_PIVOT_MINUS, SRT_SIGN_REVC, SRT_SIGN_REVD = 0x00F0, 4, 0x0100, 0x0200, 0x0400
PIVOT_UTIL = [(4, 5, 7, 8), (3, 5, 6, 8), (3, 4, 6, 7), (1, 2, 7, 8), (0, 2, 6, 8), (0, 1, 6, 7),
              (1, 2, 4, 5), (0, 2, 3, 5), (0, 1, 3, 4)]


def sign_extend(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def s16(value: int) -> int:
    return sign_extend(value, 16)


def rgb555(value: int) -> tuple[float, float, float]:
    return ((value & 31) / 31, ((value >> 5) & 31) / 31, ((value >> 10) & 31) / 31)


@dataclass
class Primitive:
    kind: int
    positions: np.ndarray              # (n, 3)
    uvs: np.ndarray                    # (n, 2), in texels
    colours: np.ndarray                # (n, 3), 0-1
    has_uv: bool = False

    def count_triangles(self) -> int:
        n = len(self.positions)
        return n // 3 if self.kind == TRIANGLES else max(n - 2, 0) if self.kind == TRIANGLE_STRIP else 0

    def count_quads(self) -> int:
        n = len(self.positions)
        return n // 4 if self.kind == QUADS else max((n - 2) // 2, 0) if self.kind == QUAD_STRIP else 0

    def triangles(self) -> list[tuple[int, int, int]]:
        """Vertex index triples, wound the way the hardware draws them."""
        n = len(self.positions)
        if self.kind == TRIANGLES:
            return [(i, i + 1, i + 2) for i in range(0, n - 2, 3)]
        if self.kind == QUADS:
            return [t for i in range(0, n - 3, 4) for t in ((i, i + 1, i + 2), (i, i + 2, i + 3))]
        if self.kind == TRIANGLE_STRIP:
            return [(i, i + 1, i + 2) if i % 2 == 0 else (i + 1, i, i + 2) for i in range(n - 2)]
        return [t for i in range(0, n - 3, 2) for t in ((i, i + 1, i + 3), (i, i + 3, i + 2))]


class GeometryEngine:
    """Just enough of the DS geometry engine's matrix state to place vertices."""

    def __init__(self, matrix: np.ndarray, stack: dict):
        self.current = np.array(matrix, dtype=float)
        self.stack = stack
        self.push_stack = []

    def multiply(self, matrix: np.ndarray):
        self.current = matrix @ self.current

    def transform(self, x: float, y: float, z: float) -> np.ndarray:
        return (np.array([x, y, z, 1.0]) @ self.current)[:3]


def matrix_4x3(values) -> np.ndarray:
    m = np.eye(4)
    m[:4, :3] = np.array(values, dtype=float).reshape(4, 3)
    return m


def matrix_3x3(values) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = np.array(values, dtype=float).reshape(3, 3)
    return m


def scale_matrix(x: float, y: float, z: float) -> np.ndarray:
    return np.diag([x, y, z, 1.0])


def translate_matrix(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4)
    m[3, :3] = [x, y, z]
    return m


def decode_display_list(data: bytes, matrix: np.ndarray, stack: dict, engine: GeometryEngine | None = None) -> list[Primitive]:
    engine = engine or GeometryEngine(matrix, stack)
    words = struct.unpack(f'<{len(data) // 4}I', data[:len(data) // 4 * 4])
    primitives = []
    kind = None
    positions, uvs, colours = [], [], []
    has_uv = False
    vertex = [0.0, 0.0, 0.0]       # untransformed, for the compact vertex commands
    uv = (0.0, 0.0)
    colour = (1.0, 1.0, 1.0)

    def flush():
        nonlocal positions, uvs, colours, has_uv
        if kind is not None and positions:
            primitives.append(Primitive(kind, np.array(positions), np.array(uvs), np.array(colours), has_uv))
        positions, uvs, colours, has_uv = [], [], [], False

    def emit():
        positions.append(engine.transform(*vertex))
        uvs.append(uv)
        colours.append(colour)

    index = 0
    while index < len(words):
        opcodes = [(words[index] >> shift) & 0xFF for shift in (0, 8, 16, 24)]
        index += 1
        for op in opcodes:
            if op not in GX_PARAMS:
                raise ValueError(f'unknown display list command 0x{op:02x}')
            params = words[index:index + GX_PARAMS[op]]
            index += GX_PARAMS[op]

            if op == 0x40:                                   # BEGIN_VTXS
                flush()
                kind = params[0] & 3
            elif op == 0x41:                                 # END_VTXS
                flush()
                kind = None
            elif op == 0x23:                                 # VTX_16
                vertex = [s16(params[0]) / FX, s16(params[0] >> 16) / FX, s16(params[1]) / FX]
                emit()
            elif op == 0x24:                                 # VTX_10
                vertex = [sign_extend(params[0] >> shift, 10) / 64 for shift in (0, 10, 20)]
                emit()
            elif op == 0x25:                                 # VTX_XY
                vertex = [s16(params[0]) / FX, s16(params[0] >> 16) / FX, vertex[2]]
                emit()
            elif op == 0x26:                                 # VTX_XZ
                vertex = [s16(params[0]) / FX, vertex[1], s16(params[0] >> 16) / FX]
                emit()
            elif op == 0x27:                                 # VTX_YZ
                vertex = [vertex[0], s16(params[0]) / FX, s16(params[0] >> 16) / FX]
                emit()
            elif op == 0x28:                                 # VTX_DIFF
                vertex = [v + sign_extend(params[0] >> shift, 10) / FX for v, shift in zip(vertex, (0, 10, 20))]
                emit()
            elif op == 0x22:                                 # TEXCOORD, 1.11.4 texels
                uv = (s16(params[0]) / 16, s16(params[0] >> 16) / 16)
                has_uv = True
            elif op == 0x20:                                 # COLOR
                colour = rgb555(params[0])
            elif op == 0x14:                                 # MTX_RESTORE
                engine.current = engine.stack.get(params[0] & 31, np.eye(4)).copy()
            elif op == 0x13:                                 # MTX_STORE
                engine.stack[params[0] & 31] = engine.current.copy()
            elif op == 0x11:                                 # MTX_PUSH
                engine.push_stack.append(engine.current.copy())
            elif op == 0x12:                                 # MTX_POP
                count = sign_extend(params[0], 6)
                for _ in range(max(count, 1)):
                    if engine.push_stack:
                        engine.current = engine.push_stack.pop()
            elif op == 0x15:                                 # MTX_IDENTITY
                engine.current = np.eye(4)
            elif op == 0x16:                                 # MTX_LOAD_4x4
                engine.current = np.array([sign_extend(p, 32) / FX for p in params]).reshape(4, 4)
            elif op == 0x17:                                 # MTX_LOAD_4x3
                engine.current = matrix_4x3([sign_extend(p, 32) / FX for p in params])
            elif op == 0x18:                                 # MTX_MULT_4x4
                engine.multiply(np.array([sign_extend(p, 32) / FX for p in params]).reshape(4, 4))
            elif op == 0x19:                                 # MTX_MULT_4x3
                engine.multiply(matrix_4x3([sign_extend(p, 32) / FX for p in params]))
            elif op == 0x1A:                                 # MTX_MULT_3x3
                engine.multiply(matrix_3x3([sign_extend(p, 32) / FX for p in params]))
            elif op == 0x1B:                                 # MTX_SCALE
                engine.multiply(scale_matrix(*[sign_extend(p, 32) / FX for p in params]))
            elif op == 0x1C:                                 # MTX_TRANS
                engine.multiply(translate_matrix(*[sign_extend(p, 32) / FX for p in params]))
            # Everything else (lighting, polygon attributes, tests) does not move vertices.
    flush()
    return primitives


@dataclass
class ModelInfo:
    num_vertices: int
    num_polygons: int
    num_triangles: int
    num_quads: int
    pos_scale: float
    inv_pos_scale: float
    box: tuple[np.ndarray, np.ndarray]


@dataclass
class Material:
    name: str
    texture: str | None = None
    palette: str | None = None
    diffuse: tuple = (1.0, 1.0, 1.0)
    alpha: float = 1.0
    poly_attr: int = 0
    tex_image_param: int = 0
    orig_width: int = 0
    orig_height: int = 0
    flag: int = 0


@dataclass
class Draw:
    material: int
    shape: int
    primitives: list[Primitive] = field(default_factory=list)


@dataclass
class Model:
    name: str
    info: ModelInfo
    materials: list[Material]
    draws: list[Draw]


def read_dict(data: bytes, offset: int) -> tuple[list[str], list[bytes]]:
    count = data[offset + 1]
    entries = offset + struct.unpack_from('<H', data, offset + 6)[0]
    unit_size, names_offset = struct.unpack_from('<HH', data, entries)
    units = [data[entries + 4 + unit_size * i:entries + 4 + unit_size * (i + 1)] for i in range(count)]
    names = [data[entries + names_offset + 16 * i:entries + names_offset + 16 * (i + 1)].rstrip(b'\0').decode('ascii')
             for i in range(count)]
    return names, units


def read_materials(data: bytes, mat: int) -> list[Material]:
    ofs_tex, ofs_pltt = struct.unpack_from('<HH', data, mat)
    names, units = read_dict(data, mat + 4)
    materials = []
    for name, unit in zip(names, units):
        base = mat + struct.unpack('<I', unit)[0]
        diff_amb, spec_emi, poly_attr, _, tex_param, _, _, flag, orig_w, orig_h = struct.unpack_from('<IIIIIIHHHH', data, base + 4)
        materials.append(Material(name=name, diffuse=rgb555(diff_amb), alpha=((poly_attr >> 16) & 31) / 31,
                                  poly_attr=poly_attr, tex_image_param=tex_param, orig_width=orig_w,
                                  orig_height=orig_h, flag=flag))

    for dict_offset, attribute in ((ofs_tex, 'texture'), (ofs_pltt, 'palette')):
        names, units = read_dict(data, mat + dict_offset)
        for name, unit in zip(names, units):
            list_offset, count = struct.unpack_from('<HB', unit)
            for index in data[mat + list_offset:mat + list_offset + count]:
                setattr(materials[index], attribute, name)
    return materials


def node_matrix(data: bytes, node: int) -> np.ndarray:
    """The local transform (scale, then rotation, then translation) of a node, as a row-vector matrix."""
    flag, r00 = struct.unpack_from('<Hh', data, node)
    p = node + 4
    trans = (0.0, 0.0, 0.0)
    if not flag & SRT_TRANS_ZERO:
        trans = tuple(v / FX for v in struct.unpack_from('<3i', data, p))
        p += 12
    rot = None
    if not flag & SRT_ROT_ZERO:
        if flag & SRT_PIVOT_EXIST:
            a, b = (v / FX for v in struct.unpack_from('<2h', data, p))
            pivot = (flag & SRT_IDXPIVOT_MASK) >> SRT_IDXPIVOT_SHIFT
            values = [0.0] * 9
            values[pivot] = -1.0 if flag & SRT_PIVOT_MINUS else 1.0
            u = PIVOT_UTIL[pivot]
            values[u[0]], values[u[1]] = a, b
            values[u[2]] = -b if flag & SRT_SIGN_REVC else b
            values[u[3]] = -a if flag & SRT_SIGN_REVD else a
            p += 4
        else:
            values = [r00 / FX] + [v / FX for v in struct.unpack_from('<8h', data, p)]
            p += 16
        rot = values
    scale = None
    if not flag & SRT_SCALE_ONE:
        scale = tuple(v / FX for v in struct.unpack_from('<3i', data, p))

    # The geometry engine receives translate (or 4x3 with rotation) first, then scale, each multiplied
    # onto the current matrix, so the scale applies to vertices first.
    m = np.eye(4)
    if rot is not None:
        m = matrix_3x3(rot) @ m
    m = translate_matrix(*trans) @ m if rot is None else matrix_4x3(rot + list(trans))
    if scale is not None:
        m = scale_matrix(*scale) @ m
    return m


def load_model(data: bytes, index: int = 0) -> Model:
    if data[0:4] != b'BMD0':
        raise ValueError(f'not an NSBMD file: magic is {data[0:4]!r}')
    mdl0 = struct.unpack_from('<I', data, 0x10)[0]
    names, units = read_dict(data, mdl0 + 8)
    model = mdl0 + struct.unpack('<I', units[index])[0]
    _, ofs_sbc, ofs_mat, ofs_shp, _ = struct.unpack_from('<5I', data, model)

    info_offset = model + 0x14
    (pos_scale, inv_pos_scale, num_vertices, num_polygons, num_triangles, num_quads,
     bx, by, bz, bw, bh, bd, box_scale, _) = struct.unpack_from('<ii4H6hii', data, info_offset + 8)
    box_scale /= FX
    low = np.array([bx, by, bz]) / FX * box_scale
    high = low + np.array([bw, bh, bd]) / FX * box_scale
    info = ModelInfo(num_vertices, num_polygons, num_triangles, num_quads, pos_scale / FX, inv_pos_scale / FX, (low, high))

    node_info = info_offset + 0x2C
    _, node_units = read_dict(data, node_info)
    nodes = [node_info + struct.unpack('<I', unit)[0] for unit in node_units]

    materials = read_materials(data, model + ofs_mat)

    shp = model + ofs_shp
    _, shape_units = read_dict(data, shp)
    shapes = []
    for unit in shape_units:
        base = shp + struct.unpack('<I', unit)[0]
        ofs_dl, size_dl = struct.unpack_from('<II', data, base + 8)
        shapes.append(data[base + ofs_dl:base + ofs_dl + size_dl])

    draws = run_sbc(data[model + ofs_sbc:model + ofs_mat], data, nodes, shapes, info)
    return Model(names[index], info, materials, draws)


def run_sbc(sbc: bytes, data: bytes, nodes: list[int], shapes: list[bytes], info: ModelInfo) -> list[Draw]:
    engine = GeometryEngine(np.eye(4), {})
    draws = []
    material = 0
    pos = 0
    while pos < len(sbc):
        op = sbc[pos]
        command, option = op & 0x1F, op & 0xE0
        if op not in SBC_LENGTHS and command != SBC_NODEMIX:
            raise ValueError(f'unknown render command 0x{op:02x}')
        length = 3 + 3 * sbc[pos + 2] if command == SBC_NODEMIX else SBC_LENGTHS[op]
        args = sbc[pos + 1:pos + length]

        if command == SBC_RET:
            break
        if command == SBC_MTX:
            engine.current = engine.stack.get(args[0], np.eye(4)).copy()
        elif command == SBC_MAT:
            material = args[0]
        elif command == SBC_SHP:
            draws.append(Draw(material, args[0], decode_display_list(shapes[args[0]], engine.current, engine.stack, engine)))
        elif command == SBC_NODEDESC:
            if option in (0x40, 0x60):
                restore = args[3] if option == 0x40 else args[4]
                engine.current = engine.stack.get(restore, np.eye(4)).copy()
            engine.multiply(node_matrix(data, nodes[args[0]]))
            if option in (0x20, 0x60):
                engine.stack[args[3]] = engine.current.copy()
        elif command in (SBC_BB, SBC_BBY):
            # Billboards turn to face the camera; the node's own placement is kept.
            if option in (0x40, 0x60):
                engine.current = engine.stack.get(args[1] if option == 0x40 else args[1], np.eye(4)).copy()
            if option in (0x20, 0x60):
                engine.stack[args[1] if option == 0x20 else args[2]] = engine.current.copy()
        elif command == SBC_NODEMIX:
            dest, count = args[0], args[1]
            blended = np.zeros((4, 4))
            for i in range(count):
                stack_index, _node, ratio = args[2 + 3 * i:5 + 3 * i]
                blended += engine.stack.get(stack_index, np.eye(4)) * (ratio / 256)
            engine.stack[dest] = blended
        elif command == SBC_POSSCALE:
            factor = info.inv_pos_scale if option == 0x20 else info.pos_scale
            engine.multiply(scale_matrix(factor, factor, factor))
        pos += length
    return draws
