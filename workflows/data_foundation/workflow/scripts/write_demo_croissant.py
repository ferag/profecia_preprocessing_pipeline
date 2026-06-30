#!/usr/bin/env python3
"""Write a minimal Croissant JSON-LD descriptor for the demo release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--variable", required=True)
    parser.add_argument("--year", required=True)
    parser.add_argument("--long-name", required=True)
    parser.add_argument("--source-unit", required=True)
    parser.add_argument("--monthly-path", required=True, type=Path)
    parser.add_argument("--annual-path", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = {
        "@context": {
            "schema": "https://schema.org/",
            "cr": "http://mlcommons.org/croissant/",
            "profecia": "https://w3id.org/profecia/terms/",
        },
        "@id": f"profecia:dataset/demo/{args.variable}_{args.year}",
        "@type": ["schema:Dataset", "profecia:PreparedDataset"],
        "name": f"PROFECIA {args.variable} {args.year} prepared NetCDF",
        "description": (
            "Prepared NetCDF release for the PROFECIA data-foundation pipeline. "
            f"This metadata describes monthly and annual {args.long_name} products "
            f"for {args.year}."
        ),
        "encodingFormat": "application/x-netcdf",
        "variableMeasured": [
            {
                "@id": f"profecia:variable/{args.variable}",
                "name": args.long_name,
                "profecia:sourceUnits": args.source_unit,
            }
        ],
        "distribution": [
            {
                "@type": "cr:FileObject",
                "@id": f"profecia:file/{args.variable}_{args.year}_monthly_netcdf",
                "name": args.monthly_path.name,
                "contentUrl": f"../monthly/{args.monthly_path.name}",
                "encodingFormat": "application/x-netcdf",
            },
            {
                "@type": "cr:FileObject",
                "@id": f"profecia:file/{args.variable}_{args.year}_annual_netcdf",
                "name": args.annual_path.name,
                "contentUrl": f"../annual/{args.annual_path.name}",
                "encodingFormat": "application/x-netcdf",
            }
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
