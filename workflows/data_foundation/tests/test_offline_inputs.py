import tempfile
import unittest
from pathlib import Path

import yaml

from workflows.data_foundation.stage_offline_inputs import collect_inputs, relocate
from workflows.data_foundation.workflow.scripts.common.ro_crate_writer import copy_config_into_crate


class TestOfflineInputs(unittest.TestCase):
    def test_collects_only_selected_canonical_files_and_lai(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "canonical"
            soil = canonical / "soil"
            soil.mkdir(parents=True)
            for name in ("sand", "clay", "unused"):
                (soil / f"{name}.nc").write_bytes(b"fixture")
            lai = root / "lai"
            lai.mkdir()
            (lai / "one.h5.gz").write_bytes(b"fixture")
            (lai / "notes.txt").write_text("not an input")
            config = {
                "canonical_reference_products": {"monthly/sand": str(soil / "sand.nc")},
                "selected_variables": [{"source": "soil", "variable": name} for name in ("sand", "clay")],
                "sources": {"soil": {"canonical_reference_dir": str(soil),
                                      "canonical_reference_template": "{variable}.nc",
                                      "variables": {"sand": {}, "clay": {}}}},
                "local_input_paths": {"lai_h5gz": "lai"},
            }
            files, _, _ = collect_inputs(config, project=root, canonical_root=canonical)
            self.assertEqual(len(files), 3)
            self.assertNotIn(soil / "unused.nc", files)
            self.assertEqual(len(set(files.values())), 3)

    def test_relocation_prefers_exact_file_mapping_over_directory(self):
        mapping = {"/old": "relative", "/old/file.nc": "other/file.nc"}
        result = relocate({"input": "/old/file.nc", "parts": ["/old/sub/item", "/older"]}, mapping)
        self.assertEqual(result, {"input": "other/file.nc", "parts": ["relative/sub/item", "/older"]})

    def test_packaged_config_points_to_bundled_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "config.yml"
            source.write_text(yaml.safe_dump({"offline_inputs": {"root": "resources/offline"},
                              "script": "workflows/data_foundation/workflow/scripts/legacy/test.py",
                              "input": "resources/offline/lai/file.gz"}))
            target = copy_config_into_crate(source, root / "crate", Path("config/run.yml"))
            data = yaml.safe_load(target.read_text())
            self.assertEqual(data["script"], "workflow/scripts/legacy/test.py")
            self.assertEqual(data["input"], "resources/offline/lai/file.gz")


if __name__ == "__main__":
    unittest.main()
