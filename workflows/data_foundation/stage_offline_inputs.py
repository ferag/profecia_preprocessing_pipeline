#!/usr/bin/env python3
"""Copy effective local inputs without changing science or running Snakemake."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil

import yaml

PROJECT = Path(__file__).resolve().parents[2]
CANONICAL_ROOT = Path("/srv/read_only_data/final_datasets")
GML = Path("/srv/read_only_data/NANA/human/RAW/co2/co2_mm_gl.csv")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def collect_inputs(config, project=PROJECT, canonical_root=CANONICAL_ROOT):
    """Exactly the configured files, not all members of canonical directories."""
    values = set(config.get("canonical_reference_products", {}).values())
    for selected in config.get("selected_variables", []):
        source = config["sources"][selected["source"]]
        variable = source["variables"][selected["variable"]]
        if variable.get("canonical_reference_path"):
            values.add(variable["canonical_reference_path"])
        if source.get("canonical_reference_dir"):
            template = source.get("canonical_reference_template", "{variable}_1982_2022_monthly_0.5deg.nc")
            values.add(str(Path(source["canonical_reference_dir"]) / template.format(variable=selected["variable"])))
    files = {}
    for value in sorted(values):
        source = Path(value)
        if not source.is_absolute():
            source = project / source
        relative = source.relative_to(canonical_root)
        files[source] = Path("canonical") / relative
    lai_value = config.get("local_input_paths", {}).get("lai_h5gz", "resources/source_data/lai_h5gz")
    lai = Path(lai_value)
    if not lai.is_absolute():
        lai = project / lai
    composites = sorted(lai.glob("*.gz"))
    if not composites:
        raise FileNotFoundError(f"No LAI composites found in {lai}")
    for source in composites:
        files[source] = Path("lai_h5gz") / source.name
    return files, lai, lai_value


def relocate(value, mapping):
    if isinstance(value, dict):
        return {key: relocate(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [relocate(item, mapping) for item in value]
    if isinstance(value, str):
        for old, new in sorted(mapping.items(), key=lambda pair: -len(pair[0])):
            if value == old or value.startswith(old + "/"):
                return new + value[len(old):]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("workflows/data_foundation/config/data_foundation_all_available.yml"))
    parser.add_argument("--destination", type=Path, default=Path("resources/offline_inputs/profecia_all_available_v1"))
    parser.add_argument("--output-config", type=Path, default=Path("workflows/data_foundation/config/data_foundation_all_available_portable.yml"))
    args = parser.parse_args()
    if Path.cwd().resolve() != PROJECT:
        raise RuntimeError(f"Run from the repository root: {PROJECT}")
    if args.destination.is_absolute() or ".." in args.destination.parts:
        raise ValueError("Destination must be a relative path inside the project")
    if args.output_config.is_absolute() or ".." in args.output_config.parts:
        raise ValueError("Output config must be a relative path inside the project")
    args.destination.resolve().relative_to(PROJECT)
    args.output_config.resolve().relative_to(PROJECT)
    if args.destination.exists() or args.output_config.exists():
        raise FileExistsError("Destination/config already exists; choose new names, never overwrite")
    config = yaml.safe_load(args.config.read_text())
    files, lai, lai_value = collect_inputs(config)
    files[GML] = Path("auxiliary/co2_mm_gl.csv")
    for source in files:
        if not source.is_file():
            raise FileNotFoundError(source)
    destinations = list(files.values())
    if len(destinations) != len(set(destinations)):
        raise ValueError("Input destination collision")
    needed = sum(source.stat().st_size for source in files)
    if shutil.disk_usage(PROJECT).free < needed + 100_000_000:
        raise RuntimeError(f"Insufficient free space for {needed} bytes")
    print(f"Copying {len(files)} files, {needed} bytes; no workflow execution", flush=True)
    args.destination.mkdir(parents=True)
    mapping = {}
    entries = []
    for index, (source, relative) in enumerate(files.items(), 1):
        target = args.destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        expected, actual = sha256(source), sha256(target)
        if expected != actual:
            raise RuntimeError(f"Copy checksum mismatch: {target}")
        mapping[str(source)] = target.as_posix()
        entries.append({"original_path": str(source), "path": target.as_posix(),
                        "size_bytes": target.stat().st_size, "sha256": actual})
        if index % 100 == 0 or index == len(files):
            print(f"Verified {index}/{len(files)} copies", flush=True)
    mapping[str(lai)] = (args.destination / "lai_h5gz").as_posix()
    mapping[lai_value] = mapping[str(lai)]
    for selected in config["selected_variables"]:
        source = config["sources"][selected["source"]]
        if source.get("canonical_reference_dir"):
            old = source["canonical_reference_dir"]
            relative = Path(old).relative_to(CANONICAL_ROOT)
            mapping[old] = (args.destination / "canonical" / relative).as_posix()
    portable = relocate(copy.deepcopy(config), mapping)
    historical = []
    # Retain historical identifiers without treating old host paths as runnable inputs.
    for item in portable.get("provenance_inputs", []):
        path = item.get("path", "")
        if path.startswith("/srv/"):
            historical.append(copy.deepcopy(item))
            item["path"] = f"urn:profecia:historical-input:{item['id']}"
            item["description"] = "Historical reference only; not an effective input of this configuration. See INPUTS_MANIFEST.json for original location."
    for item in portable.get("derived_products", []):
        if str(item.get("notebook_reference", "")).startswith("/srv/"):
            historical.append({"id": item["id"], "notebook_reference": item.pop("notebook_reference")})
    portable.setdefault("local_input_paths", {}).update(
        lai_h5gz=(args.destination / "lai_h5gz").as_posix(),
        co2_gml_csv=(args.destination / "auxiliary/co2_mm_gl.csv").as_posix())
    portable["release"].update(id="profecia_inputs_all_available_portable_v1",
                              base_dir="resources/data_releases/profecia_inputs_all_available_portable_v1")
    portable["offline_inputs"] = {"root": args.destination.as_posix(),
                                  "manifest": (args.destination / "INPUTS_MANIFEST.json").as_posix(),
                                  "path_base": "repository or extracted crate root"}
    portable["ro_crate_packaging"].update(copy_harmonized_outputs=False, copy_raw_inputs=False,
                                         copy_allowlist=[(args.destination / "**/*").as_posix()])
    manifest = {"status": "VERIFIED", "files": entries, "total_bytes": needed,
                "path_map": mapping, "historical_references": historical,
                "scope": "Effective local inputs of the existing all_available configuration; preserves canonical product selection. Online raw downloads and final release outputs are not included."}
    (args.destination / "INPUTS_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    args.output_config.parent.mkdir(parents=True, exist_ok=True)
    args.output_config.write_text(yaml.safe_dump(portable, sort_keys=False))
    print(f"Prepared {args.output_config}; originals and original config unchanged")


if __name__ == "__main__":
    main()
