#!/usr/bin/env python3
"""Show how a map is wired: its entry table, and what points at each entry.

    python3 tools/scripts/map_info.py twinleaf_town
    python3 tools/scripts/map_info.py twinleaf_town --state

Answers the questions that come up constantly when editing an existing map:
which entry is index 7, what references it, which index is free to append at,
and which flags and variables this map already uses.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fieldscript as fs  # noqa: E402

LOCAL_SCRIPT_LIMIT = 2000
NO_SCRIPT = (0, 65535)

INIT_HOOKS = {
    "InitScriptEntry_OnTransition": "on transition",
    "InitScriptEntry_OnLoad": "on load",
    "InitScriptEntry_OnResume": "on resume",
}


def references(events, init_script):
    """script index -> list of human descriptions of what points at it."""
    found = {}

    def note(index, description):
        if isinstance(index, int) and index not in NO_SCRIPT \
                and index < LOCAL_SCRIPT_LIMIT:
            found.setdefault(index, []).append(description)

    if events:
        for item in events.get("object_events", []):
            note(item.get("script"), item.get("id", "object event"))
        for number, item in enumerate(events.get("coord_events", []), 1):
            note(item.get("script"),
                 f"coord event {number} ({item.get('var', 'no var')}"
                 f"=={item.get('value')})")
        for number, item in enumerate(events.get("bg_events", []), 1):
            note(item.get("script"), f"bg event {number}")

    if init_script:
        for macro, argument, _ in init_script.init_entries:
            if macro in INIT_HOOKS and argument and argument.isdigit():
                note(int(argument), f"init script, {INIT_HOOKS[macro]}")
            if macro == "InitScriptGoToIfEqual" and argument:
                pass
        # Frame-table rows carry the script index as their third argument.
        for macro, argument, line in init_script.init_entries:
            if macro == "InitScriptGoToIfEqual":
                found.setdefault(-1, [])

    return found


def frame_table_rows(init_path):
    """(var, value, index) for each InitScriptGoToIfEqual row."""
    if not init_path or not os.path.exists(init_path):
        return []
    rows = []
    with open(init_path, encoding="utf-8") as handle:
        for raw in handle:
            match = re.match(r"\s*InitScriptGoToIfEqual\s+(.*)", raw)
            if match:
                parts = [p.strip() for p in match.group(1).split(",")]
                if len(parts) == 3:
                    rows.append(tuple(parts))
    return rows


def state_used(script):
    """Flags and variables the script mentions, in first-seen order."""
    flags, variables = [], []
    for body in script.labels.values():
        for command in body:
            for argument in command.args:
                name = argument.strip()
                if name.startswith("FLAG_") and name not in flags:
                    flags.append(name)
                elif name.startswith("VAR_") and name not in variables:
                    variables.append(name)
    return flags, variables


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("map", help="map name, e.g. twinleaf_town")
    parser.add_argument("--state", action="store_true",
                        help="also list the flags and variables it uses")
    args = parser.parse_args()

    stem = args.map if args.map.startswith("scripts_") else "scripts_" + args.map
    path = fs.script_path(stem)
    if not path:
        print(f"error: no {stem}.s in res/field/scripts", file=sys.stderr)
        return 2

    script = fs.parse_script(path)
    header, fields = None, {}
    for candidate, values in fs.map_wiring().items():
        if values.get("scriptsArchiveID") == stem:
            header, fields = candidate, values
            break

    print(f"{header or '(no map header points at this file)'}\n")
    print(f"  scripts       {stem}.s")
    for label, key in (("init scripts ", "initScriptsArchiveID"),
                       ("text bank    ", "msgArchiveID"),
                       ("events       ", "eventsArchiveID"),
                       ("map matrix   ", "mapMatrixID"),
                       ("area data    ", "areaDataArchiveID")):
        if fields.get(key):
            print(f"  {label} {fields[key]}")

    init_symbol = fields.get("initScriptsArchiveID")
    init_path = fs.script_path(init_symbol) if init_symbol else None
    init_script = fs.parse_script(init_path) if init_path else None
    events = fs.load_events(fields["eventsArchiveID"]) if fields.get(
        "eventsArchiveID") else None

    used = references(events, init_script)
    print(f"\nentry table ({len(script.entries)} entries)\n")
    width = max((len(e) for e in script.entries), default=0)
    for index, label in enumerate(script.entries, 1):
        who = ", ".join(used.get(index, [])) or "(not referenced from events or init)"
        print(f"  {index:3d}  {label:<{width}}  {who}")
    print(f"\n  next free index: {len(script.entries) + 1} (append only)")
    if any(index not in used for index in range(1, len(script.entries) + 1)):
        print("  unreferenced entries are reached from C or another script, "
              "not from this map's events file")

    rows = frame_table_rows(init_path)
    if rows:
        print("\ninit script frame table")
        for variable, value, index in rows:
            print(f"  when {variable} == {value}  ->  entry {index}")

    if events:
        counts = {section: len(events.get(section, []))
                  for section in ("object_events", "coord_events",
                                  "bg_events", "warp_events")}
        print("\nevents  " + "  ".join(f"{k.replace('_events','')}={v}"
                                       for k, v in counts.items()))

    bank_constant = fields.get("msgArchiveID")
    bank = fs.load_text_bank(bank_constant) if bank_constant else None
    if bank is not None:
        print(f"text    {len(bank)} messages in "
              f"{os.path.relpath(fs.text_bank_path(bank_constant), fs.ROOT)}")

    if args.state:
        flags, variables = state_used(script)
        print(f"\nflags used ({len(flags)})")
        for flag in flags:
            print(f"  {flag}")
        print(f"\nvariables used ({len(variables)})")
        for variable in variables:
            print(f"  {variable}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
