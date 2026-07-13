#!/usr/bin/env python3
"""Compare generated PROFECIA release NetCDFs against legacy final_datasets.

The comparison is intentionally value-focused:
- variable names, attrs, dtype, and equivalent coordinate names may differ;
- NaNs in the same positions are equal;
- same-shape grids are compared by position, so half-cell coordinate offsets do
  not force an xarray labelled broadcast.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import xarray as xr


DEFAULT_RELEASE_DIR = Path(
    "resources/data_releases/profecia_inputs_all_available_v0"
)
DEFAULT_REFERENCE_DIR = Path("/srv/read_only_data/final_datasets")
DEFAULT_REPORT_JSON = Path("logs/final_dataset_comparison.json")
DEFAULT_REPORT_CSV = Path("logs/final_dataset_comparison.csv")

RTOL = 1e-5
ATOL = 1e-6
NUMERICALLY_EQUIVALENT_MAX_ABS = 1e-3
NUMERICALLY_EQUIVALENT_RMSE = 1e-6

LAT_DIMS = ("latitude", "lat", "y")
LON_DIMS = ("longitude", "lon", "x")


@dataclass(frozen=True)
class PairSpec:
    key: str
    generated_rel: str
    generated_var: str
    reference_rel: str
    reference_var: str
    exact: bool = False
    derived_kind: str | None = None
    note: str | None = None


@dataclass
class Stats:
    total: int = 0
    comparable: int = 0
    equal: int = 0
    different: int = 0
    nan_mask_different: int = 0
    sum_abs_diff: float = 0.0
    sum_sq_diff: float = 0.0
    max_abs_diff: float = 0.0
    generated_min: float | None = None
    generated_max: float | None = None
    reference_min: float | None = None
    reference_max: float | None = None

    def add_range(self, generated: np.ndarray, reference: np.ndarray) -> None:
        for arr, prefix in ((generated, "generated"), (reference, "reference")):
            finite = arr[np.isfinite(arr)]
            if finite.size == 0:
                continue
            mn = float(np.nanmin(finite))
            mx = float(np.nanmax(finite))
            old_min = getattr(self, f"{prefix}_min")
            old_max = getattr(self, f"{prefix}_max")
            setattr(self, f"{prefix}_min", mn if old_min is None else min(old_min, mn))
            setattr(self, f"{prefix}_max", mx if old_max is None else max(old_max, mx))

    def add_diff(self, generated: np.ndarray, reference: np.ndarray, *, exact: bool) -> None:
        generated = np.asarray(generated)
        reference = np.asarray(reference)
        self.total += int(generated.size)
        self.add_range(generated, reference)

        gen_nan = np.isnan(generated)
        ref_nan = np.isnan(reference)
        nan_same = gen_nan == ref_nan
        self.nan_mask_different += int((~nan_same).sum())

        both_finite = np.isfinite(generated) & np.isfinite(reference)
        self.comparable += int(both_finite.sum())

        if exact:
            finite_equal = generated[both_finite] == reference[both_finite]
        else:
            finite_equal = np.isclose(
                generated[both_finite],
                reference[both_finite],
                rtol=RTOL,
                atol=ATOL,
                equal_nan=False,
            )

        nan_equal_count = int((gen_nan & ref_nan).sum())
        finite_equal_count = int(finite_equal.sum())
        self.equal += nan_equal_count + finite_equal_count

        finite_diff = both_finite.copy()
        finite_positions = np.flatnonzero(both_finite.ravel())
        if finite_positions.size:
            finite_diff_flat = finite_diff.ravel()
            finite_diff_flat[finite_positions[finite_equal]] = False

        self.different += int(finite_diff.sum()) + int((~nan_same).sum())

        if both_finite.any():
            abs_diff = np.abs(generated[both_finite] - reference[both_finite]).astype("float64")
            if abs_diff.size:
                self.sum_abs_diff += float(abs_diff.sum())
                self.sum_sq_diff += float(np.square(abs_diff).sum())
                self.max_abs_diff = max(self.max_abs_diff, float(abs_diff.max()))

    def finish(self) -> dict:
        mean_abs = self.sum_abs_diff / self.comparable if self.comparable else None
        rmse = math.sqrt(self.sum_sq_diff / self.comparable) if self.comparable else None
        return {
            "total_values": self.total,
            "comparable_values": self.comparable,
            "equal_values": self.equal,
            "different_values": self.different,
            "nan_mask_different": self.nan_mask_different,
            "max_abs_diff": self.max_abs_diff if self.comparable else None,
            "mean_abs_diff": mean_abs,
            "rmse": rmse,
            "generated_min": self.generated_min,
            "generated_max": self.generated_max,
            "reference_min": self.reference_min,
            "reference_max": self.reference_max,
        }


def build_pair_specs() -> list[PairSpec]:
    specs: list[PairSpec] = []

    for var in ["t2m", "d2m", "tp", "pev", "ssrd", "swvl1", "swvl2", "swvl3", "tcc", "u10", "v10"]:
        specs.append(
            PairSpec(
                key=var,
                generated_rel=f"monthly/era5_single_levels_{var}_monthly_0.5deg.nc",
                generated_var=var,
                reference_rel=f"monthly/{var}_1982_2022_monthly_0.5deg.nc",
                reference_var=var,
            )
        )

    for scale in ["01", "02", "03", "06", "09", "12", "24"]:
        specs.append(
            PairSpec(
                key=f"spei{scale}",
                generated_rel=f"monthly/speibase_v211_spei{scale}_monthly_0.5deg.nc",
                generated_var=f"spei{scale}",
                reference_rel=f"monthly/spei{scale}_1982_2022_monthly_0.5deg.nc",
                reference_var="spei",
            )
        )

    specs.extend(
        [
            PairSpec(
                key="lai",
                generated_rel="monthly/lai_1982_2022_monthly_0.5deg.nc",
                generated_var="lai",
                reference_rel="monthly/lai_1982_2022_monthly_0.5deg.nc",
                reference_var="LAI",
            ),
            PairSpec(
                key="swvl1-2",
                generated_rel="monthly/swvl1-2_1982_2022_monthly_0.5deg.nc",
                generated_var="swvl1-2",
                reference_rel="monthly/swvl1-2_1982_2022_monthly_0.5deg.nc",
                reference_var="swvl1-2",
                derived_kind="swvl1-2",
            ),
            PairSpec(
                key="subswc",
                generated_rel="monthly/subswc_1982_2022_monthly_0.5deg.nc",
                generated_var="subswc",
                reference_rel="monthly/subswc_1982_2022_monthly_0.5deg.nc",
                reference_var="swc_sub",
                derived_kind="subswc",
            ),
            PairSpec(
                key="wind",
                generated_rel="monthly/wind_1982_2022_monthly_0.5deg.nc",
                generated_var="wind",
                reference_rel="monthly/wind_1982_2022_monthly_0.5deg.nc",
                reference_var="wind_speed",
                derived_kind="wind",
            ),
            PairSpec(
                key="vpd",
                generated_rel="monthly/vpd_1982_2022_monthly_0.5deg.nc",
                generated_var="vpd",
                reference_rel="monthly/vpd_1982_2022_monthly_0.5deg.nc",
                reference_var="vpd",
                derived_kind="vpd",
            ),
            PairSpec(
                key="spei06_univariable",
                generated_rel="monthly/spei06_univariable_1982_2022_monthly_0.5deg.nc",
                generated_var="spei06",
                reference_rel="monthly/spei06_univariable_1982_2022_monthly_0.5deg.nc",
                reference_var="spei",
            ),
        ]
    )

    for var in ["bulk", "cec", "clay", "elevation", "ph", "richness", "sand", "silt", "soc", "total_n"]:
        specs.append(
            PairSpec(
                key=var,
                generated_rel=f"monthly/{var}_1982_2022_monthly_0.5deg.nc",
                generated_var=var,
                reference_rel=f"monthly/soil/{var}_1982_2022_monthly_0.5deg.nc",
                reference_var=var,
                note="Reference is annual/static-like in monthly/soil; expanded to generated monthly years when needed.",
            )
        )

    for var, generated_rel in [
        ("co2", "annual/co2_1982_2022_annual_0.5deg.nc"),
        ("hfp", "annual/hfp_mu_hengl_hfp_annual_0.5deg.nc"),
        ("ndep", "annual/ndep_tian2022_ndep_annual_0.5deg.nc"),
        ("tlu", "annual/tlu_1982_2022_annual_0.5deg.nc"),
    ]:
        specs.append(
            PairSpec(
                key=f"{var}_annual_human",
                generated_rel=generated_rel,
                generated_var=var,
                reference_rel=f"annual/human/{var}_1982_2022_annual_0.5deg.nc",
                reference_var=var,
                note="Annual human reference uses time coordinate; generated may use year coordinate.",
            )
        )

    for var in ["sand", "clay", "silt", "ph", "soc", "total_n", "bulk", "cec"]:
        specs.append(
            PairSpec(
                key=f"hwsd2_static_{var}",
                generated_rel="static/hwsd2_soil_0.5deg.nc",
                generated_var=var,
                reference_rel=f"monthly/soil/{var}_1982_2022_monthly_0.5deg.nc",
                reference_var=var,
                note="Generated is static 2D; reference is annual/static-like and compared by broadcasting over years.",
            )
        )
    return specs


def data_var(ds: xr.Dataset, requested: str) -> xr.DataArray:
    if requested in ds.data_vars:
        return ds[requested]

    candidates = [
        name
        for name, da in ds.data_vars.items()
        if da.ndim > 0 and name.lower() not in {"crs", "spatial_ref"}
    ]
    if len(candidates) == 1:
        return ds[candidates[0]]
    raise KeyError(f"Variable {requested!r} not found; available={list(ds.data_vars)}")


def spatial_dims(da: xr.DataArray) -> tuple[str | None, str | None]:
    lat = next((dim for dim in LAT_DIMS if dim in da.dims), None)
    lon = next((dim for dim in LON_DIMS if dim in da.dims), None)
    return lat, lon


def coord_values(da: xr.DataArray, dim: str) -> np.ndarray:
    if dim in da.coords:
        return np.asarray(da[dim].values)
    return np.arange(da.sizes[dim])


def normalize_dims(da: xr.DataArray) -> xr.DataArray:
    rename: dict[str, str] = {}
    if "year" in da.dims:
        rename["year"] = "time"
    lat, lon = spatial_dims(da)
    if lat and lat != "latitude":
        rename[lat] = "latitude"
    if lon and lon != "longitude":
        rename[lon] = "longitude"
    if rename:
        da = da.rename(rename)

    non_spatial = [dim for dim in da.dims if dim not in {"latitude", "longitude"}]
    final_dims = non_spatial + [dim for dim in ["latitude", "longitude"] if dim in da.dims]
    return da.transpose(*final_dims)


def years_for(da: xr.DataArray) -> np.ndarray | None:
    if "time" not in da.dims:
        return None
    coord = da["time"].values if "time" in da.coords else np.arange(da.sizes["time"])
    if np.issubdtype(coord.dtype, np.datetime64):
        return coord.astype("datetime64[Y]").astype(int) + 1970
    return coord.astype(int)


def expand_time_to_match(source: xr.DataArray, target: xr.DataArray) -> xr.DataArray | None:
    """Expand annual/static source along target time if years are compatible."""
    if "time" not in target.dims:
        return None

    target_years = years_for(target)
    if target_years is None:
        return None

    if "time" not in source.dims:
        expanded = source.expand_dims(time=target["time"] if "time" in target.coords else target_years)
        return expanded.transpose(*target.dims)

    source_years = years_for(source)
    if source_years is None:
        return None
    if set(np.unique(target_years)).issubset(set(source_years)):
        positions = np.array([int(np.where(source_years == year)[0][0]) for year in target_years])
        expanded = source.isel(time=positions)
        if "time" in target.coords:
            expanded = expanded.assign_coords(time=target["time"])
        return expanded.transpose(*target.dims)
    return None


def harmonize_temporal(generated: xr.DataArray, reference: xr.DataArray) -> tuple[xr.DataArray, xr.DataArray, str | None]:
    if generated.shape == reference.shape:
        return generated, reference, None

    expanded_reference = expand_time_to_match(reference, generated)
    if expanded_reference is not None and expanded_reference.shape == generated.shape:
        return generated, expanded_reference, "Reference annual/static time expanded to generated time axis."

    expanded_generated = expand_time_to_match(generated, reference)
    if expanded_generated is not None and expanded_generated.shape == reference.shape:
        return expanded_generated, reference, "Generated annual/static time expanded to reference time axis."

    return generated, reference, None


def coord_summary(da: xr.DataArray) -> dict:
    out: dict[str, dict] = {}
    for dim in da.dims:
        vals = coord_values(da, dim)
        if vals.size == 0:
            out[dim] = {"size": 0}
            continue
        entry = {"size": int(vals.size), "first": str(vals[0]), "last": str(vals[-1])}
        if vals.size > 1 and np.issubdtype(vals.dtype, np.number):
            entry["median_step"] = float(np.nanmedian(np.diff(vals)))
        out[dim] = entry
    return out


def slices_for(da: xr.DataArray, chunk: int) -> Iterable[dict[str, slice]]:
    leading_dims = [dim for dim in da.dims if dim not in {"latitude", "longitude"}]
    if not leading_dims:
        yield {}
        return

    dim = leading_dims[0]
    size = da.sizes[dim]
    for start in range(0, size, chunk):
        yield {dim: slice(start, min(start + chunk, size))}


def compare_arrays(generated: xr.DataArray, reference: xr.DataArray, *, exact: bool, chunk: int) -> dict:
    generated = normalize_dims(generated)
    reference = normalize_dims(reference)
    generated, reference, temporal_note = harmonize_temporal(generated, reference)

    dims_match = generated.dims == reference.dims
    shape_match = generated.shape == reference.shape
    result = {
        "generated_dims": list(generated.dims),
        "reference_dims": list(reference.dims),
        "generated_shape": list(generated.shape),
        "reference_shape": list(reference.shape),
        "generated_dtype": str(generated.dtype),
        "reference_dtype": str(reference.dtype),
        "generated_coords": coord_summary(generated),
        "reference_coords": coord_summary(reference),
        "comparison_mode": "position" if shape_match else "aligned_coords",
    }
    if temporal_note:
        result["temporal_note"] = temporal_note

    if not shape_match:
        generated, reference = xr.align(generated, reference, join="inner")
        result["aligned_shape"] = list(generated.shape)
        if any(size == 0 for size in generated.shape):
            result["status"] = "NOT_COMPARABLE"
            result["reason"] = "No common coordinates after alignment and shapes differ."
            return result
        if generated.shape != reference.shape:
            result["status"] = "NOT_COMPARABLE"
            result["reason"] = "Aligned arrays still have different shapes."
            return result
    elif not dims_match:
        result["reason"] = "Shapes match; dimensions/coordinates compared by position."

    stats = Stats()
    for indexer in slices_for(generated, chunk):
        gen = np.asarray(generated.isel(indexer).values)
        ref = np.asarray(reference.isel(indexer).values)
        stats.add_diff(gen, ref, exact=exact)

    result.update(stats.finish())
    if result["different_values"] == 0:
        result["status"] = "OK"
    elif result["nan_mask_different"] == result["different_values"]:
        result["status"] = "DIFF_NAN_MASK_ONLY"
        result["reason"] = "Only NaN mask differs; finite overlapping values are within tolerance."
    elif (
        result["nan_mask_different"] == 0
        and result.get("max_abs_diff") is not None
        and result.get("rmse") is not None
        and result["max_abs_diff"] <= NUMERICALLY_EQUIVALENT_MAX_ABS
        and result["rmse"] <= NUMERICALLY_EQUIVALENT_RMSE
    ):
        result["status"] = "OK_NUMERICALLY_EQUIVALENT"
        result["reason"] = "Finite differences are below numeric-equivalence thresholds."
    else:
        result["status"] = "DIFF_REAL_VALUES"
    return result


def open_and_compare(spec: PairSpec, release_dir: Path, reference_dir: Path, chunk: int) -> dict:
    generated_path = release_dir / spec.generated_rel
    reference_path = reference_dir / spec.reference_rel
    result = {
        "key": spec.key,
        "status": None,
        "generated_path": str(generated_path),
        "reference_path": str(reference_path),
        "generated_var": spec.generated_var,
        "reference_var": spec.reference_var,
        "exact": spec.exact,
        "derived_kind": spec.derived_kind,
        "note": spec.note,
    }

    if not generated_path.exists():
        result["status"] = "MISSING_GENERATED"
        return result
    if not reference_path.exists():
        result["status"] = "MISSING_REFERENCE"
        return result

    try:
        with xr.open_dataset(generated_path) as gen_ds, xr.open_dataset(reference_path) as ref_ds:
            gen_da = data_var(gen_ds, spec.generated_var)
            ref_da = data_var(ref_ds, spec.reference_var)
            result.update(compare_arrays(gen_da, ref_da, exact=spec.exact, chunk=chunk))
    except Exception as exc:  # keep the full run going variable by variable
        result["status"] = "ERROR"
        result["error_type"] = type(exc).__name__
        result["reason"] = str(exc)
    return result


def formula_stats(
    target_path: Path,
    target_var: str,
    inputs: dict[str, tuple[Path, str]],
    formula: Callable[[dict[str, np.ndarray]], np.ndarray],
    *,
    chunk: int,
) -> dict:
    paths = [target_path] + [path for path, _ in inputs.values()]
    if any(not path.exists() for path in paths):
        return {"status": "SKIPPED", "reason": "Missing formula input."}

    try:
        datasets = [xr.open_dataset(path) for path in paths]
        target = normalize_dims(data_var(datasets[0], target_var))
        input_arrays = {
            name: normalize_dims(data_var(ds, var))
            for (name, (path, var)), ds in zip(inputs.items(), datasets[1:])
        }
        stats = Stats()
        for indexer in slices_for(target, chunk):
            target_values = np.asarray(target.isel(indexer).values)
            input_values = {
                name: np.asarray(arr.isel(indexer).values)
                for name, arr in input_arrays.items()
            }
            expected = formula(input_values)
            stats.add_diff(target_values, expected, exact=False)
        out = stats.finish()
        out["status"] = "OK" if out["different_values"] == 0 else "DIFF"
        return out
    except Exception as exc:
        return {"status": "ERROR", "error_type": type(exc).__name__, "reason": str(exc)}
    finally:
        for ds in locals().get("datasets", []):
            ds.close()


def add_formula_diagnostic(result: dict, release_dir: Path, reference_dir: Path, chunk: int) -> None:
    if result.get("status") != "DIFF_REAL_VALUES":
        return

    kind = result.get("derived_kind")
    if kind == "wind":
        result["formula_diagnostic"] = {
            "generated_vs_formula": formula_stats(
                release_dir / "monthly/wind_1982_2022_monthly_0.5deg.nc",
                "wind",
                {
                    "u10": (release_dir / "monthly/era5_single_levels_u10_monthly_0.5deg.nc", "u10"),
                    "v10": (release_dir / "monthly/era5_single_levels_v10_monthly_0.5deg.nc", "v10"),
                },
                lambda x: np.hypot(x["u10"], x["v10"]),
                chunk=chunk,
            ),
            "reference_vs_formula": formula_stats(
                reference_dir / "monthly/wind_1982_2022_monthly_0.5deg.nc",
                "wind_speed",
                {
                    "u10": (reference_dir / "monthly/u10_1982_2022_monthly_0.5deg.nc", "u10"),
                    "v10": (reference_dir / "monthly/v10_1982_2022_monthly_0.5deg.nc", "v10"),
                },
                lambda x: np.hypot(x["u10"], x["v10"]),
                chunk=chunk,
            ),
        }
    elif kind == "subswc":
        formula = lambda x: ((x["swvl2"] * 21.0) + (x["swvl3"] * 72.0)) / 93.0
        result["formula_diagnostic"] = {
            "generated_vs_formula": formula_stats(
                release_dir / "monthly/subswc_1982_2022_monthly_0.5deg.nc",
                "subswc",
                {
                    "swvl2": (release_dir / "monthly/era5_single_levels_swvl2_monthly_0.5deg.nc", "swvl2"),
                    "swvl3": (release_dir / "monthly/era5_single_levels_swvl3_monthly_0.5deg.nc", "swvl3"),
                },
                formula,
                chunk=chunk,
            ),
            "reference_vs_formula": formula_stats(
                reference_dir / "monthly/subswc_1982_2022_monthly_0.5deg.nc",
                "swc_sub",
                {
                    "swvl2": (reference_dir / "monthly/swvl2_1982_2022_monthly_0.5deg.nc", "swvl2"),
                    "swvl3": (reference_dir / "monthly/swvl3_1982_2022_monthly_0.5deg.nc", "swvl3"),
                },
                formula,
                chunk=chunk,
            ),
        }
    elif kind == "swvl1-2":
        formula = lambda x: ((x["swvl1"] * 7.0) + (x["swvl2"] * 21.0)) / 28.0
        result["formula_diagnostic"] = {
            "generated_vs_formula": formula_stats(
                release_dir / "monthly/swvl1-2_1982_2022_monthly_0.5deg.nc",
                "swvl1-2",
                {
                    "swvl1": (release_dir / "monthly/era5_single_levels_swvl1_monthly_0.5deg.nc", "swvl1"),
                    "swvl2": (release_dir / "monthly/era5_single_levels_swvl2_monthly_0.5deg.nc", "swvl2"),
                },
                formula,
                chunk=chunk,
            ),
            "reference_vs_formula": formula_stats(
                reference_dir / "monthly/swvl1-2_1982_2022_monthly_0.5deg.nc",
                "swvl1-2",
                {
                    "swvl1": (reference_dir / "monthly/swvl1_1982_2022_monthly_0.5deg.nc", "swvl1"),
                    "swvl2": (reference_dir / "monthly/swvl2_1982_2022_monthly_0.5deg.nc", "swvl2"),
                },
                formula,
                chunk=chunk,
            ),
        }
    elif kind == "vpd":
        def formula(x: dict[str, np.ndarray]) -> np.ndarray:
            t = x["t2m"] - 273.15
            td = x["d2m"] - 273.15
            es = 0.611 * np.exp((17.5 * t) / (t + 240.978))
            ea = 0.611 * np.exp((17.5 * td) / (td + 240.978))
            return np.clip(es - ea, 0, None)

        result["formula_diagnostic"] = {
            "generated_vs_formula": formula_stats(
                release_dir / "monthly/vpd_1982_2022_monthly_0.5deg.nc",
                "vpd",
                {
                    "t2m": (release_dir / "monthly/era5_single_levels_t2m_monthly_0.5deg.nc", "t2m"),
                    "d2m": (release_dir / "monthly/era5_single_levels_d2m_monthly_0.5deg.nc", "d2m"),
                },
                formula,
                chunk=chunk,
            ),
            "reference_vs_formula": formula_stats(
                reference_dir / "monthly/vpd_1982_2022_monthly_0.5deg.nc",
                "vpd",
                {
                    "t2m": (reference_dir / "monthly/t2m_1982_2022_monthly_0.5deg.nc", "t2m"),
                    "d2m": (reference_dir / "monthly/d2m_1982_2022_monthly_0.5deg.nc", "d2m"),
                },
                formula,
                chunk=chunk,
            ),
        }


def generated_netcdfs(release_dir: Path) -> list[str]:
    roots = [release_dir / "monthly", release_dir / "annual", release_dir / "static"]
    out: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.nc")):
            out.append(str(path.relative_to(release_dir)))
    return out


def not_comparable_results(release_dir: Path, specs: list[PairSpec]) -> list[dict]:
    mapped = {spec.generated_rel for spec in specs}
    results = []
    for rel in generated_netcdfs(release_dir):
        if rel in mapped:
            continue
        results.append(
            {
                "key": Path(rel).stem,
                "status": "NOT_COMPARABLE",
                "generated_path": str(release_dir / rel),
                "reference_path": None,
                "reason": "No explicit counterpart in /srv/read_only_data/final_datasets mapping.",
            }
        )
    return results


def write_reports(results: list[dict], json_path: Path, csv_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")

    fields = [
        "key",
        "status",
        "different_values",
        "nan_mask_different",
        "max_abs_diff",
        "mean_abs_diff",
        "rmse",
        "generated_shape",
        "reference_shape",
        "comparison_mode",
        "reason",
        "generated_path",
        "reference_path",
    ]
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow(row)


def print_summary(results: list[dict]) -> None:
    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("Status counts:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print()
    print(f"{'status':<18} {'key':<22} {'diff':>12} {'max_abs':>12} {'rmse':>12}")
    for row in results:
        print(
            f"{row['status']:<18} {row['key']:<22} "
            f"{str(row.get('different_values', '')):>12} "
            f"{fmt(row.get('max_abs_diff')):>12} "
            f"{fmt(row.get('rmse')):>12}"
        )


def fmt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    parser.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE_DIR)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-csv", type=Path, default=DEFAULT_REPORT_CSV)
    parser.add_argument("--chunk", type=int, default=12, help="Chunk size along the first non-spatial dimension.")
    parser.add_argument("--only", nargs="*", help="Optional variable keys to compare, e.g. t2m spei06 wind.")
    parser.add_argument("--skip-formula-diagnostics", action="store_true")
    parser.add_argument("--include-not-comparable", action="store_true", default=True)
    parser.add_argument("--no-not-comparable", action="store_false", dest="include_not_comparable")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    specs = build_pair_specs()
    if args.only:
        wanted = set(args.only)
        specs = [spec for spec in specs if spec.key in wanted]
        missing = sorted(wanted - {spec.key for spec in specs})
        if missing:
            raise SystemExit(f"Unknown --only keys: {missing}")

    results = []
    for spec in specs:
        print(f"Comparing {spec.key}...", flush=True)
        result = open_and_compare(spec, args.release_dir, args.reference_dir, args.chunk)
        if not args.skip_formula_diagnostics:
            add_formula_diagnostic(result, args.release_dir, args.reference_dir, args.chunk)
        results.append(result)

    if args.include_not_comparable and not args.only:
        results.extend(not_comparable_results(args.release_dir, build_pair_specs()))

    write_reports(results, args.report_json, args.report_csv)
    print_summary(results)
    print()
    print(f"JSON report: {args.report_json}")
    print(f"CSV report:  {args.report_csv}")


if __name__ == "__main__":
    main()
