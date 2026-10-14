#!/usr/bin/env python3
"""
preprocess_soil_0p5.py
HWSD2 + species richness + elevation -> global 0.5deg static NC.

Outputs:
  data/HWSD2_soil/hwsd2_soil_0.5deg.nc       (sand/clay/silt/ph/soc/total_n/bulk/cec)
  data/SPECIES_RICHNESS/richness_0.5deg.nc
  data/Elevation/elevation_0.5deg.nc
"""

import gc
import numpy as np
import xarray as xr
import rioxarray
import pandas as pd
from pathlib import Path
from rasterio.enums import Resampling

# =================== Configuration ===================
DATA_ROOT = Path("/home/jovyan/data")

HWSD2_BIL  = DATA_ROOT / "HWSD2_soil/RAW/HWSD2.bil"
HWSD2_CSV  = DATA_ROOT / "HWSD2_soil/RAW/HWSD2_LAYERS.csv"
RICH_TIF   = DATA_ROOT / "SPECIES_RICHNESS/RAW/w3_tile_joint_sr1000.tif"
# ESRI Grid: prefer inner directory containing ADF files, fall back to outer
_elev_outer = DATA_ROOT / "Elevation/RAW/mn30_grd"
ELEV_DIR    = (_elev_outer / "mn30_grd") if (_elev_outer / "mn30_grd").exists() else _elev_outer

# Output paths
OUT_HWSD2 = DATA_ROOT / "HWSD2_soil" / "hwsd2_soil_0.5deg.nc"
OUT_RICH  = DATA_ROOT / "SPECIES_RICHNESS" / "richness_0.5deg.nc"
OUT_ELEV  = DATA_ROOT / "Elevation" / "elevation_0.5deg.nc"
for p in (OUT_HWSD2, OUT_RICH, OUT_ELEV):
    p.parent.mkdir(parents=True, exist_ok=True)

LAI_NC = "/home/jovyan/read_only_data/final_datasets/annual/lai_1982_2022_annual_0.5deg.nc"

# HWSD2 column -> output variable name
VAR_MAP = {
    "SAND":      "sand",
    "CLAY":      "clay",
    "SILT":      "silt",
    "PH_WATER":  "ph",
    "ORG_CARBON":"soc",
    "TOTAL_N":   "total_n",
    "BULK":      "bulk",
    "CEC_SOIL":  "cec",
}
ATTRS_MAP = {
    "sand":    ("Sand content, topsoil", "%"),
    "clay":    ("Clay content, topsoil", "%"),
    "silt":    ("Silt content, topsoil", "%"),
    "ph":      ("pH in water, topsoil", ""),
    "soc":     ("Organic carbon, topsoil", "%"),
    "total_n": ("Total nitrogen, topsoil", "%"),
    "bulk":    ("Bulk density, topsoil", "g/cm3"),
    "cec":     ("CEC of soil, topsoil", "cmol/kg"),
}
NODATA_BIL = 65535
# =====================================================


def make_target(lai_nc):
    ds = xr.open_dataset(lai_nc)
    target = xr.DataArray(
        np.zeros((360, 720)),
        dims=["latitude", "longitude"],
        coords={"latitude": ds.latitude, "longitude": ds.longitude},
    ).rio.write_crs("EPSG:4326")
    ds.close()
    return target


def weighted_mean(group, col):
    """SHARE-weighted mean, filtering HWSD2 negative sentinel values (NoData markers)."""
    w = group["SHARE"].fillna(1)
    v = group[col]
    valid = v.notna() & (w > 0) & (v >= 0)   # HWSD2 uses -1/-4 etc. for NoData
    if valid.sum() == 0:
        return np.nan
    return float((v[valid] * w[valid]).sum() / w[valid].sum())


