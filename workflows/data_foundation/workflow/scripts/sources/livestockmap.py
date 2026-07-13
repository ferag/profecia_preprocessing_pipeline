#!/usr/bin/env python3
"""Manual/internal LivestockMap source adapter for PROFECIA TLU."""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, source_config, variable_config


def configured_year_range(data: dict[str, Any], key: str) -> tuple[int, int] | None:
    period = data.get(key) or {}
    if not isinstance(period, dict):
        return None
    start = period.get("start_year")
    end = period.get("end_year")
    if start is None or end is None:
        return None
    return int(start), int(end)


def archive_path(source_data: dict[str, Any]) -> Path:
    raw_archive = source_data.get("raw_archive") or {}
    path = raw_archive.get("expected_path")
    if not path:
        raise ValueError("livestockmap source requires raw_archive.expected_path.")
    return Path(path)


def member_matches(member: str, pattern: str, year: int) -> bool:
    rendered = pattern.format(year=year)
    name = Path(member).name
    return fnmatch.fnmatch(name, rendered) or fnmatch.fnmatch(member, rendered)


def find_species_files(
    members: list[str],
    species_data: dict[str, Any],
    years: list[int],
) -> tuple[dict[str, dict[str, list[str]]], list[dict[str, Any]]]:
    matched: dict[str, dict[str, list[str]]] = {}
    missing: list[dict[str, Any]] = []

    for species, metadata in species_data.items():
        patterns = metadata.get("expected_patterns", [])
        if not patterns:
            missing.extend({"species": species, "year": year, "patterns": []} for year in years)
            continue
        matched[species] = {}
        for year in years:
            hits: list[str] = []
            for pattern in patterns:
                hits.extend(member for member in members if member_matches(member, pattern, year))
            unique_hits = sorted(set(hits))
            if unique_hits:
                matched[species][str(year)] = unique_hits
            else:
                missing.append({"species": species, "year": year, "patterns": patterns})

    return matched, missing


def extension_years(source_data: dict[str, Any]) -> list[int]:
    target = configured_year_range(source_data, "profecia_target_period")
    temporal = source_data.get("temporal_extension") or {}
    available_until = temporal.get("source_available_until")
    if not target or available_until is None:
        return []
    return [
        year
        for year in range(target[0], target[1] + 1)
        if year > int(available_until)
    ]


def required_years(source_data: dict[str, Any]) -> list[int]:
    target = configured_year_range(source_data, "profecia_target_period")
    available = configured_year_range(source_data, "expected_period")
    if not target:
        raise ValueError("livestockmap source requires profecia_target_period.")

    start, end = target
    if available:
        start = max(start, available[0])
        end = min(end, available[1])

    temporal = source_data.get("temporal_extension") or {}
    available_until = temporal.get("source_available_until")
    if available_until is not None:
        end = min(end, int(available_until))

    if end < start:
        return []
    return list(range(start, end + 1))


def check_manual_input(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    source_data = source_config(config, args.source)
    variable_data = variable_config(config, args.source, args.variable)

    path = archive_path(source_data)
    species_data = source_data.get("species") or {}
    if not species_data:
        raise ValueError("livestockmap source requires species definitions.")

    years = required_years(source_data)
    unresolved_extension = extension_years(source_data)
    status = "OK"
    message = f"Found complete LivestockMap archive for {args.source}/{args.variable}."
    members: list[str] = []
    matched: dict[str, dict[str, list[str]]] = {}
    missing_required: list[dict[str, Any]] = []

    if not path.exists():
        status = "MISSING"
        message = (
            f"LivestockMap archive not found: {path}. Place the manually provided "
            "LivestockMap.zip there, or update raw_archive.expected_path."
        )
    elif not zipfile.is_zipfile(path):
        status = "MISSING"
        message = f"LivestockMap archive is not a valid ZIP file: {path}"
    else:
        with zipfile.ZipFile(path) as archive:
            members = sorted(member for member in archive.namelist() if not member.endswith("/"))
        matched, missing_required = find_species_files(members, species_data, years)
        if missing_required:
            status = "MISSING"
            message = (
                f"LivestockMap archive is missing {len(missing_required)} required "
                f"species/year raster(s) for {args.source}/{args.variable}."
            )

    warnings = []
    if unresolved_extension:
        warnings.append(
            "TLU target period extends beyond verified LivestockMap availability "
            f"for year(s): {unresolved_extension}. Confirm temporal_extension.extension_policy."
        )

    inventory = {
        "source": args.source,
        "variable": args.variable,
        "access_mode": source_data.get("access_mode", "manual_or_internal"),
        "access_protocol": source_data.get("access_protocol", "local_file"),
        "source_family": source_data.get("source_family"),
        "provider": source_data.get("provider"),
        "public_source_verified": source_data.get("public_source_verified", False),
        "raw_archive": str(path),
        "archive_exists": path.exists(),
        "expected_period": source_data.get("expected_period"),
        "profecia_target_period": source_data.get("profecia_target_period"),
        "temporal_extension": source_data.get("temporal_extension"),
        "required_years_checked": years,
        "unresolved_extension_years": unresolved_extension,
        "formula": variable_data.get("formula"),
        "species_weights": {
            species: metadata.get("weight") for species, metadata in species_data.items()
        },
        "n_archive_members": len(members),
        "matched_files": matched,
        "missing_required": missing_required,
        "warnings": warnings,
        "status": status,
        "message": message,
        "notes": source_data.get("notes", []),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")

    for warning in warnings:
        print(f"WARNING: {warning}")
    print(message)
    if status != "OK" and not args.allow_missing:
        raise FileNotFoundError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-manual-input")
    check.add_argument("--config", required=True, type=Path)
    check.add_argument("--source", required=True)
    check.add_argument("--variable", required=True)
    check.add_argument("--output", required=True, type=Path)
    check.add_argument("--allow-missing", action="store_true")
    check.set_defaults(func=check_manual_input)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
