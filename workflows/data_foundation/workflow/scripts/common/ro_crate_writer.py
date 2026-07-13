#!/usr/bin/env python3
"""Write a referential Workflow/Data RO-Crate for a PROFECIA release."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, release, release_base_dir


RO_CRATE_CONTEXT = [
    "https://w3id.org/ro/crate/1.2/context",
    "https://w3id.org/ro/terms/workflow-run/context",
]
RO_CRATE_PROFILE = "https://w3id.org/ro/crate/1.2"
WORKFLOW_RO_CRATE_PROFILE = "https://w3id.org/workflowhub/workflow-ro-crate/1.0"
PROCESS_RUN_PROFILE = "https://w3id.org/ro/wfrun/process/0.1"
WORKFLOW_RUN_PROFILE = "https://w3id.org/ro/wfrun/workflow/0.5"
BIOSCHEMAS_FORMAL_PARAMETER = "https://bioschemas.org/profiles/FormalParameter/1.0-RELEASE"
SNAKEMAKE_LANGUAGE = "https://snakemake.github.io/"
NETCDF_MEDIA_TYPE = "application/x-netcdf"
METADATA_LICENSE = "https://spdx.org/licenses/CC0-1.0.html"
DATA_LICENSE = "https://spdx.org/licenses/CC-BY-4.0.html"
CODE_LICENSE = "https://spdx.org/licenses/Apache-2.0.html"


def posix_rel(path: Path, start: Path) -> str:
    return Path(os.path.relpath(path, start)).as_posix()


def crate_id(path: Path, crate_dir: Path) -> str:
    return posix_rel(path, crate_dir)


def ref(entity_id: str) -> dict[str, str]:
    return {"@id": entity_id}


def slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value))
    return "-".join(part for part in cleaned.split("-") if part)


def canonical_crate_path(source_path: Path, *, base_dir: Path, workflow_dir: Path, config_dir: Path) -> Path:
    source_path = source_path.resolve()
    try:
        return Path("workflow") / source_path.relative_to(workflow_dir)
    except ValueError:
        pass
    try:
        return Path("config") / source_path.relative_to(config_dir)
    except ValueError:
        pass
    try:
        relative = source_path.relative_to(base_dir)
    except ValueError:
        return Path(source_path.name)
    if relative.parts and relative.parts[0] in {"metadata", "fair", "validation"}:
        return relative
    if relative.name in {"manifest.json", "checksums.sha256", "CITATION.cff"}:
        return relative
    return Path("referenced-data") / relative


def copy_into_crate(source_path: Path, crate_dir: Path, relative_path: Path) -> Path:
    target = crate_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target)
    return target


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    if not path.exists():
        return checksums
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, relative = line.partition("  ")
        if digest and relative:
            checksums[relative.strip()] = digest.strip()
    return checksums


def encoding_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".nc":
        return NETCDF_MEDIA_TYPE
    if suffix in {".json", ".jsonld"}:
        return "application/ld+json" if suffix == ".jsonld" else "application/json"
    if suffix in {".yml", ".yaml"}:
        return "application/x-yaml"
    if suffix == ".smk":
        return "text/x-snakemake"
    media_type, _ = mimetypes.guess_type(path.name)
    return media_type or "application/octet-stream"


def is_safe_config_reference(path: Path) -> bool:
    name = path.name.lower()
    is_example = ".example." in name or name.endswith(".template.yml") or name.endswith(".template.yaml")
    if ".local." in name and not is_example:
        return False
    if "secret" in name and not is_example:
        return False
    if "credential" in name and not is_example:
        return False
    return True


def add_entity(graph: list[dict[str, Any]], entity: dict[str, Any], seen: set[str]) -> None:
    entity_id = str(entity["@id"])
    if entity_id in seen:
        return
    seen.add(entity_id)
    graph.append(entity)


def file_entity(
    path: Path,
    crate_dir: Path,
    base_dir: Path,
    checksums: dict[str, str],
    *,
    entity_id: str | None = None,
    name: str | None = None,
    types: list[str] | None = None,
    description: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entity: dict[str, Any] = {
        "@id": entity_id or crate_id(path, crate_dir),
        "@type": types or ["File"],
        "name": name or path.name,
        "encodingFormat": encoding_format(path),
    }
    if description:
        entity["description"] = description
    if path.exists() and path.is_file():
        entity["contentSize"] = str(path.stat().st_size)
    try:
        base_relative = path.relative_to(base_dir).as_posix()
    except ValueError:
        base_relative = None
    if base_relative and checksums.get(base_relative):
        entity["sha256"] = checksums[base_relative]
    if extra:
        entity.update(extra)
    return entity


def workflow_files(workflow_dir: Path) -> list[Path]:
    suffixes = {".py", ".smk", ".yml", ".yaml"}
    files = [workflow_dir / "Snakefile"]
    files.extend(
        sorted(
            item
            for item in workflow_dir.rglob("*")
            if item.is_file()
            and item.suffix.lower() in suffixes
            and "__pycache__" not in item.parts
        )
    )
    return sorted(set(files))


def release_file_paths(base_dir: Path, manifest: dict[str, Any]) -> set[Path]:
    paths = {
        base_dir / "manifest.json",
        base_dir / "checksums.sha256",
        base_dir / "fair" / "harmonized_netcdf_demo.croissant.jsonld",
        base_dir / "validation" / "release_validation.json",
        base_dir / "validation" / "harmonized_validation.json",
    }
    for value in manifest.get("release_metadata", []):
        paths.add(base_dir / value)
    for value in manifest.get("validation_reports", []):
        paths.add(base_dir / value)
    for value in manifest.get("source_request_metadata", []):
        paths.add(base_dir / value)
    for item in manifest.get("selected_variables", []):
        for value in (item.get("metadata") or {}).values():
            if value:
                paths.add(base_dir / value)
        for key in ("raw_files", "harmonized_files"):
            for value in item.get(key) or []:
                if value:
                    paths.add(base_dir / value)
    return paths


def safe_config_files(config_dir: Path, config_path: Path) -> list[Path]:
    files = [config_path] if is_safe_config_reference(config_path) else []
    files.extend(
        path
        for path in sorted(config_dir.glob("*"))
        if path.is_file()
        and path.suffix.lower() in {".yml", ".yaml"}
        and is_safe_config_reference(path)
    )
    return sorted(set(files))


def git_metadata(project_root: Path) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []

    def run(*args: str) -> str | None:
        try:
            return subprocess.check_output(
                ["git", *args], cwd=project_root, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            return None

    commit = run("rev-parse", "HEAD")
    branch = run("rev-parse", "--abbrev-ref", "HEAD")
    remote = run("config", "--get", "remote.origin.url")
    dirty = run("status", "--porcelain")
    tag = run("describe", "--tags", "--always")
    if not commit:
        warnings.append("Optional Git commit metadata not available.")
    if not branch:
        warnings.append("Optional Git branch metadata not available.")
    data = {
        "commit": commit,
        "branch": branch,
        "repository_url": remote,
        "dirty": bool(dirty) if dirty is not None else None,
        "software_version": tag,
    }
    return {key: value for key, value in data.items() if value not in {None, ""}}, warnings


def entity_for_release_path(path: Path, base_dir: Path, workflow_dir: Path, config_dir: Path) -> str:
    return canonical_crate_path(path, base_dir=base_dir, workflow_dir=workflow_dir, config_dir=config_dir).as_posix()


def write_readme(path: Path, release_id: str, archive_path: Path) -> None:
    text = f"""# PROFECIA Data Foundation Demo Release

