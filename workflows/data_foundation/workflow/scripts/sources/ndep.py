#!/usr/bin/env python3
"""PANGAEA HaNi nitrogen deposition source adapter."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import requests
import xarray as xr

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, release, source_config, variable_config


def build_payload(config_path: Path, source: str, variable: str) -> dict[str, Any]:
    config = load_config(config_path)
    release_data = release(config)
    source_data = source_config(config, source)
    variable_data = variable_config(config, source, variable)
    return {
        "source": source,
        "variable": variable,
        "provider": source_data.get("provider"),
        "source_family": source_data.get("source_family"),
        "access_mode": source_data.get("access_mode"),
        "access_protocol": source_data.get("access_protocol"),
        "doi": source_data.get("doi"),
        "landing_page": source_data.get("landing_page"),
        "target_start_year": int(variable_data.get("start_year", release_data.get("start_year", 1982))),
        "target_end_year": int(variable_data.get("end_year", release_data.get("end_year", 2022))),
        "source_start_year": int(source_data.get("source_start_year", 1860)),
        "source_end_year": int(source_data.get("source_end_year", 2019)),
        "components": source_data.get("components", {}),
        "native_units": source_data.get("native_units", "g N per cell yr-1"),
        "output_units": variable_data.get("source_units", "kg N/ha/yr"),
        "coarsen_factor": int(variable_data.get("coarsen_factor", 6)),
        "extrapolation": variable_data.get("extrapolation", {}),
        "notes": source_data.get("notes", []),
    }


def build_request(args: argparse.Namespace) -> None:
    payload = build_payload(args.config, args.source, args.variable)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        "Built ndep request for components: "
        + ", ".join(sorted(payload["components"]))
        + f" -> {args.output}"
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


def extract_first_netcdf(zip_path: Path, output_dir: Path, expected_name: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        members = [
            member
            for member in archive.namelist()
            if not member.endswith("/") and member.lower().endswith((".nc", ".nc4"))
        ]
        if expected_name:
            preferred = [member for member in members if Path(member).name == expected_name]
        else:
            preferred = []
        if preferred:
            selected = preferred[0]
        elif len(members) == 1:
            selected = members[0]
        else:
            raise RuntimeError(f"Could not choose one NetCDF from {zip_path}: {members}")
        output = output_dir / Path(selected).name
        if output.exists() and output.stat().st_size > 0:
            return output
        with archive.open(selected) as source, output.open("wb") as target:
            shutil.copyfileobj(source, target)
        return output


def years_from_time(data: xr.Dataset) -> np.ndarray:
    values = data["time"].values
    units = str(data["time"].attrs.get("units", ""))
    if "since 1850" in units:
        return (1850 + values).astype(int)
    if np.issubdtype(values.dtype, np.datetime64):
        return data.indexes["time"].year.astype(int)
    years = values.astype(int)
    if years.min() < 1000:
        years = 1850 + years
    return years


def component_data(path: Path, variable: str) -> xr.DataArray:
    dataset = xr.open_dataset(path, decode_times=False)
    if variable not in dataset:
        raise KeyError(f"Variable '{variable}' not found in {path}. Found {list(dataset.data_vars)}")
    years = years_from_time(dataset)
    dataset = dataset.assign_coords(time=("time", years))
    return dataset[variable]


def cell_area_m2(latitudes: xr.DataArray, n_lon: int) -> xr.DataArray:
    radius = 6_371_000.0
    lat_values = latitudes.values.astype("float64")
    dlat = abs(float(np.nanmedian(np.diff(lat_values))))
    dlon = 360.0 / n_lon
    dlat_rad = np.deg2rad(dlat)
    dlon_rad = np.deg2rad(dlon)
    lat_rad = np.deg2rad(lat_values)
    area_per_lat = radius * radius * dlon_rad * (
        np.sin(lat_rad + dlat_rad / 2.0) - np.sin(lat_rad - dlat_rad / 2.0)
    )
    area = np.broadcast_to(np.abs(area_per_lat)[:, None], (len(lat_values), n_lon))
    return xr.DataArray(
        area.astype("float32"),
        dims=("lat", "lon"),
        coords={"lat": latitudes, "lon": np.arange(n_lon)},
    )


def standardize_lat_lon(data: xr.DataArray) -> xr.DataArray:
    rename = {}
    if "latitude" in data.dims:
        rename["latitude"] = "lat"
    if "longitude" in data.dims:
        rename["longitude"] = "lon"
    if rename:
        data = data.rename(rename)
    if "lat" not in data.dims or "lon" not in data.dims:
        raise ValueError(f"Expected lat/lon dimensions, found {data.dims}")
    return data


def aggregate_to_half_degree(data: xr.DataArray, factor: int) -> xr.DataArray:
    if data.sizes["lat"] % factor or data.sizes["lon"] % factor:
        raise ValueError(
            f"Cannot coarsen shape {data.sizes['lat']}x{data.sizes['lon']} by factor {factor}."
        )
    return data.coarsen(lat=factor, lon=factor, boundary="trim").mean()


def extrapolate_years(data: xr.DataArray, target_end_year: int, window_start: int) -> xr.DataArray:
    last_year = int(data["year"].max())
    if last_year >= target_end_year:
        return data.sel(year=slice(None, target_end_year))
    hist = data.sel(year=slice(window_start, last_year))
    coefs = hist.polyfit(dim="year", deg=1, skipna=True)["polyfit_coefficients"]
    slope = coefs.sel(degree=1)
    intercept = coefs.sel(degree=0)
    hist_max = data.max(dim="year")
    extras = []
    for year in range(last_year + 1, target_end_year + 1):
        pred = (intercept + slope * year).clip(min=0)
        pred = xr.where(pred > 1.5 * hist_max, 1.5 * hist_max, pred)
        extras.append(pred.expand_dims(year=[year]).astype("float32"))
    return xr.concat([data] + extras, dim="year").sortby("year").drop_vars("degree", errors="ignore")


def preprocess(component_paths: dict[str, Path], payload: dict[str, Any], output: Path) -> None:
    nhx = standardize_lat_lon(component_data(component_paths["nhx"], "ndep_nhx"))
    noy = standardize_lat_lon(component_data(component_paths["noy"], "ndep_noy"))
    if not np.array_equal(nhx["time"].values, noy["time"].values):
        raise RuntimeError("NHx and NOy time axes differ.")

    start_year = payload["target_start_year"]
    target_end_year = payload["target_end_year"]
    source_end_year = min(payload["source_end_year"], int(nhx["time"].max()), int(noy["time"].max()))
    nhx = nhx.sel(time=slice(start_year, source_end_year))
    noy = noy.sel(time=slice(start_year, source_end_year))

    total_g_per_cell = nhx + noy
    area = cell_area_m2(total_g_per_cell["lat"], total_g_per_cell.sizes["lon"])
    area = area.assign_coords(lon=total_g_per_cell["lon"])
    kg_per_ha = (total_g_per_cell / area) * 10.0
    kg_per_ha = kg_per_ha.astype("float32").rename({"time": "year"})
    kg_per_ha = kg_per_ha.assign_coords(year=kg_per_ha["year"].astype(int))

    half_degree = aggregate_to_half_degree(kg_per_ha, payload["coarsen_factor"])
    extrap = payload.get("extrapolation", {})
    window_start = int(extrap.get("ols_start_year", 2015))
    half_degree = extrapolate_years(half_degree, target_end_year, window_start)
    half_degree = half_degree.rename("ndep").astype("float32")
    half_degree.attrs.update(
        {
            "long_name": "Total nitrogen deposition (NOy + NHx, dry + wet)",
            "units": payload["output_units"],
            "source": "Tian et al. (2022), PANGAEA.942069",
            "doi": payload.get("doi", "10.1594/PANGAEA.942069"),
            "processing": (
                "NHx + NOy summed; converted g N/cell/yr to kg N/ha/yr via "
                "spherical cell area; average-aggregated from native 1/12 degree "
                "to 0.5 degree; missing target years extrapolated by per-pixel "
                "OLS and clipped to [0, 1.5 x historical max]."
            ),
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    half_degree.to_dataset().to_netcdf(
        output,
        encoding={"ndep": {"zlib": True, "complevel": 4, "dtype": "float32"}},
    )


def download(args: argparse.Namespace) -> None:
    payload = json.loads(args.request.read_text(encoding="utf-8"))
    work_dir = args.output.parent / "hani_components"
    component_paths: dict[str, Path] = {}
    for name, info in payload["components"].items():
        zip_path = work_dir / f"{name}.zip"
        print(f"Downloading/checking {info['url']}")
        download_file(info["url"], zip_path)
        component_paths[name] = extract_first_netcdf(
            zip_path,
            work_dir,
            expected_name=info.get("filename"),
        )
    preprocess(component_paths, payload, args.output)
    print(f"Wrote ndep file: {args.output}")
    if not payload.get("keep_component_files", False):
        for path in component_paths.values():
            path.unlink(missing_ok=True)


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
