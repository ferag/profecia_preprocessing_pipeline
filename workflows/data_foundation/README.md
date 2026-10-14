# PROFECIA Pipeline 1: Data Foundation

This workflow is the data-foundation prototype for PROFECIA. It is organized
around one central YAML config, one source adapter per provider family, and one
Snakemake step per selected source/variable output.

The manifest is the main contract for later pipelines. Pipeline 2 should read a
selected release manifest instead of relying on ad hoc paths. This structure is
also intended to make later Data Release RO-Crate export straightforward.

## Design

- `config/data_foundation_demo.yml` declares the release, source families, access
  modes, and selected variables.
- `workflow/scripts/sources/` contains provider adapters such as `era5.py` and
  `lai_geov2.py`.
- `workflow/scripts/common/` contains shared inspection, manifest, checksums,
  Croissant, and config-loading code.
- Snakemake rules use `{source}` and `{variable}` wildcards where possible and
  write into a stable release layout.

## API And Manual Sources

Sources declare an `access_mode`:

- `api`: Snakemake builds a provider request and downloads a raw data file.
- `manual`: Snakemake registers files that the user has already placed locally.
- `manual_or_internal`: Snakemake registers a local or internally stored
  derived dataset whose public automated download has not been verified.

The current executable demo selects the ERA5 single-level monthly predictor set
for 1982:

```yaml
selected_variables:
  - source: era5_single_levels
    variable: t2m
  - source: era5_single_levels
    variable: d2m
  # ... tp, pev, ssrd, swvl1, swvl2, swvl3, tcc, u10, v10
```

This keeps LAI out of the default run because LAI is a manual local input in
this prototype.

## RO-Crate Release Model

The generated RO-Crate is a reproducible data-release crate for ROHub. The root dataset is `PROFECIA Data Foundation Demo Release`; `workflow/Snakefile` is the main computational workflow entity for Workflow RO-Crate compatibility.

The official release products are harmonized NetCDF files under `monthly/`, `annual/`, or `static/`. Raw/source files under `raw/` are provenance inputs only. The manifest, Croissant descriptor, checksums, validation reports, source requests, workflow code, environment files, and safe config templates are packaged or referenced so the release can be regenerated.

License handling is split deliberately: RO-Crate metadata uses CC0-1.0, derived harmonized data products use CC-BY-4.0, workflow/code uses Apache-2.0, and external source datasets remain governed by the original provider terms. Real credentials, local secrets, `.env`, `.netrc`, and private local settings must not be included; use `config/secrets.local.example.yml` and `config/user_settings.template.yml` as safe templates.

To validate a release, review `validation/harmonized_validation.json`, then run:

```bash
sha256sum -c resources/data_releases/profecia_inputs_demo_v0/checksums.sha256
```

A release-level validation error is expected if harmonized products or `validation/harmonized_validation.json` are absent, because harmonized NetCDF products are the official outputs. Missing DOI and optional Git metadata are warnings for the demo release, not publication blockers.

Citation is provisional until a DOI or ROHub URL exists. Use the release title, release ID, Fernando Aguilar Gomez, CSIC, and the eventual DOI/URL once assigned.

## LAI Is Manual

GEOV2 / GEOV2-GCM AVHRR LAI is not downloaded through this prototype. The
GEODES STAC catalog exposes some metadata, but the desired LAI product is not
treated as an API-downloadable dataset here.

LAI is configured as:

```yaml
sources:
  geov2_lai:
    access_mode: manual
    access_protocol: manual_local_input
    raw_input_dir: data/manual/GEOV2_GCM_LAI/
```

To activate LAI registration, add it to `selected_variables`:

```yaml
selected_variables:
  - source: era5_single_levels
    variable: t2m
  - source: geov2_lai
    variable: lai
```

Then place matching files, for example `THEIA_GEOV2_R01_AVHRR_LAI_19881115.h5`,
in:

```text
data/manual/GEOV2_GCM_LAI/
```

The LAI adapter writes:

```text
resources/data_releases/profecia_inputs_demo_v0/metadata/geov2_lai/lai/manual_inventory.json
```

If no files are found, the workflow fails with instructions. It does not call a
LAI API.

## CO2 From NOAA

The `carbontracker_co2` source uses public HTTP URLs and does not require
credentials. It combines two NOAA inputs:

