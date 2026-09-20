"""Shared parsing for field scripts, for the tools in this directory.

Nothing here builds anything; it just reads the repo and answers the questions
the script tools keep needing:

    parse_script(path)        -> Script: entry table, labels, commands
    macro_effects()           -> which commands lock/release, expanded
    map_wiring()              -> map header -> script / text bank / events files
    load_text_bank(name)      -> message id -> index
    load_events(name)         -> the events JSON

Scripts are parsed textually rather than preprocessed. That is enough for
structure, and it keeps the tools runnable without a configured build.
"""

import json
import os
import re
from collections import OrderedDict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

SCRIPT_DIR = os.path.join(ROOT, "res/field/scripts")
EVENTS_DIR = os.path.join(ROOT, "res/field/events")
TEXT_DIR = os.path.join(ROOT, "res/text")
SCRCMD_INC = os.path.join(ROOT, "asm/macros/scrcmd.inc")
MOVEMENT_INC = os.path.join(ROOT, "asm/macros/movement.inc")
MAP_HEADERS = os.path.join(ROOT, "include/data/map_headers.h")

# Commands whose final argument is a label in the same file.
BRANCH_COMMANDS = re.compile(r"^(GoTo|Call)(If\w+)?$")
MOVEMENT_COMMANDS = re.compile(r"^(ApplyMovement|ApplyFreeCameraMovement)$")
# Commands that stop the current script running on.
TERMINATORS = {"End", "Return", "ReturnCommonScript"}
# ...plus these, which end a block without execution continuing into the next
# label. Anything else falls through, exactly as the assembled bytecode does.
BLOCK_ENDERS = TERMINATORS | {"EndMovement", "GoTo"}


class Command:
    __slots__ = ("name", "args", "line")

    def __init__(self, name, args, line):
        self.name = name
        self.args = args
        self.line = line

    @property
    def target(self):
        """The label this command branches to, if it branches."""
        if BRANCH_COMMANDS.match(self.name) or MOVEMENT_COMMANDS.match(self.name):
            return self.args[-1] if self.args else None
        return None

    def __repr__(self):
        return f"{self.name} {', '.join(self.args)}".strip()


class Script:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.stem = self.name[:-2] if self.name.endswith(".s") else self.name
        self.includes = []
        self.defines = {}
        self.entries = []            # entry-table labels, in table order
        self.labels = OrderedDict()  # label -> [Command]
        self.label_lines = {}        # label -> line number
        self.aligned = set()         # labels preceded by .balign
        self.init_entries = []       # (macro, argument, line) for init scripts

    def entry_index(self, label):
        """1-based position in the entry table, or None."""
        return self.entries.index(label) + 1 if label in self.entries else None

    def is_movement_block(self, label):
        body = self.labels.get(label)
        return bool(body) and body[-1].name == "EndMovement"

    @property
    def order(self):
        """Labels in the order they appear in the file."""
        return list(self.labels)

    def needs_align(self, label):
        """A movement block needs .balign only when it follows script code.

        Every movement action assembles to 4 bytes, so a block that directly
        follows another movement block is already aligned.
        """
        if not self.is_movement_block(label):
            return False
        order = self.order
        index = order.index(label)
        if index == 0:
            return True
        return not self.is_movement_block(order[index - 1])

    def falls_through(self, label):
        """Does execution run on into the next label, as the bytecode would?"""
        body = self.labels.get(label)
        if not body:
            return True
        return body[-1].name not in BLOCK_ENDERS

    def next_label(self, label):
        order = self.order
        index = order.index(label)
        return order[index + 1] if index + 1 < len(order) else None

    def reachable_from(self, label, _seen=None):
        """Every label reachable from `label`, following branches and
        fall-through into the next label, as the assembled script does."""
        seen = _seen if _seen is not None else set()
        if label in seen or label not in self.labels:
            return seen
        seen.add(label)
        for command in self.labels[label]:
            target = command.target
            if target and not MOVEMENT_COMMANDS.match(command.name):
                self.reachable_from(target, seen)
        if self.falls_through(label):
            following = self.next_label(label)
            if following:
                self.reachable_from(following, seen)
        return seen


def _strip_comment(line):
    line = re.sub(r"/\*.*?\*/", " ", line)
    # These files comment with @, and occasionally with // or /* */.
    line = line.split("//")[0]
    return line.split("@")[0].rstrip()


