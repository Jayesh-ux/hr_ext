"""Demo data: create the conditions that fire every nudge rule.

Run:

    bench --site <site> execute hr_ext.demo_data.run      # create + sweep + print Nudge Log

or step by step:

    bench --site <site> execute hr_ext.demo_data.create
    bench --site <site> execute hr_ext.tasks.sweep_nudges
    # open /app/nudge-log

``create`` reuses existing employees and creates fresh Leave Application /
Expense Claim drafts each run (so the after_insert triggers fire), and sets a
confirmation date within the probation window. Artifacts are tagged so
``hr_ext.demo_data.cleanup`` can remove them.
"""
from __future__ import annotations

import frappe
from frappe.utils import add_days, today

DEMO_TAG = "hr_ext demo"


def _active_employees(limit: int = 3) -> list[str]:
    return frappe.get_all("Employee", filters={"status": "Active"}, limit=limit, pluck="name")


def _default_company() -> str | None:
    return (
        frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
        or (frappe.get_all("Company", limit=1, pluck="name") or [None])[0]
    )


def _expense_type(company: str | None) -> str | None:
    from hr_ext.api.chat import _default_expense_type

    return _default_expense_type(company)


def fire_pending_leave(employee: str) -> str | None:
    """Insert a Leave Application draft -> after_insert fires pending_leave_approval."""
    if not frappe.db.exists("Leave Type", "Casual Leave"):
        return None
    day = add_days(today(), 60)
    while frappe.db.exists(
        "Leave Application", {"employee": employee, "from_date": day, "status": ["!=", "Cancelled"]}
    ):
        day = add_days(day, 1)
    doc = frappe.get_doc(
        {
            "doctype": "Leave Application",
            "employee": employee,
            "leave_type": "Casual Leave",
            "from_date": day,
            "to_date": day,
            "status": "Open",
            "description": f"{DEMO_TAG}: pending leave approval",
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name


def fire_pending_expense(employee: str, company: str | None) -> str | None:
    """Insert an Expense Claim draft -> after_insert fires pending_expense_approval."""
    expense_type = _expense_type(company)
    if not expense_type:
        return None
    doc = frappe.get_doc(
        {
            "doctype": "Expense Claim",
            "employee": employee,
            "company": company,
            "posting_date": today(),
            "approval_status": "Draft",
        }
    )
    doc.append(
        "expenses",
        {"expense_date": today(), "expense_type": expense_type, "amount": 1234, "sanctioned_amount": 1234},
    )
    doc.insert(ignore_permissions=True)
    return doc.name


def seed_probation(employee: str) -> str | None:
    """Set a confirmation date within the probation window so probation_ending fires."""
    field = None
    for candidate in ("probation_end_date", "scheduled_confirmation_date", "final_confirmation_date"):
        if frappe.db.has_column("Employee", candidate):
            field = candidate
            break
    if not field:
        return None
    frappe.db.set_value("Employee", employee, field, add_days(today(), 15))
    return field


def fire_attrition_nudge(employee: str) -> list:
    """Emit a high_attrition_risk nudge with a forced high score.

    The daily sweep re-scores employees first, so a persisted demo score would be
    overwritten. We instead evaluate the nudge engine with an overridden context
    (score 0.82) so the Nudge Log gets a high_attrition_risk row deterministically.
    """
    from hr_ext.nudges import notify

    decisions = notify.evaluate(employee, {"attrition_risk": 0.82})
    return notify.dispatch(decisions)


def create() -> dict:
    """Create the conditions that fire the bundle/trigger nudge rules."""
    employees = _active_employees(3)
    if not employees:
        return {"ok": False, "error": "no active employees to build demo data on"}

    company = _default_company()
    employee = employees[0]
    summary = {"ok": True, "company": company, "employee": employee, "created": {}}

    # 1. missing_attendance: any active employee with a real gap and no mark fires it (context only)
    summary["created"]["missing_attendance"] = "context only (employee with no attendance records)"

    # 2. pending_leave_approval (after_insert)
    summary["created"]["pending_leave_approval"] = fire_pending_leave(employee)

    # 3. pending_expense_approval (after_insert)
    summary["created"]["pending_expense_approval"] = fire_pending_expense(employee, company)

    # 4. probation_ending (confirmation date within 30 days)
    summary["created"]["probation_ending"] = seed_probation(employee)

    frappe.db.commit()
    return summary


def run() -> dict:
    """create() + sweep + explicit attrition nudge, then return the Nudge Log."""
    created = create()
    from hr_ext.tasks import sweep_nudges

    employee = created.get("employee")
    if employee:
        fire_attrition_nudge(employee)
    sweep = sweep_nudges()
    log = frappe.get_all(
        "Nudge Log",
        fields=["name", "nudge_type", "recipient", "channel", "status"],
        order_by="creation desc",
        limit=25,
    )
    return {"ok": True, "created": created.get("created"), "sweep": sweep, "nudge_log": log}


def cleanup() -> dict:
    """Remove demo artifacts (leave drafts, demo expenses)."""
    removed = {}
    leaves = frappe.get_all("Leave Application", filters={"description": ["like", f"%{DEMO_TAG}%"]}, pluck="name")
    for name in leaves:
        frappe.delete_doc("Leave Application", name, force=True, ignore_permissions=True)
    removed["leave_applications"] = len(leaves)

    demo_expenses = frappe.db.sql(
        "select distinct parent from `tabExpense Claim Detail` where amount=1234", pluck=True
    )
    for name in demo_expenses:
        try:
            frappe.delete_doc("Expense Claim", name, force=True, ignore_permissions=True)
        except Exception:
            pass
    removed["expense_claims"] = len(demo_expenses)
    frappe.db.commit()
    return {"ok": True, "removed": removed}
