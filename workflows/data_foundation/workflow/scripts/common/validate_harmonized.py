#!/usr/bin/env python3
"""Validate harmonized PROFECIA outputs on the 0.5 degree grid."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


def find_name(candidates: list[str], names: set[str]) -> str | None:
    lowered = {name.lower(): name for name in names}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def _range_matches(values: np.ndarray, allowed: list[tuple[float, float]], tolerance: float = 1e-6) -> bool:
    actual = (float(np.nanmin(values)), float(np.nanmax(values)))
    return any(np.isclose(actual[0], low, atol=tolerance) and np.isclose(actual[1], high, atol=tolerance) for low, high in allowed)


def check_file(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    with xr.open_dataset(path) as ds:
        names = set(ds.coords) | set(ds.dims)
        lat_name = find_name(["latitude", "lat", "y"], names)
        lon_name = find_name(["longitude", "lon", "x"], names)
        time_name = find_name(["time", "valid_time", "year"], names)
        if not lat_name or not lon_name:
            errors.append("Missing latitude/longitude coordinate.")
            return {"path": str(path), "status": "FAILED", "errors": errors, "warnings": warnings}
        lat = ds[lat_name].values.astype("float64")
        lon = ds[lon_name].values.astype("float64")
        if len(lat) != 360:
            errors.append(f"Latitude length {len(lat)} != 360.")
        if len(lon) != 720:
            errors.append(f"Longitude length {len(lon)} != 720.")
        if len(lat) > 1 and abs(float(np.nanmedian(np.abs(np.diff(lat)))) - 0.5) > 1e-6:
            errors.append("Latitude spacing is not 0.5 degrees.")
        if len(lon) > 1 and abs(float(np.nanmedian(np.abs(np.diff(lon)))) - 0.5) > 1e-6:
            errors.append("Longitude spacing is not 0.5 degrees.")
        lat_allowed = [(-90.0, 89.5)]
        lon_allowed = [(-180.0, 179.5)]
        if not _range_matches(lat, lat_allowed):
            errors.append(f"Latitude range is [{float(np.nanmin(lat))}, {float(np.nanmax(lat))}], expected one of {lat_allowed}.")
        if not _range_matches(lon, lon_allowed):
            errors.append(f"Longitude range is [{float(np.nanmin(lon))}, {float(np.nanmax(lon))}], expected one of {lon_allowed}.")
        for name, data in ds.data_vars.items():
            finite = int(np.isfinite(data.values).sum())
            if finite == 0:
                errors.append(f"Variable {name} has no finite values.")
        return {
            "path": str(path),
            "status": "FAILED" if errors else ("WARNINGS" if warnings else "OK"),
            "dims": dict(ds.sizes),
            "variables": list(ds.data_vars),
            "time_coordinate": time_name,
            "errors": errors,
            "warnings": warnings,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args()

    reports = [check_file(path) for path in args.files if path.exists()]
    errors = [error for report in reports for error in report.get("errors", [])]
    warnings = [warning for report in reports for warning in report.get("warnings", [])]
    result = {
        "status": "FAILED" if errors else ("WARNINGS" if warnings else "OK"),
        "files_checked": len(reports),
        "errors": errors,
        "warnings": warnings,
        "reports": reports,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Harmonized validation status: {result['status']} ({len(reports)} files)")
    if errors:
        raise RuntimeError("Harmonized validation failed.")


if __name__ == "__main__":
    main()
