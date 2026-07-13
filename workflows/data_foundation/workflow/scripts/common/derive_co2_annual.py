#!/usr/bin/env python3
"""Extend CarbonTracker CO2 with NOAA GML monthly offsets and aggregate annually."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr


def copy_canonical(src: Path, output: Path) -> bool:
    if not src or not src.exists():
        return False
    with xr.open_dataset(src) as ds:
        var = 'co2' if 'co2' in ds.data_vars else next(iter(ds.data_vars))
        out = ds[[var]].rename({var: 'co2'}) if var != 'co2' else ds[[var]]
        out.attrs.update({
            'profecia_derived': 'true',
            'canonical_reference_file': str(src),
            'canonical_reference_policy': 'Copied from /srv/read_only_data final_datasets because the original CO2 preprocessing is authoritative.',
        })
        output.parent.mkdir(parents=True, exist_ok=True)
        out.to_netcdf(output, encoding={'co2': {'zlib': True, 'complevel': 6, 'dtype': 'float32'}})
    print(f'Wrote {output} from canonical reference {src}')
    return True


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--monthly-co2', type=Path, default=None)
    ap.add_argument('--gml-csv', type=Path, default=None)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--start-year', type=int, default=1982)
    ap.add_argument('--end-year', type=int, default=2022)
    ap.add_argument('--canonical-reference', type=Path, default=None)
    args=ap.parse_args()

    if args.canonical_reference and copy_canonical(args.canonical_reference, args.output):
        return
    if args.monthly_co2 is None or args.gml_csv is None:
        raise ValueError("--monthly-co2 and --gml-csv are required when --canonical-reference is not provided or does not exist.")

    with xr.open_dataset(args.monthly_co2) as ds:
        if 'co2' not in ds.data_vars:
            raise KeyError(f"co2 not found in {args.monthly_co2}: {list(ds.data_vars)}")
        co2 = ds['co2'].load()

    df = pd.read_csv(args.gml_csv, comment='#')
    df.columns = df.columns.str.strip()
    df['date'] = pd.to_datetime(df[['year','month']].assign(day=1))
    df = df.set_index('date')
    if 'average' not in df.columns:
        raise KeyError(f"Column 'average' not found in {args.gml_csv}: {df.columns.tolist()}")

    time_index = pd.DatetimeIndex(co2.time.values)
    existing = set(zip(time_index.year, time_index.month))
    ref_maps = {}
    ref_avg = {}
    for month in range(1, 13):
        ref_time = pd.Timestamp(f'2000-{month:02d}-01')
        ref_maps[month] = co2.sel(time=f'2000-{month:02d}', method='nearest')
        ref_avg[month] = float(df.loc[ref_time, 'average'])

    extended = []
    for year in range(args.start_year, args.end_year + 1):
        for month in range(1, 13):
            if (year, month) in existing:
                continue
            t = pd.Timestamp(f'{year}-{month:02d}-01')
            if t not in df.index:
                raise KeyError(f'NOAA GML CSV lacks {t:%Y-%m}')
            delta = ref_avg[month] - float(df.loc[t, 'average'])
            new_map = (ref_maps[month] - delta).assign_coords(time=np.datetime64(t)).expand_dims('time')
            extended.append(new_map)

    pieces = [co2]
    if extended:
        pieces.append(xr.concat(extended, dim='time'))
    full = xr.concat(pieces, dim='time').sortby('time')
    full = full.sel(time=slice(f'{args.start_year}-01-01', f'{args.end_year}-12-31'))
    if full.sizes.get('time') != (args.end_year - args.start_year + 1) * 12:
        raise RuntimeError(f"Unexpected monthly length {full.sizes.get('time')}; expected {(args.end_year - args.start_year + 1) * 12}")

    annual = full.resample(time='YS').mean().astype('float32')
    annual = annual.assign_coords(year=annual.time.dt.year).swap_dims({'time':'year'}).drop_vars('time')
    annual.name = 'co2'
    annual.attrs.update({
        'long_name': 'Annual mean atmospheric CO2 mole fraction',
        'units': 'ppm',
        'source': 'CarbonTracker CT2022 monthly fields plus NOAA GML delta extension',
        'method': 'Monthly average offset: map(y,m) = map(2000,m) - (GML(2000,m) - GML(y,m)); annual mean from monthly fields.',
        'reference_year': 2000,
        'source_monthly_co2': str(args.monthly_co2),
        'source_gml_csv': str(args.gml_csv),
    })
    out = annual.to_dataset(name='co2')
    out.attrs.update({'profecia_derived':'true','temporal_resolution':'annual'})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_netcdf(args.output, encoding={'co2': {'zlib': True, 'complevel': 6, 'dtype': 'float32'}})
    print(f'Wrote {args.output}')
    print(f'Annual years: {int(annual.year[0])}-{int(annual.year[-1])}; shape={annual.shape}')

if __name__ == '__main__':
    main()
