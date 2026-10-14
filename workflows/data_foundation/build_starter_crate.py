#!/usr/bin/env python3
"""Build a referential Workflow RO-Crate without executing data acquisition."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_offline_inputs import relocate
from workflow.scripts.sources.gmted2010 import source_definition as gmted_source_definition

PROJECT = Path(__file__).resolve().parents[2]
FOUNDATION = PROJECT / "workflows/data_foundation"
WORKFLOW_PROFILE = "https://w3id.org/workflowhub/workflow-ro-crate/1.0"
CRATE_PROFILE = "https://w3id.org/ro/crate/1.1"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def urls(value):
    if isinstance(value, dict):
        return set().union(*(urls(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(urls(item) for item in value)) if value else set()
    return {value} if isinstance(value, str) and value.startswith(("https://", "http://")) else set()


def source_catalog(config):
    result = []
    selected = {item["source"] for item in config["selected_variables"]}
    selected.update(("geov2_lai", "livestockmap"))
    # Supplied citation and historical mn30_grd name identify GMTED2010.
    selected.add("gmted2010")
    for name in sorted(selected):
        source = config["sources"].get(name, {})
        if name == "gmted2010" and not source:
            source = gmted_source_definition(config)
        result.append({"id": name, "provider": source.get("provider", name),
                       "urls": sorted(urls(source)), "doi": source.get("doi"),
                       "downloaded_by_this_profile": name in {"era5_single_levels", "speibase_v211", "hwsd2", "gmted2010"} and name in {item["source"] for item in config["selected_variables"]},
                       "url_verification": "Declared in source configuration; network availability not tested by builder",
                       "packaging_reason": "Online acquisition retained" if name in {"era5_single_levels", "speibase_v211", "gmted2010"} else
                       "Preserve effective canonical/local inputs until equivalent upstream reconstruction is verified; a public source may exist"})
    result.append({"id": "richness", "urls": [], "downloaded_by_this_profile": False,
                   "packaging_reason": "No original online acquisition is configured for the effective local richness product"})
    return result


def effective_offline_files(config, manifest):
    required = set(config.get("canonical_reference_products", {}).values())
    required.update(config.get("local_input_paths", {}).values())
    for item in config["selected_variables"]:
        source = config["sources"][item["source"]]
        variable = source["variables"][item["variable"]]
        if variable.get("canonical_reference_path"):
            required.add(variable["canonical_reference_path"])
        if source.get("canonical_reference_dir"):
            template = source.get("canonical_reference_template", "{variable}_1982_2022_monthly_0.5deg.nc")
            required.add(str(Path(source["canonical_reference_dir"]) / template.format(variable=item["variable"])))
    return [item for item in manifest["files"] if any(item["path"] == path or item["path"].startswith(path.rstrip("/") + "/") for path in required)]


def write_metadata(root, files, catalog, code_state):
    graph = [
        {"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "about": {"@id": "./"},
         "conformsTo": {"@id": CRATE_PROFILE}},
        {"@id": "./", "@type": "Dataset", "name": "PROFECIA portable preprocessing starter",
         "description": "Executable starter, not an observed execution. Online source references plus effective offline inputs; no release outputs or credentials.",
         "license": "Mixed original provider terms and internal derivative/code rights; no additional redistribution license granted. Review SOURCES.json and README.md before sharing or publishing.",
         "mainEntity": {"@id": "workflow/Snakefile"},
         "conformsTo": [{"@id": CRATE_PROFILE}, {"@id": WORKFLOW_PROFILE}],
         "hasPart": [{"@id": item["path"]} for item in files],
         "mentions": [{"@id": "#source-" + source["id"]} for source in catalog],
         "datePublished": "2026-10-14", "version": "starter-1", "codeState": json.dumps(code_state)},
        {"@id": "#snakemake", "@type": "ComputerLanguage", "name": "Snakemake",
         "identifier": "https://snakemake.github.io/", "url": "https://snakemake.github.io/", "version": "9.26.1"},
        {"@id": "#python", "@type": "SoftwareApplication", "name": "Python", "softwareVersion": "3.12"},
        {"@id": "#output-dir", "@type": "FormalParameter", "name": "output-dir", "additionalType": "Text",
         "description": "New output directory outside the extracted crate; configured by run.py"},
        {"@id": "#variables", "@type": "FormalParameter", "name": "variables", "additionalType": "Text",
         "description": "all or a comma-separated source/variable and derived-product selection", "defaultValue": "all"},
    ]
    for item in files:
        entity = {"@id": item["path"], "@type": "File", "name": Path(item["path"]).name,
                  "contentSize": str(item["size_bytes"]), "sha256": item["sha256"]}
        if item["path"] == "workflow/Snakefile":
            entity.update({"@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
                           "programmingLanguage": {"@id": "#snakemake"},
                           "softwareRequirements": {"@id": "#python"},
                           "conformsTo": {"@id": "https://bioschemas.org/profiles/ComputationalWorkflow/1.0-RELEASE"},
                           "input": [{"@id": "#output-dir"}, {"@id": "#variables"}],
                           "codeRepository": "https://github.com/ferag/profecia_preprocessing_pipeline",
                           "version": "Bundled working-tree snapshot; file checksums identify exact code"})
        graph.append(entity)
    for source in catalog:
        graph.append({"@id": "#source-" + source["id"], "@type": "Dataset", "name": source["id"],
                      "url": source["urls"], "description": source["packaging_reason"]})
    context = ["https://w3id.org/ro/crate/1.1/context",
               {"sha256": "https://schema.org/sha256", "codeState": "https://w3id.org/profecia/vocab/codeState"}]
    (root / "ro-crate-metadata.json").write_text(json.dumps({"@context": context, "@graph": graph}, indent=2) + "\n")


def finalize_archive(root, archive):
    print("Writing archive", flush=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zipped:
        for file in sorted(root.rglob("*")):
            if file.is_file():
                zipped.write(file, file.relative_to(root).as_posix())
    with zipfile.ZipFile(archive) as zipped:
        broken = zipped.testzip()
        if broken:
            raise RuntimeError(f"ZIP integrity error: {broken}")
    checksum = sha(archive)
    archive.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive.name}\n")
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size, "sha256": checksum, "status": "CRC_OK"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=FOUNDATION / "config/data_foundation_all_available_portable.yml")
    parser.add_argument("--output", type=Path, default=PROJECT / "resources/crates/profecia_starter_20261014")
    parser.add_argument("--finalize-existing", action="store_true", help="Explicitly regenerate metadata/archive of a verified starter built by this script")
    args = parser.parse_args()
    root = args.output.resolve()
    root.relative_to(PROJECT / "resources/crates")
    archive = root.parent / "profecia-starter.zip"
    if args.finalize_existing:
        previous = json.loads((root / "ro-crate-metadata.json").read_text())
        if next(entity for entity in previous["@graph"] if entity["@id"] == "./")["name"] != "PROFECIA portable preprocessing starter":
            raise ValueError("Not a starter crate generated by this builder")
        payload = json.loads((root / "PAYLOAD_MANIFEST.json").read_text())
        for item in payload["files"]:
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe payload path")
            if sha(root / relative) != item["sha256"]:
                raise RuntimeError(f"Existing snapshot changed: {relative}")
        graph_files = payload["files"] + [{"path": "PAYLOAD_MANIFEST.json", "size_bytes": (root / "PAYLOAD_MANIFEST.json").stat().st_size,
                                           "sha256": sha(root / "PAYLOAD_MANIFEST.json")}]
        write_metadata(root, graph_files, json.loads((root / "SOURCES.json").read_text()), payload["code_state"])
        finalize_archive(root, archive)
        return
    if root.exists() or archive.exists():
        raise FileExistsError("Choose a fresh crate directory; no overwrite is allowed")
    config = yaml.safe_load(args.config.read_text())
    offline = config["offline_inputs"]["root"]
    manifest = json.loads((PROJECT / config["offline_inputs"]["manifest"]).read_text())
    manifest["files"] = effective_offline_files(config, manifest)
    root.mkdir(parents=True)
    payload = []

    def include(source, relative, expected=None):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        checksum = sha(target)
        if expected and checksum != expected:
            raise RuntimeError(f"Source snapshot changed or copy corrupted: {source}")
        payload.append({"path": relative, "size_bytes": target.stat().st_size, "sha256": checksum})

    print(f"Packaging {len(manifest['files'])} offline files; no data jobs or downloads", flush=True)
    for index, item in enumerate(manifest["files"], 1):
        relative = "inputs/" + Path(item["path"]).relative_to(offline).as_posix()
        include(PROJECT / item["path"], relative, item["sha256"])
        if index % 250 == 0 or index == len(manifest["files"]):
            print(f"Verified payload {index}/{len(manifest['files'])}", flush=True)
    for source in sorted((FOUNDATION / "workflow").rglob("*")):
        if source.is_file() and (source.name == "Snakefile" or source.suffix in {".py", ".smk", ".yaml", ".yml"}) and "__pycache__" not in source.parts:
            include(source, "workflow/" + source.relative_to(FOUNDATION / "workflow").as_posix())
    for source in sorted((FOUNDATION / "metadata/vocabulary").rglob("*")):
        if source.is_file():
            include(source, "metadata/vocabulary/" + source.relative_to(FOUNDATION / "metadata/vocabulary").as_posix())
    include(FOUNDATION / "starter_run.py", "run.py")
    include(FOUNDATION / "requirements-full.lock.txt", "requirements.lock.txt")
    include(FOUNDATION / "requirements.txt", "requirements.txt")
    include(FOUNDATION / "STARTER_CRATE_GUIDE.md", "README.md")
    config = relocate(config, {offline: "inputs", "workflows/data_foundation/workflow": "workflow"})
    config["release"].update(id="profecia_user_release", base_dir="USER_CONFIGURED_OUTPUT")
    config["offline_inputs"]["manifest"] = "PAYLOAD_MANIFEST.json"
    config["ro_crate_packaging"]["copy_allowlist"] = ["inputs/**/*"]
    config["ro_crate_packaging"]["archive_compression"] = "stored"
    (root / "config").mkdir()
    (root / "config/all.yml").write_text(yaml.safe_dump(config, sort_keys=False))
    payload.append({"path": "config/all.yml", "size_bytes": (root / "config/all.yml").stat().st_size,
                    "sha256": sha(root / "config/all.yml")})
    catalog = source_catalog(config)
    (root / "SOURCES.json").write_text(json.dumps(catalog, indent=2) + "\n")
    payload.append({"path": "SOURCES.json", "size_bytes": (root / "SOURCES.json").stat().st_size,
                    "sha256": sha(root / "SOURCES.json")})
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip()
    code_state = {"base_git_commit": commit, "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=PROJECT)),
                  "repository": "https://github.com/ferag/profecia_preprocessing_pipeline",
                  "note": "Included workflow hashes, not base commit alone, identify the actual bundled working-tree code"}
    (root / "ro-crate-preview.html").write_text('<!doctype html><html><head><meta charset="utf-8"><title>PROFECIA starter</title></head><body><h1>PROFECIA preprocessing starter</h1><p>Not an observed execution.</p><a href="README.md">Instructions</a> <a href="SOURCES.json">Original sources and packaging rationale</a></body></html>')
    payload.append({"path": "ro-crate-preview.html", "size_bytes": (root / "ro-crate-preview.html").stat().st_size,
                    "sha256": sha(root / "ro-crate-preview.html")})
    (root / "PAYLOAD_MANIFEST.json").write_text(json.dumps({"files": payload, "code_state": code_state}, indent=2) + "\n")
    graph_files = payload + [{"path": "PAYLOAD_MANIFEST.json", "size_bytes": (root / "PAYLOAD_MANIFEST.json").stat().st_size,
                              "sha256": sha(root / "PAYLOAD_MANIFEST.json")}]
    write_metadata(root, graph_files, catalog, code_state)
    finalize_archive(root, archive)


if __name__ == "__main__":
    main()
