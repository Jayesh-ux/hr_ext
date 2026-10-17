"""Microsoft Teams adapter via an incoming webhook (adaptive-card style JSON).

Credentials (settings override, else environment):
    HR_EXT_TEAMS_WEBHOOK_URL        — incoming webhook URL for your bot

Network-dependent: NOT exercised in the sandbox; unit tests only assert the
misconfiguration path. For a production channel, this is where an official
Azure Bot Service / adaptive card payload would be constructed.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from .base import ChannelAdapter, ChannelError, ChannelMisconfigured, DeliveryResult, require_creds


class TeamsChannelAdapter(ChannelAdapter):
    name = "teams"

    def __init__(self, creds: Optional[dict] = None, timeout: float = 15.0):
        self.creds = dict(creds or {})
        self.timeout = timeout

    def _cred(self, key: str) -> Optional[str]:
        return self.creds.get(key) or os.environ.get(key)

    def deliver(self, payload: dict) -> DeliveryResult:
        webhook = self._cred("HR_EXT_TEAMS_WEBHOOK_URL")
        require_creds({"HR_EXT_TEAMS_WEBHOOK_URL": webhook}, "HR_EXT_TEAMS_WEBHOOK_URL")

        subject = payload.get("subject") or ""
        body = payload.get("body")
        if not body:
            raise ChannelError("Teams deliver() needs 'body'")

        card = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": subject,
            "title": subject,
            "text": body,
        }
        data = json.dumps(card).encode("utf-8")
        req = urllib.request.Request(
            webhook,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "hr_ext/0.1"},
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