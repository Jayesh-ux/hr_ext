"""Frappe glue for the attrition model (feature 3).

Gathers real employee features from HRMS doctypes and persists results into
``Attrition Risk Score``. The model itself (``analytics/model.py``) is pure and
unittest-able; this module only collects features and stores outputs.
"""
from __future__ import annotations

import json

import frappe
from dateutil.relativedelta import relativedelta

from hr_ext.analytics.model import risk_score

ATTENDANCE_LINKED_STATUSES = ("Present", "Half Day")
LOOKBACK_DAYS = 180


def _clamp(value, low, high):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return min(high, max(low, value))


def _attendance_rate(employee: str, start_date: object) -> float | None:
    records = frappe.get_all(
        "Attendance",
        filters={"employee": employee, "docstatus": 1, "attendance_date": [">=", start_date]},
        fields=["status"],
    )
    if not records:
        return None
    present = sum(1 for r in records if r["status"] in ATTENDANCE_LINKED_STATUSES)
    return round(present / len(records), 4)


def _unscheduled_leave_ratio(employee: str, today: object) -> float | None:
    month = relativedelta(days=30)
    recent = frappe.db.count(
        "Leave Application",
        {"employee": employee, "status": ["in", ("Approved", "Sanctioned")], "from_date": [">=", today - month]},
    )
    prior = frappe.db.count(
        "Leave Application",
        {"employee": employee, "status": ["in", ("Approved", "Sanctioned")], "from_date": ["<", today - month]},
    )
    recent = int(recent or 0)
    prior = int(prior or 0)
    if prior == 0 and recent == 0:
        return None
    return round(recent / max(prior, 1), 4)


def _tenure_months(employee: str, today: object) -> int | None:
    doj = frappe.db.get_value("Employee", employee, "date_of_joining")
    if not doj:
        return None
    try:
        delta = (today.date() if hasattr(today, "date") else today) - doj
    except (TypeError, AttributeError):
        return None
    return max(0, int(delta.days / 30.44))


def _performance(employee: str) -> float | None:
    if not frappe.db.exists("DocType", "Appraisal"):
        return None
    try:
        scores = frappe.get_all(
            "Appraisal",
            filters={"employee": employee, "status": ["in", ("Completed", "Submitted")]},
            fields=["total_score"],
        )
    except Exception:
        return None
    if not scores:
        return None
    values = [float(s["total_score"] or 0.0) for s in scores]
    avg = sum(values) / len(values)
    return _clamp(avg / 5.0 if avg > 1 else avg, 0.0, 1.0)


def _salary_hike_pct(employee: str) -> float | None:
    rows = frappe.db.sql(
        """select from_date, base from `tabSalary Structure Assignment`
           where employee=%s and docstatus<2 and base>0 order by from_date desc, creation desc""",
        employee,
        as_dict=True,
    )
    if not rows:
        return None
    latest = rows[0]
    previous = next((r for r in rows[1:] if r["from_date"] < latest["from_date"]), None)
    if not previous or not previous["base"]:
        return None
    return round(((latest["base"] - previous["base"]) / previous["base"]) * 100.0, 2)


def collect_features(employee: str) -> dict:
    today = frappe.utils.datetime.date.today()
    start = today - relativedelta(days=LOOKBACK_DAYS)
    att = _attendance_rate(employee, start)
    leave = _unscheduled_leave_ratio(employee, today)
    tenure = _tenure_months(employee, today)
    perf = _performance(employee)
    hike = _salary_hike_pct(employee)
    return {
        "attendance_rate": att if att is not None else 0.95,
        "unscheduled_leave_ratio": leave if leave is not None else 0.0,
        "tenure_months": tenure if tenure is not None else 0,
        "performance": perf if perf is not None else 0.6,
        "salary_hike_pct": hike if hike is not None else 0.0,
        "_source": {"lookback_days": LOOKBACK_DAYS},
    }


def score_employee(employee: str, weights: dict | None = None, bias: float | None = None) -> dict:
    features = collect_features(employee)
    raw = {k: v for k, v in features.items() if not k.startswith("_")}
    result = risk_score(raw, weights=weights, bias=bias)
    name = _persist(employee, result)
    result["_name"] = name
    return result


def _persist(employee: str, result: dict) -> str:
    existing = frappe.db.get_value("Attrition Risk Score", {"employee": employee}, "name")
    values = {
        "employee": employee,
        "employee_name": frappe.db.get_value("Employee", employee, "employee_name"),
        "scored_on": frappe.utils.today(),
        "score": result["score"],
        "risk_level": result["risk_level"],
        "contributions": json.dumps(result["contributions"]),
        "snapshot": json.dumps(result["features"]),
    }
    if existing:
        doc = frappe.get_doc("Attrition Risk Score", existing)
        doc.update(values)
        doc.save(ignore_permissions=True)
        return doc.name
    doc = frappe.get_doc({"doctype": "Attrition Risk Score", **values})
    doc.insert(ignore_permissions=True)
    return doc.name


def score_all_employees(weights: dict | None = None, bias: float | None = None) -> int:
    """Score every employee; returns how many were scored."""
    employees = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name")
    count = 0
    for emp in employees:
        try:
            score_employee(emp, weights=weights, bias=bias)
            count += 1
        except Exception:
            frappe.log_error(title="hr_ext attrition scoring failed", message=frappe.get_traceback())
    return count