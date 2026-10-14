# PROFECIA: RO-Crate de arranque

Este paquete permite planificar y ejecutar el preprocesado fuera del servidor
original. No contiene resultados de una nueva ejecución ni es un Provenance Run
Crate: sus perfiles describen el paquete y el workflow, no jobs observados.
La fase de machine learning está fuera de alcance.

## Contenido y política de mínimo

Se incluye solo el workflow necesario, su lanzador, configuración, entorno
bloqueado y los inputs offline efectivos. No se incluyen cache de descargas,
resultados de releases ni credenciales. `SOURCES.json` enlaza los proveedores y
los endpoints originales declarados en la configuración. Esos enlaces no se
confunden con los archivos canónicos PROFECIA derivados de esas fuentes.

El perfil online descarga ERA5 y SPEI; HWSD2 conserva la adquisición que actualmente
solicita el DAG, aunque la armonización seleccionada usa campos canónicos.
ERA5 necesita cuenta, token y aceptación de condiciones del dataset.

Se incluyen LAI H5.GZ originales y los productos canónicos que siguen siendo
inputs de esta implementación (TLU, riqueza, elevación, suelo, CO2, NDEP, HFP,
SPEI06), más el CSV auxiliar de CO2. **Mínimo compatible con el pipeline actual**
no significa mínimo teórico: algunas fuentes originales son online pero su
reconstrucción equivalente al producto canónico aún no está verificada. No se
eliminan esas dependencias ni se cambia silenciosamente la ciencia para reducir
el ZIP. `SOURCES.json` explica los motivos. Los checkpoints canónicos se aportan
como inputs, no como resultados regenerados desde sus raw.

Los términos de los proveedores y la autorización para redistribuir derivados
deben revisarse antes de publicar el paquete. Este crate no concede nuevas
licencias. Las URLs se registran desde el repositorio, no implican que se haya
probado la descarga de cada recurso al construir el paquete.

## 1. Extraer e instalar

Linux x86_64, Python 3.12. Usar rutas sin espacios, caracteres no ASCII ni
metacaracteres de shell (limitación de los templates actuales). Reservar espacio
para las descargas y archivos extraídos además del ZIP; el tamaño del paquete no
es una estimación del espacio total de ejecución.

```bash
sha256sum -c profecia-starter.zip.sha256
unzip profecia-starter.zip -d /tmp/profecia-starter
python3.12 -m venv /tmp/profecia-starter-env
source /tmp/profecia-starter-env/bin/activate
pip install -r /tmp/profecia-starter/requirements.lock.txt
pip check
python /tmp/profecia-starter/run.py --verify
```

La instalación necesita Internet y acceso al commit Git del plugin presente en el
lock; el reporter experimental sigue sin activarse para esta ejecución.

## 2. Seleccionar variables y revisar el plan

```bash
python /tmp/profecia-starter/run.py --list-variables
python /tmp/profecia-starter/run.py --output-dir /ruta/mi-release --variables all
```

Por defecto, `run.py` hace **solo dry-run**: no descarga ni procesa. Crea el
directorio de salida, una copia de la configuración y `plan.log`. La salida debe
estar fuera del paquete extraído. Se puede invocar el script desde cualquier cwd.

También se puede pedir un subconjunto:

```bash
python /tmp/profecia-starter/run.py --output-dir /ruta/prueba-vpd --variables vpd
```

VPD añade T2M y D2M automáticamente. Otras variables derivadas añaden sus
dependencias declaradas. Los nombres `sand`, `clay`, etc. seleccionan el producto
mensual; `hwsd2/sand` selecciona explícitamente la variable de fuente estática.
`co2` selecciona el CO2 anual; `carbontracker_co2/co2` selecciona la rama de fuente.
Seleccionar un subconjunto no elimina archivos ya incluidos en el ZIP.

## 3. Credenciales y ejecución real (a cargo del usuario)

Configurar CDS fuera del paquete, siguiendo
https://cds.climate.copernicus.eu/how-to-api . No introducir tokens en chats,
archivos compartidos ni en la configuración empaquetada.

```bash
export CDSAPI_URL="https://cds.climate.copernicus.eu/api"
read -rsp "Token CDS: " CDSAPI_KEY
export CDSAPI_KEY
python /tmp/profecia-starter/run.py --output-dir /ruta/mi-release --variables all --execute --cores 1
```

El mismo directorio puede usarse para pasar del plan a la ejecución, o reanudar
tras un fallo, solo si su configuración coincide exactamente. Para cambiar la
selección o comprobar otra reproducción, elegir una carpeta nueva. El lanzador
no admite sobrescribir carpetas ajenas. Mantener `execution.log` y `execution.yml`.

El objetivo `all` corresponde a las 29 entradas fuente y 18 productos derivados
de esta configuración, que producen 39 archivos científicos distintos.
Revisar `validation/harmonized_validation.json` (esperado `OK`) y
`validation/release_validation.json` (ningún error; interpretar avisos). Las
descargas pueden fallar por acceso, cambios de proveedor o condiciones de uso:
un dry-run correcto no garantiza la disponibilidad remota.

## 4. Evaluación externa

Compartir el ZIP y su checksum, nunca las credenciales. El testeador debe extraer
su propia copia, instalar el lock, verificar el payload y ejecutar desde una
carpeta nueva. La equivalencia numérica de las ramas online se comprueba después
de la ejecución contra la referencia; construir o validar este crate no la
demuestra. No se afirma que la selección de variables o las descargas hayan sido
validadas científicamente solo porque su DAG sea planificable.

## Elevation: nueva ruta optativa GMTED2010

La cita aportada y el archivo histórico `mn30_grd` identifican GMTED2010 mean
30 arc-seconds; la etiqueta GTOPO30 de los scripts antiguos es incorrecta.
Se ha añadido una ruta de descarga pública y remuestreo bilineal optativa.
Consultar `workflows/data_foundation/GMTED2010_INTEGRATION.md` en el repositorio.
El perfil estable y el ZIP ya entregado siguen usando el canónico; esa ruta nueva
no está dentro de aquel snapshot ni su equivalencia numérica está confirmada.
Los nuevos builds con el perfil optativo pueden omitir el canónico de elevación,
pero requieren una prueba científica independiente antes de adoptarlos como
sustitutos estables. No se ha ejecutado la descarga ni el reprocesado del DEM real.
