#!/usr/bin/env python3
"""Validate the packaged PROFECIA common and conditional SHACL shapes."""
import json
from pathlib import Path

from pyshacl import validate
from rdflib import Graph


def main():
    root = Path.cwd()
    data = Graph().parse(root / "ro-crate-metadata.json", format="json-ld")
    shapes = Graph()
    for path in sorted((root / "metadata/vocabulary/shacl").glob("*.ttl")):
        shapes.parse(path, format="turtle")
    if not len(shapes):
        raise RuntimeError("No SHACL shapes found")
    conforms, _, report = validate(data, shacl_graph=shapes, allow_warnings=False)
    Path("shacl-report.txt").write_text(report)
    Path("shacl-result.json").write_text(json.dumps({"conforms": bool(conforms)}, indent=2) + "\n")
    print(report)
    if not conforms:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
