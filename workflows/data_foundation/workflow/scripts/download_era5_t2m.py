#!/usr/bin/env python3
"""Download the demo ERA5/ERA5-Land T2M NetCDF using cdsapi."""

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--user-settings", default="", type=Path)
    return parser.parse_args()


def load_user_settings(path: Path | None) -> dict[str, Any]:
    if not path or str(path) == "." or not str(path):
        return {}
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"User settings file must contain a YAML mapping: {path}")
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
            "The Python package 'cdsapi' is required. Use the provided cdsapi.yml "
            "environment or install cdsapi in your active environment."
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
                    "Could not choose one NetCDF file inside the CDS ZIP download. "
                    "Expected a single .nc file or a member containing 'mnth', "
                    f"found {len(members)}: {members}"
                )
            with archive.open(selected_member) as source:
                with output_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
        return

    shutil.move(str(download_path), output_path)


def main() -> None:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)

    with args.log.open("w", encoding="utf-8") as log_handle:
        with contextlib.redirect_stdout(log_handle), contextlib.redirect_stderr(log_handle):
            print("PROFECIA data-foundation demo download")
            print(f"Request JSON: {args.request_json}")
            print(f"Output NetCDF: {args.output}")

            payload = json.loads(args.request_json.read_text(encoding="utf-8"))
            dataset = payload["dataset"]
            request = payload["request"]

            settings = load_user_settings(args.user_settings)
            url, key, source = resolve_credentials(settings)
            print(f"Credential source: {source}")

            if not url and not key and not has_standard_cds_config():
                message = (
                    "CDS credentials are not available.\n"
                    "Provide credentials with CDSAPI_URL/CDSAPI_KEY, or copy "
                    "workflows/data_foundation/config/user_settings.template.yml to "
                    "workflows/data_foundation/config/user_settings.local.yml and pass it with "
                    "--config user_settings=workflows/data_foundation/config/user_settings.local.yml, "
                    "or configure cdsapi outside this repository.\n"
                    "The pipeline never writes .cdsapirc or stores credentials in git."
                )
                print(message)
                raise RuntimeError(message)

            try:
                client = build_client(url, key)
            except RuntimeError:
                raise
            except Exception as exc:
                message = (
                    "CDS credentials could not be read by cdsapi.\n"
                    "Provide credentials with CDSAPI_URL/CDSAPI_KEY, or copy "
                    "workflows/data_foundation/config/user_settings.template.yml to "
                    "workflows/data_foundation/config/user_settings.local.yml and pass it with "
                    "--config user_settings=workflows/data_foundation/config/user_settings.local.yml, "
                    "or configure cdsapi outside this repository.\n"
                    "The pipeline never writes .cdsapirc or stores credentials in git.\n"
                    f"Original error: {exc}"
                )
                print(message)
                raise RuntimeError(message) from exc

            print(f"Retrieving dataset: {dataset}")
            with tempfile.NamedTemporaryFile(
                prefix=f"{args.output.stem}_",
                suffix=".download",
                dir=args.output.parent,
                delete=False,
            ) as tmp_handle:
                tmp_path = Path(tmp_handle.name)

            try:
                client.retrieve(dataset, request, str(tmp_path))
                normalize_download(tmp_path, args.output)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()

            if not args.output.exists() or args.output.stat().st_size == 0:
                raise RuntimeError(f"CDS download did not create a non-empty file: {args.output}")
            print(f"Download completed and normalized as NetCDF: {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
