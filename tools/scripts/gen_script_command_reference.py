#!/usr/bin/env python3
"""Regenerate the field-script command references under docs/scripting/.

Both output files are derived entirely from the repository, so they never drift
from the macros they describe:

  docs/scripting/command_reference.md   from asm/macros/scrcmd.inc
  docs/scripting/movement_reference.md  from asm/macros/movement.inc

Usage counts come from res/field/scripts/*.s; handler names come from
include/data/scripts/scrcmd.h and the ScrCmd_* definitions under src/.

Run from anywhere:  python3 tools/scripts/gen_script_command_reference.py
"""

import collections
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

SCRCMD_INC = os.path.join(ROOT, "asm/macros/scrcmd.inc")
MOVEMENT_INC = os.path.join(ROOT, "asm/macros/movement.inc")
CMD_TABLE = os.path.join(ROOT, "include/data/scripts/scrcmd.h")
SCRIPT_DIR = os.path.join(ROOT, "res/field/scripts")
OUT_DIR = os.path.join(ROOT, "docs/scripting")

# Ordered: the first pattern a macro name matches wins.
CATEGORIES = [
    ("Script table structure", r"^(ScriptEntry|InitScript)"),
    ("Unused and dummy commands", r"(Unused|^Dummy|Dummy[0-9]|^ScrCmd_Dummy)"),
    ("Control flow", r"^(Noop|End$|GoTo|Call$|CallIf|Return|CallCommonScript|ReturnCommonScript|Common_|WaitTime|Compare)"),
    ("Flags", r"Flag"),
    ("Variables", r"Var(?!iable)|^Set(Var|Value)|^GetVar"),
    ("Messages and text", r"(Message|Text|Buffer|WaitButton|WaitAB|Signpost|Sign|Window|String|Word|Print|Sentence|Capitalize)"),
    ("Menus and input", r"(Menu|YesNo|Choice|Input|Keyboard|Select|ABPress)"),
    ("Object events and movement", r"(Object|Movement|^Move$|FacePlayer|Lock|Release|Player|Camera|Follow|Emote|SetPosition|Partner)"),
    ("Screen, fades and effects", r"(Fade|Screen|Blend|Bright|Palette|Shake|Flash|Weather|Snow|Fog|Light|Anim|Effect|Draw|HBlank|ScrollBG|Scene)"),
    ("Sound and music", r"(PlaySE|WaitSE|Sound|Music|BGM|Fanfare|Cry|Sequence|Song|Volume|Pitch|Pan$|Seq)"),
    ("Field moves and HM behaviour", r"(RockClimb|Waterfall|Strength|Defog|HMCutIn|Bicycl|RockSmash|Headbutt|Whirlpool|Surf|Fly$|Dig$|Teleport|RunningShoes)"),
    ("Battles and trainers", r"(Battle|Trainer|Wild|Opponent|Frontier|Tower|Arcade|Castle|Factory|Hall|Safari|VsSeeker|League)"),
    ("Party and Pokemon", r"(Party|Mon(?!ey)|Pokemon|Species|Egg|Daycare|Evolut|Nature|Ribbon|Move(?!ment)|Form|Nickname|Shiny|Hatch|HiddenPower|Poison|Capture)"),
    ("Items, money and shops", r"(Item|Money|Coin|Bag|Mart|Shop|Prize|Badge|Berry|Seal|Accessory|Underground|Sphere|Trap|Goods|Decor|Poffin|Shard|Honey|Fossil|BPDisplay|Good)"),
    ("Warps, maps and world state", r"(Warp|Map|Location|Zone|Escape|Matrix|Tile|Terrain|Door|Elevator|Bike|Rod|Boat|Ship|Turnback|Regi|Distortion|Giratina|LakeGuardian|PlatformLift|GymButton|GreatMarsh|Tram|Swarm|Floors|Transition)"),
    ("Pokedex, records and journal", r"([Dd]ex|Record|Journal|Score|Time|Date|Day|Clock|Hour|Save|Game|Stat|Count|Random|Heap)"),
    ("Contests, TV and minigames", r"(Contest|TV|Broadcast|Interview|Lottery|Poketch|Amity|Villa|Catching|Ranking|Radio|Show|ScratchOff|Backdrop|DressUpPhoto|Ceremony|Bonus|Starter|Furniture|NewsPress|DepartmentStore|Fateful)"),
    ("Multiplayer, mystery gift and comms", r"(Union|Comm|Wireless|Wifi|WiFi|Link|Mystery|Gift|Mix|Friend|Group|Trade|Distribution|NetID|Netw|GTS|GBACartridge)"),
    ("Unnamed commands", r"^ScrCmd_[0-9A-F]{3}$"),
]
FALLBACK_CATEGORY = "Miscellaneous"

