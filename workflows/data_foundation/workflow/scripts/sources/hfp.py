#!/usr/bin/env python3
"""Human Footprint source adapter for Mu et al. Figshare + Hengl Zenodo."""

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


def require_rasterio():
    try:
        import rasterio
        from rasterio.transform import from_origin
        from rasterio.warp import Resampling, reproject
    except ImportError as exc:
        raise RuntimeError(
            "HFP preprocessing requires rasterio. Install it in the runtime "
            "environment, e.g. pip install rasterio or use the xarray env."
        ) from exc
    return rasterio, from_origin, Resampling, reproject


def figshare_files(api_url: str) -> dict[int, dict[str, Any]]:
    response = requests.get(api_url, timeout=60)
    response.raise_for_status()
    data = response.json()
    files: dict[int, dict[str, Any]] = {}
    for item in data.get("files", []):
        name = item.get("name", "")
        if not name.startswith("hfp") or not name.endswith(".zip"):
            continue
        try:
            year = int(name.replace("hfp", "").replace(".zip", ""))
        except ValueError:
            continue
        files[year] = {
            "name": name,
            "size": item.get("size"),
            "download_url": item.get("download_url"),
        }
    return files


def build_payload(config_path: Path, source: str, variable: str) -> dict[str, Any]:
    config = load_config(config_path)
    release_data = release(config)
    source_data = source_config(config, source)
    variable_data = variable_config(config, source, variable)
    target_start = int(variable_data.get("start_year", release_data.get("start_year", 1982)))
    target_end = int(variable_data.get("end_year", 2022))
    mu = source_data["mu_figshare"]
    hengl = source_data["hengl_zenodo"]
    observed = figshare_files(mu["api_url"])
    observed_years = sorted(year for year in observed if target_start <= year <= target_end)
    verified_start = int(mu.get("verified_start_year", 2000))
    verified_end = int(mu.get("verified_end_year", 2018))
    verified_missing = [
        year
        for year in range(verified_start, verified_end + 1)
        if year not in observed
    ]
    target_missing_observed = [
        year
        for year in range(max(verified_start, target_start), target_end + 1)
        if year not in observed
    ]
    hengl_years = [
        year
        for year in range(int(hengl["start_year"]), int(hengl["end_year"]) + 1)
        if target_start <= year <= target_end
    ]
    return {
        "source": source,
        "variable": variable,
        "provider": source_data.get("provider"),
        "source_family": source_data.get("source_family"),
        "access_mode": source_data.get("access_mode"),
        "access_protocol": source_data.get("access_protocol"),
        "target_start_year": target_start,
        "target_end_year": target_end,
        "mu_figshare": {
            **mu,
            "available_years": observed_years,
            "verified_missing_years": verified_missing,
            "target_missing_observed_years": target_missing_observed,
            "files": {str(year): observed[year] for year in observed_years},
        },
        "hengl_zenodo": {
            **hengl,
            "years": hengl_years,
        },
        "target_grid": source_data.get("target_grid", {}),
        "output_units": variable_data.get("source_units", "index"),
        "notes": source_data.get("notes", []),
    }


def build_request(args: argparse.Namespace) -> None:
    payload = build_payload(args.config, args.source, args.variable)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    available = payload["mu_figshare"]["available_years"]
    missing = payload["mu_figshare"]["target_missing_observed_years"]
    print(
        f"Built HFP request. Figshare observed years: {available[0] if available else 'none'}"
        f"-{available[-1] if available else 'none'} ({len(available)} files)."
    )
    if missing:
        print(f"Observed Mu/Figshare missing target years: {missing}")


def download_file(url: str, output: Path) -> None:
    if output.exists() and output.stat().st_size > 0:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    with requests.get(url, stream=True, timeout=180) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    tmp.replace(output)


