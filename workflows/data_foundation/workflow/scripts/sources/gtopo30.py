#!/usr/bin/env python3
"""USGS/GTOPO30 source adapter with local-secrets credential loading."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common.config_loader import load_config, source_config


@dataclass(frozen=True)
class UsgsCredentials:
    username: str
    token: str
    source: str


def redacted_credentials_config(source_data: dict[str, Any]) -> dict[str, Any]:
    cfg = source_data.get("credentials") or {}
    return {
        "source": cfg.get("source"),
        "path": cfg.get("path"),
        "key": cfg.get("key"),
        "environment_override": ["USGS_USERNAME", "USGS_M2M_TOKEN"],
    }


def load_secret_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            "USGS credentials file not found.\n"
            f"Expected: {path}\n"
            "Create it from workflows/data_foundation/config/secrets.local.example.yml."
        )
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"USGS credentials file must contain a YAML mapping: {path}")
    return data


def resolve_credentials(source_data: dict[str, Any]) -> UsgsCredentials:
    env_username = os.environ.get("USGS_USERNAME")
    env_token = os.environ.get("USGS_M2M_TOKEN")
    if env_username and env_token:
        return UsgsCredentials(env_username, env_token, "environment")

    cfg = source_data.get("credentials") or {}
    secret_path = Path(cfg.get("path", "workflows/data_foundation/config/secrets.local.yml"))
    secret_key = cfg.get("key", "usgs_m2m")
    secrets = load_secret_mapping(secret_path)
    values = secrets.get(secret_key) or {}
    if not isinstance(values, dict):
        raise ValueError(f"USGS credentials key '{secret_key}' must contain a YAML mapping.")

    username = values.get("username")
    token = values.get("token")
    if not username:
        raise ValueError(
            f"USGS username is missing in secrets.local.yml under key {secret_key}.username."
        )
    if not token:
        raise ValueError(
            f"USGS M2M token is missing in secrets.local.yml under key {secret_key}.token."
        )
    return UsgsCredentials(str(username), str(token), "local_secrets_file")


def m2m_login(credentials: UsgsCredentials, endpoint: str) -> str:
    payload = {"username": credentials.username, "token": credentials.token}
    response = requests.post(endpoint, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    if data.get("errorCode"):
        raise RuntimeError(f"USGS M2M authentication failed: {data.get('errorMessage')}")
    api_key = data.get("data")
    if not api_key:
        raise RuntimeError("USGS M2M authentication did not return an API key.")
    return str(api_key)


def m2m_logout(api_key: str, endpoint: str) -> None:
    try:
        requests.post(endpoint, headers={"X-Auth-Token": api_key}, timeout=30)
    except requests.RequestException:
        pass


def build_file_list(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    source_data = source_config(config, args.source)
    payload = {
        "source": args.source,
        "provider": source_data.get("provider"),
        "source_family": source_data.get("source_family"),
        "access_mode": source_data.get("access_mode"),
        "access_protocol": source_data.get("access_protocol"),
        "requires_authentication": source_data.get("requires_authentication", True),
        "doi": source_data.get("doi"),
        "landing_page": source_data.get("landing_page"),
        "native_spatial_resolution": source_data.get("native_spatial_resolution"),
        "credentials": redacted_credentials_config(source_data),
        "m2m": {
            "login_endpoint": source_data.get("m2m", {}).get(
                "login_endpoint",
                "https://m2m.cr.usgs.gov/api/api/json/stable/login-token",
            ),
            "logout_endpoint": source_data.get("m2m", {}).get(
                "logout_endpoint",
                "https://m2m.cr.usgs.gov/api/api/json/stable/logout",
            ),
            "download_spec_status": source_data.get(
                "download_design_status",
                "credentials_ready_pending_m2m_product_selection",
            ),
        },
        "notes": source_data.get("notes", []),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote sanitized GTOPO30 file list: {args.output}")


def download(args: argparse.Namespace) -> None:
    payload = json.loads(args.file_list.read_text(encoding="utf-8"))
    config = load_config(args.config) if args.config else None
    source_data = source_config(config, payload["source"]) if config else {}
    credentials = resolve_credentials(source_data)

    m2m = payload.get("m2m") or {}
    login_endpoint = m2m.get("login_endpoint")
    logout_endpoint = m2m.get("logout_endpoint")
    api_key = None
    try:
        api_key = m2m_login(credentials, login_endpoint)
        report = {
            "source": payload.get("source"),
            "status": "AUTHENTICATED_PENDING_PRODUCT_SELECTION",
            "credential_source": credentials.source,
            "access_protocol": payload.get("access_protocol"),
            "landing_page": payload.get("landing_page"),
            "message": (
                "USGS M2M authentication succeeded, but automated GTOPO30 download "
                "requires a confirmed M2M product/entity selection."
            ),
            "files": [],
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(report["message"])
    finally:
        if api_key and logout_endpoint:
            m2m_logout(api_key, logout_endpoint)


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
    dl.add_argument("--report", required=True, type=Path)
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
        sys.exit(1)
