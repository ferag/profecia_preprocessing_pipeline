#!/usr/bin/env python3
"""Inspect a NetCDF file and write a compact validation report."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--variable", required=True)
    parser.add_argument("--expected-names", default="")
    parser.add_argument("--expected-unit", required=True)
    parser.add_argument("--expected-time-steps", required=True, type=int)
    parser.add_argument("--min-reasonable-value", required=True, type=float)
    parser.add_argument("--max-reasonable-value", required=True, type=float)
    return parser.parse_args()


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


def variable_name(dataset: xr.Dataset, expected_names: list[str], warnings: list[str]) -> str | None:
    lowered_data_vars = {name.lower(): name for name in dataset.data_vars}
    for expected in expected_names:
        if expected.lower() in lowered_data_vars:
            return lowered_data_vars[expected.lower()]
    for name, data_array in dataset.data_vars.items():
        attrs = {key.lower(): str(value).lower() for key, value in data_array.attrs.items()}
        if any(expected.lower() in attrs.values() for expected in expected_names):
            warnings.append(
                f"Using equivalent variable '{name}' for expected one of {expected_names}."
            )
            return name
    warnings.append(f"Expected variable names {expected_names} were not found.")
    return None


def coord_range(dataset: xr.Dataset, name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    values = dataset[name].values
    return {"min": to_jsonable(np.nanmin(values)), "max": to_jsonable(np.nanmax(values))}


def main() -> None:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    with args.log.open("w", encoding="utf-8") as log_handle:
        with contextlib.redirect_stdout(log_handle), contextlib.redirect_stderr(log_handle):
            print("PROFECIA NetCDF inspection")
            print(f"Input: {args.input}")

            with xr.open_dataset(args.input) as dataset:
                expected_names = [
                    item.strip()
                    for item in (args.expected_names or args.variable).split(",")
                    if item.strip()
                ]
                var_name = variable_name(dataset, expected_names, warnings)
                all_names = list(dataset.coords) + list(dataset.dims)
                time_name = find_name(["time", "valid_time"], all_names)
                lat_name = find_name(["latitude", "lat", "y"], all_names)
                lon_name = find_name(["longitude", "lon", "x"], all_names)

                if not time_name:
                    warnings.append("No temporal coordinate or dimension found.")
                if not lat_name:
                    warnings.append("No latitude coordinate or dimension found.")
                if not lon_name:
                    warnings.append("No longitude coordinate or dimension found.")

                data_array = dataset[var_name] if var_name else None
                units = data_array.attrs.get("units") if data_array is not None else None
                if units and units != args.expected_unit:
                    warnings.append(f"Expected units '{args.expected_unit}', found '{units}'.")
                if not units:
                    warnings.append("Variable units attribute is missing.")

                time_steps = int(dataset.sizes[time_name]) if time_name and time_name in dataset.sizes else None
                if time_steps != args.expected_time_steps:
                    warnings.append(
                        f"Expected {args.expected_time_steps} time steps, found {time_steps}."
                    )

                stats = {}
                shape = None
                encoding = {}
                if data_array is not None:
                    shape = list(data_array.shape)
                    encoding = to_jsonable(data_array.encoding)
                    min_value = float(data_array.min(skipna=True).values)
                    max_value = float(data_array.max(skipna=True).values)
                    mean_value = float(data_array.mean(skipna=True).values)
                    stats = {"min": min_value, "max": max_value, "mean": mean_value}
                    if min_value < args.min_reasonable_value or max_value > args.max_reasonable_value:
                        warnings.append(
                            "Values are outside the configured reasonable range "
                            f"{args.min_reasonable_value}-{args.max_reasonable_value}."
                        )

                time_range = None
                if time_name and time_name in dataset:
                    time_values = dataset[time_name].values
                    time_range = {
                        "start": to_jsonable(np.nanmin(time_values)),
                        "end": to_jsonable(np.nanmax(time_values)),
                    }

                report = {
                    "file_path": str(args.input),
                    "requested_variable": args.variable,
                    "expected_names": expected_names,
                    "variables": list(dataset.data_vars),
                    "selected_variable": var_name,
                    "dimensions": dict(dataset.sizes),
                    "coordinates": list(dataset.coords),
                    "shape": shape,
                    "units": units,
                    "time_range": time_range,
                    "lat_range": coord_range(dataset, lat_name),
                    "lon_range": coord_range(dataset, lon_name),
                    "encoding": encoding,
                    "global_attributes": to_jsonable(dataset.attrs),
                    "statistics": stats,
                    "warnings": warnings,
                    "status": "OK" if not warnings else "WARNINGS",
                }

            args.output.write_text(json.dumps(to_jsonable(report), indent=2) + "\n", encoding="utf-8")
            print(f"Status: {report['status']}")
            for warning in warnings:
                print(f"WARNING: {warning}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
