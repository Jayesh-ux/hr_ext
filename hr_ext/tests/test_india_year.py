"""India tax-year label must match the data it claims to describe.

Guards against relabelling: the year in ``tax_year`` must be one of the
independently confirmed regimes, and the slab set must match that regime.

Budget 2026 (Finance Act 2026) made no change to the new-regime slab rates, the
Rs 75,000 standard deduction, or the section 87A rebate, so the FY 2025-26 /
AY 2026-27 figures continue to apply to FY 2026-27 (Tax Year 2026-27 under the
Income-tax Act 2025).
"""
import unittest

from hr_ext.payroll import engine

# Confirmed new-regime slab boundaries (in INR), unchanged from FY 2025-26.
NEW_REGIME_SLABS = [400000, 800000, 1200000, 1600000, 2000000, 2400000, None]
NEW_REGIME_RATES = [0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3]


class TestIndiaYear(unittest.TestCase):
    def test_tax_year_names_confirmed_regimes(self):
        rule = engine.load_rule("india")
        self.assertTrue(rule.get("tax_year"), "missing tax_year")
        # Current year plus the prior confirmed year, both unchanged.
        self.assertIn("FY 2026-27", rule["tax_year"])
        self.assertIn("FY 2025-26", rule["tax_year"])

    def test_year_label_matches_slab_data(self):
        rule = engine.load_rule("india")
        slabs = [s["up_to"] for s in rule["slabs"]]
        rates = [s["rate"] for s in rule["slabs"]]
        self.assertEqual(slabs, NEW_REGIME_SLABS)
        self.assertEqual(rates, NEW_REGIME_RATES)
        # standard deduction unchanged for FY 2026-27
        self.assertEqual(rule["standard_exemption"], 75000)
        self.assertEqual(rule["rebate"]["threshold"], 1200000)
        self.assertEqual(rule["rebate"]["max_amount"], 60000)


if __name__ == "__main__":
    unittest.main()
