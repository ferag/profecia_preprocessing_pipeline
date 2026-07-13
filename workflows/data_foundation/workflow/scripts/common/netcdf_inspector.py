#!/usr/bin/env python3
"""Inspect one NetCDF file and write a JSON report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, variable_config


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.dtype):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return str(value)


def find_name(candidates: list[str], names: list[str]) -> str | None:
    lowered = {name.lower(): name for name in names}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def coord_range(dataset: xr.Dataset, name: str | None) -> dict[str, Any] | None:
    if not name or name not in dataset:
        return None
    values = dataset[name].values
    return {"min": to_jsonable(np.nanmin(values)), "max": to_jsonable(np.nanmax(values))}


def select_variable(dataset: xr.Dataset, expected: list[str], warnings: list[str]) -> str | None:
    lowered = {name.lower(): name for name in dataset.data_vars}
    for name in expected:
        if name.lower() in lowered:
            return lowered[name.lower()]
    warnings.append(f"Expected data variable names {expected} were not found.")
    return next(iter(dataset.data_vars), None)


def inspect(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    var_data = variable_config(config, args.source, args.variable)
    expected_names = [args.variable]
    if var_data.get("cds_name"):
        expected_names.append(str(var_data["cds_name"]))

    warnings: list[str] = []
    with xr.open_dataset(args.input) as dataset:
        all_names = list(dataset.coords) + list(dataset.dims)
        time_name = find_name(["time", "valid_time"], all_names)
        lat_name = find_name(["latitude", "lat", "y"], all_names)
        lon_name = find_name(["longitude", "lon", "x"], all_names)
        var_name = select_variable(dataset, expected_names, warnings)
        data_array = dataset[var_name] if var_name else None

        if not time_name:
            warnings.append("No temporal coordinate or dimension found.")
        if not lat_name:
            warnings.append("No latitude coordinate or dimension found.")
        if not lon_name:
            warnings.append("No longitude coordinate or dimension found.")

        units = data_array.attrs.get("units") if data_array is not None else None
        expected_units = var_data.get("source_units")
        if expected_units and units and units != expected_units:
            warnings.append(f"Expected units '{expected_units}', found '{units}'.")
        if data_array is not None and not units:
            warnings.append("Variable units attribute is missing.")

        stats = {}
        shape = None
        if data_array is not None:
            shape = list(data_array.shape)
            stats = {
                "min": float(data_array.min(skipna=True).values),
                "max": float(data_array.max(skipna=True).values),
                "mean": float(data_array.mean(skipna=True).values),
            }
            expected_min = var_data.get("expected_min")
            expected_max = var_data.get("expected_max")
            if expected_min is not None and stats["min"] < float(expected_min):
                warnings.append(f"Minimum value {stats['min']} is below expected_min {expected_min}.")
            if expected_max is not None and stats["max"] > float(expected_max):
                warnings.append(f"Maximum value {stats['max']} is above expected_max {expected_max}.")

        time_range = None
        if time_name and time_name in dataset:
            values = dataset[time_name].values
            time_range = {"start": to_jsonable(np.nanmin(values)), "end": to_jsonable(np.nanmax(values))}

        report = {
            "file_path": str(args.input),
            "source": args.source,
            "variable": args.variable,
            "variables": list(dataset.data_vars),
            "dimensions": dict(dataset.sizes),
            "coordinates": list(dataset.coords),
            "selected_variable": var_name,
            "shape": shape,
            "units": units,
            "time_range": time_range,
            "lat_range": coord_range(dataset, lat_name),
            "lon_range": coord_range(dataset, lon_name),
            "global_attributes": to_jsonable(dataset.attrs),
            "statistics": stats,
            "warnings": warnings,
            "status": "OK" if not warnings else "WARNINGS",
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(to_jsonable(report), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote inspection report: {args.output} ({report['status']})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--variable", required=True)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    inspect(parse_args())


if __name__ == "__main__":
    main()
