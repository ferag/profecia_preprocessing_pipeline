#!/usr/bin/env python3
"""Small helpers for the PROFECIA data-foundation config.

The central YAML file describes sources and variables. These helpers keep path
construction and config lookup consistent across Snakemake-facing scripts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SelectedVariable:
    source: str
    variable: str

    @property
    def key(self) -> str:
        return f"{self.source}/{self.variable}"


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a YAML mapping: {config_path}")
    return data


def release(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("release", {})
    if not isinstance(value, dict):
        raise ValueError("Config key 'release' must be a mapping.")
    return value


def release_base_dir(config: dict[str, Any]) -> Path:
    base_dir = release(config).get("base_dir")
    if not base_dir:
        raise ValueError("Config key release.base_dir is required.")
    return Path(base_dir)


def selected_variables(config: dict[str, Any]) -> list[SelectedVariable]:
    values = config.get("selected_variables", [])
    if not isinstance(values, list):
        raise ValueError("Config key 'selected_variables' must be a list.")
    selected: list[SelectedVariable] = []
    for item in values:
        if not isinstance(item, dict) or not item.get("source") or not item.get("variable"):
            raise ValueError(
                "Each selected_variables item must contain 'source' and 'variable'."
            )
        selected.append(SelectedVariable(str(item["source"]), str(item["variable"])))
    return selected


def source_config(config: dict[str, Any], source: str) -> dict[str, Any]:
    sources = config.get("sources", {})
    if not isinstance(sources, dict) or source not in sources:
        raise KeyError(f"Unknown source '{source}'.")
    value = sources[source]
    if not isinstance(value, dict):
        raise ValueError(f"Source config must be a mapping: {source}")
    return value


def variable_config(config: dict[str, Any], source: str, variable: str) -> dict[str, Any]:
    source_data = source_config(config, source)
    variables = source_data.get("variables", {})
    if not isinstance(variables, dict) or variable not in variables:
        raise KeyError(f"Unknown variable '{source}/{variable}'.")
    value = variables[variable]
    if not isinstance(value, dict):
        raise ValueError(f"Variable config must be a mapping: {source}/{variable}")
    return value


def access_mode(config: dict[str, Any], source: str) -> str:
    return str(source_config(config, source).get("access_mode", "manual"))


def adapter(config: dict[str, Any], source: str) -> str:
    return str(source_config(config, source).get("adapter", source))


def is_source_bundle(config: dict[str, Any], source: str) -> bool:
    return bool(source_config(config, source).get("data_files")) or access_mode(
        config, source
    ).lower() in {"usgs_authenticated"}


def request_path(config: dict[str, Any], source: str, variable: str) -> Path:
    return release_base_dir(config) / "metadata" / source / variable / "request.json"


def manual_inventory_path(config: dict[str, Any], source: str, variable: str) -> Path:
    return release_base_dir(config) / "metadata" / source / variable / "manual_inventory.json"


def source_file_list_path(config: dict[str, Any], source: str) -> Path:
    return release_base_dir(config) / "metadata" / source / "file_list.json"


def source_download_report_path(config: dict[str, Any], source: str) -> Path:
    return release_base_dir(config) / "metadata" / source / "download_report.json"


def source_raw_dir(config: dict[str, Any], source: str) -> Path:
    return release_base_dir(config) / "raw" / source


def source_raw_files(config: dict[str, Any], source: str) -> list[Path]:
    files = source_config(config, source).get("data_files") or {}
    return [
        source_raw_dir(config, source) / str(item["filename"])
        for item in files.values()
        if isinstance(item, dict) and item.get("filename")
    ]


def raw_output_path(config: dict[str, Any], source: str, variable: str) -> Path:
    var_data = variable_config(config, source, variable)
    filename = var_data.get("output_filename")
    if not filename:
        raise ValueError(f"Variable '{source}/{variable}' needs output_filename.")
    return release_base_dir(config) / "raw" / source / variable / str(filename)


def selected_api_variables(config: dict[str, Any]) -> list[SelectedVariable]:
    return [
        item
        for item in selected_variables(config)
        if access_mode(config, item.source).lower() in {"api", "http", "usgs_authenticated"}
        and not is_source_bundle(config, item.source)
    ]


def selected_manual_variables(config: dict[str, Any]) -> list[SelectedVariable]:
    return [
        item
        for item in selected_variables(config)
        if access_mode(config, item.source).lower() in {"manual", "manual_or_internal"}
    ]


def inspection_path(config: dict[str, Any], source: str, variable: str) -> Path:
    return release_base_dir(config) / "validation" / source / variable / "inspection.json"


def manifest_path(config: dict[str, Any]) -> Path:
    return release_base_dir(config) / "manifest.json"


def checksums_path(config: dict[str, Any]) -> Path:
    return release_base_dir(config) / "checksums.sha256"


def croissant_path(config: dict[str, Any]) -> Path:
    return release_base_dir(config) / "fair" / "harmonized_netcdf_demo.croissant.jsonld"


def release_validation_path(config: dict[str, Any]) -> Path:
    return release_base_dir(config) / "validation" / "release_validation.json"
