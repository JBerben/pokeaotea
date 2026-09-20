#!/usr/bin/env python3
"""Check field scripts for the mistakes that are invisible until you play.

    python3 tools/scripts/lint_field_scripts.py                 # every map
    python3 tools/scripts/lint_field_scripts.py twinleaf_town   # one map
    python3 tools/scripts/lint_field_scripts.py --check locks-strict twinleaf_town

Checks, all on by default except `locks-strict`:

  labels        entry-table and branch targets exist; movement blocks that are
                actually used are aligned and end in EndMovement
  messages      every message id a script prints exists in a text bank the
                script includes
  events        every script index in events_*.json and scripts_init_*.s points
                at a real entry, or at a valid shared-script range
  locks         a script takes control away from the player and nothing
                reachable ever gives it back. High confidence: one finding
                across the whole vanilla game.

  locks-strict  *some* path reaches End while still locked. This is the right
                semantic but over-reports, because the usual idiom is a ladder
                of GoToIfEq covering every case with an unreachable End after
                it as a safety net. Useful aimed at one map you just wrote;
                noisy across the whole game. Opt in with --check locks-strict.

Exit status is 0 when clean, 1 when anything is reported, 2 on a usage error.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fieldscript as fs  # noqa: E402

# Below this, a script index addresses the map's own entry table; at or above
# it the engine routes to a shared script file (see include/script_manager.h).
LOCAL_SCRIPT_LIMIT = 2000
NO_SCRIPT = (0, 65535)

# Commands after which the script is expected to end without releasing: control
# comes back via a new map, a battle, or the field task that replaces it.
HAND_OFF = {"ReturnToField", "BlackOutFromBattle", "StartTrainerBattle"}

MESSAGE_COMMANDS = {
    "Message", "MessageInstant", "MessageNoSkip", "MessageSynchronized",
    "NPCMessage", "EventMessage", "MessageAutoScroll", "MessageUnown",
    "ShowMapSign", "ShowArrowSign", "ShowLandmarkSign", "ShowScrollingSign",
    "DrawSignpostInstantMessage", "DrawSignpostScrollingMessage",
}

DEFAULT_CHECKS = ("labels", "messages", "events", "locks")
ALL_CHECKS = DEFAULT_CHECKS + ("locks-strict",)

# Findings inherited from the base game, accepted so the check can run green in
# CI and still catch anything new. Matched on file and message, ignoring line
# numbers so unrelated edits do not break the match.
DEFAULT_BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "lint_baseline.txt")


def load_baseline(path):
    if not path or not os.path.exists(path):
        return set()
    accepted = set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            where, _, message = text.partition("::")
            accepted.add((where.strip(), message.strip()))
    return accepted


def hands_off(name):
    return name in HAND_OFF or "Warp" in name


class Report:
    def __init__(self):
        self._seen = set()
        self.findings = []

    def add(self, where, line, message):
        key = (where, line, message)
        if key in self._seen:
            return
        self._seen.add(key)
        self.findings.append(key)

    def __len__(self):
        return len(self.findings)


def check_labels(script, report):
    for position, label in enumerate(script.entries, 1):
        if label not in script.labels:
            report.add(script.name, None,
                       f"entry {position} names {label}, which is not defined")

    used_as_movement = set()
    for body in script.labels.values():
        for command in body:
            target = command.target
            if target is None or target in script.defines:
                continue
            if target not in script.labels:
                report.add(script.name, command.line,
                           f"{command.name} targets {target}, which is not defined")
                continue
            if fs.MOVEMENT_COMMANDS.match(command.name):
                used_as_movement.add(target)
                if not script.is_movement_block(target):
                    report.add(script.name, command.line,
                               f"{command.name} targets {target}, which does not "
                               "end in EndMovement")

    for label in used_as_movement:
        if script.needs_align(label) and label not in script.aligned:
            report.add(script.name, script.label_lines[label],
                       f"movement block {label} follows script code and is not "
                       "preceded by .balign 4, 0")


def check_messages(script, bank, report):
    if bank is None:
        return
    for body in script.labels.values():
        for command in body:
            if command.name not in MESSAGE_COMMANDS or not command.args:
                continue
            message_id = command.args[0]
            if (message_id in script.defines
                    or message_id.lstrip("-").isdigit()
                    or message_id.startswith(("VAR_", "FR_VAR_"))):
                continue
            if message_id not in bank:
                report.add(script.name, command.line,
                           f"{command.name} prints {message_id}, which is not in "
                           "any text bank this script includes")


def _local_index_problem(index, count):
    """None if this script index is fine, else why it is not."""
    if not isinstance(index, int) or index in NO_SCRIPT:
        return None
    if index >= LOCAL_SCRIPT_LIMIT:
        return None                      # routed to a shared script file
    if index > count:
        return f"script {index}, but the table has only {count} entries"
    return None


def check_events(script, events, init_script, report):
    count = len(script.entries)

    if events:
        for section in ("object_events", "coord_events", "bg_events"):
            for item in events.get(section, []):
                problem = _local_index_problem(item.get("script"), count)
                if problem:
                    name = item.get("id") or f"{section} entry"
                    report.add(f"{script.stem} events", None,
                               f"{name} uses {problem}")

    if init_script:
        for macro, argument, line in init_script.init_entries:
            if not macro.startswith("InitScriptEntry_On"):
                continue
            if macro.endswith("OnFrameTable") or argument is None:
                continue
            if not argument.isdigit():
                continue                 # a symbolic shared-script constant
            problem = _local_index_problem(int(argument), count)
            if problem:
                report.add(init_script.name, line,
                           f"{macro} runs {problem} in {script.name}")


def _commands_reachable(script, label):
    return [command
            for reachable in script.reachable_from(label)
            for command in script.labels.get(reachable, [])]


def check_locks(script, report):
    """Conservative: the script locks and nothing reachable ever releases."""
    effects = fs.macro_effects()
    for label in script.entries:
        commands = _commands_reachable(script, label)
        locks = any(effects.get(c.name, (0, 0))[0] for c in commands)
        releases = any(effects.get(c.name, (0, 0))[1] for c in commands)
        if locks and not releases and not any(hands_off(c.name) for c in commands):
            report.add(script.name, script.label_lines.get(label),
                       f"{label} locks the player but nothing reachable from it "
                       "releases; no ReleaseAll and no warp or battle hand-off")


def check_locks_strict(script, report):
    """Every path: flag an End reached while still locked."""
    effects = fs.macro_effects()

    def walk(label, locked, seen):
        if label not in script.labels or (label, locked) in seen:
            return
        seen = seen | {(label, locked)}

        for command in script.labels[label]:
            takes, gives = effects.get(command.name, (False, False))
            if takes:
                locked = True
            if gives or hands_off(command.name):
                locked = False

            name, target = command.name, command.target
            if fs.MOVEMENT_COMMANDS.match(name):
                continue
            if name.startswith("Call") and target:
                # A subroutine that can release leaves us unlocked afterwards.
                if any(effects.get(c.name, (0, 0))[1]
                       for c in _commands_reachable(script, target)):
                    locked = False
                continue
            if name.startswith("GoTo") and target:
                walk(target, locked, seen)
                if name == "GoTo":
                    return               # unconditional; nothing after it runs
                continue
            if name in fs.TERMINATORS:
                if name == "End" and locked:
                    report.add(script.name, command.line,
                               f"{label} reaches End while still locked")
                return

        following = script.next_label(label)
        if script.falls_through(label) and following:
            walk(following, locked, seen)

    for label in script.entries:
        walk(label, False, frozenset())


def wiring_for(script_stem):
    for header, fields in fs.map_wiring().items():
        if fields.get("scriptsArchiveID") == script_stem:
            return header, fields
    return None, {}


def lint(path, checks, report):
    script = fs.parse_script(path)
    _, fields = wiring_for(script.stem)

    if "labels" in checks:
        check_labels(script, report)
    if "locks" in checks:
        check_locks(script, report)
    if "locks-strict" in checks:
        check_locks_strict(script, report)
    if "messages" in checks:
        bank, found_any = {}, False
        for include in script.includes:
            if include.startswith("res/text/bank/"):
                name = os.path.basename(include)[:-2]
                loaded = fs.load_text_bank("TEXT_BANK_" + name.upper())
                if loaded is not None:
                    bank.update(loaded)
                    found_any = True
        check_messages(script, bank if found_any else None, report)
    if "events" in checks:
        events_symbol = fields.get("eventsArchiveID")
        events = fs.load_events(events_symbol) if events_symbol else None
        init_symbol = fields.get("initScriptsArchiveID")
        init_path = fs.script_path(init_symbol) if init_symbol else None
        init_script = fs.parse_script(init_path) if init_path else None
        check_events(script, events, init_script, report)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("maps", nargs="*",
                        help="map names to check (default: all)")
    parser.add_argument("--check", action="append", choices=ALL_CHECKS,
                        help="run only these checks (repeatable)")
    parser.add_argument("--quiet", action="store_true",
                        help="print findings only, no summary")
    parser.add_argument("--no-baseline", action="store_true",
                        help="also report findings inherited from the base game")
    args = parser.parse_args()
    checks = set(args.check or DEFAULT_CHECKS)
    baseline = set() if args.no_baseline else load_baseline(DEFAULT_BASELINE)

    paths = [p for p in fs.all_script_paths()
             if not os.path.basename(p).startswith("scripts_init_")]
    if args.maps:
        wanted = {m if m.startswith("scripts_") else "scripts_" + m
                  for m in args.maps}
        paths = [p for p in paths if os.path.basename(p)[:-2] in wanted]
        if not paths:
            print(f"error: no script files match {args.maps}", file=sys.stderr)
            return 2

    report = Report()
    for path in paths:
        lint(path, checks, report)

    shown, suppressed = [], 0
    for where, line, message in report.findings:
        if (where, message) in baseline:
            suppressed += 1
            continue
        shown.append(f"{where}:{line}: {message}" if line
                     else f"{where}: {message}")

    for entry in shown:
        print(entry)

    if not args.quiet:
        note = f", {suppressed} accepted from the base game" if suppressed else ""
        print(f"\n{len(paths)} script file(s), {len(shown)} finding(s){note}",
              file=sys.stderr)
    return 1 if shown else 0


if __name__ == "__main__":
    sys.exit(main())