DIRECTIVE_PREFIXES = (
    ".short", ".byte", ".long", ".word", ".if", ".else", ".endif",
    ".set", ".error", ".balign", ".align",
)


def parse_macros(path):
    """Pull every `.macro` out of an include file, keeping its `@` doc comment."""
    macros = []
    lines = open(path, encoding="utf-8").read().splitlines()
    index, pending_doc = 0, []
    while index < len(lines):
        stripped = lines[index].strip()
        header = re.match(r"\.macro\s+(\S+)\s*(.*)$", stripped)
        if header:
            body, cursor = [], index + 1
            while cursor < len(lines) and lines[cursor].strip() != ".endm":
                body.append(lines[cursor].strip())
                cursor += 1
            macros.append({
                "name": header.group(1).rstrip(","),
                "args": header.group(2).strip(),
                "body": body,
                "doc": " ".join(pending_doc).strip(),
            })
            pending_doc, index = [], cursor + 1
            continue
        if stripped.startswith("@"):
            pending_doc.append(stripped.lstrip("@ ").strip())
        elif stripped != "":
            pending_doc = []
        index += 1
    return macros


def usage_counts():
    """Count how often each command appears across the vanilla field scripts."""
    counts = collections.Counter()
    for name in os.listdir(SCRIPT_DIR):
        if not name.endswith(".s"):
            continue
        for line in open(os.path.join(SCRIPT_DIR, name), encoding="utf-8"):
            token = line.strip()
            if not token or token.startswith(("#", "@", ".", "/*")) or token.endswith(":"):
                continue
            counts[token.split()[0].rstrip(",")] += 1
    return counts


def handler_sources():
    """Map every ScrCmd_* handler to the source file that defines it."""
    sources = {}
    for dirpath, _, filenames in os.walk(os.path.join(ROOT, "src")):
        for filename in filenames:
            if not filename.endswith(".c"):
                continue
            path = os.path.join(dirpath, filename)
            relative = os.path.relpath(path, ROOT)
            text = open(path, encoding="utf-8", errors="ignore").read()
            pattern = r"^(?:static\s+)?BOOL\s+(ScrCmd_\w+)\s*\(ScriptContext"
            for match in re.finditer(pattern, text, re.M):
                sources.setdefault(match.group(1), relative)
    return sources


def command_handlers():
    """Map every SCRCMD_* opcode to its handler, from the dispatch table."""
    handlers = {}
    for line in open(CMD_TABLE, encoding="utf-8"):
        match = re.match(r"ScriptCommand\((\w+),\s*(\w+)\)", line.strip())
        if match:
            handlers[match.group(1)] = match.group(2)
    return handlers


def categorize(name):
    for category, pattern in CATEGORIES:
        if re.search(pattern, name):
            return category
    return FALLBACK_CATEGORY


def opcode_of(macro):
    for entry in macro["body"]:
        match = re.match(r"\.(?:short|byte)\s+(SCRCMD_\w+)", entry)
        if match:
            return match.group(1)
    return None


def expansion_of(macro):
    return [e for e in macro["body"] if e and not e.startswith(DIRECTIVE_PREFIXES)]


def anchor(heading):
    return heading.lower().replace(",", "").replace(" ", "-")


