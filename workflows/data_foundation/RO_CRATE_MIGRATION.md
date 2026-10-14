# PROFECIA RO-Crate semantic migration

This document records the model and identifier decisions for the data-foundation RO-Crate generated on 2026-08-27. It is an implementation note, not a claim that unknown historical execution facts were recovered.

## Profile family

| Layer | Declared profile | Decision |
|---|---|---|
| Base | `https://w3id.org/ro/crate/1.1` | Common base required by the selected workflow profiles. |
| Workflow description | `https://w3id.org/workflowhub/workflow-ro-crate/1.0` | Stable Workflow RO-Crate profile; the 1.1 line is still a draft. |
| Process execution | `https://w3id.org/ro/wfrun/process/0.5` | Compatible with Workflow Run Crate 0.5. |
| Workflow execution | `https://w3id.org/ro/wfrun/workflow/0.5` | Highest auto-detected validation profile. |
| Main workflow | Bioschemas ComputationalWorkflow 1.0-RELEASE | Declared on `workflow/Snakefile`, not as a root RO-Crate profile. |
| Parameters | Bioschemas FormalParameter 1.0-RELEASE | Declared on formal input/output parameter entities. |
| PROFECIA steps | `https://w3id.org/profecia/profile/preprocessing-step/1.0` | Local semantic extension validated by SHACL. |

RELIANCE terms are reused for spatial/temporal coverage, processors and quality links, but RELIANCE conformance is deliberately not declared. The crate has not been shown to satisfy the full RELIANCE profile. Croissant is a complementary discovery descriptor for harmonized products and is not a replacement for RO-Crate provenance.