- CarbonTracker CT2022 monthly spatial CO2 fields:
  `https://gml.noaa.gov/aftp/products/carbontracker/co2/CT2022/molefractions/co2_total_monthly/`
- NOAA GML global monthly mean CO2 CSV:
  `https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_mm_gl.csv`

The current adapter downloads CarbonTracker monthly NetCDF files, extracts the
native `co2` variable, concatenates it over time, and stores the NOAA GML CSV
beside the raw output for later temporal extension/offset preprocessing. The
full 2000-2021 monthly request is not selected by default because it can be a
large download.

To test only CO2, use:

```yaml
selected_variables:
  - source: carbontracker_co2
    variable: co2
```

The existing annual extension method from the old preprocessing script should
be added as a later processing step after the raw CarbonTracker download.

## Nitrogen Deposition From PANGAEA

The `ndep_tian2022` source uses Tian et al. (2022), HaNi: A Historical dataset
of Anthropogenic Nitrogen Inputs to the terrestrial biosphere (PANGAEA.942069,
DOI `10.1594/PANGAEA.942069`). It downloads two public PANGAEA ZIP files:

- NHx-N deposition:
  `https://download.pangaea.de/dataset/942069/files/ndep_nhx.zip`
- NOy-N deposition:
  `https://download.pangaea.de/dataset/942069/files/ndep_noy.zip`

No credentials are required. The files are large, roughly 2.9 GB each. The
adapter computes:

```text
ndep = ndep_nhx + ndep_noy
```

It converts the native `g N per cell yr-1` values to `kg N/ha/yr`, aggregates
from the native 1/12 degree grid to 0.5 degree by averaging, and extrapolates
missing target years after the source period with the per-pixel OLS method from
the prototype preprocessing script.

To test only N deposition, use:

```yaml
selected_variables:
  - source: ndep_tian2022
    variable: ndep
```

## Human Footprint From Figshare And Zenodo

The `hfp_mu_hengl` source builds annual Human Footprint Index maps from:

- Mu et al. (2022), Figshare article `16571064`, DOI
  `10.6084/m9.figshare.16571064`
- Hengl (2022), Zenodo record `6636562`, DOI `10.5281/zenodo.6636562`

The adapter uses the Figshare API endpoint
`https://api.figshare.com/v2/articles/16571064` to list files and retrieve
`download_url` values. It does not scrape the HTML landing page. The article
verified 2000-2018, while the current Figshare API response also lists
2019-2022; the adapter records the current available years in `request.json`
before download.

Hengl/Zenodo provides the 1982-1999 extrapolated maps with URLs like:

```text
https://zenodo.org/records/6636562/files/hfootprint_1982_1km.tif?download=1
```

The adapter downloads source rasters, resamples them to the 0.5 degree WGS84
target grid with bilinear reprojection, applies the additive bias correction
from the prototype script to 1982-1999, and writes:

```text
hfp_1982_2022_annual_0.5deg.nc
```

This step requires `rasterio` in the runtime environment and can download many
large files. To test only HFP, use:

```yaml
selected_variables:
  - source: hfp_mu_hengl
    variable: hfp
```

## Tropical Livestock Units From LivestockMap

The `livestockmap` source is configured as `manual_or_internal`. A public,
directly downloadable dataset named exactly `LivestockMap annual 1961-2021` has
not been verified, so the workflow does not try to reconstruct it from FAOSTAT
and GLW automatically.

Place the manually provided or internally stored archive at:

```text
data/manual/LivestockMap/LivestockMap.zip
```

The archive is expected to contain annual livestock density rasters for cattle,
buffalo, horse, sheep, and goats. The adapter checks the configured species/year
patterns and records an inventory. Conceptually, PROFECIA TLU is:

```text
TLU = cattle + buffalo + 0.8 * horse + 0.1 * sheep + 0.1 * goats
```

The source is available through 2021, while the PROFECIA target period currently
ends in 2022. The config keeps the 2022 temporal extension policy as
`TODO_CONFIRM`; accepted future policies include holding 2021, using a
user-provided 2022 layer, or cropping to 2021.

To test only TLU registration, use:

```yaml
selected_variables:
  - source: livestockmap
    variable: tlu
```

## Static Soil From HWSD2

The `hwsd2` source downloads the two FAO HWSD2 raw archives once per release:

```text
HWSD2_DB.zip
HWSD2_RASTER.zip
```