def process_hwsd2(target, out_path):
    print("=== HWSD2 preprocessing ===\n")
    print("Reading HWSD2_LAYERS.csv ...")
    df = pd.read_csv(HWSD2_CSV, low_memory=False)
    print(f"  LAYER values: {sorted(df['LAYER'].dropna().unique())}")

    # Per SMU, take the shallowest layer (min TOPDEP); preserve multi-component rows
    shallowest = df.groupby("HWSD2_SMU_ID")["TOPDEP"].transform("min")
    df_top = df[df["TOPDEP"] == shallowest].copy()
    layer_distrib = df_top["LAYER"].value_counts()
    print(f"  Shallowest-layer distribution:\n    {dict(layer_distrib)}")

    smu_ids = df_top["HWSD2_SMU_ID"].unique()
    max_smu = int(smu_ids.max()) + 1
    print(f"  {len(smu_ids)} unique SMU_IDs (shallowest-layer coverage)")

    print("Computing SHARE-weighted means ...")
    lookup = {col: np.full(max_smu, np.nan, dtype=np.float32) for col in VAR_MAP}
    for smu_id, grp in df_top.groupby("HWSD2_SMU_ID"):
        for col in VAR_MAP:
            if col in grp.columns:
                lookup[col][int(smu_id)] = weighted_mean(grp, col)
    print("  Lookup table built")

    print("\nReading HWSD2.bil (uint16, ~1.86 GB) ...")
    smu_arr = np.fromfile(str(HWSD2_BIL), dtype="<u2").reshape(21600, 43200)  # uint16
    print(f"  Read complete. Masking NoData ({NODATA_BIL}) -> 0 in place ...")
    # In-place mask (avoid 3.7 GB peak from np.where allocating a copy)
    smu_arr[smu_arr == NODATA_BIL] = 0
    print(f"  shape: {smu_arr.shape}  dtype: {smu_arr.dtype}  "
          f"SMU_ID range: {smu_arr[smu_arr>0].min()}~{smu_arr.max()}")

    nrows, ncols = smu_arr.shape
    lat_30s = np.linspace(89.99583333, -89.99583333, nrows)
    lon_30s = np.linspace(-179.99583333, 179.99583333, ncols)

    soil_vars = {}
    for csv_col, var_name in VAR_MAP.items():
        print(f"  Processing {var_name} ...")
        lut = lookup[csv_col]
        # Out-of-range SMU_ID -> index 0 (lookup[0] = NaN)
        safe_idx = np.where(smu_arr < len(lut), smu_arr, 0)
        prop_arr = lut[safe_idx]                          # float32, (21600, 43200) ~3.7 GB
        del safe_idx

        da_30s = xr.DataArray(
            prop_arr, dims=["latitude", "longitude"],
            coords={"latitude": lat_30s, "longitude": lon_30s},
        ).rio.write_crs("EPSG:4326").rio.write_nodata(np.nan)
        # Average resampling: each 0.5° cell = mean of all overlapping 30-arc-sec
        # source pixels, skipping NaN. Bilinear was wrong here — it propagated
        # internal NaN holes (water bodies, unclassified soil) and yielded ~93% NaN.
        da_05 = da_30s.rio.reproject_match(target, resampling=Resampling.average)
        soil_vars[var_name] = da_05.values.copy()
        print(f"    mean={np.nanmean(da_05.values):.3f}  valid={np.sum(~np.isnan(da_05.values)):,}")

        del prop_arr, da_30s, da_05
        gc.collect()

    # Normalize sand+silt+clay -> 100 (constraint broken by bilinear resampling)
    if all(k in soil_vars for k in ("sand", "silt", "clay")):
        s = soil_vars["sand"] + soil_vars["silt"] + soil_vars["clay"]
        m = s > 0
        for k in ("sand", "silt", "clay"):
            soil_vars[k] = np.where(m, soil_vars[k] / s * 100.0, np.nan).astype(np.float32)
        print("  Texture normalized: sand+silt+clay -> 100%")

    print(f"\nSaving {out_path.name} ...")
    lats = target.latitude.values
    lons = target.longitude.values
    data_vars = {}
    for var_name, arr in soil_vars.items():
        long_name, units = ATTRS_MAP[var_name]
        data_vars[var_name] = xr.DataArray(
            arr, dims=["latitude", "longitude"],
            coords={"latitude": lats, "longitude": lons},
            attrs={"long_name": long_name, "units": units,
                   "source": "HWSD2 (FAO/IIASA), topsoil SHARE-weighted"},
        )
    enc = {v: {"zlib": True, "complevel": 6, "dtype": "float32"} for v in data_vars}
    xr.Dataset(data_vars).to_netcdf(str(out_path), encoding=enc)
    print(f"  Saved: {out_path}")


