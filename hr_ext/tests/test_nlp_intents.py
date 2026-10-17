"""Unit tests for the rule-based intent parser (pure, no Frappe/DB)."""
import datetime
import unittest

from hr_ext.nlp import intents


class TestParseLeaveDateRange(unittest.TestCase):
    def setUp(self):
        self.today = datetime.date(2026, 10, 13)  # a Tuesday

    def test_tomorrow(self):
        d = intents.parse_leave_date_range("leave tomorrow", self.today)
        self.assertEqual(d["from_date"], "2026-10-14")
        self.assertEqual(d["to_date"], "2026-10-14")

    def test_for_n_days(self):
        d = intents.parse_leave_date_range("leave for 3 days", self.today)
        self.assertEqual(d["from_date"], "2026-10-14")
        self.assertEqual(d["to_date"], "2026-10-16")

    def test_weekday_range(self):
        d = intents.parse_leave_date_range("leave friday to sunday", self.today)
        self.assertEqual(d["from_date"], "2026-10-16")  # Friday
        self.assertEqual(d["to_date"], "2026-10-18")  # Sunday

    def test_explicit_date(self):
        d = intents.parse_leave_date_range("leave on 2026-11-20", self.today)
        self.assertEqual(d["from_date"], "2026-11-20")

    def test_no_date(self):
        self.assertEqual(intents.parse_leave_date_range("apply leave", self.today), {})


class TestParseIntent(unittest.TestCase):
    def test_leave_apply(self):
        intent = intents.parse("I need leave tomorrow")
        self.assertEqual(intent.action, "leave_apply")
        self.assertEqual(intent.params["from_date"], (datetime.date.today() + datetime.timedelta(days=1)).isoformat())
        self.assertEqual(intent.params["leave_type"], "Casual Leave")

    def test_sick_leave(self):
        intent = intents.parse("i need sick leave tomorrow")
        self.assertEqual(intent.action, "leave_apply")
        self.assertEqual(intent.params["leave_type"], "Sick Leave")

    def test_leave_balance(self):
        intent = intents.parse("how much leave balance do I have")
        self.assertEqual(intent.action, "leave_balance")

    def test_attendance(self):
        intent = intents.parse("mark my attendance for today")
        self.assertEqual(intent.action, "attendance_status")

    def test_expense(self):
        intent = intents.parse("I want to claim an expense")
        self.assertEqual(intent.action, "expense_claim")

    def test_salary(self):
        intent = intents.parse("what is my take home salary")
        self.assertEqual(intent.action, "salary_information")

    def test_fallback(self):
        intent = intents.parse("hello, how are you?")
        self.assertEqual(intent.action, "help")
        self.assertEqual(intent.template_key, "help_response")

    def test_empty(self):
        intent = intents.parse("")
        self.assertEqual(intent.action, "help")

    def test_clean_and_confidence(self):
        intent = intents.parse("   I NEED   LEAVE tomorrow   ")
        self.assertTrue(0.0 <= intent.confidence <= 1.0)
        self.assertEqual(intent.params["from_date"], (datetime.date.today() + datetime.timedelta(days=1)).isoformat())


class TestLlmActionAllowlist(unittest.TestCase):
    """The LLM performs intent classification only; output is allowlisted."""

    def setUp(self):
        from hr_ext.nlp import llm

        self.llm = llm

    def test_known_actions_pass(self):
        for action in self.llm.VALID_ACTIONS:
            self.assertEqual(self.llm.validate_action(action), action)

    def test_prompt_injection_and_unknown_actions_rejected(self):
        for bad in (
            "delete_user",
            "raw_sql",
            "run_payroll",
            "DROP TABLE",
            "leave_apply; rm -rf /",
            "salary_information ",
            "Salary_Information",
            "",
            None,
            123,
            {"action": "leave_apply"},
        ):
            self.assertIsNone(self.llm.validate_action(bad), f"{bad!r} must be rejected")

    def test_allowlist_matches_rule_parser_actions(self):
        # Every action the LLM may return must be one the dispatcher understands.
        parser_actions = {
            "leave_apply",
            "leave_balance",
            "attendance_status",
            "expense_claim",
            "salary_information",
            "help",
        }
        self.assertTrue(self.llm.VALID_ACTIONS <= parser_actions)


if __name__ == "__main__":
    unittest.main()