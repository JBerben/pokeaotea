#!/usr/bin/env python3
# ABOUTME: Shows how a map is wired: its entry table, what references each entry, events, text and state used.
# ABOUTME: summarize() returns the report as data for mapedit; the command line prints format_summary().
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
from dataclasses import dataclass

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


class MapInfoError(Exception):
    pass


@dataclass
class Entry:
    index: int
    label: str
    references: list


@dataclass
class MapSummary:
    stem: str
    header: str
    fields: dict
    entries: list
    next_free_index: int
    has_unreferenced: bool
    frame_rows: list
    event_counts: dict
    text_messages: int
    text_path: str
    flags: list
    variables: list


def script_stem_for_header(header):
    """The scripts file a map header points at, or None."""
    return fs.map_wiring().get(header, {}).get("scriptsArchiveID")


def summarize(map_name):
    """Everything map_info reports about a map, as data."""
    stem = map_name if map_name.startswith("scripts_") else "scripts_" + map_name
    path = fs.script_path(stem)
    if not path:
        raise MapInfoError(f"no {stem}.s in res/field/scripts")

    script = fs.parse_script(path)
    header, fields = None, {}
    for candidate, values in fs.map_wiring().items():
        if values.get("scriptsArchiveID") == stem:
            header, fields = candidate, values
            break

    init_symbol = fields.get("initScriptsArchiveID")
    init_path = fs.script_path(init_symbol) if init_symbol else None
    init_script = fs.parse_script(init_path) if init_path else None
    events = fs.load_events(fields["eventsArchiveID"]) if fields.get(
        "eventsArchiveID") else None

    used = references(events, init_script)
    entries = [Entry(index, label, used.get(index, []))
               for index, label in enumerate(script.entries, 1)]

    event_counts = None
    if events:
        event_counts = {section: len(events.get(section, []))
                        for section in ("object_events", "coord_events",
                                        "bg_events", "warp_events")}

    bank_constant = fields.get("msgArchiveID")
    bank = fs.load_text_bank(bank_constant) if bank_constant else None
    text_messages = len(bank) if bank is not None else None
    text_path = (os.path.relpath(fs.text_bank_path(bank_constant), fs.ROOT)
                 if bank is not None else None)

    flags, variables = state_used(script)
    return MapSummary(
        stem=stem,
        header=header,
        fields=fields,
        entries=entries,
        next_free_index=len(script.entries) + 1,
        has_unreferenced=any(index not in used
                             for index in range(1, len(script.entries) + 1)),
        frame_rows=frame_table_rows(init_path),
        event_counts=event_counts,
        text_messages=text_messages,
        text_path=text_path,
        flags=flags,
        variables=variables,
    )


def format_summary(summary, state=False):
    """The map_info report for a summary, as printed by the command line."""
    lines = []
    lines.append(f"{summary.header or '(no map header points at this file)'}\n")
    lines.append(f"  scripts       {summary.stem}.s")
    for label, key in (("init scripts ", "initScriptsArchiveID"),
                       ("text bank    ", "msgArchiveID"),
                       ("events       ", "eventsArchiveID"),
                       ("map matrix   ", "mapMatrixID"),
                       ("area data    ", "areaDataArchiveID")):
        if summary.fields.get(key):
            lines.append(f"  {label} {summary.fields[key]}")

    lines.append(f"\nentry table ({len(summary.entries)} entries)\n")
    width = max((len(e.label) for e in summary.entries), default=0)
    for entry in summary.entries:
        who = ", ".join(entry.references) or "(not referenced from events or init)"
        lines.append(f"  {entry.index:3d}  {entry.label:<{width}}  {who}")
    lines.append(f"\n  next free index: {summary.next_free_index} (append only)")
    if summary.has_unreferenced:
        lines.append("  unreferenced entries are reached from C or another script, "
                     "not from this map's events file")

    if summary.frame_rows:
        lines.append("\ninit script frame table")
        for variable, value, index in summary.frame_rows:
            lines.append(f"  when {variable} == {value}  ->  entry {index}")

    if summary.event_counts:
        lines.append("\nevents  " + "  ".join(f"{k.replace('_events','')}={v}"
                                              for k, v in summary.event_counts.items()))

    if summary.text_messages is not None:
        lines.append(f"text    {summary.text_messages} messages in {summary.text_path}")

    if state:
        lines.append(f"\nflags used ({len(summary.flags)})")
        for flag in summary.flags:
            lines.append(f"  {flag}")
        lines.append(f"\nvariables used ({len(summary.variables)})")
        for variable in summary.variables:
            lines.append(f"  {variable}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("map", help="map name, e.g. twinleaf_town")
    parser.add_argument("--state", action="store_true",
                        help="also list the flags and variables it uses")
    args = parser.parse_args()

    try:
        summary = summarize(args.map)
    except MapInfoError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(format_summary(summary, state=args.state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
