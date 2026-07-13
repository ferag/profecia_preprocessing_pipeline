#!/usr/bin/env python3
"""Harmonize acquired PROFECIA inputs to common analysis folders.

Outputs are organized by temporal structure under the release directory:
  monthly/  monthly dynamic NetCDFs on 0.5 degree WGS84 grid
  annual/   annual dynamic NetCDFs on 0.5 degree WGS84 grid
  static/   static 2D NetCDFs on 0.5 degree WGS84 grid
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, release_base_dir, selected_variables, source_config, variable_config

TARGET_N_LAT = 360
TARGET_N_LON = 720
TARGET_LAT = 89.5 - np.arange(TARGET_N_LAT, dtype="float64") * 0.5
TARGET_LON = -180.0 + np.arange(TARGET_N_LON, dtype="float64") * 0.5

HWSD2_VAR_MAP = {
    "SAND": "sand",
    "CLAY": "clay",
    "SILT": "silt",
    "PH_WATER": "ph",
    "ORG_CARBON": "soc",
    "TOTAL_N": "total_n",
    "BULK": "bulk",
    "CEC_SOIL": "cec",
}
HWSD2_ATTRS = {
    "sand": ("Sand content, topsoil", "%"),
    "clay": ("Clay content, topsoil", "%"),
    "silt": ("Silt content, topsoil", "%"),
    "ph": ("pH in water, topsoil", "pH"),
    "soc": ("Organic carbon, topsoil", "%"),
    "total_n": ("Total nitrogen, topsoil", "%"),
    "bulk": ("Bulk density, topsoil", "g/cm3"),
    "cec": ("CEC of soil, topsoil", "cmol/kg"),
}
HWSD2_NODATA = 65535


def target_grid() -> tuple[xr.DataArray, xr.DataArray]:
    return (
        xr.DataArray(TARGET_LAT, dims=("latitude",), name="latitude"),
        xr.DataArray(TARGET_LON, dims=("longitude",), name="longitude"),
    )


def find_name(candidates: list[str], names: set[str]) -> str | None:
    lowered = {name.lower(): name for name in names}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def normalize_lon(dataset: xr.Dataset, lon_name: str) -> xr.Dataset:
    lon = dataset[lon_name]
    if float(lon.max()) > 180.0:
        dataset = dataset.assign_coords({lon_name: (((lon + 180.0) % 360.0) - 180.0)})
        dataset = dataset.sortby(lon_name)
    return dataset


def open_standardized(path: Path) -> xr.Dataset:
    dataset = xr.open_dataset(path)
    names = set(dataset.coords) | set(dataset.dims)
    lat_name = find_name(["latitude", "lat", "y"], names)
    lon_name = find_name(["longitude", "lon", "x"], names)
    if not lat_name or not lon_name:
        dataset.close()
        raise RuntimeError(f"Could not find latitude/longitude coordinates in {path}")

    rename: dict[str, str] = {}
    if lat_name != "latitude":
        rename[lat_name] = "latitude"
    if lon_name != "longitude":
        rename[lon_name] = "longitude"
    if rename:
        dataset = dataset.rename(rename)
    dataset = normalize_lon(dataset, "longitude")
    return dataset.sortby("latitude", ascending=False).sortby("longitude")


def interp_to_target(dataset: xr.Dataset) -> xr.Dataset:
    lat, lon = target_grid()
    return dataset.interp(latitude=lat, longitude=lon, method="linear")


def data_var(dataset: xr.Dataset, preferred: str) -> str:
    if preferred in dataset.data_vars:
        return preferred
    if len(dataset.data_vars) == 1:
        return next(iter(dataset.data_vars))
    raise KeyError(f"Could not find variable {preferred}; available={list(dataset.data_vars)}")


def write_canonical_reference(canonical_path: Path, variable: str, output: Path, attrs: dict[str, Any] | None = None) -> None:
    if not canonical_path.exists():
        raise RuntimeError(f"Configured canonical reference does not exist: {canonical_path}")
    with open_standardized(canonical_path) as dataset:
        source_var = data_var(dataset, variable)
        out = dataset[[source_var]].rename({source_var: variable}) if source_var != variable else dataset[[source_var]]
        if attrs:
            out[variable].attrs.update(attrs)
        out.attrs.update(
            {
                "profecia_harmonized": "true",
                "canonical_reference_file": str(canonical_path),
                "canonical_reference_policy": "Copied from /srv/read_only_data final_datasets because legacy preprocessing is authoritative for this product.",
            }
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        encoding = {variable: {"zlib": True, "complevel": 4, "dtype": "float32"}}
        out.to_netcdf(output, encoding=encoding)
    print(f"Wrote canonical-reference NetCDF: {output}")


def drop_provider_auxiliary_coords(dataset: xr.Dataset) -> xr.Dataset:
    """Drop provider bookkeeping coordinates that are not analysis axes."""
    return dataset.drop_vars(["expver"], errors="ignore")


def harmonize_netcdf(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    var_data = variable_config(config, args.source, args.variable)
    if var_data.get("canonical_reference_path"):
        attrs = {k: v for k, v in var_data.items() if k in {"long_name", "source_units", "units"}}
        if var_data.get("source_units") and not attrs.get("units"):
            attrs["units"] = var_data["source_units"]
        write_canonical_reference(Path(var_data["canonical_reference_path"]), args.variable, args.output, attrs)
        return
    if args.input is None:
        raise ValueError("--input is required when canonical_reference_path is not configured.")

    with open_standardized(args.input) as dataset:
        variable = data_var(dataset, args.variable)
        keep = dataset[[variable]]
        keep = drop_provider_auxiliary_coords(keep)
        selected_level = None
        if "level" in keep[variable].dims and not var_data.get("preserve_vertical_levels", False):
            selected_level = keep["level"].values[0].item()
            keep = keep.isel(level=0).drop_vars("level", errors="ignore")
        time_name = find_name(["time", "valid_time", "year"], set(keep.coords) | set(keep.dims))
        if time_name == "valid_time":
            keep = keep.rename({"valid_time": "time"})
        harmonized = interp_to_target(keep)
        if selected_level is not None:
            harmonized[variable].attrs["selected_source_level"] = selected_level
        harmonized[variable].attrs.update({k: v for k, v in var_data.items() if k in {"long_name", "source_units", "units"}})
        if var_data.get("source_units") and not harmonized[variable].attrs.get("units"):
            harmonized[variable].attrs["units"] = var_data["source_units"]
        harmonized.attrs.update(
            {
                "profecia_harmonized": "true",
                "target_grid": "global_0.5_degree_original_profecia",
                "source_file": str(args.input),
                "source": args.source,
                "variable": args.variable,
                "temporal_folder": args.frequency,
            }
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        encoding = {name: {"zlib": True, "complevel": 4, "dtype": "float32"} for name in harmonized.data_vars}
        harmonized.to_netcdf(args.output, encoding=encoding)
    print(f"Wrote harmonized {args.frequency} NetCDF: {args.output}")


def extract_member(zip_path: Path, member_name: str, output_dir: Path) -> Path:
    output = output_dir / member_name
    if output.exists() and output.stat().st_size > 0:
        return output
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        with archive.open(member_name) as source, output.open("wb") as target:
            while True:
                chunk = source.read(1024 * 1024 * 32)
                if not chunk:
                    break
                target.write(chunk)
    return output


def find_hwsd2_layers_csv(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend(
        [
            Path("resources/data_releases/profecia_inputs_full_auto_v0/raw/hwsd2/HWSD2_LAYERS.csv"),
            Path("/srv/read_only_data/NANA/soil/RAW/HWSD2_soil/RAW/HWSD2_LAYERS.csv"),
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    raise RuntimeError(
        "HWSD2_LAYERS.csv was not found. Export it from HWSD2.mdb or provide "
        "--layers-csv."
    )


def weighted_mean(group: pd.DataFrame, column: str) -> float:
    weights = group["SHARE"].fillna(1)
    values = group[column]
    valid = values.notna() & (weights > 0) & (values >= 0)
    if int(valid.sum()) == 0:
        return np.nan
    return float((values[valid] * weights[valid]).sum() / weights[valid].sum())


def build_hwsd2_lookup(layers_csv: Path, variables: list[str]) -> dict[str, np.ndarray]:
    print(f"Reading HWSD2 layers: {layers_csv}")
    df = pd.read_csv(layers_csv, low_memory=False)
    shallowest = df.groupby("HWSD2_SMU_ID")["TOPDEP"].transform("min")
    df_top = df[df["TOPDEP"] == shallowest].copy()
    max_smu = int(df_top["HWSD2_SMU_ID"].max()) + 1
    wanted_csv_cols = [csv_col for csv_col, name in HWSD2_VAR_MAP.items() if name in variables]
    lookup = {csv_col: np.full(max_smu, np.nan, dtype=np.float32) for csv_col in wanted_csv_cols}
    for smu_id, group in df_top.groupby("HWSD2_SMU_ID"):
        idx = int(smu_id)
        for csv_col in wanted_csv_cols:
            if csv_col in group.columns:
                lookup[csv_col][idx] = weighted_mean(group, csv_col)
    return lookup


def aggregate_lookup_to_half_degree(smu: np.memmap, lookup: np.ndarray) -> np.ndarray:
    output = np.full((TARGET_N_LAT, TARGET_N_LON), np.nan, dtype=np.float32)
    for row in range(TARGET_N_LAT):
        block = np.asarray(smu[row * 60 : (row + 1) * 60, :])
        safe = np.where((block != HWSD2_NODATA) & (block < len(lookup)), block, 0)
        values = lookup[safe].reshape(60, TARGET_N_LON, 60)
        with np.errstate(invalid="ignore"):
            output[row, :] = np.nanmean(values, axis=(0, 2)).astype(np.float32)
        if row % 45 == 0:
            print(f"  aggregated latitude band {row + 1}/{TARGET_N_LAT}")
        del safe, values
    return output


def harmonize_hwsd2(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    source_data = source_config(config, "hwsd2")
    selected = [item.variable for item in selected_variables(config) if item.source == "hwsd2"]
    variables = [name for name in HWSD2_ATTRS if name in selected]
    if not variables:
        raise RuntimeError("No selected hwsd2 variables found in config.")

    canonical_dir = source_data.get("canonical_reference_dir")
    canonical_template = source_data.get("canonical_reference_template", "{variable}_1982_2022_monthly_0.5deg.nc")
    if canonical_dir:
        data_vars: dict[str, xr.DataArray] = {}
        for var_name in variables:
            path = Path(canonical_dir) / canonical_template.format(variable=var_name)
            if not path.exists():
                raise RuntimeError(f"Missing HWSD2 canonical reference for {var_name}: {path}")
            with open_standardized(path) as ref:
                ref_var = data_var(ref, var_name)
                da = ref[ref_var]
                if "time" in da.dims:
                    da = da.isel(time=0, drop=True)
                data_vars[var_name] = da.astype("float32").rename(var_name).load()

        dataset = xr.Dataset(data_vars)
        dataset.attrs.update(
            {
                "profecia_harmonized": "true",
                "target_grid": "global_0.5_degree_original_profecia",
                "source": "hwsd2",
                "canonical_reference_dir": str(canonical_dir),
                "canonical_reference_policy": "Static soil fields copied from the first timestep of canonical final_datasets monthly soil products.",
            }
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        encoding = {name: {"zlib": True, "complevel": 4, "dtype": "float32"} for name in dataset.data_vars}
        dataset.to_netcdf(args.output, encoding=encoding)
        print(f"Wrote canonical-reference static HWSD2 NetCDF: {args.output}")
        return

    base_dir = release_base_dir(config)
    raw_dir = base_dir / "raw" / "hwsd2"
    raster_zip = raw_dir / "HWSD2_RASTER.zip"
    if not raster_zip.exists():
        raise RuntimeError(f"Missing HWSD2 raster zip: {raster_zip}")

    work_dir = base_dir / "work" / "hwsd2"
    bil = extract_member(raster_zip, "HWSD2.bil", work_dir)
    layers_csv = find_hwsd2_layers_csv(args.layers_csv)
    lookup = build_hwsd2_lookup(layers_csv, variables)
    smu = np.memmap(bil, dtype="<u2", mode="r", shape=(21600, 43200))

    data_vars: dict[str, xr.DataArray] = {}
    soil_arrays: dict[str, np.ndarray] = {}
    for csv_col, var_name in HWSD2_VAR_MAP.items():
        if var_name not in variables:
            continue
        print(f"Processing HWSD2 {var_name}")
        arr = aggregate_lookup_to_half_degree(smu, lookup[csv_col])
        soil_arrays[var_name] = arr
        gc.collect()

    if all(name in soil_arrays for name in ("sand", "silt", "clay")):
        total = soil_arrays["sand"] + soil_arrays["silt"] + soil_arrays["clay"]
        mask = total > 0
        for name in ("sand", "silt", "clay"):
            soil_arrays[name] = np.where(mask, soil_arrays[name] / total * 100.0, np.nan).astype(np.float32)

    for var_name, arr in soil_arrays.items():
        long_name, units = HWSD2_ATTRS[var_name]
        data_vars[var_name] = xr.DataArray(
            arr,
            dims=("latitude", "longitude"),
            coords={"latitude": TARGET_LAT, "longitude": TARGET_LON},
            attrs={
                "long_name": long_name,
                "units": units,
                "source": "HWSD2 topsoil SHARE-weighted mean, aggregated to 0.5 degree",
            },
        )

    dataset = xr.Dataset(data_vars)
    dataset.attrs.update(
        {
            "profecia_harmonized": "true",
            "target_grid": "global_0.5_degree_original_profecia",
            "source": "hwsd2",
            "layers_csv": str(layers_csv),
            "raster_file": str(bil),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoding = {name: {"zlib": True, "complevel": 4, "dtype": "float32"} for name in dataset.data_vars}
    dataset.to_netcdf(args.output, encoding=encoding)
    print(f"Wrote harmonized static HWSD2 NetCDF: {args.output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    nc = sub.add_parser("netcdf")
    nc.add_argument("--config", required=True, type=Path)
    nc.add_argument("--source", required=True)
    nc.add_argument("--variable", required=True)
    nc.add_argument("--input", default=None, type=Path)
    nc.add_argument("--output", required=True, type=Path)
    nc.add_argument("--frequency", required=True, choices=["monthly", "annual", "static"])
    nc.set_defaults(func=harmonize_netcdf)

    soil = sub.add_parser("hwsd2-static")
    soil.add_argument("--config", required=True, type=Path)
    soil.add_argument("--output", required=True, type=Path)
    soil.add_argument("--layers-csv", default="")
    soil.set_defaults(func=harmonize_hwsd2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
