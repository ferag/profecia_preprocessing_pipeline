#!/usr/bin/env python3
"""ERA5/ERA5-Land source adapter for PROFECIA data-foundation."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, source_config, variable_config


def load_user_settings(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    settings_path = Path(path)
    if not settings_path.exists():
        return {}
    with settings_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"User settings file must contain a YAML mapping: {settings_path}")
    return data


def resolve_credentials(settings: dict[str, Any]) -> tuple[str | None, str | None, str]:
    env_url = os.environ.get("CDSAPI_URL")
    env_key = os.environ.get("CDSAPI_KEY")
    if env_url and env_key:
        return env_url, env_key, "environment variables CDSAPI_URL/CDSAPI_KEY"

    cds_settings = settings.get("cds", {}) if isinstance(settings.get("cds", {}), dict) else {}
    file_url = cds_settings.get("url")
    file_key = cds_settings.get("key")
    if file_url and file_key and "replace-with" not in str(file_key):
        return str(file_url), str(file_key), "user_settings.local.yml"

    return None, None, "standard cdsapi discovery"


def has_standard_cds_config() -> bool:
    rc_path = os.environ.get("CDSAPI_RC")
    if rc_path and Path(rc_path).expanduser().exists():
        return True
    return (Path.home() / ".cdsapirc").exists()


def build_client(url: str | None, key: str | None):
    try:
        import cdsapi
    except ImportError as exc:
        raise RuntimeError(
            "The Python package 'cdsapi' is required. Install "
            "workflows/data_foundation/requirements.txt or use the cdsapi env."
        ) from exc
    if url and key:
        return cdsapi.Client(url=url, key=key)
    return cdsapi.Client()


def normalize_download(download_path: Path, output_path: Path) -> None:
    if zipfile.is_zipfile(download_path):
        with zipfile.ZipFile(download_path) as archive:
            members = [
                member
                for member in archive.namelist()
                if not member.endswith("/") and member.lower().endswith(".nc")
            ]
            preferred = [member for member in members if "mnth" in Path(member).stem.lower()]
            if preferred:
                selected_member = preferred[0]
            elif len(members) == 1:
                selected_member = members[0]
            else:
                raise RuntimeError(
                    "Could not choose one NetCDF inside the CDS ZIP download. "
                    f"Found {len(members)} .nc files: {members}"
                )
            with archive.open(selected_member) as source:
                with output_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
        return
    shutil.move(str(download_path), output_path)


def request_payload(config_path: Path, source: str, variable: str) -> dict[str, Any]:
    config = load_config(config_path)
    source_data = source_config(config, source)
    variable_data = variable_config(config, source, variable)

    dataset = source_data.get("dataset")
    cds_name = variable_data.get("cds_name")
    if not dataset or not cds_name:
        raise ValueError(f"{source}/{variable} requires source.dataset and variable.cds_name.")

    request = {
        "variable": [cds_name],
        "year": [str(item) for item in variable_data.get("years", [])],
        "month": [str(item) for item in variable_data.get("months", [])],
        "time": [str(item) for item in variable_data.get("time", [])],
        "data_format": variable_data.get("data_format", "netcdf"),
        "download_format": variable_data.get("download_format", "unarchived"),
    }
    product_type = variable_data.get("product_type") or source_data.get("product_type")
    if product_type:
        request["product_type"] = product_type

    missing = [key for key, value in request.items() if value in (None, [], "")]
    if missing:
        raise ValueError(f"{source}/{variable} CDS request is missing: {', '.join(missing)}")

    return {
        "dataset": dataset,
        "source": source,
        "variable": variable,
        "request": request,
    }


def build_request(args: argparse.Namespace) -> None:
    payload = request_payload(args.config, args.source, args.variable)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        "Built CDS request "
        f"dataset={payload['dataset']} variable={payload['request']['variable'][0]} "
        f"years={','.join(payload['request']['year'])} output={args.output}"
    )


def download(args: argparse.Namespace) -> None:
    payload = json.loads(args.request.read_text(encoding="utf-8"))
    settings = load_user_settings(args.user_settings)
    url, key, credential_source = resolve_credentials(settings)
    if not url and not key and not has_standard_cds_config():
        raise RuntimeError(
            "CDS credentials are not available. Provide CDSAPI_URL/CDSAPI_KEY, "
            "configure ~/.cdsapirc, or pass --user-settings pointing to a local "
            "settings file with cds.url and cds.key. Credentials are never written "
            "by the workflow."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("w", encoding="utf-8") as log_handle:
        with contextlib.redirect_stdout(log_handle), contextlib.redirect_stderr(log_handle):
            print("PROFECIA ERA5 source adapter")
            print(f"Credential source: {credential_source}")
            print(f"Dataset: {payload['dataset']}")
            print(f"Variable: {payload['request'].get('variable')}")
            print(f"Years: {payload['request'].get('year')}")
            print(f"Months: {payload['request'].get('month')}")
            print(f"Output: {args.output}")

            client = build_client(url, key)
            with tempfile.NamedTemporaryFile(
                prefix=f"{args.output.stem}_",
                suffix=".download",
                dir=args.output.parent,
                delete=False,
            ) as tmp_handle:
                tmp_path = Path(tmp_handle.name)
            try:
                client.retrieve(payload["dataset"], payload["request"], str(tmp_path))
                normalize_download(tmp_path, args.output)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()

            if not args.output.exists() or args.output.stat().st_size == 0:
                raise RuntimeError(f"CDS download did not create a non-empty file: {args.output}")
            print(f"Download completed: {args.output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-request")
    build.add_argument("--config", required=True, type=Path)
    build.add_argument("--source", required=True)
    build.add_argument("--variable", required=True)
    build.add_argument("--output", required=True, type=Path)
    build.set_defaults(func=build_request)

    dl = sub.add_parser("download")
    dl.add_argument("--config", required=True, type=Path)
    dl.add_argument("--source", required=True)
    dl.add_argument("--variable", required=True)
    dl.add_argument("--request", required=True, type=Path)
    dl.add_argument("--output", required=True, type=Path)
    dl.add_argument("--log", required=True, type=Path)
    dl.add_argument("--user-settings", default="")
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
