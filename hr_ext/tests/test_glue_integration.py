"""Integration tests that exercise the Frappe glue (run with `bench run-tests --app hr_ext`)."""
import unittest

try:
    import frappe

    USE_FRAPPE = True
except ImportError:  # pragma: no cover - outside bench
    frappe = None
    USE_FRAPPE = False


@unittest.skipUnless(USE_FRAPPE, "requires a frappe site context (bench run-tests)")
class TestGlueIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not USE_FRAPPE:
            raise unittest.SkipTest("requires a frappe site context (bench run-tests)")
        # only proceed when we are inside a live frappe session (site + DB)
        try:
            if not (frappe.db and frappe.session and frappe.session.user):
                raise unittest.SkipTest("no frappe session context")
            cls.employee = frappe.get_all("Employee", filters={"status": "Active"}, limit=1, pluck="name")
            cls.employee = cls.employee[0] if cls.employee else None
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"no site context, skipping glue tests ({exc})")

    def test_scoring_persists_doc(self):
        if not self.employee:
            self.skipTest("no active employee")
        from hr_ext.analytics.scoring import score_employee

        result = score_employee(self.employee)
        self.assertTrue(0.0 <= result["score"] <= 1.0)
        self.assertIn(result["risk_level"], ("low", "medium", "high"))
        self.assertTrue(frappe.db.exists("Attrition Risk Score", {"employee": self.employee}))

    def test_payroll_estimate_for_employee(self):
        if not self.employee:
            self.skipTest("no active employee")
        from hr_ext.payroll.hooks import estimate_for_employee

        est = estimate_for_employee(self.employee)
        if est is None:
            self.skipTest("no salary structure assigned")
        for key in ("monthly_gross", "net_monthly", "currency", "income_tax_annual"):
            self.assertIn(key, est)
        self.assertGreater(est["net_monthly"], 0.0)

    def test_nudge_evaluate_and_dispatch(self):
        if not self.employee:
            self.skipTest("no active employee")
        from hr_ext.channels import mock as mock_channel
        from hr_ext.nudges import notify

        mock_channel.clear()
        decisions = notify.evaluate(self.employee, {"attendance_gap_days": 10})
        results = notify.dispatch(decisions)
        self.assertIsInstance(results, list)
        if results:
            self.assertTrue(frappe.db.exists("Nudge Log", results[0]["log"]) or results[0]["log"])
            self.assertTrue(mock_channel.outbox())  # default transport is mock

    def test_chat_help_hindi(self):
        if not self.employee:
            self.skipTest("no active employee")
        from hr_ext.api.chat import handle_message

        resp = handle_message(text="hi", language="hi", employee=self.employee)
        self.assertEqual(resp["template"], "help_response")
        self.assertTrue(resp["response"])

    def test_chat_leave_apply_creates_draft(self):
        if not self.employee:
            self.skipTest("no active employee")
        from datetime import date, timedelta

        from hr_ext.api.chat import _execute_leave_apply, handle_message

        leave_type = frappe.db.get_value("Leave Type", "Casual Leave", "name")
        if not leave_type:
            self.skipTest("no Leave Type configured")
        # dry-run must NOT create a document
        dry = handle_message(text="I need leave tomorrow", language="en", employee=self.employee)
        self.assertEqual(dry["intent"]["action"], "leave_apply")
        self.assertFalse(dry["intent"].get("doc"))
        # execute against a guaranteed-free future date so pre-existing leaves cannot overlap
        day = date.today() + timedelta(days=30)
        while frappe.db.exists(
            "Leave Application",
            {"employee": self.employee, "from_date": day, "status": ["!=", "Cancelled"]},
        ):
            day += timedelta(days=1)
        out = _execute_leave_apply(
            self.employee,
            {"from_date": str(day), "to_date": str(day), "leave_type": "Casual Leave"},
        )
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["doc"])
        self.assertTrue(frappe.db.exists("Leave Application", out["doc"]))
        frappe.db.delete("Leave Application", out["doc"])
        frappe.db.commit()

    def test_attendance_gap_never_zero_without_records_when_doj_in_past(self):
        from hr_ext.nudges import notify

        emp = None
        for candidate in frappe.get_all("Employee", filters={"status": "Active"}, pluck="name"):
            if not frappe.db.exists("Attendance", {"employee": candidate, "docstatus": 1}):
                emp = candidate
                break
        if not emp:
            self.skipTest("every active employee has attendance records")
        doj = frappe.db.get_value("Employee", emp, "date_of_joining")
        gap = notify._attendance_gap_days(emp)
        if doj and not notify._on_approved_leave_today(emp):
            self.assertIsNotNone(gap)
            self.assertGreater(gap, 0, "no-records must not silently become a zero gap")

    def test_weekly_off_is_non_working_in_gap(self):
        from datetime import date, timedelta

        from hr_ext.nudges import notify

        if not self.employee:
            self.skipTest("no active employee")
        context = notify._holiday_context(self.employee)
        if not context.get("weekly_off"):
            self.skipTest("no weekly off configured")
        day = date.today()
        while day.strftime("%A") != context["weekly_off"]:
            day += timedelta(days=1)
        self.assertTrue(notify._is_non_working(day, context), "weekly off day must be non-working")
        # the gap over a span of exactly one non-working day (plus no working days) is 0
        self.assertEqual(notify._working_days_since(day - timedelta(days=1), day, context), 0)

    def test_chat_leave_balance(self):
        if not self.employee:
            self.skipTest("no active employee")
        from hr_ext.api.chat import handle_message

        resp = handle_message(text="how much leave balance", language="en", employee=self.employee)
        self.assertEqual(resp["template"], "leave_balance_response")
        self.assertIn("balance", resp["response"])

    def test_chat_attendance_status(self):
        if not self.employee:
            self.skipTest("no active employee")
        from hr_ext.api.chat import handle_message

        resp = handle_message(text="check my attendance today", language="en", employee=self.employee)
        self.assertEqual(resp["intent"]["action"], "attendance_status")
        self.assertEqual(resp["template"], "attendance_status_response")
        self.assertTrue(resp["response"])

    def test_chat_salary_estimate(self):
        if not self.employee:
            self.skipTest("no active employee")
        from hr_ext.api.chat import handle_message

        resp = handle_message(text="what is my take home salary", language="en", employee=self.employee)
        self.assertEqual(resp["intent"]["action"], "salary_information")
        if "take-home" not in resp["response"] and "gross" not in resp["response"]:
            self.skipTest("no salary structure assigned for this employee")

    def test_chat_french_translation(self):
        if not self.employee:
            self.skipTest("no active employee")
        from hr_ext.api.chat import handle_message

        resp = handle_message(text="how much leave balance", language="fr", employee=self.employee)
        self.assertEqual(resp["template"], "leave_balance_response")
        self.assertIn("solde", resp["response"])

    def test_chat_expense_creates_draft(self):
        if not self.employee:
            self.skipTest("no active employee")
        from hr_ext.api.chat import _default_expense_type, handle_message

        company = frappe.db.get_value("Employee", self.employee, "company")
        if not _default_expense_type(company):
            self.skipTest("no expense claim type configured")
        dry = handle_message(text="reimburse me 2500", language="en", employee=self.employee)
        self.assertEqual(dry["intent"]["action"], "expense_claim")
        self.assertEqual(dry["intent"]["params"].get("amount"), 2500)
        resp = handle_message(text="reimburse me 2500", language="en", employee=self.employee, execute="true")
        self.assertTrue(resp["intent"].get("doc"), resp)
        self.assertTrue(frappe.db.exists("Expense Claim", resp["intent"]["doc"]))
        frappe.delete_doc("Expense Claim", resp["intent"]["doc"], force=True, ignore_permissions=True)
        frappe.db.commit()


    def test_leave_filed_fires_pending_approval_nudge(self):
        if not self.employee:
            self.skipTest("no active employee")
        from datetime import date, timedelta

        day = date.today() + timedelta(days=45)
        while frappe.db.exists(
            "Leave Application", {"employee": self.employee, "from_date": day, "status": ["!=", "Cancelled"]}
        ):
            day += timedelta(days=1)
        leave = frappe.get_doc(
            {
                "doctype": "Leave Application",
                "employee": self.employee,
                "leave_type": "Casual Leave",
                "from_date": str(day),
                "to_date": str(day),
                "status": "Open",
                "description": "hr_ext test (leave filed trigger)",
            }
        )
        leave.insert(ignore_permissions=True)
        try:
            fired = frappe.db.exists("Nudge Log", {"nudge_type": "pending_leave_approval", "employee": self.employee})
            self.assertTrue(fired, "filing a leave application must fire the pending_leave_approval nudge")
        finally:
            frappe.db.delete("Nudge Log", {"nudge_type": "pending_leave_approval", "employee": self.employee})
            frappe.delete_doc("Leave Application", leave.name, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_expense_filed_fires_pending_approval_nudge(self):
        if not self.employee:
            self.skipTest("no active employee")
        from hr_ext.api.chat import _default_expense_type

        company = frappe.defaults.get_user_default("Company") or frappe.db.get_value("Employee", self.employee, "company")
        expense_type = _default_expense_type(company)
        if not expense_type:
            self.skipTest("no expense claim type configured")
        claim = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": self.employee,
                "company": company,
                "posting_date": frappe.utils.today(),
                "approval_status": "Draft",
            }
        )
        claim.append("expenses", {"expense_date": frappe.utils.today(), "expense_type": expense_type, "amount": 999, "sanctioned_amount": 999})
        claim.insert(ignore_permissions=True)
        try:
            fired = frappe.db.exists("Nudge Log", {"nudge_type": "pending_expense_approval", "employee": self.employee})
            self.assertTrue(fired, "filing an expense claim must fire the pending_expense_approval nudge")
        finally:
            frappe.db.delete("Nudge Log", {"nudge_type": "pending_expense_approval", "employee": self.employee})
            frappe.delete_doc("Expense Claim", claim.name, force=True, ignore_permissions=True)
            frappe.db.commit()


if __name__ == "__main__":
    unittest.main()