import unittest

from workflows.data_foundation.starter_run import select_variables


class TestStarterSelection(unittest.TestCase):
    def setUp(self):
        self.config = {"selected_variables": [{"source": "era5_single_levels", "variable": v} for v in ("t2m", "d2m", "tp")]
                       + [{"source": "carbontracker_co2", "variable": "co2"}],
                       "derived_products": [{"id": key} for key in ("vpd", "co2_annual", "lai")],
                       "canonical_reference_products": {"annual/co2": "inputs/co2.nc"}}

    def test_all_preserves_configuration_without_mutating(self):
        result = select_variables(self.config, "all")
        self.assertEqual(result, self.config)
        self.assertIsNot(result, self.config)

    def test_vpd_resolves_only_necessary_source_variables(self):
        result = select_variables(self.config, "vpd")
        self.assertEqual([x["variable"] for x in result["selected_variables"]], ["t2m", "d2m"])
        self.assertEqual(result["derived_products"], [{"id": "vpd"}])

    def test_bare_co2_selects_final_annual_product(self):
        result = select_variables(self.config, "co2")
        self.assertEqual(result["derived_products"], [{"id": "co2_annual"}])
        self.assertEqual(result["selected_variables"], [])
        self.assertIn("annual/co2", result["canonical_reference_products"])

    def test_explicit_source_co2_does_not_get_suppressed(self):
        result = select_variables(self.config, "carbontracker_co2/co2")
        self.assertEqual(result["derived_products"], [])
        self.assertNotIn("annual/co2", result["canonical_reference_products"])

    def test_bad_or_mixed_all_selection_rejected(self):
        for value in ("all,lai", "vpd,", "invented"):
            with self.assertRaises(ValueError):
                select_variables(self.config, value)


if __name__ == "__main__":
    unittest.main()
