#!/usr/bin/env python3
"""Re-execute the packaged preprocessing workflow without original host paths."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("reproduced"))
    parser.add_argument("--cores", type=int, default=1)
    args = parser.parse_args()
    root = Path.cwd()
    base = args.output_dir.resolve()
    if base.exists():
        raise RuntimeError("Choose a new output directory, never the reference release")
    config = yaml.safe_load((root / "reproduction/config.yml").read_text())
    config["release"]["base_dir"] = str(base)
    config["release"]["id"] += "_reproduced"
    config["ro_crate_packaging"].update(copy_harmonized_outputs=False, copy_raw_inputs=False, copy_allowlist=[])
    config.pop("reproduction_assets", None)
    base.mkdir(parents=True)
    raw = root / "referenced-data/raw"
    if not raw.is_dir():
        raw = root / "raw"
    if not raw.is_dir():
        raise FileNotFoundError("The package does not contain raw inputs")
    (base / "raw").symlink_to(raw, target_is_directory=True)
    (base / "metadata").mkdir()
    for source in (root / "metadata").iterdir():
        if source.is_dir():
            shutil.copytree(source, base / "metadata" / source.name)
    config_path = base / "reproduction.yml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    command = [str(Path(sys.executable).with_name("snakemake")), "--snakefile", "workflow/Snakefile",
               "--configfile", str(config_path), "--cores", str(args.cores), "--rerun-triggers", "mtime"]
    dry = subprocess.run(command + ["--dry-run"], capture_output=True, text=True)
    (base / "preflight.log").write_text(dry.stdout + dry.stderr)
    dry.check_returncode()
    if any(f"rule {name}:" in dry.stdout + dry.stderr for name in ("download_api_variable", "download_source_bundle")):
        raise RuntimeError("Offline reproduction unexpectedly requires a download")
    with (base / "execution.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    validation = json.loads((base / "validation/harmonized_validation.json").read_text())
    if validation["status"] != "OK":
        raise RuntimeError("Harmonized validation did not pass")
    print(base)


if __name__ == "__main__":
    main()
