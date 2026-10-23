#!/usr/bin/env python3
"""Write a complete, deterministic SHA-256 inventory for a candidate directory."""

from __future__ import annotations

import argparse
import hashlib
import re
import stat
import sys
from pathlib import Path


class InventoryError(ValueError):
    """Candidate contents are not safe to inventory without ambiguity."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_inventory(root: Path, output: Path) -> list[str]:
    if root.is_symlink() or not root.is_dir():
        raise InventoryError("candidate root must be a real directory")
    root = root.resolve(strict=True)
    if output.is_symlink() or output.exists():
        raise InventoryError("refusing to overwrite an existing inventory")
    output_parent = output.parent.resolve(strict=True)
    if output_parent != root:
        raise InventoryError("inventory must be written at the candidate root")

    entries: list[str] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path == output:
            continue
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise InventoryError(f"candidate contains a symlink: {path.relative_to(root).as_posix()}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise InventoryError(f"candidate contains a non-regular or multiply linked file: {path.relative_to(root).as_posix()}")
        relative = path.relative_to(root).as_posix()
        if (not re.fullmatch(r"[A-Za-z0-9._~+/-]+", relative) or
            relative.startswith("/") or ".." in Path(relative).parts):
            raise InventoryError(f"candidate path is not checksum-manifest safe: {relative!r}")
        entries.append(f"{sha256(path)}  {relative}")
    if not entries:
        raise InventoryError("candidate directory is empty")
    with output.open("x", encoding="ascii") as stream:
        stream.write("\n".join(entries) + "\n")
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        entries = create_inventory(args.root.absolute(), args.output.absolute())
    except (InventoryError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"inventory_entries={len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
