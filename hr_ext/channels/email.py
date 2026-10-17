"""Email channel adapter (feature 4).

Pure adapter: it validates the recipient and delegates the actual send to an
injected ``sender`` callable. The Frappe glue layer injects a sender backed by
``frappe.sendmail`` (see ``hr_ext.nudges.notify``); in unit tests a fake sender
is injected so no network or site is required.
"""
from __future__ import annotations

from typing import Callable, Optional

from .base import ChannelAdapter, ChannelMisconfigured, DeliveryResult


def looks_like_email(value: str) -> bool:
    return bool(value) and "@" in value and "." in value.split("@")[-1]


class EmailChannelAdapter(ChannelAdapter):
    name = "email"

    def __init__(self, sender: Optional[Callable[..., object]] = None):
        self._sender = sender

    def deliver(self, payload: dict) -> DeliveryResult:
        to = payload.get("to") or payload.get("recipient") or ""
        subject = payload.get("subject") or ""
        body = payload.get("body") or ""
        if not self._sender:
            raise ChannelMisconfigured(
                "email channel needs a sender; on a real host it is backed by frappe.sendmail"
            )
        if not looks_like_email(str(to)):
            return DeliveryResult(self.name, False, detail=f"recipient {to!r} is not an email address")
        self._sender(to=to, subject=subject, message=body)
        return DeliveryResult(self.name, True, detail="dispatched via email", meta={"to": to})
