#!/usr/bin/env python3
"""Write the PROFECIA multivariable demo release manifest."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--base-dir", required=True, type=Path)
    parser.add_argument("--start-year", required=True, type=int)
    parser.add_argument("--end-year", required=True, type=int)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--variables-json", required=True)
    parser.add_argument("--derived-or-external-json", default="{}")
    parser.add_argument("--monthly-paths", nargs="+", required=True, type=Path)
    parser.add_argument("--annual-paths", nargs="+", required=True, type=Path)
    parser.add_argument("--request-paths", nargs="*", default=[], type=Path)
    parser.add_argument("--validation-paths", nargs="+", required=True, type=Path)
    parser.add_argument("--croissant-paths", nargs="+", required=True, type=Path)
    return parser.parse_args()


def rel(path: Path, base_dir: Path) -> str:
    return path.relative_to(base_dir).as_posix()


def keyed(paths: list[Path], base_dir: Path) -> dict[str, str]:
    values = {}
    for path in paths:
        variable = path.stem.split("_")[0]
        if path.parent.name in {"monthly", "annual"}:
            variable = re.sub(
                rf"_\d{{4}}_\d{{4}}_{path.parent.name}_0\.5deg$",
                "",
                path.stem,
            )
        if path.name.startswith("validation_report_"):
            variable = path.stem.replace("validation_report_", "")
        if path.name.startswith("cds_request_"):
            variable = path.stem.split("_")[2]
        values[variable] = rel(path, base_dir)
    return values


def variable_entries(variables: dict[str, Any], files: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    entries = []
    for name, meta in variables.items():
        entries.append(
            {
                "name": name,
                "long_name": meta.get("long_name", name),
                "cds_variable": meta.get("cds_variable"),
                "source_unit": meta.get("source_unit", ""),
                "files": {
                    "monthly_netcdf": files["monthly"].get(name),
                    "annual_netcdf": files["annual"].get(name),
                    "cds_request": files["requests"].get(name),
                    "validation_report": files["validations"].get(name),
                    "croissant": files["croissants"].get(name),
                },
            }
        )
    return entries


def main() -> None:
    args = parse_args()
    variables = json.loads(args.variables_json)
    derived_or_external = json.loads(args.derived_or_external_json)
    files = {
        "monthly": keyed(args.monthly_paths, args.base_dir),
        "annual": keyed(args.annual_paths, args.base_dir),
        "requests": keyed(args.request_paths, args.base_dir),
        "validations": keyed(args.validation_paths, args.base_dir),
        "croissants": keyed(args.croissant_paths, args.base_dir),
    }

    manifest = {
        "data_release_id": args.release_id,
        "status": "demo-expanded",
        "created_by": "Snakemake data_foundation demo pipeline",
        "source": "Prepared PROFECIA predictors from ERA5/CDS, SPEIbase, LAI, and CarbonTracker inputs",
        "provider": "ECMWF/CDS, CSIC SPEIbase, THEIA GEOV2-GCM, NOAA CarbonTracker",
        "dataset": args.dataset,
        "period": {"start_year": args.start_year, "end_year": args.end_year},
        "temporal_resolution": ["monthly", "annual"],
        "variables": variable_entries(variables, files),
        "derived_or_external": derived_or_external,
        "notes": [
            "Final NetCDF products are stored in flat monthly/ and annual/ release folders.",
            "Raw downloads and processing intermediates are kept under raw/ and work/.",
            "LAI is prepared from local THEIA GEOV2-GCM .h5.gz files configured by products.lai.input_dir.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
