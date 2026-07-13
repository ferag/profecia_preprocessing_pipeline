#!/usr/bin/env python3
"""NOAA CarbonTracker CT2022 + NOAA GML CO2 source adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import xarray as xr

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, source_config, variable_config


def month_values(source_data: dict[str, Any]) -> list[int]:
    months = source_data.get("carbontracker", {}).get("months")
    if months:
        return [int(month) for month in months]
    return list(range(1, 13))


def carbontracker_files(source_data: dict[str, Any]) -> list[dict[str, Any]]:
    ct = source_data.get("carbontracker", {})
    base_url = str(ct["base_url"]).rstrip("/") + "/"
    pattern = ct.get("filename_pattern", "CT2022.molefrac_glb3x2_{year}-{month:02d}.nc")
    start_year = int(ct["start_year"])
    end_year = int(ct["end_year"])
    files = []
    for year in range(start_year, end_year + 1):
        for month in month_values(source_data):
            filename = pattern.format(year=year, month=f"{month:02d}", month_int=month)
            files.append(
                {
                    "year": year,
                    "month": month,
                    "filename": filename,
                    "url": base_url + filename,
                }
            )
    return files


def request_payload(config_path: Path, source: str, variable: str) -> dict[str, Any]:
    config = load_config(config_path)
    source_data = source_config(config, source)
    variable_data = variable_config(config, source, variable)
    return {
        "source": source,
        "variable": variable,
        "provider": source_data.get("provider"),
        "source_family": source_data.get("source_family"),
        "access_mode": source_data.get("access_mode"),
        "access_protocol": source_data.get("access_protocol"),
        "carbontracker": source_data.get("carbontracker", {}),
        "noaa_gml_global_mean": source_data.get("noaa_gml_global_mean", {}),
        "files": carbontracker_files(source_data),
        "output_variable": variable_data.get("native_variable", variable),
        "notes": source_data.get("notes", []),
    }


def build_request(args: argparse.Namespace) -> None:
    payload = request_payload(args.config, args.source, args.variable)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"Built CO2 request for {len(payload['files'])} CarbonTracker monthly files: "
        f"{args.output}"
    )


def download_file(url: str, output: Path) -> None:
    if output.exists() and output.stat().st_size > 0:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    tmp.replace(output)


def merge_carbontracker(files: list[Path], variable: str, output: Path, gml_csv: Path) -> None:
    arrays = []
    for path in files:
        with xr.open_dataset(path) as dataset:
            if variable not in dataset:
                raise KeyError(f"Variable '{variable}' not found in {path}")
            arrays.append(dataset[variable].load())
    merged = xr.concat(arrays, dim="time").sortby("time").to_dataset(name=variable)
    merged[variable].attrs.update(
        {
            "long_name": "Atmospheric CO2 mole fraction",
            "units": "ppm",
            "source": "CarbonTracker CT2022 monthly mole fraction fields",
            "noaa_gml_global_mean_csv": str(gml_csv),
            "note": (
                "NOAA GML global mean CO2 is downloaded for later temporal "
                "extension/offset preprocessing; this file contains the native "
                "CarbonTracker spatial monthly fields."
            ),
        }
    )
    encoding = {variable: {"zlib": True, "complevel": 4, "dtype": "float32"}}
    output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_netcdf(output, encoding=encoding)
    merged.close()


def download(args: argparse.Namespace) -> None:
    payload = json.loads(args.request.read_text(encoding="utf-8"))
    variable = payload.get("output_variable", args.variable)
    monthly_dir = args.output.parent / "carbontracker_monthly_files"
    monthly_paths = []
    for item in payload["files"]:
        path = monthly_dir / item["filename"]
        print(f"Downloading/checking {item['url']}")
        download_file(item["url"], path)
        monthly_paths.append(path)

    gml = payload.get("noaa_gml_global_mean", {})
    gml_url = gml.get("url")
    gml_path = args.output.parent / "noaa_gml_global_mean_monthly.csv"
    if gml_url:
        print(f"Downloading/checking {gml_url}")
        download_file(gml_url, gml_path)
        # Parse once so failures are caught during acquisition.
        pd.read_csv(gml_path, comment="#")

    merge_carbontracker(monthly_paths, variable=variable, output=args.output, gml_csv=gml_path)
    print(f"Wrote merged CarbonTracker CO2 file: {args.output}")

    if not payload.get("carbontracker", {}).get("keep_monthly_files", False):
        for path in monthly_paths:
            path.unlink(missing_ok=True)
        try:
            monthly_dir.rmdir()
        except OSError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-request")
    build.add_argument("--config", required=True, type=Path)
    build.add_argument("--source", required=True)
    build.add_argument("--variable", required=True)
    build.add_argument("--output", required=True, type=Path)
    build.set_defaults(func=build_request)

    dl = sub.add_parser("download")
    dl.add_argument("--config", required=True, type=Path)
    dl.add_argument("--source", required=True)
    dl.add_argument("--variable", required=True)
    dl.add_argument("--request", required=True, type=Path)
    dl.add_argument("--output", required=True, type=Path)
    dl.add_argument("--log", required=True, type=Path)
    dl.add_argument("--user-settings", default="")
    dl.set_defaults(func=download)
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
