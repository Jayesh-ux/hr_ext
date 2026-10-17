"""Rule-based intent parsing for natural-language HR requests (pure Python).

Two layers:
  1. A deterministic keyword/date parser here that runs everywhere.
  2. An optional LLM override (``hr_ext/nlp/llm.py``) that the Frappe API
     layer can consult first when a model endpoint is configured.

Intent kinds supported:
  leave_apply, leave_balance, attendance_status, expense_claim,
  salary_information, help (fallback)
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Optional

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

LEAVE_KEYWORDS = (
    "leave",
    "day off",
    "time off",
    "vacation",
    "holiday",
    "off today",
    "casual leave",
    "sick leave",
    "annual leave",
    "privilege leave",
)
BALANCE_KEYWORDS = ("balance", "remaining", "how many days", "entitled", "draw")
ATTENDANCE_KEYWORDS = ("attendance", "mark my attendance", "check-in", "check in", "punch", "present")
EXPENSE_KEYWORDS = ("expense", "claim", "reimburse", "reimburse me", "bill")
SALARY_KEYWORDS = ("salary", "take home", "take-home", "net pay", "payroll", "payslip", "payout", "gross")

LEAVE_TYPE_HINTS = {
    "sick": "Sick Leave",
    "casual": "Casual Leave",
    "annual": "Privilege Leave",
    "privilege": "Privilege Leave",
}


@dataclass
class Intent:
    action: str
    template_key: str
    confidence: float
    params: dict = field(default_factory=dict)
    raw: str = ""

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "template_key": self.template_key,
            "confidence": self.confidence,
            "params": self.params,
            "raw": self.raw,
        }


def clean(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^\w\s./-]", " ", text)
    return " ".join(text.split())


def _parse_weekday(day_name: str, today: datetime.date) -> datetime.date:
    target = WEEKDAYS[day_name]
    delta = (target - today.weekday()) % 7
    delta = 7 if delta == 0 else delta
    return today + datetime.timedelta(days=delta)


def parse_leave_date_range(text: str, today: Optional[datetime.date] = None) -> dict:
    """Extract a (from, to) date range from leave text.

    Understands: "today", "tomorrow", weekday names, "for N days",
    "<weekday> to <weekday>", and "yyyy-mm-dd" / "dd-mm-yyyy".
    Returns {from_date, to_date} (ISO strings) or {}.
    """
    today = today or datetime.date.today()
    day = datetime.timedelta(days=1)
    t = clean(text)

    date_matches = re.findall(r"(\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}|\d{2}/\d{2}/\d{4})", t)
    if date_matches:
        try:
            if "-" in date_matches[0]:
                parts = date_matches[0].split("-")
                if len(parts[0]) == 4:
                    d = datetime.datetime.strptime(date_matches[0], "%Y-%m-%d").date()
                else:
                    d = datetime.datetime.strptime(date_matches[0], "%d-%m-%Y").date()
            else:
                d = datetime.datetime.strptime(date_matches[0], "%d/%m/%Y").date()
            return {"from_date": d.isoformat(), "to_date": d.isoformat()}
        except ValueError:
            pass

    for n in re.findall(r"for (\d+)\s+days?", t):
        start = today + day
        end = start + datetime.timedelta(days=int(n) - 1)
        return {"from_date": start.isoformat(), "to_date": end.isoformat()}

    named_days = sorted(WEEKDAYS.keys(), key=len, reverse=True)
    present = [name for name in named_days if name in t]

    if "tomorrow" in t:
        return {"from_date": (today + day).isoformat(), "to_date": (today + day).isoformat()}
    if "today" in t:
        return {"from_date": today.isoformat(), "to_date": today.isoformat()}

    if len(present) >= 2:
        d1 = _parse_weekday(present[0], today)
        d2 = _parse_weekday(present[1], today)
        if d2 < d1:
            d2 = d2 + datetime.timedelta(days=7)
        return {"from_date": d1.isoformat(), "to_date": d2.isoformat()}
    if len(present) == 1:
        d1 = _parse_weekday(present[0], today)
        return {"from_date": d1.isoformat(), "to_date": d1.isoformat()}
    return {}


def _has(text: str, keywords) -> bool:
    return any(kw in text for kw in keywords)


def _detect_leave_type(text: str, default: str = "Casual Leave") -> str:
    for token, name in LEAVE_TYPE_HINTS.items():
        if token in text:
            return name
    return default


def parse(text: str, today: Optional[datetime.date] = None) -> Intent:
    """Classify free-text into an Intent. Never raises; falls back to help."""
    raw = text or ""
    t = clean(raw)
    if _has(t, BALANCE_KEYWORDS):
        leave_type = _detect_leave_type(t)
        return Intent("leave_balance", "leave_balance_response", 0.9, {"leave_type": leave_type}, raw)
    if _has(t, LEAVE_KEYWORDS):
        params = parse_leave_date_range(t, today)
        params["leave_type"] = _detect_leave_type(t)
        return Intent("leave_apply", "leave_apply_confirmation", 0.95, params, raw)
    if _has(t, BALANCE_KEYWORDS):
        leave_type = _detect_leave_type(t)
        return Intent("leave_balance", "leave_balance_response", 0.9, {"leave_type": leave_type}, raw)
    if _has(t, ATTENDANCE_KEYWORDS):
        return Intent("attendance_status", "attendance_status_response", 0.9, {}, raw)
    if _has(t, EXPENSE_KEYWORDS):
        params = {}
        match = re.search(r"(\d[\d,]*(?:\.\d+)?)", t)
        if match:
            try:
                params["amount"] = float(match.group(1).replace(",", ""))
            except ValueError:
                pass
        return Intent("expense_claim", "expense_claim_confirmation", 0.85, params, raw)
    if _has(t, SALARY_KEYWORDS):
        return Intent("salary_information", "salary_information_response", 0.85, {}, raw)
    return Intent("help", "help_response", 0.4, {}, raw)