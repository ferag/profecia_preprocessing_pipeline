"""
Funciones para descargar, descomprimir, limpiar y procesar datos ERA5/ERA5-Land
usando la API de Copernicus Climate Data Store (CDS) y xarray.

Diseñado para el flujo de trabajo del proyecto PROFECIA:
    - Descarga anual de medias mensuales ERA5 single levels.
    - Organización de archivos por año y/o por tipo de stream.
    - Limpieza de NetCDF descargados.
    - Conversión de longitudes [0, 360) a [-180, 180).
    - Rejillado global a 0.5 grados.
    - Concatenación temporal 1982-2022.
    - Separación por variable.
    - Agregación mensual -> anual.
    - Cálculo de anomalías anuales.
    - Cálculo de variables derivadas: VPD, SWC_sub y wind_speed.

Requisitos:
    pip install cdsapi xarray netCDF4 numpy cftime

Configuración previa de CDS API:
    1. Crear cuenta en Copernicus Climate Data Store.
    2. Instalar cdsapi.
    3. Crear el archivo ~/.cdsapirc con la URL y la key de usuario.

Notas críticas:
    - La descarga desde CDS puede cambiar ligeramente según el estado de la API.
    - Algunas peticiones devuelven directamente NetCDF; otras pueden venir empaquetadas
      como ZIP aunque la extensión final sea .nc. Por eso se incluye una función de
      descompresión tolerante.
    - ERA5 single-level monthly means mezcla variables acumuladas y medias. En el CDS,
      variables como tp, ssrd o pev suelen pertenecer a stepType="avgad", mientras que
      t2m, d2m, swvl* suelen aparecer como stepType="avgua". Conviene mantener grupos
      separados cuando la API devuelva archivos por stream.
"""

import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Literal, Sequence

import numpy as np
import xarray as xr

try:
    import cdsapi
except ImportError:  # Permite importar el módulo aunque no se vaya a descargar.
    cdsapi = None

ERA5_CDS_VARIABLES: dict[str, str] = {
    "t2m": "2m_temperature",
    "d2m": "2m_dewpoint_temperature",
    "tp": "total_precipitation",
    "ssrd": "surface_solar_radiation_downwards",
    "swvl1": "volumetric_soil_water_layer_1",
    "swvl2": "volumetric_soil_water_layer_2",
    "swvl3": "volumetric_soil_water_layer_3",
    "u10": "10m_u_component_of_wind",
    "v10": "10m_v_component_of_wind",
    "tcc": "total_cloud_cover",
    "pev": "potential_evaporation",
}

ERA5_PROJECT_GROUPS: dict[str, list[str]] = {
    # Variables principales usadas directamente o como base de humedad.
    "main": ["t2m", "tp", "ssrd", "swvl1", "swvl2", "swvl3"],

    # Variables secundarias usadas para derivadas o como predictores adicionales.
    "secondary": ["d2m", "u10", "v10", "tcc", "pev"],

    # Grupo típico de variables medias instantáneas o de estado.
    # Suele acabar en stream/stepType avgua en algunos archivos de CDS.
    "avgua_like": ["t2m", "d2m", "swvl1", "swvl2", "swvl3", "u10", "v10", "tcc"],

    # Grupo típico de variables acumuladas/promediadas por día.
    # Suele acabar en stream/stepType avgad en algunos archivos de CDS.
    "avgad_like": ["tp", "ssrd", "pev"],
}


def cds_names_from_short_names(short_names: Sequence[str]) -> list[str]:
    """
    Convierte nombres cortos internos a nombres oficiales de CDS.
    """
    missing = [name for name in short_names if name not in ERA5_CDS_VARIABLES]
    if missing:
        raise ValueError(
            f"Variables no reconocidas: {missing}. "
            f"Disponibles: {sorted(ERA5_CDS_VARIABLES)}"
        )
    return [ERA5_CDS_VARIABLES[name] for name in short_names]

