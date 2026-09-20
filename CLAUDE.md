# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

`pokeaotea` is a ROM hack built on top of the [pret/pokeplatinum](https://github.com/pret/pokeplatinum)
decompilation of Pokémon Platinum (EN-US). The git remote `upstream` points at pret; `origin` is the
fork. `main` tracks upstream, `dev` is the working branch.

Because this is a hack, the build is **not** expected to match the retail ROM. The SHA-1 manifests in
`platinum.us/*.sha1` are "blessed" hashes of *our* current output, and `make check` compares against
those. Upstream docs (README/INSTALL/CONTRIBUTING) still describe the matching-decomp workflow; where
they conflict with this file, this file wins.

## Build commands

Toolchain: Meson (vendored at `subprojects/meson-1.12.0/meson.py`, cloned on first build) + Ninja,
driving the CodeWarrior ARM compiler through `tools/metroskrew` (downloaded on first build) and
`arm-none-eabi-gcc` for script assembly. Build dir is `build/`. Do not use system `meson` unless you
pass `MESON=meson` explicitly.

```bash
make                 # release build of build/pokeplatinum.us.nds, then re-bless the SHA-1 manifests
BLESS=0 make         # same, but leave platinum.us/*.sha1 untouched
make rom             # just build the ROM (no bless, no checksum test)
make check           # build, then `meson test` (SHA-1 checks of sbins, filesystem, ROM) against blessed hashes
make bless           # build, then rewrite platinum.us/*.sha1 from the current build (tools/scripts/update_checksums.py)
make debug           # build with -Dgdb_debugging=true -Dlogging_enabled=true, plus debug.nef and overlay.map for GDB
make format          # run clang-format over src/, include/, lib/ (also enforced by pre-commit and CI)
make target MESON_TARGET=<name>   # build a single Meson target, e.g. MESON_TARGET=scr_seq.narc
make clean           # ninja clean + rm build/res
make distclean       # rm -rf build
make update          # refresh subprojects and metroskrew after merging from upstream
ROM_REVISION=0 make  # build the rev-0 ROM (only affects overlay94/GTS and the header template)
```

Switching between `make` (release) and `make debug` reconfigures the same build dir; expect a large
rebuild. `ninja -C build <target>` works directly once configured.

`make check` is the only automated test suite for the game: it is a byte-level regression test on
the ROM. Any intentional change to code or assets changes the hashes, which is why a release build
re-blesses automatically. Use `BLESS=0` when you want to prove a change is a no-op.

The bless script derives each manifest's file list from the build's own sources, not from the old
manifest: `sbins_*.sha1` from the `Overlay` blocks in `platinum.us/main.lsf`, `filesys.sha1` from
`platinum.us/filesys.csv`. So an overlay renamed upstream, or a NARC you add to `filesys.csv`, is
covered by the next `make` with no manual manifest editing. The only hand-maintained piece is
`REVISION_SPECIFIC_SBINS` in the script (currently just `gts_application.sbin`).

**Merging from upstream:** if `platinum.us/*.sha1` conflicts, take upstream's side (their lists and
retail hashes are both fine as a starting point), then run `make` to re-bless. Never hand-merge hash
lines. The script has its own tests:
`python3 -m unittest tools/scripts/test_update_checksums.py`. Full write-up in
`docs/checksums_and_blessing.md`.

Formatting: pre-commit runs clang-format 19 (`pre-commit install` after `pip install pre-commit`).
`.s`/`.inc`, `tools/`, and `subprojects/` are never formatted. Compile database for editors:
`python tools/devtools/gen_compile_commands.py`.

Line endings: `res/**/*.txt` and `*.pal` must stay CRLF (see `.gitattributes`); everything else is LF.

## Architecture

### Build pipeline (top-level `meson.build`)

1. `generated/` — plain-text constant lists (`*.txt`) are turned into headers under `build/generated/`
   by `metang`. Each header is a C `enum` when `POKEPLATINUM_GENERATED_ENUM` is defined (always, for
   C) and plain `#define`s otherwise (for assembled scripts). New constant set = new `.txt` file plus an
   entry in `generated/meson.build`.
2. `tools/` — native host tools built by Meson: `nitrogfx` (PNG → NCGR/NCLR/NCER/NANR), `dataproc/*proc`
   (JSON → NARC + generated headers; see `docs/datafiles/overview.md`), `msgenc` (text banks),
   `nitroarc`, `nitrorom` (packs the ROM), `enumproc`, `ordergen`, `postconf`.
3. `platinum.us/` — ROM spec: `main.lsf` (linker spec fed to `makelcf`), `filesys.csv` (NitroFS
   layout), `rom_rev*.ini`, header templates, and the SHA-1 manifests.
