"""Unit tests for the chatbot i18n layer (pure, no Frappe/DB)."""
import unittest

from hr_ext.i18n import chatbot

LEAVE = "Sure {name}, I've applied for your leave from {from_date} to {to_date}."
BALANCE = "Your available {leave_type} balance is {balance} days."


class TestChatbotI18n(unittest.TestCase):
    def test_languages(self):
        langs = chatbot.list_languages()
        self.assertIn("en", langs)
        self.assertIn("hi", langs)
        self.assertIn("fr", langs)

    def test_en_is_pass_through(self):
        self.assertEqual(chatbot.translate_template(LEAVE, "en"), LEAVE)
        self.assertEqual(chatbot.translate_template(LEAVE), LEAVE)

    def test_hindi_translation(self):
        self.assertNotEqual(chatbot.translate_template(LEAVE, "hi"), LEAVE)
        self.assertIn("छुट्टी", chatbot.translate_template(LEAVE, "hi"))

    def test_french_translation(self):
        self.assertNotEqual(chatbot.translate_template(LEAVE, "fr"), LEAVE)
        self.assertIn("congé", chatbot.translate_template(LEAVE, "fr"))

    def test_missing_language_falls_back(self):
        self.assertEqual(chatbot.translate_template(LEAVE, "zz"), LEAVE)

    def test_render_fills_placeholders_after_translation(self):
        out = chatbot.render(LEAVE, {"name": "Arjun", "from_date": "2026-10-14", "to_date": "2026-10-14"}, "hi")
        self.assertNotIn("from_date", out)
        self.assertIn("2026-10-14", out)

    def test_safe_render_keeps_unknown_placeholders(self):
        out = chatbot.render(BALANCE, {"balance": "5"}, "fr")
        self.assertIn("{leave_type}", out)  # not supplied -> preserved verbatim
        self.assertIn("5", out)

    def test_render_en(self):
        out = chatbot.render(LEAVE, {"name": "Priya", "from_date": "2026-10-14", "to_date": "2026-10-15"}, "en")
        self.assertEqual(out, "Sure Priya, I've applied for your leave from 2026-10-14 to 2026-10-15.")


if __name__ == "__main__":
    unittest.main()