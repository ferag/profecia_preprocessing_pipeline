rule validate_release:
    input:
        monthly=MONTHLY_NETCDFS,
        annual=ANNUAL_NETCDFS,
        requests=REQUESTS,
        manifest=MANIFEST,
        validations=VALIDATION_REPORTS,
        croissants=CROISSANTS,
        checksums=CHECKSUMS
    output:
        summary=VALIDATE_LOG
    params:
        base_dir=BASE_DIR
    shell:
        """
        python3 {SCRIPT_DIR}/validate_release.py \
          --base-dir {params.base_dir} \
          --manifest {input.manifest} \
          --checksums {input.checksums} \
          --validation-reports {input.validations} \
          --croissants {input.croissants} \
          --monthly-netcdfs {input.monthly} \
          --annual-netcdfs {input.annual} \
          --cds-requests {input.requests} \
          --output-log {output.summary}
        """
