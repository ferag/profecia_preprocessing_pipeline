"""
Fuente:
    SPEIbase v2.11, CSIC
    https://spei.csic.es

Producto:
    Standardized Precipitation-Evapotranspiration Index, SPEI.

Escalas disponibles:
    spei01, spei02, spei03, spei06, spei09, spei12, spei24

Dependencias:
    pip install requests xarray netCDF4 numpy pandas
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np
import requests
import xarray as xr

SPEI_BASE_URL = "https://spei.csic.es/spei_database_2_11/nc/"

# Escalas oficialmente disponibles en SPEIbase v2.11 según la documentación usada.
VALID_SPEI_SCALES = (1, 2, 3, 6, 9, 12, 24)

# Malla común del proyecto PROFECIA / ERA5 / LAI.
# Se usa latitud descendente en los archivos finales para mantener convención N -> S.
TARGET_LAT_DESC = np.arange(89.5, -90.01, -0.5, dtype="float32")
TARGET_LON_ASC = np.arange(-180.0, 180.0, 0.5, dtype="float32")

def _ensure_dir(path: Path | str) -> Path:
    """Crea un directorio si no existe y devuelve el objeto Path."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalise_scale(scale: int | str) -> str:
    """
    Normaliza una escala SPEI a dos dígitos.
    
    Raises
    ------
    ValueError
        Si la escala no está entre las disponibles.
    """
    scale_int = int(scale)
    if scale_int not in VALID_SPEI_SCALES:
        raise ValueError(
            f"Escala SPEI no válida: {scale}. "
            f"Escalas disponibles: {VALID_SPEI_SCALES}"
        )
    return f"{scale_int:02d}"


def _detect_lat_lon_names(ds: xr.Dataset) -> tuple[str, str]:
    """
    Detecta los nombres de coordenadas espaciales en un Dataset SPEI.
    """
    lat_name = next((name for name in ("latitude", "lat") if name in ds.coords), None)
    lon_name = next((name for name in ("longitude", "lon") if name in ds.coords), None)

    if lat_name is None or lon_name is None:
        raise ValueError(
            "No se han podido detectar las coordenadas espaciales. "
            "Se esperaban coordenadas lat/lon o latitude/longitude."
        )

    return lat_name, lon_name


def _standardise_spatial_names(ds: xr.Dataset) -> xr.Dataset:
    """
    Renombra coordenadas espaciales a la convención del proyecto:
    `latitude`, `longitude`.
    """
    lat_name, lon_name = _detect_lat_lon_names(ds)
    rename_dict = {}

    if lat_name != "latitude":
        rename_dict[lat_name] = "latitude"
    if lon_name != "longitude":
        rename_dict[lon_name] = "longitude"

    if rename_dict:
        ds = ds.rename(rename_dict)

    return ds


def _detect_main_variable(ds: xr.Dataset, preferred: str = "spei") -> str:
    """
    Detecta la variable principal de un NetCDF SPEI.
    """
    if preferred in ds.data_vars:
        return preferred

    candidates = [var for var in ds.data_vars if var.lower() not in {"crs"}]
    if not candidates:
        raise ValueError("No se ha encontrado ninguna variable de datos SPEI.")

    if len(candidates) > 1:
        print(
            "Aviso: se han detectado varias variables de datos. "
            f"Se usará la primera: {candidates[0]}. Variables: {candidates}"
        )

    return candidates[0]


def _compression_encoding(ds: xr.Dataset, complevel: int = 4) -> dict:
    """Devuelve codificación NetCDF comprimida para todas las variables de datos."""
    return {var: {"zlib": True, "complevel": complevel} for var in ds.data_vars}


def _scale_from_filename(path: Path) -> Optional[str]:
    """Extrae la escala SPEI desde nombres tipo spei03_1982_2022_monthly_0.5deg.nc."""
    match = re.search(r"spei(\d{2})", path.name.lower())
    if match:
        return match.group(1)
    return None

