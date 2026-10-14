# Inputs locales portátiles

La configuración `config/data_foundation_all_available_portable.yml` es una copia
de `data_foundation_all_available.yml` con los inputs locales trasladados a
`resources/offline_inputs/profecia_all_available_v1/`. Ejecutar desde la raíz del
repositorio. Las rutas son relativas a esa raíz, no al directorio del YAML.

Los originales no se mueven ni modifican. `stage_offline_inputs.py` copia archivos
reales (no enlaces simbólicos) y verifica cada copia mediante SHA-256 del origen
y destino. `INPUTS_MANIFEST.json` registra tamaños, checksums, rutas originales y
su correspondencia con las rutas portátiles. Los orígenes absolutos quedan como
información histórica en ese manifest, no como requisitos ejecutables del YAML.

## Alcance

Se incluyen los compuestos LAI H5.GZ, los NetCDF canónicos que la configuración
actual utiliza para CO2, TLU, NDEP, HFP, SPEI06 y las capas de suelo/elevación/riqueza,
y el pequeño CSV auxiliar de CO2. Solo se copian los archivos configurados: no todo
el directorio de suelo, ni los raw grandes descargables, ni salidas de releases.

Esta es una adaptación conservadora de rutas: mantiene la selección canónica
existente para no introducir cambios científicos. No significa que todas esas
fuentes carezcan de datos online. Para reducir más el payload hay que conectar y
verificar la reconstrucción de sus productos a partir de fuentes descargadas.

ERA5 y SPEI siguen dependiendo de descargas; ERA5 necesita credenciales externas.
Las credenciales no se copian. Las referencias históricas no utilizadas por esta
configuración se identifican con URN; sus ubicaciones anteriores están registradas
en el manifest, sin prometer que sus archivos estén incluidos.

## Preparar otra copia (sin ejecutar el pipeline)

```bash
python workflows/data_foundation/stage_offline_inputs.py \
  --destination resources/offline_inputs/otra_copia \
  --output-config workflows/data_foundation/config/otra_copia.yml
```

El script rechaza sobrescribir una carpeta o configuración existentes. Si una
copia se interrumpe, conserva los archivos parciales para inspección y no genera
la configuración final hasta verificar todas las copias. Usar nombres nuevos
para repetir o revisar explícitamente la carpeta incompleta.

## Comprobar el plan, sin descargar ni procesar

```bash
snakemake --snakefile workflows/data_foundation/workflow/Snakefile \
  --configfile workflows/data_foundation/config/data_foundation_all_available_portable.yml \
  --cores 1 --dry-run
```

El dry-run debe incluir los jobs de descarga que corresponden; es distinto del
ensayo anterior basado exclusivamente en cache. No ejecuta esos jobs.

Antes de una ejecución real, elegir una release y `release.base_dir` nuevos en
el YAML; no reutilizar carpetas de resultados anteriores. El objetivo `all` usa
todas las variables ya seleccionadas en esta configuración. Esta adaptación no
añade todavía un selector de variables por CLI.

## Empaquetado posterior

`ro_crate_packaging.copy_allowlist` incluye únicamente esta carpeta de inputs.
El generador copiará los datos al ZIP manteniendo las mismas rutas relativas,
sin incluir los raw online ni los resultados científicos grandes. Para esta
configuración, los campos que apuntan a scripts se adaptan a `workflow/` al copiar
el YAML al crate, que es donde se incluye el código. Utilizar la configuración
portátil del propio crate para ejecutar desde su raíz, junto con su entorno.

No se genera ni se publica un nuevo RO-Crate al ejecutar el script de copia.
La autorización para redistribuir cada fuente debe revisarse antes de compartir
el paquete; el manifest de copia no concede licencias adicionales.
