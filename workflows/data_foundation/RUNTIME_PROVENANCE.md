# Optional execution provenance pilot

The pilot uses Python 3.12, Snakemake 9.26.1 and plugin commit
`e3202263df07e66451d77dec7d916e5c5721e5d5`. Its complete resolved environment is
recorded in `requirements-runtime.lock.txt` (Linux, Python 3.12).

```bash
python3.12 -m venv /tmp/profecia-runtime-venv
/tmp/profecia-runtime-venv/bin/pip install -r workflows/data_foundation/requirements-runtime.lock.txt
/tmp/profecia-runtime-venv/bin/python workflows/data_foundation/runtime_provenance_pilot.py --output-dir /tmp/profecia-runtime-pilot
```

The output directory must be new. The script stages copies of the production
harmonization and validation scripts, a synthetic temperature input, and an
explicit safe configuration. It executes an initial run, an independent clean
run, a no-op invocation and a validation-only rerun. Each report is validated
by the plugin against `provenance-run-crate-0.5`. `evidence.json` records actual
invocation logs/rules, persisted actions, ZIP inventories, checksums, versions,
configuration digest and Git base commit/dirty status. Each script invocation
uses two fresh workspaces. Verification also rebuilt a second virtualenv from
the lockfile and repeated the pilot; this does not test a second OS.

To attach an already generated execution crate when rebuilding a scientific
release, explicitly add this to its configuration:

```yaml
runtime_provenance:
  enabled: true
  archive: /absolute/path/to/workflow-run.zip
```

Absent this section, execution provenance is disabled. The scientific writer
copies the ZIP to `provenance/workflow-run-ro-crate.zip`, records its SHA-256,
and links it to the release workflow action through `subjectOf` / `about`.
The workflow action remains the scientific release action, not the pilot's
execution. Only attach an archive generated for the release being described.

## Verified behavior and adoption limits

On 2026-10-09 all four reports passed required profile validation in each of
two independently installed environments; their scientific outputs were
identical. The largest ZIP member was 42,263 bytes. All 28 existing semantic
tests passed for both the original crate and a temporary scientific crate with
the execution archive attached; its recorded SHA-256 matched the copied ZIP.
No-op reporting retained historical jobs,
and partial reporting retained harmonization while updating validation.
Consequently report timestamps span persisted jobs, not necessarily one
invocation. Invocation logs are the evidence for what executed now.

Shell rules in this pilot use `#snakemake-rule-executor` as instrument; the
plugin does not identify the individual Python libraries as their tools.
The dependency lock provides that software context separately.

The plugin copies data into its ZIP and does not implement PROFECIA's
referential packaging policy. Keep full releases disabled pending upstream
reference-only or inclusion/exclusion support. The pilot rejects archive
members larger than 10 MB; this is a pilot guard, not a production data policy.
The archive inventory must be reviewed before publication. Keep the crate
graphs separate and preserve PROFECIA's scientific semantics.
