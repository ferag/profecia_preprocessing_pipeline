import numpy as np
import xarray as xr
import rioxarray  # noqa: F401
from pathlib import Path
from rasterio.enums import Resampling


# =================== 路径配置 ===================
BASE_DIR = Path(r"D:\2_study\Paper4\data")
RAW_N_DIR = BASE_DIR / "human" / "N"
LAI_PATH = BASE_DIR / "lai_1982_2022_annual_0.5deg.nc"
OUT_PATH = RAW_N_DIR / "Ndep_1982_2022_annual_0.5deg.nc"

print("=== N Deposition Preprocessing (Tian et al. 2022, PANGAEA.942069) ===\n")

# --- 1. 加载 LAI 参考网格（0.5°） ---
lai = xr.open_dataset(LAI_PATH).rename({"latitude": "lat", "longitude": "lon"})
target = lai["LAI"].isel(time=0).drop_vars("time")
target = target.rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs("EPSG:4326")
print(f"[1] LAI target grid: {dict(target.sizes)}, "
      f"lat {float(target.lat.min())}~{float(target.lat.max())}")

# --- 2. 加载 Tian NHx / NOy（原始 1/12°，单位 g N per cell） ---
nhx = xr.open_dataset(RAW_N_DIR / "ndep_nhx.nc", decode_times=False)
noy = xr.open_dataset(RAW_N_DIR / "ndep_noy.nc", decode_times=False)

# 修正时间：原 time 为 "years since 1850-01-01"，值 0..170
years_full = (1850 + nhx["time"].values).astype(int)
assert np.array_equal(years_full, (1850 + noy["time"].values).astype(int)), \
    "nhx / noy 时间轴不一致"

nhx = nhx.assign_coords(time=("time", years_full))
noy = noy.assign_coords(time=("time", years_full))

# 只取 1982–2020 真值段
nhx = nhx.sel(time=slice(1982, 2020))
noy = noy.sel(time=slice(1982, 2020))
print(f"[2] Loaded {int(nhx.time.min())}–{int(nhx.time.max())} "
      f"(n={nhx.sizes['time']}); var units = '{nhx['ndep_nhx'].attrs.get('units')}'")

# --- 3. NHx + NOy 求和（仍是 g N per cell） ---
ndep_total = nhx["ndep_nhx"] + noy["ndep_noy"]  # (time, lat, lon)

# --- 4. 单位换算：g N per cell → g N m⁻² yr⁻¹（除以格元面积） ---
# 球面带状面积：A(lat) = R² · dlon_rad · (sin(lat_top) - sin(lat_bot))
R = 6_371_000.0  # m
dlat = 1.0 / 12.0
dlon = 1.0 / 12.0
dlat_rad = np.deg2rad(dlat)
dlon_rad = np.deg2rad(dlon)
lat_rad = np.deg2rad(ndep_total.lat.values)
area_per_lat = R * R * dlon_rad * (
    np.sin(lat_rad + dlat_rad / 2) - np.sin(lat_rad - dlat_rad / 2)
)  # (n_lat,), m²
cell_area = xr.DataArray(
    np.broadcast_to(area_per_lat[:, None],
                    (len(lat_rad), ndep_total.sizes["lon"])).astype("float32"),
    dims=("lat", "lon"),
    coords={"lat": ndep_total.lat, "lon": ndep_total.lon},
    name="cell_area_m2",
)
ndep_intensive = (ndep_total / cell_area).astype("float32")  # g N m⁻² yr⁻¹
print(f"[3] After unit conversion: global land-mean(1982-2020) "
      f"= {float(ndep_intensive.mean()):.4f} g N m-2 yr-1")

# --- 5. 1/12° → 0.5°（average 重采样，对齐 LAI 网格） ---
ndep_intensive = (
    ndep_intensive
    .rio.set_spatial_dims(x_dim="lon", y_dim="lat")
    .rio.write_crs("EPSG:4326")
)

out_list = []
for y in ndep_intensive["time"].values:
    yr_da = (
        ndep_intensive.sel(time=int(y))
        .rio.set_spatial_dims(x_dim="lon", y_dim="lat")
        .rio.write_crs("EPSG:4326")
    )
    yr_05 = yr_da.rio.reproject_match(target, resampling=Resampling.average)
    out_list.append(yr_05.expand_dims(year=[int(y)]))
ndep_05 = xr.concat(out_list, dim="year").sortby("year")
# rio.reproject_match 会把空间维改成 y/x，统一改回 lat/lon
rename_map = {d: t for d, t in (("y", "lat"), ("x", "lon")) if d in ndep_05.dims}
if rename_map:
    ndep_05 = ndep_05.rename(rename_map)
ndep_05 = ndep_05.drop_vars(["time", "spatial_ref"], errors="ignore")
print(f"[4] After 0.5° regrid: shape={tuple(ndep_05.shape)}, "
      f"mean={float(ndep_05.mean()):.4f}")

# --- 6. 2021–2022 用 2015–2020 OLS 外推（按像元） ---
print("[5] Extrapolating 2021–2022 via per-pixel OLS on 2015–2020 ...")
hist = ndep_05.sel(year=slice(2015, 2020))
coefs = hist.polyfit(dim="year", deg=1, skipna=True)["polyfit_coefficients"]
slope = coefs.sel(degree=1)
intercept = coefs.sel(degree=0)

hist_max = ndep_05.sel(year=slice(1982, 2020)).max(dim="year")  # 像元历史最大
ext_list = []
for y in [2021, 2022]:
    pred = (intercept + slope * y).clip(min=0)
    pred = xr.where(pred > 1.5 * hist_max, 1.5 * hist_max, pred)  # 像元 1.5× 上限
    ext_list.append(pred.expand_dims(year=[y]).astype("float32"))
ndep_05 = xr.concat([ndep_05] + ext_list, dim="year").sortby("year")
ndep_05 = ndep_05.drop_vars(["degree"], errors="ignore")

# --- 7. 保存 ---
ndep_05 = ndep_05.rename("ndep").astype("float32")
ndep_05.attrs = {
    "long_name": "Total nitrogen deposition (NOy + NHx, dry + wet)",
    "units": "g N m-2 yr-1",
    "source": "Tian et al. (2022), PANGAEA.942069",
    "processing": (
        "NHx + NOy summed; converted g N/cell -> g N m-2 yr-1 via geodesic "
        "cell area; average-resampled from 1/12 deg to 0.5 deg LAI grid; "
        "2021-2022 extrapolated by per-pixel OLS on 2015-2020, "
        "clipped to [0, 1.5 x per-pixel historical max]."
    ),
}

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
ndep_05.to_dataset().to_netcdf(
    OUT_PATH,
    encoding={"ndep": {"zlib": True, "complevel": 6, "dtype": "float32"}},
)

# --- 8. 摘要 ---
ts = ndep_05.mean(dim=["lat", "lon"])
print("\n[6] Output written.")
print(f"    File : {OUT_PATH}")
print(f"    Shape: {ndep_05.shape} (year, lat, lon)")
print(f"    Years: {int(ndep_05.year.min())} ~ {int(ndep_05.year.max())}")
print(f"    Mean : {float(ndep_05.mean()):.4f} g N m-2 yr-1")
print(f"    Time series (global land mean):")
for y, v in zip(ts.year.values, ts.values):
    tag = "  *EXTRAP*" if y in (2021, 2022) else ""
    print(f"      {int(y)}: {float(v):.4f}{tag}")
print("\nDone.")
