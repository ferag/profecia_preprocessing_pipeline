"""
- Fuente: THEIA GEOV2-GCM AVHRR LAI.
- Formato original: `.h5.gz`.
- Frecuencia original: composiciones de 10 días, normalmente días 05, 15 y 25.
- Resolución usada en este proyecto: 0.5° global.
- Periodo de trabajo recomendado: 1982-2022.
- Conversión física: LAI = DN / 30.
- Rango válido físico: 0 <= LAI <= 7.
- Rango válido DN: 0 <= DN <= 210.

Dependencias
------------
pip install numpy pandas xarray h5py netCDF4

"""

from __future__ import annotations

import gzip
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence

import h5py
import numpy as np
import pandas as pd
import xarray as xr

DEFAULT_INPUT_PATTERN = "THEIA_GEOV2-GCM_*_LAI_*.h5.gz"
DEFAULT_VARIABLE_CANDIDATES = ("LAI", "/LAI/LAI", "Data/LAI", "AVHRR_LAI")

DEFAULT_START_YEAR = 1982
DEFAULT_END_YEAR = 2022

# Malla global 0.5° usada en PROFECIA.
DEFAULT_LATITUDES = np.linspace(89.5, -90.0, 360).astype("float32")
DEFAULT_LONGITUDES = np.linspace(-180.0, 179.5, 720).astype("float32")

# Conversión física del producto GEOV2-GCM AVHRR LAI.
DEFAULT_SCALING_FACTOR = 30.0
DEFAULT_VALID_DN_MIN = 0
DEFAULT_VALID_DN_MAX = 210
DEFAULT_VALID_LAI_MIN = 0.0
DEFAULT_VALID_LAI_MAX = 7.0

