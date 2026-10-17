"""Unit tests for the channel adapters (mock is exercised; networks asserted as misconfigured)."""
import os
import unittest

from hr_ext.channels import available_channels, get_adapter
from hr_ext.channels import mock as mock_channel
from hr_ext.channels.base import ChannelMisconfigured
from hr_ext.channels.email import EmailChannelAdapter, looks_like_email
from hr_ext.channels.mock import MockChannelAdapter
from hr_ext.channels.slack import SlackChannelAdapter
from hr_ext.channels.teams import TeamsChannelAdapter
from hr_ext.channels.whatsapp import WhatsAppChannelAdapter


class TestEmailChannel(unittest.TestCase):
    def test_sends_via_injected_sender(self):
        sent = []
        adapter = EmailChannelAdapter(sender=lambda to, subject, message: sent.append((to, subject, message)))
        result = adapter.send("emp@example.com", "Subject", "Body")
        self.assertTrue(result.ok)
        self.assertEqual(sent, [("emp@example.com", "Subject", "Body")])

    def test_requires_sender(self):
        with self.assertRaises(ChannelMisconfigured):
            EmailChannelAdapter().send("emp@example.com", "S", "B")

    def test_rejects_non_email_recipient(self):
        adapter = EmailChannelAdapter(sender=lambda **_: None)
        result = adapter.send("not-an-email", "S", "B")
        self.assertFalse(result.ok)

    def test_looks_like_email(self):
        self.assertTrue(looks_like_email("a@b.co"))
        self.assertFalse(looks_like_email("+919999999999"))
        self.assertFalse(looks_like_email("a@b"))


class TestMockChannel(unittest.TestCase):
    def setUp(self):
        mock_channel.clear()

    def test_deliver_records(self):
        adapter = MockChannelAdapter()
        result = adapter.send("emp@example.com", "Subject", "Body")
        self.assertTrue(result.ok)
        outbox = mock_channel.outbox()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0]["to"], "emp@example.com")

    def test_clear(self):
        MockChannelAdapter().send("a", "s", "b")
        mock_channel.clear()
        self.assertEqual(mock_channel.outbox(), [])


class TestMisconfiguredChannels(unittest.TestCase):
    def _scrub(self, *keys):
        saved = {key: os.environ.pop(key, None) for key in keys}

        def restore():
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value
                else:
                    os.environ.pop(key, None)

        self.addCleanup(restore)

    def test_whatsapp_requires_creds(self):
        self._scrub("HR_EXT_WHATSAPP_TOKEN", "HR_EXT_WHATSAPP_PHONE_ID")
        with self.assertRaises(ChannelMisconfigured):
            WhatsAppChannelAdapter().send("+919999999999", "S", "B")

    def test_slack_requires_token(self):
        self._scrub("HR_EXT_SLACK_BOT_TOKEN")
        with self.assertRaises(ChannelMisconfigured):
            SlackChannelAdapter().send("#general", "S", "B")

    def test_teams_requires_webhook(self):
        self._scrub("HR_EXT_TEAMS_WEBHOOK_URL")
        with self.assertRaises(ChannelMisconfigured):
            TeamsChannelAdapter().send("team", "S", "B")


class TestFactory(unittest.TestCase):
    def test_available(self):
        for name in ("mock", "email", "whatsapp", "slack", "teams"):
            self.assertIn(name, available_channels())

    def test_resolution(self):
        self.assertIsInstance(get_adapter("mock"), MockChannelAdapter)
        self.assertIsInstance(get_adapter("whatsapp"), WhatsAppChannelAdapter)
        self.assertIsInstance(get_adapter("email"), EmailChannelAdapter)
        self.assertIsInstance(get_adapter(None), MockChannelAdapter)

    def test_unknown(self):
        with self.assertRaises(ValueError):
            get_adapter("sms")


if __name__ == "__main__":
    unittest.main()