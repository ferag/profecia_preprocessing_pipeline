#!/usr/bin/env python3
"""Create and execute a fresh all-available release from audited cached inputs."""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("workflows/data_foundation/config/data_foundation_all_available.yml"))
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--cores", type=int, default=1)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    old_base = config["release"]["base_dir"]
    base = Path("resources/data_releases") / args.release_id
    if base.exists():
        raise RuntimeError(f"Refusing to overwrite existing release: {base}")
    base.mkdir(parents=True)
    (base / "metadata").mkdir()
    # Copy metadata, not scientific outputs: all scientific rules must execute.
    for source in args.cache.joinpath("metadata").iterdir():
        if source.is_dir():
            shutil.copytree(source, base / "metadata" / source.name)
    # Link only inputs actually used by this configuration, excluding large
    # historical raw products replaced by explicit canonical references.
    refs = config.get("canonical_reference_products", {})
    for selected in config["selected_variables"]:
        name, variable = selected["source"], selected["variable"]
        source = config["sources"][name]
        var = source["variables"][variable]
        if source.get("data_files"):
            target = base / "raw" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.symlink_to((args.cache / "raw" / name).resolve(), target_is_directory=True)
        elif source.get("access_mode") in ("api", "http") and not var.get("canonical_reference_path"):
            if name == "carbontracker_co2" and refs.get("annual/co2"):
                continue
            relative = Path("raw") / name / variable / var["output_filename"]
            cached = args.cache / relative
            if not cached.is_file():
                raise FileNotFoundError(cached)
            target = base / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(cached.resolve())
    def relocate(value):
        if isinstance(value, dict):
            return {key: relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        return value.replace(old_base, base.as_posix()) if isinstance(value, str) else value
    config = relocate(config)
    config["release"].update(id=args.release_id, base_dir=base.as_posix(), status="external-reproduction-reference")
    config["ro_crate_packaging"].update(copy_harmonized_outputs=True, copy_raw_inputs=True, archive_compression="stored")
    config_path = Path("workflows/data_foundation/config") / f"{args.release_id}.yml"
    if config_path.exists():
        raise RuntimeError(f"Configuration already exists: {config_path}")
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    # A complete delivery needs the effective canonical inputs and offline runner,
    # not only the downloaded raw files and final outputs.
    subprocess.run([sys.executable, str(Path(__file__).with_name("prepare_reproduction_assets.py")),
                    "--config", str(config_path)], check=True)
    snake = str(Path(sys.executable).with_name("snakemake"))
    command = [snake, "--snakefile", "workflows/data_foundation/workflow/Snakefile", "--configfile", str(config_path),
               "--cores", str(args.cores), "--rerun-triggers", "mtime"]
    dry = subprocess.run(command + ["--dry-run"], capture_output=True, text=True)
    (base / "metadata/preflight.log").write_text(dry.stdout + dry.stderr)
    dry.check_returncode()
    if any(f"rule {rule}:" in dry.stdout + dry.stderr for rule in ("download_api_variable", "download_source_bundle")):
        raise RuntimeError("Preflight requires downloads; inspect cache before execution")
    start = datetime.now(timezone.utc)
    record = {"run_id": args.release_id, "start_time": start.isoformat(), "status": "active",
              "python_version": platform.python_version(), "platform": platform.platform(),
              "snakemake_version": subprocess.check_output([snake, "--version"], text=True).strip(),
              "git_base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
              "config": str(config_path), "command": command, "input_policy": "cached acquisition; canonical inputs explicitly configured"}
    metadata = base / "metadata/workflow-run.json"
    metadata.write_text(json.dumps(record, indent=2) + "\n")
    with (base / "metadata/execution.log").open("w") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    end = datetime.now(timezone.utc)
    record.update(end_time=end.isoformat(), duration=f"PT{(end-start).total_seconds():.3f}S",
                  status="completed" if result.returncode == 0 else "failed", exit_code=result.returncode)
    metadata.write_text(json.dumps(record, indent=2) + "\n")
    result.check_returncode()
    # Refresh only packaging after closing the observed run; never rerun science.
    subprocess.run(command + ["--forcerun", "write_ro_crate"], check=True)
    print(base / "ro-crate.zip")


if __name__ == "__main__":
    main()
