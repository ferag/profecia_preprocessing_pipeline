#!/usr/bin/env python3
"""SPEIbase v2.11 source adapter for PROFECIA data-foundation."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import requests
import xarray as xr

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, release, source_config, variable_config

VALID_SCALES = (1, 2, 3, 6, 9, 12, 24)
DEFAULT_BASE_URL = "https://spei.csic.es/spei_database_2_11/nc/"


def normalize_scale(scale: int | str) -> str:
    value = int(scale)
    if value not in VALID_SCALES:
        raise ValueError(f"Invalid SPEI scale {scale}. Valid scales: {VALID_SCALES}")
    return f"{value:02d}"


def variable_scale(variable: str, variable_data: dict[str, Any]) -> str:
    if variable_data.get("scale") is not None:
        return normalize_scale(variable_data["scale"])
    if variable.lower().startswith("spei"):
        return normalize_scale(variable.lower().replace("spei", ""))
    raise ValueError(f"Cannot infer SPEI scale for variable '{variable}'.")


def request_payload(config_path: Path, source: str, variable: str) -> dict[str, Any]:
    config = load_config(config_path)
    release_data = release(config)
    source_data = source_config(config, source)
    variable_data = variable_config(config, source, variable)
    scale = variable_scale(variable, variable_data)
    base_url = str(source_data.get("base_url", DEFAULT_BASE_URL)).rstrip("/") + "/"
    source_filename = variable_data.get("source_filename", f"spei{scale}.nc")
    target_start = int(variable_data.get("start_year", release_data.get("start_year", 1982)))
    target_end = int(variable_data.get("end_year", release_data.get("end_year", 2022)))
    source_start = int(source_data.get("source_start_year", 1901))
    source_end = int(source_data.get("source_end_year", 2023))
    return {
        "source": source,
        "variable": variable,
        "provider": source_data.get("provider"),
        "source_family": source_data.get("source_family"),
        "access_mode": source_data.get("access_mode"),
        "access_protocol": source_data.get("access_protocol"),
        "doi": source_data.get("doi"),
        "landing_page": source_data.get("landing_page"),
        "spei_version": source_data.get("version", "2.11"),
        "scale_months": int(scale),
        "base_url": base_url,
        "source_filename": source_filename,
        "url": base_url + str(source_filename),
        "source_period": {"start_year": source_start, "end_year": source_end},
        "target_period": {"start_year": target_start, "end_year": target_end},
        "native_variable": variable_data.get("native_variable", "spei"),
        "output_variable": variable,
        "notes": source_data.get("notes", []),
    }


def build_request(args: argparse.Namespace) -> None:
    payload = request_payload(args.config, args.source, args.variable)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        "Built SPEI request "
        f"scale={payload['scale_months']:02d} url={payload['url']} output={args.output}"
    )


def download_file(url: str, output: Path, timeout: int, retries: int = 4) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        tmp.unlink(missing_ok=True)
        try:
            print(f"Download attempt {attempt}/ {retries}: {url}")
            with requests.get(url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            tmp.replace(output)
            return
        except (requests.RequestException, OSError) as error:
            last_error = error
            tmp.unlink(missing_ok=True)
            if attempt == retries:
                break
            delay = min(60, 5 * attempt)
            print(f"Download attempt {attempt} failed: {error}. Retrying in {delay}s...")
            time.sleep(delay)
    raise RuntimeError(f"Failed to download {url} after {retries} attempt(s).") from last_error


def standardize_spatial_names(dataset: xr.Dataset) -> xr.Dataset:
    names = set(dataset.coords) | set(dataset.dims)
    rename: dict[str, str] = {}
    if "lat" in names and "latitude" not in names:
        rename["lat"] = "latitude"
    if "lon" in names and "longitude" not in names:
        rename["lon"] = "longitude"
    if rename:
        dataset = dataset.rename(rename)
    return dataset


def write_temporal_subset(source_path: Path, payload: dict[str, Any], output: Path) -> None:
    target = payload["target_period"]
    start = f"{target['start_year']}-01-01"
    end = f"{target['end_year']}-12-31"
    native_variable = payload.get("native_variable", "spei")
    output_variable = payload.get("output_variable", native_variable)

    with xr.open_dataset(source_path) as dataset:
        if "time" not in set(dataset.coords) | set(dataset.dims):
            raise ValueError(f"SPEI source has no time coordinate: {source_path}")
        dataset = standardize_spatial_names(dataset)
        subset = dataset.sel(time=slice(start, end))
        if subset.sizes.get("time", 0) == 0:
            raise ValueError(f"SPEI temporal subset is empty for {start} to {end}.")
        if native_variable not in subset.data_vars:
            native_variable = next(iter(subset.data_vars))
        subset = subset[[native_variable]]
        if native_variable != output_variable:
            subset = subset.rename({native_variable: output_variable})
        if subset[output_variable].dtype == "float64":
            subset[output_variable] = subset[output_variable].astype("float32")
        subset[output_variable].attrs.update(
            {
                "long_name": f"SPEI {payload['scale_months']:02d}-month scale",
                "units": "standardized_index",
                "source": "SPEIbase v2.11, CSIC",
                "source_url": payload["url"],
                "temporal_subset": f"{start} to {end}",
            }
        )
        subset.attrs.update(dataset.attrs)
        subset.attrs.update(
            {
                "source": "SPEIbase v2.11, CSIC",
                "source_url": payload["url"],
                "source_file": str(source_path),
                "temporal_subset": f"{start} to {end}",
                "processing_step": "Downloaded original SPEIbase NetCDF and cropped to PROFECIA period.",
            }
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        encoding = {name: {"zlib": True, "complevel": 4, "dtype": "float32"} for name in subset.data_vars}
        subset.to_netcdf(output, encoding=encoding)


def download(args: argparse.Namespace) -> None:
    payload = json.loads(args.request.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("w", encoding="utf-8") as log_handle:
        stdout = sys.stdout
        stderr = sys.stderr
        sys.stdout = log_handle
        sys.stderr = log_handle
        try:
            print("PROFECIA SPEI source adapter")
            print(f"URL: {payload['url']}")
            print(f"Scale: {payload['scale_months']:02d}")
            print(f"Target period: {payload['target_period']}")
            with tempfile.TemporaryDirectory(prefix="profecia_spei_") as tmpdir:
                source_path = Path(tmpdir) / payload["source_filename"]
                download_file(payload["url"], source_path, timeout=args.timeout, retries=args.retries)
                print(f"Downloaded source file: {source_path} ({source_path.stat().st_size} bytes)")
                write_temporal_subset(source_path, payload, args.output)
            if not args.output.exists() or args.output.stat().st_size == 0:
                raise RuntimeError(f"SPEI download did not create a non-empty file: {args.output}")
            print(f"Wrote SPEI temporal subset: {args.output} ({args.output.stat().st_size} bytes)")
        finally:
            sys.stdout = stdout
            sys.stderr = stderr


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
    dl.add_argument("--timeout", type=int, default=180)
    dl.add_argument("--retries", type=int, default=4)
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
