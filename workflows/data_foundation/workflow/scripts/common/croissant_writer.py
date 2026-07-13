#!/usr/bin/env python3
"""Write a Croissant JSON-LD descriptor for harmonized PROFECIA NetCDF products."""

from __future__ import annotations

import argparse
import json
import sys
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


def rel(path: Path, base_dir: Path) -> str:
    return path.relative_to(base_dir).as_posix()


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
            }
        )

    data = {
        "@context": {
            "schema": "https://schema.org/",
            "cr": "http://mlcommons.org/croissant/",
            "profecia": "https://w3id.org/profecia/terms/",
        },
        "@id": f"profecia:data-release/{release_data.get('id')}",
        "@type": ["schema:Dataset"],
        "name": "PROFECIA Data Foundation Demo Release harmonized NetCDF products",
        "description": "Croissant descriptor for the harmonized NetCDF products of the PROFECIA data-foundation release. Raw/source files are provenance inputs and are not the primary Croissant distributions.",
        "license": "https://spdx.org/licenses/CC-BY-4.0.html",
        "variableMeasured": variables,
        "distribution": distributions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote Croissant descriptor: {args.output}")


if __name__ == "__main__":
    main()
