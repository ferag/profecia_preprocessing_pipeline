#!/usr/bin/env python3
"""Build the CDS request JSON for the PROFECIA data-foundation demo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def comma_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--variable", required=True)
    parser.add_argument("--year")
    parser.add_argument("--years")
    parser.add_argument("--months", required=True)
    parser.add_argument("--time", required=True)
    parser.add_argument("--data-format", required=True)
    parser.add_argument("--download-format", required=True)
    parser.add_argument("--extra-request-json", default="{}")
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    years = comma_list(args.years) if args.years else [args.year]
    if not years or years == [None]:
        raise ValueError("Provide --year or --years.")
    extra_request = json.loads(args.extra_request_json)
    payload = {
        "dataset": args.dataset,
        "request": {
            "variable": [args.variable],
            "year": years,
            "month": comma_list(args.months),
            "time": comma_list(args.time),
            "data_format": args.data_format,
            "download_format": args.download_format,
        },
    }
    payload["request"].update({key: value for key, value in extra_request.items() if value})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
