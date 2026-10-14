#!/usr/bin/env python3
"""
preprocess_grazing_annual.py  —  Annual TLU time series from LivestockMap
==========================================================================
Replaces the old 4-snapshot extraction (1961/1981/2001/2021 → tlu_2001 +
tlu_change). The original LivestockMap archive actually has annual TIFs
for 1961-2021 — 61 years per species — but the previous preprocess only
read 4 years.

This script:
  1. Reads annual TIFs for the 5 grazer species (Cattl, Buffa, Horse,
     Sheep, Goats) for every year 1982-2021
  2. Reprojects each TIF to the 0.5° LAI grid (Resampling.average)
  3. Applies the FAO TLU formula:
       TLU/km² = 1.0·cattle + 1.0·buffalo + 0.8·horse + 0.1·sheep + 0.1·goats
  4. Saves an annual TLU NetCDF (year=40, lat=360, lon=720)
  5. Pads 2022 = 2021 (the upstream dataset ends in 2021)

Output:
  /home/jovyan/data/Grazing/tlu_1982_2022_annual_0.5deg.nc
"""

import os

# ── PROJ database fix (MUST run before importing rasterio/rioxarray) ──
# The conda install has /opt/conda/share/proj/proj.db at LAYOUT.MINOR=2 but
# rasterio/PROJ 9.x expects ≥6. Redirect PROJ lookups to pyproj's bundled
# database which has the correct version.
try:
    import pyproj
    _pyproj_data = pyproj.datadir.get_data_dir()
    os.environ["PROJ_DATA"] = _pyproj_data
    os.environ["PROJ_LIB"]  = _pyproj_data
    print(f"  [PROJ fix] using pyproj database at {_pyproj_data}")
except ImportError:
    print("  [PROJ fix] pyproj not available — falling back to system PROJ")

import glob
import numpy as np
import xarray as xr
import rioxarray as rxr
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.crs import CRS

# ─── Config ─────────────────────────────────────────────────────────────────
# Adjust IN_DIR depending on environment
CANDIDATES_IN = [
    "/home/jovyan/data/Grazing/LivestockMap",                # JupyterHub
    "/home/jovyan/read_only_data/NANA/human/Grazing/LivestockMap",
    "D:/2_study/Paper4/data/human/Grazing/LivestockMap",     # Local Windows
]
IN_DIR = next((p for p in CANDIDATES_IN if os.path.isdir(p)), None)
if IN_DIR is None:
    raise FileNotFoundError(
        "LivestockMap TIF directory not found. Tried:\n  " +
        "\n  ".join(CANDIDATES_IN))

CANDIDATES_OUT = [
    "/home/jovyan/data/Grazing",                             # JupyterHub
    "D:/2_study/Paper4/data/human/Grazing",                  # Local Windows
]
OUT_DIR = next((p for p in CANDIDATES_OUT if os.path.isdir(p)), CANDIDATES_OUT[0])
os.makedirs(OUT_DIR, exist_ok=True)
OUT_NC = os.path.join(OUT_DIR, "tlu_1982_2022_annual_0.5deg.nc")

YEARS = list(range(1982, 2023))            # 1982..2022 (41 years)
TLU_WEIGHTS = {                            # FAO standard
    "Cattl": 1.0,
    "Buffa": 1.0,
    "Horse": 0.8,
    "Sheep": 0.1,
    "Goats": 0.1,
}

# Reference 0.5° grid — matches LAI / mask (N→S, W→E)
REF_LAT = np.linspace( 89.5, -89.5, 360, dtype=np.float32)
REF_LON = np.linspace(-179.5, 179.5, 720, dtype=np.float32)

TARGET_SHAPE = (360, 720)

# Target 0.5° bin edges (ascending for np.histogram2d)
LAT_EDGES = np.linspace(-90.0, 90.0,  361)      # 360 cells
LON_EDGES = np.linspace(-180.0, 180.0, 721)      # 720 cells


