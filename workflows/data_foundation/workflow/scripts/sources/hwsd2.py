#!/usr/bin/env python3
"""HWSD2 source adapter for PROFECIA static soil moderators."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, source_config


def file_entries(source_data: dict[str, Any]) -> list[dict[str, Any]]:
    files = source_data.get("data_files") or {}
    entries = []
    for role, item in files.items():
        if not isinstance(item, dict) or not item.get("url") or not item.get("filename"):
            raise ValueError(f"Invalid HWSD2 data_files entry for role '{role}'.")
        entries.append(
            {
                "role": role,
                "url": item["url"],
                "filename": item["filename"],
            }
        )
    if not entries:
        raise ValueError("HWSD2 source requires data_files entries.")
    return entries


def build_file_list(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    source_data = source_config(config, args.source)
    payload = {
        "source": args.source,
        "provider": source_data.get("provider"),
        "source_family": source_data.get("source_family"),
        "access_mode": source_data.get("access_mode"),
        "access_protocol": source_data.get("access_protocol"),
        "landing_page": source_data.get("landing_page"),
        "native_spatial_resolution": source_data.get("native_spatial_resolution"),
        "files": file_entries(source_data),
        "notes": [
            "HWSD2 raw source is downloaded once per release and shared by all soil variables.",
            "Scientific preprocessing to derive PROFECIA static soil layers is handled downstream.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote HWSD2 file list with {len(payload['files'])} file(s): {args.output}")


def copy_file_url(url: str, output: Path) -> None:
    parsed = urlparse(url)
    source = Path(parsed.path if parsed.scheme == "file" else url)
    if not source.exists():
        raise FileNotFoundError(f"Local source file not found: {source}")
    shutil.copy2(source, output)


def download_url(url: str, output: Path) -> None:
    if output.exists() and output.stat().st_size > 0:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    parsed = urlparse(url)
    if parsed.scheme in {"", "file"}:
        copy_file_url(url, tmp)
    else:
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
    tmp.replace(output)


def download(args: argparse.Namespace) -> None:
    payload = json.loads(args.file_list.read_text(encoding="utf-8"))
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.report or args.file_list.parent / "download_report.json"

    downloaded = []
    for item in payload["files"]:
        output = output_dir / item["filename"]
        print(f"Downloading/checking {item['url']}")
        download_url(item["url"], output)
        downloaded.append(
            {
                "role": item["role"],
                "url": item["url"],
                "path": str(output),
                "filename": item["filename"],
                "size_bytes": output.stat().st_size,
                "status": "OK",
            }
        )

    report = {
        "source": payload.get("source"),
        "status": "OK",
        "files": downloaded,
        "message": f"Downloaded/verified {len(downloaded)} HWSD2 raw file(s).",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(report["message"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-file-list")
    build.add_argument("--config", required=True, type=Path)
    build.add_argument("--source", required=True)
    build.add_argument("--output", required=True, type=Path)
    build.set_defaults(func=build_file_list)

    dl = sub.add_parser("download")
    dl.add_argument("--config", type=Path)
    dl.add_argument("--file-list", required=True, type=Path)
    dl.add_argument("--output-dir", required=True, type=Path)
    dl.add_argument("--report", type=Path)
    dl.set_defaults(func=download)
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
