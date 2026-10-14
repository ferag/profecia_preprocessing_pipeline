#!/usr/bin/env python3
"""Write a Croissant JSON-LD descriptor for harmonized PROFECIA NetCDF products."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import (
    load_config,
    release,
    release_base_dir,
    selected_variables,
    source_config,
    variable_config,
)


def croissant_context() -> dict[str, Any]:
    """Croissant 1.0 standard context plus the PROFECIA extension prefix."""
    return {
        "@language": "en",
        "@vocab": "https://schema.org/",
        "citeAs": "cr:citeAs",
        "column": "cr:column",
        "conformsTo": "dct:conformsTo",
        "cr": "http://mlcommons.org/croissant/",
        "rai": "http://mlcommons.org/croissant/RAI/",
        "data": {"@id": "cr:data", "@type": "@json"},
        "dataType": {"@id": "cr:dataType", "@type": "@vocab"},
        "dct": "http://purl.org/dc/terms/",
        "equivalentProperty": "cr:equivalentProperty",
        "examples": {"@id": "cr:examples", "@type": "@json"},
        "extract": "cr:extract",
        "field": "cr:field",
        "fileProperty": "cr:fileProperty",
        "fileObject": "cr:fileObject",
        "fileSet": "cr:fileSet",
        "format": "cr:format",
        "includes": "cr:includes",
        "isLiveDataset": "cr:isLiveDataset",
        "jsonPath": "cr:jsonPath",
        "key": "cr:key",
        "md5": "cr:md5",
        "parentField": "cr:parentField",
        "path": "cr:path",
        "recordSet": "cr:recordSet",
        "references": "cr:references",
        "regex": "cr:regex",
        "repeated": "cr:repeated",
        "replace": "cr:replace",
        "samplingRate": "cr:samplingRate",
        "sc": "https://schema.org/",
        "separator": "cr:separator",
        "source": "cr:source",
        "subField": "cr:subField",
        "transform": "cr:transform",
        "profecia": "https://w3id.org/profecia/terms/",
    }


def rel(path: Path, base_dir: Path) -> str:
    return path.relative_to(base_dir).as_posix()


def checksum_index(base_dir: Path) -> dict[str, str]:
    path = base_dir / "checksums.sha256"
    if not path.exists():
        return {}
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if separator and re.fullmatch(r"[0-9a-f]{64}", digest):
            checksums[relative.strip()] = digest
    return checksums


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def croissant_version(release_id: str) -> str:
    """Map an explicit terminal vN[.N[.N]] release marker to SemVer."""
    match = re.search(r"(?:^|[_-])v(\d+)(?:\.(\d+))?(?:\.(\d+))?$", release_id)
    if not match:
        return "0.0.0"
    return ".".join(part or "0" for part in match.groups())


def variable_temporal_kind(var: dict[str, Any]) -> str:
    text = " ".join(
        str(var.get(key, "")).lower()
        for key in ("data_structure", "dimensionality", "native_temporal_resolution")
    )
    filename = str(var.get("output_filename", "")).lower()
    if "static" in text:
        return "static"
    if "annual" in text or "annual" in filename:
        return "annual"
    if "monthly" in text or "monthly" in filename or var.get("months"):
        return "monthly"
    return "static"


def harmonized_path(base_dir: Path, source: str, variable: str, var: dict[str, Any]) -> Path:
    if var.get("release_output_path"):
        relative = Path(var["release_output_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("release_output_path must stay inside the release")
        return base_dir / relative
    kind = variable_temporal_kind(var)
    if kind == "monthly":
        return base_dir / "monthly" / f"{source}_{variable}_monthly_0.5deg.nc"
    if kind == "annual":
        return base_dir / "annual" / f"{source}_{variable}_annual_0.5deg.nc"
    if source == "hwsd2":
        return base_dir / "static" / "hwsd2_soil_0.5deg.nc"
    return base_dir / "static" / f"{source}_static_0.5deg.nc"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    config = load_config(args.config)
    base_dir = release_base_dir(config)
    release_data = release(config)
    known_checksums = checksum_index(base_dir)
    distributions = []
    variables = []
    for item in selected_variables(config):
        src = source_config(config, item.source)
        var = variable_config(config, item.source, item.variable)
        path = harmonized_path(base_dir, item.source, item.variable, var)
        if not path.exists():
            continue
        file_id = f"profecia:file/harmonized/{item.source}/{item.variable}"
        variables.append(
            {
                "@id": f"profecia:variable/{item.source}/{item.variable}",
                "name": var.get("long_name", item.variable),
                "description": f"Harmonized PROFECIA variable derived from {src.get('source_family') or item.source}.",
                "profecia:sourceFamily": src.get("source_family"),
                "profecia:sourceUnits": var.get("source_units"),
                "profecia:role": var.get("role"),
                "profecia:distribution": {"@id": file_id},
            }
        )
        distributions.append(
            {
                "@type": "cr:FileObject",
                "@id": file_id,
                "name": path.name,
                "description": "Harmonized NetCDF data product on the PROFECIA target grid.",
                "contentUrl": rel(path, base_dir),
                "encodingFormat": "application/x-netcdf",
                "sha256": known_checksums.get(rel(path, base_dir)) or sha256_file(path),
            }
        )

    for item in config.get("derived_products", []) or []:
        variable = str(item.get("variable") or item.get("id"))
        output = item.get("output_filename")
        if not variable or not output:
            continue
        kind = str(item.get("temporal_resolution", "monthly")).lower()
        folder = "annual" if kind == "annual" else ("static" if kind == "static" else "monthly")
        path = base_dir / folder / str(output)
        if not path.exists():
            continue
        file_id = f"profecia:file/harmonized/derived/{variable}"
        variables.append(
            {
                "@id": f"profecia:variable/derived/{variable}",
                "name": item.get("long_name", variable),
                "description": item.get("description") or f"Derived PROFECIA variable {variable}.",
                "profecia:sourceFamily": "Derived PROFECIA variables",
                "profecia:sourceUnits": item.get("source_units") or item.get("units"),
                "profecia:role": item.get("role"),
                "profecia:formula": item.get("formula"),
                "profecia:distribution": {"@id": file_id},
            }
        )
        distributions.append(
            {
                "@type": "cr:FileObject",
                "@id": file_id,
                "name": path.name,
                "description": "Derived harmonized NetCDF data product on the PROFECIA target grid.",
                "contentUrl": rel(path, base_dir),
                "encodingFormat": "application/x-netcdf",
                "sha256": known_checksums.get(rel(path, base_dir)) or sha256_file(path),
            }
        )

    data = {
        "@context": croissant_context(),
        "@id": f"profecia:data-release/{release_data.get('id')}",
        "@type": ["sc:Dataset"],
        "conformsTo": "http://mlcommons.org/croissant/1.0",
        "name": "PROFECIA Data Foundation Demo Release harmonized NetCDF products",
        "description": "Croissant descriptor for the harmonized NetCDF products of the PROFECIA data-foundation release. Raw/source files are provenance inputs and are not the primary Croissant distributions.",
        "citeAs": "https://github.com/ferag/profecia_preprocessing_pipeline",
        "citation": "https://github.com/ferag/profecia_preprocessing_pipeline",
        "datePublished": datetime.now(timezone.utc).date().isoformat(),
        "license": "https://spdx.org/licenses/CC-BY-4.0.html",
        "identifier": str(release_data.get("id")),
        "version": croissant_version(str(release_data.get("id"))),
        "variableMeasured": variables,
        "distribution": distributions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote Croissant descriptor: {args.output}")


if __name__ == "__main__":
    main()
