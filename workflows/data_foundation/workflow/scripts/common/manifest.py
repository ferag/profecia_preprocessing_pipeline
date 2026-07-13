#!/usr/bin/env python3
"""Generate the PROFECIA data-foundation manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import (
    access_mode,
    is_source_bundle,
    load_config,
    manual_inventory_path,
    raw_output_path,
    release,
    release_base_dir,
    request_path,
    selected_variables,
    source_config,
    source_download_report_path,
    source_file_list_path,
    source_raw_files,
    variable_config,
    inspection_path,
)


def rel(path: Path, base_dir: Path) -> str | None:
    return path.relative_to(base_dir).as_posix() if path.exists() else None


def read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def variable_temporal_kind(var: dict[str, Any]) -> str:
    text = " ".join(
        str(var.get(key, "")).lower()
        for key in ("data_structure", "dimensionality", "native_temporal_resolution")
    )
    filename = str(var.get("output_filename", "")).lower()
    if "static" in text:
        return "static"
    if "annual" in text or "annual" in filename:
        return "annual"
    if "monthly" in text or "monthly" in filename or var.get("months"):
        return "monthly"
    return "static"


def harmonized_path(base_dir: Path, source: str, variable: str, var: dict[str, Any], source_bundle: bool) -> Path | None:
    kind = variable_temporal_kind(var)
    if kind == "monthly":
        return base_dir / "monthly" / f"{source}_{variable}_monthly_0.5deg.nc"
    if kind == "annual":
        return base_dir / "annual" / f"{source}_{variable}_annual_0.5deg.nc"
    if source_bundle and source == "hwsd2":
        return base_dir / "static" / "hwsd2_soil_0.5deg.nc"
    if kind == "static":
        return base_dir / "static" / f"{source}_static_0.5deg.nc"
    return None


def compact(values: list[str | None]) -> list[str]:
    return [value for value in values if value]


def unique(values: list[str]) -> list[str]:
    return sorted(set(values))


def sha256_file(path: Path, block_size: int = 1024 * 1024 * 8) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def provenance_inputs(config: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in config.get("provenance_inputs", []) or []:
        path = Path(str(item.get("path", "")))
        exists = path.exists()
        is_file = path.is_file()
        size = path.stat().st_size if exists and is_file else None
        copy_policy = str(item.get("copy_policy", "reference")).lower()
        should_hash = bool(exists and is_file and (copy_policy == "copy" or (size is not None and size <= 50 * 1024 * 1024)))
        entry = {
            "id": item.get("id") or path.stem,
            "role": item.get("role", "raw_input"),
            "path": str(path),
            "exists": exists,
            "is_file": is_file,
            "size_bytes": size,
            "sha256": sha256_file(path) if should_hash else None,
            "checksum_policy": "sha256" if should_hash else "not_computed_large_or_missing",
            "copy_policy": copy_policy,
            "license_or_terms": item.get("license_or_terms", "Governed by original provider terms."),
            "used_by": item.get("used_by", []),
            "description": item.get("description"),
        }
        if copy_policy == "copy" and not is_file:
            entry["warning"] = "copy_policy=copy requires an existing regular file; this input will only be referenced."
            entry["copy_policy"] = "reference"
        entries.append(entry)
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    config = load_config(args.config)
    base_dir = release_base_dir(config)
    release_data = release(config)
    entries = []
    source_entries: dict[str, dict[str, Any]] = {}
    for item in selected_variables(config):
        src = source_config(config, item.source)
        var = variable_config(config, item.source, item.variable)
        mode = access_mode(config, item.source).lower()
        source_bundle = is_source_bundle(config, item.source)
        request = request_path(config, item.source, item.variable)
        raw = (
            raw_output_path(config, item.source, item.variable)
            if mode in {"api", "http"} and not source_bundle
            else None
        )
        inventory = manual_inventory_path(config, item.source, item.variable)
        inspection = inspection_path(config, item.source, item.variable)
        file_list = source_file_list_path(config, item.source) if source_bundle else None
        download_report = source_download_report_path(config, item.source) if source_bundle else None
        harmonized = harmonized_path(base_dir, item.source, item.variable, var, source_bundle)
        metadata = {
            "request": rel(request, base_dir),
            "manual_inventory": rel(inventory, base_dir),
            "source_file_list": rel(file_list, base_dir) if file_list else None,
            "source_download_report": rel(download_report, base_dir) if download_report else None,
            "inspection": rel(inspection, base_dir),
        }
        raw_files = (
            [rel(path, base_dir) for path in source_raw_files(config, item.source) if path.exists()]
            if source_bundle
            else ([rel(raw, base_dir)] if raw and raw.exists() else [])
        )
        harmonized_files = [rel(harmonized, base_dir)] if harmonized and harmonized.exists() else []
        source_entries.setdefault(
            item.source,
            {
                "id": item.source,
                "provider": src.get("provider"),
                "source_family": src.get("source_family"),
                "access_mode": mode,
                "access_protocol": src.get("access_protocol"),
                "dataset": src.get("dataset"),
                "requires_authentication": src.get("requires_authentication", False),
                "terms": "Governed by original provider terms.",
                "variables": [],
            },
        )
        source_entries[item.source]["variables"].append(item.variable)
        entries.append(
            {
                "source": item.source,
                "variable": item.variable,
                "long_name": var.get("long_name", item.variable),
                "role": var.get("role"),
                "source_units": var.get("source_units"),
                "source_family": src.get("source_family"),
                "provider": src.get("provider"),
                "access_mode": mode,
                "access_protocol": src.get("access_protocol"),
                "requires_authentication": src.get("requires_authentication", False),
                "metadata": metadata,
                "raw_files": raw_files,
                "harmonized_files": harmonized_files,
                "manual_files": (read_json(inventory) or {}).get("matched_files", []),
            }
        )

    metadata_files = unique(
        compact(
            [
                "manifest.json",
                "checksums.sha256",
                "fair/harmonized_netcdf_demo.croissant.jsonld",
                "validation/release_validation.json",
                "validation/harmonized_validation.json",
            ]
        )
    )
    request_files = unique(compact([entry["metadata"].get("request") for entry in entries]))
    validation_reports = unique(
        compact(
            ["validation/harmonized_validation.json", "validation/release_validation.json"]
            + [entry["metadata"].get("inspection") for entry in entries]
        )
    )
    raw_files = unique(compact([path for entry in entries for path in entry.get("raw_files", [])]))
    harmonized_files = unique(compact([path for entry in entries for path in entry.get("harmonized_files", [])]))
    provenance = provenance_inputs(config)
    missing_harmonized = [
        f"{entry['source']}/{entry['variable']}"
        for entry in entries
        if not entry.get("harmonized_files")
    ]
    for item in config.get("derived_products", []) or []:
        variable = str(item.get("variable") or item.get("id"))
        source = str(item.get("source") or "derived")
        output = item.get("output_filename")
        if not variable or not output:
            continue
        kind = str(item.get("temporal_resolution", "monthly")).lower()
        folder = "annual" if kind == "annual" else ("static" if kind == "static" else "monthly")
        harmonized = base_dir / folder / str(output)
        input_files = [str(value) for value in item.get("input_files", [])]
        source_entries.setdefault(
            source,
            {
                "id": source,
                "provider": "PROFECIA data-foundation workflow",
                "source_family": "Derived PROFECIA variables",
                "access_mode": "derived",
                "access_protocol": "workflow_derivation",
                "dataset": None,
                "requires_authentication": False,
                "terms": "Derived from harmonized PROFECIA inputs; governed by release license and upstream terms.",
                "variables": [],
            },
        )
        source_entries[source]["variables"].append(variable)
        entries.append(
            {
                "source": source,
                "variable": variable,
                "long_name": item.get("long_name", variable),
                "role": item.get("role"),
                "source_units": item.get("source_units") or item.get("units"),
                "source_family": "Derived PROFECIA variables",
                "provider": "PROFECIA data-foundation workflow",
                "access_mode": "derived",
                "access_protocol": "workflow_derivation",
                "requires_authentication": False,
                "metadata": {
                    "request": None,
                    "manual_inventory": None,
                    "source_file_list": None,
                    "source_download_report": None,
                    "inspection": None,
                },
                "raw_files": [],
                "harmonized_files": [rel(harmonized, base_dir)] if harmonized.exists() else [],
                "manual_files": [],
                "derived": True,
                "derivation": {
                    "formula": item.get("formula"),
                    "weights": item.get("weights"),
                    "description": item.get("description"),
                    "input_files": input_files,
                    "source_variables": item.get("source_variables", []),
                    "notebook_reference": item.get("notebook_reference"),
                },
            }
        )

    for source in source_entries.values():
        source["variables"] = sorted(set(source["variables"]))

    manifest = {
        "data_release_id": release_data.get("id"),
        "status": release_data.get("status"),
        "created_by": "Snakemake data_foundation pipeline",
        "release": release_data,
        "configured_sources": source_entries,
        "selected_sources": sorted(source_entries),
        "selected_variables": entries,
        "release_metadata": metadata_files,
        "source_request_metadata": request_files,
        "raw_source_files": raw_files,
        "provenance_inputs": provenance,
        "harmonized_files": harmonized_files,
        "validation_reports": validation_reports,
        "croissant_descriptor": "fair/harmonized_netcdf_demo.croissant.jsonld",
        "checksums": "checksums.sha256",
        "workflow_code": [
            "workflow/Snakefile",
            "workflow/rules/*.smk",
            "workflow/scripts/**/*.py",
            "workflow/envs/*.yml",
        ],
        "excluded_files": [
            ".env",
            ".netrc",
            "config/*.local.yml",
            "config/*secrets*.yml unless explicitly marked as example/template",
        ],
        "credential_templates": [
            "config/secrets.local.example.yml",
            "config/user_settings.template.yml",
        ],
        "warnings": (
            [
                "Demo release has no DOI yet.",
                "External source data are provenance inputs governed by original provider terms.",
            ]
            + [f"Harmonized product missing from manifest for {key}." for key in missing_harmonized]
            + [f"Configured provenance input does not exist: {item['path']}" for item in provenance if not item.get("exists")]
        ),
        "errors": [],
        "notes": [
            "The manifest is the contract consumed by later PROFECIA pipelines.",
            "Manual sources are registered from local files and are not downloaded by this workflow.",
            "Harmonized NetCDF files are the official release products; raw/source files are provenance inputs.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote manifest: {args.output}")


if __name__ == "__main__":
    main()
