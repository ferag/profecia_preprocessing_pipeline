# Prueba externa de reproducción del preprocesado PROFECIA

Este protocolo cubre exclusivamente la primera parte del pipeline. El entrenamiento
de machine learning se evaluará en otra entrega. Su objetivo es comprobar que un
testeador independiente, usando el paquete entregado, puede regenerar **todos los
productos declarados** y comparar los resultados sin acceder al servidor original.

## Qué se entrega y qué se está probando

Se entrega `ro-crate.zip` de la release `profecia_inputs_all_available_20261009` y
su checksum de transporte. El paquete contiene los NetCDF de referencia, las
entradas efectivas usadas por esta configuración, requests de adquisición,
workflow y scripts, configuración original y portátil, vocabulario, SHACL,
Croissant, manifest, checksums, informes y entorno bloqueado.

La configuración declara 29 variables de fuente y 18 productos derivados. Varias
variables HWSD2 comparten un NetCDF multivariable: el número de archivos no es el
número de variables. Esta release produce 39 archivos científicos distintos.
El inventario autoritativo está en `manifest.json`, campo
`harmonized_files`; todas sus entradas deben existir y volver a generarse.
En el paquete, los archivos científicos y raw incluidos están bajo
`referenced-data/`; el nombre conserva la convención histórica del generador,
pero en esta entrega esos archivos están físicamente incluidos en el ZIP.

La ejecución reutiliza entradas descargadas. NDEP, HFP, CO2 anual, TLU y algunas
capas de suelo utilizan productos canónicos explícitos. Para esas ramas se prueba
su incorporación/armonización, **no** la reconstrucción de los productos canónicos
desde sus fuentes originales. LAI se reconstruye desde los compuestos H5.GZ
incluidos. Ninguna etapa de esta prueba necesita credenciales de proveedores.
Las fuentes históricas adicionales pueden seguir descritas mediante referencias;
`reproduction/input-map.json` identifica los inputs efectivos incluidos.

El plugin de ejecución RO-Crate sigue siendo experimental para archivos grandes.
Esta entrega utiliza el generador científico de PROFECIA y registra el log real y
los tiempos de la ejecución global; no afirma disponer de tiempos observados para
todas las actividades históricas descritas en el grafo.

## Criterios fijados antes de la reproducción

| Comprobación | Criterio de aceptación |
| --- | --- |
| Transporte e inputs | SHA-256 del ZIP y de archivos incluidos coincide |
| Inventario | Mismo conjunto completo de `harmonized_files` |
| Coordenadas | Dimensiones, orden y valores exactos; grilla 360 × 720, 0,5° |
| Valores científicos | `abs(nuevo-ref) <= 1e-6 + 1e-5*abs(ref)` en cada valor |
| Datos ausentes | Máscaras NaN idénticas; infinitos equivalentes |
| Semántica de variable | Unidades y `long_name` iguales |
| Calidad | Validación armonizada `OK`; validación de release sin errores |
| Metadata | Suite semántica, perfil requerido y SHACL conformes |

La igualdad binaria del NetCDF se informa, pero no es requisito: rutas de origen,
atributos de ejecución y bibliotecas pueden cambiar la serialización. La prueba
numérica exige revisar todos los productos, sin reducir la comparación a un muestreo.
No cambiar las tolerancias tras ver los resultados. Este ensayo verifica reproducción
computacional y numérica; no demuestra equivalencia de conclusiones científicas.

## 1. Registrar el entorno y verificar la entrega

Usar Linux x86_64 con Python 3.12, acceso a Internet durante la instalación de
dependencias y espacio suficiente para el ZIP, su extracción, las salidas nuevas
y el entorno. Reservar al menos 50 GB libres y 32 GB RAM; usar un único core en
esta primera evaluación. Registrar CPU, RAM, sistema operativo, fecha, nombre del
testeador y versión de Python en un acta propia. Las extensiones NumPy/NetCDF
requieren que el entorno esté en un filesystem que permita ejecutar binarios.

```bash
sha256sum -c ro-crate.zip.sha256
unzip ro-crate.zip -d profecia-test
cd profecia-test
python3.12 -m venv /tmp/profecia-external-venv
/tmp/profecia-external-venv/bin/pip install -r reproduction/requirements.lock.txt
/tmp/profecia-external-venv/bin/python --version
/tmp/profecia-external-venv/bin/snakemake --version
```

Se espera Python 3.12 y Snakemake 9.26.1. Guardar el log de instalación y
`pip freeze`. El plugin está fijado a un commit Git; la instalación inicial necesita
GitHub. Tras instalar, la reconstrucción de datos funciona sin red.

