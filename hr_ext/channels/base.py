"""Channel adapter interface (pure Python).

Every messaging transport (WhatsApp, Slack, Teams, Mock) implements
:class:`ChannelAdapter.deliver`. Adapters run standalone for unit tests and
are wired to Frappe only by the glue layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


class ChannelError(Exception):
    """Base error for channel delivery."""


class ChannelMisconfigured(ChannelError):
    """Raised when required credentials/tokens are missing."""


@dataclass
class DeliveryResult:
    channel: str
    ok: bool
    detail: str = ""
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"channel": self.channel, "ok": self.ok, "detail": self.detail, "meta": self.meta}


class ChannelAdapter:
    name = "base"

    def deliver(self, payload: dict) -> DeliveryResult:
        raise NotImplementedError

    def send(self, to: str, subject: str, body: str, meta: Optional[dict] = None) -> DeliveryResult:
        return self.deliver({"to": to, "subject": subject, "body": body, "meta": meta or {}})  # type: ignore[arg-type]


def require_creds(creds: Dict[str, str], *keys: str):
    missing = [k for k in keys if not creds.get(k)]
    if missing:
        raise ChannelMisconfigured(f"Missing credentials for channel: {', '.join(missing)}")