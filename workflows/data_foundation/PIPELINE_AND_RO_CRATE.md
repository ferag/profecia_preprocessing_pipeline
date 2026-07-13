# PROFECIA Data Foundation Pipeline And RO-Crate Roadmap

Este documento explica como funciona el pipeline `workflows/data_foundation`, que contrato de datos produce y como puede evolucionar hacia un RO-Crate reproducible o incluso ejecutable.

El pipeline actual tiene dos objetivos complementarios:

1. Descargar o registrar fuentes heterogeneas de datos ambientales, climaticos y antropicos.
2. Producir una release local con una estructura estable, checksums, validaciones y salidas homogeneizadas en grilla global `0.5 x 0.5` grados.

La idea de fondo es que esta release sea el contrato de entrada para pipelines posteriores de PROFECIA, evitando rutas ad hoc y dejando suficiente metadata para empaquetar la release como RO-Crate.

## Resumen Ejecutivo

El pipeline se ejecuta con Snakemake y una configuracion YAML central. La configuracion declara:

- que variables forman parte de la release;
- que fuente provee cada variable;
- si la fuente se descarga por API/HTTP o si es manual;
- que adaptador de Python debe usarse;
- que archivo bruto debe producirse;
- como clasificar cada salida como mensual, anual o estatica.

El resultado se escribe bajo:

```text
resources/data_releases/profecia_inputs_full_auto_v0/
```

La release queda organizada asi:

```text
metadata/      requests, listas de archivos, reportes de descarga
raw/           archivos originales o casi-originales por fuente
monthly/       NetCDF mensuales homogeneizados a 0.5 grados
annual/        NetCDF anuales homogeneizados a 0.5 grados
static/        NetCDF estaticos homogeneizados a 0.5 grados
validation/    inspecciones, validacion de armonizados y validacion global
fair/          descriptor Croissant provisional
manifest.json  contrato principal de la release
checksums.sha256
```

La validacion clave de salidas homogeneizadas es:

```text
validation/harmonized_validation.json
```

Debe estar en `OK`. En la ejecucion actual comprueba que todas las salidas armonizadas tienen:

- `latitude = 360`
- `longitude = 720`
- paso espacial `0.5` grados
- rango de latitud `[-89.75, 89.75]`
- rango de longitud `[-179.75, 179.75]`
- al menos algun valor finito por variable

## Componentes Principales

### Configuracion

Archivo principal:

```text
workflows/data_foundation/config/data_foundation_full_auto.local.yml
```

Archivo de configuracion local de usuario:

```text
workflows/data_foundation/config/user_settings.local.yml
```

La clave mas importante es `selected_variables`, por ejemplo:

```yaml
selected_variables:
  - source: era5_single_levels
    variable: t2m
  - source: carbontracker_co2
    variable: co2
  - source: ndep_tian2022
    variable: ndep
  - source: hfp_mu_hengl
    variable: hfp
  - source: hwsd2
    variable: sand
```

Cada `source` se define bajo `sources`. Ahi se declara el modo de acceso, adaptador, proveedor, unidades, nombres de salida y metadata cientifica.

### Snakemake

El punto de entrada del workflow es:

```text
workflows/data_foundation/workflow/Snakefile
```

El `Snakefile` calcula listas de targets a partir del YAML:

- `REQUESTS`
- `RAW_OUTPUTS`
- `INSPECTIONS`
- `HARMONIZED_MONTHLY_OUTPUTS`
- `HARMONIZED_ANNUAL_OUTPUTS`
- `HARMONIZED_STATIC_OUTPUTS`
- `HARMONIZED_VALIDATION`

Despues incluye reglas modulares:

```text
workflow/rules/acquire.smk
workflow/rules/inspect.smk
workflow/rules/harmonize.smk
workflow/rules/metadata.smk
workflow/rules/validate.smk
```

Una decision importante es que las reglas usan el Python que ejecuta Snakemake:

```python
PYTHON = sys.executable
```

Esto evita usar accidentalmente un `.venv` ubicado en `/srv_2`, que puede fallar si el filesystem esta montado con `noexec` y NumPy no puede cargar extensiones nativas.

### Adaptadores De Fuente

Los adaptadores viven en:

```text
workflow/scripts/sources/
```

Cada adaptador encapsula la logica especifica de una fuente. Por ejemplo:

