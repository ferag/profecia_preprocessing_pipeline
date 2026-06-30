rule build_cds_request:
    output:
        request=f"{BASE_DIR}/metadata/cds_request_{{variable}}_{START_YEAR}_{END_YEAR}.json"
    wildcard_constraints:
        variable=wildcard_regex(ERA5_VARIABLES)
    params:
        dataset=lambda wildcards: variables[wildcards.variable].get(
            "dataset", cds_defaults["dataset"]
        ),
        variable=lambda wildcards: variables[wildcards.variable]["cds_variable"],
        years=",".join(YEARS),
        months=",".join(cds_defaults["months"]),
        time=",".join(cds_defaults["time"]),
        data_format=cds_defaults["data_format"],
        download_format=cds_defaults["download_format"],
        extra_request_json=lambda wildcards: json.dumps(
            {
                "product_type": variables[wildcards.variable].get(
                    "product_type", cds_defaults.get("product_type")
                )
            }
        )
    shell:
        """
        python3 {SCRIPT_DIR}/build_cds_request.py \
          --dataset {params.dataset} \
          --variable {params.variable} \
          --years {params.years} \
          --months {params.months} \
          --time {params.time} \
          --data-format {params.data_format} \
          --download-format {params.download_format} \
          --extra-request-json '{params.extra_request_json}' \
          --output {output.request}
        """


rule download_era5_variable:
    input:
        request=lambda wildcards: request_path(wildcards.variable)
    output:
        raw=f"{BASE_DIR}/raw/era5/{{variable}}/{{variable}}_{START_YEAR}_{END_YEAR}_monthly_raw.nc"
    wildcard_constraints:
        variable=wildcard_regex(ERA5_VARIABLES)
    log:
        f"{BASE_DIR}/logs/download_era5_{{variable}}_{START_YEAR}_{END_YEAR}.log"
    params:
        user_settings=lambda wildcards: config.get("user_settings", "")
    shell:
        """
        python3 {SCRIPT_DIR}/download_era5_t2m.py \
          --request-json {input.request} \
          --output {output.raw} \
          --log {log} \
          --user-settings "{params.user_settings}"
        """


rule prepare_era5_monthly:
    input:
        raw=lambda wildcards: raw_path(wildcards.variable)
    output:
        monthly=f"{BASE_DIR}/monthly/{{variable}}_{START_YEAR}_{END_YEAR}_monthly_0.5deg.nc"
    wildcard_constraints:
        variable=wildcard_regex(ERA5_VARIABLES)
    params:
        source_name=lambda wildcards: variables[wildcards.variable]["cds_variable"]
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py era5-monthly \
          --input {input.raw} \
          --output {output.monthly} \
          --variable {wildcards.variable} \
          --source-name "{params.source_name}"
        """


rule derive_vpd_monthly:
    input:
        t2m=lambda wildcards: monthly_path("t2m"),
        d2m=lambda wildcards: monthly_path("d2m")
    output:
        monthly=f"{BASE_DIR}/monthly/vpd_{START_YEAR}_{END_YEAR}_monthly_0.5deg.nc"
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py derive-vpd \
          --t2m {input.t2m} \
          --d2m {input.d2m} \
          --output {output.monthly}
        """


rule derive_wind_speed_monthly:
    input:
        u10=lambda wildcards: monthly_path("u10"),
        v10=lambda wildcards: monthly_path("v10")
    output:
        monthly=f"{BASE_DIR}/monthly/wind_speed_{START_YEAR}_{END_YEAR}_monthly_0.5deg.nc"
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py derive-wind-speed \
          --u10 {input.u10} \
          --v10 {input.v10} \
          --output {output.monthly}
        """


rule derive_swc_sub_monthly:
    input:
        swvl2=lambda wildcards: monthly_path("swvl2"),
        swvl3=lambda wildcards: monthly_path("swvl3")
    output:
        monthly=f"{BASE_DIR}/monthly/swc_sub_{START_YEAR}_{END_YEAR}_monthly_0.5deg.nc"
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py derive-swc-sub \
          --swvl2 {input.swvl2} \
          --swvl3 {input.swvl3} \
          --output {output.monthly}
        """


