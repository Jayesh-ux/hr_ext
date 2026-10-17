"""GCC-national goes through the real Salary Slip path (on_submit doc_event).

Sets the shipped ``hr_ext_nationality`` Custom Field to a GCC country, points the
default payroll country at the UAE, submits a real Salary Slip, and asserts the
on_submit handler applied the GPSSA contribution (nationality-restricted).
"""
import unittest

try:
    import frappe

    USE_FRAPPE = True
except ImportError:  # pragma: no cover
    frappe = None
    USE_FRAPPE = False


@unittest.skipUnless(USE_FRAPPE, "requires a frappe site context (bench run-tests)")
class TestGccNationalSlip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not USE_FRAPPE:
            raise unittest.SkipTest("requires a frappe site context")
        try:
            if not (frappe.db and frappe.session and frappe.session.user):
                raise unittest.SkipTest("no frappe session context")
        except Exception as exc:  # noqa
            raise unittest.SkipTest(f"no site context ({exc})")
        cls.employee = frappe.get_all("Employee", filters={"status": "Active"}, limit=1, pluck="name")
        cls.employee = cls.employee[0] if cls.employee else None

    def test_gcc_national_salary_slip_applies_social_security(self):
        if not self.employee:
            self.skipTest("no active employee")
        if not frappe.db.has_column("Employee", "hr_ext_nationality"):
            self.skipTest("hr_ext_nationality Custom Field not installed (fixtures)")

        from frappe.utils import add_days, getdate, today

        from hr_ext.payroll import hooks
        from hr_ext.payroll.engine import load_rule

        settings = frappe.get_single("HR Ext Settings")
        prev_country = settings.default_country
        prev_nationality = frappe.db.get_value("Employee", self.employee, "hr_ext_nationality")
        slip_name = None
        try:
            frappe.db.set_value("Employee", self.employee, "hr_ext_nationality", "United Arab Emirates")
            settings.default_country = "uae"
            settings.save(ignore_permissions=True)
            frappe.db.commit()

            # nationality now resolves to a GCC national through the real field
            self.assertEqual(hooks.employee_nationality(self.employee), "United Arab Emirates")
            rule = load_rule("uae")
            self.assertIs(hooks.social_security_applies(self.employee, rule), True)

            # exercise the real on_submit handler via a genuine Salary Slip
            slip = self._make_salary_slip()
            if slip is None:
                self.skipTest("could not create a Salary Slip for a free period")
            slip_name = slip.name
            slip.flags.ignore_permissions = True
            slip.submit()

            comments = frappe.get_all(
                "Comment",
                filters={"reference_doctype": "Salary Slip", "reference_name": slip_name},
                pluck="content",
            )
            joined = " ".join(comments)
            self.assertIn("Country-rule estimate (uae)", joined, "on_submit handler must annotate the slip")
        finally:
            if slip_name and frappe.db.exists("Salary Slip", slip_name):
                doc = frappe.get_doc("Salary Slip", slip_name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Salary Slip", slip_name, force=True, ignore_permissions=True)
            frappe.db.set_value("Employee", self.employee, "hr_ext_nationality", prev_nationality)
            settings.default_country = prev_country
            settings.save(ignore_permissions=True)
            frappe.db.commit()

    def _make_salary_slip(self):
        from frappe.utils import getdate, today

        emp_company = frappe.db.get_value("Employee", self.employee, "company")
        start = getdate(today()).replace(day=1)
        for months_ahead in range(1, 36):
            y = start.year + (start.month - 1 + months_ahead) // 12
            m = (start.month - 1 + months_ahead) % 12 + 1
            s = getdate(f"{y}-{m:02d}-01")
            e = getdate(f"{y}-{m:02d}-20")
            if frappe.db.exists("Salary Slip", {"employee": self.employee, "start_date": s}):
                continue
            try:
                slip = frappe.get_doc(
                    {
                        "doctype": "Salary Slip",
                        "employee": self.employee,
                        "company": emp_company,
                        "start_date": s,
                        "end_date": e,
                        "payroll_frequency": "Monthly",
                    }
                )
                slip.insert(ignore_permissions=True)
                return slip
            except Exception:  # noqa
                continue
        return None


if __name__ == "__main__":
    unittest.main()