```text
era5.py       ERA5 via CDS API
co2.py        NOAA CarbonTracker + NOAA GML
ndep.py       Nitrogen deposition de Tian/PANGAEA
hfp.py        Human Footprint via Figshare + Zenodo
hwsd2.py      HWSD2 raw ZIP downloads
```

El patron general para fuentes API/HTTP es:

1. `build-request`: escribe un `request.json` reproducible.
2. `download`: descarga y produce un archivo bruto en `raw/`.

Para fuentes tipo bundle, como HWSD2, se produce:

```text
metadata/hwsd2/file_list.json
metadata/hwsd2/download_report.json
raw/hwsd2/HWSD2_DB.zip
raw/hwsd2/HWSD2_RASTER.zip
```

### Scripts Comunes

Los scripts comunes viven en:

```text
workflow/scripts/common/
```

Los mas importantes son:

```text
config_loader.py          lectura y resolucion de rutas desde YAML
netcdf_inspector.py       inspeccion de NetCDF brutos
harmonize.py              homogeneizacion a carpetas monthly/annual/static
validate_harmonized.py    validacion de grilla 0.5 grados
manifest.py               manifest de la release
checksums.py              checksums SHA256
croissant_writer.py       descriptor Croissant provisional
```

## Flujo Del Pipeline

### 1. Construccion De Requests

Para cada variable API/HTTP no bundle, Snakemake ejecuta `build_request`.

Salida tipica:

```text
metadata/{source}/{variable}/request.json
```

Este archivo es importante para reproducibilidad porque captura exactamente que se pidio al proveedor: years, months, URLs, endpoint, variables nativas, etc.

### 2. Descarga O Registro

Las descargas se escriben en `raw/`.

Ejemplos:

```text
raw/era5_single_levels/t2m/t2m_1982_monthly_raw.nc
raw/carbontracker_co2/co2/co2_2000_2020_monthly_glb3x2.nc
raw/ndep_tian2022/ndep/ndep_1982_2022_annual_0.5deg.nc
raw/hfp_mu_hengl/hfp/hfp_1982_2022_annual_0.5deg.nc
raw/hwsd2/HWSD2_DB.zip
raw/hwsd2/HWSD2_RASTER.zip
```

Los logs de descarga se guardan en:

```text
logs/{source}_{variable}_{filename}.download.log
```

### 3. Inspeccion De NetCDF Brutos

Para cada NetCDF descargado o construido, el pipeline ejecuta `netcdf_inspector.py`.

Salida:

```text
validation/{source}/{variable}/inspection.json
```

La inspeccion recoge:

- variables presentes;
- dimensiones;
- coordenadas;
- variable seleccionada;
- shape;
- unidades;
- rango temporal;
- rango lat/lon;
- estadisticas min/max/media;
- warnings.

En la ejecucion actual hay algunos warnings benignos en brutos, por ejemplo valores negativos minimos en capas de humedad de suelo o nombres de unidad ligeramente distintos.

### 4. Homogeneizacion

Esta es la etapa nueva que convierte la release descargada en una release usable directamente por modelos posteriores.

Reglas:

```text
workflow/rules/harmonize.smk
```

Script principal:

```text
workflow/scripts/common/harmonize.py
```

Clasificacion temporal:

- Si una variable es mensual, se escribe en `monthly/`.
- Si una variable es anual, se escribe en `annual/`.
- Si una variable es estatica o bundle estatico, se escribe en `static/`.

La clasificacion se infiere de `data_structure`, `dimensionality`, `native_temporal_resolution`, `output_filename` y `months`.

#### Monthly

ERA5 y CO2 se escriben como NetCDF mensuales a `0.5 x 0.5` grados:

```text
monthly/era5_single_levels_t2m_monthly_0.5deg.nc
monthly/era5_single_levels_d2m_monthly_0.5deg.nc
monthly/era5_single_levels_tp_monthly_0.5deg.nc
monthly/era5_single_levels_pev_monthly_0.5deg.nc
monthly/era5_single_levels_ssrd_monthly_0.5deg.nc
monthly/era5_single_levels_swvl1_monthly_0.5deg.nc
monthly/era5_single_levels_swvl2_monthly_0.5deg.nc
monthly/era5_single_levels_swvl3_monthly_0.5deg.nc
monthly/era5_single_levels_tcc_monthly_0.5deg.nc
monthly/era5_single_levels_u10_monthly_0.5deg.nc
monthly/era5_single_levels_v10_monthly_0.5deg.nc
monthly/carbontracker_co2_co2_monthly_0.5deg.nc
```