rule download_spei_variable:
    output:
        raw=f"{BASE_DIR}/raw/spei/{{variable}}_{START_YEAR}_{END_YEAR}_source.nc"
    wildcard_constraints:
        variable=wildcard_regex(SPEI_VARIABLES)
    params:
        scale=lambda wildcards: wildcards.variable.replace("spei", "")
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py spei-download \
          --output {output.raw} \
          --scale {params.scale} \
          --start-year {START_YEAR} \
          --end-year {END_YEAR}
        """


rule prepare_spei_monthly:
    input:
        raw=f"{BASE_DIR}/raw/spei/{{variable}}_{START_YEAR}_{END_YEAR}_source.nc"
    output:
        monthly=f"{BASE_DIR}/monthly/{{variable}}_{START_YEAR}_{END_YEAR}_monthly_0.5deg.nc"
    wildcard_constraints:
        variable=wildcard_regex(SPEI_VARIABLES)
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py spei-monthly \
          --input {input.raw} \
          --output {output.monthly} \
          --variable {wildcards.variable} \
          --start-year {START_YEAR} \
          --end-year {END_YEAR}
        """


rule prepare_lai_monthly:
    output:
        monthly=f"{BASE_DIR}/monthly/lai_{START_YEAR}_{END_YEAR}_monthly_0.5deg.nc"
    params:
        input_dir=LAI_INPUT_DIR,
        work_dir=f"{BASE_DIR}/work/lai"
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py lai-monthly \
          --input-dir {params.input_dir} \
          --work-dir {params.work_dir} \
          --output {output.monthly} \
          --start-year {START_YEAR} \
          --end-year {END_YEAR}
        """


rule download_co2_monthly_files:
    output:
        marker=f"{BASE_DIR}/work/co2/download_complete.txt"
    params:
        output_dir=f"{BASE_DIR}/raw/co2/monthly_files"
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py co2-download \
          --output-dir {params.output_dir} \
          --marker {output.marker} \
          --start-year {START_YEAR} \
          --end-year {END_YEAR}
        """


rule merge_co2_monthly_files:
    input:
        marker=f"{BASE_DIR}/work/co2/download_complete.txt"
    output:
        merged=f"{BASE_DIR}/work/co2/co2_merged_{START_YEAR}_{END_YEAR}_monthly.nc"
    params:
        input_dir=f"{BASE_DIR}/raw/co2/monthly_files"
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py co2-merge \
          --input-dir {params.input_dir} \
          --output {output.merged}
        """


rule extract_co2_surface_monthly:
    input:
        merged=f"{BASE_DIR}/work/co2/co2_merged_{START_YEAR}_{END_YEAR}_monthly.nc"
    output:
        surface=f"{BASE_DIR}/work/co2/co2_surface_{START_YEAR}_{END_YEAR}_monthly_native.nc"
    params:
        level=co2_config.get("surface_level", 0)
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py co2-surface \
          --input {input.merged} \
          --output {output.surface} \
          --level {params.level}
        """


rule extract_co2_column_monthly:
    input:
        merged=f"{BASE_DIR}/work/co2/co2_merged_{START_YEAR}_{END_YEAR}_monthly.nc"
    output:
        column=f"{BASE_DIR}/work/co2/co2_column_{START_YEAR}_{END_YEAR}_monthly_native.nc"
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py co2-column \
          --input {input.merged} \
          --output {output.column}
        """


rule regrid_co2_monthly:
    input:
        native=f"{BASE_DIR}/work/co2/{{variable}}_{START_YEAR}_{END_YEAR}_monthly_native.nc"
    output:
        monthly=f"{BASE_DIR}/monthly/{{variable}}_{START_YEAR}_{END_YEAR}_monthly_0.5deg.nc"
    wildcard_constraints:
        variable=wildcard_regex(CO2_VARIABLES)
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py co2-regrid \
          --input {input.native} \
          --output {output.monthly}
        """


rule aggregate_monthly_to_annual:
    input:
        monthly=lambda wildcards: monthly_path(wildcards.variable)
    output:
        annual=f"{BASE_DIR}/annual/{{variable}}_{START_YEAR}_{END_YEAR}_annual_0.5deg.nc"
    wildcard_constraints:
        variable=wildcard_regex(FINAL_VARIABLES)
    params:
        aggregation=lambda wildcards: products.get("annual_aggregation", {}).get(wildcards.variable, "mean")
    shell:
        """
        python3 {SCRIPT_DIR}/run_product_step.py annual \
          --input {input.monthly} \
          --output {output.annual} \
          --aggregation {params.aggregation}
        """
