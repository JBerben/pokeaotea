#!/usr/bin/env python3
"""Scaffold a new map's scripts, text and events, fully wired into the build.

    python3 tools/scripts/new_map.py my_new_town --dry-run
    python3 tools/scripts/new_map.py my_new_town
    python3 tools/scripts/new_map.py my_new_town --header

Creating a script file by hand means touching seven places, in two files that
must stay in the same order, one of which uses CRLF. Missing one fails the
build in a way that points somewhere else. This does all of it:

    res/field/scripts/scripts_<name>.s          created
    res/field/scripts/scripts_init_<name>.s     created
    res/field/scripts/meson.build               both registered
    res/field/scripts/scripts.order             both registered, same order
    res/text/<name>.json                        created
    generated/text_banks.txt                    TEXT_BANK_<NAME> appended
    res/field/events/events_<name>.json         created
    res/field/events/meson.build                registered
    res/field/events/zone_event.order           registered (CRLF)

With `--header` it also adds the map header itself, copying the geometry
fields (map matrix, area data, music, weather) from `--like` so the new map is
immediately buildable and walkable. Swap that geometry for your own when you
have it; until then the map is a playable copy of the template's layout.

Nothing is written unless every step can be done: the tool refuses if any file
already exists, so a half-wired map is not a state you can end up in.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fieldscript as fs  # noqa: E402

SCRIPTS_MESON = os.path.join(fs.SCRIPT_DIR, "meson.build")
SCRIPTS_ORDER = os.path.join(fs.SCRIPT_DIR, "scripts.order")
EVENTS_MESON = os.path.join(fs.EVENTS_DIR, "meson.build")
EVENTS_ORDER = os.path.join(fs.EVENTS_DIR, "zone_event.order")
TEXT_BANKS = os.path.join(fs.ROOT, "generated/text_banks.txt")
MAP_HEADERS_TXT = os.path.join(fs.ROOT, "generated/map_headers.txt")
MAP_HEADERS_H = os.path.join(fs.ROOT, "include/data/map_headers.h")

DEFAULT_TEMPLATE = "MAP_HEADER_TWINLEAF_TOWN_NORTHEAST_HOUSE"

# Fields that must point at the new map's own resources, not the template's.
OWN_RESOURCES = ("scriptsArchiveID", "initScriptsArchiveID",
                 "msgArchiveID", "eventsArchiveID")

SCRIPT_TEMPLATE = '''#include "macros/scrcmd.inc"
#include "res/text/bank/{name}.h"
#include "res/field/events/events_{name}.h"


    ScriptEntry {camel}_OnTransition
    ScriptEntryEnd

{camel}_OnTransition:
    End
'''

INIT_TEMPLATE = '''#include "macros/scrcmd.inc"


    InitScriptEntry_OnTransition 1
    InitScriptEntryEnd

    InitScriptEnd
'''

TEXT_TEMPLATE = '''{{
  "key": {key},
  "messages": [
    {{
      "id": "{camel}_Text_Placeholder",
      "en_US": "This is {label}."
    }}
  ]
}}
'''

EVENTS_TEMPLATE = '''{
    "bg_events": [],
    "object_events": [],
    "warp_events": [],
    "coord_events": []
}
'''


def camel_case(name):
    return "".join(part.capitalize() for part in name.split("_"))


class Plan:
    """Every change, collected before anything is written."""

    def __init__(self):
        self.creates = []       # (path, content)
        self.edits = []         # (path, description, new_content)

    def create(self, path, content):
        self.creates.append((path, content))

    def edit(self, path, description, content):
        self.edits.append((path, description, content))

    def describe(self):
        for path, _ in self.creates:
            print(f"  create  {os.path.relpath(path, fs.ROOT)}")
        for path, description, _ in self.edits:
            print(f"  edit    {os.path.relpath(path, fs.ROOT)}  ({description})")

    def apply(self):
        for path, content in self.creates:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
        for path, _, content in self.edits:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)


def read(path, newline=""):
    with open(path, encoding="utf-8", newline=newline) as handle:
        return handle.read()


def append_to_meson_list(text, entry, anchor):
    """Insert `    'entry',` as the last item of the list opened by `anchor`."""
    start = text.index(anchor)
    close = text.index("\n)", start)
    return text[:close] + f"\n    '{entry}'," + text[close:]


def append_line(text, line, ending):
    if text and not text.endswith(ending):
        text += ending
    return text + line + ending


def next_text_bank_key():
    """Text bank keys look arbitrary; take one clear of everything in use."""
    highest = 0
    for filename in os.listdir(fs.TEXT_DIR):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(fs.TEXT_DIR, filename), encoding="utf-8") as h:
                import json
                key = json.load(h).get("key")
        except (OSError, ValueError):
            continue
        if isinstance(key, int):
            highest = max(highest, key)
    return highest + 1


def header_block(new_header, template_header, name):
    """A map header entry copying the template's geometry."""
    text = read(MAP_HEADERS_H)
    match = re.search(r"\[" + re.escape(template_header) + r"\]\s*=\s*\{(.*?)\n    \}",
                      text, re.S)
    if not match:
        return None
    replacements = {
        "scriptsArchiveID": f"scripts_{name}",
        "initScriptsArchiveID": f"scripts_init_{name}",
        "msgArchiveID": "TEXT_BANK_" + name.upper(),
        "eventsArchiveID": f"events_{name}",
    }
    lines = []
    for line in match.group(1).strip("\n").split("\n"):
        field = re.match(r"\s*\.(\w+)\s*=", line)
        if field and field.group(1) in replacements:
            lines.append(f"        .{field.group(1)} = "
                         f"{replacements[field.group(1)]},")
        else:
            lines.append(line)
    body = "\n".join(lines)
    return f"    [{new_header}] = {{\n{body}\n    }},\n"


