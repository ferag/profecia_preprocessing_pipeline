import tempfile
import unittest
from pathlib import Path

import numpy as np
import xarray as xr

from workflows.data_foundation.compare_releases import compare
from workflows.data_foundation.workflow.scripts.common.ro_crate_writer import canonical_crate_path


class TestReleaseComparison(unittest.TestCase):
    def test_replay_config_parent_does_not_capture_release_products(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "reproduced"
            result = canonical_crate_path(base / "monthly/value.nc", base_dir=base,
                                          workflow_dir=root / "workflow", config_dir=base)
            self.assertEqual(result, Path("referenced-data/monthly/value.nc"))
            metadata = canonical_crate_path(base / "validation/report.json", base_dir=base,
                                            workflow_dir=root / "workflow", config_dir=base)
            self.assertEqual(metadata, Path("validation/report.json"))

    def test_cached_symlink_keeps_its_release_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "release"
            source = root / "cached.nc"
            source.touch()
            linked = base / "raw/source/value.nc"
            linked.parent.mkdir(parents=True)
            linked.symlink_to(source)
            result = canonical_crate_path(linked, base_dir=base,
                                          workflow_dir=root / "workflow", config_dir=root / "config")
            self.assertEqual(result, Path("referenced-data/raw/source/value.nc"))

    def test_accepts_roundoff_but_rejects_grid_or_missing_mask_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first.nc", Path(directory) / "second.nc"
            data = xr.Dataset({"value": (("latitude", "longitude"), np.ones((2, 2)), {"units": "K"})},
                              coords={"latitude": [0.0, 0.5], "longitude": [0.0, 0.5]})
            data.to_netcdf(first)
            changed = data.copy(deep=True)
            changed["value"].values[0, 0] += 1e-7
            changed.to_netcdf(second)
            self.assertEqual(compare(first, second, 1e-5, 1e-6)["status"], "OK")
            changed["value"].values[0, 0] = np.nan
            changed.to_netcdf(second)
            with self.assertRaisesRegex(ValueError, "mask"):
                compare(first, second, 1e-5, 1e-6)
            changed = data.assign_coords(latitude=[0.0, 0.50001])
            changed.to_netcdf(second)
            with self.assertRaisesRegex(ValueError, "latitude"):
                compare(first, second, 1e-5, 1e-6)

    def test_rejects_changed_units(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first.nc", Path(directory) / "second.nc"
            data = xr.Dataset({"value": ("time", [1.0], {"units": "K"})})
            data.to_netcdf(first)
            data["value"].attrs["units"] = "degC"
            data.to_netcdf(second)
            with self.assertRaisesRegex(ValueError, "attribute"):
                compare(first, second, 1e-5, 1e-6)
