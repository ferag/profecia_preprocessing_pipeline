#!/usr/bin/env python3
"""Manual GEOV2-GCM AVHRR LAI source adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, source_config, variable_config


def check_manual_input(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    source_data = source_config(config, args.source)
    variable_data = variable_config(config, args.source, args.variable)
    raw_input_dir = Path(source_data.get("raw_input_dir", ""))
    patterns = variable_data.get("expected_patterns", [])
    if not raw_input_dir:
        raise ValueError(f"{args.source} requires raw_input_dir.")
    if not patterns:
        raise ValueError(f"{args.source}/{args.variable} requires expected_patterns.")

    matched: list[Path] = []
    if raw_input_dir.exists():
        for pattern in patterns:
            matched.extend(sorted(raw_input_dir.glob(pattern)))
    matched = sorted({path.resolve() for path in matched})

    status = "OK" if matched else "MISSING"
    instructions = source_data.get("instructions", "")
    message = (
        f"Found {len(matched)} manual LAI file(s) in {raw_input_dir}."
        if matched
        else (
            "No manual GEOV2-GCM AVHRR LAI files were found. Place files matching "
            f"{patterns} in {raw_input_dir}. {instructions}"
        )
    )
    inventory = {
        "source": args.source,
        "variable": args.variable,
        "access_mode": source_data.get("access_mode", "manual"),
        "access_protocol": source_data.get("access_protocol", "manual_local_input"),
        "raw_input_dir": str(raw_input_dir),
        "patterns": patterns,
        "matched_files": [str(path) for path in matched],
        "n_files": len(matched),
        "status": status,
        "message": message,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(message)
    if not matched and not args.allow_missing:
        raise FileNotFoundError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check-manual-input")
    check.add_argument("--config", required=True, type=Path)
    check.add_argument("--source", required=True)
    check.add_argument("--variable", required=True)
    check.add_argument("--output", required=True, type=Path)
    check.add_argument("--allow-missing", action="store_true")
    check.set_defaults(func=check_manual_input)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