This RO-Crate describes the PROFECIA data-foundation demo release `{release_id}`. It packages workflow code, safe configuration examples, provenance metadata, validation summaries, checksums, and a Croissant descriptor for discovery.

## Official Products

The official scientific outputs are the harmonized NetCDF products on the PROFECIA target grid. Raw/source files are represented as provenance inputs: they may be referenced by path, request metadata, checksum, and source dataset, but they are not the primary release distributions.

## Regeneration

Install the workflow requirements, provide local credentials where a source requires them, and run the Snakemake workflow with `workflows/data_foundation/config/data_foundation_demo.yml`. Safe credential templates are included; real credentials and local secrets are intentionally excluded.

## Validation

Run `sha256sum -c checksums.sha256` from the release directory to verify checksums. Review `validation/harmonized_validation.json` for harmonized product checks and `validation/release_validation.json` for release-level checks and warnings.

## Licenses

Metadata is CC0-1.0. Derived harmonized data products are CC-BY-4.0. Workflow/code files are Apache-2.0. External source datasets remain governed by their original provider terms and may require credentials or manual access.

## Citation

No DOI has been assigned yet. Cite the release title, release identifier `{release_id}`, creator Fernando Aguilar Gomez, CSIC, and the eventual ROHub URL/DOI when available.

## ROHub Notes

