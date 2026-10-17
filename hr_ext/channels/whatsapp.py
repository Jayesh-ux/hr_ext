"""WhatsApp Business Cloud API adapter.

Credentials (override-able per settings; else read from environment):
    HR_EXT_WHATSAPP_TOKEN          — permanent access token
    HR_EXT_WHATSAPP_PHONE_ID       — phone-number-id of the business sender
    HR_EXT_WHATSAPP_BASE_URL       — default https://graph.facebook.com/v18.0

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

DEFAULT_BASE_URL = "https://graph.facebook.com/v18.0"


class WhatsAppChannelAdapter(ChannelAdapter):
    name = "whatsapp"

    def __init__(self, creds: Optional[dict] = None, timeout: float = 15.0):
        self.creds = dict(creds or {})
        self.timeout = timeout

    def _cred(self, key: str) -> Optional[str]:
        return self.creds.get(key) or os.environ.get(key)

    def deliver(self, payload: dict) -> DeliveryResult:
        token = self._cred("HR_EXT_WHATSAPP_TOKEN")
        phone_id = self._cred("HR_EXT_WHATSAPP_PHONE_ID")
        base = self._cred("HR_EXT_WHATSAPP_BASE_URL") or DEFAULT_BASE_URL
        require_creds({"HR_EXT_WHATSAPP_TOKEN": token, "HR_EXT_WHATSAPP_PHONE_ID": phone_id}, "HR_EXT_WHATSAPP_TOKEN", "HR_EXT_WHATSAPP_PHONE_ID")

        to = payload.get("to")
        body = payload.get("body")
        if not to or not body:
            raise ChannelError("WhatsApp deliver() needs 'to' and 'body'")

        url = f"{base}/{phone_id}/messages"
        data = json.dumps(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "text": {"body": body, "preview_url": False},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "hr_ext/0.1",
            },
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