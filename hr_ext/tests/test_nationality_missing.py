"""Nationality-restricted social security: missing and non-GCC cases.

Stock ``Employee`` has no nationality column, so hr_ext ships the
``hr_ext_nationality`` Custom Field (fixtures). When the value is absent the
restricted scheme must NOT apply (we never withhold without confirmation), and a
non-GCC national must also be excluded.
"""
import unittest

try:
    import frappe

    USE_FRAPPE = True
except ImportError:  # pragma: no cover
    frappe = None
    USE_FRAPPE = False


@unittest.skipUnless(USE_FRAPPE, "requires a frappe site context (bench run-tests)")
class TestNationalityMissing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not USE_FRAPPE:
            raise unittest.SkipTest("requires a frappe site context")
        try:
            if not (frappe.db and frappe.session and frappe.session.user):
                raise unittest.SkipTest("no frappe session context")
        except Exception as exc:  # noqa
            raise unittest.SkipTest(f"no site context ({exc})")
        employees = frappe.get_all("Employee", filters={"status": "Active"}, limit=1, pluck="name")
        cls.employee = employees[0] if employees else None

    def test_social_security_applies_when_nationality_missing(self):
        from hr_ext.payroll import engine, hooks

        if not self.employee:
            self.skipTest("no active employee")
        if not frappe.db.has_column("Employee", "hr_ext_nationality"):
            self.skipTest("hr_ext_nationality Custom Field not installed (fixtures)")

        rule = engine.load_rule("uae")
        prev = frappe.db.get_value("Employee", self.employee, "hr_ext_nationality")
        try:
            frappe.db.set_value("Employee", self.employee, "hr_ext_nationality", None)
            self.assertIsNone(hooks.employee_nationality(self.employee))
            self.assertIs(hooks.social_security_applies(self.employee, rule), False)

            frappe.db.set_value("Employee", self.employee, "hr_ext_nationality", "India")
            self.assertIs(hooks.social_security_applies(self.employee, rule), False)
        finally:
            frappe.db.set_value("Employee", self.employee, "hr_ext_nationality", prev)
            frappe.db.commit()

    def test_unrestricted_scheme_needs_no_nationality(self):
        from hr_ext.payroll import engine, hooks

        rule = engine.load_rule("india")
        # India has no ``applies_to`` -> engine always applies (None == unrestricted)
        self.assertIsNone(hooks.social_security_applies(self.employee or "x", rule))


if __name__ == "__main__":
    unittest.main()
