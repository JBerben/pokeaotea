#!/usr/bin/env python3
"""Check that every warp leads somewhere real.

    python3 tools/scripts/check_warps.py            # every map
    python3 tools/scripts/check_warps.py twinleaf_town
    python3 tools/scripts/check_warps.py --one-way  # also list one-way warps

A warp in `events_*.json` names a destination header and an index into *that*
map's warp list. Both can go stale when maps are edited, and neither fails the
build - you find out by walking into a door and landing somewhere wrong.

Checks:

  - `dest_header_id` is a real map header
  - the destination map has an events file
  - `dest_warp_id` is a valid index into the destination's warp list

Use `check_tile.py` separately if you want to confirm the tile a warp lands on;
warp targets often sit on door tiles, which carry collision by design, so it is
not a check that can be automated cleanly.

`MAP_HEADER_DYNAMIC` is accepted: elevators set their destination at runtime.

`--one-way` additionally lists warps whose destination does not lead back. That
is legal and vanilla uses it deliberately, so it is informational, not a finding.

Exit status is 0 when clean, 1 when anything is reported.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fieldscript as fs  # noqa: E402

DYNAMIC = "MAP_HEADER_DYNAMIC"
MAP_HEADERS_TXT = os.path.join(fs.ROOT, "generated/map_headers.txt")


def known_headers():
    """Every map header constant, from the generated list."""
    names = set()
    with open(MAP_HEADERS_TXT, encoding="utf-8") as handle:
        for line in handle:
            name = line.strip().split("=")[0].strip()
            if name.startswith("MAP_HEADER_"):
                names.add(name)
    return names


def events_symbol_for(header, wiring):
    return wiring.get(header, {}).get("eventsArchiveID")


def warps_of(events_symbol, cache):
    if events_symbol in cache:
        return cache[events_symbol]
    data = fs.load_events(events_symbol) if events_symbol else None
    warps = data.get("warp_events", []) if data else None
    cache[events_symbol] = warps
    return warps


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("maps", nargs="*", help="map names (default: all)")
    parser.add_argument("--one-way", action="store_true",
                        help="also list warps with no return warp")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    wiring = fs.map_wiring()
    headers = known_headers()
    # An events file can be shared; report against the header that owns it.
    header_of_events = {}
    for header, fields in wiring.items():
        symbol = fields.get("eventsArchiveID")
        if symbol:
            header_of_events.setdefault(symbol, header)

    wanted = None
    if args.maps:
        wanted = {m if m.startswith("events_") else "events_" + m
                  for m in args.maps}

    cache, findings, one_way, total = {}, [], [], 0
    directory = fs.EVENTS_DIR
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue
        symbol = filename[:-5]
        if wanted and symbol not in wanted:
            continue
        source_header = header_of_events.get(symbol, symbol)
        with open(os.path.join(directory, filename), encoding="utf-8") as handle:
            warps = json.load(handle).get("warp_events", [])

        for index, warp in enumerate(warps):
            total += 1
            destination = warp.get("dest_header_id")
            where = f"{symbol} warp {index} ({warp.get('x')},{warp.get('z')})"

            if destination == DYNAMIC:
                continue
            if destination not in headers:
                findings.append(f"{where}: destination {destination!r} is not a "
                                "map header")
                continue

            target_symbol = events_symbol_for(destination, wiring)
            target_warps = warps_of(target_symbol, cache)
            if target_warps is None:
                findings.append(f"{where}: destination {destination} has no "
                                "events file, so its warps cannot be resolved")
                continue

            warp_id = warp.get("dest_warp_id", 0)
            if warp_id >= len(target_warps):
                findings.append(
                    f"{where}: dest_warp_id {warp_id} but {destination} has "
                    f"only {len(target_warps)} warp(s)")
                continue

            if args.one_way:
                landing = target_warps[warp_id]
                returns = (landing.get("dest_header_id") == source_header
                           or landing.get("dest_header_id") == DYNAMIC)
                if not returns:
                    one_way.append(
                        f"{where} -> {destination}[{warp_id}], which leads to "
                        f"{landing.get('dest_header_id')}")

    for finding in findings:
        print(finding)
    if args.one_way and one_way:
        print(f"\none-way warps ({len(one_way)}) - legal, listed for review:")
        for entry in one_way:
            print(f"  {entry}")

    if not args.quiet:
        print(f"\n{total} warp(s) checked, {len(findings)} finding(s)",
              file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
