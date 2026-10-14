#!/usr/bin/env python3
"""Compare every manifested product by chunks, coordinates and missing masks."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import xarray as xr


def compare(reference, candidate, rtol, atol):
    result = {"status": "OK", "max_abs_diff": 0.0, "byte_identical": False}
    def sha(path):
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    result["reference_sha256"], result["candidate_sha256"] = sha(reference), sha(candidate)
    result["byte_identical"] = result["reference_sha256"] == result["candidate_sha256"]
    if result["byte_identical"]:
        # Equal bytes imply equal coordinates, metadata, masks and all values.
        return result
    with xr.open_dataset(reference) as first, xr.open_dataset(candidate) as second:
        if dict(first.sizes) != dict(second.sizes) or set(first.variables) != set(second.variables):
            raise ValueError("Variables or dimensions differ")
        for name in first.variables:
            a, b = first[name], second[name]
            if a.dims != b.dims:
                raise ValueError(f"Dimension order differs: {name}")
            dimension = a.dims[0] if a.ndim else None
            for start in range(0, a.sizes[dimension] if dimension else 1, 12):
                selection = {dimension: slice(start, start + 12)} if dimension else {}
                av, bv = a.isel(selection).values, b.isel(selection).values
                if np.issubdtype(av.dtype, np.number):
                    if not np.array_equal(np.isnan(av), np.isnan(bv)):
                        raise ValueError(f"Missing-value mask differs: {name}")
                    # Coordinates are exact; scientific arrays use predeclared tolerance.
                    if not np.allclose(av, bv, rtol=0 if name in first.coords else rtol,
                                       atol=0 if name in first.coords else atol, equal_nan=True):
                        raise ValueError(f"Numeric values differ: {name}")
                    finite = np.isfinite(av) & np.isfinite(bv)
                    if finite.any():
                        result["max_abs_diff"] = max(result["max_abs_diff"], float(np.max(np.abs(av[finite].astype("float64") - bv[finite].astype("float64")))))
                elif not np.array_equal(av, bv):
                    raise ValueError(f"Values differ: {name}")
            for key in ("units", "long_name"):
                if a.attrs.get(key) != b.attrs.get(key):
                    raise ValueError(f"Scientific attribute differs: {name}/{key}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rtol", type=float, default=1e-5)
    parser.add_argument("--atol", type=float, default=1e-6)
    args = parser.parse_args()
    manifest = json.loads((args.reference / "manifest.json").read_text())
    expected = sorted(set(manifest["harmonized_files"]))
    actual = set(json.loads((args.candidate / "manifest.json").read_text())["harmonized_files"])
    if set(expected) != actual:
        raise RuntimeError("Candidate product inventory differs from reference")
    results = []
    for name in expected:
        print(f"Comparing {name}", flush=True)
        try:
            reference = args.reference / name
            if not reference.is_file():
                reference = args.reference / "referenced-data" / name
            candidate = args.candidate / name
            if not candidate.is_file():
                candidate = args.candidate / "referenced-data" / name
            result = compare(reference, candidate, args.rtol, args.atol)
        except Exception as exc:
            result = {"status": "FAILED", "error": str(exc)}
        results.append({"path": name, **result})
    report = {"status": "OK" if results and all(x["status"] == "OK" for x in results) else "FAILED",
              "rtol": args.rtol, "atol": args.atol, "products": results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "OK":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
