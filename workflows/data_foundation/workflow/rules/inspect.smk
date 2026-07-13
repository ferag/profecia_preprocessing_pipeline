rule inspect_netcdf:
    input:
        raw=lambda wildcards: raw_path(wildcards.source, wildcards.variable)
    output:
        report=f"{BASE_DIR}/validation/{{source}}/{{variable}}/inspection.json"
    wildcard_constraints:
        source=wildcard_regex([source for source, _ in API_PAIRS]),
        variable=wildcard_regex([variable for _, variable in API_PAIRS])
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/netcdf_inspector.py \
          --input {input.raw} \
          --source {wildcards.source} \
          --variable {wildcards.variable} \
          --config {CONFIG_PATH} \
          --output {output.report}
        """
