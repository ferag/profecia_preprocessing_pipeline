# PROFECIA Pipeline 1: Data Foundation

This directory contains a Snakemake data-foundation pipeline for PROFECIA. It
downloads and prepares ERA5/CDS variables, derived predictors, SPEI, local LAI
inputs, and CarbonTracker CO2 products, then writes release metadata.

## What This Pipeline Downloads

The current configuration targets ERA5 monthly means for 1982-2022:

- `t2m`
- `d2m`
- `tp`
- `pev`
- `ssrd`
- `swvl1`
- `swvl2`
- `swvl3`
- `tcc`
- `u10`
- `v10`

It also prepares configured derived/external products:

- `vpd`, `wind_speed`, `swc_sub`
- `spei01`, `spei02`, `spei03`, `spei06`, `spei09`, `spei12`, `spei24`
- `lai` from local THEIA GEOV2-GCM `.h5.gz` inputs
- `co2_surface`, `co2_column` from CarbonTracker

These products are configured in:

```text
workflows/data_foundation/config/data_foundation_demo.yml
```

The release is written to:

```text
resources/data_releases/profecia_inputs_era5_monthly_1982_2022/
```

## LAI Input

LAI is not downloaded automatically. Place the THEIA GEOV2-GCM AVHRR LAI
`.h5.gz` files in the configured local folder:

```text
resources/source_data/lai_h5gz
```

or update `products.lai.input_dir` in the YAML config.

By default `products.lai.enabled` is `auto`: LAI is included only when that
folder exists and contains `.h5.gz` files. Set it to `true` to require LAI and
fail if inputs are missing, or `false` to skip it explicitly.

## Python Environment

This pipeline does not depend on Conda. It uses the active Python environment.

One simple setup with `venv` and `pip` is:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r workflows/data_foundation/requirements.txt
```

## CDS Credentials

Copy the template:

```bash
cp workflows/data_foundation/config/user_settings.template.yml \
   workflows/data_foundation/config/user_settings.local.yml
```

Then edit:

```text
workflows/data_foundation/config/user_settings.local.yml
```

Files matching `workflows/data_foundation/config/*.local.yml` are ignored by
git. The pipeline never creates `.cdsapirc` and never stores credentials in the
repository.

Credential lookup order:

1. `CDSAPI_URL` and `CDSAPI_KEY` environment variables.
2. `user_settings.local.yml` when passed with `--config user_settings=...`.
3. Standard `cdsapi` discovery outside this repository.

## Dry Run

Use dry-run first:

```bash
snakemake \
  --snakefile workflows/data_foundation/workflow/Snakefile \
  --configfile workflows/data_foundation/config/data_foundation_demo.yml \
  --config user_settings=workflows/data_foundation/config/user_settings.local.yml \
  --cores 1 \
  --dry-run \
  --printshellcmds \
  --rerun-incomplete
```

## Real Execution

Run the full configured release:

```bash
snakemake \
  --snakefile workflows/data_foundation/workflow/Snakefile \
  --configfile workflows/data_foundation/config/data_foundation_demo.yml \
  --config user_settings=workflows/data_foundation/config/user_settings.local.yml \
  --cores 1 \
  --printshellcmds \
  --rerun-incomplete
```

The full 1982-2022 multivariable run can be large. For a small test, temporarily
uncomment `selected_variables` in the YAML config and set it to one or two
variables, for example `t2m` and `tp`.

## Outputs

The expanded release contains flat final NetCDF products:

```text
manifest.json
checksums.sha256
monthly/<variable>_1982_2022_monthly_0.5deg.nc
annual/<variable>_1982_2022_annual_0.5deg.nc
metadata/cds_request_<variable>_1982_2022.json
validation/validation_report_<variable>.json
fair/<variable>.croissant.jsonld
raw/
work/
logs/
```

## DAG

To inspect the dependency graph:

```bash
snakemake \
  --snakefile workflows/data_foundation/workflow/Snakefile \
  --configfile workflows/data_foundation/config/data_foundation_demo.yml \
  --dag > data_foundation_era5_1982_2022.dag
```

If Graphviz is installed:

```bash
dot -Tpng data_foundation_era5_1982_2022.dag > data_foundation_era5_1982_2022.png
```

## Connecting To Later Pipelines

Later harmonization and ML workflows should read `manifest.json`, verify
`checksums.sha256`, and consume the documented NetCDF files instead of relying
on ad hoc paths.
