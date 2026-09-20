# The script command database

`subprojects/scrcmd-database/` is a submodule holding a machine-readable
description of every Gen 4 script command: opcode numbers, parameter names and
types, what each command does, which parameter it writes its answer into, and
what the convenience macros expand to. It is maintained alongside DSPRE and
synced from the pret decompilations, and it is the reference to reach for when
you need to know what a command *means*.

Use **`subprojects/scrcmd-database/platinum_v2.json`**. The other files in that
repo are for other games (`diamond_pearl_v2.json`, `hgss_v2.json`), for other
hacks (`custom_databases/`), or are the legacy DSPRE format
(`*_scrcmd_database.json`), which is kept only for compatibility and should not
be read here.

```bash
git submodule update --init subprojects/scrcmd-database
```

## What it is authoritative for, and what it is not

The database and the macro files (`asm/macros/scrcmd.inc` for commands,
`asm/macros/movement.inc` for movement actions) describe the same 1110 entries,
and they agree on every name. They answer different questions, so neither
replaces the other:

| Question | Read |
| --- | --- |
| How do I spell this command in a `.s` file, and in what argument order? | `asm/macros/scrcmd.inc` and [command_reference.md](command_reference.md) |
| What does this command actually do? | the database's `description` and `notes` |
| Which argument does it write its result into? | the database's `access` metadata |
| Is this argument a literal, a variable, or either? | the database's parameter `type` |
| What opcode does it assemble to? | the database's `id` |
| What does this macro expand to? | the database's `expansion` |
| What does the engine do on the C side? | the handler named in [command_reference.md](command_reference.md) |

