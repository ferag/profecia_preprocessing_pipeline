rule harmonize_monthly_netcdf:
    input:
        raw=lambda wildcards: variable_config(wildcards.source, wildcards.variable)["canonical_reference_path"] if variable_has_canonical_reference(wildcards.source, wildcards.variable) else raw_path(wildcards.source, wildcards.variable)
    output:
        monthly=f"{BASE_DIR}/monthly/{{source}}_{{variable}}_monthly_0.5deg.nc"
    params:
        input_arg=lambda wildcards: "" if variable_has_canonical_reference(wildcards.source, wildcards.variable) else f"--input {raw_path(wildcards.source, wildcards.variable)}"
    wildcard_constraints:
        source=wildcard_regex([source for source, _ in HARMONIZED_MONTHLY_PAIRS]),
        variable=wildcard_regex([variable for _, variable in HARMONIZED_MONTHLY_PAIRS])
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/harmonize.py netcdf \
          --config {CONFIG_PATH} \
          --source {wildcards.source} \
          --variable {wildcards.variable} \
          {params.input_arg} \
          --output {output.monthly} \
          --frequency monthly
        """


rule harmonize_annual_netcdf:
    input:
        raw=lambda wildcards: variable_config(wildcards.source, wildcards.variable)["canonical_reference_path"] if variable_has_canonical_reference(wildcards.source, wildcards.variable) else raw_path(wildcards.source, wildcards.variable)
    output:
        annual=f"{BASE_DIR}/annual/{{source}}_{{variable}}_annual_0.5deg.nc"
    params:
        input_arg=lambda wildcards: "" if variable_has_canonical_reference(wildcards.source, wildcards.variable) else f"--input {raw_path(wildcards.source, wildcards.variable)}"
    wildcard_constraints:
        source=wildcard_regex([source for source, _ in HARMONIZED_ANNUAL_PAIRS]),
        variable=wildcard_regex([variable for _, variable in HARMONIZED_ANNUAL_PAIRS])
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/harmonize.py netcdf \
          --config {CONFIG_PATH} \
          --source {wildcards.source} \
          --variable {wildcards.variable} \
          {params.input_arg} \
          --output {output.annual} \
          --frequency annual
        """


rule harmonize_hwsd2_static:
    input:
        report=lambda wc: [] if hwsd2_uses_canonical_reference() else f"{BASE_DIR}/metadata/hwsd2/download_report.json",
        raw_dir=lambda wc: [] if hwsd2_uses_canonical_reference() else f"{BASE_DIR}/raw/hwsd2",
        canonical=lambda wc: [str(Path(sources["hwsd2"]["canonical_reference_dir"]) / sources["hwsd2"].get("canonical_reference_template", "{variable}_1982_2022_monthly_0.5deg.nc").format(variable=variable)) for source, variable in selected_pairs() if source == "hwsd2"] if hwsd2_uses_canonical_reference() else []
    output:
        static=f"{BASE_DIR}/static/hwsd2_soil_0.5deg.nc"
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/harmonize.py hwsd2-static \
          --config {CONFIG_PATH} \
          --output {output.static}
        """


rule derive_swvl12_monthly:
    input:
        swvl1=lambda wc: [] if has_canonical_reference("monthly", "swvl1-2") else f"{BASE_DIR}/monthly/era5_single_levels_swvl1_monthly_0.5deg.nc",
        swvl2=lambda wc: [] if has_canonical_reference("monthly", "swvl1-2") else f"{BASE_DIR}/monthly/era5_single_levels_swvl2_monthly_0.5deg.nc"
    output:
        monthly=f"{BASE_DIR}/monthly/swvl1-2_{{period}}_monthly_0.5deg.nc"
    params:
        canonical=canonical_reference("monthly", "swvl1-2")
    wildcard_constraints:
        period=r"[0-9]{4}_[0-9]{4}"
    shell:
        """
        if [ -n "{params.canonical}" ]; then
          {PYTHON} {SCRIPT_DIR}/common/repackage_local.py annual \
            --variable swvl1-2 --output {output.monthly} \
            --canonical-reference "{params.canonical}"
        else
          {PYTHON} {SCRIPT_DIR}/common/derive_swvl12.py \
            --swvl1 {input.swvl1} \
            --swvl2 {input.swvl2} \
            --output {output.monthly}
        fi
        """


rule derive_vpd_monthly:
    input:
        t2m=lambda wc: [] if has_canonical_reference("monthly", "vpd") else f"{BASE_DIR}/monthly/era5_single_levels_t2m_monthly_0.5deg.nc",
        d2m=lambda wc: [] if has_canonical_reference("monthly", "vpd") else f"{BASE_DIR}/monthly/era5_single_levels_d2m_monthly_0.5deg.nc"
    output:
        monthly=f"{BASE_DIR}/monthly/vpd_{{period}}_monthly_0.5deg.nc"
    params:
        canonical=canonical_reference("monthly", "vpd")
    wildcard_constraints:
        period=r"[0-9]{4}_[0-9]{4}"
    shell:
        """
        if [ -n "{params.canonical}" ]; then
          {PYTHON} {SCRIPT_DIR}/common/repackage_local.py annual \
            --variable vpd --output {output.monthly} \
            --canonical-reference "{params.canonical}"
        else
          {PYTHON} {SCRIPT_DIR}/common/derive_products.py vpd \
            --t2m {input.t2m} --d2m {input.d2m} --output {output.monthly}
        fi
        """

rule derive_subswc_monthly:
    input:
        swvl2=f"{BASE_DIR}/monthly/era5_single_levels_swvl2_monthly_0.5deg.nc",
        swvl3=f"{BASE_DIR}/monthly/era5_single_levels_swvl3_monthly_0.5deg.nc"
    output:
        monthly=f"{BASE_DIR}/monthly/subswc_{{period}}_monthly_0.5deg.nc"
    wildcard_constraints:
        period=r"[0-9]{4}_[0-9]{4}"
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/derive_products.py subswc \
          --swvl2 {input.swvl2} --swvl3 {input.swvl3} --output {output.monthly}
        """