def extract_tif(zip_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        members = [
            member
            for member in archive.namelist()
            if not member.endswith("/") and member.lower().endswith((".tif", ".tiff"))
        ]
        if len(members) != 1:
            raise RuntimeError(f"Expected one GeoTIFF in {zip_path}, found {members}")
        output = output_dir / Path(members[0]).name
        if output.exists() and output.stat().st_size > 0:
            return output
        with archive.open(members[0]) as source, output.open("wb") as target:
            shutil.copyfileobj(source, target)
        return output


def target_grid(payload: dict[str, Any]) -> tuple[tuple[int, int], Any, str, np.ndarray, np.ndarray]:
    _, from_origin, _, _ = require_rasterio()
    grid = payload.get("target_grid") or {}
    resolution = float(grid.get("resolution_degrees", 0.5))
    west = float(grid.get("west", -180.0))
    north = float(grid.get("north", 90.0))
    n_lon = int(grid.get("n_lon", round(360.0 / resolution)))
    n_lat = int(grid.get("n_lat", round(180.0 / resolution)))
    transform = from_origin(west, north, resolution, resolution)
    lon = west + resolution / 2 + np.arange(n_lon, dtype="float64") * resolution
    lat = north - resolution / 2 - np.arange(n_lat, dtype="float64") * resolution
    return (n_lat, n_lon), transform, "EPSG:4326", lat, lon


def read_resample(tif_path: Path, payload: dict[str, Any]) -> np.ndarray:
    rasterio, _, Resampling, reproject = require_rasterio()
    shape, dst_transform, dst_crs, _, _ = target_grid(payload)
    with rasterio.open(tif_path) as src:
        arr = np.empty(shape, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=arr,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
            num_threads=2,
        )
    arr[arr < 0] = np.nan
    return arr


def hengl_url(payload: dict[str, Any], year: int) -> str:
    hengl = payload["hengl_zenodo"]
    if year == 2000 and hengl.get("year_2000_url"):
        return hengl["year_2000_url"]
    return hengl["url_pattern"].format(year=year)


def download(args: argparse.Namespace) -> None:
    payload = json.loads(args.request.read_text(encoding="utf-8"))
    work_dir = args.output.parent / "hfp_source_files"
    raw_arrays: dict[int, np.ndarray] = {}
    source_tags: dict[int, str] = {}

    for year in payload["hengl_zenodo"]["years"]:
        tif = work_dir / f"hfootprint_{year}_1km.tif"
        print(f"Downloading/checking Hengl {year}")
        download_file(hengl_url(payload, year), tif)
        raw_arrays[year] = read_resample(tif, payload)
        source_tags[year] = "hengl_zenodo"

    for year in payload["mu_figshare"]["available_years"]:
        if year < payload["target_start_year"] or year > payload["target_end_year"]:
            continue
        file_info = payload["mu_figshare"]["files"][str(year)]
        zip_path = work_dir / file_info["name"]
        print(f"Downloading/checking Mu/Figshare {year}")
        download_file(file_info["download_url"], zip_path)
        tif = extract_tif(zip_path, work_dir)
        raw_arrays[year] = read_resample(tif, payload)
        source_tags[year] = "mu_figshare"

    if 2000 in raw_arrays and 1999 in raw_arrays:
        delta = raw_arrays[2000] - raw_arrays[1999]
        for year in range(payload["target_start_year"], 2000):
            if year in raw_arrays:
                raw_arrays[year] = raw_arrays[year] + delta

    expected = list(range(payload["target_start_year"], payload["target_end_year"] + 1))
    missing = [year for year in expected if year not in raw_arrays]
    if missing:
        raise RuntimeError(f"Missing HFP years after download/preprocess: {missing}")

    _, _, _, lat, lon = target_grid(payload)
    years = np.array(expected, dtype=np.int32)
    stack = np.stack([raw_arrays[year] for year in expected], axis=0).astype("float32")
    data = xr.DataArray(
        stack,
        dims=["year", "latitude", "longitude"],
        coords={"year": years, "latitude": lat, "longitude": lon},
        attrs={
            "long_name": "Annual Human Footprint Index",
            "units": payload["output_units"],
            "source": "Mu et al. 2022 Figshare 16571064 + Hengl 2022 Zenodo 6636562",
            "mu_figshare_article": payload["mu_figshare"].get("article_url"),
            "mu_figshare_doi": payload["mu_figshare"].get("doi"),
            "hengl_zenodo_doi": payload["hengl_zenodo"].get("doi"),
            "bias_correction": "Additive offset delta=observed(2000)-extrapolated(1999) applied to 1982-1999.",
            "resampling": "Bilinear reprojection/resampling to 0.5 degree WGS84.",
        },
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    data.to_dataset(name=args.variable).to_netcdf(
        args.output,
        encoding={args.variable: {"zlib": True, "complevel": 4, "dtype": "float32"}},
    )
    print(f"Wrote HFP file: {args.output}")


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
