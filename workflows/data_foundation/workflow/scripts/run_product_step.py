#!/usr/bin/env python3
"""Small CLI bridge between Snakemake rules and product-specific helpers."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

TARGET_LAT_DESC = np.arange(89.5, -90.01, -0.5, dtype="float32")
TARGET_LON_ASC = np.arange(-180.0, 180.0, 0.5, dtype="float32")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_user_settings(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    if str(path) in {"", "."}:
        return {}
    if path.is_dir():
        return {}
    if not path.exists():
        raise FileNotFoundError(f"User settings file does not exist: {path}")
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("PyYAML is required to read user_settings.local.yml.") from exc
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def standardize_coords(ds: xr.Dataset) -> xr.Dataset:
    rename = {}
    if "valid_time" in ds.dims or "valid_time" in ds.coords:
        rename["valid_time"] = "time"
    if "lat" in ds.dims or "lat" in ds.coords:
        rename["lat"] = "latitude"
    if "lon" in ds.dims or "lon" in ds.coords:
        rename["lon"] = "longitude"
    if rename:
        ds = ds.rename(rename)
    return ds


def compression_encoding(ds: xr.Dataset, complevel: int = 4) -> dict:
    return {var: {"zlib": True, "complevel": complevel} for var in ds.data_vars}


def main_data_variable(ds: xr.Dataset, preferred_names: tuple[str, ...]) -> str:
    for name in preferred_names:
        if name in ds.data_vars:
            return name
    candidates = [name for name in ds.data_vars if name.lower() not in {"crs", "spatial_ref"}]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(
        "Could not identify a single data variable. "
        f"Preferred={preferred_names}; available={list(ds.data_vars)}"
    )


def normalize_variable_name(ds: xr.Dataset, variable: str, source_name: str | None) -> xr.Dataset:
    if variable in ds.data_vars:
        return ds
    candidates = [source_name] if source_name else []
    candidates.extend(name for name in ds.data_vars if name.lower() == variable.lower())
    for candidate in candidates:
        if candidate and candidate in ds.data_vars:
            return ds.rename({candidate: variable})
    if len(ds.data_vars) == 1:
        only_var = next(iter(ds.data_vars))
        return ds.rename({only_var: variable})
    raise ValueError(
        f"Could not identify variable '{variable}' in dataset variables {list(ds.data_vars)}."
    )


def write_monthly_05deg(args: argparse.Namespace) -> None:
    ensure_parent(args.output)
    with xr.open_dataset(args.input, engine=args.engine) as ds:
        ds = standardize_coords(ds)
        ds = normalize_variable_name(ds, args.variable, args.source_name)
        ds = ds.drop_vars(["expver", "number"], errors="ignore")

        if "longitude" not in ds.coords or "latitude" not in ds.coords:
            raise ValueError(f"{args.input} must contain latitude/longitude coordinates.")

        if float(ds.longitude.max()) > 180.0:
            lon_new = ((ds.longitude + 180) % 360) - 180
            ds = ds.assign_coords(longitude=lon_new).sortby("longitude")
        if float(ds.latitude[0]) < float(ds.latitude[-1]):
            ds = ds.sortby("latitude", ascending=False)

        ds_out = ds.interp(
            latitude=TARGET_LAT_DESC,
            longitude=TARGET_LON_ASC,
            method=args.method,
        )
        for var in ds_out.data_vars:
            if np.issubdtype(ds_out[var].dtype, np.floating):
                ds_out[var] = ds_out[var].astype("float32")
        ds_out.attrs.update(ds.attrs)
        ds_out.attrs["spatial_resolution"] = "0.5 degree"
        ds_out.attrs["temporal_resolution"] = "monthly"
        ds_out.attrs["target_grid"] = "latitude 89.5..-90.0; longitude -180.0..179.5"
        ds_out.to_netcdf(args.output, engine="netcdf4", encoding=compression_encoding(ds_out))
        ds_out.close()


def aggregate_annual(args: argparse.Namespace) -> None:
    ensure_parent(args.output)
    with xr.open_dataset(args.input, engine="netcdf4") as ds:
        ds = standardize_coords(ds)
        if "time" not in ds.coords and "time" not in ds.dims:
            raise ValueError(f"{args.input} has no time coordinate/dimension.")
        if args.aggregation == "mean":
            ds_out = ds.resample(time="YS").mean(keep_attrs=True)
        elif args.aggregation == "sum":
            ds_out = ds.resample(time="YS").sum(keep_attrs=True)
        elif args.aggregation == "min":
            ds_out = ds.resample(time="YS").min(keep_attrs=True)
        elif args.aggregation == "max":
            ds_out = ds.resample(time="YS").max(keep_attrs=True)
        else:
            raise ValueError(f"Unsupported annual aggregation: {args.aggregation}")
        for var in ds_out.data_vars:
            if np.issubdtype(ds_out[var].dtype, np.floating):
                ds_out[var] = ds_out[var].astype("float32")
        ds_out.attrs.update(ds.attrs)
        ds_out.attrs["temporal_resolution"] = "annual"
        ds_out.attrs["annual_aggregation"] = args.aggregation
        ds_out.to_netcdf(args.output, engine="netcdf4", encoding=compression_encoding(ds_out))
        ds_out.close()


def derive_vpd(args: argparse.Namespace) -> None:
    from era5_pipeline import calculate_vpd

    calculate_vpd(args.t2m, args.d2m, args.output)


def derive_wind_speed(args: argparse.Namespace) -> None:
    from era5_pipeline import calculate_wind_speed

    calculate_wind_speed(args.u10, args.v10, args.output)


def derive_swc_sub(args: argparse.Namespace) -> None:
    from era5_pipeline import calculate_swc_subsurface

    calculate_swc_subsurface(args.swvl2, args.swvl3, args.output)


def spei_download(args: argparse.Namespace) -> None:
    from spei_pipeline import download_spei

    files = download_spei(
        args.output.parent,
        scales=[args.scale],
        start_year=args.start_year,
        end_year=args.end_year,
        overwrite=args.overwrite,
    )
    scale = int(args.scale)
    expected = args.output.parent / f"spei{scale:02d}_{args.start_year}_{args.end_year}_monthly_0.5deg.nc"
    if expected != args.output and expected.exists():
        shutil.move(str(expected), args.output)
    if not args.output.exists() and files:
        shutil.move(str(files[0]), args.output)
    if not args.output.exists():
        raise RuntimeError(f"SPEI download did not create {args.output}")


def spei_prepare_monthly(args: argparse.Namespace) -> None:
    ensure_parent(args.output)
    with xr.open_dataset(args.input, engine="netcdf4") as ds:
        ds = standardize_coords(ds)

        missing_coords = [
            name for name in ("time", "latitude", "longitude")
            if name not in ds.coords and name not in ds.dims
        ]
        if missing_coords:
            raise ValueError(
                f"SPEI input {args.input} is missing coordinates/dimensions {missing_coords}. "
                f"Coordinates={list(ds.coords)}; dimensions={dict(ds.sizes)}"
            )

        source_var = main_data_variable(ds, (args.variable, "spei"))
        ds = ds[[source_var]].rename({source_var: args.variable})

        if float(ds.longitude.max()) > 180.0:
            ds = ds.assign_coords(longitude=((ds.longitude + 180) % 360) - 180)
        if float(ds.latitude[0]) > float(ds.latitude[-1]):
            ds = ds.sortby("latitude", ascending=True)
        if float(ds.longitude[0]) > float(ds.longitude[-1]):
            ds = ds.sortby("longitude", ascending=True)

        start = f"{args.start_year}-01-01"
        end = f"{args.end_year}-12-31"
        ds = ds.sel(time=slice(start, end))
        if ds.sizes.get("time", 0) == 0:
            raise ValueError(f"SPEI temporal crop {start} to {end} returned no data.")

        target_lat_asc = np.sort(TARGET_LAT_DESC)
        source_lat = ds.latitude.values.astype("float32")
        source_lon = ds.longitude.values.astype("float32")
        already_on_target_grid = (
            source_lat.shape == target_lat_asc.shape
            and source_lon.shape == TARGET_LON_ASC.shape
            and np.allclose(source_lat, target_lat_asc)
            and np.allclose(source_lon, TARGET_LON_ASC)
        )
        if already_on_target_grid:
            ds_out = ds.sortby("latitude", ascending=False)
        else:
            try:
                ds_out = ds.interp(
                    latitude=target_lat_asc,
                    longitude=TARGET_LON_ASC,
                    method=args.method,
                ).sortby("latitude", ascending=False)
            except ImportError as exc:
                raise ImportError(
                    "SPEI regridding with xarray.interp requires scipy. "
                    "Install updated requirements with: "
                    "python -m pip install -r workflows/data_foundation/requirements.txt"
                ) from exc

        for var in ds_out.data_vars:
            if np.issubdtype(ds_out[var].dtype, np.floating):
                ds_out[var] = ds_out[var].astype("float32")
        ds_out[args.variable].attrs.update(ds[args.variable].attrs)
        ds_out[args.variable].attrs["source_variable"] = source_var
        ds_out.attrs.update(ds.attrs)
        ds_out.attrs["temporal_resolution"] = "monthly"
        ds_out.attrs["spatial_resolution"] = "0.5 degree"
        ds_out.to_netcdf(args.output, engine="netcdf4", encoding=compression_encoding(ds_out))
        ds_out.close()


def lai_monthly(args: argparse.Namespace) -> None:
    from lai_pipeline import merge_monthly_files, process_monthly_lai

    if not args.input_dir.exists():
        raise FileNotFoundError(f"LAI input_dir does not exist: {args.input_dir}")
    monthly_work = args.work_dir / "monthly_parts"
    process_monthly_lai(
        args.input_dir,
        monthly_work,
        start_year=args.start_year,
        end_year=args.end_year,
        overwrite=args.overwrite,
    )
    merged = merge_monthly_files(
        monthly_work,
        args.output,
        start_year=args.start_year,
        end_year=args.end_year,
        overwrite=True,
    )
    tmp_output = args.output.with_suffix(".tmp.nc")
    with xr.open_dataset(merged, engine="netcdf4") as ds:
        rename = {name: "lai" for name in ds.data_vars if name != "lai"}
        if rename:
            ds = ds.rename(rename)
        ds.attrs["temporal_resolution"] = "monthly"
        ds.to_netcdf(tmp_output, engine="netcdf4", encoding=compression_encoding(ds))
    shutil.move(str(tmp_output), args.output)


def lai_download(args: argparse.Namespace) -> None:
    from lai_pipeline import download_geodes_lai_from_stac, download_geov2_gcm_lai

    settings = load_user_settings(args.user_settings)
    geodes_settings = settings.get("geodes", {})
    extensions = [item.strip() for item in args.extensions.split(",") if item.strip()]
    api_key = args.api_key or geodes_settings.get("api_key")
    api_key_env = args.api_key_env or geodes_settings.get("api_key_env") or "GEODES_API_KEY"
    auth_header = args.auth_header or geodes_settings.get("auth_header") or "Authorization"
    auth_scheme = args.auth_scheme
    if auth_scheme is None:
        auth_scheme = geodes_settings.get("auth_scheme", "Bearer")

    if args.method == "stac":
        files = download_geodes_lai_from_stac(
            args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            stac_url=args.stac_url,
            collection=args.stac_collection,
            api_key=api_key,
            api_key_env=api_key_env,
            auth_header=auth_header,
            auth_scheme=auth_scheme,
            overwrite=args.overwrite,
        )
    else:
        files = download_geov2_gcm_lai(
            args.output_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            url_template=args.url_template or None,
            base_url=args.base_url or None,
            version=args.version,
            extensions=extensions,
            overwrite=args.overwrite,
        )
    ensure_parent(args.marker)
    args.marker.write_text("\n".join(path.name for path in files) + "\n", encoding="utf-8")


def co2_download(args: argparse.Namespace) -> None:
    from co2_pipeline import download_carbontracker_co2

    download_carbontracker_co2(
        args.output_dir,
        start_year=args.start_year,
        end_year=args.end_year,
        overwrite=args.overwrite,
    )
    marker_files = sorted(args.output_dir.glob("CT*.molefrac_*.nc"))
    if not marker_files:
        raise RuntimeError(f"No CarbonTracker files were downloaded to {args.output_dir}")
    ensure_parent(args.marker)
    args.marker.write_text("\n".join(path.name for path in marker_files) + "\n", encoding="utf-8")


def co2_merge(args: argparse.Namespace) -> None:
    from co2_pipeline import merge_co2_monthly

    merge_co2_monthly(args.input_dir, args.output)


def co2_surface(args: argparse.Namespace) -> None:
    from co2_pipeline import extract_co2_surface

    extract_co2_surface(args.input, args.output, level=args.level)


def co2_column(args: argparse.Namespace) -> None:
    from co2_pipeline import compute_co2_column_weighted

    compute_co2_column_weighted(args.input, args.output)


def co2_regrid(args: argparse.Namespace) -> None:
    from co2_pipeline import regrid_co2_to_05deg

    regrid_co2_to_05deg(args.input, args.output)


def co2_annual(args: argparse.Namespace) -> None:
    from co2_pipeline import compute_annual_co2

    compute_annual_co2(args.input, args.output, aggregation=args.aggregation)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    p = sub.add_parser("era5-monthly")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--variable", required=True)
    p.add_argument("--source-name")
    p.add_argument("--method", default="linear")
    p.add_argument("--engine", default="netcdf4")
    p.set_defaults(func=write_monthly_05deg)

    p = sub.add_parser("annual")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--aggregation", default="mean", choices=["mean", "sum", "min", "max"])
    p.set_defaults(func=aggregate_annual)

    p = sub.add_parser("derive-vpd")
    p.add_argument("--t2m", required=True, type=Path)
    p.add_argument("--d2m", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.set_defaults(func=derive_vpd)

    p = sub.add_parser("derive-wind-speed")
    p.add_argument("--u10", required=True, type=Path)
    p.add_argument("--v10", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.set_defaults(func=derive_wind_speed)

    p = sub.add_parser("derive-swc-sub")
    p.add_argument("--swvl2", required=True, type=Path)
    p.add_argument("--swvl3", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.set_defaults(func=derive_swc_sub)

    p = sub.add_parser("spei-download")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--scale", required=True)
    p.add_argument("--start-year", required=True, type=int)
    p.add_argument("--end-year", required=True, type=int)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=spei_download)

    p = sub.add_parser("spei-monthly")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--variable", required=True)
    p.add_argument("--start-year", required=True, type=int)
    p.add_argument("--end-year", required=True, type=int)
    p.add_argument("--method", default="linear")
    p.set_defaults(func=spei_prepare_monthly)

    p = sub.add_parser("lai-monthly")
    p.add_argument("--input-dir", required=True, type=Path)
    p.add_argument("--work-dir", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--start-year", required=True, type=int)
    p.add_argument("--end-year", required=True, type=int)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=lai_monthly)

    p = sub.add_parser("lai-download")
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--marker", required=True, type=Path)
    p.add_argument("--start-year", required=True, type=int)
    p.add_argument("--end-year", required=True, type=int)
    p.add_argument("--method", default="direct", choices=["direct", "stac"])
    p.add_argument("--url-template", default="")
    p.add_argument("--base-url", default="")
    p.add_argument("--version", default="R03")
    p.add_argument("--extensions", default=".h5.gz,.h5")
    p.add_argument("--stac-url", default="https://geodes-portal.cnes.fr/api/stac")
    p.add_argument("--stac-collection", default="THEIA_POSTEL_VEGETATION_LAI")
    p.add_argument("--api-key", default="")
    p.add_argument("--api-key-env", default="")
    p.add_argument("--auth-header", default="")
    p.add_argument("--auth-scheme")
    p.add_argument("--user-settings", type=Path)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=lai_download)

    p = sub.add_parser("co2-download")
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--marker", required=True, type=Path)
    p.add_argument("--start-year", required=True, type=int)
    p.add_argument("--end-year", required=True, type=int)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=co2_download)

    p = sub.add_parser("co2-merge")
    p.add_argument("--input-dir", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.set_defaults(func=co2_merge)

    p = sub.add_parser("co2-surface")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--level", default=0, type=int)
    p.set_defaults(func=co2_surface)

    p = sub.add_parser("co2-column")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.set_defaults(func=co2_column)

    p = sub.add_parser("co2-regrid")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.set_defaults(func=co2_regrid)

    p = sub.add_parser("co2-annual")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--aggregation", default="mean")
    p.set_defaults(func=co2_annual)

    return root


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
