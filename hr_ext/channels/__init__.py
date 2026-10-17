"""Channel factory. Maps a channel name to an adapter instance.

Standard channels:

    mock      in-memory outbox (default; no credentials needed)
    whatsapp  Meta WhatsApp Business Cloud (HR_EXT_WHATSAPP_*)
    slack     Slack Web API (HR_EXT_SLACK_*)
    teams     Microsoft Teams incoming webhook (HR_EXT_TEAMS_WEBHOOK_URL)

``get_adapter(name, creds=None)`` passes settings-held credentials (from the
HR Ext Settings DocType via the glue layer) to the adapter; each adapter falls
back to environment variables so it works unchanged on a real Docker host.
"""
from __future__ import annotations

from typing import Dict, Optional

from .base import ChannelAdapter
from .email import EmailChannelAdapter
from .mock import MockChannelAdapter
from .slack import SlackChannelAdapter
from .teams import TeamsChannelAdapter
from .whatsapp import WhatsAppChannelAdapter

BUILTIN = ("mock", "email", "whatsapp", "slack", "teams")


def available_channels() -> list:
    return list(BUILTIN)


def get_adapter(channel: Optional[str], creds: Optional[Dict[str, str]] = None) -> ChannelAdapter:
    name = (channel or "mock").lower()
    if name == "mock":
        return MockChannelAdapter()
    if name == "email":
        return EmailChannelAdapter(sender=(creds or {}).get("_email_sender"))
    if name == "whatsapp":
        return WhatsAppChannelAdapter(creds=creds)
    if name == "slack":
        return SlackChannelAdapter(creds=creds)
    if name == "teams":
        return TeamsChannelAdapter(creds=creds)
    raise ValueError(f"Unknown channel: {channel}")