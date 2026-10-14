#!/usr/bin/env python3
"""Write a referential Workflow/Data RO-Crate for a PROFECIA release."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import html
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

import yaml

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, release, release_base_dir


RO_CRATE_CONTEXT = [
    "https://w3id.org/ro/crate/1.1/context",
    "https://w3id.org/ro/terms/workflow-run/context",
]
RO_CRATE_PROFILE = "https://w3id.org/ro/crate/1.1"
WORKFLOW_RO_CRATE_PROFILE = "https://w3id.org/workflowhub/workflow-ro-crate/1.0"
PROCESS_RUN_PROFILE = "https://w3id.org/ro/wfrun/process/0.5"
WORKFLOW_RUN_PROFILE = "https://w3id.org/ro/wfrun/workflow/0.5"
BIOSCHEMAS_FORMAL_PARAMETER = "https://bioschemas.org/profiles/FormalParameter/1.0-RELEASE"
BIOSCHEMAS_COMPUTATIONAL_WORKFLOW = "https://bioschemas.org/profiles/ComputationalWorkflow/1.0-RELEASE"
SNAKEMAKE_LANGUAGE = "https://snakemake.github.io/"
PROV_O = "http://www.w3.org/ns/prov-o#"
DCTERMS = "http://purl.org/dc/terms/"
DCAT = "http://www.w3.org/ns/dcat#"
PAV = "http://purl.org/pav/"
SKOS = "http://www.w3.org/2004/02/skos/core#"
QUDT = "http://qudt.org/schema/qudt/"
PROFECIA_STEP_PROFILE = "https://w3id.org/profecia/profile/preprocessing-step/1.0"
PROFECIA_TERMS = "https://w3id.org/profecia/terms/"
PROFECIA_STEP_TYPES = "https://w3id.org/profecia/vocab/preprocessing-step-type/"
FAIR4PREP = "https://w3id.org/fair4prep#"
RELIANCE_PROFILE = "https://reliance-eosc.github.io/reliance-ro-crate/"
RELIANCE_TERMS = "https://w3id.org/reliance/terms/"
EUROVOC_DATASET = "http://publications.europa.eu/resource/dataset/eurovoc"
EUROVOC_EARTH_OBSERVATION = "http://eurovoc.europa.eu/c_a935cf3f"
NETCDF_MEDIA_TYPE = "application/x-netcdf"
METADATA_LICENSE = "https://spdx.org/licenses/CC0-1.0.html"
DATA_LICENSE = "https://spdx.org/licenses/CC-BY-4.0.html"
CODE_LICENSE = "https://spdx.org/licenses/Apache-2.0.html"
SEMANTIC_CONTEXT = {
    "profecia": PROFECIA_TERMS,
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "pav": "http://purl.org/pav/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "qudt": "http://qudt.org/schema/qudt/",
    "reliance": RELIANCE_TERMS,
    "spdx": "https://spdx.org/licenses/",
    "unitText": "http://schema.org/unitText",
    "mathExpression": "http://schema.org/mathExpression",
}


def posix_rel(path: Path, start: Path) -> str:
    return Path(os.path.relpath(path, start)).as_posix()


def crate_id(path: Path, crate_dir: Path) -> str:
    return posix_rel(path, crate_dir)


def ref(entity_id: str) -> dict[str, str]:
    return {"@id": entity_id}


def refs(entity_ids: list[str]) -> list[dict[str, str]]:
    return [ref(entity_id) for entity_id in entity_ids]


PROVIDER_BY_SOURCE = {
    "era5_single_levels": "https://ror.org/014w0fd65",
    "carbontracker_co2": "https://ror.org/02z5nhe81",
    "ndep_tian2022": "#org-pangaea",
    "hfp_mu_hengl": "#org-figshare-zenodo",
    "hwsd2": "https://ror.org/00pe0tf51",
    "speibase_v211": "https://ror.org/02gfc7t72",
    "derived_soil_water": "#org-ifca-csic",
    "derived_climate": "#org-ifca-csic",
    "derived_drought_index": "#org-ifca-csic",
    "local_annual": "#org-ifca-csic",
    "local_static": "#org-ifca-csic",
    "local_hwsd2_monthly": "#org-ifca-csic",
    "local_lai": "#org-ifca-csic",
    "derived_human": "#org-ifca-csic",
}

UNIT_IRIS = {
    "K": "http://qudt.org/vocab/unit/K",
    "m": "http://qudt.org/vocab/unit/M",
    "m s**-1": "http://qudt.org/vocab/unit/M-PER-SEC",
    "J m**-2": "http://qudt.org/vocab/unit/J-PER-M2",
    "m**3 m**-3": "http://qudt.org/vocab/unit/M3-PER-M3",
    "0-1": "http://qudt.org/vocab/unit/UNITLESS",
    "kPa": "http://qudt.org/vocab/unit/KiloPA",
    "kg N/ha/yr": "http://qudt.org/vocab/unit/KiloGM-PER-HA-YR",
    "m2 m-2": "http://qudt.org/vocab/unit/M2-PER-M2",
}


def provider_ref(source_id: str) -> dict[str, str]:
    return ref(PROVIDER_BY_SOURCE.get(source_id, "#org-ifca-csic"))


def source_urls(source: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return explicit landing/access URLs already present in configuration."""
    landing = source.get("landing_page")
    access = source.get("base_url")
    for key in ("api_url", "url"):
        if not access and isinstance(source.get(key), str):
            access = source[key]
    for value in source.values():
        if not isinstance(value, dict):
            continue
        if not landing and isinstance(value.get("landing_page"), str):
            landing = value["landing_page"]
        if not access:
            for key in ("api_url", "base_url", "url"):
                if isinstance(value.get(key), str):
                    access = value[key]
                    break
    return landing, access

def slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value))
    return "-".join(part for part in cleaned.split("-") if part)


def canonical_crate_path(source_path: Path, *, base_dir: Path, workflow_dir: Path, config_dir: Path) -> Path:
    # Preserve release-relative paths even for symlinked cached inputs. A replay
    # config may live inside the release; its parent must not capture all outputs.
    source_path = source_path.absolute()
    try:
        relative = source_path.relative_to(base_dir)
    except ValueError:
        relative = None
    if relative is not None:
        if relative.parts and relative.parts[0] in {"metadata", "fair", "validation"}:
            return relative
        if relative.name in {"manifest.json", "checksums.sha256", "CITATION.cff"}:
            return relative
        if source_path.parent == config_dir and source_path.suffix in {".yaml", ".yml"}:
            return Path("config") / relative.name
        return Path("referenced-data") / relative
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


def copy_config_into_crate(source_path: Path, crate_dir: Path, relative_path: Path) -> Path:
    target = crate_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    data = load_config(source_path)
    if data.get("offline_inputs"):
        def portable_workflow_paths(value):
            if isinstance(value, dict):
                return {key: portable_workflow_paths(item) for key, item in value.items()}
            if isinstance(value, list):
                return [portable_workflow_paths(item) for item in value]
            if isinstance(value, str) and value.startswith("workflows/data_foundation/workflow/"):
                return "workflow/" + value[len("workflows/data_foundation/workflow/"):]
            return value
        data = portable_workflow_paths(data)
    allowlist = copy_allowlist_patterns(data)
    lai_product = "monthly/lai_1982_2022_monthly_0.5deg.nc"
    if matches_allowlist(lai_product, allowlist) and not data.get("reproduction_assets"):
        canonical_refs = data.setdefault("canonical_reference_products", {})
        canonical_refs.setdefault("monthly/lai", f"referenced-data/{lai_product}")
    target.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    shutil.copystat(source_path, target)
    return target


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def apply_run_metadata(action: dict[str, Any], environment: dict[str, Any], path: Path | None) -> None:
    """Apply captured runtime facts when a future execution supplies them; never synthesize history."""
    if path is None or not path.exists():
        return
    data = read_json(path)
    mappings = {
        "run_id": "identifier",
        "start_time": "startTime",
        "end_time": "endTime",
        "duration": "duration",
        "error": "error",
    }
    for source, target in mappings.items():
        if data.get(source) is not None:
            action[target] = data[source]
    status = data.get("status")
    if status:
        action["actionStatus"] = {
            "completed": "http://schema.org/CompletedActionStatus",
            "failed": "http://schema.org/FailedActionStatus",
            "active": "http://schema.org/ActiveActionStatus",
        }.get(str(status).lower(), status)
    environment_fields = {
        "snakemake_version": "profecia:snakemakeVersion",
        "python_version": "profecia:pythonVersion",
        "conda_environment": "profecia:condaEnvironment",
        "platform": "profecia:platform",
        "container": "profecia:container",
        "container_digest": "profecia:containerDigest",
        "git_commit": "profecia:gitCommit",
        "git_base_commit": "profecia:baseGitCommit",
    }
    for source, target in environment_fields.items():
        if data.get(source) is not None:
            environment[target] = data[source]
    environment["profecia:recordingStatus"] = "recorded-effective-environment"
    if data.get("start_time") and data.get("end_time"):
        action["profecia:recordingStatus"] = "captured-current-execution"
    action["subjectOf"] = ref("metadata/workflow-run.json")

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
    if path.name == "Snakefile":
        return "text/x-snakemake"
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


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def ref_id(value: Any) -> str | None:
    if isinstance(value, dict):
        item = value.get("@id")
        return str(item) if item else None
    if isinstance(value, str):
        return value
    return None


def ref_ids(value: Any) -> list[str]:
    ids: list[str] = []
    for item in as_list(value):
        item_id = ref_id(item)
        if item_id:
            ids.append(item_id)
    return ids


def add_type(entity: dict[str, Any], *types: str) -> None:
    current = as_list(entity.get("@type"))
    entity["@type"] = sorted({str(item) for item in current + list(types)})


def add_refs(entity: dict[str, Any], key: str, entity_ids: list[str]) -> None:
    existing = ref_ids(entity.get(key))
    merged = sorted({*existing, *[item for item in entity_ids if item]})
    if merged:
        entity[key] = refs(merged)


def add_or_update_entity(graph: list[dict[str, Any]], entity: dict[str, Any], seen: set[str]) -> None:
    entity_id = str(entity["@id"])
    for existing in graph:
        if str(existing.get("@id")) != entity_id:
            continue
        for key, value in entity.items():
            if key == "@id":
                continue
            if key == "@type":
                existing_types = existing.get("@type", [])
                if not isinstance(existing_types, list):
                    existing_types = [existing_types]
                value_types = value if isinstance(value, list) else [value]
                existing["@type"] = sorted({*existing_types, *value_types})
                continue
            if key not in existing or existing[key] is None or existing[key] == "":
                existing[key] = value
            elif key in {"additionalType", "contentUrl", "usageInfo", "usedBy", "isPartOf", "sha256"}:
                existing[key] = value
        return
    add_entity(graph, entity, seen)


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


def semantic_asset_files(project_root: Path) -> list[Path]:
    root = project_root / "workflows" / "data_foundation" / "metadata" / "vocabulary"
    if not root.exists():
        root = project_root / "metadata" / "vocabulary"
    return sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []

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


def copy_allowlist_patterns(config: dict[str, Any]) -> list[str]:
    packaging = config.get("ro_crate_packaging") or {}
    return [str(pattern) for pattern in packaging.get("copy_allowlist", []) or []]


def matches_allowlist(relative_path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in patterns)


def should_copy_release_file(relative_path: str, config: dict[str, Any]) -> bool:
    packaging = config.get("ro_crate_packaging") or {}
    allowlist = copy_allowlist_patterns(config)
    if matches_allowlist(relative_path, allowlist):
        return True
    if relative_path.startswith("raw/") and not bool(packaging.get("copy_raw_inputs", True)):
        return False
    if relative_path.endswith(".nc") and not bool(packaging.get("copy_harmonized_outputs", False)):
        return False
    return True