Upload `{archive_path.name}` to ROHub after confirming validation status, checksum coverage, and absence of secrets. ROHub is the target platform, not the scientific publisher.
"""
    path.write_text(text, encoding="utf-8")


def write_citation(path: Path, release_id: str) -> None:
    text = f"""cff-version: 1.2.0
title: PROFECIA Data Foundation Demo Release
message: Cite this data release using the metadata below. No DOI has been assigned yet.
type: dataset
authors:
  - family-names: Aguilar Gomez
    given-names: Fernando
    orcid: https://orcid.org/0000-0001-9462-4831
version: {release_id}
license: CC-BY-4.0
"""
    path.write_text(text, encoding="utf-8")


def write_archive(archive_path: Path, crate_dir: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(crate_dir.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(crate_dir).as_posix())


def make_action(action_id: str, name: str, instrument: str, objects: list[str], results: list[str], description: str) -> dict[str, Any]:
    entity: dict[str, Any] = {
        "@id": action_id,
        "@type": "CreateAction",
        "name": name,
        "description": description,
        "instrument": ref(instrument),
        "actionStatus": "https://schema.org/CompletedActionStatus",
    }
    if objects:
        entity["object"] = [ref(item) for item in sorted(set(objects))]
    if results:
        entity["result"] = [ref(item) for item in sorted(set(results))]
    entity["agent"] = [ref("#person-fernando-aguilar-gomez"), ref("#workflow-snakemake")]
    return entity


def provenance_entity_id(item: dict[str, Any]) -> str:
    return f"provenance/referenced/{slug(item.get('id') or item.get('path') or 'input')}"


def provenance_copy_path(item: dict[str, Any], used: set[str]) -> Path:
    source = Path(str(item.get("path", "")))
    role = slug(item.get("role", "input")) or "input"
    stem = slug(item.get("id") or source.stem) or "input"
    suffix = source.suffix
    name = f"{stem}{suffix}" if suffix and not stem.endswith(slug(suffix)) else source.name
    relative = Path("provenance") / "original_scripts" / role / name
    counter = 2
    while relative.as_posix() in used:
        relative = Path("provenance") / "original_scripts" / role / f"{stem}-{counter}{suffix}"
        counter += 1
    used.add(relative.as_posix())
    return relative


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--workflow-dir", required=True, type=Path)
    parser.add_argument("--project-root", default=Path("."), type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    args = parser.parse_args()

    config_path = args.config.resolve()
    workflow_dir = args.workflow_dir.resolve()
    project_root = args.project_root.resolve()
    config_dir = config_path.parent
    requirements_path = project_root / "workflows" / "data_foundation" / "requirements.txt"
    output_dir = args.output_dir.resolve()
    archive_path = args.archive.resolve()

    config = load_config(config_path)
    release_data = release(config)
    release_id = str(release_data.get("id", "unknown-release"))
    base_dir = release_base_dir(config).resolve()
    manifest_path = base_dir / "manifest.json"
    checksums_path = base_dir / "checksums.sha256"
    croissant_path = base_dir / "fair" / "harmonized_netcdf_demo.croissant.jsonld"
    release_validation_path = base_dir / "validation" / "release_validation.json"
    harmonized_validation_path = base_dir / "validation" / "harmonized_validation.json"

    manifest = read_json(manifest_path)
    checksums = parse_checksums(checksums_path)
    git_data, git_warnings = git_metadata(project_root)

    if output_dir.exists():
        for item in output_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / "ro-crate-metadata.json"
    readme_path = output_dir / "README.md"
    citation_path = output_dir / "CITATION.cff"

    graph: list[dict[str, Any]] = []
    seen: set[str] = set()
    has_part: list[dict[str, str]] = []
    release_id_map: dict[str, str] = {}

    for profile_id, name, version in [
        (RO_CRATE_PROFILE, "RO-Crate", "1.2"),
        (WORKFLOW_RO_CRATE_PROFILE, "Workflow RO-Crate", "1.0"),
        (PROCESS_RUN_PROFILE, "Process Run Crate", "0.1"),
        (WORKFLOW_RUN_PROFILE, "Workflow Run Crate", "0.5"),
        (SNAKEMAKE_LANGUAGE, "Snakemake", ""),
        (BIOSCHEMAS_FORMAL_PARAMETER, "Bioschemas FormalParameter", "1.0-RELEASE"),
        (METADATA_LICENSE, "CC0 1.0 Universal", ""),
        (DATA_LICENSE, "Creative Commons Attribution 4.0 International", ""),
        (CODE_LICENSE, "Apache License 2.0", ""),
    ]:
        entity: dict[str, Any] = {"@id": profile_id, "@type": "CreativeWork", "name": name}
        if version:
            entity["version"] = version
        add_entity(graph, entity, seen)

    add_entity(graph, {"@id": "#person-fernando-aguilar-gomez", "@type": "Person", "name": "Fernando Aguilar Gomez", "identifier": "https://orcid.org/0000-0001-9462-4831", "affiliation": ref("#org-ifca-csic")}, seen)
    add_entity(graph, {"@id": "#org-csic", "@type": "Organization", "name": "Spanish National Research Council (CSIC)", "alternateName": "CSIC"}, seen)
    add_entity(graph, {"@id": "#org-ifca-csic", "@type": "Organization", "name": "Instituto de Fisica de Cantabria", "alternateName": "IFCA-CSIC", "parentOrganization": ref("#org-csic")}, seen)
    add_entity(graph, {"@id": "#grant-pid2023-152114ob-i00", "@type": "Grant", "name": "PID2023-152114OB-I00", "identifier": "PID2023-152114OB-I00", "funder": ref("#org-csic")}, seen)
    add_entity(graph, {"@id": "#workflow-snakemake", "@type": "SoftwareApplication", "name": "Snakemake workflow runner"}, seen)

    add_entity(
        graph,
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": ref("./"),
            "license": ref(METADATA_LICENSE),
            "conformsTo": [ref(RO_CRATE_PROFILE), ref(WORKFLOW_RO_CRATE_PROFILE)],
        },
        seen,
    )

    release_paths = sorted(path for path in release_file_paths(base_dir, manifest) if path.exists())
    for path in release_paths:
        rel_to_base = path.relative_to(base_dir).as_posix()
        crate_relative = canonical_crate_path(path, base_dir=base_dir, workflow_dir=workflow_dir, config_dir=config_dir)
        should_copy = not rel_to_base.endswith(".nc")
        if should_copy:
            copy_into_crate(path, output_dir, crate_relative)
        entity_id = crate_relative.as_posix()
        release_id_map[rel_to_base] = entity_id
        extra: dict[str, Any] = {}
        types = ["File"]
        name = path.name
        if not should_copy:
            extra["contentUrl"] = rel_to_base
            extra["description"] = "Referenced release data file; not copied into this RO-Crate archive."
        if rel_to_base in {"manifest.json", "checksums.sha256"}:
            extra["about"] = ref("./")
            extra["license"] = ref(METADATA_LICENSE)
        if rel_to_base == croissant_path.relative_to(base_dir).as_posix():
            name = "Croissant descriptor for harmonized PROFECIA NetCDF release"
            extra["about"] = ref("#dataset-harmonized")
            extra["license"] = ref(METADATA_LICENSE)
        if rel_to_base == "validation/harmonized_validation.json":
            name = "Harmonized NetCDF validation report"
            extra["about"] = ref("#dataset-harmonized")
        if rel_to_base == "validation/release_validation.json":
            name = "Release validation report"
            extra["about"] = ref("./")
        if "/inspection.json" in rel_to_base:
            raw_refs = [raw for item in manifest.get("selected_variables", []) for raw in item.get("raw_files") or [] if (item.get("metadata") or {}).get("inspection") == rel_to_base]
            extra["about"] = [ref(release_id_map.get(raw, entity_for_release_path(base_dir / raw, base_dir, workflow_dir, config_dir))) for raw in raw_refs]
        if rel_to_base.endswith(".nc"):
            name = rel_to_base
            variables = [entry for entry in manifest.get("selected_variables", []) if rel_to_base in (entry.get("raw_files") or []) or rel_to_base in (entry.get("harmonized_files") or [])]
            extra["variableMeasured"] = [ref(f"#variable-{slug(entry['source'])}-{slug(entry['variable'])}") for entry in variables]
            if any(rel_to_base in (entry.get("harmonized_files") or []) for entry in manifest.get("selected_variables", [])):
                types = ["File", "Dataset"]
                extra["license"] = ref(DATA_LICENSE)
                extra["isPartOf"] = ref("#dataset-harmonized")
            else:
                extra["usageInfo"] = "External source data governed by original provider terms; included only as provenance input metadata/reference."
                extra["isPartOf"] = ref("#dataset-raw-provenance")
        entity = file_entity(path, output_dir, base_dir, checksums, entity_id=entity_id, name=name, types=types, extra=extra)
        add_entity(graph, entity, seen)
        has_part.append(ref(entity_id))

    workflow_parts = []
    for workflow_path in workflow_files(workflow_dir):
        if not workflow_path.exists():
            continue
        types = ["File", "SoftwareSourceCode"]
        extra: dict[str, Any] = {"license": ref(CODE_LICENSE)}
        if workflow_path.name == "Snakefile":
            types.append("ComputationalWorkflow")
            extra.update(
                {
                    "name": "PROFECIA Data Foundation Snakemake workflow",
                    "description": "Workflow used to build requests, acquire/register source data, inspect raw files, harmonize NetCDF products, validate outputs, write FAIR metadata, checksums and RO-Crate metadata.",
                    "programmingLanguage": ref(SNAKEMAKE_LANGUAGE),
                    "input": [ref("#configfile"), ref("#user-settings")],
                    "output": [ref("#harmonized-release"), ref("#release-metadata")],
                }
            )
            if git_data.get("repository_url"):
                extra["codeRepository"] = git_data["repository_url"]
            if git_data.get("software_version"):
                extra["softwareVersion"] = git_data["software_version"]
            if git_data.get("commit"):
                extra["version"] = git_data["commit"]
        crate_relative = canonical_crate_path(workflow_path, base_dir=base_dir, workflow_dir=workflow_dir, config_dir=config_dir)
        copy_into_crate(workflow_path, output_dir, crate_relative)
        entity_id = crate_relative.as_posix()
        workflow_parts.append(ref(entity_id))
        entity = file_entity(workflow_path, output_dir, project_root, {}, entity_id=entity_id, types=types, extra=extra)
        add_entity(graph, entity, seen)
        has_part.append(ref(entity_id))
    if workflow_parts:
        snake = next((entity for entity in graph if entity.get("@id") == "workflow/Snakefile"), None)
        if snake is not None:
            snake["hasPart"] = sorted([item for item in workflow_parts if item["@id"] != "workflow/Snakefile"], key=lambda item: item["@id"])

    run_config_object: dict[str, str] | None = None
    for safe_config in safe_config_files(config_dir, config_path):
        crate_relative = canonical_crate_path(safe_config, base_dir=base_dir, workflow_dir=workflow_dir, config_dir=config_dir)
        copy_into_crate(safe_config, output_dir, crate_relative)
        entity_id = crate_relative.as_posix()
        entity = file_entity(
            safe_config,
            output_dir,
            project_root,
            {},
            entity_id=entity_id,
            name="Snakemake config file used for this release" if safe_config == config_path else f"Safe configuration template/example: {safe_config.name}",
            types=["File"],
            extra={"license": ref(CODE_LICENSE)},
        )
        add_entity(graph, entity, seen)
        has_part.append(ref(entity_id))
        if safe_config == config_path:
            run_config_object = ref(entity_id)
    if run_config_object is None:
        run_config_object = ref("#withheld-configfile")
        add_entity(graph, {"@id": "#withheld-configfile", "@type": "PropertyValue", "name": "configfile", "description": "Local config path withheld from the packaged RO-Crate to avoid publishing secrets or machine-specific settings.", "value": config_path.name}, seen)

    if requirements_path.exists():
        copy_into_crate(requirements_path, output_dir, Path("requirements.txt"))
        entity = file_entity(requirements_path, output_dir, project_root, {}, entity_id="requirements.txt", name="Python requirements for the PROFECIA data-foundation workflow", types=["File", "SoftwareSourceCode"], extra={"license": ref(CODE_LICENSE)})
        add_entity(graph, entity, seen)
        has_part.append(ref("requirements.txt"))

    provenance_id_map: dict[str, str] = {}
    provenance_parts: list[dict[str, str]] = []
    used_provenance_paths: set[str] = set()
    for item in manifest.get("provenance_inputs", []) or []:
        source_path = Path(str(item.get("path", "")))
        copy_policy = str(item.get("copy_policy", "reference")).lower()
        exists = bool(item.get("exists")) and source_path.exists()
        extra = {
            "contentUrl": str(source_path),
            "usageInfo": item.get("license_or_terms") or "Governed by original provider terms.",
            "isPartOf": ref("#dataset-provenance-inputs"),
            "additionalType": item.get("role"),
            "usedBy": item.get("used_by", []),
        }
        if item.get("sha256"):
            extra["sha256"] = item["sha256"]
        if item.get("size_bytes") is not None:
            extra["contentSize"] = str(item["size_bytes"])
        if copy_policy == "copy" and exists and source_path.is_file():
            crate_relative = provenance_copy_path(item, used_provenance_paths)
            copied = copy_into_crate(source_path, output_dir, crate_relative)
            entity_id = crate_relative.as_posix()
            extra["contentUrl"] = str(source_path)
            entity = file_entity(
                copied,
                output_dir,
                output_dir,
                {},
                entity_id=entity_id,
                name=str(item.get("id") or source_path.name),
                types=["File", "SoftwareSourceCode"] if item.get("role") == "original_script" else ["File"],
                description=item.get("description") or f"Provenance input ({item.get('role')}) copied from {source_path}.",
                extra=extra,
            )
        else:
            entity_id = provenance_entity_id(item)
            entity = {
                "@id": entity_id,
                "@type": ["File"],
                "name": str(item.get("id") or source_path.name),
                "encodingFormat": encoding_format(source_path),
                "description": item.get("description") or f"Referenced provenance input ({item.get('role')}); not copied into the RO-Crate archive.",
                **extra,
            }
        provenance_id_map[str(item.get("id"))] = entity_id
        add_entity(graph, entity, seen)
        provenance_parts.append(ref(entity_id))
        has_part.append(ref(entity_id))

    write_readme(readme_path, release_id, archive_path)
    add_entity(graph, file_entity(readme_path, output_dir, output_dir, {}, entity_id="README.md", name="RO-Crate and ROHub publication notes", types=["File", "CreativeWork"], extra={"license": ref(METADATA_LICENSE)}), seen)
    has_part.append(ref("README.md"))
    write_citation(citation_path, release_id)
    add_entity(graph, file_entity(citation_path, output_dir, output_dir, {}, entity_id="CITATION.cff", name="Citation metadata", types=["File", "CreativeWork"], extra={"license": ref(METADATA_LICENSE)}), seen)
    has_part.append(ref("CITATION.cff"))

    for item in manifest.get("selected_variables", []):
        variable_id = f"#variable-{slug(item['source'])}-{slug(item['variable'])}"
        variable_entity = {
            "@id": variable_id,
            "@type": "PropertyValue",
            "name": item.get("long_name") or item["variable"],
            "propertyID": item["variable"],
            "value": item.get("source_units"),
            "description": f"{item['source']}/{item['variable']} ({item.get('role') or 'variable'})",
            "provider": item.get("provider"),
        }
        if item.get("derived"):
            derivation = item.get("derivation") or {}
            details = [value for value in [derivation.get("description"), derivation.get("formula"), derivation.get("weights")] if value]
            if details:
                variable_entity["description"] = variable_entity["description"] + "; " + " | ".join(details)
            if derivation.get("formula"):
                variable_entity["formula"] = derivation["formula"]
            if derivation.get("notebook_reference"):
                variable_entity["isBasedOn"] = derivation["notebook_reference"]
        add_entity(graph, variable_entity, seen)

    for source_id, source in sorted((manifest.get("configured_sources") or {}).items()):
        sid = f"#source-{slug(source_id)}"
        entity = {
            "@id": sid,
            "@type": "Dataset",
            "name": source.get("source_family") or source_id,
            "provider": source.get("provider"),
            "description": f"External source dataset used as provenance input for PROFECIA harmonized products. Access method: {source.get('access_protocol') or source.get('access_mode') or 'unspecified'}.",
            "usageInfo": source.get("terms") or "Governed by original provider terms.",
            "variableMeasured": [ref(f"#variable-{slug(source_id)}-{slug(variable)}") for variable in source.get("variables", [])],
        }
        if source.get("dataset"):
            entity["identifier"] = source["dataset"]
        add_entity(graph, entity, seen)

    add_entity(graph, {"@id": "#dataset-harmonized", "@type": "Dataset", "name": "Harmonized PROFECIA NetCDF products", "description": "Official derived data products for this release.", "license": ref(DATA_LICENSE), "hasPart": [ref(release_id_map[path]) for path in manifest.get("harmonized_files", []) if path in release_id_map]}, seen)
    add_entity(graph, {"@id": "#dataset-raw-provenance", "@type": "Dataset", "name": "Raw/source provenance inputs", "description": "Raw or source artifacts used to generate harmonized products. These are provenance inputs, not primary release distributions.", "usageInfo": "External source data remain governed by original provider terms.", "hasPart": [ref(release_id_map[path]) for path in manifest.get("raw_source_files", []) if path in release_id_map]}, seen)
    add_entity(graph, {"@id": "#dataset-provenance-inputs", "@type": "Dataset", "name": "Original scripts and critical external provenance inputs", "description": "Legacy scripts, canonical references, target grids and large raw inputs needed to reproduce the canonical /srv/read_only_data products. Large inputs may be referenced rather than copied.", "usageInfo": "Copy policy is recorded in manifest.json; referenced inputs are not redistributed in the RO-Crate archive.", "hasPart": provenance_parts}, seen)
    add_entity(graph, {"@id": "#dataset-validation-reports", "@type": "Dataset", "name": "Validation reports", "description": "Raw inspection, harmonized validation and release validation reports.", "hasPart": [ref(release_id_map[path]) for path in manifest.get("validation_reports", []) if path in release_id_map]}, seen)
    has_part.extend([ref("#dataset-harmonized"), ref("#dataset-raw-provenance"), ref("#dataset-provenance-inputs"), ref("#dataset-validation-reports")])

    for entity in [
        {"@id": "#configfile", "@type": "FormalParameter", "additionalType": "File", "conformsTo": ref(BIOSCHEMAS_FORMAL_PARAMETER), "name": "configfile", "valueRequired": "True", "workExample": run_config_object},
        {"@id": "#user-settings", "@type": "FormalParameter", "additionalType": "File", "conformsTo": ref(BIOSCHEMAS_FORMAL_PARAMETER), "name": "user_settings", "valueRequired": "False"},
        {"@id": "#harmonized-release", "@type": "FormalParameter", "additionalType": "Dataset", "conformsTo": ref(BIOSCHEMAS_FORMAL_PARAMETER), "name": "harmonized release files", "valueRequired": "True"},
        {"@id": "#release-metadata", "@type": "FormalParameter", "additionalType": "Dataset", "conformsTo": ref(BIOSCHEMAS_FORMAL_PARAMETER), "name": "release metadata files", "valueRequired": "True"},
    ]:
        add_entity(graph, entity, seen)

    run_objects = [run_config_object, ref(release_id_map.get("manifest.json", "manifest.json")), ref(release_id_map.get("checksums.sha256", "checksums.sha256"))] + provenance_parts
    run_results = [ref(release_id_map[path]) for path in manifest.get("harmonized_files", []) if path in release_id_map]
    for value in ["fair/harmonized_netcdf_demo.croissant.jsonld", "validation/release_validation.json", "validation/harmonized_validation.json"]:
        if value in release_id_map:
            run_results.append(ref(release_id_map[value]))
    action_id = f"#run-{slug(release_id)}"
    add_entity(graph, {"@id": action_id, "@type": "CreateAction", "name": f"Run PROFECIA data-foundation workflow for {release_id}", "description": "Global workflow run that generated or registered source inputs, harmonized products and release metadata.", "instrument": ref("workflow/Snakefile"), "object": run_objects, "result": run_results, "agent": [ref("#person-fernando-aguilar-gomez"), ref("#workflow-snakemake")], "actionStatus": "https://schema.org/CompletedActionStatus"}, seen)

    for item in manifest.get("selected_variables", []):
        source = slug(item["source"])
        variable = slug(item["variable"])
        metadata = item.get("metadata") or {}
        raw_ids = [release_id_map[path] for path in item.get("raw_files") or [] if path in release_id_map]
        item_key = f"{item['source']}/{item['variable']}"
        provenance_ids = [
            provenance_id_map[str(prov.get("id"))]
            for prov in manifest.get("provenance_inputs", []) or []
            if item_key in (prov.get("used_by") or []) and str(prov.get("id")) in provenance_id_map
        ]
        harmonized_ids = [release_id_map[path] for path in item.get("harmonized_files") or [] if path in release_id_map]
        request_id = release_id_map.get(metadata.get("request", ""))
        inspection_id = release_id_map.get(metadata.get("inspection", ""))
        hval_id = release_id_map.get("validation/harmonized_validation.json")
        source_dataset_id = f"#source-{source}"
        prefix = f"#action-{source}-{variable}"
        if request_id:
            add_entity(graph, make_action(f"{prefix}-build-request", f"Build request for {item['source']}/{item['variable']}", "workflow/rules/acquire.smk", ["config/data_foundation_demo.yml"], [request_id], "Create source request metadata."), seen)
        add_entity(graph, make_action(f"{prefix}-acquire-source", f"Download or register source data for {item['source']}/{item['variable']}", "workflow/rules/acquire.smk", [x for x in [request_id, source_dataset_id] if x] + provenance_ids, raw_ids, "Acquire, download or register source/raw provenance inputs."), seen)
        if inspection_id:
            add_entity(graph, make_action(f"{prefix}-inspect-raw", f"Inspect raw NetCDF for {item['source']}/{item['variable']}", "workflow/rules/inspect.smk", raw_ids, [inspection_id], "Inspect source/raw NetCDF structure and basic metadata."), seen)
        add_entity(graph, make_action(f"{prefix}-harmonize", f"Harmonize monthly NetCDF for {item['source']}/{item['variable']}", "workflow/rules/harmonize.smk", raw_ids + provenance_ids + ([inspection_id] if inspection_id else []), harmonized_ids, "Transform source data to the PROFECIA target grid and harmonized NetCDF conventions."), seen)
        if hval_id:
            add_entity(graph, make_action(f"{prefix}-validate-harmonized", f"Validate harmonized NetCDF for {item['source']}/{item['variable']}", "workflow/rules/validate.smk", harmonized_ids, [hval_id], "Validate harmonized output dimensions, coordinates and data variables."), seen)
    if "manifest.json" in release_id_map:
        add_entity(graph, make_action(f"#action-write-manifest-{slug(release_id)}", "Write release manifest", "workflow/rules/metadata.smk", ["workflow/Snakefile"], [release_id_map["manifest.json"]], "Write machine-readable release manifest."), seen)
    if "fair/harmonized_netcdf_demo.croissant.jsonld" in release_id_map:
        add_entity(graph, make_action(f"#action-write-croissant-{slug(release_id)}", "Write Croissant descriptor", "workflow/rules/metadata.smk", manifest.get("harmonized_files", []), [release_id_map["fair/harmonized_netcdf_demo.croissant.jsonld"]], "Write ML discovery metadata for harmonized products."), seen)
    if "checksums.sha256" in release_id_map:
        add_entity(graph, make_action(f"#action-write-checksums-{slug(release_id)}", "Write checksums", "workflow/rules/metadata.smk", sorted(release_id_map.values()), [release_id_map["checksums.sha256"]], "Write SHA256 checksums for data, validation and metadata artifacts."), seen)
    if "validation/release_validation.json" in release_id_map:
        add_entity(graph, make_action(f"#action-validate-release-{slug(release_id)}", "Validate release package", "workflow/rules/validate.smk", [release_id_map.get("manifest.json", "manifest.json"), release_id_map.get("checksums.sha256", "checksums.sha256")], [release_id_map["validation/release_validation.json"]], "Validate release-level requirements."), seen)

    root_dataset = {
        "@id": "./",
        "@type": "Dataset",
        "name": "PROFECIA Data Foundation Demo Release",
        "description": "Reproducible PROFECIA data-foundation demo release generated by a Snakemake workflow. Harmonized NetCDF files are the main scientific data products; raw/source data are provenance inputs used to regenerate them.",
        "identifier": release_id,
        "version": release_id,
        "dateCreated": datetime.now(timezone.utc).date().isoformat(),
        "creator": ref("#person-fernando-aguilar-gomez"),
        "maintainer": ref("#person-fernando-aguilar-gomez"),
        "contactPoint": ref("#person-fernando-aguilar-gomez"),
        "publisher": ref("#org-csic"),
        "funder": ref("#grant-pid2023-152114ob-i00"),
        "license": ref(METADATA_LICENSE),
        "keywords": ["PROFECIA", "RO-Crate", "Snakemake", "harmonized NetCDF", "data foundation", "reproducible workflow"],
        "conformsTo": [ref(RO_CRATE_PROFILE), ref(WORKFLOW_RO_CRATE_PROFILE), ref(PROCESS_RUN_PROFILE), ref(WORKFLOW_RUN_PROFILE)],
        "mainEntity": ref("workflow/Snakefile"),
        "mentions": [ref(action_id)] + [ref(f"#source-{slug(source)}") for source in manifest.get("selected_sources", [])],
        "hasPart": sorted({item["@id"]: item for item in has_part}.values(), key=lambda item: item["@id"]),
        "temporalCoverage": f"{release_data.get('start_year')}/{release_data.get('end_year')}",
        "spatialCoverage": {"@type": "Place", "name": (release_data.get("target_grid") or {}).get("name", "release target grid")},
    }
    if git_data:
        root_dataset["softwareVersion"] = git_data
    warnings = list(manifest.get("warnings") or []) + git_warnings
    if warnings:
        root_dataset["conditionsOfAccess"] = "Warnings: " + " | ".join(sorted(set(warnings)))
    graph.insert(1, root_dataset)

    crate = {"@context": RO_CRATE_CONTEXT, "@graph": graph}
    metadata_path.write_text(json.dumps(crate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_archive(archive_path, output_dir)
    print(f"Wrote RO-Crate metadata: {metadata_path}")
    print(f"Wrote RO-Crate archive: {archive_path}")


if __name__ == "__main__":
    main()
