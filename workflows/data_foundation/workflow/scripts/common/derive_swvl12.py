#!/usr/bin/env python3
"""Create the PROFECIA combined swvl1-2 soil-water product."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import xarray as xr

VAR_SWVL1 = "swvl1"
VAR_SWVL2 = "swvl2"
VAR_OUT = "swvl1-2"
FORMULA = "swvl1-2 = (swvl1 * 7 + swvl2 * 21) / 28"
DESCRIPTION = (
    "Weighted combination of swvl1 and swvl2. swvl1 represents the first 7 cm "
    "and swvl2 the following 21 cm, yielding a weighted mean for the 0-28 cm layer."
)


def comparable_coords(a: xr.DataArray, b: xr.DataArray) -> list[str]:
    return [
        coord
        for coord in ["time", "latitude", "longitude", "lat", "lon"]
        if coord in a.coords and coord in b.coords
    ]


def combine(swvl1_path: Path, swvl2_path: Path, output_path: Path) -> None:
    with xr.open_dataset(swvl1_path) as ds1, xr.open_dataset(swvl2_path) as ds2:
        if VAR_SWVL1 not in ds1.data_vars:
            raise ValueError(f"Variable {VAR_SWVL1!r} not found in {swvl1_path}: {list(ds1.data_vars)}")
        if VAR_SWVL2 not in ds2.data_vars:
            raise ValueError(f"Variable {VAR_SWVL2!r} not found in {swvl2_path}: {list(ds2.data_vars)}")

        da1 = ds1[VAR_SWVL1]
        da2 = ds2[VAR_SWVL2]
        coords = comparable_coords(da1, da2)
        same_dims = da1.dims == da2.dims
        same_shape = da1.shape == da2.shape
        same_coords = all(np.array_equal(da1[coord].values, da2[coord].values) for coord in coords)

        if same_dims and same_shape and same_coords:
            da1_aligned, da2_aligned = xr.align(da1, da2, join="exact")
            adaptation = "no spatial/temporal adaptation needed; coordinates matched exactly"
        else:
            da1_aligned = da1
            da2_aligned = da2.interp_like(da1)
            adaptation = "swvl2 interpolated to swvl1 grid/time coordinates using xarray.interp_like"

        combined = ((da1_aligned * 7) + (da2_aligned * 21)) / 28
        combined = combined.rename(VAR_OUT).astype("float32")
        combined.attrs.update(da1.attrs)
        combined.attrs.update(
            {
                "long_name": "Volumetric soil water layer 1-2 weighted mean",
                "description": DESCRIPTION,
                "formula": FORMULA,
                "weights": "swvl1: 7/28; swvl2: 21/28",
                "layer_depth_cm": "0-28",
                "source_variables": "swvl1, swvl2",
            }
        )

        out = combined.to_dataset(name=VAR_OUT)
        out.attrs.update(ds1.attrs)
        out.attrs.update(
            {
                "profecia_derived": "true",
                "derived_variable": VAR_OUT,
                "source_swvl1": str(swvl1_path),
                "source_swvl2": str(swvl2_path),
                "formula": FORMULA,
                "derivation_description": DESCRIPTION,
                "adaptation": adaptation,
                "notebook_reference": "/srv/volumes/ferag/profecia/notebooks/check_d_swvl_combined.ipynb",
            }
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_netcdf(
            output_path,
            encoding={VAR_OUT: {"zlib": True, "complevel": 4, "dtype": "float32"}},
        )
    print(f"Wrote derived {VAR_OUT} NetCDF: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--swvl1", required=True, type=Path)
    parser.add_argument("--swvl2", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    combine(args.swvl1, args.swvl2, args.output)


if __name__ == "__main__":
    main()
