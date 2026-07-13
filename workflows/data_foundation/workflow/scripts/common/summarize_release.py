#!/usr/bin/env python3
"""Summarize PROFECIA data-foundation outputs for readiness checks."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, manifest_path, release_base_dir


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return str(value)


def find_name(candidates: list[str], names: list[str]) -> str | None:
    lowered = {name.lower(): name for name in names}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def step(values: np.ndarray) -> float | None:
    if values.size < 2:
        return None
    diffs = np.diff(values.astype("float64"))
    return float(np.nanmedian(diffs))


def time_summary(data: xr.Dataset, time_name: str | None) -> dict[str, Any]:
    if not time_name or time_name not in data:
        return {"name": None, "count": None, "start": None, "end": None, "step": None}
    values = data[time_name].values
    return {
        "name": time_name,
        "count": int(values.size),
        "start": jsonable(np.nanmin(values)),
        "end": jsonable(np.nanmax(values)),
        "step": jsonable(step(values)) if np.issubdtype(values.dtype, np.number) else None,
    }


def coord_summary(data: xr.Dataset, name: str | None) -> dict[str, Any]:
    if not name or name not in data:
        return {"name": name, "count": None, "min": None, "max": None, "step": None}
    values = data[name].values
    return {
        "name": name,
        "count": int(values.size),
        "min": jsonable(np.nanmin(values)),
        "max": jsonable(np.nanmax(values)),
        "step": jsonable(step(values)),
    }


def array_stats(array: xr.DataArray) -> dict[str, Any]:
    values = array.values
    finite = np.isfinite(values)
    n_total = int(values.size)
    n_valid = int(finite.sum())
    if n_valid == 0:
        return {
            "n_total": n_total,
            "n_valid": 0,
            "valid_fraction": 0.0,
            "min": None,
            "p01": None,
            "mean": None,
            "median": None,
            "p99": None,
            "max": None,
            "std": None,
        }
    sample = values[finite]
    return {
        "n_total": n_total,
        "n_valid": n_valid,
        "valid_fraction": n_valid / n_total,
        "min": float(np.nanmin(sample)),
        "p01": float(np.nanpercentile(sample, 1)),
        "mean": float(np.nanmean(sample)),
        "median": float(np.nanmedian(sample)),
        "p99": float(np.nanpercentile(sample, 99)),
        "max": float(np.nanmax(sample)),
        "std": float(np.nanstd(sample)),
    }


def summarize_netcdf(path: Path, variable: str) -> dict[str, Any]:
    with xr.open_dataset(path) as data:
        names = list(data.coords) + list(data.dims)
        time_name = find_name(["time", "valid_time", "year"], names)
        lat_name = find_name(["latitude", "lat", "y"], names)
        lon_name = find_name(["longitude", "lon", "x"], names)
        var_name = variable if variable in data.data_vars else next(iter(data.data_vars), None)
        array = data[var_name] if var_name else None
        return {
            "path": str(path),
            "kind": "netcdf",
            "selected_variable": var_name,
            "data_variables": list(data.data_vars),
            "dimensions": dict(data.sizes),
            "time": time_summary(data, time_name),
            "latitude": coord_summary(data, lat_name),
            "longitude": coord_summary(data, lon_name),
            "units": array.attrs.get("units") if array is not None else None,
            "statistics": array_stats(array) if array is not None else {},
        }


def summarize_file(path: Path, variable: str) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "kind": "missing", "status": "MISSING"}
    if path.suffix.lower() in {".nc", ".nc4"}:
        try:
            return summarize_netcdf(path, variable)
        except Exception as exc:
            return {
                "path": str(path),
                "kind": "netcdf",
                "status": "ERROR",
                "error": str(exc),
                "size_bytes": path.stat().st_size,
            }
    return {
        "path": str(path),
        "kind": "file",
        "size_bytes": path.stat().st_size,
        "status": "OK",
    }


def flatten_row(item: dict[str, Any], file_summary: dict[str, Any]) -> dict[str, Any]:
    stats = file_summary.get("statistics") or {}
    lat = file_summary.get("latitude") or {}
    lon = file_summary.get("longitude") or {}
    time = file_summary.get("time") or {}
    return {
        "source": item.get("source"),
        "variable": item.get("variable"),
        "access_mode": item.get("access_mode"),
        "file": file_summary.get("path"),
        "kind": file_summary.get("kind"),
        "selected_variable": file_summary.get("selected_variable"),
        "units": file_summary.get("units") or item.get("source_units"),
        "dims": json.dumps(file_summary.get("dimensions", {}), sort_keys=True),
        "time_count": time.get("count"),
        "time_start": time.get("start"),
        "time_end": time.get("end"),
        "lat_count": lat.get("count"),
        "lat_min": lat.get("min"),
        "lat_max": lat.get("max"),
        "lat_step": lat.get("step"),
        "lon_count": lon.get("count"),
        "lon_min": lon.get("min"),
        "lon_max": lon.get("max"),
        "lon_step": lon.get("step"),
        "n_valid": stats.get("n_valid"),
        "valid_fraction": stats.get("valid_fraction"),
        "min": stats.get("min"),
        "p01": stats.get("p01"),
        "mean": stats.get("mean"),
        "median": stats.get("median"),
        "p99": stats.get("p99"),
        "max": stats.get("max"),
        "std": stats.get("std"),
        "status": file_summary.get("status", "OK"),
        "error": file_summary.get("error"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-csv", type=Path)
    args = parser.parse_args()

    config = load_config(args.config)
    base_dir = release_base_dir(config)
    manifest = json.loads(manifest_path(config).read_text(encoding="utf-8"))
    summaries = []
    rows = []
    for item in manifest.get("selected_variables", []):
        raw_files = item.get("raw_files") or []
        manual_files = item.get("manual_files") or []
        files = raw_files or manual_files
        if not files:
            metadata = item.get("metadata") or {}
            files = [
                value
                for key, value in metadata.items()
                if value and key in {"manual_inventory", "source_download_report"}
            ]
        file_summaries = [
            summarize_file(base_dir / path, item.get("variable", "")) for path in files
        ]
        entry = {**item, "file_summaries": file_summaries}
        summaries.append(entry)
        rows.extend(flatten_row(item, summary) for summary in file_summaries)

    output_json = args.output_json or base_dir / "validation" / "release_summary.json"
    output_csv = args.output_csv or base_dir / "validation" / "release_summary.csv"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(jsonable(summaries), indent=2) + "\n", encoding="utf-8")
    if rows:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        with output_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(f"Wrote release summary JSON: {output_json}")
    print(f"Wrote release summary CSV: {output_csv}")


if __name__ == "__main__":
    main()
