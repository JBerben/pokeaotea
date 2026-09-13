#!/usr/bin/env python3
# ABOUTME: Re-blesses the SHA-1 manifests in platinum.us/ against the current build.
# ABOUTME: File lists come from main.lsf, filesys.csv and the build dir, hashes from the build.
"""Re-bless the SHA-1 manifests in platinum.us/ against the current build.

The manifests are matching-decomp regression tests: they pin the exact bytes of
the retail ROM. Any intentional change to code or assets makes them fail, so a
hack needs a way to say "yes, this is the new expected output".

Each manifest is regenerated from scratch. The list of files comes from the
same sources the build itself uses, so upstream renames and locally added
files are picked up automatically:

  sbins_shared.sha1   main.sbin + every `Overlay` block in platinum.us/main.lsf
  sbins_rev<N>.sha1   the overlays whose bytes differ between ROM revisions
  sbins_arm7.sha1     the ARM7 sbin built by the NitroSDK subproject
  filesys.sha1        the source-file column of platinum.us/filesys.csv
  rom_rev<N>.sha1     the packed ROM

Manifests belonging to the revision the build dir was *not* configured for are
left alone (they would be blessed with the wrong ROM's bytes).
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Overlays that are compiled differently per ROM revision (POKEPLATINUM_REVISION).
# Everything else in main.lsf is byte-identical across revisions and goes in the
# shared manifest.
REVISION_SPECIFIC_SBINS = ["gts_application.sbin"]

ARM7_SBIN_GLOB = "subprojects/NitroSDK-*/components/ichneumon/ichneumon_sub.sbin"
ROM_FILE = "pokeplatinum.us.nds"

OVERLAY_RE = re.compile(r"^Overlay\s+(\S+)", re.MULTILINE)


class ManifestError(Exception):
    """Raised when a manifest cannot be derived from the sources or the build."""


def detect_revision(build_dir: Path) -> str:
    """Read the `revision` option out of the build dir's meson configuration."""
    info = build_dir / "meson-info" / "intro-buildoptions.json"
    if not info.is_file():
        raise ManifestError(f"{info} not found; is {build_dir} a configured build dir?")

    for option in json.loads(info.read_text()):
        if option["name"] == "revision":
            return option["value"]

    raise ManifestError(f"no `revision` option recorded in {info}")


