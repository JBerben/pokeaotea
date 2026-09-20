# Field script tooling

In-house tools for working on field scripts. All live in `tools/scripts/`, are
plain Python with no dependencies, and read the repo directly - none of them
need a configured build except where noted.

| Tool | Answers |
| --- | --- |
| [`new_map.py`](#new_mappy) | scaffold a new map, fully wired into the build |
| [`map_info.py`](#map_infopy) | how is this map wired, and what is entry 7? |
| [`lint_field_scripts.py`](#lint_field_scriptspy) | did I break something invisible? |
| [`check_warps.py`](#check_warpspy) | does every door lead somewhere real? |
| [`check_tile.py`](#check_tilepy) | can an NPC stand here? |
| [`find_free_state.py`](#find_free_statepy) | which flag or variable can I safely claim? |
| [`gen_script_command_reference.py`](#generated-references) | regenerate the command docs |
| [`check_script_doc_snippets.py`](#generated-references) | do the doc examples still assemble? |

Four of them run automatically as part of `make check` - see
[continuous checks](#continuous-checks).

They share [`fieldscript.py`](#fieldscriptpy), a small parsing library, so new
tools do not have to re-derive the file formats.

## `new_map.py`

```
$ python3 tools/scripts/new_map.py sunrise_hollow --header --dry-run
  create  res/field/scripts/scripts_sunrise_hollow.s
  create  res/field/scripts/scripts_init_sunrise_hollow.s
  create  res/text/sunrise_hollow.json
  create  res/field/events/events_sunrise_hollow.json
  edit    res/field/scripts/meson.build      (scr_seq_files += 2)
  edit    res/field/scripts/scripts.order    (+2 entries, same order as meson)
  edit    res/field/events/meson.build       (events_files += 1)
  edit    res/field/events/zone_event.order  (+1 entry (CRLF))
  edit    generated/text_banks.txt           (TEXT_BANK_SUNRISE_HOLLOW)
  edit    generated/map_headers.txt          (before MAP_HEADER_COUNT)
  edit    include/data/map_headers.h         (geometry from the template)
```

Adding a map by hand means eleven edits across nine files, two of which must
stay in exactly the same order, one of which uses CRLF line endings. Missing
one fails the build somewhere unrelated. This does all of it, or nothing: the
tool builds the whole plan first and refuses if any target already exists, so a
half-wired map is not a state you can reach.

`--header` also creates the map header, copying the geometry fields (map
matrix, area data, music, weather) from `--like` (default: a small interior).
The new map is therefore immediately buildable and walkable - a playable copy
of the template's layout - and you swap `.mapMatrixID` and
`.areaDataArchiveID` when you have your own geometry. Without `--header` the
resources are wired but nothing points at them yet.

Always `--dry-run` first. Afterwards, `make rom`, then `map_info.py <name>` to
confirm the whole chain resolved.

## `map_info.py`

```
$ python3 tools/scripts/map_info.py twinleaf_town
MAP_HEADER_TWINLEAF_TOWN

  scripts       scripts_twinleaf_town.s
  init scripts  scripts_init_twinleaf_town
  text bank     TEXT_BANK_TWINLEAF_TOWN
  events        events_twinleaf_town

entry table (10 entries)

    1  TwinleafTown_OnTransition          init script, on transition
    2  TwinleafTown_CoordEvent_RivalThud  coord event 2 (VAR_..._RIVAL_TRIGGER_STATE==0)
    3  TwinleafTown_Guitarist             LOCALID_GUITARIST
   ...
   10  TwinleafTown_Rancher               LOCALID_RANCHER

  next free index: 11 (append only)
```

The right-hand column is the one to read: it resolves, for each entry, what
actually reaches it - an object event, a coord event with its trigger
condition, a bg event, or an init-script hook. An entry marked *not referenced
from events or init* is either dead or driven from C (dynamic maps such as the
Distortion World work that way).

`--state` additionally lists every flag and variable the script touches, which
is the quickest way to see what state a map already owns before adding more.

## `lint_field_scripts.py`

```
$ python3 tools/scripts/lint_field_scripts.py                  # the whole game
$ python3 tools/scripts/lint_field_scripts.py twinleaf_town    # one map
```

Catches the failures that do not show up until you load the map. Exits 0 clean,
1 with findings.

| Check | Catches |
| --- | --- |
| `labels` | an entry or branch target that is not defined; `ApplyMovement` aimed at something that is not a movement block; a movement block that follows script code without `.balign 4, 0` |
| `messages` | a message id that is not in any text bank the script includes |
| `events` | a script index in `events_*.json` or `scripts_init_*.s` that runs past the end of the entry table - the off-by-one that silently rewires a map |
| `locks` | a script that takes control from the player where nothing reachable gives it back, and which does not hand off via a warp or a battle |

Run against all 574 vanilla script files it reports exactly two findings, both
real:

- `scripts_oreburgh_city` has a bg event pointing at script 45 when that map's
  table has 22 entries - a dangling reference inherited from the base game.
- `DistortionWorldB7F_OnFrame_FirstEntry` locks the player with no reachable
  release and no hand-off. Vanilla behaviour; noted here so it is not mistaken
  for your own bug.

That low false-positive rate is the point; a linter that cries wolf gets
ignored. Two things earn it. The `locks` check derives which commands take and
give back control by expanding the macros in `asm/macros/scrcmd.inc`
transitively, so a composite like `NPCMessage` is correctly seen to balance
itself. And the reachability model follows fall-through - in assembly, a label
whose last command is not `End`, `Return` or `GoTo` runs straight on into the
next label, which vanilla relies on constantly.

### `--check locks-strict`

An opt-in, stricter version: flag *any* path that reaches `End` while still
locked. That is the semantically correct question, but it over-reports, because
the standard idiom is a ladder of `GoToIfEq` covering every case with an
unreachable `End` after it as a safety net:

```asm
    GetPlayerMapPos VAR_0x8004, VAR_0x8005
    GoToIfEq VAR_0x8004, 110, MyMap_AtX110
    GoToIfEq VAR_0x8004, 111, MyMap_AtX111
    End                      @ cannot be reached, but the linter cannot know
```

Across the whole game it reports 240 of these. Aimed at one map you just wrote,
where you know which ladders are exhaustive, it is a useful audit.

## `check_warps.py`

```
$ python3 tools/scripts/check_warps.py
1213 warp(s) checked, 0 finding(s)
```

A warp names a destination header and an index into *that* map's warp list.
Both go stale silently when maps are edited - nothing fails the build, you just
walk into a door and end up somewhere wrong. This checks that the destination
header exists, that it has an events file, and that the warp index is in range.

`MAP_HEADER_DYNAMIC` is accepted; elevators set their destination at runtime.
`--one-way` lists warps whose destination does not lead back, which is legal
and used deliberately in the base game, so it is reported separately as
information rather than as a finding.

Vanilla is clean on all 1213 warps, so anything it reports on your content is
worth acting on.

## `check_tile.py`

```
$ python3 tools/scripts/check_tile.py MAP_HEADER_TWINLEAF_TOWN 112 888 --map 6
(112,888): walkable  collision=0  TILE_BEHAVIOR_NONE
```

Decodes the same terrain grid the engine reads, so you can confirm an object
event's tile before loading the map. See
[placing an object event](README.md#placing-an-object-event).

## `find_free_state.py`

```
$ python3 tools/scripts/find_free_state.py --check FLAG_DEFEATED_TRAINER_YOUNGSTER_SEBASTIAN
FLAG_DEFEATED_TRAINER_YOUNGSTER_SEBASTIAN: RESERVED - indexed as TRAINER_DEFEATED_FLAGS_START + trainer id

$ python3 tools/scripts/find_free_state.py --check FLAG_UNUSED_0x0094
FLAG_UNUSED_0x0094: free to claim (general range, line 151 of generated/vars_flags.txt)
```

Finding a spare flag by grepping for one nothing mentions is actively
dangerous, because several ranges are addressed by arithmetic rather than by
name. `TRAINER_DEFEATED_FLAGS_START + trainerID` means all 930 defeated-trainer
flags look unreferenced while being very much in use; claiming one corrupts an
unrelated trainer. Flag 0 is worse: `events_*.json` writes `hidden_flag: "0"`
1943 times to mean *not hidden*, so flag 0 must always read false.

This tool knows the ranges, offers names only from the general pool, and
prefers the ones the base game already marks spare. Run `--ranges` to see every
reserved region and why. Currently 1582 flags and 27 variables are genuinely
free.

Claim a name by **renaming it in place**. Never insert or reorder entries -
position in the file is the numeric value, and save data depends on it.

## Continuous checks

`make check` runs four of these as meson tests, in about two seconds total:

```
pokeplatinum:Field Scripts - Lint                  OK   0.44s
pokeplatinum:Field Scripts - Warp Connectivity     OK   0.10s
pokeplatinum:Field Scripts - Tool Unit Tests       OK   0.08s
pokeplatinum:Field Scripts - Doc Examples Assemble OK   1.20s
```

The lint test is green because `tools/scripts/lint_baseline.txt` accepts the two
findings inherited from the base game. That keeps the test meaningful - it fails
on anything *new* - while leaving the inherited ones visible via
`lint_field_scripts.py --no-baseline`. Add to the baseline only for findings you
have decided to live with, and say why in the file.

## Generated references

`gen_script_command_reference.py` rebuilds
[`command_reference.md`](command_reference.md) and
[`movement_reference.md`](movement_reference.md) from `asm/macros/*.inc`. Run it
after adding or changing a macro.

`check_script_doc_snippets.py` assembles and links every example in
[`README.md`](README.md) and [`patterns.md`](patterns.md) with the real
toolchain, so a signature change cannot silently invalidate the docs. This one
needs a configured build directory.

## `fieldscript.py`

The shared library, not a command. It parses a script into its entry table,
labels and commands, models fall-through, resolves map header to script file /
text bank / events file, and derives lock-and-release effects from the macro
definitions. Build new tools on it rather than re-parsing:

```python
import fieldscript as fs

script = fs.parse_script("res/field/scripts/scripts_twinleaf_town.s")
script.entry_index("TwinleafTown_Rancher")      # -> 10
script.reachable_from("TwinleafTown_Guitarist") # every label it can reach
fs.macro_effects()["NPCMessage"]                # -> (locks, releases)
```

## Tests

```
python3 -m unittest tools.scripts.test_lint_field_scripts
```

21 tests covering each check, including the cases that used to be false
positives: fall-through into a releasing label, `NPCMessage` balancing itself,
locking then warping away, consecutive movement blocks needing only one
`.balign`, and shared script-ID ranges in both events and init scripts.
