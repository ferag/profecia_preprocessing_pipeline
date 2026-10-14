#!/usr/bin/env python3
"""Create an opt-in GMTED2010 reconstruction profile; never runs the workflow."""
import argparse
import copy
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workflows.data_foundation.workflow.scripts.sources.gmted2010 import source_definition


def enable(config):
    result = copy.deepcopy(config)
    result.get("canonical_reference_products", {}).pop("monthly/elevation", None)
    result["sources"]["gmted2010"] = source_definition(config)
    if not any(item.get("source") == "gmted2010" and item.get("variable") == "elevation" for item in result["selected_variables"]):
        result["selected_variables"].append({"source": "gmted2010", "variable": "elevation"})
    for item in result["derived_products"]:
        if item["id"] == "elevation":
            item["input_files"] = ["work/gmted2010/elevation_0.5deg.nc"]
            item["source_variables"] = [{"source": "gmted2010", "variable": "elevation"}]
            item["description"] = "GMTED2010 mn30_grd mean elevation, bilinear reprojected to the PROFECIA grid and repeated monthly. Equivalence to the canonical product has not been tested."
    result["elevation_reconstruction"] = {"status": "OPT_IN_UNVALIDATED", "product_id": "mn30_grd",
        "statistic": "mean", "resolution_arc_seconds": 30, "resampling": "bilinear",
        "evidence": "Historical code names mn30_grd; USGS official catalogue identifies it as mean/30 arc-seconds",
        "canonical_retirement_gate": "Compare all values, coordinates and NaN masks; separately approve corrected source/unit metadata"}
    result["release"].update(id="profecia_inputs_gmted2010_trial_v1",
                            base_dir="resources/data_releases/profecia_inputs_gmted2010_trial_v1")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("workflows/data_foundation/config/data_foundation_all_available_portable.yml"))
    parser.add_argument("--output", type=Path, default=Path("workflows/data_foundation/config/data_foundation_gmted2010_trial.yml"))
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Never overwrite the original or an existing profile")
    config = enable(yaml.safe_load(args.config.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(config, sort_keys=False))
    print(f"Created opt-in profile {args.output}; no downloads or processing")


if __name__ == "__main__":
    main()
