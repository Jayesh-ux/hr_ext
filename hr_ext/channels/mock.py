"""Mock channel — records deliveries in memory; never touches the network.

Used as the default transport so the platform is fully exerciseable without
external credentials, and by Nudge/chat tests to assert on what was "sent".
"""
from __future__ import annotations

from typing import List

from .base import ChannelAdapter, DeliveryResult

_outbox: List[dict] = []


class MockChannelAdapter(ChannelAdapter):
    name = "mock"

    def deliver(self, payload: dict) -> DeliveryResult:
        record = {
            "channel": self.name,
            "to": payload.get("to"),
            "subject": payload.get("subject"),
            "body": payload.get("body"),
            "meta": payload.get("meta") or {},
        }
        _outbox.append(record)
        return DeliveryResult(channel=self.name, ok=True, detail=f"Recorded {len(_outbox)} messages", meta=record)


def outbox() -> List[dict]:
    return list(_outbox)


def clear() -> None:
    _outbox.clear()