ERA5 pasa de su grilla nativa `0.25 x 0.25` a `0.5 x 0.5` usando interpolacion lineal sobre los centros de celda de destino.

CO2 CarbonTracker entra como `2 x 3` grados y 34 niveles verticales. La salida mensual armonizada usa el primer nivel (`level=1`) como campo 2D mensual y lo documenta en atributos. Esto evita producir un NetCDF 4D enorme cuando el contrato del pipeline necesita un predictor espacial mensual simple.

#### Annual

NDEP y HFP se escriben como anuales:

```text
annual/ndep_tian2022_ndep_annual_0.5deg.nc
annual/hfp_mu_hengl_hfp_annual_0.5deg.nc
```

Ambos quedan con:

```text
year = 41
latitude = 360
longitude = 720
```

#### Static

HWSD2 se escribe como NetCDF estatico:

```text
static/hwsd2_soil_0.5deg.nc
```

Variables incluidas:

```text
sand, clay, silt, ph, soc, total_n, bulk, cec
```

HWSD2 se procesa desde:

```text
raw/hwsd2/HWSD2_RASTER.zip
raw/hwsd2/HWSD2_DB.zip
```

El raster `HWSD2.bil` se extrae a una carpeta de trabajo, no a `raw/`, para no mezclar intermediarios con datos fuente:

```text
work/hwsd2/HWSD2.bil
```

La tabla `HWSD2_LAYERS.csv` se busca en rutas conocidas o puede pasarse explicitamente al script. En la ejecucion actual se encontro en:

```text
/srv/read_only_data/NANA/soil/RAW/HWSD2_soil/RAW/HWSD2_LAYERS.csv
```

La logica usa el topsoil/shallowest layer por `HWSD2_SMU_ID`, calcula medias ponderadas por `SHARE`, agrega bloques de `60 x 60` pixeles de 30 arcsec a celdas de 0.5 grados y normaliza `sand + silt + clay` a 100 cuando las tres variables estan presentes.

### 5. Validacion De Homogeneizados

La regla `validate_harmonized` produce:

```text
validation/harmonized_validation.json
```

El reporte debe estar en:

```json
{
  "status": "OK"
}
```

En la ejecucion actual valida 15 archivos:

- 12 mensuales;
- 2 anuales;
- 1 estatico.

### 6. Manifest, Croissant, Checksums Y Validacion Global

El pipeline produce:

```text
manifest.json
fair/harmonized_netcdf_demo.croissant.jsonld
checksums.sha256
validation/release_validation.json
```

`manifest.json` es el contrato principal para otros pipelines. Por cada variable seleccionada contiene:

- fuente;
- variable;
- proveedor;
- familia de fuente;
- modo de acceso;
- metadata generada;
- archivos raw;
- archivos homogeneizados;
- inventario manual si aplica.

`checksums.sha256` permite verificar integridad:

```bash
cd resources/data_releases/profecia_inputs_full_auto_v0
sha256sum -c checksums.sha256
```

`release_validation.json` comprueba que existan los artefactos esperados, que los JSON sean validos, que las inspecciones esten presentes y que `harmonized_validation.json` no falle.

Puede quedar en `WARNINGS` aunque no haya errores. Los warnings actuales vienen de inspecciones de datos brutos; los homogeneizados estan en `OK`.

## Comando De Ejecucion

Desde la raiz del repositorio:

```bash
/tmp/profecia_data_foundation_venv/bin/snakemake \
  --snakefile workflows/data_foundation/workflow/Snakefile \
  --configfile workflows/data_foundation/config/data_foundation_full_auto.local.yml \
  --config user_settings=workflows/data_foundation/config/user_settings.local.yml \
  --cores 1 \
  --printshellcmds \
  --rerun-incomplete \
  --rerun-triggers mtime \
  --keep-going \
  --nolock
```

Comprobaciones utiles:

```bash
sed -n '1,220p' resources/data_releases/profecia_inputs_full_auto_v0/validation/harmonized_validation.json
sed -n '1,220p' resources/data_releases/profecia_inputs_full_auto_v0/validation/release_validation.json
cd resources/data_releases/profecia_inputs_full_auto_v0 && sha256sum -c checksums.sha256
```

## Contrato De Carpetas

La estructura de la release es parte del contrato.

### `metadata/`

Contiene evidencia de adquisicion:

```text
metadata/{source}/{variable}/request.json
metadata/{source}/file_list.json
metadata/{source}/download_report.json
```

### `raw/`

Contiene los datos fuente descargados o construidos antes de armonizar. Debe evitarse guardar intermediarios pesados generados en `raw/`; para eso debe usarse `work/`.

### `monthly/`

Contiene predictores dinamicos mensuales en grilla comun.

Convencion de nombre:

```text
{source}_{variable}_monthly_0.5deg.nc
```

### `annual/`

Contiene predictores dinamicos anuales en grilla comun.

Convencion de nombre:

```text
{source}_{variable}_annual_0.5deg.nc
```

### `static/`

Contiene moderadores o covariables estaticas en grilla comun.

Ejemplo:

```text
static/hwsd2_soil_0.5deg.nc
```

### `validation/`

Contiene validaciones mecanicas y reportes de calidad:

```text
validation/{source}/{variable}/inspection.json
validation/harmonized_validation.json
validation/release_validation.json
```

### `fair/`

Contiene metadata FAIR inicial. Actualmente hay un descriptor Croissant provisional:

```text
fair/harmonized_netcdf_demo.croissant.jsonld
```

## Como Convertir Esto En Un RO-Crate Reproducible

RO-Crate es un paquete basado en JSON-LD que describe datasets, software, workflows, personas, organizaciones, licencias, contexto y relaciones de procedencia. La pieza central es:

```text
ro-crate-metadata.json
```

La release actual ya tiene la mayoria de ingredientes necesarios:

- archivos de datos organizados por rol (`raw`, `monthly`, `annual`, `static`);
- checksums;
- manifest de variables;
- requests reproducibles por fuente;
- logs y reportes de validacion;
- scripts de workflow versionados;
- configuracion YAML;
- descriptor Croissant parcial.

Para generar un RO-Crate de datos reproducible, el pipeline deberia crear una carpeta, por ejemplo:

```text
resources/data_releases/profecia_inputs_full_auto_v0/ro-crate/
```

con al menos:

```text
ro-crate-metadata.json
README.md
manifest.json
checksums.sha256
metadata/
monthly/
annual/
static/
validation/
fair/
workflow/
config/
```

No necesariamente hay que duplicar todos los datos fisicamente. Hay dos estrategias:

1. RO-Crate autocontenido: copia los datos dentro del crate.
2. RO-Crate referencial: describe archivos locales o remotos mediante rutas/URIs y checksums.

Para reproducibilidad fuerte, el crate autocontenido es mas robusto. Para datasets grandes, el crate referencial es mas practico.

### Entidades Que Deberia Declarar El RO-Crate

El `ro-crate-metadata.json` deberia describir:

- Dataset raiz: `profecia_inputs_full_auto_v0`.
- Cada NetCDF armonizado como `File` o `Dataset`.
- Cada fuente bruta importante como `File`.
- Cada `request.json` como evidencia de adquisicion.
- Cada script como `SoftwareSourceCode`.
- El workflow Snakemake como `ComputationalWorkflow`.
- La ejecucion concreta como `CreateAction`.
- La organizacion/proyecto PROFECIA como `Organization`.
- Personas/autores si aplica como `Person`.
- Licencias por fuente si se conocen.
- Fecha de creacion.
- Version de la config.
- Checksums.

Ejemplo conceptual de entidades:

```json
{
  "@id": "monthly/era5_single_levels_t2m_monthly_0.5deg.nc",
  "@type": "File",
  "name": "ERA5 2m temperature monthly harmonized to 0.5 degree",
  "encodingFormat": "application/x-netcdf",
  "contentSize": "4431206",
  "sha256": "...",
  "variableMeasured": "t2m",
  "spatialCoverage": {
    "@id": "#global-0p5-grid"
  },
  "temporalCoverage": "1982-01/1982-12"
}
```

### Procedencia Recomendada

Cada archivo armonizado deberia declarar:

- `wasDerivedFrom`: archivo raw correspondiente;
- `instrument` o `softwareRequirements`: script `harmonize.py` y version de Python/paquetes;
- `object`: request/config de entrada;
- `result`: NetCDF armonizado;
- checksum del resultado.

En terminos RO-Crate/Schema.org, una ejecucion podria modelarse como `CreateAction`:

```json
{
  "@id": "#run-2026-07-03-data-foundation",
  "@type": "CreateAction",
  "name": "Run PROFECIA data foundation workflow",
  "instrument": [
    {"@id": "workflow/Snakefile"},
    {"@id": "workflow/scripts/common/harmonize.py"}
  ],
  "object": [
    {"@id": "config/data_foundation_full_auto.local.yml"},
    {"@id": "metadata/era5_single_levels/t2m/request.json"}
  ],
  "result": [
    {"@id": "monthly/era5_single_levels_t2m_monthly_0.5deg.nc"}
  ]
}
```

### Checksums En RO-Crate

RO-Crate no impone una unica forma de declarar checksums, pero se recomienda incluirlos como propiedades adicionales o mediante perfiles usados por Workflow RO-Crate. Como minimo:

- mantener `checksums.sha256`;
- declarar checksum por archivo en `ro-crate-metadata.json`;
- validar que ambos coincidan.

### Licencias Y Citacion

La config ya contiene parte de la informacion de proveedor, DOI y landing pages. Para un RO-Crate FAIR mas completo, conviene completar por fuente:

- `license`;
- `citation`;
- `identifier`/DOI;
- `publisher`;
- `url`;
- condiciones de uso.

Esto es especialmente importante para ERA5/CDS, NOAA, PANGAEA, Figshare, Zenodo y FAO HWSD2.

## Como Convertirlo En Un RO-Crate Ejecutable

Un RO-Crate reproducible describe datos, scripts y provenance. Un RO-Crate ejecutable va mas alla: debe permitir re-ejecutar el workflow en otro entorno.

Para eso conviene alinearse con el perfil Workflow RO-Crate / Process Run Crate.

### Incluir El Workflow

El crate deberia incluir:

```text
workflow/Snakefile
workflow/rules/*.smk
workflow/scripts/**/*.py
workflow/envs/*.yml
config/data_foundation_full_auto.local.yml
config/user_settings.template.yml
requirements.txt
```

El `Snakefile` deberia declararse como `ComputationalWorkflow`:

```json
{
  "@id": "workflow/Snakefile",
  "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
  "name": "PROFECIA Data Foundation Snakemake workflow",
  "programmingLanguage": "Snakemake"
}
```

### Declarar Comando De Ejecucion

El RO-Crate ejecutable deberia contener la forma canonica de ejecutar:

```bash
snakemake \
  --snakefile workflow/Snakefile \
  --configfile config/data_foundation_full_auto.local.yml \
  --config user_settings=config/user_settings.local.yml \
  --cores 1 \
  --rerun-incomplete \
  --rerun-triggers mtime
```

En un crate realmente portable, habria que evitar rutas absolutas como `/tmp/profecia_data_foundation_venv/bin/snakemake`. El crate deberia especificar el entorno, no depender de una ruta concreta.

### Entorno De Software

Opciones de reproducibilidad, de menor a mayor robustez:

1. `requirements.txt` con versiones fijadas.
2. Conda/Mamba env YAML completo.
3. Container Docker/Singularity/Apptainer.
4. RO-Crate ejecutable con container declarado como dependencia.

La opcion recomendada para ejecutabilidad real es un contenedor.

Ejemplo de metadata conceptual:

```json
{
  "@id": "container/profecia-data-foundation.sif",
  "@type": "File",
  "encodingFormat": "application/vnd.sylabs.sif",
  "name": "Apptainer image for PROFECIA data foundation"
}
```

Y el workflow podria referenciarlo como requisito de software.

### Inputs Parametrizables

Un RO-Crate ejecutable deberia distinguir:

- config base reproducible;
- config local con secretos o credenciales;
- inputs manuales;
- outputs esperados.

No deberian incluirse secretos reales. En su lugar:

```text
config/user_settings.template.yml
config/secrets.local.example.yml
```

Para fuentes con autenticacion, el crate debe documentar variables de entorno o archivos esperados, no empaquetar credenciales.

### Datos Remotos Vs Datos Incluidos

Hay dos modalidades de ejecucion:

#### Reproducir Desde Cero

El crate contiene workflow/config, pero descarga datos remotos otra vez. Ventajas:

- crate pequeño;
- reproduce adquisicion.

Riesgos:

- URLs cambian;
- APIs cambian;
- credenciales caducan;
- proveedores retiran archivos.

#### Reproducir Desde Datos Congelados

El crate incluye o referencia con checksum los raw ya descargados. Ventajas:

- resultados mas reproducibles;
- no depende tanto de APIs externas.