# ─── Helpers ────────────────────────────────────────────────────────────────
def _reproject_to_05(tif_path):
    """Read TIF and regrid to 0.5° via numpy histogram2d (area-mean binning).
    Avoids rasterio.reproject (and its broken PROJ database) entirely.
    Source TIFs are EPSG:4326 in metadata, so x/y coords from rioxarray are
    already in geographic lon/lat — no CRS conversion needed.
    """
    src = rxr.open_rasterio(tif_path, mask_and_scale=True).squeeze()
    src_x = src.x.values.astype(np.float64)       # source longitudes (W→E)
    src_y = src.y.values.astype(np.float64)       # source latitudes  (typically N→S)
    src_arr = src.values.astype(np.float64)       # (H, W)
    del src

    # Normalise longitudes to [-180, 180] (LivestockMap uses Pacific-centred
    # extent up to +191°). Anything > 180 wraps to negative side.
    src_x = np.where(src_x > 180.0, src_x - 360.0, src_x)

    # Build pixel-centre coordinate grids and flatten
    XX, YY = np.meshgrid(src_x, src_y)
    lons = XX.ravel()
    lats = YY.ravel()
    vals = src_arr.ravel()

    # Drop NaN and negative sentinels before binning
    valid = np.isfinite(vals) & (vals >= 0)
    lons, lats, vals = lons[valid], lats[valid], vals[valid]
    if vals.size == 0:
        return np.full(TARGET_SHAPE, np.nan, dtype=np.float32)

    # Area-mean bin = sum(values) / count per 0.5° cell
    sum_grid, _, _ = np.histogram2d(lats, lons,
                                    bins=[LAT_EDGES, LON_EDGES], weights=vals)
    cnt_grid, _, _ = np.histogram2d(lats, lons,
                                    bins=[LAT_EDGES, LON_EDGES])
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_grid = np.where(cnt_grid > 0, sum_grid / cnt_grid, np.nan)

    # histogram2d returns lat ascending (S→N); flip to match LAI grid (N→S)
    return mean_grid[::-1, :].astype(np.float32)


def _load_year(year):
    """Compute TLU/km² for one year by summing 5 species with FAO weights.
    Returns (360, 720) float32. NaN where all 5 species are missing.
    """
    accumulator = np.zeros((360, 720), dtype=np.float64)
    any_present  = np.zeros((360, 720), dtype=bool)
    n_loaded = 0
    for sp, w in TLU_WEIGHTS.items():
        tif = os.path.join(IN_DIR, f"{sp}_{year}.tif")
        if not os.path.isfile(tif):
            print(f"  [skip] {sp}_{year}.tif not found")
            continue
        arr = _reproject_to_05(tif)                 # (360, 720)
        valid = np.isfinite(arr)
        accumulator[valid] += w * arr[valid]
        any_present |= valid
        n_loaded += 1
    out = np.where(any_present, accumulator, np.nan).astype(np.float32)
    return out, n_loaded


# ─── Main ───────────────────────────────────────────────────────────────────
def main():
    print(f"Input  : {IN_DIR}")
    print(f"Output : {OUT_NC}")
    print(f"Years  : {YEARS[0]}-{YEARS[-1]}  ({len(YEARS)} years)")

    tlu_cube = np.full((len(YEARS), 360, 720), np.nan, dtype=np.float32)

    for i, yr in enumerate(YEARS):
        src_year = yr if yr <= 2021 else 2021      # 2022 padded from 2021
        print(f"\nYear {yr}  (using {src_year} TIFs):")
        arr, n_sp = _load_year(src_year)
        n_valid  = int(np.isfinite(arr).sum())
        mean_tlu = float(np.nanmean(arr))
        print(f"  species loaded={n_sp}/5   valid pixels={n_valid:,}   "
              f"mean TLU/km²={mean_tlu:.2f}")
        tlu_cube[i] = arr

    # Save NetCDF
    ds = xr.Dataset(
        {"tlu": (("year", "lat", "lon"), tlu_cube)},
        coords={"year": np.array(YEARS, dtype=np.int16),
                "lat":  REF_LAT,
                "lon":  REF_LON},
        attrs={
            "title": "Annual Tropical Livestock Units (TLU) at 0.5°",
            "source": "LivestockMap (FAO-derived gridded historical livestock)",
            "species_included": "Cattle, Buffalo, Horse, Sheep, Goats",
            "formula": "TLU/km² = 1.0*cattle + 1.0*buffalo + 0.8*horse + 0.1*sheep + 0.1*goats",
            "years_native": "1961-2021 annual; 2022 padded = 2021",
            "regridding": "rasterio Resampling.average from ~5 km → 0.5°",
            "nan_policy": "NaN where all 5 species missing; per-species missing set to 0 in weighted sum",
        }
    )
    ds.to_netcdf(OUT_NC, encoding={"tlu": {"zlib": True, "complevel": 4}})
    print(f"\n✔ Saved {OUT_NC}")
    print(f"  shape = (year={len(YEARS)}, lat=360, lon=720)")
    print(f"  total non-NaN cells = {int(np.isfinite(tlu_cube).sum()):,} "
          f"({100*np.isfinite(tlu_cube).mean():.1f}% of cube)")


if __name__ == "__main__":
    main()
