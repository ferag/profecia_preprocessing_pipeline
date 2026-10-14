# Final RO-Crate navigation examples

These compact examples use identifiers present in the generated `profecia_inputs_all_available_v0` crate. Omitted properties remain available in `ro-crate-metadata.json`.

## Root research object

```json
{
  "@id": "./",
  "@type": ["Dataset", "dcat:Dataset", "prov:Entity"],
  "identifier": "profecia_inputs_all_available_v0",
  "mainEntity": {"@id": "workflow/Snakefile"},
  "mentions": [{"@id": "#run-profecia-inputs-all-available-v0"}],
  "conformsTo": [
    {"@id": "https://w3id.org/ro/crate/1.1"},
    {"@id": "https://w3id.org/workflowhub/workflow-ro-crate/1.0"},
    {"@id": "https://w3id.org/ro/wfrun/process/0.5"},
    {"@id": "https://w3id.org/ro/wfrun/workflow/0.5"}
  ]
}
```

## Main workflow and formal interface

```json
{
  "@id": "workflow/Snakefile",
  "@type": ["ComputationalWorkflow", "File", "SoftwareSourceCode"],
  "version": "1.0",
  "profecia:baseGitCommit": "5b023208977cbdc74d7ec66f7e587e552e78d04c",
  "programmingLanguage": {"@id": "https://snakemake.github.io/"},
  "input": [{"@id": "#configfile"}],
  "output": [{"@id": "#harmonized-release"}, {"@id": "#release-metadata"}]
}
```

## Global run

```json
{
  "@id": "#run-profecia-inputs-all-available-v0",
  "@type": ["CreateAction", "prov:Activity"],
  "instrument": {"@id": "workflow/Snakefile"},
  "agent": {"@id": "#person-fernando-aguilar-gomez"},
  "prov:wasAssociatedWith": {"@id": "#workflow-snakemake"},
  "result": {"@id": "#dataset-harmonized"},
  "environment": {"@id": "#run-environment-not-recorded"},
  "profecia:recordingStatus": "completed-artifacts-times-unknown"
}
```

## Individual activity

```json
{
  "@id": "#action-derived-climate-vpd-harmonize",
  "@type": ["CreateAction", "prov:Activity"],
  "object": [
    {"@id": "referenced-data/monthly/era5_single_levels_t2m_monthly_0.5deg.nc"},
    {"@id": "referenced-data/monthly/era5_single_levels_d2m_monthly_0.5deg.nc"},
    {"@id": "workflow/scripts/common/derive_products.py"}
  ],
  "result": [{"@id": "referenced-data/monthly/vpd_1982_2022_monthly_0.5deg.nc"}],
  "prov:qualifiedAssociation": [{"@id": "#association-action-derived-climate-vpd-harmonize-prep-derived-vpd"}]
}
```

## Qualified PROV association

```json
{
  "@id": "#association-action-derived-climate-vpd-harmonize-prep-derived-vpd",
  "@type": "prov:Association",
  "prov:agent": {"@id": "#workflow-snakemake"},
  "prov:hadPlan": {"@id": "#prep-derived-vpd"}
}
```

## Generic preprocessing plan

```json
{
  "@id": "#prep-derived-vpd",
  "@type": ["profecia:PreprocessingStep", "prov:Plan"],
  "profecia:stepType": [{"@id": "https://w3id.org/profecia/vocab/preprocessing-step-type/derived-variable"}],
  "profecia:formula": "vpd = max(es(t2m) - ea(d2m), 0)",
  "profecia:parameter": [{"@id": "#prep-derived-vpd-parameter-vapour-pressure-scale"}],
  "profecia:implementedBy": {"@id": "workflow/scripts/common/derive_products.py"},
  "profecia:relatedWorkflowAction": [{"@id": "#action-derived-climate-vpd-harmonize"}]
}
```

## Plan with multiple operation types

```json
{
  "@id": "#prep-lai-h5gz-to-monthly-netcdf",
  "@type": ["profecia:PreprocessingStep", "prov:Plan"],
  "profecia:stepType": [
    {"@id": "https://w3id.org/profecia/vocab/preprocessing-step-type/format-conversion"},
    {"@id": "https://w3id.org/profecia/vocab/preprocessing-step-type/masking"},
    {"@id": "https://w3id.org/profecia/vocab/preprocessing-step-type/temporal-aggregation"}
  ],
  "profecia:missingDataPolicy": "Digital numbers outside [0, 210] are masked before monthly aggregation."
}
```

## Harmonized NetCDF product and variable

```json
{
  "@id": "referenced-data/monthly/vpd_1982_2022_monthly_0.5deg.nc",
  "@type": ["DataCubeProduct", "Dataset", "File", "dcat:Dataset", "dcat:Distribution", "prov:Entity"],
  "variableMeasured": [{"@id": "#variable-derived-climate-vpd"}],
  "prov:wasGeneratedBy": [{"@id": "#action-derived-climate-vpd-harmonize"}],
  "profecia:wasPreprocessedBy": [{"@id": "#prep-derived-vpd"}]
}
```

```json
{
  "@id": "#variable-derived-climate-vpd",
  "@type": "PropertyValue",
  "propertyID": "vpd",
  "unitText": "kPa",
  "unitCode": {"@id": "http://qudt.org/vocab/unit/KiloPA"},
  "provider": {"@id": "#org-ifca-csic"}
}
```

## Source and access mechanism

```json
{
  "@id": "#source-era5-single-levels",
  "@type": ["Dataset", "dcat:Dataset", "prov:Entity"],
  "identifier": "reanalysis-era5-single-levels-monthly-means",
  "provider": [
    {"@id": "https://ror.org/014w0fd65"},
    {"@id": "#org-copernicus-climate-change-service"}
  ],
  "conditionsOfAccess": "Authentication required."
}
```

## Aggregate validation report

```json
{
  "@id": "validation/harmonized_validation.json",
  "@type": ["File", "dcat:Distribution", "prov:Entity"],
  "about": {"@id": "#dataset-harmonized"},
  "prov:wasGeneratedBy": [{"@id": "#action-validate-harmonized-profecia-inputs-all-available-v0"}]
}
```

Following these links yields the requested path: root → workflow → global run/activity → qualified association → plan → input/output → variable/source → aggregate validation.