def download_spei(
    output_dir: Path | str,
    scales: Sequence[int | str] = VALID_SPEI_SCALES,
    base_url: str = SPEI_BASE_URL,
    start_year: int = 1901,
    end_year: int = 2023,
    overwrite: bool = False,
    timeout: int = 120,
) -> list[Path]:
    """
    Descarga archivos SPEIbase v2.11 desde CSIC.

    Parameters
    ----------
    output_dir : Path | str
        Directorio donde se guardarán los NetCDF descargados.

    scales : Sequence[int | str]
        Escalas SPEI a descargar. Valores posibles:
        1, 2, 3, 6, 9, 12, 24.

    base_url : str
        URL base del repositorio NetCDF de SPEIbase.

    start_year, end_year : int
        Solo afectan al nombre de salida. Los archivos originales de SPEIbase
        v2.11 cubren 1901-2023.

    overwrite : bool
        Si False, no descarga de nuevo un archivo que ya exista.

    timeout : int
        Tiempo máximo de espera por petición HTTP.

    Returns
    -------
    list[Path]
        Rutas de los archivos descargados o ya existentes.
    """
    output_dir = _ensure_dir(output_dir)
    downloaded_files: list[Path] = []

    for scale in scales:
        scale_str = _normalise_scale(scale)
        source_name = f"spei{scale_str}.nc"
        output_name = f"spei{scale_str}_{start_year}_{end_year}_monthly_0.5deg.nc"
        url = base_url.rstrip("/") + "/" + source_name
        output_path = output_dir / output_name

        if output_path.exists() and not overwrite:
            print(f"Ya existe, se omite: {output_path.name}")
            downloaded_files.append(output_path)
            continue

        print(f"Descargando {source_name} -> {output_path.name}")
        response = requests.get(url, stream=True, timeout=timeout)

        if response.status_code != 200:
            print(f"ERROR {response.status_code}: no se pudo descargar {url}")
            continue

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

        downloaded_files.append(output_path)
        print(f"Guardado: {output_path}")

    return downloaded_files

def crop_spei_time_range(
    input_dir: Path | str,
    output_dir: Path | str,
    start: str = "1982-01-01",
    end: str = "2022-12-31",
    engine: str = "netcdf4",
    overwrite: bool = False,
) -> list[Path]:
    """
    Recorta todos los archivos SPEI de un directorio al periodo indicado.

    Parameters
    ----------
    input_dir : Path | str
        Directorio con archivos SPEI mensuales originales o descargados.

    output_dir : Path | str
        Directorio de salida.

    start, end : str
        Fechas de inicio y fin en formato compatible con xarray/pandas.

    engine : str
        Motor de lectura/escritura NetCDF. Normalmente `netcdf4`.

    overwrite : bool
        Si False, no sobrescribe salidas existentes.

    Returns
    -------
    list[Path]
        Archivos recortados generados.
    """
    input_dir = Path(input_dir)
    output_dir = _ensure_dir(output_dir)
    nc_files = sorted(input_dir.glob("*.nc"))

    if not nc_files:
        raise FileNotFoundError(f"No hay archivos .nc en {input_dir}")

    output_files: list[Path] = []

    for input_path in nc_files:
        print(f"\nRecortando: {input_path.name}")

        # Cambia el nombre temporal si contiene el periodo original.
        output_name = input_path.name
        output_name = re.sub(r"1901_2023", "1982_2022", output_name)

        # Si el nombre no contiene periodo, intentamos construir uno estándar.
        scale = _scale_from_filename(input_path)
        if scale and "1982_2022" not in output_name and "1901_2023" not in output_name:
            output_name = f"spei{scale}_1982_2022_monthly_0.5deg.nc"

        output_path = output_dir / output_name

        if output_path.exists() and not overwrite:
            print(f"Ya existe, se omite: {output_path.name}")
            output_files.append(output_path)
            continue

        with xr.open_dataset(input_path, engine=engine) as ds:
            if "time" not in ds.coords and "time" not in ds.dims:
                raise ValueError(f"El archivo no tiene dimensión temporal: {input_path}")

            ds_subset = ds.sel(time=slice(start, end))

            if ds_subset.sizes.get("time", 0) == 0:
                raise ValueError(
                    f"El recorte temporal {start} -> {end} no contiene datos "
                    f"para {input_path.name}."
                )

            ds_subset.attrs.update(ds.attrs)
            ds_subset.attrs["temporal_subset"] = f"{start} to {end}"
            ds_subset.attrs["processing_step"] = "Temporal crop"

            encoding = _compression_encoding(ds_subset)
            ds_subset.to_netcdf(output_path, engine=engine, encoding=encoding)

        print(f"Guardado: {output_path.name}")
        output_files.append(output_path)

    return output_files

