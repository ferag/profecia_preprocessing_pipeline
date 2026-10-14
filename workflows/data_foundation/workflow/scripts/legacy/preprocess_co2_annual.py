#!/usr/bin/env python3
"""
preprocess_co2_annual.py
Method 1 (monthly average offset) — see CO2.ipynb.

Inputs:
  CT2022 level1: /home/jovyan/read_only_data/raw/co2/co2_2000_2021_monthly_0.5deg_level1.nc
  NOAA GML CSV : /home/jovyan/data/CO2/co2_mm_gl.csv     <- uploaded from local

Outputs:
  Monthly: /home/jovyan/data/CO2/co2_1982_2022_monthly_0.5deg.nc
  Annual : /home/jovyan/data/CO2/co2_1982_2022_annual_0.5deg.nc
"""

import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path

CT_NC    = Path("/home/jovyan/read_only_data/raw/co2/co2_2000_2021_monthly_0.5deg_level1.nc")
GML_CSV  = Path("/home/jovyan/data/CO2/co2_mm_gl.csv")
OUT_DIR  = Path("/home/jovyan/data/CO2")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_MON  = OUT_DIR / "co2_1982_2022_monthly_0.5deg.nc"
OUT_ANN  = OUT_DIR / "co2_1982_2022_annual_0.5deg.nc"

# ── 1. Read CT2022 ─────────────────────────────────────────────────────
print("Reading CT2022 level1 ...")
ds = xr.open_dataset(CT_NC, engine="netcdf4")
print(f"  Time range: {ds.time.values[0]} ~ {ds.time.values[-1]}")
print(f"  Total months: {len(ds.time)}")

# ── 2. Read NOAA GML CSV ───────────────────────────────────────────────
print("\nReading NOAA GML CSV ...")
df = pd.read_csv(GML_CSV, comment="#")
df.columns = df.columns.str.strip()
df["date"] = pd.to_datetime(df[["year", "month"]].assign(day=1))
df = df.set_index("date")
print(f"  Columns:    {df.columns.tolist()}")
print(f"  Year range: {df.index[0].year} ~ {df.index[-1].year}")

# ── 3. Reference maps: year 2000 monthly + GML global mean ────────────
print("\nBuilding 2000 reference maps ...")
ref_maps = {}
ref_avg  = {}
for m in range(1, 13):
    ref_maps[m] = ds["co2"].sel(time=f"2000-{m:02d}", method="nearest")
    ref_avg[m]  = df.loc[pd.Timestamp(f"2000-{m:02d}-01"), "average"]
print("  Done (12 months)")

# ── 4. Identify year-months missing from CT2022 (1982-1999 and 2022) ──
existing_ym = set(zip(pd.DatetimeIndex(ds.time.values).year,
                      pd.DatetimeIndex(ds.time.values).month))
target_times = [(y, m) for y in range(1982, 2023) for m in range(1, 13)
                if (y, m) not in existing_ym]
print(f"\nMonths to extrapolate: {len(target_times)}")  # expected ~238

# ── 5. Method 1: monthly offset extrapolation ─────────────────────────
# map(y, m) = map(2000, m) - [GML(2000, m) - GML(y, m)]
print("Extrapolating ...")
extended = []
for y, m in target_times:
    t = pd.Timestamp(f"{y}-{m:02d}-01")
    if t not in df.index:
        print(f"  Warning: {t} not in GML CSV, skipping")
        continue
    delta   = ref_avg[m] - df.loc[t, "average"]
    new_map = (ref_maps[m] - delta).assign_coords(time=t).expand_dims("time")
    extended.append(new_map)

extended_da = xr.concat(extended, dim="time").sortby("time")

# ── 6. Merge CT2022 original + extrapolated segment ───────────────────
full_da = xr.concat([ds["co2"], extended_da], dim="time").sortby("time")
full_ds = full_da.to_dataset(name="co2")

print(f"\nMerged time range: {full_ds.time.values[0]} ~ {full_ds.time.values[-1]}")
print(f"Total months: {len(full_ds.time)}  (expected 492)")

# Save monthly
full_ds.to_netcdf(str(OUT_MON),
                  encoding={"co2": {"zlib": True, "complevel": 6, "dtype": "float32"}})
print(f"Monthly saved: {OUT_MON}")

# ── 7. Monthly -> annual ──────────────────────────────────────────────
print("\nAggregating annual mean ...")
annual = full_da.resample(time="1YE").mean()
# Replace time with integer year coordinate
annual = annual.assign_coords(year=annual.time.dt.year).swap_dims({"time": "year"}).drop_vars("time")
annual.attrs.update({
    "long_name": "Annual mean atmospheric CO2 mole fraction",
    "units": "ppm",
    "source": "CarbonTracker CT2022 (2000-2021) + NOAA GML delta extension (1982-1999, 2022)",
    "method": "Method 1: monthly average offset (Chen et al. 2024)",
})
ds_ann = annual.to_dataset(name="co2")
ds_ann.to_netcdf(str(OUT_ANN),
                 encoding={"co2": {"zlib": True, "complevel": 6, "dtype": "float32"}})

print(f"Annual shape: {annual.shape}  years: {int(annual.year[0])}~{int(annual.year[-1])}")
print(f"Global mean:  {float(annual.mean()):.2f} ppm")
print(f"Annual saved: {OUT_ANN}")
print("\nDone.")