These raw files are shared by the static soil variables `sand`, `clay`, `silt`,
`ph`, `soc`, `total_n`, `bulk`, and `cec`. The data-foundation step registers
and downloads the raw source files; the scientific derivation of
`hwsd2_soil_0.5deg.nc` should be handled by the existing preprocessing code.

The current preprocessing script at
`/srv/read_only_data/NANA/scripts/current/preprocess_soil_0p5.py` expects the
downloaded ZIP contents to be extracted first, specifically `HWSD2.bil` and
`HWSD2_LAYERS.csv`. It uses the shallowest/topsoil HWSD2 layer and writes a
360 x 720 global 0.5 degree NetCDF. The matching verifier is
`/srv/read_only_data/NANA/scripts/current/verify_soil_outputs.py`.

To test only HWSD2 acquisition, use one or more of the shared-source variables:

```yaml
selected_variables:
  - source: hwsd2
    variable: sand
  - source: hwsd2
    variable: clay
```

The workflow writes:

```text
resources/data_releases/profecia_inputs_demo_v0/metadata/hwsd2/file_list.json
resources/data_releases/profecia_inputs_demo_v0/metadata/hwsd2/download_report.json
resources/data_releases/profecia_inputs_demo_v0/raw/hwsd2/HWSD2_DB.zip
resources/data_releases/profecia_inputs_demo_v0/raw/hwsd2/HWSD2_RASTER.zip
```

No credentials are required.

## Static Elevation

`elevation` is configured as an authenticated USGS/GTOPO30 source:

```yaml
selected_variables:
  - source: gtopo30
    variable: elevation
```

The public config references a local secrets file but does not contain
credentials. Create the real ignored file from the example:

```bash
cp workflows/data_foundation/config/secrets.local.example.yml \
   workflows/data_foundation/config/secrets.local.yml
```

Then fill:

```yaml
usgs_m2m:
  username: "actual_username"
  token: "actual_token"
```

`USGS_USERNAME` and `USGS_M2M_TOKEN` override the local secrets file when both
are present. Tokens are not written to logs, manifests, metadata, checksums, or
Croissant outputs.

The adapter can authenticate to USGS M2M. Automated file download still needs a
confirmed M2M product/entity selection for GTOPO30.

## Run The Demo

Dry-run:

```bash
snakemake \
  --snakefile workflows/data_foundation/workflow/Snakefile \
  --configfile workflows/data_foundation/config/data_foundation_demo.yml \
  --cores 1 \
  --dry-run \
  --printshellcmds
```

If this workspace is mounted with execution restrictions, compiled Python
packages such as NumPy may fail from a repository-local `.venv` with an error
like `failed to map segment from shared object`. In that case, create the
runtime environment on `/tmp` and run Snakemake with that environment first on
`PATH`:

```bash
python3 -m venv /tmp/profecia_data_foundation_venv
/tmp/profecia_data_foundation_venv/bin/python -m pip install -r workflows/data_foundation/requirements.txt
```

Then run the workflow with:

```bash
PATH=/tmp/profecia_data_foundation_venv/bin:$PATH \
/tmp/profecia_data_foundation_venv/bin/snakemake \
  --snakefile workflows/data_foundation/workflow/Snakefile \
  --configfile workflows/data_foundation/config/data_foundation_demo.yml \
  --config user_settings=workflows/data_foundation/config/user_settings.local.yml \
  --cores 1 \
  --printshellcmds \
  --rerun-incomplete \
  --nolock
```

Real execution:

```bash
snakemake \
  --snakefile workflows/data_foundation/workflow/Snakefile \
  --configfile workflows/data_foundation/config/data_foundation_demo.yml \
  --cores 1 \
  --printshellcmds
```

If `.snakemake/locks` is not writable because of a previous privileged run, fix
the directory ownership or add `--nolock` for a single-user local run.

## CDS Credentials

The ERA5 adapter never writes credentials. It checks, in order:

1. `CDSAPI_URL` and `CDSAPI_KEY`
2. `workflows/data_foundation/config/user_settings.local.yml` when passed with
   `--config user_settings=...`
3. Standard `cdsapi` discovery such as `~/.cdsapirc`

Local settings files are ignored by git:

```bash
cp workflows/data_foundation/config/user_settings.template.yml \
   workflows/data_foundation/config/user_settings.local.yml
```

