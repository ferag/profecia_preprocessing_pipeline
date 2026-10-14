import copy
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling
import rioxarray
import xarray as xr

from workflows.data_foundation.enable_gmted2010 import enable
from workflows.data_foundation.starter_run import select_variables
from workflows.data_foundation.build_starter_crate import effective_offline_files, source_catalog
from workflows.data_foundation.workflow.scripts.sources.gmted2010 import extract_grid, resample_elevation
from workflows.data_foundation.workflow.scripts.common.manifest import harmonized_path as manifest_path
from workflows.data_foundation.workflow.scripts.common.croissant_writer import harmonized_path as croissant_path


class TestGMTED2010(unittest.TestCase):
    def config(self):
        return {"release": {"target_grid": {"resolution": "0.5deg"}},
                "sources": {}, "selected_variables": [], "derived_products": [{"id": "elevation"}],
                "canonical_reference_products": {"monthly/elevation": "offline/elevation.nc", "monthly/richness": "offline/richness.nc"},
                "local_input_paths": {"lai_h5gz": "offline/lai"}}

    def test_opt_in_does_not_change_original_and_dependency_resolves(self):
        original = self.config()
        snapshot = copy.deepcopy(original)
        config = enable(original)
        self.assertEqual(original, snapshot)
        self.assertNotIn("monthly/elevation", config["canonical_reference_products"])
        selected = select_variables(config, "elevation")
        self.assertEqual(selected["selected_variables"], [{"source": "gmted2010", "variable": "elevation"}])
        self.assertEqual(config["sources"]["gmted2010"]["statistic"], "mean")
        self.assertFalse(config["sources"]["gmted2010"]["requires_authentication"])

    def test_builder_excludes_unreferenced_canonical_and_links_real_source(self):
        config = enable(self.config())
        manifest = {"files": [{"path": path} for path in ("offline/elevation.nc", "offline/richness.nc", "offline/lai/a.gz")]}
        paths = [item["path"] for item in effective_offline_files(config, manifest)]
        self.assertEqual(paths, ["offline/richness.nc", "offline/lai/a.gz"])
        catalog = source_catalog(config)
        self.assertNotIn("gtopo30", [item["id"] for item in catalog])
        source = next(item for item in catalog if item["id"] == "gmted2010")
        self.assertTrue(source["downloaded_by_this_profile"])
        self.assertTrue(any("mn30_grd.zip" in url for url in source["urls"]))

    def test_manifest_and_croissant_share_existing_final_output(self):
        var = enable(self.config())["sources"]["gmted2010"]["variables"]["elevation"]
        first = manifest_path(Path("release"), "gmted2010", "elevation", var, True)
        second = croissant_path(Path("release"), "gmted2010", "elevation", var)
        self.assertEqual(first, second)
        self.assertEqual(first, Path("release/monthly/elevation_1982_2022_monthly_0.5deg.nc"))
        var["release_output_path"] = "../escape.nc"
        with self.assertRaises(ValueError):
            manifest_path(Path("release"), "gmted2010", "elevation", var, True)

    def test_negative_values_and_nodata_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.tif"
            data = np.arange(-4, 12, dtype="float32").reshape(4, 4)
            data[2, 2] = -9999
            with rasterio.open(path, "w", driver="GTiff", width=4, height=4, count=1,
                               dtype="float32", crs="EPSG:4326", transform=from_origin(-1, 1, .5, .5), nodata=-9999) as target:
                target.write(data, 1)
            latitude = np.array([.75, .25, -.25, -.75])
            longitude = np.array([-.75, -.25, .25, .75])
            result, metadata = resample_elevation(path, latitude, longitude)
            expected = data.copy()
            expected[expected == -9999] = np.nan
            np.testing.assert_allclose(result.elevation.values, expected, equal_nan=True)
            self.assertEqual(result.elevation.attrs["units"], "m")
            self.assertEqual(metadata["resampling"], "bilinear")
            # Match the historical reproject_match operator on a shifted synthetic grid.
            latitude, longitude = latitude - .1, longitude + .1
            result, _ = resample_elevation(path, latitude, longitude)
            reference = xr.DataArray(np.zeros((4, 4)), dims=("latitude", "longitude"),
                                     coords={"latitude": latitude, "longitude": longitude}).rio.set_spatial_dims(x_dim="longitude", y_dim="latitude").rio.write_crs("EPSG:4326")
            with rioxarray.open_rasterio(path, masked=True) as opened:
                oracle = opened.squeeze().rio.reproject_match(reference, resampling=Resampling.bilinear)
                np.testing.assert_allclose(result.elevation.values, oracle.values, equal_nan=True, atol=1e-6)

    def test_safe_arcgrid_discovery_and_traversal_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "good.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("mn30_grd/mn30_grd/hdr.adf", b"synthetic header")
            self.assertEqual(extract_grid(archive, root / "good"), root / "good/mn30_grd/mn30_grd")
            with zipfile.ZipFile(root / "bad.zip", "w") as zipped:
                zipped.writestr("../escape", b"not allowed")
            with self.assertRaises(ValueError):
                extract_grid(root / "bad.zip", root / "bad")
            self.assertFalse((root / "escape").exists())


if __name__ == "__main__":
    unittest.main()
