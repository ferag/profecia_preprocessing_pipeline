#!/usr/bin/env python3
"""Verify packaged RO-Crate files and scientific product completeness."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path.cwd()
    graph = json.loads((root / "ro-crate-metadata.json").read_text())["@graph"]
    checked = 0
    for entity in graph:
        identifier = entity["@id"]
        if identifier.startswith(("#", "http:", "https:", "urn:", "mailto:")):
            continue
        path = root / identifier
        if entity.get("sha256") and path.is_file():
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != entity["sha256"]:
                raise RuntimeError(f"Checksum mismatch: {identifier}")
            checked += 1
        elif entity.get("sha256") and not identifier.startswith("referenced-"):
            raise FileNotFoundError(path)
    manifest = json.loads((root / "manifest.json").read_text())
    for product in manifest["harmonized_files"]:
        if not (root / product).is_file() and not (root / "referenced-data" / product).is_file():
            raise FileNotFoundError(root / product)
    print(f"Verified {checked} checksums and {len(set(manifest['harmonized_files']))} scientific products")


if __name__ == "__main__":
    main()