def ensure_dir(path: str | Path) -> Path:
    """Crea un directorio si no existe y devuelve un objeto Path."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def extract_date_from_filename(filename: str | Path) -> datetime:
    """
    Extrae una fecha YYYYMMDD desde el nombre de archivo THEIA.
    """
    filename = Path(filename).name
    match = re.search(r"(\d{8})", filename)
    if not match:
        raise ValueError(f"No se pudo extraer fecha YYYYMMDD del archivo: {filename}")
    return datetime.strptime(match.group(1), "%Y%m%d")


def filter_files_by_year(
    files: Sequence[Path],
    start_year: Optional[int] = DEFAULT_START_YEAR,
    end_year: Optional[int] = DEFAULT_END_YEAR,
) -> list[Path]:
    """
    Filtra archivos por año usando la fecha contenida en el nombre.

    Usa `start_year=None` y `end_year=None` para filtrar.
    """
    selected: list[Path] = []
    for file in files:
        date = extract_date_from_filename(file.name)
        if start_year is not None and date.year < start_year:
            continue
        if end_year is not None and date.year > end_year:
            continue
        selected.append(file)
    return selected

def unzip_h5gz(gzip_file: str | Path, output_dir: str | Path, overwrite: bool = False) -> Path:
    """
    Descomprime un archivo `.h5.gz` a `.h5`.

    Parámetros
    ----------
    gzip_file:
        Ruta al archivo comprimido original.
    output_dir:
        Carpeta donde se guardará el `.h5` temporal o permanente.
    overwrite:
        Si True, vuelve a descomprimir aunque el `.h5` ya exista.

    Devuelve
    --------
    Path al archivo `.h5` descomprimido.
    """
    gzip_file = Path(gzip_file)
    output_dir = ensure_dir(output_dir)

    # `.with_suffix("")` elimina solo el último sufijo: .gz -> queda .h5
    output_file = output_dir / gzip_file.with_suffix("").name

    if output_file.exists() and not overwrite:
        return output_file

    with gzip.open(gzip_file, "rb") as f_in, open(output_file, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    return output_file


def inspect_hdf5_structure(h5_file: str | Path) -> list[str]:
    """
    Lista la estructura interna de un HDF5.
    Devuelve una lista con las rutas internas encontradas.
    """
    h5_file = Path(h5_file)
    paths: list[str] = []

    def visitor(name: str, obj) -> None:  # h5py usa una callback sin tipado estable.
        kind = "dataset" if isinstance(obj, h5py.Dataset) else "group"
        shape = getattr(obj, "shape", "")
        dtype = getattr(obj, "dtype", "")
        paths.append(f"{kind}: /{name} shape={shape} dtype={dtype}")

    with h5py.File(h5_file, "r") as handle:
        handle.visititems(visitor)

    return paths


def _find_dataset_recursive(handle: h5py.File | h5py.Group, keyword: str = "LAI") -> Optional[h5py.Dataset]:
    """Busca recursivamente el primer dataset cuyo nombre contenga `keyword`."""
    keyword = keyword.upper()
    found: Optional[h5py.Dataset] = None

    def visitor(name: str, obj) -> None:
        nonlocal found
        if found is not None:
            return
        if isinstance(obj, h5py.Dataset) and keyword in name.upper():
            found = obj

    handle.visititems(visitor)
    return found


def read_lai_raw_data(
    h5_file: h5py.File,
    variable_candidates: Sequence[str] = DEFAULT_VARIABLE_CANDIDATES,
    recursive_keyword: str = "LAI",
) -> np.ndarray:
    """
    Lee la matriz LAI en valores digitales DN desde un HDF5 abierto.
    """
    for candidate in variable_candidates:
        if candidate in h5_file:
            return np.asarray(h5_file[candidate])

    dataset = _find_dataset_recursive(h5_file, keyword=recursive_keyword)
    if dataset is not None:
        return np.asarray(dataset)

    raise KeyError(
        "No se encontró ninguna variable LAI en el HDF5. "
        "Usa inspect_hdf5_structure() para revisar la estructura interna."
    )

def convert_to_physical_lai(
    dn_array: np.ndarray,
    scaling_factor: float = DEFAULT_SCALING_FACTOR,
    valid_dn_min: int | float = DEFAULT_VALID_DN_MIN,
    valid_dn_max: int | float = DEFAULT_VALID_DN_MAX,
    output_dtype: str = "float32",
) -> np.ndarray:
    """
    Convierte LAI desde valores digitales DN a unidades físicas.

    Fórmula del producto GEOV2-GCM
    ------------------------------
    LAI = DN / 30

    Valores fuera del rango DN válido se convierten a NaN.
    """
    dn = np.asarray(dn_array)
    valid_mask = (dn >= valid_dn_min) & (dn <= valid_dn_max)
    lai = np.where(valid_mask, dn / scaling_factor, np.nan)
    return lai.astype(output_dtype)


def validate_lai_grid_shape(
    array: np.ndarray,
    latitudes: np.ndarray = DEFAULT_LATITUDES,
    longitudes: np.ndarray = DEFAULT_LONGITUDES,
) -> None:
    """
    Verifica que la matriz LAI coincide con la malla espacial esperada.
    Para 0.5° global se espera `(360, 720)`.
    """
    expected = (len(latitudes), len(longitudes))
    if array.shape != expected:
        raise ValueError(
            f"Shape espacial inesperada: {array.shape}. Esperado: {expected}. "
            "Comprueba si el producto es 0.5° o 0.05°, o si hay que transponer la matriz."
        )

def group_files_by_month(
    input_dir: str | Path,
    input_pattern: str = DEFAULT_INPUT_PATTERN,
    start_year: Optional[int] = DEFAULT_START_YEAR,
    end_year: Optional[int] = DEFAULT_END_YEAR,
) -> dict[str, list[Path]]:
    """
    Agrupa archivos `.h5.gz` por mes usando la fecha del nombre.

    Devuelve
    --------
    Diccionario `{YYYY-MM: [archivos decadales del mes]}`.
    """
    input_dir = Path(input_dir)
    files = sorted(input_dir.glob(input_pattern))
    files = filter_files_by_year(files, start_year=start_year, end_year=end_year)

    grouped: dict[str, list[Path]] = defaultdict(list)
    for file in files:
        date = extract_date_from_filename(file.name)
        grouped[date.strftime("%Y-%m")].append(file)

    return dict(grouped)


def compute_monthly_lai(
    file_group: Sequence[str | Path],
    output_dir: str | Path,
    temp_dir: Optional[str | Path] = None,
    latitudes: np.ndarray = DEFAULT_LATITUDES,
    longitudes: np.ndarray = DEFAULT_LONGITUDES,
    variable_candidates: Sequence[str] = DEFAULT_VARIABLE_CANDIDATES,
    scaling_factor: float = DEFAULT_SCALING_FACTOR,
    valid_dn_min: int | float = DEFAULT_VALID_DN_MIN,
    valid_dn_max: int | float = DEFAULT_VALID_DN_MAX,
    remove_temp_h5: bool = True,
    overwrite: bool = False,
) -> Path:
    """
    Calcula un archivo mensual NetCDF a partir de composiciones decadales HDF5.
    """
    if not file_group:
        raise ValueError("file_group está vacío; no hay composiciones para agregar.")

    output_dir = ensure_dir(output_dir)
    temp_dir = ensure_dir(temp_dir or output_dir / "_tmp_h5")

    file_group = [Path(file) for file in file_group]
    ref_date = extract_date_from_filename(file_group[0].name)
    output_file = output_dir / f"GEOV2_GCM_LAI_monthly_{ref_date.strftime('%Y_%m')}.nc"

    if output_file.exists() and not overwrite:
        print(f"Archivo mensual ya existe: {output_file.name}")
        return output_file

    arrays: list[xr.DataArray] = []
    timestamps: list[datetime] = []
    temp_files: list[Path] = []

    for gz_file in sorted(file_group):
        h5_path = unzip_h5gz(gz_file, temp_dir, overwrite=overwrite)
        temp_files.append(h5_path)

        date = extract_date_from_filename(gz_file.name)
        timestamps.append(date)

        with h5py.File(h5_path, "r") as handle:
            raw_dn = read_lai_raw_data(handle, variable_candidates=variable_candidates)
            lai = convert_to_physical_lai(
                raw_dn,
                scaling_factor=scaling_factor,
                valid_dn_min=valid_dn_min,
                valid_dn_max=valid_dn_max,
            )

        validate_lai_grid_shape(lai, latitudes=latitudes, longitudes=longitudes)

        da = xr.DataArray(
            lai,
            name="LAI",
            dims=("latitude", "longitude"),
            coords={"latitude": latitudes, "longitude": longitudes},
            attrs={
                "long_name": "Leaf Area Index",
                "units": "m2 m-2",
                "valid_min": DEFAULT_VALID_LAI_MIN,
                "valid_max": DEFAULT_VALID_LAI_MAX,
                "comment": f"LAI = DN / {scaling_factor}; invalid DN set to NaN.",
            },
        )
        arrays.append(da)

    stack = xr.concat(arrays, dim=pd.Index(timestamps, name="time"))
    monthly = stack.mean(dim="time", skipna=True).to_dataset(name="LAI")

    monthly.attrs.update(
        {
            "title": "GEOV2-GCM AVHRR LAI monthly product",
            "processing_level": "Monthly aggregated from 10-day composites",
            "aggregation_method": "Mean of available 10-day composites within each month",
            "source_product": "THEIA GEOV2-GCM AVHRR LAI",
            "source_files": ", ".join(file.name for file in file_group),
            "spatial_resolution": "0.5 degree",
            "crs": "EPSG:4326",
            "creation_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
        }
    )

    encoding = {"LAI": {"zlib": True, "complevel": 4, "dtype": "float32"}}
    monthly.to_netcdf(output_file, format="NETCDF4", engine="netcdf4", encoding=encoding)
    monthly.close()
    stack.close()

    if remove_temp_h5:
        for temp_file in temp_files:
            try:
                temp_file.unlink(missing_ok=True)
            except Exception as exc:
                print(f"Aviso: no se pudo eliminar temporal {temp_file}: {exc}")

    print(f"Guardado mensual: {output_file.name}")
    return output_file


def process_monthly_lai(
    input_dir: str | Path,
    output_dir: str | Path,
    input_pattern: str = DEFAULT_INPUT_PATTERN,
    start_year: Optional[int] = DEFAULT_START_YEAR,
    end_year: Optional[int] = DEFAULT_END_YEAR,
    overwrite: bool = False,
) -> list[Path]:
    """
    Procesa todos los `.h5.gz` de una carpeta y crea archivos mensuales NetCDF.
    """
    groups = group_files_by_month(
        input_dir=input_dir,
        input_pattern=input_pattern,
        start_year=start_year,
        end_year=end_year,
    )

    if not groups:
        raise FileNotFoundError(
            f"No se encontraron archivos con patrón {input_pattern} en {input_dir}."
        )

    outputs: list[Path] = []
    for month_key, files in sorted(groups.items()):
        print(f"Procesando {month_key}: {len(files)} composiciones")
        out = compute_monthly_lai(files, output_dir=output_dir, overwrite=overwrite)
        outputs.append(out)

    return outputs

def merge_monthly_files(
    monthly_dir: str | Path,
    output_nc: str | Path,
    start_year: Optional[int] = DEFAULT_START_YEAR,
    end_year: Optional[int] = DEFAULT_END_YEAR,
    overwrite: bool = False,
) -> Path:
    """
    Fusiona archivos mensuales `GEOV2_GCM_LAI_monthly_YYYY_MM.nc` en un solo NetCDF.
    """
    monthly_dir = Path(monthly_dir)
    output_nc = Path(output_nc)
    ensure_dir(output_nc.parent)

    if output_nc.exists() and not overwrite:
        print(f"Archivo mensual global ya existe: {output_nc.name}")
        return output_nc

    files = sorted(monthly_dir.glob("GEOV2_GCM_LAI_monthly_*.nc"))
    if not files:
        raise FileNotFoundError(f"No hay archivos mensuales en {monthly_dir}")

    selected_files: list[Path] = []
    timestamps: list[pd.Timestamp] = []

    for file in files:
        match = re.search(r"monthly_(\d{4})_(\d{2})", file.name)
        if not match:
            print(f"Aviso: se omite archivo con nombre no estándar: {file.name}")
            continue

        year, month = map(int, match.groups())
        if start_year is not None and year < start_year:
            continue
        if end_year is not None and year > end_year:
            continue

        selected_files.append(file)
        timestamps.append(pd.Timestamp(year=year, month=month, day=1))

    if not selected_files:
        raise FileNotFoundError("No quedan archivos mensuales tras aplicar el filtro temporal.")

    arrays: list[xr.DataArray] = []
    opened: list[xr.Dataset] = []
    try:
        for file in selected_files:
            ds = xr.open_dataset(file, engine="netcdf4")
            opened.append(ds)
            arrays.append(ds["LAI"])

        lai = xr.concat(arrays, dim=pd.Index(timestamps, name="time")).to_dataset(name="LAI")
        lai = lai.sortby("time")

        lai.attrs.update(
            {
                "title": "GEOV2-GCM AVHRR LAI - Global monthly time series",
                "source_product": "THEIA GEOV2-GCM AVHRR LAI",
                "temporal_resolution": "monthly",
                "spatial_resolution": "0.5 degree",
                "period": f"{timestamps[0].year}-{timestamps[-1].year}",
                "crs": "EPSG:4326",
                "creation_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
            }
        )
        lai["LAI"].attrs.update(
            {
                "long_name": "Leaf Area Index",
                "units": "m2 m-2",
                "valid_min": DEFAULT_VALID_LAI_MIN,
                "valid_max": DEFAULT_VALID_LAI_MAX,
            }
        )

        encoding = {"LAI": {"zlib": True, "complevel": 4, "dtype": "float32"}}
        lai.to_netcdf(output_nc, format="NETCDF4", engine="netcdf4", encoding=encoding)
        lai.close()
    finally:
        for ds in opened:
            ds.close()

    print(f"Archivo mensual global creado: {output_nc}")
    return output_nc