rule derive_wind_monthly:
    input:
        u10=lambda wc: [] if has_canonical_reference("monthly", "wind") else f"{BASE_DIR}/monthly/era5_single_levels_u10_monthly_0.5deg.nc",
        v10=lambda wc: [] if has_canonical_reference("monthly", "wind") else f"{BASE_DIR}/monthly/era5_single_levels_v10_monthly_0.5deg.nc"
    output:
        monthly=f"{BASE_DIR}/monthly/wind_{{period}}_monthly_0.5deg.nc"
    params:
        canonical=canonical_reference("monthly", "wind")
    wildcard_constraints:
        period=r"[0-9]{4}_[0-9]{4}"
    shell:
        """
        if [ -n "{params.canonical}" ]; then
          {PYTHON} {SCRIPT_DIR}/common/repackage_local.py annual \
            --variable wind --output {output.monthly} \
            --canonical-reference "{params.canonical}"
        else
          {PYTHON} {SCRIPT_DIR}/common/derive_products.py wind \
            --u10 {input.u10} --v10 {input.v10} --output {output.monthly}
        fi
        """

rule derive_spei06_univariable_monthly:
    input:
        spei06=lambda wc: canonical_reference("monthly", "spei06_univariable") if has_canonical_reference("monthly", "spei06_univariable") else f"{BASE_DIR}/monthly/speibase_v211_spei06_monthly_0.5deg.nc"
    output:
        monthly=f"{BASE_DIR}/monthly/spei06_univariable_{{period}}_monthly_0.5deg.nc"
    params:
        canonical=canonical_reference("monthly", "spei06_univariable"),
        spei06_arg=lambda wc: "" if has_canonical_reference("monthly", "spei06_univariable") else f"--spei06 {BASE_DIR}/monthly/speibase_v211_spei06_monthly_0.5deg.nc"
    wildcard_constraints:
        period=r"[0-9]{4}_[0-9]{4}"
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/derive_products.py spei06-univariable \
          {params.spei06_arg} --output {output.monthly} \
          --canonical-reference "{params.canonical}"
        """


rule repackage_tlu_annual:
    input:
        src=lambda wc: canonical_reference("annual", "tlu") if has_canonical_reference("annual", "tlu") else "resources/source_data/annual/tlu_1982_2022_annual_0.5deg.nc"
    output:
        annual=f"{BASE_DIR}/annual/tlu_1982_2022_annual_0.5deg.nc"
    params:
        canonical=canonical_reference("annual", "tlu"),
        input_arg=lambda wc: "" if has_canonical_reference("annual", "tlu") else "--input resources/source_data/annual/tlu_1982_2022_annual_0.5deg.nc"
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/repackage_local.py annual \
          {params.input_arg} --variable tlu --output {output.annual} \
          --canonical-reference "{params.canonical}"
        """