def allowlisted_project_files(project_root: Path, base_dir: Path, patterns: list[str]) -> list[Path]:
    files: set[Path] = set()
    for pattern in patterns:
        if Path(pattern).is_absolute():
            candidates = [path for path in Path("/").glob(pattern.lstrip("/"))]
        else:
            candidates = list(project_root.glob(pattern)) + list(base_dir.glob(pattern))
        for candidate in candidates:
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            try:
                resolved.relative_to(base_dir)
                continue
            except ValueError:
                pass
            files.add(resolved)
    return sorted(files)


def workflow_relative_entity_id(path: Path, workflow_dir: Path) -> str | None:
    try:
        return (Path("workflow") / path.resolve().relative_to(workflow_dir)).as_posix()
    except ValueError:
        return None


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
    if dirty:
        warnings.append("Git working tree contains uncommitted changes; the recorded commit is the base revision, not an exact identifier for the packaged source snapshot.")
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


def write_readme(path: Path, release_id: str, archive_path: Path, complete: bool = False) -> None:
    text = f"""# PROFECIA Data Foundation Demo Release

This RO-Crate describes the PROFECIA data-foundation demo release `{release_id}`. It packages the workflow code, safe configuration examples, provenance metadata, validation summaries, checksums, a Croissant descriptor for discovery, and the small data artifacts explicitly needed inside the crate.

## Official Products

The official scientific outputs are the harmonized NetCDF products on the PROFECIA target grid. To keep the RO-Crate lightweight, large raw/source inputs and most harmonized NetCDF products are represented as referenced entities with path, checksum/size where available, request metadata, and source dataset terms. The monthly LAI NetCDF product and reusable mask arrays are copied into the crate as packaging exceptions; the original LAI H5.GZ composites are referenced as provenance inputs, not redistributed.

## LAI Preprocessing

The packaged monthly LAI NetCDF is generated from local THEIA GEOV2-GCM AVHRR 10-day H5.GZ composites by `workflow/scripts/common/process_lai.py`. The workflow reads each composite, converts digital numbers to physical LAI with `LAI = DN / 30`, masks invalid DN values outside `[0, 210]`, and writes monthly means on the PROFECIA 0.5 degree grid.

## Regeneration

Install the workflow requirements, provide local credentials where a source requires them, and run the Snakemake workflow with a safe release config. Workflow scripts, including the legacy preprocessing scripts needed for canonical reproduction, are included. Safe credential templates are included; real credentials and local secrets are intentionally excluded.

## Validation

Run `sha256sum -c checksums.sha256` from the release directory to verify checksums. Review `validation/harmonized_validation.json` for harmonized product checks and `validation/release_validation.json` for release-level checks and warnings.

## Licenses

Metadata is CC0-1.0. Derived harmonized data products are CC-BY-4.0. Workflow/code files are Apache-2.0. External source datasets remain governed by their original provider terms and may require credentials or manual access.

## Citation

No DOI has been assigned yet. Cite the release title, release identifier `{release_id}`, creator Fernando Aguilar Gomez, CSIC, and the eventual ROHub URL/DOI when available.

## ROHub Notes

Upload `{archive_path.name}` to ROHub after confirming validation status, checksum coverage, and absence of secrets. ROHub is the target platform, not the scientific publisher.
"""
    if complete:
        text = f"""# PROFECIA Data Foundation Release {release_id}

This package contains every harmonized product declared in `manifest.json`,
the cached raw inputs used by this configuration, and effective canonical/LAI
input snapshots under `reproduction/inputs/`. Historical sources not used by
this execution remain explicitly contextual external references.

Start with [the external tester guide](reproduction/EXTERNAL_TESTER_GUIDE.md).
Use `reproduction/config.yml` and `reproduction/reproduce.py` for portable
re-execution; the original configuration records the generating host paths.
The exact dependency lock is `reproduction/requirements.lock.txt`.

The reference products are in `monthly/`, `annual/` and `static/`. Compare all
products using `reproduction/compare_releases.py`. The global observed execution
is recorded in `metadata/workflow-run.json`; its scope includes cached acquisition
inputs and explicit canonical-product incorporation. Individual historical
activities are not assigned invented execution timestamps.

Metadata/code/data licenses are described in the graph. Upstream source terms
remain applicable to the included inputs. No DOI has been assigned.
Archive: `{archive_path.name}`.
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


def write_preview(path: Path, release_id: str) -> None:
    safe_release = html.escape(release_id)
    text = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>PROFECIA RO-Crate {safe_release}</title>
<style>body{{font:16px system-ui;max-width:900px;margin:2rem auto;padding:0 1rem}}code{{background:#eee;padding:.15rem .3rem}}li{{margin:.45rem 0}}</style></head>
<body><h1>PROFECIA Data Foundation Release</h1><p>Release <code>{safe_release}</code>.</p>
<p>This preview provides entry points into the machine-actionable research object.</p><ul>
<li><a href="ro-crate-metadata.json">RO-Crate JSON-LD descriptor</a></li>
<li><a href="workflow/Snakefile">Main Snakemake workflow</a></li>
<li><a href="fair/harmonized_netcdf_demo.croissant.jsonld">Croissant descriptor</a></li>
<li><a href="README.md">Publication and regeneration notes</a></li>
<li><a href="metadata/vocabulary/index.html">PROFECIA vocabulary documentation</a></li>
</ul></body></html>\n"""
    path.write_text(text, encoding="utf-8")


def write_archive(archive_path: Path, crate_dir: Path, compression: str = "deflated") -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if compression not in {"stored", "deflated"}:
        raise ValueError("archive_compression must be stored or deflated")
    codec = zipfile.ZIP_STORED if compression == "stored" else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(archive_path, "w", compression=codec) as archive:
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
        "actionStatus": "http://schema.org/CompletedActionStatus",
    }
    if objects:
        entity["object"] = [ref(item) for item in sorted(set(objects))]
    if results:
        entity["result"] = [ref(item) for item in sorted(set(results))]
    entity["agent"] = [ref("#person-fernando-aguilar-gomez"), ref("#workflow-snakemake")]
    return entity


STEP_TYPE_DEFINITIONS: dict[str, dict[str, str | None]] = {
    "workflow-run": {"en": "workflow run", "es": "ejecución de workflow", "definition": "Execution of the overall preprocessing workflow.", "broader": None},
    "request-building": {"en": "request building", "es": "construcción de petición", "definition": "Construction of a machine-readable request to a data provider.", "broader": "acquisition"},
    "acquisition": {"en": "acquisition", "es": "adquisición", "definition": "Retrieval or registration of source data.", "broader": None},
    "manual-acquisition": {"en": "manual acquisition", "es": "adquisición manual", "definition": "Registration of source data obtained through a manual mechanism.", "broader": "acquisition"},
    "inspection": {"en": "inspection", "es": "inspección", "definition": "Inspection of data structure, coordinates, variables, or metadata.", "broader": "quality-control"},
    "format-conversion": {"en": "format conversion", "es": "conversión de formato", "definition": "Conversion between physical data encodings or formats.", "broader": "scientific-preprocessing"},
    "spatial-harmonization": {"en": "spatial harmonization", "es": "armonización espacial", "definition": "Transformation to common spatial conventions, coverage, or grid.", "broader": "scientific-preprocessing"},
    "reprojection": {"en": "reprojection", "es": "reproyección", "definition": "Transformation between coordinate reference systems.", "broader": "spatial-harmonization"},
    "regridding": {"en": "regridding", "es": "cambio de rejilla", "definition": "Transformation from a source grid to a target grid.", "broader": "spatial-harmonization"},
    "spatial-resampling": {"en": "spatial resampling", "es": "remuestreo espacial", "definition": "Estimation of values at new spatial support or resolution.", "broader": "spatial-harmonization"},
    "temporal-harmonization": {"en": "temporal harmonization", "es": "armonización temporal", "definition": "Transformation to common temporal conventions or cadence.", "broader": "scientific-preprocessing"},
    "temporal-aggregation": {"en": "temporal aggregation", "es": "agregación temporal", "definition": "Aggregation from a finer to a coarser temporal resolution.", "broader": "temporal-harmonization"},
    "temporal-interpolation": {"en": "temporal interpolation", "es": "interpolación temporal", "definition": "Estimation of values at unsampled temporal positions.", "broader": "temporal-harmonization"},
    "unit-conversion": {"en": "unit conversion", "es": "conversión de unidades", "definition": "Conversion of measurements between compatible units.", "broader": "scientific-preprocessing"},
    "normalization": {"en": "normalization", "es": "normalización", "definition": "Transformation of values to a common numerical scale or convention.", "broader": "scientific-preprocessing"},
    "derived-variable": {"en": "derived variable", "es": "variable derivada", "definition": "Computation of a scientific variable from one or more input variables.", "broader": "scientific-preprocessing"},
    "masking": {"en": "masking", "es": "enmascarado", "definition": "Exclusion or marking of values according to a mask or validity rule.", "broader": "scientific-preprocessing"},
    "feature-selection": {"en": "feature selection", "es": "selección de variables", "definition": "Selection of variables or features for downstream use.", "broader": "scientific-preprocessing"},
    "static-to-dynamic-expansion": {"en": "static to dynamic expansion", "es": "expansión estática a dinámica", "definition": "Repetition of a static field over an explicit temporal axis.", "broader": "temporal-harmonization"},
    "scientific-preprocessing": {"en": "scientific preprocessing", "es": "preprocesado científico", "definition": "Scientific transformation that prepares data for downstream analysis.", "broader": None},
    "metadata-generation": {"en": "metadata generation", "es": "generación de metadatos", "definition": "Generation of machine-readable descriptive or provenance metadata.", "broader": None},
    "quality-control": {"en": "quality control", "es": "control de calidad", "definition": "Assessment of a resource against explicit quality criteria.", "broader": None},
    "packaging": {"en": "packaging", "es": "empaquetado", "definition": "Assembly of data and metadata into a distributable research object.", "broader": None},
    "manual-decision": {"en": "manual decision", "es": "decisión manual", "definition": "A documented human decision that affects preprocessing.", "broader": None},
}


def step_type_ref(step_type: str) -> dict[str, str]:
    return ref(f"{PROFECIA_STEP_TYPES}{step_type}")


def step_type_for_action(action: dict[str, Any]) -> str:
    action_id = str(action.get("@id", ""))
    name = str(action.get("name", "")).lower()
    if action_id.startswith("#run-"):
        return "workflow-run"
    if "build-request" in action_id:
        return "request-building"
    if "acquire-source" in action_id:
        return "acquisition"
    if "inspect-raw" in action_id:
        return "inspection"
    if "validate" in action_id:
        return "quality-control"
    if "manifest" in action_id or "croissant" in action_id or "checksums" in action_id:
        return "metadata-generation"
    if "ro-crate" in action_id or "package" in name:
        return "packaging"
    if "harmonize" in action_id:
        if any(token in action_id for token in ["derived-", "local-lai", "local-hwsd2-monthly", "derived-human"]):
            return "derived-variable"
        return "spatial-harmonization"
    return "scientific-preprocessing"


def add_vocabulary_entities(graph: list[dict[str, Any]], seen: set[str]) -> None:
    vocabularies = [
        (RO_CRATE_PROFILE, "RO-Crate", "1.1"),
        (WORKFLOW_RO_CRATE_PROFILE, "Workflow RO-Crate", "1.0"),
        (PROCESS_RUN_PROFILE, "Process Run Crate", "0.5"),
        (WORKFLOW_RUN_PROFILE, "Workflow Run Crate", "0.5"),
        (BIOSCHEMAS_COMPUTATIONAL_WORKFLOW, "Bioschemas ComputationalWorkflow", "1.0-RELEASE"),
        (PROV_O, "PROV-O", ""),
        (DCTERMS, "Dublin Core Terms", ""),
        (DCAT, "Data Catalog Vocabulary", ""),
        (PAV, "Provenance, Authoring and Versioning", ""),
        (SKOS, "Simple Knowledge Organization System", ""),
        (QUDT, "Quantities, Units, Dimensions and Types", ""),
        (PROFECIA_STEP_PROFILE, "PROFECIA Preprocessing Step Profile", "1.0"),
    ]
    for vocab_id, name, version in vocabularies:
        entity: dict[str, Any] = {"@id": vocab_id, "@type": ["CreativeWork", "prov:Entity"], "name": name}
        if version:
            entity["version"] = version
        add_or_update_entity(graph, entity, seen)


