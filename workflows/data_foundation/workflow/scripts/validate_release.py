#!/usr/bin/env python3
"""Validate the demo release files and write a readable summary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--checksums", required=True, type=Path)
    parser.add_argument("--validation-reports", nargs="+", required=True, type=Path)
    parser.add_argument("--croissants", nargs="+", required=True, type=Path)
    parser.add_argument("--monthly-netcdfs", nargs="+", required=True, type=Path)
    parser.add_argument("--annual-netcdfs", nargs="+", required=True, type=Path)
    parser.add_argument("--cds-requests", nargs="*", default=[], type=Path)
    parser.add_argument("--output-log", required=True, type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_status(base_dir: Path, checksums_path: Path) -> str:
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split(maxsplit=1)
        path = base_dir / relative.strip()
        if not path.exists() or sha256(path) != expected:
            return "FAILED"
    return "OK"


def main() -> None:
    args = parse_args()
    expected_files = [
        args.manifest,
        args.checksums,
        *args.validation_reports,
        *args.croissants,
        *args.monthly_netcdfs,
        *args.annual_netcdfs,
        *args.cds_requests,
    ]
    missing = [str(path) for path in expected_files if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing release files: " + ", ".join(missing))

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    reports = [
        json.loads(path.read_text(encoding="utf-8")) for path in args.validation_reports
    ]
    checksums = checksum_status(args.base_dir, args.checksums)
    warning_reports = [report for report in reports if report.get("warnings")]
    failed_reports = [report for report in reports if not report.get("selected_variable")]
    validation_status = "OK"
    if failed_reports:
        validation_status = "FAILED"
    elif warning_reports:
        validation_status = "WARNINGS"

    lines = [
        "PROFECIA data-foundation demo release",
        f"Release ID: {manifest.get('data_release_id')}",
        f"Variables: {', '.join(item['name'] for item in manifest.get('variables', []))}",
        f"Source: {manifest.get('source')}",
        f"Monthly NetCDF files: {len(args.monthly_netcdfs)}",
        f"Annual NetCDF files: {len(args.annual_netcdfs)}",
        f"Validation: {validation_status}",
        f"Checksums: {checksums}",
        f"Croissant files: {len(args.croissants)}",
    ]
    if warning_reports:
        lines.append("Warnings:")
        for report in warning_reports:
            variable = report.get("requested_variable", report.get("selected_variable", "unknown"))
            for warning in report.get("warnings", []):
                lines.append(f"- {variable}: {warning}")

    summary = "\n".join(lines) + "\n"
    args.output_log.parent.mkdir(parents=True, exist_ok=True)
    args.output_log.write_text(summary, encoding="utf-8")
    print(summary)

    if checksums != "OK" or validation_status == "FAILED":
        raise RuntimeError("Release validation failed.")


if __name__ == "__main__":
    main()
