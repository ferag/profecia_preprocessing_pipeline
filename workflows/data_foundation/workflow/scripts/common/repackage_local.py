#!/usr/bin/env python3
"""Repackage local PROFECIA source_data files into expected release products."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr

LAT = np.linspace(89.5, -90.0, 360).astype('float32')
LON = np.linspace(-180.0, 179.5, 720).astype('float32')


def _rename_xy(ds: xr.Dataset) -> xr.Dataset:
    ren={}
    if 'y' in ds.dims or 'y' in ds.coords: ren['y']='latitude'
    if 'x' in ds.dims or 'x' in ds.coords: ren['x']='longitude'
    if 'lat' in ds.dims or 'lat' in ds.coords: ren['lat']='latitude'
    if 'lon' in ds.dims or 'lon' in ds.coords: ren['lon']='longitude'
    ds=ds.rename({k:v for k,v in ren.items() if k in set(ds.dims)|set(ds.coords)})
    if 'latitude' in ds and float(ds.latitude[0]) < float(ds.latitude[-1]): ds=ds.sortby('latitude', ascending=False)
    if 'longitude' in ds and float(ds.longitude[0]) > float(ds.longitude[-1]): ds=ds.sortby('longitude')
    return ds


def _standardize_grid(ds: xr.Dataset) -> xr.Dataset:
    if ds.sizes.get('latitude') == 360 and ds.sizes.get('longitude') == 720:
        ds = ds.assign_coords(latitude=LAT, longitude=LON)
        ds['latitude'].attrs.update({'standard_name': 'latitude', 'units': 'degrees_north'})
        ds['longitude'].attrs.update({'standard_name': 'longitude', 'units': 'degrees_east'})
    return ds


def _one(ds: xr.Dataset, variable: str) -> str:
    if variable in ds.data_vars:
        return variable
    if len(ds.data_vars) == 1:
        return next(iter(ds.data_vars))
    raise KeyError(f"Could not find {variable}; available={list(ds.data_vars)}")


def _write_selected(input: Path, variable: str, output: Path, attrs: dict | None = None):
    with xr.open_dataset(input) as ds:
        ds=_standardize_grid(_rename_xy(ds))
        var=_one(ds, variable)
        out=ds[[var]].rename({var: variable}) if var != variable else ds[[var]]
        if attrs:
            out.attrs.update(attrs)
            out[variable].attrs.update(attrs)
        output.parent.mkdir(parents=True, exist_ok=True)
        out.to_netcdf(output, encoding={variable:{'zlib':True,'complevel':4,'dtype':'float32'}})


def _canonical_or_none(path: Path | None) -> Path | None:
    if path is None:
        return None
    raw = str(path)
    if not raw or raw == ".":
        return None
    if path.exists():
        return path
    return None


def copy_annual(input: Path | None, variable: str, output: Path, canonical_reference: Path | None = None):
    canonical = _canonical_or_none(canonical_reference)
    if canonical:
        _write_selected(
            canonical,
            variable,
            output,
            {
                'profecia_repackaged': 'true',
                'canonical_reference_file': str(canonical),
                'canonical_reference_policy': 'Copied from /srv/read_only_data final_datasets.',
            },
        )
        print(f'Wrote {output} from canonical reference {canonical}')
        return
    if input is None:
        raise ValueError("--input is required when --canonical-reference is not provided or does not exist.")

    with xr.open_dataset(input) as ds:
        ds=_standardize_grid(_rename_xy(ds))
        var=_one(ds, variable)
        out=ds[[var]].rename({var: variable}) if var != variable else ds[[var]]
        if 'year' in out.dims:
            out=out.rename({'year':'time'})
            vals=out.time.values.astype(int)
            out=out.assign_coords(time=np.array([np.datetime64(f'{y}-01-01') for y in vals]))
        output.parent.mkdir(parents=True, exist_ok=True)
        out.to_netcdf(output, encoding={variable:{'zlib':True,'complevel':4,'dtype':'float32'}})
    print(f'Wrote {output}')


def expand_static(input: Path | None, variable: str, output: Path, start_year=1982, end_year=2022, canonical_reference: Path | None = None):
    canonical = _canonical_or_none(canonical_reference)
    if canonical:
        _write_selected(
            canonical,
            variable,
            output,
            {
                'profecia_repackaged': 'true',
                'canonical_reference_file': str(canonical),
                'canonical_reference_policy': 'Copied from /srv/read_only_data final_datasets to preserve canonical masks and values.',
            },
        )
        print(f'Wrote {output} from canonical reference {canonical}')
        return
    if input is None:
        raise ValueError("--input is required when --canonical-reference is not provided or does not exist.")

    with xr.open_dataset(input) as ds:
        ds=_standardize_grid(_rename_xy(ds))
        var=_one(ds, variable)
        da=ds[var].astype('float32')
        times=pd.date_range(f'{start_year}-01-01', f'{end_year}-12-01', freq='MS')
        da=da.expand_dims(time=times).rename(variable)
        out=da.to_dataset(name=variable)
        out.attrs.update(ds.attrs)
        out.attrs['profecia_repackaged']='true'
        out.attrs['processing']='Static local layer repeated for each monthly timestep in PROFECIA period.'
        output.parent.mkdir(parents=True, exist_ok=True)
        out.to_netcdf(output, encoding={variable:{'zlib':True,'complevel':4,'dtype':'float32'}})
    print(f'Wrote {output}')


def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest='cmd', required=True)
    p=sub.add_parser('annual'); p.add_argument('--input',type=Path,default=None); p.add_argument('--variable',required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--canonical-reference',type=Path,default=None)
    p=sub.add_parser('static-monthly'); p.add_argument('--input',type=Path,default=None); p.add_argument('--variable',required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--start-year',type=int,default=1982); p.add_argument('--end-year',type=int,default=2022); p.add_argument('--canonical-reference',type=Path,default=None)
    a=ap.parse_args()
    if a.cmd=='annual': copy_annual(a.input,a.variable,a.output,a.canonical_reference)
    else: expand_static(a.input,a.variable,a.output,a.start_year,a.end_year,a.canonical_reference)
if __name__=='__main__': main()
