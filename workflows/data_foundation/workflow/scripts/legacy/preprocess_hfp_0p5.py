#!/usr/bin/env python3

import gc
import numpy as np
import xarray as xr
import rioxarray
import rasterio
from rasterio.warp import reproject, Resampling
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# =================== Configuration ===================
RAW_DIR = Path("/home/jovyan/data/HFP/RAW")
OUT_DIR = Path("/home/jovyan/data/HFP/0p5")
OUT_DIR.mkdir(parents=True, exist_ok=True)

YEARS = list(range(1982, 2023))
LAI_NC = "/home/jovyan/read_only_data/final_datasets/annual/lai_1982_2022_annual_0.5deg.nc"
MAX_WORKERS = 8   # 根据你的CPU调整，建议4-8
# =====================================================

def make_target(lai_nc):
    ds = xr.open_dataset(lai_nc)
    target = xr.DataArray(
        np.zeros((360, 720), dtype=np.float32),
        dims=["latitude", "longitude"],
        coords={"latitude": ds.latitude, "longitude": ds.longitude},
    ).rio.write_crs("EPSG:4326")
    ds.close()
    return target

def find_tif(year: int) -> Path | None:
    candidates = [
        RAW_DIR / f"hfp{year}.tif",
        RAW_DIR / f"hfootprint_{year}_1km.tif",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None

def read_resample(tif_path: Path, dst_transform, dst_crs, dst_shape) -> np.ndarray:
    """复用变换参数，单次重投影"""
    with rasterio.open(tif_path) as src:
        arr = np.empty(dst_shape, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=arr,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
            num_threads=2,          # 每个任务内再开少量线程
        )
    arr[arr < 0] = np.nan
    return arr

print("=== Optimized HFP preprocessing ===\n")

target = make_target(LAI_NC)
target_transform = target.rio.transform()
target_crs = target.rio.crs
dst_shape = target.shape

print(f"Target grid: {target.latitude.values[0]:.2f}~{target.latitude.values[-1]:.2f} "
      f"lon {target.longitude.values[0]:.2f}~{target.longitude.values[-1]:.2f}\n")

# ── STEP 1: 并行读 & 重采样 ─────────────────────────────────────
raw_arrays = {}
missing = []

def process_year(year):
    tif = find_tif(year)
    if tif is None:
        return year, None, "missing"
    arr = read_resample(tif, target_transform, target_crs, dst_shape)
    src = "obs" if "hfp" in tif.name else "ext"
    mean_val = np.nanmean(arr)
    valid = np.sum(~np.isnan(arr))
    return year, arr, f"{src}  mean={mean_val:.3f}  valid={valid:,}"

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    future_to_year = {executor.submit(process_year, y): y for y in YEARS}
    for future in as_completed(future_to_year):
        year, arr, msg = future.result()
        if arr is None:
            print(f"  [{year}] missing")
            missing.append(year)
        else:
            raw_arrays[year] = arr
            print(f"  [{year}] {msg}", flush=True)
        gc.collect()

# ── STEP 2 & 3: Bias correction + 保存（不变）──
if 2000 in raw_arrays and 1999 in raw_arrays:
    delta = raw_arrays[2000] - raw_arrays[1999]
    print(f"\nBias correction: delta mean={np.nanmean(delta):.4f}")
    for year in range(1982, 2000):
        if year in raw_arrays:
            raw_arrays[year] += delta
            # print(f"  Corrected {year}")  # 可选

# ── STEP 3: Stack and save NC ───────────────────────────────────────────
valid_years = sorted(raw_arrays.keys())
stack = np.stack([raw_arrays[y] for y in valid_years], axis=0)  # (N, 360, 720)

print(f"\nStack shape: {stack.shape}  years: {valid_years[0]}~{valid_years[-1]}")
print(f"Global mean: {np.nanmean(stack):.3f}")

da_out = xr.DataArray(
    stack,
    dims=["year", "latitude", "longitude"],
    coords={
        "year":      np.array(valid_years, dtype=np.int32),
        "latitude":  target.latitude.values,
        "longitude": target.longitude.values,
    },
    attrs={
        "long_name": "Annual Human Footprint Index",
        "units":     "dimensionless",
        "source":    "Mu et al. 2022 (Figshare 16571064, 2000-2022) + "
                     "Hengl 2022 (Zenodo 6636562, 1982-1999, extrapolated)",
        "bias_correction": "Additive offset delta=obs(2000)-extrap(1999) applied to 1982-1999",
        "resampling": "Bilinear, 1km -> 0.5deg WGS84",
    },
)

out_path = OUT_DIR / "hfp_1982_2022_annual_0.5deg.nc"
da_out.to_dataset(name="hfp").to_netcdf(
    str(out_path),
    encoding={"hfp": {"zlib": True, "complevel": 6, "dtype": "float32"}},
)
print(f"\n✅ Saved: {out_path}")