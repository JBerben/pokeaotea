#!/usr/bin/env python3
# ABOUTME: Scaffolds a new map's scripts, text and events (and optionally its header), wired into the build.
# ABOUTME: build_plan() collects every change for a repo root; nothing is written until Plan.apply().
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
import map_matrices  # noqa: E402

class Paths:
    """Every file new_map reads or writes, under one repository root."""

    def __init__(self, root):
        self.root = os.fspath(root)
        self.script_dir = os.path.join(self.root, "res/field/scripts")
        self.events_dir = os.path.join(self.root, "res/field/events")
        self.text_dir = os.path.join(self.root, "res/text")
        self.scripts_meson = os.path.join(self.script_dir, "meson.build")
        self.scripts_order = os.path.join(self.script_dir, "scripts.order")
        self.events_meson = os.path.join(self.events_dir, "meson.build")
        self.events_order = os.path.join(self.events_dir, "zone_event.order")
        self.text_banks = os.path.join(self.root, "generated/text_banks.txt")
        self.map_headers_txt = os.path.join(self.root, "generated/map_headers.txt")
        self.map_headers_h = os.path.join(self.root, "include/data/map_headers.h")


class NewMapError(Exception):
    pass

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

    def __init__(self, root=fs.ROOT):
        self.root = os.fspath(root)
        self.creates = []       # (path, content)
        self.edits = []         # (path, description, new_content)

    def create(self, path, content):
        self.creates.append((path, content))

    def edit(self, path, description, content):
        self.edits.append((path, description, content))

    def lines(self):
        lines = [f"  create  {os.path.relpath(path, self.root)}" for path, _ in self.creates]
        lines += [f"  edit    {os.path.relpath(path, self.root)}  ({description})"
                  for path, description, _ in self.edits]
        return lines

    def describe(self):
        for line in self.lines():
            print(line)

    def apply(self):
        for path, content in self.creates + [(path, content) for path, _, content in self.edits]:
            if isinstance(content, bytes):
                with open(path, "wb") as handle:
                    handle.write(content)
            else:
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


def next_text_bank_key(text_dir):
    """Text bank keys look arbitrary; take one clear of everything in use."""
    highest = 0
    for filename in os.listdir(text_dir):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(text_dir, filename), encoding="utf-8") as h:
                import json
                key = json.load(h).get("key")
        except (OSError, ValueError):
            continue
        if isinstance(key, int):
            highest = max(highest, key)
    return highest + 1


def header_block(new_header, template_header, name, map_headers_h, matrix_id=None):
    """A map header entry copying the template's geometry."""
    text = read(map_headers_h)
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
    if matrix_id is not None:
        replacements["mapMatrixID"] = matrix_id
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


def build_plan(name, label, add_header, template_header, root=fs.ROOT, own_matrix=False):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise NewMapError("name must be lower snake_case")
    if own_matrix and not add_header:
        raise NewMapError("--own-matrix needs --header: the matrix belongs to the new header")

    paths = Paths(root)
    camel = camel_case(name)
    plan = Plan(paths.root)

    targets = {
        "script": os.path.join(paths.script_dir, f"scripts_{name}.s"),
        "init": os.path.join(paths.script_dir, f"scripts_init_{name}.s"),
        "text": os.path.join(paths.text_dir, f"{name}.json"),
        "events": os.path.join(paths.events_dir, f"events_{name}.json"),
    }
    existing = [p for p in targets.values() if os.path.exists(p)]
    if existing:
        raise NewMapError("these already exist, refusing to overwrite:\n  "
                          + "\n  ".join(os.path.relpath(p, paths.root)
                                        for p in existing))

    plan.create(targets["script"], SCRIPT_TEMPLATE.format(name=name, camel=camel))
    plan.create(targets["init"], INIT_TEMPLATE)
    plan.create(targets["text"], TEXT_TEMPLATE.format(
        key=next_text_bank_key(paths.text_dir), camel=camel, label=label))
    plan.create(targets["events"], EVENTS_TEMPLATE)

    # Scripts: meson list and order file must gain both files, in step.
    meson = read(paths.scripts_meson)
    meson = append_to_meson_list(meson, f"scripts_{name}.s", "scr_seq_files = files(")
    meson = append_to_meson_list(meson, f"scripts_init_{name}.s", "scr_seq_files = files(")
    plan.edit(paths.scripts_meson, "scr_seq_files += 2", meson)

    order = read(paths.scripts_order)
    order = append_line(order, f"scripts_{name}", "\n")
    order = append_line(order, f"scripts_init_{name}", "\n")
    plan.edit(paths.scripts_order, "+2 entries, same order as meson", order)

    # Events: meson list and its own order file, which uses CRLF.
    events_meson = read(paths.events_meson)
    events_meson = append_to_meson_list(events_meson, f"events_{name}.json",
                                        "events_files = files(")
    plan.edit(paths.events_meson, "events_files += 1", events_meson)

    events_order = read(paths.events_order)
    events_order = append_line(events_order, f"events_{name}", "\r\n")
    plan.edit(paths.events_order, "+1 entry (CRLF)", events_order)

    banks = read(paths.text_banks)
    banks = append_line(banks, "TEXT_BANK_" + name.upper(), "\n")
    plan.edit(paths.text_banks, "TEXT_BANK_" + name.upper(), banks)

    if add_header:
        new_header = "MAP_HEADER_" + name.upper()
        headers_txt = read(paths.map_headers_txt)
        if new_header in headers_txt:
            raise NewMapError(f"{new_header} already exists")
        # MAP_HEADER_COUNT closes the list, so the new name goes before it.
        headers_txt = headers_txt.replace(
            "MAP_HEADER_COUNT", new_header + "\nMAP_HEADER_COUNT", 1)
        plan.edit(paths.map_headers_txt, f"{new_header} before MAP_HEADER_COUNT",
                  headers_txt)

        matrix_id = None
        if own_matrix:
            # Copies the template's blocks into new land data under a matrix of its own.
            workspace = map_matrices.Workspace(paths.root)
            try:
                matrix_id = map_matrices.matrix_from_template(workspace, template_header)
            except map_matrices.MatrixError as error:
                raise NewMapError("; ".join(error.errors))
            for edit in workspace.edits.values():
                target = os.path.join(paths.root, edit.path)
                if edit.created:
                    plan.create(target, edit.content)
                else:
                    plan.edit(target, edit.description, edit.content)

        block = header_block(new_header, template_header, name, paths.map_headers_h, matrix_id)
        if block is None:
            raise NewMapError(f"no template header {template_header}")
        headers_h = read(paths.map_headers_h)
        close = headers_h.rindex("};")
        where = f"own matrix {matrix_id} copied from" if matrix_id else "geometry from"
        plan.edit(paths.map_headers_h, f"{new_header}, {where} {template_header}",
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
    parser.add_argument("--own-matrix", action="store_true",
                        help="with --header: give the map its own matrix, copying the "
                             "template's blocks into new land data files")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would change and stop")
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z][a-z0-9_]*", args.name):
        print("error: name must be lower snake_case", file=sys.stderr)
        return 2

    try:
        plan = build_plan(args.name, args.label or args.name.replace("_", " "),
                          args.header, args.like, own_matrix=args.own_matrix)
    except NewMapError as error:
        raise SystemExit(f"error: {error}")

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