4. `lib/` — internal libraries (`crypto`, `gds`, `spl`, `ppwlobby`). NitroSDK, NitroSystem, NitroWiFi,
   NitroDWC come in as Meson subprojects (`subprojects/*.wrap`).
5. `res/` — asset sources. Every subdir's `meson.build` lists its inputs, runs a generator/tool, and
   appends the result to `nitrofs_files`. Many NARCs take a `.order` file that fixes member order.
6. `src/` — the ARM9 binary (`main`), compiled with the precompiled header `include/pch/global_pch.h`.

### Adding a C source file (two places, both required)

- Add the path to the `pokeplatinum_c` list in `src/meson.build`.
- Add an `Object main.nef.p/src_<path_with_underscores>.c.o` line to the right section of
  `platinum.us/main.lsf`. `Static main` is the always-resident ARM9 code; `Overlay <name>` blocks
  (122 of them) are the load-on-demand overlays. Link order inside a block is the order in the file.

Overlay sources live either in `src/overlayNNN/` (undocumented) or in named dirs such as
`src/applications/<app>/`, `src/battle/`, `src/overlay005/` (the field/overworld overlay). Overlay
binaries are named in `platinum.us/sbins_*.sha1` (e.g. `main_menu.sbin`, `overlay92.sbin`). Overlay
loading is managed from `src/overlay_manager.c` / `src/game_overlay.c`.

### Adding an asset

Follow the existing pattern in the relevant `res/<dir>/meson.build`: add the file to the `files(...)`
list and, where present, to the `.order` file. Expect `platinum.us/filesys.sha1` to change on the
next release build. Example from this fork: a new map texture set is `res/field/maps/texture_sets/
map_texture_set_NNN.nsbtx` + `map_texture_sets.order` + `meson.build`, referenced from a new
`res/field/area_data/area_data_NNN.json`.

### Field and battle scripting

- Overworld scripts: `res/field/scripts/scripts_<map>.s`, assembled with `arm-none-eabi-gcc` via
  `tools/scripts/make_script_bin.sh` into `scr_seq.narc`. Commands are macros in
  `asm/macros/scrcmd.inc` (plus `movement.inc`, `function.inc`); they include the generated constant
  headers, so script files can use the same names as C. Script order is `scripts.order`.
- **Command semantics** come from `subprojects/scrcmd-database/platinum_v2.json`, a git submodule
  (`git submodule update --init subprojects/scrcmd-database`). The macro file gives the signature;
  that JSON gives the description, opcode, parameter types, which argument receives the result, and
  the macro expansions, for 1110 of our commands. Its flag and variable IDs are synced from this
  repo and match `generated/vars_flags.txt`. Read `docs/scripting/command_database.md` before
  working on scripts; where the two disagree on an argument list, the macro wins. Ignore the legacy
  `*_scrcmd_database.json` files and the other games' databases in that submodule.
- Battle scripts and trainer AI: `res/battle/`, `asm/macros/btlcmd.inc`, `aicmd.inc`;
  `src/battle/trainer_ai/script.s` is assembled separately and linked into `main`.
- Text: `res/text/*.json` banks, compiled by `msgenc`.

### Data files

Species, moves, items, trainers, and NPC trades are JSON under `res/pokemon/<species>/data.json`,
`res/moves/<move>/data.json`, `res/items/data/`, `res/trainers/data/`, `res/npc_trades/`. The
`*proc` tools validate identifiers against `include/constants/*.h` and the generated enums, and emit
both NARCs and headers. Per-type docs are in `docs/datafiles/`.

### Maps

Map matrix → map headers → area data (texture set + prop set + lighting) → land data + BDHC height
data. Read `docs/maps/README.md` first; `src/overlay005/` holds the runtime side (`fieldmap.c`,
`area_data.c`, `land_data.c`, `bdhc.c`, `map_prop.c`).

### Logging

With `make debug`, `#include "debug.h"` and call `EmulatorLog(fmt, ...)` (printf-style, prefixed
`[GAME_LOG]`) to print to melonDS/No$GBA stdout. See `docs/logging.md`.

## Conventions (from CONTRIBUTING.md)

- `PascalCase` for structs (tag + typedef), enums (no typedef), and functions; `camelCase` for
  members, params, locals; `UPPER_SNAKE_CASE` for enum members with only the first assigned.
- Public functions are prefixed with their module name: `Module_Function()`.
- Files named `unk_XXXXXXXX.c` / `ovNN_XXXXXXXX.c` and functions `sub_XXXXXXXX` are still undocumented
  decomp output; the address in the name is the original ROM address. Renaming them is documentation
  work and is welcome, but keep the object name in `main.lsf` in sync.

## Docs index

`docs/index.md` links everything: editor setup, 2D/3D rendering, maps, data files, logging,
and `docs/bugs_and_glitches.md` for known retail bugs and their fixes.