Verificar los checksums de los archivos descritos en el grafo:

```bash
/tmp/profecia-external-venv/bin/python reproduction/verify_package.py
```

Este comando recorre los archivos **incluidos**, comprueba SHA-256 y rechaza
referencias locales descritas como archivos incluidos que no existen. No pretende
resolver fuentes históricas declaradas como externas.

## 2. Validar el research object de referencia

```bash
PROFECIA_CRATE=. /tmp/profecia-external-venv/bin/python -m unittest discover -s reproduction -p test_ro_crate.py -v
/tmp/profecia-external-venv/bin/rocrate-validator validate --profile-identifier workflow-run-crate-0.5 --requirement-severity REQUIRED .
/tmp/profecia-external-venv/bin/python reproduction/validate_shapes.py
```

Se esperan 28 pruebas correctas, cero incumplimientos requeridos del perfil y
SHACL conforme. Registrar avisos recomendados por separado. Un perfil válido no
sustituye la prueba de reproducción numérica.

## 3. Ejecutar desde cero, sin usar las salidas de referencia

```bash
/tmp/profecia-external-venv/bin/python reproduction/reproduce.py --output-dir reproduced --cores 1
```

`reproduced` debe ser un directorio nuevo. El script usa el código `workflow/`
incluido, crea una configuración portátil y monta las entradas incluidas para
reutilizar las adquisiciones. No copia los NetCDF armonizados de referencia al
directorio de resultados. La preinspección debe rechazar cualquier descarga.
Revisar `reproduced/preflight.log` y `reproduced/execution.log`; conservarlos.
Los NetCDF aparecen en `monthly/`, `annual/` y `static/` dentro de `reproduced`.

## 4. Comprobar cobertura, calidad y resultados

```bash
/tmp/profecia-external-venv/bin/python reproduction/compare_releases.py --reference . --candidate reproduced --report external-comparison.json
PROFECIA_CRATE=reproduced/ro-crate /tmp/profecia-external-venv/bin/python -m unittest discover -s reproduction -p test_ro_crate.py -v
```

La comparación debe terminar con código 0, estado `OK`, inventario completo,
cero máscaras diferentes y diferencias dentro del criterio predeclarado.
Revisar también `reproduced/validation/harmonized_validation.json` y
`reproduced/validation/release_validation.json`. Los warnings de DOI no asignado,
unidades históricas ausentes o provenance externa no autorizan a omitir errores.

La referencia también presenta avisos de valores fuera de rangos esperados en
SSRD, humedad de suelo, nubosidad y SPEI. Por ejemplo, el SPEI contiene extremos
fuera de [-5,5] y SSRD presenta valores ligeramente negativos. Se conservan sin
recorte para no alterar los datos de entrada. Reproducirlos no demuestra que sean
científicamente adecuados: registrar estos avisos y solicitar revisión antes de
usar las variables en un modelo. La validación de release se ejecuta antes del
empaquetado, por lo que su aviso «RO-Crate metadata not available yet» debe
contrastarse con las pruebas posteriores del paquete terminado.

Opcionalmente repetir con otra carpeta nueva (`reproduced-second`) para comprobar
la estabilidad. Una segunda ejecución dentro de la misma carpeta no sustituye
la reproducción desde cero: Snakemake puede reutilizar resultados ya existentes.

## 5. Auditar dos operaciones científicas

En `workflow/scripts/common/derive_swvl12.py` verificar la fórmula
`(7*swvl1 + 21*swvl2)/28`, sus inputs, unidades y salida. En
`workflow/scripts/common/process_lai.py` comprobar `LAI = DN/30`, máscara para DN
fuera de [0,210] y media de compuestos disponibles por mes. Recuperar en el grafo
sus planes, implementaciones, asociaciones a actividades, productos y reportes QC.
Anotar cualquier decisión científica que exija información fuera del paquete.

## 6. Acta del testeador

Entregar: entorno y versiones; logs de instalación y ejecución; resultados de
checksums, suite, perfil y SHACL; `external-comparison.json`; inventario de variables
y productos; tiempo/recursos; dudas de interpretación y fallos encontrados.

Clasificar cada fallo como acceso, entorno, metadata, ejecución, numérico o
científico. Registrar comando exacto, mensaje completo y producto afectado.
Si falta un input o un resultado, marcar la prueba como fallida/incompleta: no
eliminar variables para obtener un `OK`. Distinguir el éxito medido por este
testeador de las verificaciones internas efectuadas por el desarrollador.

El entrenamiento ML y su RO-Crate, features, target, particiones, semillas y
métricas están fuera de esta entrega por decisión del solicitante.
