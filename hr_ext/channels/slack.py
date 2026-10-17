"""Slack Web API adapter (chat.postMessage).

Credentials (settings override, else environment):
    HR_EXT_SLACK_BOT_TOKEN          — xoxb-... bot token
    HR_EXT_SLACK_DEFAULT_CHANNEL    — default target channel (#general)

Network-dependent: NOT exercised in the sandbox; unit tests only assert the
misconfiguration path.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from .base import ChannelAdapter, ChannelError, ChannelMisconfigured, DeliveryResult, require_creds

API_URL = "https://slack.com/api/chat.postMessage"


class SlackChannelAdapter(ChannelAdapter):
    name = "slack"

    def __init__(self, creds: Optional[dict] = None, timeout: float = 15.0):
        self.creds = dict(creds or {})
        self.timeout = timeout

    def _cred(self, key: str) -> Optional[str]:
        return self.creds.get(key) or os.environ.get(key)

    def deliver(self, payload: dict) -> DeliveryResult:
        token = self._cred("HR_EXT_SLACK_BOT_TOKEN")
        default_channel = self._cred("HR_EXT_SLACK_DEFAULT_CHANNEL")
        require_creds({"HR_EXT_SLACK_BOT_TOKEN": token}, "HR_EXT_SLACK_BOT_TOKEN")

        to = payload.get("to") or default_channel
        body = payload.get("body")
        if not to or not body:
            raise ChannelError("Slack deliver() needs 'to' (or a default channel) and 'body'")

        data = json.dumps({"channel": to, "text": body}).encode("utf-8")
        req = urllib.request.Request(
            API_URL,
            data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "hr_ext/0.1"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (intended network call)
                detail = resp.read().decode("utf-8", "replace")
            return DeliveryResult(channel=self.name, ok=True, detail=detail[:500])
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            return DeliveryResult(channel=self.name, ok=False, detail=f"HTTP {exc.code}: {detail}")  # type: ignore[attr-defined]
        except urllib.error.URLError as exc:
            return DeliveryResult(channel=self.name, ok=False, detail=f"URLError: {exc.reason}")