## Add A New ERA5 Variable

Add a variable under `sources.era5_single_levels.variables`, for example:

```yaml
tp:
  cds_name: total_precipitation
  long_name: Total precipitation
  role: predictor
  source_units: m
  expected_min: 0
  expected_max: 2
  years: ["1982"]
  months: ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
  time: ["00:00"]
  data_format: netcdf
  download_format: unarchived
  output_filename: tp_1982_monthly_raw.nc
```

Then add it to `selected_variables`.

## Output Layout

The release is written to:

```text
resources/data_releases/profecia_inputs_demo_v0/
├── manifest.json
├── checksums.sha256
├── metadata/
│   └── {source}/{variable}/
├── raw/
│   └── {source}/{variable}/
├── validation/
│   ├── {source}/{variable}/inspection.json
│   └── release_validation.json
├── fair/
│   └── harmonized_netcdf_demo.croissant.jsonld
└── logs/
```

## Later Connections

Execution provenance is available as an opt-in isolated pilot. See
[RUNTIME_PROVENANCE.md](RUNTIME_PROVENANCE.md) for the locked environment,
reproduction command, attachment configuration and verified limitations.

The Croissant descriptor is currently lightweight and describes the selected
release files. Later work can expand it for ML-specific metadata in Pipeline 2.

The manifest, checksums, inspection reports, Croissant descriptor, and validation
reports now feed a referential RO-Crate generated by the metadata stage:

```text
resources/data_releases/profecia_inputs_demo_v0/ro-crate/ro-crate-metadata.json
resources/data_releases/profecia_inputs_demo_v0/ro-crate.zip
```

The first crate milestone is intentionally hybrid: workflow code, safe config
templates/examples, release metadata, validation reports, checksums, and the
Croissant descriptor are copied into the crate archive for ROHub import. Large
NetCDF and raw artifacts remain referential and are described with paths, file
sizes, and checksums rather than copied into the crate. The generated
`ro-crate/README.md` contains the manual ROHub publication checklist, including
validation, secret inspection, archive upload, metadata entry, and recording the
resulting ROHub URL or DOI. Workflow Run provenance from
`snakemake-report-plugin-rocrate` can be added later as an optional complement
once that plugin has stable release and usage documentation.

## Full preprocessing reproduction release

The complete, offline-data reproduction protocol is documented in
[EXTERNAL_TESTER_GUIDE.md](EXTERNAL_TESTER_GUIDE.md). This release is an explicit
exception to the default referential packaging: it includes the effective raw
and canonical inputs and all 39 scientific products. It covers preprocessing
only, not machine learning or reconstruction of canonical inputs upstream.
Use Python 3.12 and `requirements-full.lock.txt`; `execute_full_release.py`
creates a new release from the acquisition cache without reusing harmonized
outputs. `prepare_reproduction_assets.py` snapshots additional effective inputs.
The delivered crate contains an offline `reproduction/reproduce.py` runner and
an exhaustive numerical comparator with predeclared tolerances.

For portable local inputs without running a release, see
[OFFLINE_INPUTS.md](OFFLINE_INPUTS.md). The new
`config/data_foundation_all_available_portable.yml`, generated by
`stage_offline_inputs.py` (not stored in Git), uses verified regular-file
copies under `resources/offline_inputs/profecia_all_available_v1/`, with paths
relative to the repository root. The original config and source datasets remain
unchanged. Its packaging allowlist includes these inputs but excludes online raw
downloads and large generated scientific outputs.

For a standalone starter archive, see [STARTER_CRATE_GUIDE.md](STARTER_CRATE_GUIDE.md).
`build_starter_crate.py` packages the portable configuration, pinned environment,
workflow snapshot, source links and effective offline inputs without running the
pipeline. The included `run.py` defaults to a dry-run, supports `--variables all`
and subsets with dependency resolution, and requires `--execute` for downloads
and preprocessing. It describes a Workflow RO-Crate, not an observed Run Crate.

Elevation can optionally be reconstructed from GMTED2010 mean/30-arc-second
ArcGrid instead of its canonical input; see
[GMTED2010_INTEGRATION.md](GMTED2010_INTEGRATION.md) and
`enable_gmted2010.py`, which generates `config/data_foundation_gmted2010_trial.yml`.
The stable profile and previously
delivered ZIP are unchanged. Real-data numerical equivalence remains untested.
