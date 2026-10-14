rule write_manifest:
    input:
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
        manifest=MANIFEST
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/manifest.py \
          --config {CONFIG_PATH} \
          --output {output.manifest}
        """


rule write_croissant:
    input:
        requests=REQUESTS,
        raw_outputs=RAW_OUTPUTS,
        manual_inventories=MANUAL_INVENTORIES,
        bundle_file_lists=BUNDLE_FILE_LISTS,
        bundle_download_reports=BUNDLE_DOWNLOAD_REPORTS,
        harmonized_outputs=HARMONIZED_OUTPUTS
    output:
        croissant=CROISSANT
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/croissant_writer.py \
          --config {CONFIG_PATH} \
          --output {output.croissant}
        """


rule write_checksums:
    input:
        manifest=MANIFEST,
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
        checksums=CHECKSUMS
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/checksums.py \
          --base-dir {BASE_DIR} \
          --output {output.checksums} \
          {input.manifest} {input.croissant} {input.requests} {input.raw_outputs} {input.manual_inventories} {input.bundle_file_lists} {input.bundle_download_reports} {input.bundle_raw_dirs} {input.inspections} {input.harmonized_outputs} {input.harmonized_validation}
        """


rule write_ro_crate:
    input:
        manifest=MANIFEST,
        checksums=CHECKSUMS,
        croissant=CROISSANT,
        release_validation=RELEASE_VALIDATION,
        harmonized_validation=HARMONIZED_VALIDATION,
        harmonized_outputs=HARMONIZED_OUTPUTS
    output:
        metadata=RO_CRATE_METADATA,
        readme=RO_CRATE_README,
        preview=RO_CRATE_PREVIEW,
        semantic_validation=SEMANTIC_RO_CRATE_VALIDATION,
        archive=RO_CRATE_ARCHIVE
    shell:
        """
        {PYTHON} {SCRIPT_DIR}/common/ro_crate_writer.py \
          --config {CONFIG_PATH} \
          --workflow-dir {WORKFLOW_DIR} \
          --project-root . \
          --output-dir {RO_CRATE_DIR} \
          --archive {output.archive}
        """
