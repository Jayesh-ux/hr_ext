"""Frappe glue for nudges (feature 4).

Assembles the context dict, evaluates the pure rule engine, persists decisions
to ``Nudge Log`` and dispatches them through the channel adapters. Everything
that requires workers/e-mail is labelled *implemented, untested in sandbox* —
the scheduler cannot run here, so the sweep is invoked directly by tests and
``bench execute``.
"""
from __future__ import annotations

import json
import os

import frappe

from hr_ext.channels import get_adapter
from hr_ext.channels.mock import clear as clear_mock_outbox
from hr_ext.channels.mock import outbox as mock_outbox
from hr_ext.nudges.rules import default_rules, run_rules

SETTINGS_KEYS = (
    "HR_EXT_WHATSAPP_TOKEN",
    "HR_EXT_WHATSAPP_PHONE_ID",
    "HR_EXT_WHATSAPP_BASE_URL",
    "HR_EXT_SLACK_BOT_TOKEN",
    "HR_EXT_SLACK_DEFAULT_CHANNEL",
    "HR_EXT_TEAMS_WEBHOOK_URL",
)


def settings_credentials() -> dict:
    """Credentials held in the HR Ext Settings DocType (env fallbacks in adapters)."""
    creds = {}
    if frappe.db.exists("DocType", "HR Ext Settings"):
        doc = frappe.get_single("HR Ext Settings")
        for key in SETTINGS_KEYS:
            value = getattr(doc, key.lower(), None)
            if value:
                creds[key] = value
    # Inject the Frappe-backed sender for the email channel (no-op unless used).
    creds["_email_sender"] = _email_sender
    return creds


def _email_sender(to: str, subject: str, message: str):
    """Deliver a nudge by e-mail using the site's configured outgoing account.

    Queued by default so it flows through the worker on a real host; set
    ``HR_EXT_EMAIL_NOW=1`` to send synchronously (handy for a delivery test).
    """
    now = os.environ.get("HR_EXT_EMAIL_NOW", "").lower() in ("1", "true", "yes")
    frappe.sendmail(recipients=[to], subject=subject, message=message, now=now)


def mock_enabled() -> bool:
    if frappe.db.exists("DocType", "HR Ext Settings"):
        return bool(frappe.db.get_single_value("HR Ext Settings", "mock_enabled"))
    return True


def _employee_user(employee: str) -> str | None:
    """Recipient for employee-facing nudges: linked User, else an email address."""
    user = frappe.db.get_value("Employee", employee, "user_id")
    if user:
        return user
    row = frappe.db.get_value("Employee", employee, ["company_email", "personal_email"], as_dict=True)
    if row:
        return row.get("company_email") or row.get("personal_email") or None
    return None


def _report_field() -> str | None:
    for field in ("reports_to", "report_to"):
        if frappe.db.has_column("Employee", field):
            return field
    return None


def _manager_user(employee: str) -> str | None:
    field = _report_field()
    if not field:
        return None
    manager = frappe.db.get_value("Employee", employee, field)
    if manager:
        return _employee_user(manager)
    return None


def _on_approved_leave_today(employee: str) -> bool:
    """True when today is covered by an approved leave application."""
    today = frappe.utils.datetime.date.today()
    return bool(
        frappe.db.exists(
            "Leave Application",
            {
                "employee": employee,
                "docstatus": 1,
                "status": ["in", ("Approved", "Sanctioned")],
                "from_date": ["<=", today],
                "to_date": [">=", today],
            },
        )
    )


def _holiday_context(employee: str) -> dict:
    """Return the employee's non-working calendar.

    ``{"weekly_off": <day name or None>, "dates": <set of date>}``. The weekly
    off day is stored on the Holiday List itself (``weekly_off`` field); explicit
    holidays are the ``Holiday`` child rows. Both are treated as non-working.
    Failures (no list, missing ERPNext helper) degrade to "no exclusions".
    """
    empty = {"weekly_off": None, "dates": set()}
    try:
        from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

        name = get_holiday_list_for_employee(employee, raise_exception=False)
    except Exception:
        name = None
    if not name:
        return empty
    try:
        holiday_list = frappe.get_doc("Holiday List", name)
    except Exception:
        return empty
    dates = {frappe.utils.getdate(h.holiday_date) for h in (holiday_list.holidays or [])}
    return {"weekly_off": (holiday_list.weekly_off or None), "dates": dates}


def _is_non_working(day, context: dict) -> bool:
    if context.get("weekly_off") and day.strftime("%A") == context["weekly_off"]:
        return True
    return day in context.get("dates", set())


def _working_days_since(anchor, end, context: dict) -> int:
    """Count working days in ``(anchor, end]`` (anchor exclusive)."""
    import datetime as _dt

    count = 0
    day = anchor + _dt.timedelta(days=1)
    while day <= end:
        if not _is_non_working(day, context):
            count += 1
        day += _dt.timedelta(days=1)
    return count