def add_skos_step_types(graph: list[dict[str, Any]], seen: set[str]) -> None:
    top_concepts = [key for key, value in STEP_TYPE_DEFINITIONS.items() if value["broader"] is None]
    add_or_update_entity(
        graph,
        {
            "@id": PROFECIA_STEP_TYPES,
            "@type": ["skos:ConceptScheme", "CreativeWork", "prov:Entity"],
            "name": "PROFECIA preprocessing step types",
            "skos:prefLabel": [
                {"@value": "PROFECIA preprocessing step types", "@language": "en"},
                {"@value": "Tipos de paso de preprocesado PROFECIA", "@language": "es"},
            ],
            "skos:definition": "Extensible controlled vocabulary used with profecia:stepType; its concepts are not OWL classes.",
            "skos:hasTopConcept": refs([f"{PROFECIA_STEP_TYPES}{key}" for key in top_concepts]),
            "version": "1.0.0",
            "creativeWorkStatus": "stable",
        },
        seen,
    )
    for key, details in STEP_TYPE_DEFINITIONS.items():
        entity: dict[str, Any] = {
            "@id": f"{PROFECIA_STEP_TYPES}{key}",
            "@type": "skos:Concept",
            "skos:prefLabel": [
                {"@value": details["en"], "@language": "en"},
                {"@value": details["es"], "@language": "es"},
            ],
            "skos:definition": details["definition"],
            "skos:inScheme": ref(PROFECIA_STEP_TYPES),
        }
        if details["broader"]:
            entity["skos:broader"] = step_type_ref(str(details["broader"]))
        else:
            entity["skos:topConceptOf"] = ref(PROFECIA_STEP_TYPES)
        add_or_update_entity(graph, entity, seen)

def add_research_area_entities(graph: list[dict[str, Any]], seen: set[str]) -> None:
    add_or_update_entity(
        graph,
        {
            "@id": EUROVOC_DATASET,
            "@type": ["CreativeWork", "skos:ConceptScheme", "prov:Entity"],
            "name": "EuroVoc",
            "dcterms:title": "EuroVoc",
            "dcterms:description": "Multilingual controlled vocabulary maintained by the Publications Office of the European Union.",
        },
        seen,
    )
    add_or_update_entity(
        graph,
        {
            "@id": EUROVOC_EARTH_OBSERVATION,
            "@type": ["DefinedTerm", "skos:Concept", "prov:Entity"],
            "name": "Earth observation",
            "termCode": "c_a935cf3f",
            "inDefinedTermSet": ref(EUROVOC_DATASET),
            "skos:prefLabel": "Earth observation",
            "skos:inScheme": ref(EUROVOC_DATASET),
        },
        seen,
    )


def temporal_kind_for_release_path(entity_id: str) -> str | None:
    if entity_id.startswith("referenced-data/monthly/") and entity_id.endswith(".nc"):
        return "monthly"
    if entity_id.startswith("referenced-data/annual/") and entity_id.endswith(".nc"):
        return "annual"
    return None


def add_reliance_profile_entities(graph: list[dict[str, Any]], seen: set[str]) -> None:
    add_or_update_entity(
        graph,
        {
            "@id": RELIANCE_PROFILE,
            "@type": ["CreativeWork", "prov:Entity"],
            "name": "RELIANCE RO-Crate profile",
            "version": "1.0",
            "description": "RO-Crate profile for packaging Earth Science and Earth Observation data cubes.",
            "url": RELIANCE_PROFILE,
        },
        seen,
    )


def add_reliance_coverage_entities(graph: list[dict[str, Any]], seen: set[str]) -> None:
    add_or_update_entity(
        graph,
        {
            "@id": "#reliance-spatial-global-0p5deg",
            "@type": "Place",
            "name": "Global 0.5 degree PROFECIA grid",
            "description": "Global regular latitude-longitude grid used by PROFECIA harmonized products.",
            "reliance:extent": "POLYGON((-180 -90, 180 -90, 180 90, -180 90, -180 -90))",
            "reliance:spatial-step-resolution": "0.5 degree",
            "reliance:coordinate-reference-system": "EPSG:4326",
        },
        seen,
    )
    for temporal_id, name, step, unit in [
        ("#reliance-temporal-monthly-1982-2022", "Monthly temporal coverage 1982-2022", "P1M", "month"),
        ("#reliance-temporal-annual-1982-2022", "Annual temporal coverage 1982-2022", "P1Y", "year"),
    ]:
        add_or_update_entity(
            graph,
            {
                "@id": temporal_id,
                "@type": "Thing",
                "name": name,
                "temporalCoverage": "1982/2022",
                "reliance:beginningTime": "1982-01-01",
                "reliance:endTime": "2022-12-31",
                "reliance:temporal-step-resolution": step,
                "reliance:temporal-reference-system-unit": unit,
            },
            seen,
        )


