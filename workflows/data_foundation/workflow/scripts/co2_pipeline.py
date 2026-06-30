"""
co2_pipeline.py
================
Producto base documentado:
    CarbonTracker CO2 CT2022
    Ruta NOAA:
    https://gml.noaa.gov/aftp/products/carbontracker/co2/CT2022/molefractions/co2_total_monthly/

Archivos esperados:
    CT2022.molefrac_glb3x2_YYYY-MM.nc

Producto mensual seleccionado:
    co2_total_monthly

Resolución original:
    - Temporal: mensual
    - Espacial: 3 grados longitud x 2 grados latitud
    - Variable principal: co2, con dimensiones típicas:
        time, level, latitude, longitude
    - Variable auxiliar necesaria para columna atmosférica:
        air_mass

Productos generados por este módulo:
    1. CO2 superficial: selección de un nivel vertical, normalmente level=0.
    2. CO2 de columna: media ponderada por masa de aire en todos los niveles.

Dependencias:
    pip install requests xarray netCDF4 numpy cftime
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np
import requests
import xarray as xr

DEFAULT_BASE_URL = (
    "https://gml.noaa.gov/aftp/products/carbontracker/co2/CT2022/"
    "molefractions/co2_total_monthly/"
)

DEFAULT_VERSION = "CT2022"
DEFAULT_GRID_TAG = "glb3x2"
DEFAULT_VARIABLE = "co2"
DEFAULT_AIR_MASS_VARIABLE = "air_mass"

# Rejilla global común del proyecto PROFECIA: 0.5 grados.
TARGET_LATITUDE = np.arange(89.5, -90.01, -0.5)      # 360 valores, norte -> sur
TARGET_LONGITUDE = np.arange(-180.0, 180.0, 0.5)     # 720 valores, oeste -> este

def _ensure_dir(path: str | Path) -> Path:
    """Crea un directorio si no existe y devuelve un objeto Path."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _compression_encoding(ds: xr.Dataset, complevel: int = 4) -> dict:
    """
    Devuelve un diccionario de compresión NetCDF para todas las variables.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset que se va a guardar.
    complevel : int
        Nivel de compresión zlib. Valores típicos: 1-9.
        - 1: más rápido, menos compresión.
        - 4: compromiso razonable.
        - 9: más compresión, más lento.
    """
    return {var: {"zlib": True, "complevel": complevel} for var in ds.data_vars}


def _standardize_lat_lon(ds: xr.Dataset) -> xr.Dataset:
    """
    Estandariza coordenadas espaciales:
    - Longitudes: de [0, 360) a [-180, 180), si hace falta.
    - Latitudes: orden norte -> sur.
    - Longitudes: orden oeste -> este.

    CarbonTracker suele venir con longitudes 0..360. Para combinarlo con LAI,
    ERA5 y máscaras en EPSG:4326, es más cómodo trabajar en [-180, 180).
    """
    if "longitude" not in ds.coords or "latitude" not in ds.coords:
        raise ValueError("El dataset debe contener coordenadas 'latitude' y 'longitude'.")

    if float(ds.longitude.max()) > 180.0:
        lon_new = ((ds.longitude + 180) % 360) - 180
        ds = ds.assign_coords(longitude=lon_new).sortby("longitude")

    if bool(ds.latitude[0] < ds.latitude[-1]):
        ds = ds.sortby("latitude", ascending=False)

    return ds


def _infer_year_month_from_filename(path: str | Path) -> tuple[Optional[int], Optional[int]]:
    """Extrae YYYY-MM de nombres tipo CT2022.molefrac_glb3x2_2000-01.nc."""
    match = re.search(r"(\d{4})-(\d{2})", Path(path).name)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))

