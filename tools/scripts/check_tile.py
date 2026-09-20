#!/usr/bin/env python3
"""Report whether map tiles are walkable, for placing object events.

Placing an NPC on a blocked tile, in a doorway, or on water is easy to do and
invisible until you load the map. This decodes the terrain attributes the
engine itself reads, so placement can be checked from the repo.

    # is this tile free?
    python3 tools/scripts/check_tile.py MAP_HEADER_TWINLEAF_TOWN 112 888

    # show the neighbourhood, to pick a spot
    python3 tools/scripts/check_tile.py MAP_HEADER_TWINLEAF_TOWN 112 888 --map 9

A tile is usable for a standing NPC when collision is clear and the behavior is
ordinary ground. Doors, water and ledges all report distinctly.

Source of truth: `terrainAttributes` at offset 0x10 of the land-data file (a
32x32 row-major u16 grid, per docs/maps/file_format_specifications.md), decoded
the way src/terrain_collision_manager.c does - bit 15 is collision, the low byte
is the tile behavior.

Caveat: this reads the *static* terrain grid and the map-prop list. It does not
account for dynamic collision (Cut trees, Strength boulders) or for other object
events standing on a tile.
"""

import argparse
import json
import os
import re
import struct
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

TILES_PER_BLOCK = 32
TERRAIN_OFFSET = 0x10
TERRAIN_COUNT = 1024
COLLISION_SHIFT = 15
BEHAVIOR_MASK = 0xFF


def tile_behavior_names():
    """Enum order in the header is the value, so index the entries."""
    path = os.path.join(ROOT, "include/constants/field/map_tile_behaviors.h")
    names, started = [], False
    for line in open(path, encoding="utf-8"):
        stripped = line.strip()
        if stripped.startswith("enum TileBehavior"):
            started = True
            continue
        if not started:
            continue
        if stripped.startswith("}"):
            break
        match = re.match(r"(TILE_BEHAVIOR_\w+)", stripped)
        if match:
            names.append(match.group(1))
    return names


def matrix_for_header(header):
    """Find the map matrix a header uses, from the compiled-in header table."""
    path = os.path.join(ROOT, "include/data/map_headers.h")
    text = open(path, encoding="utf-8").read()
    match = re.search(
        r"\[" + re.escape(header) + r"\]\s*=\s*\{(.*?)\n    \}", text, re.S)
    if not match:
        return None
    field = re.search(r"\.mapMatrixID\s*=\s*(\w+)", match.group(1))
    return field.group(1) if field else None


def load_block(matrix_name, header, tile_x, tile_z):
    """Resolve a world tile to its land-data block and local coordinates."""
    path = os.path.join(ROOT, "res/field/matrices", matrix_name + ".json")
    matrix = json.load(open(path, encoding="utf-8"))

    col, row = tile_x // TILES_PER_BLOCK, tile_z // TILES_PER_BLOCK
    grid = matrix["headers"]
    if not (0 <= row < len(grid) and 0 <= col < len(grid[0])):
        return None, f"tile ({tile_x},{tile_z}) is outside matrix {matrix_name}"
    if grid[row][col] != header:
        return None, (f"tile ({tile_x},{tile_z}) falls in matrix cell "
                      f"[row {row}][col {col}], which belongs to "
                      f"{grid[row][col]}, not {header}")

    map_id = matrix["maps"][row][col]
    number = map_id.rsplit("_", 1)[-1]
    data_path = os.path.join(ROOT, "res/field/maps/data", f"map_data_{number}.bin")
    if not os.path.exists(data_path):
        return None, f"land data {data_path} not found"

    data = open(data_path, "rb").read()
    terrain_size = struct.unpack_from("<I", data, 0)[0]
    if terrain_size != TERRAIN_COUNT * 2:
        return None, f"unexpected terrainAttributesSize {terrain_size}"
    attributes = struct.unpack_from(f"<{TERRAIN_COUNT}H", data, TERRAIN_OFFSET)
    return (attributes, col * TILES_PER_BLOCK, row * TILES_PER_BLOCK,
            os.path.relpath(data_path, ROOT)), None


def read_tile(attributes, base_x, base_z, tile_x, tile_z):
    local_x, local_z = tile_x - base_x, tile_z - base_z
    if not (0 <= local_x < TILES_PER_BLOCK and 0 <= local_z < TILES_PER_BLOCK):
        return None
    value = attributes[local_z * TILES_PER_BLOCK + local_x]
    return (value >> COLLISION_SHIFT) & 1, value & BEHAVIOR_MASK


def describe(collision, behavior, names):
    name = names[behavior] if behavior < len(names) else f"behavior {behavior}"
    if collision:
        return "BLOCKED", name
    if behavior == 0:
        return "walkable", name
    return "walkable?", name


def main():
    parser = argparse.ArgumentParser(
        description="Check whether map tiles are walkable.")
    parser.add_argument("header", help="e.g. MAP_HEADER_TWINLEAF_TOWN")
    parser.add_argument("x", type=int, help="world tile X")
    parser.add_argument("z", type=int, help="world tile Z")
    parser.add_argument("--map", type=int, metavar="RADIUS", default=0,
                        help="also print a grid of this radius around the tile")
    args = parser.parse_args()

    matrix_name = matrix_for_header(args.header)
    if not matrix_name:
        print(f"error: no header {args.header} in include/data/map_headers.h",
              file=sys.stderr)
        return 2

    block, error = load_block(matrix_name, args.header, args.x, args.z)
    if error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    attributes, base_x, base_z, data_path = block
    names = tile_behavior_names()

    print(f"{args.header}  matrix {matrix_name}  land data {data_path}")
    print(f"block covers x {base_x}..{base_x + 31}, z {base_z}..{base_z + 31}\n")

    collision, behavior = read_tile(attributes, base_x, base_z, args.x, args.z)
    verdict, name = describe(collision, behavior, names)
    print(f"({args.x},{args.z}): {verdict}  collision={collision}  {name}")

    if args.map:
        print("\n  . walkable   # blocked   ~ water   D door   + other behavior"
              "   X query tile\n")
        radius = args.map
        header_row = "        " + "".join(
            str((args.x + dx) % 10) for dx in range(-radius, radius + 1))
        print(header_row)
        for dz in range(-radius, radius + 1):
            z = args.z + dz
            cells = ""
            for dx in range(-radius, radius + 1):
                x = args.x + dx
                tile = read_tile(attributes, base_x, base_z, x, z)
                if tile is None:
                    cells += " "
                    continue
                if x == args.x and z == args.z:
                    cells += "X"
                    continue
                c, b = tile
                tile_name = names[b] if b < len(names) else ""
                if c:
                    cells += "D" if "DOOR" in tile_name else "#"
                elif "WATER" in tile_name:
                    cells += "~"
                elif b == 0:
                    cells += "."
                else:
                    cells += "+"
            print(f"  z {z:5d} {cells}")

    return 0 if not collision and behavior == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