def data_type_unit_for_product(entity: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    for variable_id in ref_ids(entity.get("variableMeasured")):
        variable = by_id.get(variable_id)
        if not variable:
            continue
        for key in ("unitText", "unitCode"):
            value = variable.get(key)
            if value:
                return str(value)
    return "unspecified"


def add_reliance_datacube_layer(graph: list[dict[str, Any]], seen: set[str]) -> None:
    by_id = {str(entity.get("@id")): entity for entity in graph if entity.get("@id")}
    harmonized = by_id.get("#dataset-harmonized")
    if harmonized:
        add_type(harmonized, "DataCubeCollection")
        harmonized["reliance:spatialCoverage"] = ref("#reliance-spatial-global-0p5deg")
        harmonized["reliance:temporalCoverage"] = [
            ref("#reliance-temporal-monthly-1982-2022"),
            ref("#reliance-temporal-annual-1982-2022"),
        ]
        harmonized["temporalCoverage"] = "1982/2022"
        harmonized["contentLocation"] = ref("#reliance-spatial-global-0p5deg")

    for entity_id, entity in by_id.items():
        temporal_kind = temporal_kind_for_release_path(entity_id)
        if temporal_kind is None:
            continue
        if ref_id(entity.get("isPartOf")) != "#dataset-harmonized" and ref_id(entity.get("dcterms:isPartOf")) != "#dataset-harmonized":
            continue
        add_type(entity, "DataCubeProduct")
        temporal_ref = "#reliance-temporal-monthly-1982-2022" if temporal_kind == "monthly" else "#reliance-temporal-annual-1982-2022"
        entity["reliance:spatialCoverage"] = ref("#reliance-spatial-global-0p5deg")
        entity["reliance:temporalCoverage"] = ref(temporal_ref)
        entity["contentLocation"] = ref("#reliance-spatial-global-0p5deg")
        entity["temporalCoverage"] = "1982/2022"
        entity["reliance:product-type"] = f"{temporal_kind} harmonized NetCDF data cube"
        entity["reliance:data-type-unit"] = data_type_unit_for_product(entity, by_id)
        entity["reliance:processing-level"] = "harmonized PROFECIA 0.5 degree product"
        entity["reliance:processor"] = ref("workflow/Snakefile")
        entity["reliance:dataquality"] = ref("validation/harmonized_validation.json")


def add_dcterms_and_dcat(entity: dict[str, Any]) -> None:
    """Add compatibility terms without changing the canonical Schema.org values."""
    pairs = {
        "name": "dcterms:title",
        "description": "dcterms:description",
        "identifier": "dcterms:identifier",
        "dateCreated": "dcterms:created",
        "temporalCoverage": "dcterms:temporal",
        "spatialCoverage": "dcterms:spatial",
        "license": "dcterms:license",
        "encodingFormat": "dcterms:format",
        "isPartOf": "dcterms:isPartOf",
    }
    for canonical, compatibility in pairs.items():
        if entity.get(canonical) is not None and compatibility not in entity:
            entity[compatibility] = entity[canonical]

    types = set(str(item) for item in as_list(entity.get("@type")))
    if "Dataset" in types:
        add_type(entity, "prov:Entity", "dcat:Dataset")
    if entity.get("contentUrl") or ("File" in types and entity.get("encodingFormat")):
        add_type(entity, "dcat:Distribution", "prov:Entity")
        content_url = entity.get("contentUrl")
        if isinstance(content_url, str) and content_url.startswith(("http://", "https://")):
            entity.setdefault("dcat:downloadURL", ref(content_url))
        if entity.get("encodingFormat"):
            entity.setdefault("dcat:mediaType", entity["encodingFormat"])
    if entity.get("profecia:formula"):
        entity.setdefault("mathExpression", entity["profecia:formula"])


def enhance_actions_and_outputs(graph: list[dict[str, Any]]) -> None:
    """Map Schema.org process provenance to PROV-O without confusing plans and agents."""
    by_id = {str(entity.get("@id")): entity for entity in graph if entity.get("@id")}
    for action in graph:
        if "CreateAction" not in as_list(action.get("@type")):
            continue
        add_type(action, "CreateAction", "prov:Activity")
        action["agent"] = ref("#person-fernando-aguilar-gomez")
        action["prov:wasAssociatedWith"] = ref("#workflow-snakemake")
        add_dcterms_and_dcat(action)
        object_ids = ref_ids(action.get("object"))
        result_ids = ref_ids(action.get("result"))
        if object_ids:
            add_refs(action, "prov:used", object_ids)
        if result_ids:
            add_refs(action, "prov:generated", result_ids)
        for result_id in result_ids:
            result = by_id.get(result_id)
            if not result:
                continue
            add_type(result, "prov:Entity")
            add_refs(result, "prov:wasGeneratedBy", [str(action["@id"])])
            if str(action.get("@id", "")).startswith("#run-"):
                continue
            direct_sources = [
                source_id
                for source_id in object_ids
                if source_id in by_id
                and source_id not in {"workflow/Snakefile", "checksums.sha256", "manifest.json"}
                and not source_id.startswith("#")
                and not source_id.startswith("workflow/rules/")
            ]
            if direct_sources:
                add_refs(result, "prov:wasDerivedFrom", direct_sources)
                add_refs(result, "dcterms:source", direct_sources)

def add_distribution_links(graph: list[dict[str, Any]]) -> None:
    by_id = {str(entity.get("@id")): entity for entity in graph if entity.get("@id")}
    for dataset_id in ["#dataset-harmonized", "#dataset-raw-provenance", "#dataset-validation-reports", "#dataset-packaged-auxiliary"]:
        dataset = by_id.get(dataset_id)
        if not dataset:
            continue
        part_ids = ref_ids(dataset.get("hasPart"))
        distributions = [
            part_id
            for part_id in part_ids
            if part_id in by_id and ("File" in as_list(by_id[part_id].get("@type")) or by_id[part_id].get("contentUrl"))
        ]
        if distributions:
            add_refs(dataset, "dcat:distribution", distributions)


def preprocessing_step(
    step_id: str,
    name: str,
    description: str,
    step_types: str | list[str],
    inputs: list[str],
    outputs: list[str],
    script: str,
    action_ids: list[str],
    *,
    method: str,
    formula: str | None = None,
    parameters: list[dict[str, Any]] | None = None,
    rationale: str | None = None,
    missing_data_policy: str | None = None,
    quality_control: str = "Validated by the aggregate harmonized-product validation activity and report.",
) -> dict[str, Any]:
    """Build prospective provenance only; execution properties belong on activities."""
    types = [step_types] if isinstance(step_types, str) else step_types
    entity: dict[str, Any] = {
        "@id": step_id,
        "@type": ["profecia:PreprocessingStep", "prov:Plan"],
        "name": name,
        "description": description,
        "profecia:stepType": [step_type_ref(value) for value in types],
        "profecia:input": refs(inputs),
        "profecia:output": refs(outputs),
        "profecia:appliesTo": refs(inputs),
        "profecia:method": method,
        "profecia:implementedBy": ref(script),
        "profecia:relatedWorkflowAction": refs(action_ids),
        "profecia:status": "documented",
        "profecia:confidence": "explicit",
        "profecia:qualityControl": ref("validation/harmonized_validation.json"),
    }
    if formula:
        entity["profecia:formula"] = formula
        entity["mathExpression"] = formula
    if parameters:
        entity["profecia:parameter"] = parameters
    if rationale:
        entity["profecia:rationale"] = rationale
    if missing_data_policy:
        entity["profecia:missingDataPolicy"] = missing_data_policy
    if quality_control:
        entity["description"] = f"{description} Quality control: {quality_control}"
    return entity


def qualified_plan_association(action: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    action_slug = slug(str(action["@id"]).lstrip("#"))
    step_slug = slug(str(step["@id"]).lstrip("#"))
    return {
        "@id": f"#association-{action_slug}-{step_slug}",
        "@type": "prov:Association",
        "prov:agent": ref("#workflow-snakemake"),
        "prov:hadPlan": ref(str(step["@id"])),
        "name": f"Plan association for {action.get('name', action['@id'])}",
    }

def add_preprocessing_steps(graph: list[dict[str, Any]], seen: set[str]) -> None:
    soil_monthly_outputs = [
        f"referenced-data/monthly/{name}_1982_2022_monthly_0.5deg.nc"
        for name in ["ph", "bulk", "cec", "clay", "sand", "silt", "soc", "total_n"]
    ]
    steps = [
        preprocessing_step(
            "#prep-derived-swvl1-2",
            "Derive topsoil moisture 0-28 cm",
            "Compute a thickness-weighted volumetric soil water content for the 0-28 cm layer from ERA5 soil water layers 1 and 2.",
            "derived-variable",
            ["referenced-data/monthly/era5_single_levels_swvl1_monthly_0.5deg.nc", "referenced-data/monthly/era5_single_levels_swvl2_monthly_0.5deg.nc"],
            ["referenced-data/monthly/swvl1-2_1982_2022_monthly_0.5deg.nc"],
            "workflow/scripts/common/derive_swvl12.py",
            ["#action-derived-soil-water-swvl1-2-harmonize"],
            method="Thickness-weighted mean",
            formula="swvl1-2 = (swvl1 * 7 + swvl2 * 21) / 28",
            parameters=[
                {"@type": "PropertyValue", "name": "swvl1_layer_thickness", "value": 7, "unitText": "cm"},
                {"@type": "PropertyValue", "name": "swvl2_layer_thickness", "value": 21, "unitText": "cm"},
                {"@type": "PropertyValue", "name": "target_depth", "value": 28, "unitText": "cm"},
            ],
        ),
        preprocessing_step(
            "#prep-derived-subswc",
            "Derive subsurface soil moisture 7-100 cm",
            "Compute a thickness-weighted volumetric soil water content for the 7-100 cm layer from ERA5 soil water layers 2 and 3.",
            "derived-variable",
            ["referenced-data/monthly/era5_single_levels_swvl2_monthly_0.5deg.nc", "referenced-data/monthly/era5_single_levels_swvl3_monthly_0.5deg.nc"],
            ["referenced-data/monthly/subswc_1982_2022_monthly_0.5deg.nc"],
            "workflow/scripts/common/derive_products.py",
            ["#action-derived-soil-water-subswc-harmonize"],
            method="Thickness-weighted mean",
            formula="subswc = (swvl2 * 21 + swvl3 * 72) / 93",
            parameters=[
                {"@type": "PropertyValue", "name": "swvl2_layer_thickness", "value": 21, "unitText": "cm"},
                {"@type": "PropertyValue", "name": "swvl3_layer_thickness", "value": 72, "unitText": "cm"},
                {"@type": "PropertyValue", "name": "target_depth", "value": 93, "unitText": "cm"},
            ],
        ),
        preprocessing_step(
            "#prep-derived-vpd",
            "Derive vapour pressure deficit",
            "Compute vapour pressure deficit from ERA5 near-surface air temperature and dew point temperature.",
            "derived-variable",
            ["referenced-data/monthly/era5_single_levels_t2m_monthly_0.5deg.nc", "referenced-data/monthly/era5_single_levels_d2m_monthly_0.5deg.nc"],
            ["referenced-data/monthly/vpd_1982_2022_monthly_0.5deg.nc"],
            "workflow/scripts/common/derive_products.py",
            ["#action-derived-climate-vpd-harmonize"],
            method="Saturation vapour pressure difference",
            formula="vpd = max(es(t2m) - ea(d2m), 0)",
            parameters=[
                {"@type": "PropertyValue", "name": "vapour_pressure_scale", "value": 0.611, "unitText": "kPa"},
                {"@type": "PropertyValue", "name": "exponential_coefficient", "value": 17.5},
                {"@type": "PropertyValue", "name": "temperature_offset", "value": 240.978, "unitText": "degree Celsius"},
                {"@type": "PropertyValue", "name": "minimum_output", "value": 0, "unitText": "kPa"},
            ],
        ),
        preprocessing_step(
            "#prep-derived-wind",
            "Derive 10 m wind speed",
            "Compute 10 m scalar wind speed from ERA5 u10 and v10 wind components.",
            "derived-variable",
            ["referenced-data/monthly/era5_single_levels_u10_monthly_0.5deg.nc", "referenced-data/monthly/era5_single_levels_v10_monthly_0.5deg.nc"],
            ["referenced-data/monthly/wind_1982_2022_monthly_0.5deg.nc"],
            "workflow/scripts/common/derive_products.py",
            ["#action-derived-climate-wind-harmonize"],
            method="Euclidean vector magnitude",
            formula="wind = sqrt(u10**2 + v10**2)",
            parameters=[{"@type": "PropertyValue", "name": "norm", "value": "Euclidean L2"}],
        ),
        preprocessing_step(
            "#prep-lai-h5gz-to-monthly-netcdf",
            "Convert LAI H5.GZ composites to monthly NetCDF",
            "Convert THEIA GEOV2-GCM AVHRR 10-day H5.GZ LAI composites to monthly PROFECIA NetCDF on the 0.5 degree grid.",
            ["format-conversion", "masking", "temporal-aggregation"],
            ["provenance/referenced/lai-h5gz-source-directory"],
            ["referenced-data/monthly/lai_1982_2022_monthly_0.5deg.nc"],
            "workflow/scripts/common/process_lai.py",
            ["#action-local-lai-lai-harmonize"],
            method="Digital-number conversion, invalid-value masking, and monthly averaging",
            formula="LAI = DN / 30; valid DN in [0, 210]",
            parameters=[
                {"@type": "PropertyValue", "name": "scale_divisor", "value": 30},
                {"@type": "PropertyValue", "name": "valid_dn_min", "value": 0},
                {"@type": "PropertyValue", "name": "valid_dn_max", "value": 210},
                {"@type": "PropertyValue", "name": "input_frequency", "value": "10-day composite"},
                {"@type": "PropertyValue", "name": "output_frequency", "value": "monthly"},
                {"@type": "PropertyValue", "name": "aggregation_function", "value": "mean"},
            ],
            missing_data_policy="Digital numbers outside [0, 210] are masked before monthly aggregation.",
        ),
        preprocessing_step(
            "#prep-derived-co2-annual",
            "Derive annual CO2 product",
            "Build the annual PROFECIA CO2 product from CarbonTracker CT2022 level1 and NOAA GML global monthly CO2 inputs, following the canonical preprocessing.",
            "scientific-preprocessing",
            ["provenance/referenced/co2-ct2022-level1", "provenance/referenced/co2-noaa-gml-csv"],
            ["referenced-data/annual/co2_1982_2022_annual_0.5deg.nc"],
            "workflow/scripts/common/derive_co2_annual.py",
            ["#action-derived-human-co2-harmonize"],
            method="Canonical annual CO2 derivation/repackaging",
            rationale="Legacy preprocessing is authoritative for matching /srv/read_only_data/final_datasets.",
        ),
        preprocessing_step(
            "#prep-spei06-univariable-repackaging",
            "Repackage SPEI06 univariable product",
            "Repackage the SPEIbase v2.11 six-month SPEI product under the downstream univariable naming convention.",
            "derived-variable",
            ["referenced-data/monthly/speibase_v211_spei06_monthly_0.5deg.nc"],
            ["referenced-data/monthly/spei06_univariable_1982_2022_monthly_0.5deg.nc"],
            "workflow/scripts/common/derive_products.py",
            ["#action-derived-drought-index-spei06-harmonize"],
            method="Alias and NetCDF repackaging",
            formula="spei06_univariable = spei06",
            parameters=[{"@type": "PropertyValue", "name": "source_timescale", "value": 6, "unitText": "month"}],
        ),
        preprocessing_step(
            "#prep-hwsd2-static-to-monthly",
            "Expand HWSD2 static soil layers to monthly products",
            "Repackage canonical HWSD2-derived static soil layers and repeat them over the PROFECIA monthly time axis.",
            ["static-to-dynamic-expansion", "temporal-harmonization"],
            ["referenced-data/static/hwsd2_soil_0.5deg.nc"],
            soil_monthly_outputs,
            "workflow/scripts/common/repackage_local.py",
            [f"#action-local-hwsd2-monthly-{name}-harmonize" for name in ["ph", "bulk", "cec", "clay", "sand", "silt", "soc", "total-n"]],
            method="Static field repetition over monthly timestamps",
            parameters=[
                {"@type": "PropertyValue", "name": "start_year", "value": 1982},
                {"@type": "PropertyValue", "name": "end_year", "value": 2022},
                {"@type": "PropertyValue", "name": "output_frequency", "value": "monthly"},
            ],
            rationale="Monthly downstream interface requires static soil layers on the same temporal axis as climate drivers.",
        ),
    ]
    by_id = {str(entity.get("@id")): entity for entity in graph if entity.get("@id")}
    for step in steps:
        parameter_refs: list[dict[str, str]] = []
        for index, parameter in enumerate(as_list(step.get("profecia:parameter")), start=1):
            if not isinstance(parameter, dict):
                continue
            parameter_entity = dict(parameter)
            parameter_id = parameter_entity.get("@id") or f"{step['@id']}-parameter-{slug(str(parameter_entity.get('name') or index))}"
            parameter_entity["@id"] = parameter_id
            add_or_update_entity(graph, parameter_entity, seen)
            parameter_refs.append(ref(str(parameter_id)))
        if parameter_refs:
            step["profecia:parameter"] = parameter_refs
        add_or_update_entity(graph, step, seen)
        input_ids = ref_ids(step.get("profecia:input"))
        script_ids = ref_ids(step.get("profecia:implementedBy"))
        for action_id in ref_ids(step.get("profecia:relatedWorkflowAction")):
            action = by_id.get(action_id)
            if not action:
                continue
            add_refs(action, "object", input_ids + script_ids)
            add_refs(action, "prov:used", input_ids + script_ids)
            association = qualified_plan_association(action, step)
            add_or_update_entity(graph, association, seen)
            add_refs(action, "prov:qualifiedAssociation", [str(association["@id"])])
        for output_id in ref_ids(step.get("profecia:output")):
            output = by_id.get(output_id)
            if not output:
                continue
            add_refs(output, "profecia:wasPreprocessedBy", [str(step["@id"])])
            add_refs(output, "prov:wasDerivedFrom", input_ids)
            add_refs(output, "dcterms:source", input_ids)

def enrich_semantics(graph: list[dict[str, Any]], seen: set[str], release_id: str, release_id_map: dict[str, str]) -> None:
    add_vocabulary_entities(graph, seen)
    add_skos_step_types(graph, seen)
    add_research_area_entities(graph, seen)
    add_reliance_coverage_entities(graph, seen)
    for entity in graph:
        add_dcterms_and_dcat(entity)
    enhance_actions_and_outputs(graph)
    add_preprocessing_steps(graph, seen)
    add_distribution_links(graph)
    add_reliance_datacube_layer(graph, seen)
    for entity in graph:
        add_dcterms_and_dcat(entity)
    by_id = {str(entity.get("@id")): entity for entity in graph if entity.get("@id")}
    root = by_id.get("./")
    if root:
        add_type(root, "Dataset", "dcat:Dataset", "prov:Entity")
        add_refs(root, "dcterms:conformsTo", [RO_CRATE_PROFILE, WORKFLOW_RO_CRATE_PROFILE, PROCESS_RUN_PROFILE, WORKFLOW_RUN_PROFILE, PROFECIA_STEP_PROFILE])
        root["dcterms:author"] = ref("#person-fernando-aguilar-gomez")
        root["dcterms:creator"] = ref("#person-fernando-aguilar-gomez")
        root["dcterms:contributor"] = [ref("#org-ifca-csic"), ref("#org-csic")]
        root["dcterms:subject"] = ref(EUROVOC_EARTH_OBSERVATION)
        root["dcat:theme"] = ref(EUROVOC_EARTH_OBSERVATION)
        root["profecia:researchArea"] = ref(EUROVOC_EARTH_OBSERVATION)
        root["pav:createdBy"] = ref("#person-fernando-aguilar-gomez")
        root["pav:authoredBy"] = ref("#person-fernando-aguilar-gomez")
        root["pav:contributedBy"] = [ref("#org-ifca-csic"), ref("#org-csic")]
        root["pav:createdOn"] = root.get("dateCreated")
        root["pav:version"] = release_id
    metadata = by_id.get("ro-crate-metadata.json")
    if metadata:
        metadata["dcterms:author"] = ref("#person-fernando-aguilar-gomez")
        metadata["dcterms:creator"] = ref("#person-fernando-aguilar-gomez")
        metadata["dcterms:contributor"] = [ref("#org-ifca-csic"), ref("#org-csic")]
        metadata["pav:createdBy"] = ref("#person-fernando-aguilar-gomez")
        metadata["pav:authoredBy"] = ref("#person-fernando-aguilar-gomez")
        metadata["pav:contributedBy"] = [ref("#org-ifca-csic"), ref("#org-csic")]
        metadata["pav:createdOn"] = root.get("dateCreated") if root else datetime.now(timezone.utc).date().isoformat()
        metadata["pav:version"] = release_id


def is_external_ref(entity_id: str) -> bool:
    return entity_id.startswith(("http://", "https://", "mailto:", "urn:", "/"))


def validate_semantic_rocrate(crate: dict[str, Any]) -> dict[str, Any]:
    graph = crate.get("@graph", [])
    ids = {str(entity.get("@id")) for entity in graph if entity.get("@id")}
    warnings: list[str] = []
    errors: list[str] = []
    expected_prefixes = set(SEMANTIC_CONTEXT)
    context_maps = [item for item in as_list(crate.get("@context")) if isinstance(item, dict)]
    found_prefixes = set().union(*(item.keys() for item in context_maps)) if context_maps else set()
    missing_prefixes = sorted(expected_prefixes - found_prefixes)
    if missing_prefixes:
        errors.append(f"Missing semantic context prefixes: {', '.join(missing_prefixes)}")

    reference_keys = {
        "about", "agent", "conformsTo", "contactPoint", "contentLocation", "creator", "dcat:distribution", "dcat:theme",
        "dcterms:author", "dcterms:conformsTo", "dcterms:contributor", "dcterms:creator", "dcterms:isPartOf",
        "dcterms:license", "dcterms:source", "funder", "hasPart", "implementedBy",
        "inDefinedTermSet", "input", "instrument", "isPartOf", "license", "mainEntity", "maintainer", "mentions",
        "object", "output", "profecia:implementedBy", "profecia:input", "profecia:output",
        "profecia:parameter", "profecia:relatedWorkflowAction", "profecia:researchArea", "profecia:wasPreprocessedBy",
        "pav:authoredBy", "pav:contributedBy", "pav:createdBy", "prov:generated", "prov:hadPlan",
        "prov:used", "prov:wasAssociatedWith", "prov:wasDerivedFrom", "prov:wasGeneratedBy",
        "publisher", "reliance:dataquality", "reliance:processor", "reliance:spatialCoverage",
        "reliance:temporalCoverage", "result", "skos:inScheme", "variableMeasured", "workExample",
    }
    for entity in graph:
        entity_id = str(entity.get("@id", ""))
        for key, value in entity.items():
            if key not in reference_keys:
                continue
            for target in ref_ids(value):
                if target not in ids and not is_external_ref(target):
                    warnings.append(f"{entity_id} references missing @id {target} via {key}")

    for action in graph:
        if "CreateAction" not in as_list(action.get("@type")):
            continue
        if (action.get("object") or action.get("result")) and not action.get("prov:used") and not action.get("prov:generated"):
            warnings.append(f"CreateAction {action.get('@id')} has no prov:used/prov:generated")

    for entity in graph:
        if entity.get("isPartOf") == ref("#dataset-harmonized") or entity.get("dcterms:isPartOf") == ref("#dataset-harmonized"):
            for required in ["prov:Entity", "dcterms:format", "dcterms:isPartOf", "variableMeasured"]:
                if required == "prov:Entity":
                    if "prov:Entity" not in as_list(entity.get("@type")):
                        errors.append(f"Harmonized output {entity.get('@id')} lacks prov:Entity")
                elif required not in entity:
                    errors.append(f"Harmonized output {entity.get('@id')} lacks {required}")

    by_id = {str(entity.get("@id")): entity for entity in graph if entity.get("@id")}
    harmonized = by_id.get("#dataset-harmonized")
    if not harmonized:
        errors.append("Missing #dataset-harmonized")
    elif "DataCubeCollection" not in as_list(harmonized.get("@type")):
        errors.append("#dataset-harmonized lacks DataCubeCollection")
    else:
        for key in ["reliance:spatialCoverage", "reliance:temporalCoverage"]:
            if key not in harmonized:
                errors.append(f"#dataset-harmonized lacks {key}")

    coverage_requirements = {
        "#reliance-spatial-global-0p5deg": ["reliance:extent", "reliance:spatial-step-resolution", "reliance:coordinate-reference-system"],
        "#reliance-temporal-monthly-1982-2022": ["reliance:beginningTime", "reliance:endTime", "reliance:temporal-step-resolution", "reliance:temporal-reference-system-unit"],
        "#reliance-temporal-annual-1982-2022": ["reliance:beginningTime", "reliance:endTime", "reliance:temporal-step-resolution", "reliance:temporal-reference-system-unit"],
    }
    for coverage_id, required_keys in coverage_requirements.items():
        coverage = by_id.get(coverage_id)
        if not coverage:
            errors.append(f"Missing RELIANCE coverage entity {coverage_id}")
            continue
        for key in required_keys:
            if key not in coverage:
                errors.append(f"RELIANCE coverage entity {coverage_id} lacks {key}")

    temporal_datacubes = [
        entity
        for entity in graph
        if temporal_kind_for_release_path(str(entity.get("@id", ""))) is not None
        and (
            ref_id(entity.get("isPartOf")) == "#dataset-harmonized"
            or ref_id(entity.get("dcterms:isPartOf")) == "#dataset-harmonized"
        )
    ]
    for entity in temporal_datacubes:
        entity_id = entity.get("@id")
        if "DataCubeProduct" not in as_list(entity.get("@type")):
            errors.append(f"Temporal harmonized output {entity_id} lacks DataCubeProduct")
        for key in [
            "reliance:spatialCoverage",
            "reliance:temporalCoverage",
            "reliance:product-type",
            "reliance:data-type-unit",
            "reliance:processing-level",
            "reliance:processor",
            "reliance:dataquality",
        ]:
            if key not in entity:
                errors.append(f"Temporal DataCubeProduct {entity_id} lacks {key}")
    static_soil = by_id.get("referenced-data/static/hwsd2_soil_0.5deg.nc")
    if static_soil and "DataCubeProduct" in as_list(static_soil.get("@type")):
        errors.append("Static HWSD2 product must not be marked as DataCubeProduct")

    required_steps = [
        "#prep-derived-swvl1-2",
        "#prep-derived-subswc",
        "#prep-derived-vpd",
        "#prep-derived-wind",
        "#prep-lai-h5gz-to-monthly-netcdf",
        "#prep-derived-co2-annual",
        "#prep-spei06-univariable-repackaging",
        "#prep-hwsd2-static-to-monthly",
    ]
    for step_id in required_steps:
        step = next((entity for entity in graph if entity.get("@id") == step_id), None)
        if not step:
            errors.append(f"Missing preprocessing step {step_id}")
            continue
        for key in ["profecia:input", "profecia:output", "profecia:method", "profecia:implementedBy", "profecia:relatedWorkflowAction"]:
            if key not in step:
                errors.append(f"Preprocessing step {step_id} lacks {key}")

    swvl12 = next((entity for entity in graph if entity.get("@id") == "referenced-data/monthly/swvl1-2_1982_2022_monthly_0.5deg.nc"), None)
    if swvl12:
        sources = set(ref_ids(swvl12.get("prov:wasDerivedFrom")))
        for source_id in ["referenced-data/monthly/era5_single_levels_swvl1_monthly_0.5deg.nc", "referenced-data/monthly/era5_single_levels_swvl2_monthly_0.5deg.nc"]:
            if source_id not in sources:
                errors.append(f"swvl1-2 missing prov:wasDerivedFrom {source_id}")
        if "#prep-derived-swvl1-2" not in ref_ids(swvl12.get("profecia:wasPreprocessedBy")):
            errors.append("swvl1-2 missing profecia:wasPreprocessedBy #prep-derived-swvl1-2")
    else:
        errors.append("Missing swvl1-2 output entity")

    return {
        "status": "OK" if not errors else "ERROR",
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "summary": {
            "entities": len(graph),
            "create_actions": sum(1 for entity in graph if "CreateAction" in as_list(entity.get("@type"))),
            "datacube_products": len(temporal_datacubes),
            "preprocessing_steps": sum(1 for entity in graph if "profecia:PreprocessingStep" in as_list(entity.get("@type"))),
        },
    }


def provenance_entity_id(item: dict[str, Any]) -> str:
    # A contextual reference must not promise a nonexistent payload-relative file.
    return f"#provenance-reference-{slug(item.get('id') or item.get('path') or 'input')}"


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
    parser.add_argument("--run-metadata", type=Path, help="Optional captured runtime metadata JSON; defaults to BASE_DIR/metadata/workflow-run.json when present.")
    args = parser.parse_args()

    config_path = args.config.resolve()
    workflow_dir = args.workflow_dir.resolve()
    project_root = args.project_root.resolve()
    config_dir = config_path.parent
    requirements_path = project_root / "workflows" / "data_foundation" / "requirements.txt"
    if not requirements_path.exists():
        requirements_path = project_root / "requirements.txt"
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
    run_metadata_path = args.run_metadata.resolve() if args.run_metadata else base_dir / "metadata" / "workflow-run.json"

    manifest = read_json(manifest_path)
    checksums = parse_checksums(checksums_path)
    git_data, git_warnings = git_metadata(project_root)
    today = datetime.now(timezone.utc).date().isoformat()
    root_dates = {"dateCreated": today, "datePublished": today}
    existing_metadata = output_dir / "ro-crate-metadata.json"
    if existing_metadata.exists():
        try:
            existing_graph = read_json(existing_metadata).get("@graph", [])
            existing_root = next(entity for entity in existing_graph if entity.get("@id") == "./")
            for key in root_dates:
                if existing_root.get(key):
                    root_dates[key] = existing_root[key]
        except (OSError, ValueError, StopIteration, AttributeError):
            pass

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
    preview_path = output_dir / "ro-crate-preview.html"

    graph: list[dict[str, Any]] = []
    seen: set[str] = set()
    has_part: list[dict[str, str]] = []
    release_id_map: dict[str, str] = {}
    packaged_auxiliary_parts: list[dict[str, str]] = []

    # Explicit, non-secret reproduction assets (portable config, input snapshots,
    # environment lock and tester guide) are part of the research object.
    for asset in config.get("reproduction_assets", []):
        source = Path(asset["path"]).resolve()
        destination = Path(asset["destination"])
        if destination.is_absolute() or ".." in destination.parts:
            raise ValueError("Reproduction asset destination must be crate-relative")
        if not source.exists():
            raise FileNotFoundError(source)
        files = sorted(source.rglob("*")) if source.is_dir() else [source]
        for path in files:
            if not path.is_file():
                continue
            relative = destination / path.relative_to(source) if source.is_dir() else destination
            if not is_safe_config_reference(path):
                raise ValueError(f"Unsafe reproduction asset: {path.name}")
            target = output_dir / relative
            if target.exists():
                raise ValueError(f"Duplicate reproduction asset: {relative}")
            copied = copy_into_crate(path, output_dir, relative)
            add_entity(graph, file_entity(copied, output_dir, output_dir, {}, entity_id=relative.as_posix(),
                name=relative.as_posix(), extra={"sha256": sha256_file(copied),
                "description": "Explicit reproduction asset; external input terms remain applicable."}), seen)
            has_part.append(ref(relative.as_posix()))

    for profile_id, name, version in [
        (RO_CRATE_PROFILE, "RO-Crate", "1.1"),
        (WORKFLOW_RO_CRATE_PROFILE, "Workflow RO-Crate", "1.0"),
        (PROCESS_RUN_PROFILE, "Process Run Crate", "0.5"),
        (WORKFLOW_RUN_PROFILE, "Workflow Run Crate", "0.5"),
        (SNAKEMAKE_LANGUAGE, "Snakemake", ""),
        (BIOSCHEMAS_FORMAL_PARAMETER, "Bioschemas FormalParameter", "1.0-RELEASE"),
        (BIOSCHEMAS_COMPUTATIONAL_WORKFLOW, "Bioschemas ComputationalWorkflow", "1.0-RELEASE"),
        (METADATA_LICENSE, "CC0 1.0 Universal", ""),
        (DATA_LICENSE, "Creative Commons Attribution 4.0 International", ""),
        (CODE_LICENSE, "Apache License 2.0", ""),
    ]:
        entity_types: str | list[str] = ["ComputerLanguage", "CreativeWork"] if profile_id == SNAKEMAKE_LANGUAGE else "CreativeWork"
        entity: dict[str, Any] = {"@id": profile_id, "@type": entity_types, "name": name}
        if version:
            entity["version"] = version
        add_entity(graph, entity, seen)

    add_entity(graph, {"@id": "#person-fernando-aguilar-gomez", "@type": ["Person", "prov:Person"], "name": "Fernando Aguilar Gomez", "identifier": "https://orcid.org/0000-0001-9462-4831", "affiliation": ref("#org-ifca-csic")}, seen)
    add_entity(graph, {"@id": "#org-csic", "@type": ["Organization", "prov:Organization"], "name": "Spanish National Research Council (CSIC)", "alternateName": "CSIC", "url": "https://www.csic.es/"}, seen)
    add_entity(graph, {"@id": "#org-ifca-csic", "@type": ["Organization", "prov:Organization"], "name": "Instituto de Fisica de Cantabria", "alternateName": "IFCA-CSIC", "url": "https://ifca.unican.es/", "parentOrganization": ref("#org-csic")}, seen)
    add_entity(graph, {"@id": "https://ror.org/02gfc7t72", "@type": ["Organization", "prov:Organization"], "name": "Spanish National Research Council", "alternateName": "CSIC", "url": "https://www.csic.es/"}, seen)
    add_entity(graph, {"@id": "https://ror.org/014w0fd65", "@type": ["Organization", "prov:Organization"], "name": "European Centre for Medium-Range Weather Forecasts", "alternateName": "ECMWF", "url": "https://www.ecmwf.int/"}, seen)
    add_entity(graph, {"@id": "https://ror.org/00pe0tf51", "@type": ["Organization", "prov:Organization"], "name": "Food and Agriculture Organization of the United Nations", "alternateName": "FAO", "url": "https://www.fao.org/"}, seen)
    add_entity(graph, {"@id": "https://ror.org/02z5nhe81", "@type": ["Organization", "prov:Organization"], "name": "National Oceanic and Atmospheric Administration", "alternateName": "NOAA", "url": "https://www.noaa.gov/"}, seen)
    add_entity(graph, {"@id": "#org-copernicus-climate-change-service", "@type": ["Organization", "prov:Organization"], "name": "Copernicus Climate Change Service", "alternateName": "C3S", "url": "https://climate.copernicus.eu/"}, seen)
    add_entity(graph, {"@id": "#org-pangaea", "@type": ["Organization", "prov:Organization"], "name": "PANGAEA Data Publisher for Earth & Environmental Science", "url": "https://www.pangaea.de/"}, seen)
    add_entity(graph, {"@id": "#org-figshare-zenodo", "@type": ["Organization", "prov:Organization"], "name": "Figshare and Zenodo source repositories", "description": "Composite provider node retained because the configured Human Footprint product combines records from both repositories.", "url": ["https://figshare.com/", "https://zenodo.org/"]}, seen)
    add_entity(graph, {"@id": "#grant-pid2023-152114ob-i00", "@type": "Grant", "name": "PID2023-152114OB-I00", "identifier": "PID2023-152114OB-I00", "funder": ref("#org-csic")}, seen)
    add_entity(graph, {"@id": "#workflow-snakemake", "@type": ["SoftwareApplication", "prov:SoftwareAgent"], "name": "Snakemake workflow runner", "url": "https://snakemake.github.io/", "profecia:recordingStatus": "version used for the historical scientific run was not recorded"}, seen)

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

    release_paths = sorted(path for path in release_file_paths(base_dir, manifest) if path.exists() and path.is_file())
    for path in release_paths:
        rel_to_base = path.relative_to(base_dir).as_posix()
        crate_relative = canonical_crate_path(path, base_dir=base_dir, workflow_dir=workflow_dir, config_dir=config_dir)
        should_copy = should_copy_release_file(rel_to_base, config)
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

    for path in allowlisted_project_files(project_root, base_dir, copy_allowlist_patterns(config)):
        relative_to_project = Path(posix_rel(path, project_root))
        crate_relative = relative_to_project
        copied = copy_into_crate(path, output_dir, crate_relative)
        entity_id = crate_relative.as_posix()
        relative_key = relative_to_project.as_posix()
        entity = file_entity(
            copied,
            output_dir,
            output_dir,
            {},
            entity_id=entity_id,
            name=path.name,
            types=["File"],
            description="Offline or auxiliary input copied into the RO-Crate by ro_crate_packaging.copy_allowlist.",
            extra={
                "isPartOf": ref("#dataset-packaged-auxiliary"),
                "sha256": sha256_file(path),
                "contentUrl": relative_key,
            },
        )
        add_entity(graph, entity, seen)
        packaged_auxiliary_parts.append(ref(entity_id))
        has_part.append(ref(entity_id))

    workflow_parts = []
    for workflow_path in workflow_files(workflow_dir):
        if not workflow_path.exists():
            continue
        types = ["File", "SoftwareSourceCode"]
        extra: dict[str, Any] = {"license": ref(CODE_LICENSE), "sha256": sha256_file(workflow_path)}
        if workflow_path.name == "Snakefile":
            types.append("ComputationalWorkflow")
            extra.update(
                {
                    "name": "PROFECIA Data Foundation Snakemake workflow",
                    "description": "Workflow used to build requests, acquire or register source data, inspect raw files, harmonize NetCDF products, validate outputs, and write FAIR release metadata.",
                    "programmingLanguage": ref(SNAKEMAKE_LANGUAGE),
                    "conformsTo": ref(BIOSCHEMAS_COMPUTATIONAL_WORKFLOW),
                    "author": ref("#person-fernando-aguilar-gomez"),
                    "maintainer": ref("#person-fernando-aguilar-gomez"),
                    "input": [ref("#configfile")],
                    "output": [ref("#harmonized-release"), ref("#release-metadata")],
                    "documentation": [ref("README.md")],
                    "runtimePlatform": "Snakemake; the exact engine version for the described historical scientific run was not recorded.",
                    "softwareRequirements": [ref("requirements.txt"), ref("#reproduction-environment-template")],
                }
            )
            if git_data.get("repository_url"):
                extra["codeRepository"] = git_data["repository_url"]
            if git_data.get("software_version"):
                extra["version"] = git_data["software_version"]
            if git_data.get("commit"):
                commit_property = "profecia:baseGitCommit" if git_data.get("dirty") else "profecia:gitCommit"
                extra[commit_property] = git_data["commit"]
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
        copied_config = copy_config_into_crate(safe_config, output_dir, crate_relative)
        entity_id = crate_relative.as_posix()
        entity = file_entity(
            copied_config,
            output_dir,
            output_dir,
            {},
            entity_id=entity_id,
            name="Snakemake config file used for this release" if safe_config == config_path else f"Safe configuration template/example: {safe_config.name}",
            types=["File"],
            extra={"license": ref(CODE_LICENSE), "sha256": sha256_file(copied_config)},
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
        entity = file_entity(requirements_path, output_dir, project_root, {}, entity_id="requirements.txt", name="Python requirements for the PROFECIA data-foundation workflow", types=["File", "SoftwareSourceCode"], extra={"license": ref(CODE_LICENSE), "sha256": sha256_file(requirements_path)})
        add_entity(graph, entity, seen)
        has_part.append(ref("requirements.txt"))

    for asset in semantic_asset_files(project_root):
        metadata_root = project_root / "workflows" / "data_foundation" / "metadata"
        if not metadata_root.exists():
            metadata_root = project_root / "metadata"
        relative = asset.relative_to(metadata_root)
        crate_relative = Path("metadata") / relative
        copied = copy_into_crate(asset, output_dir, crate_relative)
        entity_id = crate_relative.as_posix()
        entity = file_entity(copied, output_dir, output_dir, {}, entity_id=entity_id, name=asset.name, types=["File", "CreativeWork"], description="PROFECIA vocabulary, SKOS, SHACL, or human-readable semantic documentation.", extra={"license": ref(METADATA_LICENSE)})
        add_entity(graph, entity, seen)
        has_part.append(ref(entity_id))

    provenance_id_map: dict[str, str] = {}
    provenance_parts: list[dict[str, str]] = []
    used_provenance_paths: set[str] = set()
    effective_input_map = {}
    for asset in config.get("reproduction_assets", []):
        mapping_path = Path(asset["path"]) / "input-map.json"
        if mapping_path.exists():
            effective_input_map.update(read_json(mapping_path))
    for item in manifest.get("provenance_inputs", []) or []:
        configured_source_path = Path(str(item.get("path", "")))
        source_path = configured_source_path if configured_source_path.is_absolute() else (project_root / configured_source_path)
        copy_policy = str(item.get("copy_policy", "reference")).lower()
        exists = source_path.exists()
        extra = {
            "contentUrl": str(source_path),
            "identifier": str(item.get("id") or configured_source_path),
            "profecia:resolutionMethod": f"Resolve according to manifest copy policy: {copy_policy}.",
            "usageInfo": item.get("license_or_terms") or "Governed by original provider terms.",
            "isPartOf": ref("#dataset-provenance-inputs"),
            "additionalType": item.get("role"),
            "profecia:usedByProductKey": item.get("used_by", []),
        }
        if item.get("sha256"):
            extra["sha256"] = item["sha256"]
        if item.get("size_bytes") is not None:
            extra["contentSize"] = str(item["size_bytes"])
        workflow_entity_id = workflow_relative_entity_id(source_path, workflow_dir)
        if workflow_entity_id:
            entity_id = workflow_entity_id
            workflow_extra = {**extra, "contentUrl": configured_source_path.as_posix()}
            entity = file_entity(
                source_path,
                output_dir,
                project_root,
                {},
                entity_id=entity_id,
                name=str(item.get("id") or source_path.name),
                types=["File", "SoftwareSourceCode"],
                description=item.get("description") or f"Workflow-bundled legacy provenance script ({item.get('role')}).",
                extra=workflow_extra,
            )
            add_or_update_entity(graph, entity, seen)
        elif str(configured_source_path) in effective_input_map:
            entity_id = effective_input_map[str(configured_source_path)]
            packaged = output_dir / entity_id
            extra["contentUrl"] = entity_id
            extra["profecia:resolutionMethod"] = "Effective input snapshot included in the reproduction payload."
            if packaged.is_dir():
                entity_id = entity_id.rstrip("/") + "/"
                entity = {"@id": entity_id, "@type": "Dataset", "name": str(item.get("id")), **extra,
                          "hasPart": refs([entry["@id"] for entry in graph if entry["@id"].startswith(entity_id)])}
            else:
                entity = file_entity(packaged, output_dir, output_dir, {}, entity_id=entity_id,
                                     name=str(item.get("id")), extra=extra)
            add_or_update_entity(graph, entity, seen)
        elif copy_policy == "copy" and exists and source_path.is_file():
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
            add_entity(graph, entity, seen)
        else:
            entity_id = provenance_entity_id(item)
            entity = {
                "@id": entity_id,
                "@type": ["Dataset"] if source_path.is_dir() else ["File"],
                "name": str(item.get("id") or source_path.name),
                "description": item.get("description") or f"Referenced provenance input ({item.get('role')}); not copied into the RO-Crate archive.",
                **extra,
            }
            if not source_path.is_dir():
                entity["encodingFormat"] = encoding_format(source_path)
            add_entity(graph, entity, seen)
        provenance_id_map[str(item.get("id"))] = entity_id
        provenance_parts.append(ref(entity_id))
        has_part.append(ref(entity_id))

    write_readme(readme_path, release_id, archive_path, complete=bool(config.get("reproduction_assets")))
    add_entity(graph, file_entity(readme_path, output_dir, output_dir, {}, entity_id="README.md", name="RO-Crate and ROHub publication notes", types=["File", "CreativeWork"], extra={"about": ref("./"), "license": ref(METADATA_LICENSE)}), seen)
    has_part.append(ref("README.md"))
    write_citation(citation_path, release_id)
    add_entity(graph, file_entity(citation_path, output_dir, output_dir, {}, entity_id="CITATION.cff", name="Citation metadata", types=["File", "CreativeWork"], extra={"license": ref(METADATA_LICENSE)}), seen)
    has_part.append(ref("CITATION.cff"))
    write_preview(preview_path, release_id)
    add_entity(graph, file_entity(preview_path, output_dir, output_dir, {}, entity_id="ro-crate-preview.html", name="RO-Crate HTML preview", types=["File", "CreativeWork"], extra={"about": ref("./"), "license": ref(METADATA_LICENSE)}), seen)
    has_part.append(ref("ro-crate-preview.html"))

    for item in manifest.get("selected_variables", []):
        variable_id = f"#variable-{slug(item['source'])}-{slug(item['variable'])}"
        unit_text = item.get("source_units")
        variable_entity: dict[str, Any] = {
            "@id": variable_id,
            "@type": "PropertyValue",
            "name": item.get("long_name") or item["variable"],
            "propertyID": item["variable"],
            "description": f"Scientific variable {item['source']}/{item['variable']} ({item.get('role') or 'variable'}); distinct from files and measured values.",
            "provider": provider_ref(str(item["source"])),
        }
        if unit_text:
            variable_entity["unitText"] = unit_text
            if unit_text in UNIT_IRIS:
                variable_entity["unitCode"] = ref(UNIT_IRIS[unit_text])
            else:
                variable_entity["profecia:unitStatus"] = "Unit retained verbatim from the source configuration because no verified QUDT mapping is declared."
        else:
            variable_entity["profecia:unitStatus"] = "Unit not recorded in the source configuration; no unit is invented."
        if item.get("derived"):
            derivation = item.get("derivation") or {}
            details = [value for value in [derivation.get("description"), derivation.get("weights")] if value]
            if details:
                variable_entity["description"] += "; " + " | ".join(details)
            if derivation.get("formula"):
                variable_entity["mathExpression"] = derivation["formula"]
            if derivation.get("notebook_reference"):
                variable_entity["isBasedOn"] = derivation["notebook_reference"]
        add_entity(graph, variable_entity, seen)

    configured_sources = manifest.get("configured_sources") or {}
    for source_id, source in sorted(configured_sources.items()):
        sid = f"#source-{slug(source_id)}"
        landing_page, access_url = source_urls(source)
        source_providers = [provider_ref(source_id)]
        if source_id == "era5_single_levels":
            source_providers.append(ref("#org-copernicus-climate-change-service"))
        entity: dict[str, Any] = {
            "@id": sid,
            "@type": ["Dataset", "dcat:Dataset", "prov:Entity"],
            "name": source.get("source_family") or source_id,
            "provider": source_providers if len(source_providers) > 1 else source_providers[0],
            "description": f"External source dataset used as provenance input. Access method: {source.get('access_protocol') or source.get('access_mode') or 'unspecified'}.",
            "usageInfo": source.get("terms") or "Governed by original provider terms.",
            "conditionsOfAccess": "Authentication required." if source.get("requires_authentication") else "No authentication declared by the release configuration.",
            "variableMeasured": [ref(f"#variable-{slug(source_id)}-{slug(variable)}") for variable in source.get("variables", [])],
        }
        if source.get("dataset"):
            entity["identifier"] = source["dataset"]
        if source.get("version"):
            entity["version"] = source["version"]
        if source.get("doi"):
            entity["identifier"] = f"https://doi.org/{source['doi']}"
        if landing_page:
            entity["dcat:landingPage"] = ref(landing_page)
        if access_url:
            entity["dcat:accessURL"] = ref(access_url)
        add_entity(graph, entity, seen)

    add_entity(graph, {"@id": "#dataset-harmonized", "@type": "Dataset", "name": "Harmonized PROFECIA NetCDF products", "description": "Official derived data products for this release.", "license": ref(DATA_LICENSE), "hasPart": [ref(release_id_map[path]) for path in manifest.get("harmonized_files", []) if path in release_id_map]}, seen)
    add_entity(graph, {"@id": "#dataset-raw-provenance", "@type": "Dataset", "name": "Raw/source provenance inputs", "description": "Raw or source artifacts used to generate harmonized products. These are provenance inputs, not primary release distributions.", "usageInfo": "External source data remain governed by original provider terms.", "hasPart": [ref(release_id_map[path]) for path in manifest.get("raw_source_files", []) if path in release_id_map]}, seen)
    add_entity(graph, {"@id": "#dataset-provenance-inputs", "@type": "Dataset", "name": "Original scripts and critical external provenance inputs", "description": "Legacy scripts, canonical references, target grids and large raw inputs needed to reproduce the canonical /srv/read_only_data products. Large inputs may be referenced rather than copied.", "usageInfo": "Copy policy is recorded in manifest.json; referenced inputs are not redistributed in the RO-Crate archive.", "hasPart": provenance_parts}, seen)
    if packaged_auxiliary_parts:
        add_entity(graph, {"@id": "#dataset-packaged-auxiliary", "@type": "Dataset", "name": "Packaged offline and auxiliary inputs", "description": "Offline and auxiliary data inputs copied into the RO-Crate by explicit packaging allowlist.", "hasPart": packaged_auxiliary_parts}, seen)
    add_entity(graph, {"@id": "#dataset-validation-reports", "@type": "Dataset", "name": "Validation reports", "description": "Raw inspection, harmonized validation and release validation reports.", "hasPart": [ref(release_id_map[path]) for path in manifest.get("validation_reports", []) if path in release_id_map]}, seen)
    has_part.extend([ref("#dataset-harmonized"), ref("#dataset-raw-provenance"), ref("#dataset-provenance-inputs"), ref("#dataset-validation-reports")])
    if packaged_auxiliary_parts:
        has_part.append(ref("#dataset-packaged-auxiliary"))

    release_metadata_ids = [
        release_id_map[value]
        for value in ["manifest.json", "checksums.sha256", "fair/harmonized_netcdf_demo.croissant.jsonld", "validation/release_validation.json", "validation/harmonized_validation.json"]
        if value in release_id_map
    ]
    add_entity(graph, {"@id": "#dataset-release-metadata", "@type": "Dataset", "name": "Release metadata and validation artifacts", "description": "Concrete metadata outputs of the workflow run.", "hasPart": refs(release_metadata_ids)}, seen)
    has_part.append(ref("#dataset-release-metadata"))

    formal_parameters = [
        {"@id": "#configfile", "@type": "FormalParameter", "additionalType": "File", "conformsTo": ref(BIOSCHEMAS_FORMAL_PARAMETER), "name": "configfile", "description": "YAML configuration supplied to the Snakemake workflow for this release.", "valueRequired": True, "workExample": run_config_object},
        {"@id": "#harmonized-release", "@type": "FormalParameter", "additionalType": "Dataset", "conformsTo": ref(BIOSCHEMAS_FORMAL_PARAMETER), "name": "harmonized_release", "description": "Collection of harmonized NetCDF products emitted by the workflow.", "valueRequired": True, "workExample": ref("#dataset-harmonized")},
        {"@id": "#release-metadata", "@type": "FormalParameter", "additionalType": "Dataset", "conformsTo": ref(BIOSCHEMAS_FORMAL_PARAMETER), "name": "release_metadata", "description": "Manifest, checksums, validation reports, and FAIR descriptors emitted by the workflow.", "valueRequired": True, "workExample": ref("#dataset-release-metadata")},
    ]
    for entity in formal_parameters:
        add_entity(graph, entity, seen)
    by_id = {str(entity.get("@id")): entity for entity in graph if entity.get("@id")}
    concrete_config = by_id.get(ref_id(run_config_object))
    if concrete_config:
        concrete_config["exampleOfWork"] = ref("#configfile")
    by_id["#dataset-harmonized"]["exampleOfWork"] = ref("#harmonized-release")
    by_id["#dataset-release-metadata"]["exampleOfWork"] = ref("#release-metadata")

    add_entity(graph, {
        "@id": "#reproduction-environment-template",
        "@type": "CreativeWork",
        "name": "Reproduction environment template",
        "description": "Requirements and Conda environment specifications packaged for reproduction; these are not asserted to be the exact historical execution environment.",
        "hasPart": [ref("requirements.txt"), ref("workflow/envs/xarray.yml"), ref("workflow/envs/cdsapi.yml")],
        "profecia:recordingStatus": "template-not-recorded-environment",
    }, seen)

    action_id = f"#run-{slug(release_id)}"
    run_action: dict[str, Any] = {
        "@id": action_id,
        "@type": "CreateAction",
        "identifier": action_id,
        "name": f"Run PROFECIA data-foundation workflow for {release_id}",
        "description": "Global orchestration run reconstructed from materialized artifacts; historical start/end times and the effective software environment were not recorded.",
        "instrument": ref("workflow/Snakefile"),
        "object": [run_config_object] + provenance_parts,
        "result": ref("#dataset-harmonized"),
        "agent": ref("#person-fernando-aguilar-gomez"),
        "actionStatus": "http://schema.org/CompletedActionStatus",
        "profecia:recordingStatus": "completed-artifacts-times-unknown",
        "environment": ref("#run-environment-not-recorded"),
    }
    run_environment = {
        "@id": "#run-environment-not-recorded",
        "@type": "PropertyValue",
        "name": "effective execution environment",
        "description": "The exact Snakemake, Python, Conda, platform, and container versions used for the historical scientific run were not captured. See the reproduction environment template for a prospective environment.",
        "value": "not recorded",
        "profecia:recordingStatus": "not-recorded",
    }
    apply_run_metadata(run_action, run_environment, run_metadata_path)
    if run_metadata_path.exists():
        observed = read_json(run_metadata_path)
        engine = next(entity for entity in graph if entity.get("@id") == "#workflow-snakemake")
        if observed.get("snakemake_version"):
            engine["softwareVersion"] = observed["snakemake_version"]
            engine["profecia:recordingStatus"] = "captured-current-execution"
    add_entity(graph, run_action, seen)
    add_entity(graph, run_environment, seen)
    runtime_provenance = config.get("runtime_provenance") or {}
    if runtime_provenance.get("enabled", False):
        execution_crate = Path(runtime_provenance["archive"]).resolve()
        if not execution_crate.is_file():
            raise FileNotFoundError(execution_crate)
        execution_id = "provenance/workflow-run-ro-crate.zip"
        copied_execution = copy_into_crate(execution_crate, output_dir, Path(execution_id))
        add_entity(graph, file_entity(copied_execution, output_dir, output_dir, {},
            entity_id=execution_id, name="Captured Snakemake execution provenance",
            extra={"about": ref(action_id), "sha256": sha256_file(copied_execution),
                   "description": "Separate experimental Provenance Run Crate; persisted jobs may originate from earlier invocations."}), seen)
        add_refs(run_action, "subjectOf", [execution_id])
        has_part.append(ref(execution_id))
    if run_metadata_path.exists():
        copied_run_metadata = copy_into_crate(run_metadata_path, output_dir, Path("metadata/workflow-run.json"))
        add_entity(graph, file_entity(copied_run_metadata, output_dir, output_dir, {}, entity_id="metadata/workflow-run.json", name="Captured workflow runtime metadata", types=["File", "CreativeWork"], extra={"about": ref(action_id), "license": ref(METADATA_LICENSE)}), seen)
        has_part.append(ref("metadata/workflow-run.json"))
        for log_name in ("execution.log", "preflight.log"):
            log_path = base_dir / "metadata" / log_name
            if log_path.is_file():
                log_id = f"metadata/{log_name}"
                copied_log = copy_into_crate(log_path, output_dir, Path(log_id))
                add_entity(graph, file_entity(copied_log, output_dir, output_dir, {},
                           entity_id=log_id, name=f"Observed execution {log_name}",
                           extra={"about": ref(action_id), "sha256": sha256_file(copied_log)}), seen)
                has_part.append(ref(log_id))
        if runtime_provenance.get("enabled", False):
            add_refs(run_action, "subjectOf", [execution_id])


    generated_raw: set[str] = set()
    generated_inspections: set[str] = set()
    generated_harmonized: set[str] = set()
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
        source_dataset_id = f"#source-{source}"
        prefix = f"#action-{source}-{variable}"
        if request_id:
            add_entity(graph, make_action(f"{prefix}-build-request", f"Build request for {item['source']}/{item['variable']}", "workflow/rules/acquire.smk", [ref_id(run_config_object) or ""], [request_id], "Create source request metadata."), seen)
        new_raw_ids = [raw_id for raw_id in raw_ids if raw_id not in generated_raw]
        if new_raw_ids:
            add_entity(graph, make_action(f"{prefix}-acquire-source", f"Download or register source data for {item['source']}/{item['variable']}", "workflow/rules/acquire.smk", [value for value in [request_id, source_dataset_id] if value] + provenance_ids, new_raw_ids, "Acquire, download, or register source/raw provenance inputs."), seen)
            generated_raw.update(new_raw_ids)
        if inspection_id and inspection_id not in generated_inspections:
            add_entity(graph, make_action(f"{prefix}-inspect-raw", f"Inspect raw NetCDF for {item['source']}/{item['variable']}", "workflow/rules/inspect.smk", raw_ids, [inspection_id], "Inspect source/raw NetCDF structure and basic metadata."), seen)
            generated_inspections.add(inspection_id)
        new_harmonized_ids = [output_id for output_id in harmonized_ids if output_id not in generated_harmonized]
        if new_harmonized_ids:
            harmonize_action_id = "#action-hwsd2-static-harmonize" if item["source"] == "hwsd2" else f"{prefix}-harmonize"
            harmonize_name = "Generate the multi-variable HWSD2 static product" if item["source"] == "hwsd2" else f"Harmonize product for {item['source']}/{item['variable']}"
            add_entity(graph, make_action(harmonize_action_id, harmonize_name, "workflow/rules/harmonize.smk", raw_ids + provenance_ids + ([inspection_id] if inspection_id else []), new_harmonized_ids, "Transform source data to PROFECIA target conventions."), seen)
            generated_harmonized.update(new_harmonized_ids)

    hval_id = release_id_map.get("validation/harmonized_validation.json")
    if hval_id:
        harmonized_ids = [release_id_map[path] for path in manifest.get("harmonized_files", []) if path in release_id_map]
        add_entity(graph, make_action(f"#action-validate-harmonized-{slug(release_id)}", "Validate all harmonized NetCDF products", "workflow/rules/validate.smk", harmonized_ids, [hval_id], "Run aggregate grid, coordinate, variable, and finite-value checks once over the complete harmonized collection."), seen)

    if "manifest.json" in release_id_map:
        add_entity(graph, make_action(f"#action-write-manifest-{slug(release_id)}", "Write release manifest", "workflow/rules/metadata.smk", ["workflow/Snakefile"], [release_id_map["manifest.json"]], "Write machine-readable release manifest."), seen)
    if "fair/harmonized_netcdf_demo.croissant.jsonld" in release_id_map:
        croissant_inputs = [release_id_map[path] for path in manifest.get("harmonized_files", []) if path in release_id_map]
        add_entity(graph, make_action(f"#action-write-croissant-{slug(release_id)}", "Write Croissant descriptor", "workflow/rules/metadata.smk", croissant_inputs, [release_id_map["fair/harmonized_netcdf_demo.croissant.jsonld"]], "Write ML discovery metadata for harmonized products."), seen)
    if "checksums.sha256" in release_id_map:
        add_entity(graph, make_action(f"#action-write-checksums-{slug(release_id)}", "Write checksums", "workflow/rules/metadata.smk", sorted(value for value in release_id_map.values() if value != release_id_map["checksums.sha256"]), [release_id_map["checksums.sha256"]], "Write SHA256 checksums for data, validation and metadata artifacts."), seen)
    if "validation/release_validation.json" in release_id_map:
        add_entity(graph, make_action(f"#action-validate-release-{slug(release_id)}", "Validate release package", "workflow/rules/validate.smk", [release_id_map.get("manifest.json", "manifest.json"), release_id_map.get("checksums.sha256", "checksums.sha256")], [release_id_map["validation/release_validation.json"]], "Validate release-level requirements."), seen)
    add_entity(graph, make_action(
        f"#action-write-ro-crate-{slug(release_id)}",
        "Write PROFECIA RO-Crate",
        "workflow/scripts/common/ro_crate_writer.py",
        [value for value in [release_id_map.get("manifest.json"), release_id_map.get("checksums.sha256"), release_id_map.get("fair/harmonized_netcdf_demo.croissant.jsonld")] if value],
        ["ro-crate-metadata.json", "ro-crate-preview.html", "README.md", "CITATION.cff"],
        "Generate the RO-Crate descriptor, publication notes, and citation metadata.",
    ), seen)

    root_dataset = {
        "@id": "./",
        "@type": "Dataset",
        "name": f"PROFECIA Data Foundation Release {release_id}",
        "description": "PROFECIA data-foundation release generated by a Snakemake workflow. Harmonized NetCDF files are the main scientific data products; raw/source data are provenance inputs used to regenerate them. Consult the reproduction protocol for verified scope and acceptance criteria.",
        "identifier": release_id,
        "version": release_id,
        "dateCreated": root_dates["dateCreated"],
        "datePublished": root_dates["datePublished"],
        "author": ref("#person-fernando-aguilar-gomez"),
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
        "spatialCoverage": ref("#reliance-spatial-global-0p5deg"),
    }
    if git_data.get("commit"):
        commit_property = "profecia:baseGitCommit" if git_data.get("dirty") else "profecia:gitCommit"
        root_dataset[commit_property] = git_data["commit"]
    warnings = list(manifest.get("warnings") or []) + git_warnings
    if warnings:
        root_dataset["conditionsOfAccess"] = "Warnings: " + " | ".join(sorted(set(warnings)))
    graph.insert(1, root_dataset)

    crate = {"@context": [*RO_CRATE_CONTEXT, SEMANTIC_CONTEXT], "@graph": graph}
    enrich_semantics(graph, seen, release_id, release_id_map)

    # Legacy scientific descriptions use the historical reference identifier.
    # Resolve those links to the actual contextual or included input entity.
    provenance_aliases = {f"provenance/referenced/{slug(key)}": value
                          for key, value in provenance_id_map.items()}
    def resolve_provenance_links(value):
        if isinstance(value, dict):
            if "@id" in value and value["@id"] in provenance_aliases:
                value["@id"] = provenance_aliases[value["@id"]]
            for child in value.values():
                resolve_provenance_links(child)
        elif isinstance(value, list):
            for child in value:
                resolve_provenance_links(child)
    resolve_provenance_links(graph)

    semantic_report = validate_semantic_rocrate(crate)
    semantic_validation_path = base_dir / "validation" / "semantic_rocrate_validation.json"
    semantic_validation_path.parent.mkdir(parents=True, exist_ok=True)
    semantic_validation_path.write_text(json.dumps(semantic_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    semantic_crate_path = Path("validation") / "semantic_rocrate_validation.json"
    copied_semantic_validation = copy_into_crate(semantic_validation_path, output_dir, semantic_crate_path)
    semantic_entity_id = semantic_crate_path.as_posix()
    semantic_entity = file_entity(
        copied_semantic_validation,
        output_dir,
        output_dir,
        {},
        entity_id=semantic_entity_id,
        name="Semantic RO-Crate validation report",
        types=["File", "CreativeWork"],
        description="Validation report for semantic RO-Crate enrichment checks.",
        extra={"about": ref("./"), "license": ref(METADATA_LICENSE), "isPartOf": ref("#dataset-validation-reports")},
    )
    add_or_update_entity(graph, semantic_entity, seen)
    add_dcterms_and_dcat(semantic_entity)
    for entity in graph:
        if entity.get("@id") == "#dataset-validation-reports":
            add_refs(entity, "hasPart", [semantic_entity_id])
            add_refs(entity, "dcat:distribution", [semantic_entity_id])
        elif entity.get("@id") == "./":
            add_refs(entity, "hasPart", [semantic_entity_id])

    semantic_action_id = f"#action-validate-semantic-ro-crate-{slug(release_id)}"
    semantic_action = make_action(
        semantic_action_id,
        "Validate semantic RO-Crate enrichment",
        "workflow/scripts/common/ro_crate_writer.py",
        ["ro-crate-metadata.json"],
        [semantic_entity_id],
        "Validate local references, semantic context, provenance invariants, and harmonized-output metadata.",
    )
    add_entity(graph, semantic_action, seen)
    enhance_actions_and_outputs(graph)
    semantic_entity["contentSize"] = str(copied_semantic_validation.stat().st_size)
    semantic_report = validate_semantic_rocrate(crate)
    semantic_validation_path.write_text(json.dumps(semantic_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shutil.copy2(semantic_validation_path, copied_semantic_validation)
    semantic_entity["contentSize"] = str(copied_semantic_validation.stat().st_size)
    add_refs(root_dataset, "mentions", [str(entity["@id"]) for entity in graph if "CreateAction" in as_list(entity.get("@type"))])

    metadata_path.write_text(json.dumps(crate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_archive(archive_path, output_dir, (config.get("ro_crate_packaging") or {}).get("archive_compression", "deflated"))
    print(f"Wrote RO-Crate metadata: {metadata_path}")
    print(f"Wrote semantic validation report: {semantic_validation_path}")
    print(f"Wrote RO-Crate archive: {archive_path}")


if __name__ == "__main__":
    main()
