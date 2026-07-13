rule build_request:
    output:
        request=f"{BASE_DIR}/metadata/{{source}}/{{variable}}/request.json"
    wildcard_constraints:
        source=wildcard_regex([source for source, _ in API_PAIRS]),
        variable=wildcard_regex([variable for _, variable in API_PAIRS])
    params:
        adapter=lambda wildcards: adapter(wildcards.source)
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/sources/{params.adapter}.py build-request \
          --config {CONFIG_PATH} \
          --source {wildcards.source} \
          --variable {wildcards.variable} \
          --output {output.request}
        """


rule download_api_variable:
    input:
        request=lambda wildcards: request_path(wildcards.source, wildcards.variable)
    output:
        raw=f"{BASE_DIR}/raw/{{source}}/{{variable}}/{{filename}}"
    wildcard_constraints:
        source=wildcard_regex([source for source, _ in API_PAIRS]),
        variable=wildcard_regex([variable for _, variable in API_PAIRS])
    log:
        f"{BASE_DIR}/logs/{{source}}_{{variable}}_{{filename}}.download.log"
    params:
        adapter=lambda wildcards: adapter(wildcards.source),
        user_settings=lambda wildcards: config.get("user_settings", "")
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/sources/{params.adapter}.py download \
          --config {CONFIG_PATH} \
          --source {wildcards.source} \
          --variable {wildcards.variable} \
          --request {input.request} \
          --output {output.raw} \
          --log {log} \
          --user-settings "{params.user_settings}" \
          > {log} 2>&1
        """


rule check_manual_variable:
    output:
        inventory=f"{BASE_DIR}/metadata/{{source}}/{{variable}}/manual_inventory.json"
    wildcard_constraints:
        source=wildcard_regex([source for source, _ in MANUAL_PAIRS]),
        variable=wildcard_regex([variable for _, variable in MANUAL_PAIRS])
    params:
        adapter=lambda wildcards: adapter(wildcards.source)
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/sources/{params.adapter}.py check-manual-input \
          --config {CONFIG_PATH} \
          --source {wildcards.source} \
          --variable {wildcards.variable} \
          --output {output.inventory}
        """


rule build_source_file_list:
    output:
        file_list=f"{BASE_DIR}/metadata/{{source}}/file_list.json"
    wildcard_constraints:
        source=wildcard_regex(BUNDLE_SOURCES)
    params:
        adapter=lambda wildcards: adapter(wildcards.source)
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/sources/{params.adapter}.py build-file-list \
          --config {CONFIG_PATH} \
          --source {wildcards.source} \
          --output {output.file_list}
        """


rule download_source_bundle:
    input:
        file_list=lambda wildcards: source_file_list_path(wildcards.source)
    output:
        report=f"{BASE_DIR}/metadata/{{source}}/download_report.json",
        raw_dir=directory(f"{BASE_DIR}/raw/{{source}}")
    wildcard_constraints:
        source=wildcard_regex(BUNDLE_SOURCES)
    params:
        adapter=lambda wildcards: adapter(wildcards.source)
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/sources/{params.adapter}.py download \
          --config {CONFIG_PATH} \
          --file-list {input.file_list} \
          --output-dir {output.raw_dir} \
          --report {output.report}
        """
