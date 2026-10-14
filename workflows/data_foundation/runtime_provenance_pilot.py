#!/usr/bin/env python3
"""Opt-in, isolated RO-Crate pilot using the production scientific scripts."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_COMMIT = "e3202263df07e66451d77dec7d916e5c5721e5d5"
ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def stage(directory):
    import numpy as np
    import xarray as xr
    directory.mkdir(parents=True)
    source = ROOT / "workflows/data_foundation/workflow/scripts/common"
    (directory / "scripts/common").mkdir(parents=True)
    for name in ("harmonize.py", "config_loader.py", "validate_harmonized.py"):
        shutil.copy2(source / name, directory / "scripts/common" / name)
    lat = np.linspace(-90, 90, 19)
    lon = np.linspace(-180, 180, 37)
    values = (280 + lat[:, None] * 0.01 + lon[None, :] * 0.001).astype("float32")
    xr.Dataset({"t2m": (("latitude", "longitude"), values, {"units": "K"})},
               coords={"latitude": lat, "longitude": lon}).to_netcdf(directory / "input.nc")
    write_json(directory / "config.json", {"release": {"id": "runtime-pilot", "base_dir": "."},
        "sources": {"synthetic": {"variables": {"t2m": {"source_units": "K"}}}}})
    (directory / "Snakefile").write_text('''import sys
PYTHON = sys.executable
rule all:
    input: "validation.json"
rule harmonize:
    input: data="input.nc", config="config.json"
    output: "output.nc"
    shell: "{PYTHON} scripts/common/harmonize.py netcdf --config {input.config} --source synthetic --variable t2m --input {input.data} --output {output} --frequency static"
rule validate:
    input: "output.nc"
    output: "validation.json"
    shell: "{PYTHON} scripts/common/validate_harmonized.py --output {output} {input}"
''')


def invoke(directory, label, extra=()):
    start = datetime.now(timezone.utc).isoformat()
    command = [str(Path(sys.executable).with_name("snakemake")), "--cores", "1", *extra]
    result = subprocess.run(command, cwd=directory, capture_output=True, text=True)
    (directory / f"{label}.log").write_text(result.stdout + result.stderr)
    result.check_returncode()
    jobs = [name for name in re.findall(r"(?:localrule|rule) (\w+):", result.stdout + result.stderr)
            if name != "all"]
    return {"start_time": start, "end_time": datetime.now(timezone.utc).isoformat(),
            "command": command, "log": f"{label}.log", "executed_rules": jobs}


def report(directory, label):
    invoke(directory, f"report-{label}", ["--reporter", "rocrate", "--report-rocrate-filename", label,
        "--report-rocrate-run-name", "PROFECIA synthetic runtime pilot",
        "--report-rocrate-workflow-inputs", '{"temperature":"input.nc","configuration":"config.json"}'])
    path = directory / f"{label}.zip"
    with zipfile.ZipFile(path) as archive:
        entries = [{"path": e.filename, "bytes": e.file_size} for e in archive.infolist()]
        metadata = json.loads(archive.read("ro-crate-metadata.json"))
    actions = [e for e in metadata["@graph"] if "CreateAction" in
               (e.get("@type") if isinstance(e.get("@type"), list) else [e.get("@type")])]
    if not actions or not all(e.get("startTime") and e.get("endTime") for e in actions):
        raise RuntimeError("Missing action timestamps")
    for action in actions:
        for key in ("startTime", "endTime"):
            if datetime.fromisoformat(action[key]).tzinfo is None:
                raise RuntimeError("Action timestamp has no timezone")
    if actions[0].get("instrument") != {"@id": "Snakefile"}:
        raise RuntimeError("Workflow action must point to the workflow")
    for action in actions[1:]:
        expected = "output.nc" if action["name"].startswith("harmonize_") else "validation.json"
        if action.get("result") != {"@id": expected} or not action.get("object"):
            raise RuntimeError("Incorrect rule input/output mapping")
        if action.get("instrument") != {"@id": "#snakemake-rule-executor"}:
            raise RuntimeError("Unexpected shell-rule software mapping; review new plugin behavior")
    if any(e["bytes"] > 10_000_000 for e in entries):
        raise RuntimeError("Pilot archive contains an unexpectedly large file")
    return {"archive": path.name, "sha256": digest(path), "inventory": entries, "actions": actions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; existing paths are rejected")
    args = parser.parse_args()
    from importlib.metadata import version, distribution
    if sys.version_info[:2] != (3, 12) or version("snakemake") != "9.26.1":
        raise RuntimeError("Use the locked Python 3.12 / Snakemake 9.26.1 pilot environment")
    direct_url = json.loads(distribution("snakemake-report-plugin-rocrate").read_text("direct_url.json") or "{}")
    if direct_url.get("vcs_info", {}).get("commit_id") != PLUGIN_COMMIT:
        raise RuntimeError("Plugin installation does not match the pinned commit")
    output = args.output_dir.resolve()
    if output.exists():
        raise RuntimeError("Output directory must not already exist")
    output.mkdir(parents=True)
    evidence = {"plugin_commit": PLUGIN_COMMIT, "snakemake_version": version("snakemake"),
                "python_version": sys.version, "profile": "provenance-run-crate-0.5", "runs": {}}
    evidence["git_base_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    evidence["git_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    evidence["dependencies"] = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True).splitlines()
    for name in ("initial", "clean"):
        directory = output / name
        stage(directory)
        evidence["runs"][name] = {"invocation": invoke(directory, "execution"), "report": report(directory, "workflow-run")}
    import xarray as xr
    with xr.open_dataset(output / "initial/output.nc") as first, xr.open_dataset(output / "clean/output.nc") as second:
        xr.testing.assert_identical(first, second)
    evidence["scientific_comparison"] = "identical"
    evidence["config_sha256"] = digest(output / "initial/config.json")
    directory = output / "initial"
    for name, extra in (("noop", []), ("partial", ["--forcerun", "validate"])):
        evidence["runs"][name] = {"invocation": invoke(directory, name, extra), "report": report(directory, name)}
    evidence["interpretation"] = "Reporter actions may include persisted historical jobs; invocation logs determine which jobs ran now."
    initial = evidence["runs"]["initial"]["report"]["actions"]
    noop = evidence["runs"]["noop"]["report"]["actions"]
    partial = evidence["runs"]["partial"]["report"]["actions"]
    if evidence["runs"]["noop"]["invocation"]["executed_rules"] or initial != noop:
        raise RuntimeError("No-op scenario unexpectedly executed jobs or changed historical actions")
    if evidence["runs"]["partial"]["invocation"]["executed_rules"] != ["validate"]:
        raise RuntimeError("Partial scenario did not execute only validation")
    by_name = lambda actions: {a["name"]: a for a in actions}
    before, after = by_name(initial), by_name(partial)
    for name, action in before.items():
        if name.startswith("harmonize") and action != after[name]:
            raise RuntimeError("Partial run changed persisted harmonization")
        if name.startswith("validate") and action["startTime"] == after[name]["startTime"]:
            raise RuntimeError("Partial run failed to update validation timestamp")
    write_json(output / "evidence.json", evidence)
    print(output / "evidence.json")


if __name__ == "__main__":
    main()
