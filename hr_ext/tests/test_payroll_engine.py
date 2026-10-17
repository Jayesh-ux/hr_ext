"""Unit tests for the country payroll rules engine (pure, no Frappe/DB)."""
import os
import unittest

from hr_ext.payroll.engine import (
    compute_social_security,
    compute_tax,
    estimate_salary,
    list_countries,
    load_rule,
    validate_rule,
)


class TestCountryRules(unittest.TestCase):
    def test_known_countries_load(self):
        for country in ("india", "uae", "usa"):
            rule = load_rule(country)
            self.assertEqual(rule["country"], country)
            self.assertTrue(rule["currency"])
            self.assertEqual(validate_rule(rule), [])

    def test_unknown_country_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_rule("narnia")

    def test_list_countries(self):
        countries = list_countries()
        self.assertIn("india", countries)
        self.assertIn("uae", countries)

    def test_india_tax_progressive(self):
        rule = load_rule("india")
        # taxable 15L under the FY 2025-26 new regime:
        # 0-4L@0 + 4-8L@5% (20,000) + 8-12L@10% (40,000) + 12-15L@15% (45,000) = 105,000
        # above the 87A threshold (12L) with no marginal relief -> full slab tax
        total, breakdown = compute_tax(1_500_000, rule)
        self.assertAlmostEqual(total, 105_000 * 1.04, places=2)  # +4% health cess
        self.assertEqual(len(breakdown), 4)

    def test_india_slab_boundaries_match_new_regime(self):
        rule = load_rule("india")
        self.assertEqual([s["up_to"] for s in rule["slabs"]], [400000, 800000, 1200000, 1600000, 2000000, 2400000, None])
        self.assertEqual([s["rate"] for s in rule["slabs"]], [0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3])
        self.assertEqual(rule["standard_exemption"], 75000)

    def test_india_rebate_zero_tax_at_12l(self):
        rule = load_rule("india")
        # slab tax on 12L = 20,000 + 40,000 = 60,000; 87A rebate of 60,000 -> nil
        total, _ = compute_tax(1_200_000, rule)
        self.assertAlmostEqual(total, 0.0, places=2)

    def test_india_rebate_marginal_relief_above_12l(self):
        rule = load_rule("india")
        # taxable 12.1L: slab tax 61,500 but relief caps tax at income above 12L (10,000)
        total, _ = compute_tax(1_210_000, rule)
        self.assertAlmostEqual(total, 10_000 * 1.04, places=2)

    def test_india_zero_tax_below_free_slab(self):
        rule = load_rule("india")
        total, _ = compute_tax(250_000, rule)
        self.assertEqual(total, 0.0)

    def test_india_estimate(self):
        rule = load_rule("india")
        est = estimate_salary(monthly_gross=100_000, rule=rule)
        self.assertEqual(est["periods_per_year"], 12)
        self.assertAlmostEqual(est["annual_gross"], 1_200_000, places=2)
        self.assertAlmostEqual(est["taxable_income"], 1_125_000, places=2)  # less 75,000 standard deduction
        # taxable 11.25L <= 12L -> 87A rebate wipes out income tax
        self.assertAlmostEqual(est["income_tax_annual"], 0.0, places=2)
        # EPF 12% on the 1.8L statutory ceiling
        self.assertAlmostEqual(est["social_security_employee_annual"], 21_600, places=2)
        # ESI does not apply above the Rs 21,000/month gross ceiling
        self.assertAlmostEqual(self._stat(est, "ESI")["employee_annual"], 0.0, places=2)
        # Maharashtra Professional Tax: Rs 200/month above Rs 10,000 gross = Rs 2,400/yr
        self.assertAlmostEqual(est["statutory_deductions_employee_annual"], 2_400, places=2)
        self.assertAlmostEqual(est["net_monthly"], 98_000, places=2)

    @staticmethod
    def _stat(est, name):
        return next(item for item in est["statutory_breakdown"] if item["name"] == name)

    def test_india_esi_applies_below_wage_ceiling(self):
        rule = load_rule("india")
        est = estimate_salary(monthly_gross=20_000, rule=rule)
        esi = self._stat(est, "ESI")
        self.assertTrue(esi["applicable"])
        # 0.75% of Rs 20,000 x 12 = Rs 1,800 employee; employer 3.25% = Rs 7,800
        self.assertAlmostEqual(esi["employee_annual"], 1_800.0, places=2)
        self.assertAlmostEqual(esi["employer_annual"], 7_800.0, places=2)

    def test_india_esi_nil_above_wage_ceiling(self):
        rule = load_rule("india")
        est = estimate_salary(monthly_gross=21_000.01, rule=rule)
        esi = self._stat(est, "ESI")
        self.assertFalse(esi["applicable"])
        self.assertAlmostEqual(esi["employee_annual"], 0.0, places=2)

    def test_india_professional_tax_slabs(self):
        rule = load_rule("india")
        # up to 7,500 -> nil
        self.assertAlmostEqual(self._stat(estimate_salary(7_000, rule), "Professional Tax")["monthly"], 0.0)
        # 7,501-10,000 -> Rs 175/month
        mid = self._stat(estimate_salary(9_000, rule), "Professional Tax")
        self.assertAlmostEqual(mid["monthly"], 175.0, places=2)
        self.assertAlmostEqual(mid["employee_annual"], 2_100.0, places=2)
        # above 10,000 -> Rs 200/month (annual cap Rs 2,500 not reached at 12 x 200)
        high = self._stat(estimate_salary(15_000, rule), "Professional Tax")
        self.assertAlmostEqual(high["employee_annual"], 2_400.0, places=2)
        self.assertEqual(high["jurisdiction"], "Maharashtra")

    def test_statutory_deductions_absent_is_zero(self):
        rule = load_rule("uae")
        est = estimate_salary(monthly_gross=20_000, rule=rule)
        self.assertAlmostEqual(est["statutory_deductions_employee_annual"], 0.0, places=2)
        self.assertEqual(est["statutory_breakdown"], [])

    def test_country_files_record_tax_year_and_source(self):
        for country in ("india", "uae", "usa"):
            rule = load_rule(country)
            self.assertTrue(rule.get("tax_year"), f"{country} missing tax_year")
            self.assertTrue(rule.get("source"), f"{country} missing source")
            self.assertIs(rule.get("illustrative"), True, f"{country} must be marked illustrative")

    def test_uae_no_income_tax(self):
        rule = load_rule("uae")
        total, _ = compute_tax(1_000_000, rule)
        self.assertEqual(total, 0.0)
        employee, employer = compute_social_security(100_000, rule)
        self.assertAlmostEqual(employee, 5_000, places=2)
        self.assertAlmostEqual(employer, 12_500, places=2)

    def test_uae_social_security_conditional(self):
        rule = load_rule("uae")
        # Restricted scheme applies only when explicitly confirmed; default is not applied
        est_unconfirmed = estimate_salary(monthly_gross=10_000, rule=rule, periods_per_year=12, social_security_applies=None)
        self.assertFalse(est_unconfirmed["social_security_applied"])
        self.assertAlmostEqual(est_unconfirmed["social_security_employee_annual"], 0.0, places=2)
        # If confirmed as GCC national, SS is withheld
        est_applied = estimate_salary(monthly_gross=10_000, rule=rule, periods_per_year=12, social_security_applies=True)
        self.assertTrue(est_applied["social_security_applied"])
        self.assertAlmostEqual(est_applied["social_security_employee_annual"], 6_000, places=2)

    def test_usa_social_security_supplemental_on_full_gross(self):
        rule = load_rule("usa")
        salary = estimate_salary(monthly_gross=100_000, rule=rule)
        annual = 1_200_000
        expected_employee = 176_100 * 0.062 + annual * 0.0145
        self.assertAlmostEqual(salary["social_security_employee_annual"], expected_employee, places=2)
        self.assertGreater(salary["income_tax_annual"], 0.0)
        self.assertAlmostEqual(salary["net_monthly_in_base"], salary["net_monthly"] * 83.0, delta=1.0)

    def test_usa_2025_standard_deduction(self):
        rule = load_rule("usa")
        salary = estimate_salary(monthly_gross=8_000, rule=rule)  # $96,000 annual
        self.assertAlmostEqual(salary["standard_exemption"], 15_750, places=2)
        self.assertAlmostEqual(salary["taxable_income"], 96_000 - 15_750, places=2)
        self.assertAlmostEqual(salary["income_tax_annual"], 12_569.00, places=2)
        self.assertAlmostEqual(salary["net_monthly"], 6_340.58, places=2)

    def test_exchange_rate_bit_and_frequency(self):
        rule = load_rule("uae")
        est = estimate_salary(monthly_gross=10_000, rule=rule, periods_per_year=12)
        self.assertAlmostEqual(est["net_monthly_in_base"], est["net_monthly"] * 23.0, places=2)

    def test_format_estimate_shows_fx_source(self):
        from hr_ext.payroll.engine import format_estimate

        rule = load_rule("usa")
        est = estimate_salary(monthly_gross=8_000, rule=rule)
        est["exchange_rate_source"] = "Currency Exchange"
        self.assertIn("FX source: Currency Exchange", format_estimate(est))
        est.pop("exchange_rate_source")
        self.assertNotIn("FX source", format_estimate(est))

    def test_all_country_files_declare_exchange_rate_source(self):
        for country in ("india", "uae", "usa"):
            rule = load_rule(country)
            self.assertTrue(rule.get("exchange_rate_source"), f"{country} missing exchange_rate_source")

    def test_validate_rule_rejects_bad_slab(self):
        bad = {
            "country": "x",
            "currency": "X",
            "slabs": [{"up_to": 100, "rate": 2.0}, {"up_to": 10, "rate": 0.05}],
        }
        problems = validate_rule(bad)
        self.assertIn("slab 0: rate 2.0 outside 0..1", problems)
        self.assertTrue(any("prev" in p for p in problems))


if __name__ == "__main__":
    unittest.main()