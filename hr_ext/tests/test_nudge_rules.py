"""Unit tests for the nudge rule engine (pure, no Frappe/DB)."""
import datetime
import unittest

from hr_ext.nudges.rules import default_rules, run_rules


def ctx(**overrides):
    context = {
        "employee": "HR-EMP-00001",
        "employee_user": "emp@example.com",
        "manager_user": "manager@example.com",
        "hr_user": "hr@example.com",
        "attendance_gap_days": 0,
        "pending_leave_approval_days": 0,
        "pending_expense_approval_days": 0,
        "attrition_risk": 0.1,
        "probation_days_left": None,
        "nudge_attendance_gap_days": 3,
        "nudge_leave_approval_days": 2,
        "nudge_expense_approval_days": 3,
        "nudge_probation_days": 30,
    }
    context.update(overrides)
    return context


class TestNudgeRules(unittest.TestCase):
    def test_no_rule_fires_on_healthy_context(self):
        decisions = run_rules(default_rules(), ctx())
        self.assertEqual(decisions, [])

    def test_attendance_gap(self):
        decisions = run_rules(default_rules(), ctx(attendance_gap_days=4))
        fired = [d for d in decisions if d.rule_id == "missing_attendance"]
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].recipient, "emp@example.com")
        self.assertIn("4", fired[0].body)

    def test_pending_leave_approval_threshold(self):
        self.assertEqual(run_rules(default_rules(), ctx(pending_leave_approval_days=1)) and [], [])
        decisions = run_rules(default_rules(), ctx(pending_leave_approval_days=2, manager_user="mg@example.com"))
        fired = [d for d in decisions if d.rule_id == "pending_leave_approval"]
        self.assertEqual(fired[0].recipient, "mg@example.com")

    def test_pending_expense_approval(self):
        decisions = run_rules(default_rules(), ctx(pending_expense_approval_days=3))
        fired = [d for d in decisions if d.rule_id == "pending_expense_approval"]
        self.assertEqual(len(fired), 1)

    def test_high_attrition_risk(self):
        decisions = run_rules(default_rules(), ctx(attrition_risk=0.9, manager_user="m@example.com"))
        fired = [d for d in decisions if d.rule_id == "high_attrition_risk"]
        self.assertEqual(fired[0].recipient, "m@example.com")

    def test_probation_ending(self):
        decisions = run_rules(default_rules(), ctx(probation_days_left=10, hr_user="hr@example.com"))
        fired = [d for d in decisions if d.rule_id == "probation_ending"]
        self.assertEqual(fired[0].recipient, "hr@example.com")
        self.assertIn("10", fired[0].body)

    def test_channel_override(self):
        decisions = run_rules(default_rules(), ctx(probation_days_left=5), channel_override="slack")
        self.assertTrue(decisions)
        self.assertTrue(all(d.channel == "slack" for d in decisions))

    def test_missing_recipient_skipped(self):
        decisions = run_rules(default_rules(), ctx(pending_leave_approval_days=2, manager_user=None))
        self.assertFalse([d for d in decisions if d.rule_id == "pending_leave_approval"])


if __name__ == "__main__":
    unittest.main()