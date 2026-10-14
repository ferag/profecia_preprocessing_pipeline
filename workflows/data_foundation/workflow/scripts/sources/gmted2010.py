#!/usr/bin/env python3
"""GMTED2010 mean/30-arc-second public ArcGrid acquisition and reprojection."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

import numpy as np
import requests
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.config_loader import load_config

GRID = "mn30_grd"
URL = "https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/topo/downloads/GMTED/Grid_ZipFiles/mn30_grd.zip"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_definition(config):
    return {"provider": "USGS / NGA", "source_family": "GMTED2010 mean elevation",
            "version": "2010", "access_mode": "http", "access_protocol": "direct_https",
            "adapter": "gmted2010", "requires_authentication": False,
            "doi": "10.5066/F7J38R2N", "report_doi": "10.3133/ofr20111073",
            "landing_page": "https://topotools.cr.usgs.gov/gmted_viewer/gmted2010_global_grids.php",
            "product_id": GRID, "statistic": "mean", "resolution_arc_seconds": 30,
            "data_files": {"dem": {"url": URL, "filename": "mn30_grd.zip"}},
            "variables": {"elevation": {"long_name": "Mean elevation", "source_units": "m", "units": "m",
                              "data_structure": "2D static", "dimensionality": "2D static",
                              "native_temporal_resolution": "static", "role": "moderator",
                              "release_output_path": "monthly/elevation_1982_2022_monthly_0.5deg.nc"}},
            "processing": {"resampling": "bilinear", "grid": copy.deepcopy(config["release"]["target_grid"]),
                           "selection_basis": "Historical preprocess_soil_0p5.py uses mn30_grd and resampling=1. Numeric equivalence not yet verified."}}


def build_file_list(args):
    source = load_config(args.config)["sources"][args.source]
    if (source.get("product_id"), source.get("statistic"), source.get("resolution_arc_seconds")) != (GRID, "mean", 30):
        raise ValueError("This adapter supports only the explicitly documented mean/30-arc-second product")
    payload = {"source": args.source, "product_id": GRID, "statistic": "mean", "resolution_arc_seconds": 30,
               "doi": source["doi"], "files": source["data_files"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")


def download(args):
    payload = json.loads(args.file_list.read_text())
    entry = payload["files"]["dem"]
    if entry["filename"] != "mn30_grd.zip" or payload["product_id"] != GRID:
        raise ValueError("Unexpected GMTED2010 product")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / entry["filename"]
    temporary = target.with_suffix(".zip.part")
    expected = entry.get("sha256")
    if not target.exists():
        with requests.get(entry["url"], stream=True, timeout=(30, 120)) as response:
            response.raise_for_status()
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                    if chunk:
                        stream.write(chunk)
        if not zipfile.is_zipfile(temporary):
            raise RuntimeError("GMTED2010 response is not a ZIP; partial file retained for inspection")
        if expected and digest(temporary) != expected:
            raise RuntimeError("Provider archive checksum differs from configured expected SHA-256")
        temporary.replace(target)
    checksum = digest(target)
    if expected and checksum != expected:
        raise RuntimeError("Cached provider archive checksum mismatch")
    with zipfile.ZipFile(target) as zipped:
        broken = zipped.testzip()
        if broken:
            raise RuntimeError(f"Corrupt GMTED2010 member: {broken}")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"status": "OK", "source": "gmted2010", "product_id": GRID,
                                      "url": entry["url"], "path": str(target), "sha256": checksum,
                                      "size_bytes": target.stat().st_size,
                                      "expected_checksum_available": bool(expected)}, indent=2) + "\n")


def extract_grid(archive, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            name = PurePosixPath(item.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in item.filename or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError(f"Unsafe ZIP member: {item.filename}")
            (directory / Path(*name.parts)).resolve().relative_to(directory.resolve())
        zipped.extractall(directory)
    grids = [path.parent for path in directory.rglob("hdr.adf") if path.parent.name == GRID]
    if len(grids) != 1:
        raise RuntimeError(f"Expected exactly one {GRID}/hdr.adf grid, found {len(grids)}")
    return grids[0]


def resample_elevation(path, latitudes=None, longitudes=None):
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject

    lat = np.asarray(latitudes if latitudes is not None else 89.5 - np.arange(360) * 0.5, dtype="float64")
    lon = np.asarray(longitudes if longitudes is not None else -180.0 + np.arange(720) * 0.5, dtype="float64")
    if lat.ndim != 1 or lon.ndim != 1 or len(lat) < 2 or len(lon) < 2:
        raise ValueError("Target grid must have two or more centers per axis")
    dy, dx = lat[0] - lat[1], lon[1] - lon[0]
    if dy <= 0 or dx <= 0 or not np.allclose(np.diff(lat), -dy) or not np.allclose(np.diff(lon), dx):
        raise ValueError("Target must be regular, latitude descending and longitude ascending")
    destination = np.full((len(lat), len(lon)), np.nan, dtype="float32")
    with rasterio.open(path) as source:
        if source.count != 1:
            raise ValueError("Expected a single-band elevation grid")
        crs = source.crs or rasterio.crs.CRS.from_epsg(4326)
        reproject(source=rasterio.band(source, 1), destination=destination,
                  src_transform=source.transform, src_crs=crs, src_nodata=source.nodata,
                  dst_transform=from_origin(lon[0] - dx / 2, lat[0] + dy / 2, dx, dy),
                  dst_crs="EPSG:4326", dst_nodata=np.nan, resampling=Resampling.bilinear,
                  num_threads=1, init_dest_nodata=True, warp_mem_limit=256)
        metadata = {"source_crs": str(crs), "source_shape": [source.height, source.width],
                    "source_nodata": source.nodata, "resampling": "bilinear",
                    "target_center_ranges": {"latitude": [float(lat[0]), float(lat[-1])],
                                             "longitude": [float(lon[0]), float(lon[-1])]},
                    "negative_elevation_policy": "Preserve valid negative elevations; only source NoData is masked"}
    result = xr.Dataset({"elevation": (("latitude", "longitude"), destination,
                          {"long_name": "Mean elevation", "units": "m", "source": "USGS GMTED2010 mn30_grd, mean 30 arc-seconds",
                           "resampling": "bilinear"})}, coords={"latitude": lat, "longitude": lon})
    result.latitude.attrs.update(standard_name="latitude", units="degrees_north")
    result.longitude.attrs.update(standard_name="longitude", units="degrees_east")
    return result, metadata


def prepare(args):
    grid = extract_grid(args.archive, args.output.parent / "extracted")
    dataset, metadata = resample_elevation(grid)
    if not np.isfinite(dataset.elevation.values).any():
        raise RuntimeError("Reprojection produced no finite elevation values")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_netcdf(args.output, encoding={"elevation": {"zlib": True, "complevel": 6, "dtype": "float32"}})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"status": "OK", "source": "gmted2010", "variable": "elevation",
                                      "input_archive": str(args.archive), "archive_sha256": digest(args.archive),
                                      "output": str(args.output), "output_sha256": digest(args.output),
                                      "numeric_equivalence_to_canonical": "NOT_TESTED", **metadata}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("build-file-list")
    command.add_argument("--config", type=Path, required=True)
    command.add_argument("--source", default="gmted2010")
    command.add_argument("--output", type=Path, required=True)
    command.set_defaults(function=build_file_list)
    command = sub.add_parser("download")
    command.add_argument("--config", type=Path, required=True)
    command.add_argument("--file-list", type=Path, required=True)
    command.add_argument("--output-dir", type=Path, required=True)
    command.add_argument("--report", type=Path, required=True)
    command.set_defaults(function=download)
    command = sub.add_parser("prepare")
    command.add_argument("--archive", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--report", type=Path, required=True)
    command.set_defaults(function=prepare)
    args = parser.parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