`asm/macros/scrcmd.inc` stays the last word on **signatures**, because it is
what the assembler reads. The database stays the last word on **semantics**,
because the macro file carries none. Where the two disagree on an argument
list, the macro wins - see [accuracy](#accuracy-and-known-gaps) below.

## The shape of an entry

Every command is a key in the top-level `commands` object.

```json
"AddItem": {
  "type": "script_cmd",
  "id": 123,
  "legacy_name": "GiveItem",
  "description": "If the player has no space left in the bag, destVarID will be set to FALSE",
  "notes": "The quantity of any single item slot is capped at 999 (99 for TM/HM items). Berry and TM/HM pockets are sorted after adding.",
  "params": [
    { "name": "item", "type": "flex", "access": "read" },
    { "name": "amount", "type": "flex", "access": "read" },
    { "name": "destVarID", "type": "var", "default": "VAR_RESULT", "access": "must_write" }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `type` | `script_cmd`, `movement` or `macro` |
| `id` | the opcode, absent for macros (they have no opcode of their own) |
| `legacy_name` | the DSPRE name, for cross-referencing older notes and the community spreadsheet |
| `description` | one line on what the command does |
| `notes` | the caveat that costs you an afternoon: alignment rules, caps, edge cases |
| `params` | the argument list, in order |
| `expansion` | for macros, the commands they assemble into |
| `variants` | for commands whose argument list depends on a mode argument |

`legacy_name` is worth knowing about: most outside writing on Gen 4 scripting,
including the community spreadsheet linked from the submodule's README, uses
those names. `AddItem` is `GiveItem` there, `ApplyMovement` is `Movement`,
`BufferPlayerName` is `TextPlayerName`.

### Parameter types

| Type | Means |
| --- | --- |
| `flex` | either a literal value **or** a variable ID; the engine decides at runtime |
| `var` | a variable ID |
| `flag` | a flag ID |
| `label` | a branch target, written as a label in a `.s` file |
| `msg_id` | a message ID from the map's text bank |
| `u8`, `u16`, `u32` | a plain unsigned literal |
| `map_id`, `item`, `species`, `trainer_id` | a literal from that constant set |

`flex` is the one to internalise. It is why `AddItem ITEM_POTION, 1` and
`AddItem VAR_0x8004, VAR_0x8005` are both legal, and it covers 361 of the 1432
parameters in the file.

### `access`: which parameter gets written

This is the field that saves the most time, because the alternative is reading
the C handler to find out where a command leaves its answer.

| `access` | Means |
| --- | --- |
| `read` | the command reads this parameter |
| `must_write` | the command always writes its result here |
| `may_write` | the command writes here on some paths only |
| `read_must_write` / `read_may_write` | both |
| `none` | the parameter is ignored |

```json
"GetPlayerMapPos": {
  "id": 105,
  "params": [
    { "name": "destVarIDX", "type": "var", "access": "must_write" },
    { "name": "destVarIDZ", "type": "var", "access": "must_write" }
  ]
}
```

Coverage is partial and being filled in upstream: 475 of 1432 parameters carry
it, spanning opcodes 3 to 497. A missing `access` field means "not yet
annotated", not "not written". For anything above opcode 497, read the handler.

### Macros and their expansions

A `macro` entry has no opcode and instead lists what it becomes. This is how to
answer "does this thing lock the player" without tracing `.inc` files by hand:

```json
"NPCMessage": {
  "type": "macro",
  "params": [{ "name": "messageID", "type": "msg_id" }],
  "expansion": [
    "PlaySE SE_CONFIRM_sseq_3", "LockAll", "FacePlayer", "Message $messageID",
    "WaitButton", "CloseMessage", "ReleaseAll"
  ]
}
```

110 of the 1111 entries carry an `expansion`.

### Variants

Twelve commands take a mode argument that changes the rest of the argument
list. Those carry a `variants` **array**, each element holding either a `const`
that selects it or a `condition` that guards it:

```json
"DoStrengthFunc": {
  "variants": [
    { "params": [{ "name": "mode", "type": "u8", "const": "0" }],
      "desc": "Disables Strength so player can no longer move boulders" },
    { "params": [{ "name": "mode", "type": "u8", "const": "1" }],
      "desc": "Allows the player to automatically move Strength boulders" },
    { "params": [{ "name": "mode", "type": "u8", "const": "2" },
                 { "name": "result", "type": "var" }],
      "desc": "Checks if Strength is activated, store answer in Variable" }
  ]
}
```

The submodule's own README documents `variants` as an object keyed by mode
number. The file actually ships an array. Trust the file.

## Flags, variables and sounds

Beyond `commands`, `platinum_v2.json` carries `flags` (4098), `vars` (315),
`sounds` (1013), `overworld_directions` and `special_overworlds`.

The flags and vars are **synced from this repo**. Every ID in them matches the
value `generated/vars_flags.txt` produces, with no mismatches, so the database
is a safe way to look up a flag's number. Two upstream names
(`FLAG_GALACTIC_HQ_CONTROL_ROOM_STATE`, `VAR_OBTAINED_ACCESSORY_STARTER_MASK`)
do not exist in our fork, and our range sentinels (`MAP_LOCAL_FLAGS_START` and
friends) are not in the database because they are not flags. Anything *we* add
to `generated/vars_flags.txt` only appears after a resync, so
`generated/vars_flags.txt` remains the place to add state and
[`find_free_state.py`](tooling.md#find_free_statepy) remains the way to claim
it.

The `sounds` table is an **ID cross-reference, not a name source**. It uses the
upstream `SEQ_*` labels, while scripts here use the symbols generated into
`res/sound/pl_sound_data.naix`. The IDs line up - `SEQ_SE_CONFIRM` and our
`SE_CONFIRM_sseq_3` are both 1500 - so use the table to identify a sound you
found in a vanilla script, then write the `.naix` symbol.

## Looking things up

There is no wrapper tool; the file is plain JSON and reads well directly.

One command:

```bash
python3 -c 'import json,sys; d=json.load(open("subprojects/scrcmd-database/platinum_v2.json")); print(json.dumps(d["commands"][sys.argv[1]], indent=2))' AddItem
```

Searching by what a command does, which is usually the actual question:

```bash
python3 - <<'PY'
import json
db = json.load(open("subprojects/scrcmd-database/platinum_v2.json"))
for name, cmd in db["commands"].items():
    text = (cmd.get("description", "") + " " + cmd.get("notes", "")).lower()
    if "badge" in text:
        print(f'{name:40} {cmd.get("description", "")}')
PY
```

Finding where a command leaves its result:

```bash
python3 - <<'PY'
import json
db = json.load(open("subprojects/scrcmd-database/platinum_v2.json"))
cmd = db["commands"]["CheckItem"]
for p in cmd["params"]:
    print(p["name"], p["type"], p.get("access", "unannotated"), p.get("default", ""))
PY
```

Pair it with the generated [command reference](command_reference.md), which the
database does not replace: that page carries the usage count across
`res/field/scripts/*.s` and the name of the C handler, and neither is in the
JSON. Usage count is still the fastest signal for whether a command is a safe
pattern to copy.

## Accuracy and known gaps

Measured against `asm/macros/scrcmd.inc` and `asm/macros/movement.inc` in this
repo, at the submodule revision recorded here:

- The database holds 1111 entries. 1110 of them exist as macros here, so
  there is essentially nothing in it that we cannot assemble. The one
  exception is `YakoCommand`, a DSPRE-only macro alias.
- The eleven assembler directives that structure a script file - `ScriptEntry`,
  `ScriptEntryEnd` and the nine `InitScript*` macros - are **not** in the
  database. They are not bytecode commands. [README.md](README.md) covers them.
- Ten commands disagree with the macro on argument count: `StopMusic`, `Warp`,
  `ShowCurrentFloor`, `BufferPartyMonNicknameReturnSpecies`,
  `MessageSeenBanlistSpecies`, `ChooseCustomMessageWord`,
  `ChooseTwoCustomMessageWords`, `HasCoinsFromValue`,
  `BufferSpeciesNameWithArticle` and `GoToIfBadgeAcquired`. Write the macro's
  argument list, take the meaning from the database.
- Roughly a third of parameters carry a different *name* in the two places, the
  same argument described differently: `WaitTime` is `frames, countdownVarID`
  in the macro and `time, countdownVarID` in the database. Harmless, but do not
  script off the database's names.
- Some parameter names in the database are literally `???`, and 164 commands
  have no description. Those are the genuinely unresearched corners; fall back
  to the C handler.
- A few commands describe the raw bytecode rather than the macro's convenience.
  The database gives `ApplyMovement` a `relative_jump` of type `u32`, because
  that is what is in the ROM; the macro takes a label and the assembler
  computes the offset.

## Treat it as read-only

Do not edit anything under `subprojects/scrcmd-database/`, and do not run its
regeneration scripts. Two reasons, and the first one surprises people.

**You cannot commit those edits from here anyway.** A submodule is a separate
repository. All pokeaotea stores is a pointer to one commit in it:

```
$ git ls-tree HEAD subprojects/scrcmd-database
160000 commit 7b8baa5c306693d84b11c6491c22eea322aef13f  subprojects/scrcmd-database
```

Mode `160000` is a gitlink. Staging the path records *which commit* the
submodule should sit at, never the contents of its files. A dirty submodule
shows up in `git status` as a lowercase `m`, which means "modified content I
cannot stage for you":

```
 m subprojects/scrcmd-database
```

Committing it properly would mean committing inside the submodule, and its
remote belongs to the DSPRE project, so the commit would exist only on your
machine. Anyone cloning pokeaotea would then fail `git submodule update` on a
revision they cannot fetch.

**Regenerating loses more than it gains.** The submodule's two scripts are not
symmetrical:

- `scripts/sync_from_decomp.py` **enriches** the v2 files from a decomp
  checkout, adding decomp names, parameter types, the `access` annotations and
  the flags and vars sections. This is what makes our flag IDs line up.
- `scripts/db_migration.py` **rebuilds** the v2 files from the legacy DSPRE
  JSON, discarding everything the decomp sync added.

Running the rebuild on its own drops the `vars` section to empty, strips all
475 `access` annotations, and swaps decomp-derived notes for older DSPRE
speculation. The difference in quality is the whole point of the file:

| Pinned revision | After a bare `db_migration.py` |
| --- | --- |
| "The 16-bit argument is truncated to the low byte, limiting the selectable message slot range to 0-255." | "Supposed." |
| "The command overwrites variables 0x8004, 0x8005, and 0x8008 through 0x800B as working storage." | "Predicted." |

In `git diff --stat` that looks like a large successful update.

## Moving to a newer revision

Pull upstream instead. `make update` will not do it for you: that target runs
`meson subprojects update`, which only knows about the `.wrap` subprojects.

```bash
git -C subprojects/scrcmd-database pull origin main
git -C subprojects/scrcmd-database log --oneline -5    # see what you are taking
git add subprojects/scrcmd-database                    # record the new revision
```

Then re-check the two things we depend on before committing: that every command
name still resolves to a macro, and that the flag and variable IDs still agree
with `generated/vars_flags.txt`.

If we ever do need entries of our own - a command this hack adds that upstream
will never carry - the answer is to fork the database on GitHub and repoint the
submodule, or to contribute the entry upstream. Editing the checked-out copy in
place is the one approach that cannot work.
