#!/usr/bin/env python3
"""Check ZIP integrity, inventory its payload, and write transport checksum."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    archive = args.archive
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        names = [item.filename for item in entries]
        if len(names) != len(set(names)):
            raise RuntimeError("Duplicate ZIP member names")
        for name in names:
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise RuntimeError(f"Unsafe member path: {name}")
            if any(term in Path(name).name.lower() for term in ("secrets.local", ".cdsapirc", ".env", "credentials")):
                safe_example = (name == "config/secrets.local.example.yml" and
                                yaml.safe_load(zipped.read(name)) == {
                                    "usgs_m2m": {"username": "YOUR_USGS_USERNAME", "token": "YOUR_USGS_M2M_TOKEN"}})
                if not safe_example:
                    raise RuntimeError(f"Potential credential file: {name}")
        corrupt = zipped.testzip()
        if corrupt:
            raise RuntimeError(f"ZIP integrity failure: {corrupt}")
        graph = json.loads(zipped.read("ro-crate-metadata.json"))["@graph"]
        by_checksum = {}
        for entity in graph:
            if entity.get("sha256") and entity["@id"] in names:
                by_checksum.setdefault(entity["sha256"], []).append(entity["@id"])
    with archive.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(f"{checksum}  {archive.name}\n")
    report = {
        "status": "OK", "archive": str(archive), "sha256": checksum,
        "archive_bytes": archive.stat().st_size, "member_count": len(entries),
        "uncompressed_bytes": sum(item.file_size for item in entries),
        "large_files_over_100MB": [{"path": item.filename, "bytes": item.file_size}
                                  for item in entries if item.file_size > 100_000_000],
        "configuration_files": [name for name in names if name.endswith((".yml", ".yaml"))],
        "duplicate_content_groups": [paths for paths in by_checksum.values() if len(paths) > 1],
        "inventory": [{"path": item.filename, "bytes": item.file_size} for item in entries],
        "notes": ["Effective inputs and reference outputs are deliberately included.",
                  "Historical local paths remain in original provenance/configuration; portable config maps effective inputs.",
                  "Filename screening is not a comprehensive secret/content audit."],
    }
    target = archive.parent / "validation/archive_audit.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "sha256", "archive_bytes", "member_count")}))


if __name__ == "__main__":
    main()