def _attendance_gap_days(employee: str) -> int | None:
    """Working days since the employee last marked attendance.

    Only working days (excluding the Holiday List's weekly off and holidays)
    count, so a Friday-to-Monday gap is 1, not 3, and weekends/holidays do not
    trigger false nudges. Approved leave today means no attendance is expected,
    so the gap is 0. If the employee has *never* marked attendance we anchor at
    ``date_of_joining`` — an employee who never records attendance is exactly the
    case this nudge should catch. When there is no anchor at all (no records and
    no DOJ) we return ``None`` so the rule does not fire rather than fabricating
    a gap of 0.
    """
    if _on_approved_leave_today(employee):
        return 0
    context = _holiday_context(employee)
    today = frappe.utils.datetime.date.today()
    last = frappe.db.get_value(
        "Attendance",
        {"employee": employee, "docstatus": 1},
        "attendance_date",
        order_by="attendance_date desc",
    )
    if last:
        return max(0, _working_days_since(frappe.utils.getdate(last), today, context))
    doj = frappe.db.get_value("Employee", employee, "date_of_joining")
    if not doj:
        return None
    return max(0, _working_days_since(frappe.utils.getdate(doj), today, context))


def _attrition_risk(employee: str) -> float | None:
    try:
        return frappe.db.get_value("Attrition Risk Score", {"employee": employee}, "score", order_by="scored_on desc")
    except Exception:
        return None


def build_context(employee: str) -> dict:
    """Assemble the standard nudge context for an employee (sweep rules)."""
    settings = frappe.get_single("HR Ext Settings") if frappe.db.exists("DocType", "HR Ext Settings") else None
    probation_end = None
    for field in ("probation_end_date", "scheduled_confirmation_date", "final_confirmation_date"):
        if frappe.db.has_column("Employee", field):
            probation_end = frappe.db.get_value("Employee", employee, field)
            break
    probation_left = (probation_end - frappe.utils.datetime.date.today()).days if probation_end else None
    hr_user = getattr(settings, "nudge_hr_user", None) or "Administrator"
    context = {
        "employee": employee,
        "employee_user": _employee_user(employee),
        "manager_user": _manager_user(employee) or hr_user,
        "hr_user": hr_user,
        "attendance_gap_days": _attendance_gap_days(employee),
        "attrition_risk": _attrition_risk(employee),
        "probation_days_left": probation_left,
        "nudge_attendance_gap_days": getattr(settings, "nudge_attendance_gap_days", 3) or 3,
        "nudge_leave_approval_days": getattr(settings, "nudge_leave_approval_days", 2) or 2,
        "nudge_expense_approval_days": getattr(settings, "nudge_expense_approval_days", 3) or 3,
        "nudge_probation_days": getattr(settings, "nudge_probation_days", 30) or 30,
    }
    return context


def evaluate(employee: str, context_extra: dict | None = None) -> list:
    context = build_context(employee)
    if context_extra:
        context.update(context_extra)
    # HR_EXT_NUDGE_CHANNEL (e.g. "email") pins the delivery channel on a real host;
    # otherwise the sandbox default is mock, and rules keep their own channel.
    env_channel = os.environ.get("HR_EXT_NUDGE_CHANNEL")
    channel = env_channel or ("mock" if mock_enabled() else None)
    return run_rules(default_rules(), context, channel_override=channel)


def dispatch(decisions: list) -> list:
    """Persist every decision and attempt delivery; returns per-decision results."""
    results = []
    for d in decisions:
        log_name = None
        try:
            doc = frappe.get_doc(
                {
                    "doctype": "Nudge Log",
                    "employee": d.meta.get("employee"),
                    "recipient": d.recipient,
                    "nudge_type": d.rule_id,
                    "channel": d.channel,
                    "subject": d.subject,
                    "body": d.body,
                    "status": "queued",
                    "payload": json.dumps(d.meta, default=str),
                }
            )
            doc.insert(ignore_permissions=True)
            log_name = doc.name
        except Exception:
            frappe.log_error(title="hr_ext nudge persist failed", message=frappe.get_traceback())

        try:
            adapter = get_adapter(d.channel, creds=settings_credentials())
            result = adapter.send(d.recipient, d.subject, d.body)
            status = "sent" if result.ok else "failed"
            phase = "implemented, untested here (no workers/scheduler in sandbox)"
            error = result.detail if not result.ok else None
        except Exception as exc:
            status = "failed"
            error = str(exc)
            phase = "implemented, untested here (sandbox)"
        if log_name:
            doc = frappe.get_doc("Nudge Log", log_name)
            doc.status = status
            doc.error = error or (f"delivery {phase}" if status == "queued" else None)
            doc.save(ignore_permissions=True)
        results.append(
            {
                "log": log_name,
                "rule": d.rule_id,
                "recipient": d.recipient,
                "channel": d.channel,
                "status": status,
                "detail": phase,
            }
        )
    return results


def run_schedule() -> dict:
    """Daily sweep: score attrition and emit nudges for every active employee."""
    from hr_ext.analytics.scoring import score_all_employees

    scored = score_all_employees()
    decisions = []
    employees = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name")
    for emp in employees:
        decisions.extend(evaluate(emp))
    dispatch(decisions)
    return {"scored": scored, "employees": len(employees), "decisions": len(decisions)}


# --- test helpers -------------------------------------------------------------
def outbox_snapshot() -> list:
    return mock_outbox()


def reset_test_state() -> None:
    clear_mock_outbox()