def download_carbontracker_co2(
    output_dir: str | Path,
    start_year: int = 2000,
    end_year: int = 2005,
    months: Sequence[int] | None = None,
    base_url: str = DEFAULT_BASE_URL,
    version: str = DEFAULT_VERSION,
    grid_tag: str = DEFAULT_GRID_TAG,
    overwrite: bool = False,
    timeout: int = 60,
) -> list[Path]:
    """
    Descarga archivos mensuales de CarbonTracker CO2 desde NOAA GML.

    Parameters
    ----------
    output_dir : str | Path
        Carpeta donde se guardarán los NetCDF descargados.
    start_year, end_year : int
        Periodo temporal que se quiere descargar.
    months : sequence[int] | None
        Meses a descargar. Por defecto descarga enero-diciembre.
        Ejemplos:
            months=None              -> todos los meses
            months=[1, 2, 3]          -> enero, febrero, marzo
            months=range(1, 7)        -> enero-junio
    base_url : str
        URL base del producto. Cambia si se usa otra versión/producto.

    version : str
        Versión del producto. En la documentación se usa CT2022.
    grid_tag : str
        Etiqueta de rejilla incluida en el nombre del archivo. Para este producto:
            glb3x2 = global 3 grados x 2 grados.
    overwrite : bool
        Si False, no vuelve a descargar archivos ya existentes.
    timeout : int
        Tiempo máximo de espera por petición HTTP.

    Returns
    -------
    list[Path]
        Lista de archivos descargados o ya existentes.
    """
    outdir = _ensure_dir(output_dir)
    selected_months = list(months) if months is not None else list(range(1, 13))
    downloaded: list[Path] = []

    for year in range(start_year, end_year + 1):
        for month in selected_months:
            fname = f"{version}.molefrac_{grid_tag}_{year}-{month:02d}.nc"
            url = base_url.rstrip("/") + "/" + fname
            dest = outdir / fname

            if dest.exists() and not overwrite:
                print(f"Existe, se omite: {fname}")
                downloaded.append(dest)
                continue

            print(f"Descargando: {fname}")
            try:
                response = requests.get(url, stream=True, timeout=timeout)
            except requests.RequestException as exc:
                print(f"ERROR de conexión para {url}: {exc}")
                continue

            if response.status_code != 200:
                print(f"No disponible ({response.status_code}): {fname}")
                continue

            with open(dest, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

            downloaded.append(dest)
            print(f"Guardado: {dest}")

    return downloaded

def inspect_carbontracker_file(input_nc: str | Path) -> None:
    """
    Imprime estructura básica de un archivo CarbonTracker.
    """
    with xr.open_dataset(input_nc, engine="netcdf4") as ds:
        print(ds)
        print("\nVariables:")
        for var in ds.data_vars:
            print(f"- {var}: dims={ds[var].dims}, shape={ds[var].shape}, units={ds[var].attrs.get('units')}")

def clean_carbontracker_files(
    input_dir: str | Path,
    output_dir: str | Path,
    keep_variables: Sequence[str] = (DEFAULT_VARIABLE, DEFAULT_AIR_MASS_VARIABLE),
    complevel: int = 4,
) -> list[Path]:
    """
    Limpia archivos mensuales de CarbonTracker conservando solo variables necesarias.

    Parameters
    ----------
    input_dir : str | Path
        Carpeta con archivos originales CT2022.molefrac_glb3x2_YYYY-MM.nc.
    output_dir : str | Path
        Carpeta de salida.
    keep_variables : sequence[str]
        Variables a conservar.
        - Para CO2 superficial basta con ('co2',).
        - Para CO2 de columna hace falta ('co2', 'air_mass').
    complevel : int
        Nivel de compresión NetCDF.

    Returns
    -------
    list[Path]
        Archivos limpios generados.
    """
    input_dir = Path(input_dir)
    output_dir = _ensure_dir(output_dir)
    files = sorted(input_dir.glob("CT*.molefrac_*_*.nc"))

    if not files:
        raise FileNotFoundError(f"No se encontraron archivos CarbonTracker en {input_dir}")

    outputs: list[Path] = []

    for file in files:
        print(f"Limpiando: {file.name}")
        with xr.open_dataset(file, engine="netcdf4") as ds:
            missing = [v for v in keep_variables if v not in ds.data_vars]
            if missing:
                print(f"  Se omite: faltan variables {missing}")
                continue

            ds_out = ds[list(keep_variables)]
            ds_out = _standardize_lat_lon(ds_out)

            # Normaliza nombre/orden temporal si el dataset tiene time.
            if "time" in ds_out.coords:
                ds_out = ds_out.sortby("time")

            ds_out.attrs.update(ds.attrs)
            ds_out.attrs["processing_note"] = (
                "Cleaned CarbonTracker file: selected required variables and "
                "standardized latitude/longitude coordinates."
            )

            out_path = output_dir / f"{file.stem}_clean.nc"
            ds_out.to_netcdf(out_path, engine="netcdf4", encoding=_compression_encoding(ds_out, complevel))
            outputs.append(out_path)
            print(f"  Guardado: {out_path.name}")

    return outputs

def merge_co2_monthly(
    input_dir: str | Path,
    output_file: str | Path,
    variables: Sequence[str] = (DEFAULT_VARIABLE, DEFAULT_AIR_MASS_VARIABLE),
    pattern: str = "CT*.molefrac_*_*.nc",
    complevel: int = 4,
) -> Path:
    """
    Combina archivos mensuales de CarbonTracker en un único NetCDF multitemporal.

    Parameters
    ----------
    input_dir : str | Path
        Carpeta con archivos mensuales originales o limpios.
    output_file : str | Path
        Archivo NetCDF final combinado.
    variables : sequence[str]
        Variables que se conservarán.
        - ('co2', 'air_mass') permite generar superficie y columna.
        - ('co2',) reduce tamaño si solo se quiere CO2 superficial.
    pattern : str
        Patrón de búsqueda. Si usas archivos limpios, puede ser '*_clean.nc'.
    complevel : int
        Nivel de compresión.

    Returns
    -------
    Path
        Ruta del archivo combinado.
    """
    input_dir = Path(input_dir)
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No se encontraron archivos con patrón {pattern} en {input_dir}")

    print(f"Combinando {len(files)} archivos CarbonTracker...")

    datasets = []
    for file in files:
        ds = xr.open_dataset(file, engine="netcdf4")
        available = [v for v in variables if v in ds.data_vars]
        if not available:
            ds.close()
            print(f"  Se omite {file.name}: no contiene variables requeridas.")
            continue
        ds = ds[available]
        ds = _standardize_lat_lon(ds)
        datasets.append(ds)

    if not datasets:
        raise ValueError("No se pudo abrir ningún dataset válido.")

    try:
        combined = xr.concat(datasets, dim="time")
        combined = combined.sortby("time")
        combined.attrs.update({
            "product": "CarbonTracker CO2 monthly merged dataset",
            "source_file_count": len(datasets),
            "processing_note": "Monthly files concatenated along time dimension.",
        })

        combined.to_netcdf(
            output_file,
            engine="netcdf4",
            format="NETCDF4",
            encoding=_compression_encoding(combined, complevel),
        )
        print(f"Guardado combinado mensual: {output_file}")
    finally:
        for ds in datasets:
            ds.close()
        if "combined" in locals():
            combined.close()

    return output_file

def extract_co2_surface(
    input_nc: str | Path,
    output_nc: str | Path,
    level: int = 0,
    variable: str = DEFAULT_VARIABLE,
    output_variable: str = "co2_surface",
    complevel: int = 4,
) -> Path:
    """
    Extrae CO2 de un nivel vertical concreto.

    Parameters
    ----------
    input_nc : str | Path
        Dataset mensual combinado con variable co2 y dimensión level.
    output_nc : str | Path
        Archivo de salida.
    level : int
        Índice del nivel vertical.
        - level=0 suele representar aire cercano a superficie.
        - Otros niveles pueden explorarse si se justifica físicamente.
    variable : str
        Nombre de la variable de CO2 en el NetCDF. Normalmente 'co2'.
    output_variable : str
        Nombre de la variable en el archivo final.
    complevel : int
        Nivel de compresión.

    Returns
    -------
    Path
        Ruta del archivo generado.
    """
    input_nc = Path(input_nc)
    output_nc = Path(output_nc)
    output_nc.parent.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(input_nc, engine="netcdf4") as ds:
        if variable not in ds.data_vars:
            raise KeyError(f"No existe la variable '{variable}' en {input_nc}")
        if "level" not in ds[variable].dims:
            raise ValueError(f"La variable '{variable}' no tiene dimensión 'level'.")
        if level < 0 or level >= ds.sizes["level"]:
            raise IndexError(f"level={level} fuera de rango. Máximo: {ds.sizes['level'] - 1}")

        da = ds[variable].isel(level=level, drop=True).astype("float32")
        da.name = output_variable
        da.attrs.update(ds[variable].attrs)
        da.attrs["long_name"] = f"Surface or selected-level CO2 mole fraction, level index {level}"
        da.attrs["selected_level_index"] = int(level)
        da.attrs["source_variable"] = variable

        ds_out = da.to_dataset()
        ds_out.attrs.update(ds.attrs)
        ds_out.attrs["product"] = "CarbonTracker CO2 selected vertical level"
        ds_out.attrs["vertical_level_selected"] = int(level)

        ds_out.to_netcdf(output_nc, engine="netcdf4", encoding=_compression_encoding(ds_out, complevel))
        ds_out.close()

    print(f"Guardado CO2 nivel {level}: {output_nc}")
    return output_nc

def compute_co2_column_weighted(
    input_nc: str | Path,
    output_nc: str | Path,
    variable: str = DEFAULT_VARIABLE,
    air_mass_variable: str = DEFAULT_AIR_MASS_VARIABLE,
    output_variable: str = "co2_column",
    complevel: int = 4,
) -> Path:
    """
    Calcula CO2 medio de columna mediante ponderación por masa de aire.

    Fórmula:
        CO2_column = sum(co2_level * air_mass_level) / sum(air_mass_level)

    Parameters
    ----------
    input_nc : str | Path
        Dataset mensual combinado con co2 y air_mass.
    output_nc : str | Path
        Archivo de salida.
    variable : str
        Variable de CO2. Normalmente 'co2'.
    air_mass_variable : str
        Variable de masa de aire. Normalmente 'air_mass'.
    output_variable : str
        Nombre de la variable final.
    complevel : int
        Nivel de compresión.

    Returns
    -------
    Path
        Ruta del archivo generado.
    """
    input_nc = Path(input_nc)
    output_nc = Path(output_nc)
    output_nc.parent.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(input_nc, engine="netcdf4") as ds:
        if variable not in ds.data_vars:
            raise KeyError(f"No existe la variable '{variable}' en {input_nc}")
        if air_mass_variable not in ds.data_vars:
            raise KeyError(f"No existe la variable '{air_mass_variable}' en {input_nc}")
        if "level" not in ds[variable].dims:
            raise ValueError(f"La variable '{variable}' no tiene dimensión 'level'.")

        co2 = ds[variable]
        air = ds[air_mass_variable]
        co2, air = xr.align(co2, air, join="exact")

        weighted = ((co2 * air).sum(dim="level") / air.sum(dim="level")).astype("float32")
        weighted.name = output_variable
        weighted.attrs.update(co2.attrs)
        weighted.attrs["long_name"] = "Column-averaged CO2 mole fraction, air-mass weighted"
        weighted.attrs["source_variables"] = f"{variable}, {air_mass_variable}"
        weighted.attrs["vertical_aggregation"] = "air-mass weighted mean over level"

        ds_out = weighted.to_dataset()
        ds_out.attrs.update(ds.attrs)
        ds_out.attrs["product"] = "CarbonTracker CO2 column air-mass weighted"

        ds_out.to_netcdf(output_nc, engine="netcdf4", encoding=_compression_encoding(ds_out, complevel))
        ds_out.close()

    print(f"Guardado CO2 columna ponderada: {output_nc}")
    return output_nc

def regrid_co2_to_05deg(
    input_nc: str | Path,
    output_nc: str | Path,
    method: str = "linear",
    extrapolate: bool = True,
    complevel: int = 4,
) -> Path:
    """
    Remalla un producto CO2 2D+tiempo a la rejilla global 0.5 grados.

    Parameters
    ----------
    input_nc : str | Path
        NetCDF de entrada. Debe tener coordenadas latitude y longitude.
        Normalmente será la salida de:
            - extract_co2_surface
            - compute_co2_column_weighted
    output_nc : str | Path
        Archivo de salida.
    method : str
        Método de interpolación de xarray.interp.
        Opciones habituales:
            - 'linear': bilineal en lat/lon. Recomendado para CO2.
            - 'nearest': vecino más cercano. Útil para pruebas, no ideal aquí.
    extrapolate : bool
        Si True, permite extrapolar bordes para completar la rejilla global.
        En una malla global suele evitar NaN marginales.
    complevel : int
        Nivel de compresión.

    Returns
    -------
    Path
        Ruta del archivo remallado.
    """
    input_nc = Path(input_nc)
    output_nc = Path(output_nc)
    output_nc.parent.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(input_nc, engine="netcdf4") as ds:
        ds = _standardize_lat_lon(ds)

        interp_kwargs = {"fill_value": "extrapolate"} if extrapolate else None
        ds_out = ds.interp(
            latitude=TARGET_LATITUDE,
            longitude=TARGET_LONGITUDE,
            method=method,
            kwargs=interp_kwargs,
        )

        # Asegura float32 para reducir tamaño, suficiente para este uso.
        for var in ds_out.data_vars:
            if np.issubdtype(ds_out[var].dtype, np.floating):
                ds_out[var] = ds_out[var].astype("float32")

        ds_out.attrs.update(ds.attrs)
        ds_out.attrs["spatial_resolution"] = "0.5 degree"
        ds_out.attrs["target_grid"] = "latitude 89.5..-90.0; longitude -180.0..179.5"
        ds_out.attrs["interpolation"] = f"xarray.interp method={method}"

        ds_out.to_netcdf(output_nc, engine="netcdf4", encoding=_compression_encoding(ds_out, complevel))
        ds_out.close()

    print(f"Guardado CO2 remallado a 0.5 grados: {output_nc}")
    return output_nc

def compute_annual_co2(
    monthly_nc: str | Path,
    output_nc: str | Path,
    aggregation: str = "mean",
    complevel: int = 4,
) -> Path:
    """
    Convierte un producto mensual de CO2 en anual.

    Parameters
    ----------
    monthly_nc : str | Path
        Archivo mensual, idealmente ya remallado a 0.5 grados.
    output_nc : str | Path
        Archivo anual de salida.
    aggregation : str
        Tipo de agregación anual.
        Opciones:
            - 'mean': media anual. Recomendado para concentración de CO2.
            - 'median': mediana anual. Robusta, pero menos estándar.
    complevel : int
        Nivel de compresión.

    Returns
    -------
    Path
        Ruta del archivo anual.
    """
    monthly_nc = Path(monthly_nc)
    output_nc = Path(output_nc)
    output_nc.parent.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(monthly_nc, engine="netcdf4") as ds:
        if "time" not in ds.coords and "time" not in ds.dims:
            raise ValueError("El dataset no tiene dimensión/coordenada temporal 'time'.")

        if aggregation == "mean":
            ds_annual = ds.resample(time="YS").mean(keep_attrs=True)
        elif aggregation == "median":
            ds_annual = ds.resample(time="YS").median(keep_attrs=True)
        else:
            raise ValueError("aggregation debe ser 'mean' o 'median'.")

        ds_annual.attrs.update(ds.attrs)
        ds_annual.attrs["temporal_resolution"] = "annual"
        ds_annual.attrs["annual_aggregation"] = aggregation

        ds_annual.to_netcdf(output_nc, engine="netcdf4", encoding=_compression_encoding(ds_annual, complevel))
        ds_annual.close()

    print(f"Guardado CO2 anual: {output_nc}")
    return output_nc
