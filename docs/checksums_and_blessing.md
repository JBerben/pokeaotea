# Checksums and Blessing

`pokeaotea` is a ROM hack built on the `pokeplatinum` decompilation. Upstream
uses the SHA-1 manifests in `platinum.us/` as a matching test: the build must
reproduce the retail ROM byte for byte. A hack intentionally diverges from
retail, so this repository repurposes those manifests as a regression test on
*our own* output. Recording the current build's hashes as the new expected
values is called **blessing**.

## Table of Contents

<!--toc:start-->
- [The manifests](#the-manifests)
- [Everyday workflow](#everyday-workflow)
- [How the lists are derived](#how-the-lists-are-derived)
- [Merging from upstream](#merging-from-upstream)
- [Revision 0 and revision 1](#revision-0-and-revision-1)
- [Testing the bless script](#testing-the-bless-script)
<!--toc:end-->

## The manifests

| Manifest                       | Covers                                              |
| ------------------------------ | --------------------------------------------------- |
| `platinum.us/sbins_shared.sha1`| `main.sbin` and every overlay that is identical across ROM revisions |
| `platinum.us/sbins_rev0.sha1`  | Overlays whose bytes differ per revision, rev 0     |
| `platinum.us/sbins_rev1.sha1`  | Same, rev 1                                         |
| `platinum.us/sbins_arm7.sha1`  | The ARM7 binary built by the NitroSDK subproject    |
| `platinum.us/filesys.sha1`     | Every file packed into the NitroFS                  |
| `platinum.us/rom_rev0.sha1`    | The packed rev 0 ROM                                |
| `platinum.us/rom_rev1.sha1`    | The packed rev 1 ROM                                |

`meson test` (run by `make check`) feeds each manifest to `sha1sum -c` with the
build directory as the working directory. The paths inside the manifests are
therefore relative to `build/`.

## Everyday workflow

```bash
make            # build, then bless: the manifests now describe this build
make check      # build, then compare against the blessed manifests
BLESS=0 make    # build without touching the manifests
make bless      # bless without reconfiguring (what `make` runs after the ROM)
```

A plain `make` blesses automatically, so after adding or changing an asset the
manifests in your working tree already match. Commit them together with the
change that caused them.

Use `BLESS=0 make check` when you want to prove that a change is a no-op, for
example after a refactor or after merging upstream documentation work.

The bless script prints what changed:

```text
platinum.us/filesys.sha1:
  res/field/area_data/area_data.narc
    2df833d8f0145f29f21b23c06ba3561dec3f5180 -> ef6d2ff28be455119bd3c9c52c38e45b38909549
  ADDED   res/field/maps/texture_sets/map_tex_set.narc
  REMOVED res/prebuilt/graphic/ending.narc
```

If a file the manifest needs is missing from the build, the script exits
non-zero and writes nothing. Build the ROM first.

## How the lists are derived

The bless script (`tools/scripts/update_checksums.py`) does **not** trust the
old manifest for the list of files. It regenerates every manifest from the same
sources the build uses:

- `sbins_shared.sha1`: `main.sbin`, then one entry per `Overlay <name>` block
  in `platinum.us/main.lsf`, in spec order, minus the revision-specific ones.
- `sbins_rev<N>.sha1`: the constant `REVISION_SPECIFIC_SBINS` in the script.
  This is the only hand-maintained list, and it is currently just
  `gts_application.sbin`. If upstream renames that overlay the script stops
  with an error rather than silently blessing the wrong thing.
- `sbins_arm7.sha1`: the `ichneumon_sub.sbin` found under the NitroSDK
  subproject in the build directory, so an SDK version bump is picked up.
- `filesys.sha1`: the source-file column of `platinum.us/filesys.csv`, in
  order.
- `rom_rev<N>.sha1`: `pokeplatinum.us.nds`.

Two consequences worth knowing:

1. An overlay renamed upstream is picked up on the next `make`. Nothing to edit.
2. A NARC you add to `filesys.csv` is covered by `make check` from then on.
   Previously a manifest that only had its hashes updated would never learn
   about new files, so locally added assets went untested.

## Merging from upstream

The file lists belong to upstream; the hashes belong to us. Since the script
regenerates every hash anyway, the merge rule is simple:

1. If `platinum.us/*.sha1` conflicts, take upstream's version of the file.
   Their retail hashes are a fine starting point.
2. Run `make`. The manifests are re-blessed against your build.
3. Commit the merge together with the re-blessed manifests.

Never hand-merge individual hash lines.

## Revision 0 and revision 1

The build directory is configured for one revision at a time (`ROM_REVISION=1`
is the default). Blessing only touches the manifests for the configured
revision, plus the shared ones. To keep the rev 0 manifests in step:

```bash
ROM_REVISION=0 make
```

This reconfigures and rebuilds, so expect it to take a while.

## Testing the bless script

The script has its own tests and needs nothing beyond the Python standard
library:

```bash
python3 -m unittest tools/scripts/test_update_checksums.py
```

They cover list derivation from a fake `main.lsf` and `filesys.csv`, blessing a
fake repository layout including stale entries, dry-run mode, and the command
line as the Makefile invokes it.