def parse_script(path):
    script = Script(path)
    pending_align = False
    in_table = False
    table_done = False

    with open(path, encoding="utf-8") as handle:
        lines = handle.readlines()

    for number, raw in enumerate(lines, 1):
        line = _strip_comment(raw).strip()
        if not line:
            continue

        if line.startswith("#include"):
            match = re.search(r'"([^"]+)"', line)
            if match:
                script.includes.append(match.group(1))
            continue
        if line.startswith("#define"):
            parts = line.split(None, 2)
            if len(parts) == 3:
                script.defines[parts[1]] = parts[2].strip()
            continue
        if line.startswith("#"):
            continue

        if line.startswith(".balign") or line.startswith(".align"):
            pending_align = True
            continue
        if line.startswith("."):
            continue

        label = re.match(r"^(\w+):$", line)
        if label:
            current = label.group(1)
            script.labels[current] = []
            script.label_lines[current] = number
            if pending_align:
                script.aligned.add(current)
            pending_align = False
            continue

        parts = line.split(None, 1)
        name = parts[0]
        args = [a.strip() for a in parts[1].split(",")] if len(parts) > 1 else []
        # `GoToIfBadgeAcquired badge label` separates its last arg with a space.
        if args and " " in args[-1] and BRANCH_COMMANDS.match(name) is None:
            pass

        if name == "ScriptEntry" and not table_done:
            in_table = True
            script.entries.append(args[0] if args else "")
            continue
        if name == "ScriptEntryEnd":
            in_table, table_done = False, True
            continue
        if name.startswith("InitScript"):
            script.init_entries.append((name, args[0] if args else None, number))
            continue

        if script.labels:
            script.labels[next(reversed(script.labels))].append(
                Command(name, args, number))
        pending_align = False

    return script


def _macro_bodies(path):
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    bodies, index = {}, 0
    while index < len(lines):
        header = re.match(r"\.macro\s+(\S+)", lines[index].strip())
        if header:
            body, cursor = [], index + 1
            while cursor < len(lines) and lines[cursor].strip() != ".endm":
                body.append(lines[cursor].strip())
                cursor += 1
            bodies[header.group(1).rstrip(",")] = body
            index = cursor
        index += 1
    return bodies


_EFFECTS = None


def macro_effects():
    """For every command: does it lock, and does it release?

    Composite macros (NPCMessage, PokeMartCommonWithGreeting, ...) are expanded
    transitively, so a macro that locks and releases internally reports both.
    """
    global _EFFECTS
    if _EFFECTS is not None:
        return _EFFECTS

    bodies = _macro_bodies(SCRCMD_INC)
    cache = {}

    def effects(name, stack=()):
        if name in cache:
            return cache[name]
        if name in stack:                       # defensive; macros do not recurse
            return (False, False)
        locks = name in ("LockAll", "LockObject")
        releases = name in ("ReleaseAll", "ReleaseObject")
        for entry in bodies.get(name, []):
            if not entry or entry.startswith("."):
                continue
            inner = entry.split()[0].rstrip(",")
            if inner in bodies:
                inner_lock, inner_release = effects(inner, stack + (name,))
                locks, releases = locks or inner_lock, releases or inner_release
        cache[name] = (locks, releases)
        return cache[name]

    for macro in bodies:
        effects(macro)
    _EFFECTS = cache
    return cache


_WIRING = None


def map_wiring():
    """map header -> the resource symbols it points at."""
    global _WIRING
    if _WIRING is not None:
        return _WIRING

    with open(MAP_HEADERS, encoding="utf-8") as handle:
        text = handle.read()
    wiring = {}
    pattern = re.compile(r"\[(MAP_HEADER_\w+)\]\s*=\s*\{(.*?)\n    \}", re.S)
    for match in pattern.finditer(text):
        fields = dict(re.findall(r"\.(\w+)\s*=\s*([A-Za-z_]\w*)", match.group(2)))
        wiring[match.group(1)] = fields
    _WIRING = wiring
    return wiring


def text_bank_path(bank_constant):
    """TEXT_BANK_TWINLEAF_TOWN -> res/text/twinleaf_town.json"""
    name = bank_constant.replace("TEXT_BANK_", "").lower()
    path = os.path.join(TEXT_DIR, name + ".json")
    return path if os.path.exists(path) else None


def load_text_bank(bank_constant):
    """message id -> index, or None when the bank is generated at build time."""
    path = text_bank_path(bank_constant)
    if not path:
        return None
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return {m["id"]: i for i, m in enumerate(data["messages"])}


def load_events(events_symbol):
    path = os.path.join(EVENTS_DIR, events_symbol + ".json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def script_path(script_symbol):
    path = os.path.join(SCRIPT_DIR, script_symbol + ".s")
    return path if os.path.exists(path) else None


def all_script_paths():
    return sorted(
        os.path.join(SCRIPT_DIR, name)
        for name in os.listdir(SCRIPT_DIR)
        if name.endswith(".s")
    )