Primary specifications: [RO-Crate 1.1](https://www.researchobject.org/ro-crate/1.1/), [Workflow RO-Crate 1.0](https://about.workflowhub.eu/Workflow-RO-Crate/), [Workflow Run Crate 0.5](https://www.researchobject.org/workflow-run-crate/profiles/workflow_run_crate/), and [MLCommons Croissant 1.0](http://mlcommons.org/croissant/1.0).

## PROFECIA model

`profecia:PreprocessingStep` is the only preprocessing plan class and is an `rdfs:subClassOf prov:Plan`. Operation kinds are SKOS concepts linked with `profecia:stepType`; they are not OWL subclasses. A `CreateAction`/`prov:Activity` represents execution. The software file is an instrument and implementation, while Snakemake is the `prov:SoftwareAgent`.

```json
{
  "@id": "#prep-derived-vpd",
  "@type": ["profecia:PreprocessingStep", "prov:Plan"],
  "profecia:stepType": {"@id": "https://w3id.org/profecia/vocab/preprocessing-step-type/derived-variable"},
  "profecia:formula": "vpd = max(es(t2m) - ea(d2m), 0)",
  "profecia:implementedBy": {"@id": "workflow/scripts/common/derive_products.py"}
}
```

```json
{
  "@id": "#association-action-derived-climate-vpd-harmonize-prep-derived-vpd",
  "@type": "prov:Association",
  "prov:agent": {"@id": "#workflow-snakemake"},
  "prov:hadPlan": {"@id": "#prep-derived-vpd"}
}
```

`prov:hadPlan` appears only on qualified associations. For activities, `object` equals `prov:used` and `result` equals `prov:generated`; outputs link back with `prov:wasGeneratedBy`. Each materialized file has at most one canonical generator.

## FAIR4prep assessment

The inspected artifact is the proof-of-concept example linked from the 2026 FAIR4prep article ([DOI 10.1038/s41597-026-07206-2](https://doi.org/10.1038/s41597-026-07206-2)) and stored in the [FAIR4prep example repository](https://github.com/ferag/FAIR4prep). Its exact namespace is `https://w3id.org/fair4prep#`.

| Item | Inspection result |
|---|---|
| Version | No vocabulary version or formal release was stated in the example/repository inspected. |
| Status | Proof-of-concept JSON-LD example, not a published RDF ontology with documented domains/ranges. |
| License | The article states CC BY-NC-ND 4.0; the inspected repository had no separate `LICENSE` file. |
| Classes used | `PreprocessingProtocol`, `AnnotationFeatureSelectionStep`, `AuditingStep`, `DataAugmentationStep`, `DataSplittingStrategyStep`, `DatasetDocumentation`, `FeatureNormalizationStep`, `FormatConversionStep`, `LabelAdaptationStep`, `MetadataTraceabilityStep`. |
| Properties used | `preprocessingProtocol`, `usesStep`, `hasDatasetDocumentation`, `parameters`, `sampleIdentifiers`, `mapsToPreprocessingStage`, `blockPurpose`, `expectedDataType`, `appliesTo`, `subsetOf`, `selectionCriteria`, `subsetManifest`. |

Direct reuse was rejected because stability, licensing of the vocabulary artifact and formal semantics were not sufficiently documented. PROFECIA uses conservative, non-equivalence `rdfs:seeAlso` links from `appliesTo`, `parameter` and `qualityControl`; no `owl:equivalentClass`, `owl:equivalentProperty`, or FAIR4prep conformance claim is made.

## Redundancy policy

| Canonical statement | Compatibility mirror | Rule |
|---|---|---|
| `name` | `dcterms:title` | Values must be identical when both occur. |
| `description` | `dcterms:description` | Values must be identical. |
| `license` | `dcterms:license` | Same SPDX entity. |
| `isPartOf` | `dcterms:isPartOf` | Same target. |
| `temporalCoverage` | `dcterms:temporal` | Same interval. |
| `profecia:formula` | `mathExpression` | Same expression. |
| `object` | `prov:used` | Equal sets on activities. |
| `result` | `prov:generated` | Equal sets on activities. |

DCAT download/access/landing URLs are emitted only for actual HTTP(S) URLs. A relative path is never relabelled as a download URL. `PropertyValue.value` stores a value, never a unit; units use `unitText` and verified QUDT `unitCode`, or an explicit `profecia:unitStatus` when unknown.

## Identifier and behavioural migration

The machine-readable table is [`metadata/vocabulary/identifier-migration.csv`](metadata/vocabulary/identifier-migration.csv). The main behavioural corrections are:

- one generic step class plus a 24-concept bilingual SKOS hierarchy;
- one HWSD2 static harmonization activity and eight real monthly per-variable activities, each with one result;
- one aggregate harmonized validation activity/report;
- scripts as instruments, people/organizations as Schema.org agents, and Snakemake as a PROV software agent;
- flattened formal and step parameters with stable identifiers;
- a captured-runtime fixture and an explicit “not recorded” environment for the historical run;
- a Croissant 1.0 descriptor restricted to harmonized products.

Compact final examples for the root, main workflow, global run, activity, association, generic and multi-type plans, NetCDF product, variable, source and validation report are in [`RO_CRATE_EXAMPLES.md`](RO_CRATE_EXAMPLES.md).

## Validation snapshot

Validation environment versions are pinned in `requirements-validation.txt`.

| Check | Result on 2026-08-27 |
|---|---|
| Project regression suite | 28/28 passed (27 requested checks plus HWSD2/aggregate regression). |
| JSON-LD expansion | Passed with RDFLib. |
| PROFECIA common and conditional SHACL | Conforms; zero results with pySHACL 0.40.1. |
| RO-Crate/Workflow Run required rules | Passed; zero issues with roc-validator 0.11.3, auto-profile `workflow-run-crate-0.5`. |
| RO-Crate recommended rules | 269 non-blocking `SHOULD` notices, all due to absent historical end times or unrecorded software versions/absolute local publication identifiers. |
| Croissant | Passed with mlcroissant 1.1.0, without errors or warnings. |
| Internal semantic validator | `OK`, no errors or warnings. |

No CI configuration existed in the repository, so no existing CI job could be extended. The repeatable local command is `python3 -m unittest workflows.data_foundation.tests.test_ro_crate -v`; external validation uses the pinned validation requirements.

Validation results are generated locally and are not versioned. Run the semantic
tests against your own scientific crate by setting `PROFECIA_CRATE` before
running `python -m unittest workflows.data_foundation.tests.test_ro_crate`.

## Human review still required

- Capture real `startTime`, `endTime`, duration, Snakemake/Python/Conda/container versions and digest in `metadata/workflow-run.json` on a future execution.
- Publish from a clean Git tree. In a dirty tree, `profecia:baseGitCommit` is intentionally used instead of asserting an exact `profecia:gitCommit`.
- Confirm missing source units for local HWSD2 monthly variables; the crate currently states that they were not recorded and invents none.
- Resolve the manifest warning for `carbontracker_co2/co2`: the derived annual CO2 product is present, but the selected source-family product is not listed as a harmonized manifest output.
- Replace the composite Figshare/Zenodo provider node with separately verified provider records if curatorial evidence becomes available.
- Assign persistent public landing/download URLs, DOI/citation metadata and release dates during repository publication.
- Review dataset/data-product licences against every upstream provider before public redistribution; metadata/code licences are already separate SPDX entities.
