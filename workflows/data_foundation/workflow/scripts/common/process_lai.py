#!/usr/bin/env python3
"""Process local THEIA GEOV2-GCM AVHRR LAI H5.GZ files to PROFECIA monthly NetCDF."""
from __future__ import annotations
import argparse, gzip, re, shutil, tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import h5py
import numpy as np
import pandas as pd
import xarray as xr

LAT=np.linspace(89.5,-90.0,360).astype('float32')
LON=np.linspace(-180.0,179.5,720).astype('float32')
PATTERN='THEIA_GEOV2-GCM_*_LAI_*.h5.gz'

def date_of(p: Path):
    m=re.search(r'(\d{8})', p.name)
    if not m: raise ValueError(f'No YYYYMMDD in {p}')
    return datetime.strptime(m.group(1),'%Y%m%d')

def find_lai(handle):
    for cand in ('LAI','/LAI/LAI','Data/LAI','AVHRR_LAI'):
        if cand in handle: return np.asarray(handle[cand])
    found=None
    def visitor(name,obj):
        nonlocal found
        if found is None and isinstance(obj,h5py.Dataset) and 'LAI' in name.upper(): found=np.asarray(obj)
    handle.visititems(visitor)
    if found is None: raise KeyError('LAI dataset not found')
    return found

def read_gz(path: Path, tmp: Path):
    h5=tmp/path.with_suffix('').name
    with gzip.open(path,'rb') as fin, h5.open('wb') as fout: shutil.copyfileobj(fin,fout)
    with h5py.File(h5,'r') as handle:
        dn=find_lai(handle)
    h5.unlink(missing_ok=True)
    lai=np.where((dn>=0)&(dn<=210), dn/30.0, np.nan).astype('float32')
    if lai.shape != (360,720): raise ValueError(f'{path.name} shape {lai.shape} != (360,720)')
    return xr.DataArray(lai,dims=('latitude','longitude'),coords={'latitude':LAT,'longitude':LON},name='lai')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-dir',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--start-year',type=int,default=1982)
    ap.add_argument('--end-year',type=int,default=2022)
    args=ap.parse_args()
    files=sorted(args.input_dir.glob(PATTERN))
    groups=defaultdict(list)
    for f in files:
        d=date_of(f)
        if args.start_year <= d.year <= args.end_year:
            groups[(d.year,d.month)].append(f)
    if not groups: raise FileNotFoundError(f'No LAI files in {args.input_dir}')
    arrays=[]; times=[]
    with tempfile.TemporaryDirectory(prefix='profecia_lai_') as td:
        tmp=Path(td)
        for ym in sorted(groups):
            comps=[read_gz(f,tmp) for f in sorted(groups[ym])]
            month=xr.concat(comps, dim='composite').mean('composite', skipna=True).astype('float32')
            arrays.append(month)
            times.append(pd.Timestamp(year=ym[0],month=ym[1],day=1))
            print(f'Processed LAI {ym[0]}-{ym[1]:02d}: {len(comps)} composites')
    ds=xr.concat(arrays, dim=pd.Index(times,name='time')).to_dataset(name='lai')
    ds['lai'].attrs.update({'long_name':'Leaf Area Index','units':'m2 m-2','valid_min':0.0,'valid_max':7.0,'formula':'LAI = DN / 30; invalid DN outside [0,210] set to NaN','source_product':'THEIA GEOV2-GCM AVHRR LAI'})
    ds.attrs.update({'profecia_repackaged':'true','processing':'Monthly mean of available 10-day GEOV2-GCM AVHRR LAI composites','source_directory':str(args.input_dir)})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    ds.to_netcdf(args.output, encoding={'lai':{'zlib':True,'complevel':4,'dtype':'float32'}})
    print(f'Wrote {args.output}')
if __name__=='__main__': main()
