#!/usr/bin/env python3
"""Validate the PROFECIA data-foundation demo release."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import (
    access_mode,
    checksums_path,
    croissant_path,
    inspection_path,
    is_source_bundle,
    load_config,
    manifest_path,
    manual_inventory_path,
    raw_output_path,
    release_base_dir,
    release_validation_path,
    selected_variables,
    source_download_report_path,
    source_file_list_path,
    source_raw_files,
    variable_config,
)


def read_json(path: Path, errors: list[str]) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"Invalid JSON file {path}: {exc}")
        return {}


def parse_checksums(path: Path) -> set[str]:
    if not path.exists():
        return set()
    values = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        _, _, relative = line.partition("  ")
        if relative:
            values.add(relative.strip())
    return values


def has_annual_canonical_co2(config: dict) -> bool:
    return bool((config.get("canonical_reference_products") or {}).get("annual/co2"))


def variable_has_canonical_reference(config: dict, source: str, variable: str) -> bool:
    try:
        return bool(variable_config(config, source, variable).get("canonical_reference_path"))
    except Exception:
        return False


def skip_api_acquisition(config: dict, source: str, variable: str) -> bool:
    if variable_has_canonical_reference(config, source, variable):
        return True
    if source == "carbontracker_co2" and variable == "co2" and has_annual_canonical_co2(config):
        return True
    return False


def skip_manifest_harmonized_requirement(config: dict, source: str, variable: str) -> bool:
    return source == "carbontracker_co2" and variable == "co2" and has_annual_canonical_co2(config)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    config = load_config(args.config)
    output = args.output or release_validation_path(config)
    errors: list[str] = []
    warnings: list[str] = []

    required = [manifest_path(config), checksums_path(config), croissant_path(config)]
    for path in required:
        if not path.exists():
            errors.append(f"Missing required release file: {path}")

    manifest_data = {}
    croissant_data = {}
    for path in required:
        if path.suffix in {".json", ".jsonld"} and path.exists():
            data = read_json(path, errors)
            if path == manifest_path(config):
                manifest_data = data
            elif path == croissant_path(config):
                croissant_data = data

    harmonized_validation = release_base_dir(config) / "validation" / "harmonized_validation.json"
    if not harmonized_validation.exists():
        errors.append(f"Missing harmonized validation file: {harmonized_validation}")
    else:
        data = read_json(harmonized_validation, errors)
        if data.get("status") == "FAILED":
            errors.append(f"Harmonized validation failed: {harmonized_validation}")
        elif data.get("status") == "WARNINGS":
            warnings.append(f"Harmonized validation warnings: {harmonized_validation}")

    checksummed = parse_checksums(checksums_path(config))
    manifest_harmonized = set(manifest_data.get("harmonized_files") or [])
    if not manifest_harmonized:
        errors.append("Manifest has no harmonized_files entries; harmonized NetCDF products are the official release outputs.")
    for item in manifest_data.get("selected_variables", []):
        if not item.get("harmonized_files"):
            source = str(item.get("source"))
            variable = str(item.get("variable"))
            if skip_manifest_harmonized_requirement(config, source, variable):
                warnings.append(
                    f"Harmonized product intentionally omitted for intermediate source {source}/{variable}; annual canonical CO2 is used instead."
                )
            else:
                errors.append(f"Harmonized product missing from manifest for {source}/{variable}")
    for relative in sorted(manifest_harmonized):
        if relative not in checksummed:
            errors.append(f"Missing checksum for harmonized product: {relative}")
    for relative in ["manifest.json", "fair/harmonized_netcdf_demo.croissant.jsonld", "validation/harmonized_validation.json"]:
        if relative not in checksummed:
            errors.append(f"Missing checksum for required metadata artifact: {relative}")
    croissant_distributions = {entry.get("contentUrl") for entry in croissant_data.get("distribution") or []}
    missing_from_croissant = manifest_harmonized - croissant_distributions
    for relative in sorted(missing_from_croissant):
        errors.append(f"Harmonized product missing from Croissant descriptor: {relative}")

    ro_crate = release_base_dir(config) / "ro-crate" / "ro-crate-metadata.json"
    if ro_crate.exists():
        crate_data = read_json(ro_crate, errors)
        graph_ids = {entity.get("@id") for entity in crate_data.get("@graph", [])}
        for relative in sorted(manifest_harmonized):
            expected_id = f"referenced-data/{relative}"
            if expected_id not in graph_ids and relative not in graph_ids:
                errors.append(f"Harmonized product missing from RO-Crate graph: {relative}")
    else:
        warnings.append(f"RO-Crate metadata not available yet for release coverage check: {ro_crate}")

    for item in selected_variables(config):
        mode = access_mode(config, item.source).lower()
        if mode in {"api", "http", "usgs_authenticated"} and is_source_bundle(config, item.source):
            file_list = source_file_list_path(config, item.source)
            report = source_download_report_path(config, item.source)
            if not file_list.exists():
                errors.append(f"Missing source file list for {item.key}: {file_list}")
            if not report.exists():
                errors.append(f"Missing source download report for {item.key}: {report}")
            else:
                data = read_json(report, errors)
                if data.get("status") == "AUTHENTICATED_PENDING_PRODUCT_SELECTION":
                    warnings.append(data.get("message", f"Source needs product selection: {report}"))
                elif data.get("status") != "OK":
                    errors.append(data.get("message", f"Source download report is not OK: {report}"))
            for raw in source_raw_files(config, item.source):
                if not raw.exists():
                    errors.append(f"Missing source raw file for {item.key}: {raw}")
        elif mode in {"api", "http", "usgs_authenticated"}:
            if skip_api_acquisition(config, item.source, item.variable):
                warnings.append(
                    f"API acquisition intentionally skipped for {item.key}; canonical reference product is used."
                )
                continue
            raw = raw_output_path(config, item.source, item.variable)
            inspection = inspection_path(config, item.source, item.variable)
            if not raw.exists():
                errors.append(f"Missing API data file for {item.key}: {raw}")
            if not inspection.exists():
                errors.append(f"Missing NetCDF inspection for {item.key}: {inspection}")
            elif read_json(inspection, errors).get("warnings"):
                warnings.append(f"Inspection warnings for {item.key}: {inspection}")
        elif mode in {"manual", "manual_or_internal"}:
            inventory = manual_inventory_path(config, item.source, item.variable)
            if not inventory.exists():
                errors.append(f"Missing manual inventory for {item.key}: {inventory}")
            else:
                data = read_json(inventory, errors)
                if data.get("status") != "OK":
                    errors.append(data.get("message", f"Manual inventory is not OK: {inventory}"))
                for warning in data.get("warnings", []):
                    warnings.append(f"Manual inventory warning for {item.key}: {warning}")
        else:
            errors.append(f"Unsupported access_mode for {item.key}: {mode}")

    result = {
        "status": "FAILED" if errors else ("WARNINGS" if warnings else "OK"),
        "errors": errors,
        "warnings": warnings,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Release validation status: {result['status']}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise RuntimeError("Release validation failed.")


if __name__ == "__main__":
    main()