def build_plan(name, label, add_header, template_header):
    camel = camel_case(name)
    plan = Plan()

    targets = {
        "script": os.path.join(fs.SCRIPT_DIR, f"scripts_{name}.s"),
        "init": os.path.join(fs.SCRIPT_DIR, f"scripts_init_{name}.s"),
        "text": os.path.join(fs.TEXT_DIR, f"{name}.json"),
        "events": os.path.join(fs.EVENTS_DIR, f"events_{name}.json"),
    }
    existing = [p for p in targets.values() if os.path.exists(p)]
    if existing:
        raise SystemExit("error: these already exist, refusing to overwrite:\n  "
                         + "\n  ".join(os.path.relpath(p, fs.ROOT)
                                       for p in existing))

    plan.create(targets["script"], SCRIPT_TEMPLATE.format(name=name, camel=camel))
    plan.create(targets["init"], INIT_TEMPLATE)
    plan.create(targets["text"], TEXT_TEMPLATE.format(
        key=next_text_bank_key(), camel=camel, label=label))
    plan.create(targets["events"], EVENTS_TEMPLATE)

    # Scripts: meson list and order file must gain both files, in step.
    meson = read(SCRIPTS_MESON)
    meson = append_to_meson_list(meson, f"scripts_{name}.s", "scr_seq_files = files(")
    meson = append_to_meson_list(meson, f"scripts_init_{name}.s", "scr_seq_files = files(")
    plan.edit(SCRIPTS_MESON, "scr_seq_files += 2", meson)

    order = read(SCRIPTS_ORDER)
    order = append_line(order, f"scripts_{name}", "\n")
    order = append_line(order, f"scripts_init_{name}", "\n")
    plan.edit(SCRIPTS_ORDER, "+2 entries, same order as meson", order)

    # Events: meson list and its own order file, which uses CRLF.
    events_meson = read(EVENTS_MESON)
    events_meson = append_to_meson_list(events_meson, f"events_{name}.json",
                                        "events_files = files(")
    plan.edit(EVENTS_MESON, "events_files += 1", events_meson)

    events_order = read(EVENTS_ORDER)
    events_order = append_line(events_order, f"events_{name}", "\r\n")
    plan.edit(EVENTS_ORDER, "+1 entry (CRLF)", events_order)

    banks = read(TEXT_BANKS)
    banks = append_line(banks, "TEXT_BANK_" + name.upper(), "\n")
    plan.edit(TEXT_BANKS, "TEXT_BANK_" + name.upper(), banks)

    if add_header:
        new_header = "MAP_HEADER_" + name.upper()
        headers_txt = read(MAP_HEADERS_TXT)
        if new_header in headers_txt:
            raise SystemExit(f"error: {new_header} already exists")
        # MAP_HEADER_COUNT closes the list, so the new name goes before it.
        headers_txt = headers_txt.replace(
            "MAP_HEADER_COUNT", new_header + "\nMAP_HEADER_COUNT", 1)
        plan.edit(MAP_HEADERS_TXT, f"{new_header} before MAP_HEADER_COUNT",
                  headers_txt)

        block = header_block(new_header, template_header, name)
        if block is None:
            raise SystemExit(f"error: no template header {template_header}")
        headers_h = read(MAP_HEADERS_H)
        close = headers_h.rindex("};")
        plan.edit(MAP_HEADERS_H, f"{new_header}, geometry from {template_header}",
                  headers_h[:close] + block + headers_h[close:])

    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__)
    parser.add_argument("name", help="snake_case map name, e.g. my_new_town")
    parser.add_argument("--label", help="human name for the placeholder message")
    parser.add_argument("--header", action="store_true",
                        help="also add the map header entry")
    parser.add_argument("--like", default=DEFAULT_TEMPLATE,
                        help=f"header to copy geometry from (default {DEFAULT_TEMPLATE})")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would change and stop")
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z][a-z0-9_]*", args.name):
        print("error: name must be lower snake_case", file=sys.stderr)
        return 2

    plan = build_plan(args.name, args.label or args.name.replace("_", " "),
                      args.header, args.like)

    print(f"{'Would apply' if args.dry_run else 'Applying'} for "
          f"'{args.name}':\n")
    plan.describe()

    if args.dry_run:
        print("\nNothing written (--dry-run).")
        return 0

    plan.apply()
    print("\nDone. Next:")
    if not args.header:
        print(f"  - add a map header pointing at scripts_{args.name}, "
              f"scripts_init_{args.name}, TEXT_BANK_{args.name.upper()} and "
              f"events_{args.name} (or rerun with --header)")
    else:
        print(f"  - MAP_HEADER_{args.name.upper()} reuses "
              f"{args.like}'s map matrix and area data, so it is a playable "
              "copy of that layout. Replace .mapMatrixID and "
              ".areaDataArchiveID when you have your own geometry.")
    print("  - add warps in res/field/events/events_%s.json so it is reachable"
          % args.name)
    print(f"  - build with: make rom")
    print(f"  - then: python3 tools/scripts/map_info.py {args.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
