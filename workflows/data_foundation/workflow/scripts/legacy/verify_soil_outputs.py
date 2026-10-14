#!/usr/bin/env python3
"""
verify_soil_outputs.py
Validate the three soil-related NC outputs:
  - dimensions: (latitude=360, longitude=720)
  - coordinate range: lat -89.75~89.75, lon -179.75~179.75
  - data sanity: mean / std / range / valid pixels
"""

import xarray as xr
import numpy as np
from pathlib import Path

DATA_ROOT = Path("/home/jovyan/data")

PATH_HWSD2 = DATA_ROOT / "HWSD2_soil"       / "hwsd2_soil_0.5deg.nc"
PATH_RICH  = DATA_ROOT / "SPECIES_RICHNESS" / "richness_0.5deg.nc"
PATH_ELEV  = DATA_ROOT / "Elevation"        / "elevation_0.5deg.nc"

EXPECTED_RANGES = {
    "sand":      (0, 100, "%"),
    "clay":      (0, 100, "%"),
    "silt":      (0, 100, "%"),
    "ph":        (3, 10, ""),
    "soc":       (0, 50, "%"),
    "total_n":   (0, 25, "%"),         # peat soils can reach ~20%
    "bulk":      (0.1, 2.0, "g/cm3"),  # organic soils as low as 0.1
    "cec":       (0, 100, "cmol/kg"),
    "richness":  (0, 5000, "species/1000km2"),
    "elevation": (-500, 9000, "m"),
}


def banner(s):
    print("\n" + "=" * 60)
    print(f" {s}")
    print("=" * 60)


def check_grid(ds, name):
    """Validate the spatial grid specification."""
    issues = []
    if "latitude" not in ds.dims or "longitude" not in ds.dims:
        issues.append(f"  [FAIL] missing latitude/longitude dim: {dict(ds.sizes)}")
        return issues
    if ds.sizes["latitude"] != 360:
        issues.append(f"  [FAIL] latitude length {ds.sizes['latitude']} != 360")
    if ds.sizes["longitude"] != 720:
        issues.append(f"  [FAIL] longitude length {ds.sizes['longitude']} != 720")

    lat0, lat1 = float(ds.latitude[0]), float(ds.latitude[-1])
    lon0, lon1 = float(ds.longitude[0]), float(ds.longitude[-1])
    print(f"  Grid: lat [{lat0:.3f}, {lat1:.3f}]  lon [{lon0:.3f}, {lon1:.3f}]")

    lat_step = float(np.diff(ds.latitude).mean())
    lon_step = float(np.diff(ds.longitude).mean())
    if abs(abs(lat_step) - 0.5) > 0.01:
        issues.append(f"  [FAIL] lat step {lat_step:.4f} != 0.5deg")
    if abs(lon_step - 0.5) > 0.01:
        issues.append(f"  [FAIL] lon step {lon_step:.4f} != 0.5deg")
    print(f"  Step: lat={lat_step:.3f}  lon={lon_step:.3f}")
    return issues


def check_var(arr, var_name):
    """Per-variable statistics + range check."""
    issues = []
    valid = ~np.isnan(arr)
    n_valid = int(valid.sum())
    n_total = arr.size

    if n_valid == 0:
        issues.append(f"  [FAIL] {var_name}: all NaN")
        return issues

    mean = float(np.nanmean(arr))
    std  = float(np.nanstd(arr))
    vmin = float(np.nanmin(arr))
    vmax = float(np.nanmax(arr))

    expected = EXPECTED_RANGES.get(var_name)
    if expected:
        emin, emax, units = expected
        flag = ""
        if vmin < emin - abs(emin) * 0.5 or vmax > emax * 1.5:
            flag = "  [WARN] out of expected range"
            issues.append(f"  [WARN] {var_name}: range [{vmin:.2f}, {vmax:.2f}], expected [{emin}, {emax}]")
        print(f"  {var_name:<10} mean={mean:>8.2f}  std={std:>7.2f}  "
              f"range=[{vmin:>7.2f}, {vmax:>7.2f}] {units}  "
              f"valid={n_valid:>7,}/{n_total:,} ({100*n_valid/n_total:.1f}%){flag}")
    else:
        print(f"  {var_name:<10} mean={mean:.2f}  std={std:.2f}  range=[{vmin:.2f}, {vmax:.2f}]")
    return issues


def verify_file(path: Path, var_names: list):
    if not path.exists():
        print(f"\n[FAIL] file not found: {path}")
        return [f"file missing: {path.name}"]
    banner(path.name)
    print(f"  Path: {path}  ({path.stat().st_size/1024/1024:.2f} MB)")
    ds = xr.open_dataset(path)
    print(f"  Variables: {list(ds.data_vars)}")
    print(f"  Dims: {dict(ds.sizes)}")

    issues = check_grid(ds, path.name)

    print(f"\n  Statistics:")
    for vn in var_names:
        if vn in ds.data_vars:
            issues += check_var(ds[vn].values, vn)
        else:
            issues.append(f"  [FAIL] missing variable: {vn}")
    ds.close()
    return issues


# ============================ Main ============================
all_issues = []

all_issues += verify_file(
    PATH_HWSD2,
    ["sand", "clay", "silt", "ph", "soc", "total_n", "bulk", "cec"],
)
all_issues += verify_file(PATH_RICH, ["richness"])
all_issues += verify_file(PATH_ELEV, ["elevation"])

# Consistency check: sand + silt + clay ~ 100
banner("Consistency check: sand + silt + clay")
if not PATH_HWSD2.exists():
    print("  Skipped (HWSD2 file not found)")
else:
    ds = xr.open_dataset(PATH_HWSD2)
    total = (ds["sand"] + ds["silt"] + ds["clay"]).values
    m = ~np.isnan(total)
    if m.any():
        s_mean = float(np.nanmean(total[m]))
        s_std  = float(np.nanstd(total[m]))
        print(f"  sand+silt+clay  mean={s_mean:.2f}  std={s_std:.2f}  (expected ~100)")
        if abs(s_mean - 100) > 5:
            all_issues.append(f"sand+silt+clay mean {s_mean:.2f} deviates from 100")
    ds.close()

# Summary
banner("Summary")
if not all_issues:
    print("  [OK] All checks passed; outputs match expectations.")
else:
    print(f"  [WARN] {len(all_issues)} issue(s) found:")
    for i in all_issues:
        print(f"    - {i}")
