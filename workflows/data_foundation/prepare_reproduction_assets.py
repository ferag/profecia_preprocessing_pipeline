#!/usr/bin/env python3
"""Snapshot effective canonical inputs and prepare a portable offline config."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    base = Path(config["release"]["base_dir"])
    assets = base / "reproduction-assets"
    assets.mkdir()
    mapping = {}
    inputs = set(config.get("canonical_reference_products", {}).values())
    for item in config["selected_variables"]:
        source = config["sources"][item["source"]]
        variable = source["variables"][item["variable"]]
        if variable.get("canonical_reference_path"):
            inputs.add(variable["canonical_reference_path"])
        if source.get("canonical_reference_dir"):
            inputs.add(source["canonical_reference_dir"])
    inputs.add("resources/source_data/lai_h5gz")
    for value in sorted(inputs):
        source = Path(value)
        if not source.exists():
            raise FileNotFoundError(source)
        tag = hashlib.sha256(str(source).encode()).hexdigest()[:12]
        relative = Path("inputs") / tag / source.name
        target = assets / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        mapping[value] = (Path("reproduction") / relative).as_posix()
    def portable(value):
        if isinstance(value, dict):
            return {key: portable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [portable(item) for item in value]
        if isinstance(value, str):
            if value in mapping:
                return mapping[value]
            for old, new in sorted(mapping.items(), key=lambda x: -len(x[0])):
                if value.startswith(old + "/"):
                    return new + value[len(old):]
            return value.replace("workflows/data_foundation/workflow/", "workflow/")
        return value
    replay = portable(config)
    replay["local_input_paths"] = {"lai_h5gz": mapping["resources/source_data/lai_h5gz"]}
    replay.pop("reproduction_assets", None)
    (assets / "config.yml").write_text(yaml.safe_dump(replay, sort_keys=False))
    (assets / "input-map.json").write_text(json.dumps(mapping, indent=2) + "\n")
    for source, name in (("reproduce.py", "reproduce.py"), ("compare_releases.py", "compare_releases.py"),
                         ("EXTERNAL_TESTER_GUIDE.md", "EXTERNAL_TESTER_GUIDE.md"),
                         ("requirements-full.lock.txt", "requirements.lock.txt"),
                         ("verify_package.py", "verify_package.py"), ("validate_shapes.py", "validate_shapes.py")):
        shutil.copy2(ROOT / "workflows/data_foundation" / source, assets / name)
    shutil.copy2(ROOT / "workflows/data_foundation/tests/test_ro_crate.py", assets / "test_ro_crate.py")
    config["reproduction_assets"] = [{"path": str(assets), "destination": "reproduction"}]
    args.config.write_text(yaml.safe_dump(config, sort_keys=False))
    print(assets)


if __name__ == "__main__":
    main()
