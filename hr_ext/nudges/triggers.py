"""Frappe document-event triggers for nudges (feature 4).

Fired by ``doc_events`` in hooks.py. Each handler assembles a minimal context
for its own rule and dispatches through the shared pipeline. In HRMS/ERPNext v15
a *pending* leave application / expense claim is a draft (docstatus 0) that is
submitted only after approval, so these handlers are wired to ``after_insert``
(filed) rather than ``on_submit`` (post-approval).

Note: hooks are cached in redis when not in developer mode — run
``bench --site <site> clear-cache`` after changing ``hooks.py``.
"""
from __future__ import annotations

import frappe

from hr_ext.nudges import notify


def _manager_user(employee: str) -> str | None:
    field = next((f for f in ("reports_to", "report_to") if frappe.db.has_column("Employee", f)), None)
    if not field:
        return None
    manager = frappe.db.get_value("Employee", employee, field)
    return frappe.db.get_value("Employee", manager, "user_id") if manager else None


def _doc_age_days(doc) -> int:
    from frappe.utils import date_diff, nowdate

    base = doc.posting_date or doc.creation.date() if hasattr(doc, "creation") else None
    if getattr(doc, "posting_date", None):
        return max(0, date_diff(nowdate(), str(doc.posting_date)))
    return max(0, date_diff(nowdate(), frappe.utils.data.getdate(str(doc.creation)[:10]) if doc.creation else nowdate()))


def on_leave_application_filed(doc, method=None):
    """A leave application was filed and is awaiting approval.

    In HRMS v15 a pending leave application is a *draft* (status "Open",
    docstatus 0); it only becomes docstatus 1 once approved. So this fires on
    ``after_insert`` — the real-time path that nudges the approver the moment
    it is filed (threshold forced to 0). The periodic sweep keeps the age
    threshold so a pending item is not re-nudged every day.
    """
    if doc.status in ("Approved", "Sanctioned", "Rejected", "Cancelled", "On Leave"):
        return
    approver = doc.get("leave_approver") or _manager_user(doc.employee)
    context = {
        "employee": doc.employee,
        "pending_leave_approval_days": _doc_age_days(doc),
        "nudge_leave_approval_days": 0,
        "context_url": "/app/leave-application",
    }
    if approver:
        context["manager_user"] = approver
    decisions = [d for d in notify.evaluate(doc.employee, context) if d.rule_id == "pending_leave_approval"]
    if decisions:
        notify.dispatch(decisions)


def on_expense_claim_filed(doc, method=None):
    """An expense claim was filed and is awaiting approval (real-time nudge).

    Like leave, a pending expense claim is a *draft* in v15 (approval_status
    "Draft"); submission requires an approver to set it to Approved/Rejected
    first. So the real-time trigger fires on ``after_insert``.
    """
    if getattr(doc, "approval_status", None) in ("Approved", "Rejected") or doc.status in ("Approved", "Rejected", "Cancelled"):
        return
    approver = doc.get("expense_approver") or _manager_user(doc.employee)
    context = {
        "employee": doc.employee,
        "pending_expense_approval_days": _doc_age_days(doc),
        "nudge_expense_approval_days": 0,
        "context_url": "/app/expense-claim",
    }
    if approver:
        context["manager_user"] = approver
    decisions = [d for d in notify.evaluate(doc.employee, context) if d.rule_id == "pending_expense_approval"]
    if decisions:
        notify.dispatch(decisions)