def sha1_of(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def overlay_sbins(lsf_text: str) -> list[str]:
    """Every ARM9 sbin the linker spec produces, main first, then overlays in spec order."""
    return ["main.sbin"] + [f"{name}.sbin" for name in OVERLAY_RE.findall(lsf_text)]


def shared_sbins(lsf_text: str) -> list[str]:
    return [s for s in overlay_sbins(lsf_text) if s not in REVISION_SPECIFIC_SBINS]


def revision_sbins(lsf_text: str) -> list[str]:
    present = overlay_sbins(lsf_text)
    missing = [s for s in REVISION_SPECIFIC_SBINS if s not in present]
    if missing:
        raise ManifestError(
            f"revision-specific overlay(s) not found in main.lsf: {', '.join(missing)}; "
            "update REVISION_SPECIFIC_SBINS in this script if the overlay was renamed"
        )
    return list(REVISION_SPECIFIC_SBINS)


def filesys_sources(csv_text: str) -> list[str]:
    """The build-tree paths of every file packed into the NitroFS, in filesys.csv order."""
    lines = [line for line in csv_text.splitlines()[1:] if line.strip()]
    return [line.split(",", 1)[0] for line in lines]


def arm7_sbins(build_dir: Path) -> list[str]:
    matches = sorted(build_dir.glob(ARM7_SBIN_GLOB))
    if not matches:
        raise ManifestError(f"no ARM7 sbin matching {ARM7_SBIN_GLOB} under {build_dir}")
    return [m.relative_to(build_dir).as_posix() for m in matches]


def manifest_lists(repo_root: Path, build_dir: Path, revision: str) -> dict[str, list[str]]:
    """Map each manifest to bless to the build-relative files it must cover."""
    spec_dir = repo_root / "platinum.us"
    lsf_text = (spec_dir / "main.lsf").read_text()
    csv_text = (spec_dir / "filesys.csv").read_text()
    return {
        "sbins_shared.sha1": shared_sbins(lsf_text),
        f"sbins_rev{revision}.sha1": revision_sbins(lsf_text),
        "sbins_arm7.sha1": arm7_sbins(build_dir),
        "filesys.sha1": filesys_sources(csv_text),
        f"rom_rev{revision}.sha1": [ROM_FILE],
    }


def read_manifest(manifest: Path) -> dict[str, str]:
    """Map build-relative path -> hash for an existing manifest, or {} if absent."""
    if not manifest.is_file():
        return {}
    entries = {}
    for line in manifest.read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(" ", 1)
        # `*` marks sha1sum's binary mode, not part of the path.
        entries[name.lstrip("*")] = digest
    return entries


def render_manifest(build_dir: Path, files: list[str]) -> tuple[dict[str, str], list[str]]:
    """Hash every file. Returns (path -> hash, paths missing from the build)."""
    hashes = {}
    missing = []
    for rel in files:
        # sha1sum -c is run with the build dir as its cwd, so recorded paths are
        # relative to it.
        target = build_dir / rel
        if not target.is_file():
            missing.append(rel)
            continue
        hashes[rel] = sha1_of(target)
    return hashes, missing


def report_diff(old: dict[str, str], new: dict[str, str]) -> int:
    """Print what changed between two manifests. Returns the number of changes."""
    changes = 0
    for rel in old.keys() - new.keys():
        print(f"  REMOVED {rel}")
        changes += 1
    for rel, digest in new.items():
        if rel not in old:
            print(f"  ADDED   {rel}")
            changes += 1
        elif old[rel] != digest:
            print(f"  {rel}\n    {old[rel]} -> {digest}")
            changes += 1
    if not changes:
        print("  up to date")
    return changes


def bless(repo_root: Path, build_dir: Path, revision: str, dry_run: bool) -> int:
    """Regenerate every manifest for `revision`. Returns the number of changed entries."""
    spec_dir = repo_root / "platinum.us"
    total_changed = 0
    missing = []

    for name, files in manifest_lists(repo_root, build_dir, revision).items():
        manifest = spec_dir / name
        print(f"{manifest.relative_to(repo_root)}:")

        new, absent = render_manifest(build_dir, files)
        missing += absent
        old = read_manifest(manifest)
        total_changed += report_diff(old, new)

        if absent or dry_run:
            continue
        manifest.write_text("".join(f"{digest} *{rel}\n" for rel, digest in new.items()))

    if missing:
        raise ManifestError(
            "build output(s) missing, nothing was written:\n  "
            + "\n  ".join(missing)
            + "\nBuild the ROM first."
        )

    return total_changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "-C", "--build-dir", type=Path, default=None,
        help="configured meson build directory (default: <repo-root>/build)",
    )
    parser.add_argument(
        "-r", "--revision", choices=["0", "1"],
        help="ROM revision to bless (default: whatever the build dir is configured for)",
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="report what would change without writing the manifests",
    )
    parser.add_argument(
        "--repo-root", type=Path, default=REPO_ROOT,
        help="repository root containing platinum.us/ (default: this checkout)",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    build_dir = (args.build_dir or repo_root / "build").resolve()

    try:
        revision = args.revision or detect_revision(build_dir)
        total_changed = bless(repo_root, build_dir, revision, args.dry_run)
    except ManifestError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    other = "0" if revision == "1" else "1"
    print()
    if args.dry_run:
        print(f"{total_changed} entr(y/ies) would change (rev{revision}).")
    else:
        print(f"Updated {total_changed} entr(y/ies) for rev{revision}.")
    if total_changed:
        print(f"Note: rev{other} manifests were not touched; rebuild with "
              f"ROM_REVISION={other} and re-run to bless those too.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
