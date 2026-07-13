#!/usr/bin/env python3
"""Write SHA256 checksums for files that exist."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args()

    lines = []
    for path in args.files:
        if not path.exists() or path == args.output:
            continue
        paths = (
            sorted(
                item
                for item in path.rglob("*")
                if item.is_file() and item.name != ".snakemake_timestamp"
            )
            if path.is_dir()
            else [path]
        )
        for item in paths:
            if item == args.output:
                continue
            relative = item.relative_to(args.base_dir).as_posix()
            lines.append(f"{sha256(item)}  {relative}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(sorted(lines)) + ("\n" if lines else ""), encoding="utf-8")
    print(f"Wrote checksums for {len(lines)} file(s): {args.output}")


if __name__ == "__main__":
    main()
