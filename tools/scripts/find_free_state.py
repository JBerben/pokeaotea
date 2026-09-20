#!/usr/bin/env python3
"""Find flags and variables that are free to claim for new content.

    python3 tools/scripts/find_free_state.py              # what is free
    python3 tools/scripts/find_free_state.py --limit 40
    python3 tools/scripts/find_free_state.py --ranges     # explain the ranges
    python3 tools/scripts/find_free_state.py --check FLAG_UNUSED_0x0094

Flags and variables come from `generated/vars_flags.txt`, where a name's
position in the file is its numeric value. Most of the file is *not* free even
when nothing mentions a name, because several ranges are indexed numerically at
runtime rather than by name - `TRAINER_DEFEATED_FLAGS_START + trainerID`, for
instance. Claiming one of those silently corrupts unrelated game state.

This tool only offers names from the general ranges, and says why the rest are
reserved. Names are still only part of the story: verify before you commit to
one, and never reorder existing entries - position is the value, and save data
depends on it.
"""

import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VARS_FLAGS = os.path.join(ROOT, "generated/vars_flags.txt")

SCAN_DIRS = ("res", "src", "include", "asm")
SCAN_SUFFIXES = (".s", ".c", ".h", ".json", ".inc", ".txt")

NAME = re.compile(r"\b(?:FLAG|VAR)_\w+")

# Ranges the engine addresses by arithmetic, not by name. Each entry gives the
# marker that opens the range, how it closes - either an explicit end marker or
# a name prefix every member shares - and why it must not be hand-claimed.
RESERVED = {
    "MAP_LOCAL_FLAGS_START": (
        "MAP_LOCAL_FLAGS_END", None,
        "cleared on every map transition (memset in script_manager.c); use for "
        "cutscene bookkeeping only, never for progress"),
    "HIDDEN_ITEM_FLAGS_START": (
        "HIDDEN_ITEM_FLAGS_END", None,
        "indexed as HIDDEN_ITEM_FLAGS_START + hidden item id"),
    "TRAINER_DEFEATED_FLAGS_START": (
        "TRAINER_DEFEATED_FLAGS_END", None,
        "indexed as TRAINER_DEFEATED_FLAGS_START + trainer id"),
    "DAILY_FLAGS_START": (
        "DAILY_FLAGS_END", None,
        "cleared once a day (memset in script_manager.c)"),
    "SYSTEM_FLAGS_FIRST_ARRIVAL_TO_ZONE": (
        None, "FLAG_FIRST_ARRIVAL_",
        "indexed by zone from src/spawn_locations.c"),
    "MAP_LOCAL_VARS_START": (
        "MAP_LOCAL_VARS_END", None,
        "cleared on every map transition"),
    "OBJ_GFX_VARS_START": (
        None, "VAR_OBJ_GFX_",
        "indexed as OBJ_GFX_VARS_START + graphics var id"),
    "SCRIPT_LOCAL_VARS_START": (
        "SCRIPT_LOCAL_VARS_END", None,
        "scratch registers VAR_0x8000-VAR_0x800D; valid for one script run"),
}

END_MARKERS = {value[0] for value in RESERVED.values() if value[0]}


class Entry:
    __slots__ = ("name", "line", "kind", "reserved_reason")

    def __init__(self, name, line, kind, reserved_reason):
        self.name = name
        self.line = line
        self.kind = kind
        self.reserved_reason = reserved_reason