def download_era5_monthly_by_year(
    variables: Sequence[str],
    output_dir: str | Path,
    start_year: int = 1982,
    end_year: int = 2022,
    dataset: str = "reanalysis-era5-single-levels-monthly-means",
    product_type: str = "monthly_averaged_reanalysis",
    months: Sequence[str] | None = None,
    time: str = "00:00",
    area: Sequence[float] | None = None,
    file_prefix: str = "ERA5_monthly",
    skip_existing: bool = True,
    request_format: Literal["netcdf", "grib"] = "netcdf",
) -> None:
    """
    Descarga ERA5 monthly means desde CDS, generando un archivo por año.

    Parámetros principales
    ----------------------
    variables:
        Lista de variables. Puede contener nombres cortos del proyecto
        ("t2m", "tp", "ssrd"...) o nombres oficiales CDS
        ("2m_temperature", "total_precipitation"...).

    output_dir:
        Carpeta de salida.

    start_year, end_year:
        Periodo temporal.

    dataset:
        Dataset de CDS. Para ERA5 mensual de single levels:
        "reanalysis-era5-single-levels-monthly-means".

        Opción habitual alternativa:
        - "reanalysis-era5-land-monthly-means" si se quieren variables ERA5-Land.
          Ojo: no todas las variables están disponibles con el mismo nombre.

    product_type:
        Para ERA5 monthly means suele ser "monthly_averaged_reanalysis".

    months:
        Lista de meses como strings "01"..."12". Si None, descarga los 12 meses.

    time:
        Hora solicitada. Para monthly means suele usarse "00:00".

    area:
        Bounding box opcional en formato CDS [North, West, South, East].
        - None: descarga global.
        - Ejemplo Península aproximada: [44, -10, 35, 5].

    file_prefix:
        Prefijo del archivo anual. Ejemplo: "ERA5_avgua_monthly".

    skip_existing:
        Si True, no repite descargas ya presentes.

    request_format:
        "netcdf" recomendado para este pipeline. "grib" solo si quieres procesar
        posteriormente GRIB con cfgrib; no es lo usado aquí.
    """
    if cdsapi is None:
        raise ImportError(
            "No se pudo importar cdsapi. Instala con: pip install cdsapi"
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    months = list(months) if months is not None else [f"{m:02d}" for m in range(1, 13)]

    # Permite pasar nombres cortos o nombres largos de CDS.
    variables = list(variables)
    if all(v in ERA5_CDS_VARIABLES for v in variables):
        cds_variables = cds_names_from_short_names(variables)
    else:
        cds_variables = variables

    client = cdsapi.Client()

    for year in range(start_year, end_year + 1):
        outfile = output_dir / f"{file_prefix}_{year}.nc"
        if outfile.exists() and skip_existing:
            print(f"[SKIP] Ya existe: {outfile.name}")
            continue

        request = {
            "product_type": product_type,
            "variable": cds_variables,
            "year": str(year),
            "month": months,
            "time": time,
            "format": request_format,
        }

        if area is not None:
            # CDS espera [north, west, south, east].
            request["area"] = list(area)

        print(f"[DOWNLOAD] {year} -> {outfile.name}")
        client.retrieve(dataset, request, str(outfile))
        print(f"[OK] Guardado: {outfile}")

def unzip_era5_archives(
    base_path: str | Path,
    remove_zip: bool = False,
    organize_streams: bool = True,
) -> None:
    """
    Extrae archivos ZIP generados por CDS y, si procede, organiza por stream.

    Problema práctico
    -----------------
    Algunas descargas de ERA5 monthly means pueden guardarse con extensión .nc
    pero contener internamente un ZIP con ficheros NetCDF separados por stepType,
    por ejemplo:
        data_stream-moda_stepType-avgad.nc
        data_stream-moda_stepType-avgua.nc

    Esta función intenta abrir cada .zip y cada .nc como ZIP. Si no lo es, lo ignora.

    Parámetros
    ----------
    base_path:
        Carpeta donde están los archivos descargados.

    remove_zip:
        Si True, elimina el archivo comprimido tras extraerlo.

    organize_streams:
        Si True, mueve los archivos extraídos a carpetas:
            base_path/avgad
            base_path/avgua
        y los renombra como:
            moda_avgad_YYYY.nc
            moda_avgua_YYYY.nc
    """
    base_path = Path(base_path)
    avgad_dir = base_path / "avgad"
    avgua_dir = base_path / "avgua"

    if organize_streams:
        avgad_dir.mkdir(exist_ok=True)
        avgua_dir.mkdir(exist_ok=True)

    candidates = sorted(list(base_path.glob("*.zip")) + list(base_path.glob("*.nc")))
    if not candidates:
        print(f"[INFO] No se encontraron archivos .zip o .nc en {base_path}")
        return

    for archive in candidates:
        if not zipfile.is_zipfile(archive):
            print(f"[SKIP] No es ZIP: {archive.name}")
            continue

        print(f"[UNZIP] Extrayendo: {archive.name}")
        try:
            with zipfile.ZipFile(archive, "r") as zf:
                zf.extractall(base_path)

            match = re.search(r"(\d{4})", archive.stem)
            year = match.group(1) if match else "unknown"

            if organize_streams:
                for extracted in base_path.glob("data_stream-moda_stepType-*.nc"):
                    name_lower = extracted.name.lower()
                    if "avgad" in name_lower:
                        new_name = avgad_dir / f"moda_avgad_{year}.nc"
                    elif "avgua" in name_lower:
                        new_name = avgua_dir / f"moda_avgua_{year}.nc"
                    else:
                        print(f"[WARN] Stream desconocido: {extracted.name}")
                        continue

                    if new_name.exists():
                        new_name.unlink()
                    extracted.rename(new_name)
                    print(f"[OK] {new_name.name}")

            if remove_zip:
                archive.unlink()
                print(f"[REMOVE] {archive.name}")

        except Exception as exc:
            print(f"[ERROR] No se pudo procesar {archive.name}: {exc}")

def _standardize_coord_names(ds: xr.Dataset) -> xr.Dataset:
    """
    Homogeneiza nombres de coordenadas habituales.

    ERA5 suele usar latitude/longitude y valid_time, pero algunos archivos pueden
    llegar como lat/lon o time. Esta función evita que el resto del pipeline falle.
    """
    rename_map = {}
    if "valid_time" in ds.dims or "valid_time" in ds.coords:
        rename_map["valid_time"] = "time"
    if "lat" in ds.dims or "lat" in ds.coords:
        rename_map["lat"] = "latitude"
    if "lon" in ds.dims or "lon" in ds.coords:
        rename_map["lon"] = "longitude"

    if rename_map:
        ds = ds.rename(rename_map)
    return ds


def clean_era5_files(
    input_dir: str | Path,
    output_dir: str | Path,
    drop_vars: Sequence[str] = ("expver", "number"),
    compression_level: int = 4,
    overwrite: bool = False,
) -> None:
    """
    Limpia archivos NetCDF anuales de ERA5.

    Operaciones realizadas
    ----------------------
    - Renombra valid_time -> time si existe.
    - Renombra lat/lon -> latitude/longitude si fuese necesario.
    - Elimina variables auxiliares como expver y number.
    - Ordena latitud de norte a sur.
    - Normaliza fechas a día completo, eliminando la hora.
    - Guarda con compresión zlib.

    Salida
    ------
    Para cada archivo input.nc genera:
        input_clean.nc
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    nc_files = sorted(input_dir.glob("*.nc"))
    if not nc_files:
        raise FileNotFoundError(f"No se encontraron .nc en {input_dir}")

    for nc_file in nc_files:
        output_file = output_dir / f"{nc_file.stem}_clean.nc"
        if output_file.exists() and not overwrite:
            print(f"[SKIP] Ya existe: {output_file.name}")
            continue

        print(f"[CLEAN] {nc_file.name}")
        with xr.open_dataset(nc_file, engine="netcdf4") as ds:
            ds = _standardize_coord_names(ds)
            ds = ds.drop_vars(list(drop_vars), errors="ignore")

            if "latitude" in ds.coords:
                if float(ds.latitude[0]) < float(ds.latitude[-1]):
                    ds = ds.sortby("latitude", ascending=False)

            if "time" in ds.coords:
                # Funciona para datetime64. Si el calendario es cftime, se deja intacto.
                try:
                    ds["time"] = ds["time"].dt.floor("D")
                except Exception:
                    pass

            encoding = {
                var: {"zlib": True, "complevel": compression_level}
                for var in ds.data_vars
            }
            ds.to_netcdf(output_file, engine="netcdf4", encoding=encoding)

        print(f"[OK] {output_file.name}")

def regrid_era5_files_to_05deg(
    input_dir: str | Path,
    output_dir: str | Path,
    latitude_target: np.ndarray | None = None,
    longitude_target: np.ndarray | None = None,
    method: Literal["linear", "nearest"] = "linear",
    compression_level: int = 4,
    overwrite: bool = False,
) -> None:
    """
    Rejilla archivos ERA5 a 0.5° y convierte longitudes a [-180, 180).

    Rejilla objetivo por defecto
    ----------------------------
    - latitude:  89.5, 89.0, ..., -90.0  -> 360 filas
    - longitude: -180.0, -179.5, ..., 179.5 -> 720 columnas

    method
    ------
    - "linear": recomendado para variables continuas como temperatura, humedad,
      radiación o VPD.
    - "nearest": útil para variables categóricas. No es el caso típico de ERA5,
      pero se deja la opción.

    Nota metodológica
    -----------------
    Para precipitación y radiación acumulada/promediada, una interpolación lineal
    a 0.5° es práctica y consistente con muchos pipelines, pero no conserva masa
    estrictamente. Si el análisis exigiera conservación física exacta, habría que
    usar remapeo conservativo con xESMF/CDO. Para un TFM global a 0.5°, xarray es
    suficiente y bastante menos quisquilloso. CDO es más clásico; xarray se porta
    mejor en Python puro.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if latitude_target is None:
        latitude_target = np.arange(89.5, -90.01, -0.5)
    if longitude_target is None:
        longitude_target = np.arange(-180.0, 180.0, 0.5)

    nc_files = sorted(input_dir.glob("*.nc"))
    if not nc_files:
        raise FileNotFoundError(f"No se encontraron .nc en {input_dir}")

    for nc_file in nc_files:
        out_file = output_dir / f"{nc_file.stem}_0.5deg.nc"
        if out_file.exists() and not overwrite:
            print(f"[SKIP] Ya existe: {out_file.name}")
            continue

        print(f"[REGRID] {nc_file.name}")
        with xr.open_dataset(nc_file, engine="netcdf4") as ds:
            ds = _standardize_coord_names(ds)

            if "longitude" not in ds.coords or "latitude" not in ds.coords:
                raise ValueError(f"{nc_file.name} no tiene latitude/longitude.")

            # [0, 360) -> [-180, 180)
            if float(ds.longitude.max()) > 180.0:
                lon_new = ((ds.longitude + 180) % 360) - 180
                ds = ds.assign_coords(longitude=lon_new).sortby("longitude")

            # Norte -> sur
            if float(ds.latitude[0]) < float(ds.latitude[-1]):
                ds = ds.sortby("latitude", ascending=False)

            ds_05 = ds.interp(
                latitude=latitude_target,
                longitude=longitude_target,
                method=method,
            )

            encoding = {
                var: {"zlib": True, "complevel": compression_level}
                for var in ds_05.data_vars
            }
            ds_05.to_netcdf(out_file, engine="netcdf4", encoding=encoding)
            ds_05.close()

        print(f"[OK] {out_file.name}")

def concat_era5_files(
    input_dir: str | Path,
    output_file: str | Path,
    compression_level: int = 4,
) -> None:
    """
    Concatena archivos ERA5 anuales ya limpios/rejillados en un único NetCDF.

    Ejemplo de salida
    -----------------
    - avgua_1982_2022_monthly_0.5deg.nc
    - avgad_1982_2022_monthly_0.5deg.nc
    """
    input_dir = Path(input_dir)
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    nc_files = sorted(input_dir.glob("*.nc"))
    if not nc_files:
        raise FileNotFoundError(f"No se encontraron .nc en {input_dir}")

    print(f"[CONCAT] {len(nc_files)} archivos -> {output_file.name}")
    ds = xr.open_mfdataset(
        nc_files,
        combine="nested",
        concat_dim="time",
        parallel=False,
        coords="minimal",
        compat="override",
        engine="netcdf4",
    )
    ds = _standardize_coord_names(ds).sortby("time")

    encoding = {
        var: {"zlib": True, "complevel": compression_level}
        for var in ds.data_vars
    }
    ds.to_netcdf(output_file, engine="netcdf4", encoding=encoding)
    ds.close()
    print(f"[OK] {output_file}")


def split_era5_variables(
    input_file: str | Path,
    output_dir: str | Path,
    temporal_label: str = "monthly",
    spatial_label: str = "0.5deg",
    compression_level: int = 4,
) -> None:
    """
    Separa un NetCDF multivariable en un archivo por variable.

    Convención de nombres
    ---------------------
        <var>_<startyear>_<endyear>_<temporal_label>_<spatial_label>.nc

    Ejemplo
    -------
        t2m_1982_2022_monthly_0.5deg.nc
    """
    input_file = Path(input_file)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(input_file, engine="netcdf4") as ds:
        ds = _standardize_coord_names(ds)
        variables = list(ds.data_vars)
        if not variables:
            raise ValueError(f"{input_file.name} no contiene variables de datos.")

        if "time" in ds.coords:
            start_year = int(ds.time.dt.year.values[0])
            end_year = int(ds.time.dt.year.values[-1])
            period = f"{start_year}_{end_year}"
        else:
            period = "unknown_period"

        for var in variables:
            out_file = output_dir / f"{var}_{period}_{temporal_label}_{spatial_label}.nc"
            print(f"[SPLIT] {var} -> {out_file.name}")
            ds_var = ds[[var]]
            encoding = {var: {"zlib": True, "complevel": compression_level}}
            ds_var.to_netcdf(out_file, engine="netcdf4", encoding=encoding)

    print("[OK] Separación terminada.")


def convert_monthly_to_annual(
    input_dir: str | Path,
    output_dir: str | Path,
    aggregation: Literal["mean", "sum"] = "mean",
    compression_level: int = 4,
    overwrite: bool = False,
) -> None:
    """
    Convierte archivos mensuales por variable a resolución anual.

    aggregation
    -----------
    - "mean": recomendado para variables de estado o medias mensuales:
      t2m, d2m, swvl1, swvl2, swvl3, tcc, u10, v10, ssrd si ya representa media.
    - "sum": usar solo si el archivo mensual representa acumulados mensuales y se
      quiere total anual. Para tp hay que revisar unidades/metadatos del archivo.

    Decisión usada en PROFECIA
    --------------------------
    Según la documentación del proyecto, se generaron promedios anuales. Por tanto,
    aggregation="mean" es la opción por defecto.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    nc_files = sorted(input_dir.glob("*.nc"))
    if not nc_files:
        raise FileNotFoundError(f"No se encontraron .nc en {input_dir}")

    for nc_file in nc_files:
        name = nc_file.stem.replace("monthly", "annual")
        out_path = output_dir / f"{name}.nc"
        if out_path.exists() and not overwrite:
            print(f"[SKIP] Ya existe: {out_path.name}")
            continue

        print(f"[ANNUAL] {nc_file.name}")
        with xr.open_dataset(nc_file, engine="netcdf4") as ds:
            ds = _standardize_coord_names(ds)
            var_name = list(ds.data_vars)[0]
            da = ds[var_name]

            if aggregation == "mean":
                annual_da = da.groupby("time.year").mean("time", keep_attrs=True)
            elif aggregation == "sum":
                annual_da = da.groupby("time.year").sum("time", keep_attrs=True)
            else:
                raise ValueError("aggregation debe ser 'mean' o 'sum'.")

            annual_da = annual_da.astype("float32")
            annual_da = annual_da.rename({"year": "time"})

            years = annual_da.time.values.astype(int)
            new_time = xr.cftime_range(
                start=str(years[0]),
                periods=len(years),
                freq="YS",
                calendar="standard",
            )
            annual_da = annual_da.assign_coords(time=new_time)

            ds_out = annual_da.to_dataset(name=var_name)
            ds_out.attrs = ds.attrs.copy()
            ds_out.attrs["temporal_aggregation"] = f"annual_{aggregation}_from_monthly"

            encoding = {var_name: {"zlib": True, "complevel": compression_level}}
            ds_out.to_netcdf(out_path, engine="netcdf4", encoding=encoding)
            ds_out.close()

        print(f"[OK] {out_path.name}")

def compute_annual_anomalies(
    input_dir: str | Path,
    output_dir: str | Path,
    climatology_period: str = "1982-2022",
    compression_level: int = 4,
    overwrite: bool = False,
) -> None:
    """
    Calcula anomalías anuales por píxel.

    Definición
    ----------
        anomalía(t, y, x) = valor_anual(t, y, x) - media_1982_2022(y, x)

    Uso actual del TFM
    ------------------
    Si el trabajo final usa valores reales anuales, esta función queda como opción
    documentada, no como paso obligatorio. Conviene dejarla: los revisores aman
    preguntar "¿y si...?". Mejor tener la bala en la recámara.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    nc_files = sorted(input_dir.glob("*.nc"))
    if not nc_files:
        raise FileNotFoundError(f"No se encontraron .nc en {input_dir}")

    for nc_file in nc_files:
        out_name = nc_file.stem.replace("annual", "anomaly") + ".nc"
        out_path = output_dir / out_name
        if out_path.exists() and not overwrite:
            print(f"[SKIP] Ya existe: {out_path.name}")
            continue

        print(f"[ANOMALY] {nc_file.name}")
        with xr.open_dataset(nc_file, engine="netcdf4") as ds:
            ds = _standardize_coord_names(ds)
            var_name = list(ds.data_vars)[0]
            da = ds[var_name]

            clim = da.mean("time", keep_attrs=True)
            anomaly = (da - clim).astype("float32")
            anomaly.name = var_name
            anomaly.attrs = da.attrs.copy()
            anomaly.attrs["long_name"] = f"{da.attrs.get('long_name', var_name)} anomaly"
            anomaly.attrs["comment"] = "Annual anomaly computed as value minus temporal mean per pixel."
            anomaly.attrs["climatology_period"] = climatology_period

            ds_out = anomaly.to_dataset(name=var_name)
            ds_out.attrs = ds.attrs.copy()
            ds_out.attrs["climatology_period"] = climatology_period

            encoding = {var_name: {"zlib": True, "complevel": compression_level}}
            ds_out.to_netcdf(out_path, engine="netcdf4", encoding=encoding)
            ds_out.close()

        print(f"[OK] {out_path.name}")

def _get_single_dataarray(ds: xr.Dataset, preferred_name: str | None = None) -> xr.DataArray:
    """Devuelve una variable de datos, priorizando preferred_name si existe."""
    if preferred_name and preferred_name in ds.data_vars:
        return ds[preferred_name]
    data_vars = list(ds.data_vars)
    if len(data_vars) != 1:
        raise ValueError(
            f"Se esperaba un archivo con una única variable, pero contiene {data_vars}. "
            "Indica preferred_name o separa variables antes."
        )
    return ds[data_vars[0]]


def _to_celsius(da: xr.DataArray) -> xr.DataArray:
    """Convierte K -> °C si los atributos indican Kelvin."""
    units = da.attrs.get("units", "").lower().replace(" ", "")
    if units in {"k", "kelvin"}:
        out = (da - 273.15).astype("float32")
        out.attrs = da.attrs.copy()
        out.attrs["units"] = "degC"
        return out
    return da.astype("float32")


def calculate_vpd(
    t2m_path: str | Path,
    d2m_path: str | Path,
    output_path: str | Path,
    t2m_var: str = "t2m",
    d2m_var: str = "d2m",
    compression_level: int = 4,
) -> None:
    """
    Calcula Vapor Pressure Deficit, VPD, en kPa a partir de t2m y d2m.

    Fórmula
    -------
        VPD = es(T) - ea(Td)
        es = c1 * exp(c2*T  / (c3 + T))
        ea = c1 * exp(c2*Td / (c3 + Td))

    donde T y Td están en °C:
        c1 = 0.611 kPa
        c2 = 17.5
        c3 = 240.978 °C
    """
    t2m_path = Path(t2m_path)
    d2m_path = Path(d2m_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(t2m_path, engine="netcdf4") as ds_t, \
         xr.open_dataset(d2m_path, engine="netcdf4") as ds_d:

        ds_t = _standardize_coord_names(ds_t)
        ds_d = _standardize_coord_names(ds_d)
        ds_t, ds_d = xr.align(ds_t, ds_d, join="exact")

        T = _to_celsius(_get_single_dataarray(ds_t, t2m_var))
        Td = _to_celsius(_get_single_dataarray(ds_d, d2m_var))

        c1 = 0.611
        c2 = 17.5
        c3 = 240.978

        es = c1 * np.exp((c2 * T) / (T + c3))
        ea = c1 * np.exp((c2 * Td) / (Td + c3))
        vpd = (es - ea).clip(min=0).astype("float32")
        vpd.name = "vpd"
        vpd.attrs = {
            "long_name": "Vapor Pressure Deficit",
            "units": "kPa",
            "standard_name": "vapor_pressure_deficit",
            "comment": "VPD = es(T) - ea(Td), Magnus-type equation.",
            "source_variables": f"{t2m_path.name}; {d2m_path.name}",
            "reference": "Barkhordarian et al. (2019)",
        }

        ds_out = vpd.to_dataset(name="vpd")
        ds_out.attrs = ds_t.attrs.copy()
        ds_out.attrs["history"] = _append_history(ds_t.attrs.get("history", ""), "VPD computed from t2m and d2m.")

        encoding = {"vpd": {"zlib": True, "complevel": compression_level}}
        ds_out.to_netcdf(output_path, engine="netcdf4", encoding=encoding)
        ds_out.close()

    print(f"[OK] VPD guardado: {output_path.name}")

def calculate_swc_subsurface(
    swvl2_path: str | Path,
    swvl3_path: str | Path,
    output_path: str | Path,
    swvl2_var: str = "swvl2",
    swvl3_var: str = "swvl3",
    w2_cm: float = 21.0,
    w3_cm: float = 72.0,
    compression_level: int = 4,
) -> None:
    """
    Calcula humedad sub-superficial del suelo, SWC_sub, a partir de swvl2 y swvl3.

    Fórmula
    -------
        SWC_sub = (w2 * swvl2 + w3 * swvl3) / (w2 + w3)

    Pesos por defecto
    -----------------
    - swvl2: 7-28 cm  -> espesor 21 cm
    - swvl3: 28-100 cm -> espesor 72 cm
    """
    swvl2_path = Path(swvl2_path)
    swvl3_path = Path(swvl3_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(swvl2_path, engine="netcdf4") as ds2, \
         xr.open_dataset(swvl3_path, engine="netcdf4") as ds3:

        ds2 = _standardize_coord_names(ds2)
        ds3 = _standardize_coord_names(ds3)
        ds2, ds3 = xr.align(ds2, ds3, join="exact")

        swvl2 = _get_single_dataarray(ds2, swvl2_var)
        swvl3 = _get_single_dataarray(ds3, swvl3_var)

        swc_sub = ((w2_cm * swvl2 + w3_cm * swvl3) / (w2_cm + w3_cm)).astype("float32")
        swc_sub.name = "swc_sub"
        swc_sub.attrs = {
            "long_name": "Sub-surface Soil Water Content",
            "units": swvl2.attrs.get("units", "m3 m-3"),
            "standard_name": "subsurface_soil_water_content",
            "comment": f"Weighted mean of swvl2 and swvl3 using w2={w2_cm} cm and w3={w3_cm} cm.",
            "source_variables": f"{swvl2_path.name}; {swvl3_path.name}",
            "reference": "Wang et al. (2020, 2022)",
        }

        ds_out = swc_sub.to_dataset(name="swc_sub")
        ds_out.attrs = ds2.attrs.copy()
        ds_out.attrs["history"] = _append_history(ds2.attrs.get("history", ""), "SWC_sub computed from swvl2 and swvl3.")

        encoding = {"swc_sub": {"zlib": True, "complevel": compression_level}}
        ds_out.to_netcdf(output_path, engine="netcdf4", encoding=encoding)
        ds_out.close()

    print(f"[OK] SWC_sub guardado: {output_path.name}")

def calculate_wind_speed(
    u10_path: str | Path,
    v10_path: str | Path,
    output_path: str | Path,
    u10_var: str = "u10",
    v10_var: str = "v10",
    compression_level: int = 4,
) -> None:
    """
    Calcula velocidad del viento a 10 m.

    Fórmula
    -------
        wind_speed = sqrt(u10^2 + v10^2)
    """
    u10_path = Path(u10_path)
    v10_path = Path(v10_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(u10_path, engine="netcdf4") as dsu, \
         xr.open_dataset(v10_path, engine="netcdf4") as dsv:

        dsu = _standardize_coord_names(dsu)
        dsv = _standardize_coord_names(dsv)
        dsu, dsv = xr.align(dsu, dsv, join="exact")

        u = _get_single_dataarray(dsu, u10_var)
        v = _get_single_dataarray(dsv, v10_var)

        wind_speed = np.hypot(u, v).astype("float32")
        wind_speed.name = "wind_speed"
        wind_speed.attrs = {
            "long_name": "10 m wind speed",
            "units": "m s-1",
            "standard_name": "wind_speed",
            "comment": "Computed as sqrt(u10^2 + v10^2).",
            "source_variables": f"{u10_path.name}; {v10_path.name}",
        }

        ds_out = wind_speed.to_dataset(name="wind_speed")
        ds_out.attrs = dsu.attrs.copy()
        ds_out.attrs["history"] = _append_history(dsu.attrs.get("history", ""), "wind_speed computed from u10 and v10.")

        encoding = {"wind_speed": {"zlib": True, "complevel": compression_level}}
        ds_out.to_netcdf(output_path, engine="netcdf4", encoding=encoding)
        ds_out.close()

    print(f"[OK] wind_speed guardado: {output_path.name}")


def _append_history(previous_history: str, message: str) -> str:
    """Añade una línea simple al atributo global history."""
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    addition = f"{now} - {message}"
    if previous_history:
        return f"{previous_history}; {addition}"
    return addition
