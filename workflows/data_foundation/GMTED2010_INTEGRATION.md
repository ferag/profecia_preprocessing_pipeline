# Elevation desde GMTED2010: integración optativa

La fuente proporcionada por el usuario es GMTED2010 (USGS/NGA), no GTOPO30.
El código histórico `preprocess_soil_0p5.py` abre `mn30_grd` y usa
`rio.reproject_match(..., resampling=1)` (bilinear), aunque sus atributos llaman
erróneamente GTOPO30 al producto. El catálogo oficial USGS identifica `mn30_grd`
como **mean elevation, 30 arc-seconds**, en ESRI ArcGrid:

- https://topotools.cr.usgs.gov/gmted_viewer/gmted2010_global_grids.php
- https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/topo/downloads/GMTED/Grid_ZipFiles/mn30_grd.zip
- Dataset DOI: https://doi.org/10.5066/F7J38R2N
- Danielson y Gesch (2011): https://doi.org/10.3133/ofr20111073

El enlace devolvió HTTP 200 a una petición HEAD el 2026-10-14; tamaño declarado
277.229.566 bytes. No se descargó el DEM. Esto no garantiza disponibilidad futura
ni sustituye la comprobación de integridad que realiza el adaptador al descargar.

## Ruta añadida

1. Construir la descripción del archivo desde la configuración.
2. Descargar el ZIP oficial sin credenciales y registrar su SHA-256 y origen.
3. Extraer de forma segura el ArcGrid `mn30_grd`.
4. Reproyectar bilinealmente con Rasterio/GDAL a la grilla PROFECIA (360 × 720,
   centros latitudes 89,5 a -90 y longitudes -180 a 179,5).
5. Preservar NoData como NaN y elevaciones negativas válidas, sin recortes.
6. Crear el campo estático intermedio en `work/gmted2010/` y replicarlo mensualmente
   mediante la regla existente de repaquetado, para 1982–2022.

El campo intermedio no añade un producto científico nuevo al inventario: el
manifest y Croissant enlazan la fuente GMTED2010 con el mismo NetCDF mensual
final de elevación. El informe de adquisición y el de inspección se registran.

## Activación por el usuario

La configuración principal y el ZIP previo siguen usando el canónico. El nuevo
perfil optativo es `config/data_foundation_gmted2010_trial.yml`. Puede generarse
otra copia sin ejecutar ningún job:

```bash
python workflows/data_foundation/enable_gmted2010.py --output workflows/data_foundation/config/mi_gmted.yml
```

Planificar la prueba de toda la configuración:

```bash
snakemake --snakefile workflows/data_foundation/workflow/Snakefile \
  --configfile workflows/data_foundation/config/data_foundation_gmted2010_trial.yml \
  --cores 1 --dry-run
```

Quitar `--dry-run` descarga y procesa realmente; hacerlo solo cuando el usuario
decida ejecutar la prueba, en una carpeta nueva. Para probar solo elevación, una
configuración derivada puede seleccionar `gmted2010/elevation` y el producto
derivado `elevation`; el lanzador del starter resuelve esta dependencia.

Un futuro crate construido con `--config` apuntando al perfil optativo excluye
el canónico de elevación del payload efectivo (ahorro aproximado: 85 MB) y mantiene
los enlaces a GMTED2010. Esto es optativo y **no implica equivalencia validada**.
Usar una carpeta nueva de construcción y una ubicación de ZIP que no exista.
El ZIP ya entregado no se ha modificado ni actualizado silenciosamente.

## Condición para sustituir el canónico en el perfil estable

Comparar el DEM generado con la referencia: todas las coordenadas, cada valor,
máscara NaN, orientación, cobertura polar y extensión mensual. El código histórico
utiliza la rejilla de LAI; todavía debe comprobarse que coincida exactamente con
la fijada por el pipeline actual. El canónico mensual incorpora otra adaptación
espacial según sus atributos: no se supone que una única reproyección reproduzca
automáticamente todos esos pasos.

La referencia canónica no registra unidades ni long_name en la variable, mientras
el DEM nuevo declara metros y "Mean elevation". Se deben aprobar esas correcciones
de metadata por separado: no debilitar silenciosamente el comparador existente
para obtener un OK. No se ha ejecutado una comparación científica completa ni
retirado el canónico de la release/paquete estable.