def parse_entries():
    """Every FLAG_/VAR_ name, tagged with the range it falls in."""
    entries, reason, prefix = [], None, None

    def open_range(marker):
        _end, member_prefix, why = RESERVED[marker]
        return why, member_prefix

    with open(VARS_FLAGS, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            text = raw.strip()
            if not text:
                continue
            name = text.split("=")[0].strip()

            if name in RESERVED:
                reason, prefix = open_range(name)
                continue
            if name in END_MARKERS:
                # The closer aliases the range's last name, already recorded.
                reason, prefix = None, None
                continue
            if not name.startswith(("FLAG_", "VAR_")):
                continue

            # A name aliased to a range marker opens that range.
            alias = text.split("=")[1].strip() if "=" in text else None
            if alias in RESERVED:
                reason, prefix = open_range(alias)

            # A prefix-delimited range ends at the first name that leaves it.
            if reason and prefix and not name.startswith(prefix):
                reason, prefix = None, None

            kind = "flag" if name.startswith("FLAG_") else "var"
            why = reason
            if kind == "flag" and not any(e.kind == "flag" for e in entries):
                # Flag 0 is the "no flag" sentinel: events_*.json writes
                # hidden_flag "0" to mean "not hidden", and map_object.c tests
                # that flag directly, so it must always read false.
                why = ('flag 0 is the "no flag" sentinel used by '
                       "hidden_flag in events_*.json; it must never be set")
            entries.append(Entry(name, number, kind, why))
    return entries


def referenced_names():
    """Every FLAG_/VAR_ name mentioned anywhere in the sources."""
    used = set()
    for base in SCAN_DIRS:
        root = os.path.join(ROOT, base)
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for filename in filenames:
                if not filename.endswith(SCAN_SUFFIXES):
                    continue
                path = os.path.join(dirpath, filename)
                try:
                    with open(path, encoding="utf-8", errors="ignore") as handle:
                        used.update(NAME.findall(handle.read()))
                except OSError:
                    continue
    # The definition list itself does not count as a use.
    with open(VARS_FLAGS, encoding="utf-8") as handle:
        defined_only = set(NAME.findall(handle.read()))
    return used, defined_only


def claim_rank(entry):
    """Prefer names the base game already marks as spare."""
    if "UNUSED" in entry.name:
        return 0
    if "DUMMY" in entry.name:
        return 1
    if "UNK" in entry.name:
        return 2
    return 3


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=15,
                        help="how many candidates to show per kind (default 15)")
    parser.add_argument("--ranges", action="store_true",
                        help="list the reserved ranges and why")
    parser.add_argument("--check", metavar="NAME",
                        help="report whether one specific name is free")
    args = parser.parse_args()

    entries = parse_entries()
    used, _ = referenced_names()

    if args.ranges:
        print("Reserved ranges - do not hand-claim names inside these:\n")
        seen = set()
        for entry in entries:
            if entry.reserved_reason and entry.reserved_reason not in seen:
                seen.add(entry.reserved_reason)
                members = [e for e in entries
                           if e.reserved_reason == entry.reserved_reason]
                print(f"  {members[0].name}")
                print(f"    .. {members[-1].name}  ({len(members)} entries)")
                print(f"    {entry.reserved_reason}\n")
        return 0

    if args.check:
        match = next((e for e in entries if e.name == args.check), None)
        if not match:
            print(f"{args.check} is not in generated/vars_flags.txt",
                  file=sys.stderr)
            return 2
        if match.reserved_reason:
            print(f"{match.name}: RESERVED - {match.reserved_reason}")
            return 1
        if match.name in used:
            print(f"{match.name}: in use (referenced in the sources)")
            return 1
        print(f"{match.name}: free to claim "
              f"(general range, line {match.line} of generated/vars_flags.txt)")
        return 0

    for kind, label in (("flag", "flags"), ("var", "variables")):
        pool = [e for e in entries if e.kind == kind]
        general = [e for e in pool if not e.reserved_reason]
        free = sorted((e for e in general if e.name not in used),
                      key=lambda e: (claim_rank(e), e.line))
        reserved = len(pool) - len(general)

        print(f"\n{label}: {len(pool)} defined, {reserved} in reserved ranges, "
              f"{len(general) - len(free)} of the remaining {len(general)} in use")
        print(f"  {len(free)} free to claim; first {min(args.limit, len(free))}:")
        for entry in free[:args.limit]:
            print(f"    {entry.name:<52} line {entry.line}")

    print("\nClaim a name by renaming it in place in generated/vars_flags.txt.")
    print("Never insert or reorder entries - position is the numeric value, and")
    print("save data depends on it. Run --ranges to see what is off-limits.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
