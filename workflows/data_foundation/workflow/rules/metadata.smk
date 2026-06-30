rule write_demo_croissant:
    input:
        monthly=lambda wildcards: monthly_path(wildcards.variable),
        annual=lambda wildcards: annual_path(wildcards.variable)
    output:
        croissant=f"{BASE_DIR}/fair/{{variable}}.croissant.jsonld"
    wildcard_constraints:
        variable=wildcard_regex(SUPPORTED_VARIABLES)
    params:
        release_id=RELEASE_ID,
        year_range=f"{START_YEAR}-{END_YEAR}",
        long_name=lambda wildcards: SUPPORTED_VARIABLE_METADATA.get(wildcards.variable, {}).get("long_name", wildcards.variable),
        source_unit=lambda wildcards: SUPPORTED_VARIABLE_METADATA.get(wildcards.variable, {}).get("source_unit", "")
    shell:
        """
        python3 {SCRIPT_DIR}/write_demo_croissant.py \
          --output {output.croissant} \
          --release-id {params.release_id} \
          --variable {wildcards.variable} \
          --year {params.year_range} \
          --long-name "{params.long_name}" \
          --source-unit "{params.source_unit}" \
          --monthly-path {input.monthly} \
          --annual-path {input.annual}
        """


rule write_manifest:
    input:
        monthly=MONTHLY_NETCDFS,
        annual=ANNUAL_NETCDFS,
        requests=REQUESTS,
        validations=VALIDATION_REPORTS,
        croissants=CROISSANTS
    output:
        manifest=MANIFEST
    params:
        release_id=RELEASE_ID,
        base_dir=BASE_DIR,
        start_year=START_YEAR,
        end_year=END_YEAR,
        dataset=cds_defaults["dataset"],
        variables_json=VARIABLES_JSON,
        derived_or_external_json=DERIVED_OR_EXTERNAL_JSON
    shell:
        """
        python3 {SCRIPT_DIR}/write_manifest.py \
          --output {output.manifest} \
          --release-id {params.release_id} \
          --base-dir {params.base_dir} \
          --start-year {params.start_year} \
          --end-year {params.end_year} \
          --dataset {params.dataset} \
          --variables-json '{params.variables_json}' \
          --derived-or-external-json '{params.derived_or_external_json}' \
          --monthly-paths {input.monthly} \
          --annual-paths {input.annual} \
          --request-paths {input.requests} \
          --validation-paths {input.validations} \
          --croissant-paths {input.croissants}
        """


rule write_checksums:
    input:
        monthly=MONTHLY_NETCDFS,
        annual=ANNUAL_NETCDFS,
        requests=REQUESTS,
        manifest=MANIFEST,
        validations=VALIDATION_REPORTS,
        croissants=CROISSANTS
    output:
        checksums=CHECKSUMS
    params:
        base_dir=BASE_DIR
    shell:
        """
        python3 {SCRIPT_DIR}/write_checksums.py \
          --output {output.checksums} \
          --base-dir {params.base_dir} \
          {input.monthly} {input.annual} {input.requests} {input.manifest} {input.validations} {input.croissants}
        """
