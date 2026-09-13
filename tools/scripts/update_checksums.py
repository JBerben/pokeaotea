#!/usr/bin/env python3
"""Re-bless the SHA-1 manifests in platinum.us/ against the current build.

The manifests are matching-decomp regression tests: they pin the exact bytes of
the retail ROM. Any intentional change to code or assets makes them fail, so a
hack needs a way to say "yes, this is the new expected output".

The file list in each manifest is preserved as-is; only the hashes are updated.
Manifests belonging to the revision the build dir was *not* configured for are
left alone (they would be blessed with the wrong ROM's bytes).
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "platinum.us"

# Manifests that apply to every revision, and those keyed to a specific one.
SHARED_MANIFESTS = ["filesys.sha1", "sbins_shared.sha1"]
PER_REVISION_MANIFESTS = ["sbins_rev{rev}.sha1", "rom_rev{rev}.sha1"]


def detect_revision(build_dir: Path) -> str:
    """Read the `revision` option out of the build dir's meson configuration."""
    info = build_dir / "meson-info" / "intro-buildoptions.json"
    if not info.is_file():
        sys.exit(f"error: {info} not found; is {build_dir} a configured build dir?")

    for option in json.loads(info.read_text()):
        if option["name"] == "revision":
            return option["value"]

    sys.exit(f"error: no `revision` option recorded in {info}")


def sha1_of(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse(manifest: Path) -> list[tuple[str, str]]:
    """Yield (hash, path) pairs. Paths keep sha1sum's leading `*` binary marker."""
    entries = []
    for lineno, line in enumerate(manifest.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            digest, name = line.split(" ", 1)
        except ValueError:
            sys.exit(f"error: {manifest}:{lineno}: malformed entry: {line!r}")
        entries.append((digest, name))
    return entries


def update(manifest: Path, build_dir: Path, dry_run: bool) -> tuple[int, int]:
    """Rewrite `manifest` with hashes taken from `build_dir`. Returns (changed, missing)."""
    updated = []
    changed = 0
    missing = 0

    for old_digest, name in parse(manifest):
        # sha1sum -c is run with the build dir as its cwd, so the recorded
        # paths are relative to it. `*` marks binary mode, not part of the path.
        target = build_dir / name.lstrip("*")

        if not target.is_file():
            print(f"  MISSING {name.lstrip('*')} (keeping old hash)")
            updated.append((old_digest, name))
            missing += 1
            continue

        new_digest = sha1_of(target)
        if new_digest != old_digest:
            print(f"  {name.lstrip('*')}\n    {old_digest} -> {new_digest}")
            changed += 1
        updated.append((new_digest, name))

    if changed and not dry_run:
        manifest.write_text("".join(f"{d} {n}\n" for d, n in updated))

    return changed, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-C", "--build-dir", type=Path, default=REPO_ROOT / "build",
        help="configured meson build directory (default: ./build)",
    )
    parser.add_argument(
        "-r", "--revision", choices=["0", "1"],
        help="ROM revision to bless (default: whatever the build dir is configured for)",
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="report what would change without writing the manifests",
    )
    args = parser.parse_args()

    build_dir = args.build_dir.resolve()
    revision = args.revision or detect_revision(build_dir)

    manifests = SHARED_MANIFESTS + [m.format(rev=revision) for m in PER_REVISION_MANIFESTS]
    total_changed = 0
    total_missing = 0

    for name in manifests:
        manifest = MANIFEST_DIR / name
        print(f"{manifest.relative_to(REPO_ROOT)}:")
        changed, missing = update(manifest, build_dir, args.dry_run)
        total_changed += changed
        total_missing += missing
        if not changed:
            print("  up to date")

    other = "0" if revision == "1" else "1"
    print()
    if args.dry_run:
        print(f"{total_changed} hash(es) would change (rev{revision}).")
    else:
        print(f"Updated {total_changed} hash(es) for rev{revision}.")
    if total_changed:
        print(f"Note: rev{other} manifests were not touched; rebuild with "
              f"ROM_REVISION={other} and re-run to bless those too.")
    if total_missing:
        print(f"Warning: {total_missing} file(s) were not present in {build_dir}; "
              f"their old hashes were kept. Build the ROM first.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