def regrid_spei(
    input_dir: Path | str,
    output_dir: Path | str,
    lat_target: np.ndarray = TARGET_LAT_DESC,
    lon_target: np.ndarray = TARGET_LON_ASC,
    method: str = "linear",
    engine: str = "netcdf4",
    overwrite: bool = False,
) -> list[Path]:
    """
    Alinea archivos SPEI a la malla final del proyecto.
    
    Parameters
    ----------
    input_dir, output_dir : Path | str
        Directorios de entrada/salida.

    lat_target, lon_target : np.ndarray
        Coordenadas destino. Por defecto:
            latitude: 89.5 -> -90.0
            longitude: -180.0 -> 179.5

        Qué cambia si modificas la malla:
            - Para igualar ERA5/LAI: mantener valores por defecto.
            - Para otro modelo: usar exactamente su vector de lat/lon.

    method : str
        Método de interpolación xarray. Opciones habituales:
            - "linear": bilineal; opción estándar para variables continuas.
            - "nearest": vecino más cercano; conserva valores originales, útil
              para categorías, pero SPEI es continuo, así que no es la primera opción.

    engine : str
        Motor NetCDF.

    overwrite : bool
        Si False, no sobrescribe salidas existentes.

    Returns
    -------
    list[Path]
        Archivos remallados generados.
    """
    input_dir = Path(input_dir)
    output_dir = _ensure_dir(output_dir)
    nc_files = sorted(input_dir.glob("*.nc"))

    if not nc_files:
        raise FileNotFoundError(f"No hay archivos .nc en {input_dir}")

    # xarray interp requiere coordenadas ordenadas ascendentemente.
    lat_target_asc = np.sort(lat_target.astype("float32"))
    lon_target_asc = np.sort(lon_target.astype("float32"))

    output_files: list[Path] = []

    for input_path in nc_files:
        output_path = output_dir / input_path.name

        if output_path.exists() and not overwrite:
            print(f"Ya existe, se omite: {output_path.name}")
            output_files.append(output_path)
            continue

        print(f"\nRemallando: {input_path.name}")

        with xr.open_dataset(input_path, engine=engine) as ds:
            ds = _standardise_spatial_names(ds)

            # Convertir longitud a [-180, 180) si viniera en [0, 360).
            if float(ds["longitude"].max()) > 180.0:
                ds = ds.assign_coords(
                    longitude=((ds["longitude"] + 180) % 360) - 180
                )

            # Orden ascendente para interpolación.
            if ds["latitude"][0] > ds["latitude"][-1]:
                ds = ds.sortby("latitude", ascending=True)
            if ds["longitude"][0] > ds["longitude"][-1]:
                ds = ds.sortby("longitude", ascending=True)

            ds_interp = ds.interp(
                latitude=lat_target_asc,
                longitude=lon_target_asc,
                method=method,
            )

            # Salida en convención ERA5/LAI: latitud descendente.
            ds_interp = ds_interp.sortby("latitude", ascending=False)

            for var in ds_interp.data_vars:
                if ds_interp[var].dtype == "float64":
                    ds_interp[var] = ds_interp[var].astype("float32")

            ds_interp.attrs.update(ds.attrs)
            ds_interp.attrs["processing_step"] = "Spatial regridding/alignment"
            ds_interp.attrs["target_grid"] = (
                "latitude 89.5 to -90.0; longitude -180.0 to 179.5; 0.5 degree"
            )
            ds_interp.attrs["interpolation"] = method

            encoding = _compression_encoding(ds_interp)
            ds_interp.to_netcdf(output_path, engine=engine, encoding=encoding)

        print(f"Guardado: {output_path.name}")
        output_files.append(output_path)

    return output_files