def write_command_reference(macros, counts, handlers, sources):
    buckets = collections.OrderedDict((c, []) for c, _ in CATEGORIES)
    buckets[FALLBACK_CATEGORY] = []
    for macro in macros:
        buckets[categorize(macro["name"])].append(macro)

    out = ["""# Field script command reference

<!-- Generated by tools/scripts/gen_script_command_reference.py; do not edit by hand. -->

Every macro in `asm/macros/scrcmd.inc`, grouped by subject.

- **Command** - the macro name, as written in a `.s` file.
- **Arguments** - the macro's parameter list; `=` marks a default value.
- **Uses** - occurrences across `res/field/scripts/*.s`. A high count means the
  command is well established and safe to copy from a vanilla script. `0` means
  nothing in the base game uses it, so read the handler before relying on it.
- **Handler** - the C function that runs the command, and the file it lives in.
  Read it when the argument names are not self-explanatory. Macros that expand
  to other macros list those instead.

`asm/macros/scrcmd.inc` stays the authoritative signature list; grep it when you
need a command's exact byte layout. For what a command *means* - its
description, its opcode, which argument it writes its result into, and what the
macros expand to - read `subprojects/scrcmd-database/platinum_v2.json`; see
[the command database](command_database.md).
"""]
    out.append(f"**{len(macros)} commands** across {len(buckets)} groups.\n")
    out.append("## Contents\n")
    for category, entries in buckets.items():
        if entries:
            out.append(f"- [{category}](#{anchor(category)}) ({len(entries)})")
    out.append("")

    for category, entries in buckets.items():
        if not entries:
            continue
        out.append(f"## {category}\n")
        out.append("| Command | Arguments | Uses | Handler |")
        out.append("| --- | --- | --- | --- |")
        for macro in sorted(entries, key=lambda m: -counts[m["name"]]):
            args = macro["args"].replace("|", "\\|") or "-"
            opcode = opcode_of(macro)
            expansion = expansion_of(macro)
            if opcode:
                handler = handlers.get(opcode)
                source = sources.get(handler)
                if handler:
                    detail = f"`{handler}`" + (f"<br>`{source}`" if source else "")
                else:
                    detail = f"`{opcode}`"
            elif expansion:
                detail = "expands to " + ", ".join(f"`{e.split()[0]}`" for e in expansion[:4])
                if len(expansion) > 4:
                    detail += ", ..."
            else:
                detail = "assembler directive"
            if macro["doc"]:
                detail += f" {macro['doc']}"
            out.append(f"| `{macro['name']}` | `{args}` | {counts[macro['name']]} | {detail} |")
        out.append("")

    path = os.path.join(OUT_DIR, "command_reference.md")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    return path, buckets


DIRECTIONS = ["North", "South", "East", "West"]


def write_movement_reference(macros, counts):
    """Movement macros are one family per speed/action, times four directions."""
    families = collections.OrderedDict()
    standalone = []
    for macro in macros:
        name = macro["name"]
        base = re.sub(r"(North|South|East|West)$", "", name)
        if base != name:
            families.setdefault(base, {})[name[len(base):]] = macro
        else:
            standalone.append(macro)

    out = ["""# Movement action reference

<!-- Generated by tools/scripts/gen_script_command_reference.py; do not edit by hand. -->

Movement macros come from `asm/macros/movement.inc`. They are only legal inside
a movement block - a label that `ApplyMovement` points at, terminated by
`EndMovement`:

```asm
    .balign 4, 0
MyMap_Movement_WalkUpAndFacePlayer:
    WalkNormalNorth 3
    FaceSouth
    EndMovement
```

Every movement macro takes an optional repeat count, defaulting to `1`, so
`WalkNormalNorth 3` walks three tiles north. Directional families are listed as
one row across the four directions; append the direction to the family name.

Uses are counted across all four directions of a family, over
`res/field/scripts/*.s`. `subprojects/scrcmd-database/platinum_v2.json`
describes what each action looks like on screen; see
[the command database](command_database.md).
"""]

    out.append("## Directional families\n")
    out.append("| Family | Directions | Uses | Notes |")
    out.append("| --- | --- | --- | --- |")
    rows = []
    for base, members in families.items():
        total = sum(counts[m["name"]] for m in members.values())
        present = [d for d in DIRECTIONS if d in members]
        missing = [d for d in DIRECTIONS if d not in members]
        note = "all four" if not missing else "only " + ", ".join(present)
        rows.append((total, f"| `{base}…` | {', '.join(present)} | {total} | {note} |"))
    for _, row in sorted(rows, key=lambda r: -r[0]):
        out.append(row)
    out.append("")

    out.append("## Non-directional actions\n")
    out.append("| Action | Arguments | Uses |")
    out.append("| --- | --- | --- |")
    for macro in sorted(standalone, key=lambda m: -counts[m["name"]]):
        args = macro["args"] or "-"
        out.append(f"| `{macro['name']}` | `{args}` | {counts[macro['name']]} |")
    out.append("")

    path = os.path.join(OUT_DIR, "movement_reference.md")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    return path


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    counts = usage_counts()
    command_path, buckets = write_command_reference(
        parse_macros(SCRCMD_INC), counts, command_handlers(), handler_sources()
    )
    movement_path = write_movement_reference(parse_macros(MOVEMENT_INC), counts)
    for path in (command_path, movement_path):
        print(f"wrote {os.path.relpath(path, ROOT)}")
    for category, entries in buckets.items():
        if entries:
            print(f"  {len(entries):4d}  {category}")


if __name__ == "__main__":
    main()
