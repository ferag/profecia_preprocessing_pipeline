#!/usr/bin/env python3
"""Create PROFECIA derived/repackaged products from harmonized inputs."""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import xarray as xr


def _one(ds: xr.Dataset, name: str) -> xr.DataArray:
    if name in ds.data_vars:
        return ds[name]
    if len(ds.data_vars) == 1:
        return ds[next(iter(ds.data_vars))]
    raise KeyError(f"Could not find {name}; available={list(ds.data_vars)}")


def _celsius(da: xr.DataArray) -> xr.DataArray:
    units = da.attrs.get("units", "").lower().replace(" ", "")
    return (da - 273.15).astype("float32") if units in {"k", "kelvin"} else da.astype("float32")


def _write(da: xr.DataArray, out: Path, attrs: dict) -> None:
    da = da.astype("float32")
    da.attrs.update(attrs)
    ds = da.to_dataset(name=da.name)
    ds.attrs.update({"profecia_derived": "true"})
    out.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(out, encoding={da.name: {"zlib": True, "complevel": 4, "dtype": "float32"}})
    print(f"Wrote {out}")


def copy_canonical(src: Path, variable: str, out: Path) -> bool:
    if not src or not src.exists():
        return False
    with xr.open_dataset(src) as ds:
        var = variable if variable in ds.data_vars else next(iter(ds.data_vars))
        da = ds[var].rename(variable).astype("float32")
        da.attrs.update(
            {
                "canonical_reference_file": str(src),
                "canonical_reference_policy": "Copied from /srv/read_only_data final_datasets.",
            }
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        da.to_dataset(name=variable).to_netcdf(out, encoding={variable: {"zlib": True, "complevel": 4, "dtype": "float32"}})
    print(f"Wrote {out} from canonical reference {src}")
    return True


def vpd(t2m: Path, d2m: Path, out: Path) -> None:
    with xr.open_dataset(t2m) as dst, xr.open_dataset(d2m) as dsd:
        dst, dsd = xr.align(dst, dsd, join="exact")
        t = _celsius(_one(dst, "t2m"))
        td = _celsius(_one(dsd, "d2m"))
        es = 0.611 * np.exp((17.5 * t) / (t + 240.978))
        ea = 0.611 * np.exp((17.5 * td) / (td + 240.978))
        da = (es - ea).clip(min=0).rename("vpd")
        _write(da, out, {"long_name": "Vapor Pressure Deficit", "units": "kPa", "formula": "VPD = es(T2M) - ea(D2M); es/ea = 0.611 exp(17.5 T / (T + 240.978)), temperatures in degC", "source_variables": "t2m,d2m"})


def subswc(swvl2: Path, swvl3: Path, out: Path) -> None:
    with xr.open_dataset(swvl2) as ds2, xr.open_dataset(swvl3) as ds3:
        ds2, ds3 = xr.align(ds2, ds3, join="exact")
        a = _one(ds2, "swvl2")
        b = _one(ds3, "swvl3")
        da = (((a * 21.0) + (b * 72.0)) / 93.0).rename("subswc")
        _write(da, out, {"long_name": "Sub-surface Soil Water Content", "units": a.attrs.get("units", "m**3 m**-3"), "formula": "subswc = (swvl2 * 21 + swvl3 * 72) / 93", "weights": "swvl2: 21/93; swvl3: 72/93", "source_variables": "swvl2,swvl3"})


def wind(u10: Path, v10: Path, out: Path) -> None:
    with xr.open_dataset(u10) as dsu, xr.open_dataset(v10) as dsv:
        dsu, dsv = xr.align(dsu, dsv, join="exact")
        u = _one(dsu, "u10")
        v = _one(dsv, "v10")
        da = xr.apply_ufunc(np.hypot, u, v).rename("wind")
        _write(da, out, {"long_name": "10 m wind speed", "units": "m s**-1", "formula": "wind = sqrt(u10**2 + v10**2)", "source_variables": "u10,v10"})


def alias_spei(src: Path | None, out: Path, canonical_reference: Path | None = None) -> None:
    if canonical_reference and copy_canonical(canonical_reference, "spei06", out):
        return
    if src is None:
        raise ValueError("--spei06 is required when --canonical-reference is not provided or does not exist.")
    with xr.open_dataset(src) as ds:
        var = "spei06" if "spei06" in ds.data_vars else next(iter(ds.data_vars))
        da = ds[var].rename("spei06")
        out.parent.mkdir(parents=True, exist_ok=True)
        da.to_dataset(name="spei06").to_netcdf(out, encoding={"spei06": {"zlib": True, "complevel": 4, "dtype": "float32"}})
    print(f"Wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("vpd"); p.add_argument("--t2m", type=Path, required=True); p.add_argument("--d2m", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("subswc"); p.add_argument("--swvl2", type=Path, required=True); p.add_argument("--swvl3", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("wind"); p.add_argument("--u10", type=Path, required=True); p.add_argument("--v10", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("spei06-univariable"); p.add_argument("--spei06", type=Path, default=None); p.add_argument("--output", type=Path, required=True); p.add_argument("--canonical-reference", type=Path, default=None)
    args = ap.parse_args()
    if args.cmd == "vpd": vpd(args.t2m, args.d2m, args.output)
    elif args.cmd == "subswc": subswc(args.swvl2, args.swvl3, args.output)
    elif args.cmd == "wind": wind(args.u10, args.v10, args.output)
    elif args.cmd == "spei06-univariable": alias_spei(args.spei06, args.output, args.canonical_reference)

if __name__ == "__main__":
    main()
