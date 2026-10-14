#!/usr/bin/env python3
"""Run the packaged PROFECIA workflow; default is a dry-run, never a download."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml


DEPENDENCIES = {
    "swvl1-2": [("era5_single_levels", "swvl1"), ("era5_single_levels", "swvl2")],
    "subswc": [("era5_single_levels", "swvl2"), ("era5_single_levels", "swvl3")],
    "vpd": [("era5_single_levels", "t2m"), ("era5_single_levels", "d2m")],
    "wind": [("era5_single_levels", "u10"), ("era5_single_levels", "v10")],
    "spei06_univariable": [("speibase_v211", "spei06")],
}


def select_variables(config, selection):
    result = copy.deepcopy(config)
    if selection == "all":
        return result
    source_items = {(item["source"], item["variable"]): item for item in config["selected_variables"]}
    derived_items = {item["id"]: item for item in config.get("derived_products", [])}
    selected_sources, selected_derived = set(), set()
    for token in selection.split(","):
        token = token.strip()
        if not token or token == "all":
            raise ValueError("Use 'all' alone, or a comma-separated variable list")
        # co2 means the final annual product; explicit source/variable selects raw source output.
        if token == "co2":
            token = "co2_annual"
        if token in derived_items:
            selected_derived.add(token)
            selected_sources.update(DEPENDENCIES.get(token, []))
            if token == "elevation" and ("gmted2010", "elevation") in source_items:
                selected_sources.add(("gmted2010", "elevation"))
        elif "/" in token and tuple(token.split("/", 1)) in source_items:
            selected_sources.add(tuple(token.split("/", 1)))
        else:
            matches = [key for key in source_items if key[1] == token]
            if len(matches) != 1:
                raise ValueError(f"Unknown or ambiguous variable: {token}; see --list-variables")
            selected_sources.add(matches[0])
    result["selected_variables"] = [item for key, item in source_items.items() if key in selected_sources]
    result["derived_products"] = [item for key, item in derived_items.items() if key in selected_derived]
    # Source CO2 on its own must not be suppressed by an unselected annual output.
    if "co2_annual" not in selected_derived:
        result.get("canonical_reference_products", {}).pop("annual/co2", None)
    return result


def verify(root):
    manifest = json.loads((root / "PAYLOAD_MANIFEST.json").read_text())
    for item in manifest["files"]:
        path = root / item["path"]
        if not path.is_file() or path.stat().st_size != item["size_bytes"]:
            raise RuntimeError(f"Missing or size-mismatched payload: {item['path']}")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != item["sha256"]:
            raise RuntimeError(f"Checksum mismatch: {item['path']}")
    print(f"Verified {len(manifest['files'])} files", flush=True)


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--variables", default="all")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--execute", action="store_true", help="Actually download and preprocess (default only plans)")
    parser.add_argument("--verify", action="store_true", help="Verify bundled file checksums and exit")
    parser.add_argument("--list-variables", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify(root)
        return
    config = yaml.safe_load((root / "config/all.yml").read_text())
    if args.list_variables:
        print("all\n" + "\n".join(item["source"] + "/" + item["variable"] for item in config["selected_variables"]))
        print("Derived: " + ", ".join(item["id"] for item in config["derived_products"]))
        return
    if args.output_dir is None:
        parser.error("--output-dir is required")
    if args.cores < 1:
        parser.error("--cores must be positive")
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Use the locked Python 3.12 environment")
    base = args.output_dir.resolve()
    # Existing workflow shell templates do not quote every path; reject shell metacharacters.
    for path in (root, base):
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", str(path)):
            raise ValueError("Use paths without spaces, non-ASCII characters or shell metacharacters")
    try:
        base.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("Choose an output directory outside the extracted crate")
    config = select_variables(config, args.variables)
    config["release"].update(id=base.name, base_dir=str(base), status="user-execution")
    config["starter_selection"] = args.variables
    config_path = base / "execution.yml"
    if base.exists():
        if not config_path.is_file() or yaml.safe_load(config_path.read_text()) != config:
            raise FileExistsError("Output exists with another configuration; choose a new directory")
    else:
        base.mkdir(parents=True)
        config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    engine = Path(sys.executable).with_name("snakemake")
    version = subprocess.check_output([str(engine), "--version"], text=True).strip()
    if version != "9.26.1":
        raise RuntimeError(f"Expected Snakemake 9.26.1, found {version}")
    command = [str(engine), "--snakefile", "workflow/Snakefile", "--configfile", str(config_path),
               "--cores", str(args.cores)]
    if not args.execute:
        command.append("--dry-run")
    print("EXECUTE: downloads/preprocessing enabled" if args.execute else "PLAN ONLY: no jobs will execute", flush=True)
    with (base / ("execution.log" if args.execute else "plan.log")).open("w") as log:
        result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    print(f"Exit {result.returncode}; logs and configuration in {base}")
    result.check_returncode()


if __name__ == "__main__":
    main()
