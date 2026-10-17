"""Nudge rule engine (pure Python — no Frappe dependency).

Decides *what* to nudge and *to whom* based on a context dict that the Frappe
glue layer assembles. Rules are declarative-ish plain objects with a pure
``condition(context)`` callable, and decisions are plain ``NudgeDecision``
objects — fully unit-testable with no database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class NudgeDecision:
    rule_id: str
    recipient: str
    channel: str
    subject: str
    body: str
    context_url: Optional[str] = None
    meta: dict = field(default_factory=dict)


@dataclass
class Rule:
    id: str
    subject: str
    body: str
    channel: str
    recipient: str
    condition: Callable[[dict], bool]


def _resolve(recipient_spec: str, context: dict) -> Optional[str]:
    value = context.get(recipient_spec)
    if value in (None, "", "None"):
        return None
    return str(value)


def missing_attendance_condition(context: dict) -> bool:
    return (context.get("attendance_gap_days") or 0) >= int(context.get("nudge_attendance_gap_days", 3))


def pending_leave_approval_condition(context: dict) -> bool:
    return (context.get("pending_leave_approval_days") or 0) >= int(context.get("nudge_leave_approval_days", 2))


def pending_expense_approval_condition(context: dict) -> bool:
    return (context.get("pending_expense_approval_days") or 0) >= int(context.get("nudge_expense_approval_days", 3))


def high_attrition_risk_condition(context: dict) -> bool:
    return float(context.get("attrition_risk") or 0.0) > 0.66


def probation_ending_condition(context: dict) -> bool:
    days_left = context.get("probation_days_left")
    return days_left is not None and 0 < int(days_left) <= int(context.get("nudge_probation_days", 30))


def default_rules() -> List[Rule]:
    """The built-in nudge set. Extensible by adding more Rule instances."""
    return [
        Rule(
            id="missing_attendance",
            subject="Attendance gap detected",
            body="You have not marked attendance for {attendance_gap_days} consecutive day(s). Please record your attendance.",
            channel="mock",
            recipient="employee_user",
            condition=missing_attendance_condition,
        ),
        Rule(
            id="pending_leave_approval",
            subject="Leave application awaiting approval",
            body="A leave application has been pending your approval for {pending_leave_approval_days} day(s).",
            channel="mock",
            recipient="manager_user",
            condition=pending_leave_approval_condition,
        ),
        Rule(
            id="pending_expense_approval",
            subject="Expense claim awaiting approval",
            body="An expense claim has been pending your approval for {pending_expense_approval_days} day(s).",
            channel="mock",
            recipient="manager_user",
            condition=pending_expense_approval_condition,
        ),
        Rule(
            id="high_attrition_risk",
            subject="High attrition risk for a team member",
            body="Employee risk score is {attrition_risk}. Schedule a check-in conversation.",
            channel="mock",
            recipient="manager_user",
            condition=high_attrition_risk_condition,
        ),
        Rule(
            id="probation_ending",
            subject="Probation ending soon",
            body="Probation ends in {probation_days_left} day(s). Confirm confirmation or extension.",
            channel="mock",
            recipient="hr_user",
            condition=probation_ending_condition,
        ),
    ]


def _render_body(rule: Rule, context: dict) -> str:
    params = {k: v for k, v in context.items() if v is not None}
    try:
        return rule.body.format(**params)
    except (KeyError, IndexError):
        return rule.body


def run_rules(rules: List[Rule], context: dict, channel_override: Optional[str] = None) -> List[NudgeDecision]:
    """Evaluate all rules against a context; return the decisions that fired."""
    decisions: List[NudgeDecision] = []
    for rule in rules:
        if not rule.condition(context):
            continue
        recipient = _resolve(rule.recipient, context)
        if not recipient:
            continue
        channel = channel_override or rule.channel
        decisions.append(
            NudgeDecision(
                rule_id=rule.id,
                recipient=recipient,
                channel=channel,
                subject=rule.subject,
                body=_render_body(rule, context),
                context_url=context.get("context_url"),
                meta={
                    "rule_priority": context.get("rule_priority", 100),
                    "employee": context.get("employee"),
                },
            )
        )
    return decisions