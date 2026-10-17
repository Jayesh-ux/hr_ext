"""Test for dry-run currency fix."""
import unittest

try:
    import frappe

    USE_FRAPPE = True
except ImportError:  # pragma: no cover
    frappe = None
    USE_FRAPPE = False


@unittest.skipUnless(USE_FRAPPE, "requires a frappe site context (bench run-tests)")
class TestDryRunCurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not USE_FRAPPE:
            raise unittest.SkipTest("requires a frappe site context")
        try:
            if not (frappe.db and frappe.session and frappe.session.user):
                raise unittest.SkipTest("no frappe session context")
            cls.employee = frappe.get_all("Employee", filters={"status": "Active"}, limit=1, pluck="name")
            cls.employee = cls.employee[0] if cls.employee else None
        except Exception as exc:  # noqa
            raise unittest.SkipTest(f"no site context, skipping ({exc})")

    def test_expense_dry_run_has_currency(self):
        if not self.employee:
            self.skipTest("no active employee")
        from hr_ext.api import chat

        res = chat.handle_message(text="reimburse me 2500", language="en", execute=False, employee=self.employee)
        intent = res.get("intent", {})
        params = intent.get("params", {})
        self.assertIn("currency", params)
        self.assertNotEqual(str(params.get("currency")), "—")


if __name__ == "__main__":
    unittest.main()