Riesgos:

- crate grande;
- licencias pueden impedir redistribucion.

Para PROFECIA, una buena estrategia es producir dos crates:

1. Data RO-Crate: release congelada con datos armonizados y raw permitidos.
2. Workflow RO-Crate: codigo/config para reconstruir la release, referenciando datos remotos o raw congelados.

## Propuesta De Implementacion De RO-Crate En Este Repo

Una evolucion natural seria agregar una regla Snakemake:

```text
rule write_ro_crate
```

que produzca:

```text
resources/data_releases/profecia_inputs_full_auto_v0/ro-crate/ro-crate-metadata.json
```

Script sugerido:

```text
workflow/scripts/common/ro_crate_writer.py
```

Entradas:

```text
manifest.json
checksums.sha256
validation/harmonized_validation.json
validation/release_validation.json
config/data_foundation_full_auto.local.yml
workflow/Snakefile
workflow/rules/*.smk
workflow/scripts/**/*.py
```

Salidas:

```text
ro-crate/ro-crate-metadata.json
ro-crate/README.md
```

El escritor de RO-Crate deberia:

1. Leer `manifest.json`.
2. Leer `checksums.sha256`.
3. Crear entidad raiz `Dataset`.
4. Crear entidades para cada archivo raw, monthly, annual, static y validation.
5. Crear entidades para scripts/config/workflow.
6. Crear acciones de procedencia `CreateAction`.
7. Declarar perfiles usados, por ejemplo Dataset RO-Crate y Workflow RO-Crate.
8. Escribir JSON-LD estable y validable.

## Relacion Con Croissant

El pipeline ya escribe:

```text
fair/harmonized_netcdf_demo.croissant.jsonld
```

Croissant y RO-Crate no se excluyen. Se pueden usar juntos:

- Croissant describe el dataset para consumo ML/FAIR, con variables, distribuciones y campos.
- RO-Crate describe el paquete completo, incluyendo workflow, provenance, checksums, scripts, configs y validaciones.

Un RO-Crate puede incluir el descriptor Croissant como un archivo FAIR adicional:

```json
{
  "@id": "fair/harmonized_netcdf_demo.croissant.jsonld",
  "@type": "File",
  "encodingFormat": "application/ld+json",
  "name": "Croissant descriptor for harmonized PROFECIA NetCDF release"
}
```

## Limitaciones Actuales

1. El descriptor Croissant es provisional y no expresa toda la procedencia.
2. `release_validation.json` todavia reporta warnings de inspeccion raw benignos.
3. CO2 armonizado selecciona `level=1`; si se necesita otro nivel o columna integrada, debe configurarse explicitamente.
4. HWSD2 depende de una tabla `HWSD2_LAYERS.csv`; ahora se localiza en una ruta conocida de `/srv/read_only_data`, pero para portabilidad deberia extraerse automaticamente del `.mdb` o empaquetarse como input permitido.
5. No hay todavia `ro-crate-metadata.json` generado automaticamente.
6. No hay contenedor versionado para ejecucion portable completa.
7. Las licencias por fuente deben completarse antes de publicar una release redistribuible.

## Checklist Para Una Release RO-Crate Publicable

Antes de publicar o compartir una release como RO-Crate:

- `validation/harmonized_validation.json` esta en `OK`.
- `validation/release_validation.json` no tiene `errors`.
- `sha256sum -c checksums.sha256` pasa completo.
- `manifest.json` lista todos los `harmonized_files` esperados.
- Las fuentes tienen DOI/URL/proveedor/licencia cuando aplica.
- Los scripts y config usados estan incluidos o referenciados por commit.
- Los secretos locales no estan incluidos.
- El entorno de software esta fijado por requirements, conda o container.
- Se indica si el crate es autocontenido o referencial.
- Se documenta si la reproduccion descarga datos remotos o usa datos congelados.

## Resumen Practico

El pipeline ya produce una release que esta muy cerca de un Data RO-Crate:

- tiene estructura estable;
- tiene manifest;
- tiene checksums;
- tiene validaciones;
- tiene datos por frecuencia temporal;
- tiene metadata FAIR inicial.

Para convertirlo en RO-Crate falta principalmente automatizar `ro-crate-metadata.json` y formalizar entidades de workflow/procedencia. Para convertirlo en ejecutable falta fijar el entorno de software de forma portable y declarar el comando/inputs/outputs segun Workflow RO-Crate.
