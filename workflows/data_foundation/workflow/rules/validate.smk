rule validate_release:
    input:
        manifest=MANIFEST,
        checksums=CHECKSUMS,
        croissant=CROISSANT,
        requests=REQUESTS,
        raw_outputs=RAW_OUTPUTS,
        manual_inventories=MANUAL_INVENTORIES,
        bundle_file_lists=BUNDLE_FILE_LISTS,
        bundle_download_reports=BUNDLE_DOWNLOAD_REPORTS,
        bundle_raw_dirs=BUNDLE_RAW_DIRS,
        inspections=INSPECTIONS,
        harmonized_outputs=HARMONIZED_OUTPUTS,
        harmonized_validation=HARMONIZED_VALIDATION
    output:
        summary=RELEASE_VALIDATION
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/validate_release.py \
          --config {CONFIG_PATH} \
          --output {output.summary}
        """