def aggregate_spei_monthly_to_annual(
    input_dir: Path | str,
    output_dir: Path | str,
    aggregation: str = "mean",
    engine: str = "netcdf4",
    overwrite: bool = False,
) -> list[Path]:
    """
    Agrega archivos SPEI mensuales a resolución anual.

    Parameters
    ----------
    input_dir, output_dir : Path | str
        Directorios de entrada y salida.

    aggregation : str
        Método de agregación temporal. Opciones:
            - "mean": media anual. Opción usada por defecto en el proyecto.
            - "min": valor mensual mínimo del año. Puede representar sequía máxima.
            - "max": valor mensual máximo del año. Puede representar humedad máxima.
            - "last": último valor mensual del año. Puede tener sentido en escalas
              acumuladas largas, especialmente SPEI12 o SPEI24, si se interpreta
              diciembre como resumen del año hidrológico/calendario.

    engine : str
        Motor NetCDF.

    overwrite : bool
        Si False, no sobrescribe salidas existentes.

    Returns
    -------
    list[Path]
        Archivos anuales generados.
    """
    valid_aggregations = {"mean", "min", "max", "last"}
    if aggregation not in valid_aggregations:
        raise ValueError(f"aggregation debe ser una de {valid_aggregations}")

    input_dir = Path(input_dir)
    output_dir = _ensure_dir(output_dir)
    nc_files = sorted(input_dir.glob("*.nc"))

    if not nc_files:
        raise FileNotFoundError(f"No hay archivos .nc en {input_dir}")

    output_files: list[Path] = []

    for input_path in nc_files:
        out_name = input_path.name.replace("monthly", "annual")
        output_path = output_dir / out_name

        if output_path.exists() and not overwrite:
            print(f"Ya existe, se omite: {output_path.name}")
            output_files.append(output_path)
            continue

        print(f"\nAgregando mensual -> anual: {input_path.name}")

        with xr.open_dataset(input_path, engine=engine) as ds:
            var_name = _detect_main_variable(ds)
            da = ds[var_name]

            if aggregation == "mean":
                annual = da.groupby("time.year").mean("time", skipna=True)
            elif aggregation == "min":
                annual = da.groupby("time.year").min("time", skipna=True)
            elif aggregation == "max":
                annual = da.groupby("time.year").max("time", skipna=True)
            else:  # aggregation == "last"
                annual = da.groupby("time.year").last("time", skipna=True)

            annual = annual.rename({"year": "time"})
            annual = annual.astype("float32") if annual.dtype == "float64" else annual

            # Coordenada temporal: 1 de enero de cada año para consistencia con ERA5.
            years = annual["time"].values.astype(int)
            annual = annual.assign_coords(
                time=np.array([np.datetime64(f"{year}-01-01") for year in years])
            )

            annual.attrs.update(da.attrs)
            annual.attrs["aggregation"] = f"annual {aggregation} of monthly SPEI"

            ds_out = annual.to_dataset(name=var_name)
            ds_out.attrs.update(ds.attrs)
            ds_out.attrs["temporal_resolution"] = "annual"
            ds_out.attrs["annual_aggregation"] = aggregation

            encoding = _compression_encoding(ds_out)
            ds_out.to_netcdf(output_path, engine=engine, encoding=encoding)

        print(f"Guardado: {output_path.name}")
        output_files.append(output_path)

    return output_files
