rule inspect_netcdf:
    input:
        monthly=lambda wildcards: monthly_path(wildcards.variable)
    output:
        report=f"{BASE_DIR}/validation/validation_report_{{variable}}.json"
    wildcard_constraints:
        variable=wildcard_regex(FINAL_VARIABLES)
    log:
        f"{BASE_DIR}/logs/inspect_{{variable}}_{START_YEAR}_{END_YEAR}.log"
    params:
        expected_names=lambda wildcards: ",".join(
            [
                wildcards.variable,
                FINAL_VARIABLE_METADATA.get(wildcards.variable, {}).get(
                    "cds_variable",
                    FINAL_VARIABLE_METADATA.get(wildcards.variable, {}).get("source_variable", wildcards.variable),
                ),
            ]
        ),
        expected_unit=lambda wildcards: FINAL_VARIABLE_METADATA.get(wildcards.variable, {}).get("source_unit", ""),
        expected_steps=len(YEARS) * len(cds_defaults["months"]),
        min_value=lambda wildcards: FINAL_VARIABLE_METADATA.get(wildcards.variable, {}).get("min_reasonable_value", -1e30),
        max_value=lambda wildcards: FINAL_VARIABLE_METADATA.get(wildcards.variable, {}).get("max_reasonable_value", 1e30)
    shell:
        """
        python3 {SCRIPT_DIR}/inspect_netcdf.py \
          --input {input.monthly} \
          --output {output.report} \
          --log {log} \
          --variable {wildcards.variable} \
          --expected-names {params.expected_names} \
          --expected-unit "{params.expected_unit}" \
          --expected-time-steps {params.expected_steps} \
          --min-reasonable-value {params.min_value} \
          --max-reasonable-value {params.max_value}
        """