def process_richness(target, out_path):
    print("\n=== Species Richness preprocessing ===")
    if not RICH_TIF.exists():
        print(f"  Skipped (file not found): {RICH_TIF}")
        return
    da = rioxarray.open_rasterio(RICH_TIF, masked=True).squeeze()
    print(f"  shape: {da.shape}  CRS: {da.rio.crs}")
    da_05 = da.rio.reproject_match(target, resampling=1)
    arr = da_05.values.astype(np.float32)
    arr[arr < 0] = np.nan
    xr.DataArray(
        arr, dims=["latitude", "longitude"],
        coords={"latitude": target.latitude.values, "longitude": target.longitude.values},
        attrs={"long_name": "Vascular plant species richness (sr per 1000 km2)",
               "units": "species",
               "source": "Keil et al. 2019, w3_tile_joint_sr1000"},
    ).to_dataset(name="richness").to_netcdf(
        str(out_path),
        encoding={"richness": {"zlib": True, "complevel": 6, "dtype": "float32"}},
    )
    print(f"  mean={np.nanmean(arr):.1f}  valid={np.sum(~np.isnan(arr)):,}")
    print(f"  Saved: {out_path}")


def process_elevation(target, out_path):
    print("\n=== Elevation preprocessing ===")
    if not ELEV_DIR.exists():
        print(f"  Skipped (directory not found): {ELEV_DIR}")
        return
    print(f"Reading ESRI Grid: {ELEV_DIR} ...")
    da = rioxarray.open_rasterio(str(ELEV_DIR), masked=True).squeeze()
    print(f"  shape: {da.shape}  CRS: {da.rio.crs}")
    if da.rio.crs is None:
        da = da.rio.write_crs("EPSG:4326")
    da_05 = da.rio.reproject_match(target, resampling=1)
    arr = da_05.values.astype(np.float32)
    xr.DataArray(
        arr, dims=["latitude", "longitude"],
        coords={"latitude": target.latitude.values, "longitude": target.longitude.values},
        attrs={"long_name": "Mean elevation", "units": "m",
               "source": "GTOPO30 mn30_grd, 30 arc-second, bilinear to 0.5deg"},
    ).to_dataset(name="elevation").to_netcdf(
        str(out_path),
        encoding={"elevation": {"zlib": True, "complevel": 6, "dtype": "float32"}},
    )
    print(f"  mean={np.nanmean(arr):.1f} m  valid={np.sum(~np.isnan(arr)):,}")
    print(f"  Saved: {out_path}")


# ============================ Main ============================
target = make_target(LAI_NC)

if OUT_HWSD2.exists():
    print(f"=== HWSD2 already exists, skipping ===\n  {OUT_HWSD2}\n")
else:
    process_hwsd2(target, OUT_HWSD2)

if OUT_RICH.exists():
    print(f"\n=== Richness already exists, skipping ===\n  {OUT_RICH}")
else:
    process_richness(target, OUT_RICH)

if OUT_ELEV.exists():
    print(f"\n=== Elevation already exists, skipping ===\n  {OUT_ELEV}")
else:
    process_elevation(target, OUT_ELEV)

print("\nDone.")