rule prepare_gmted2010_elevation:
    input:
        report=f"{BASE_DIR}/metadata/gmted2010/download_report.json",
        raw_dir=f"{BASE_DIR}/raw/gmted2010"
    output:
        static=f"{BASE_DIR}/work/gmted2010/elevation_0.5deg.nc",
        inspection=f"{BASE_DIR}/validation/gmted2010/elevation/inspection.json"
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/sources/gmted2010.py prepare \
          --archive {input.raw_dir}/mn30_grd.zip \
          --output {output.static} --report {output.inspection}
        """


rule repackage_static_monthly:
    input:
        src=lambda wc: canonical_reference("monthly", wc.variable) if has_canonical_reference("monthly", wc.variable) else static_monthly_source(wc.variable)
    output:
        monthly=f"{BASE_DIR}/monthly/{{variable}}_1982_2022_monthly_0.5deg.nc"
    params:
        canonical=lambda wc: canonical_reference("monthly", wc.variable),
        input_arg=lambda wc: "" if has_canonical_reference("monthly", wc.variable) else f"--input {static_monthly_source(wc.variable)}"
    wildcard_constraints:
        variable=r"elevation|richness|ph|bulk|cec|clay|sand|silt|soc|total_n"
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/repackage_local.py static-monthly \
          {params.input_arg} --variable {wildcards.variable} --output {output.monthly} \
          --start-year 1982 --end-year 2022 \
          --canonical-reference "{params.canonical}"
        """


rule process_lai_monthly:
    input:
        src_dir=lambda wc: [] if has_canonical_reference("monthly", "lai") else config.get("local_input_paths", {}).get("lai_h5gz", "resources/source_data/lai_h5gz")
    output:
        monthly=f"{BASE_DIR}/monthly/lai_1982_2022_monthly_0.5deg.nc"
    params:
        canonical=canonical_reference("monthly", "lai")
    shell:
        """
        if [ -n "{params.canonical}" ]; then
          {PYTHON} {SCRIPT_DIR}/common/repackage_local.py annual \
            --variable lai --output {output.monthly} \
            --canonical-reference "{params.canonical}"
        else
          {PYTHON} {SCRIPT_DIR}/common/process_lai.py \
            --input-dir {input.src_dir} --output {output.monthly} \
            --start-year 1982 --end-year 2022
        fi
        """


rule derive_co2_annual:
    input:
        monthly=lambda wc: [] if has_canonical_reference("annual", "co2") else f"{BASE_DIR}/monthly/carbontracker_co2_co2_monthly_0.5deg.nc",
        gml=lambda wc: [] if has_canonical_reference("annual", "co2") else config.get("local_input_paths", {}).get("co2_gml_csv", "/srv/read_only_data/NANA/human/RAW/co2/co2_mm_gl.csv"),
        canonical=lambda wc: canonical_reference("annual", "co2") if has_canonical_reference("annual", "co2") else []
    output:
        annual=f"{BASE_DIR}/annual/co2_1982_2022_annual_0.5deg.nc"
    params:
        canonical=canonical_reference("annual", "co2"),
        monthly_arg=lambda wc: "" if has_canonical_reference("annual", "co2") else f"--monthly-co2 {BASE_DIR}/monthly/carbontracker_co2_co2_monthly_0.5deg.nc",
        gml_arg=lambda wc: "" if has_canonical_reference("annual", "co2") else f"--gml-csv {config.get('local_input_paths', {}).get('co2_gml_csv', '/srv/read_only_data/NANA/human/RAW/co2/co2_mm_gl.csv')}"
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/derive_co2_annual.py \
          {params.monthly_arg} \
          {params.gml_arg} \
          --output {output.annual} \
          --start-year 1982 --end-year 2022 \
          --canonical-reference "{params.canonical}"
        """


rule validate_harmonized:
    input:
        harmonized=HARMONIZED_OUTPUTS
    output:
        report=HARMONIZED_VALIDATION
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/validate_harmonized.py \
          --output {output.report} \
          {input.harmonized}
        """
