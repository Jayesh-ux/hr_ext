"""Attrition analytics API (feature 3) — feeds the desk dashboard page."""
from __future__ import annotations

import frappe


@frappe.whitelist()
def overview(recompute=False):
    """Return a summary plus the latest risk score per employee.

    ``recompute`` triggers scoring of every active employee before reading.
    """
    if str(recompute).lower() in ("1", "true", "yes"):
        from hr_ext.tasks import score_attrition

        score_attrition()

    records = frappe.get_all(
        "Attrition Risk Score",
        fields=["employee", "employee_name", "score", "risk_level", "scored_on", "modified"],
        order_by="scored_on desc, modified desc",
    )
    rows = {}
    for rec in records:
        rows.setdefault(rec["employee"], {"employee_name": rec.get("employee_name"), "score": rec["score"], "risk_level": rec["risk_level"], "scored_on": rec["scored_on"]})
    seen = [{"employee": e, **v} for e, v in rows.items()]

    summary = {"total": len(seen), "low": 0, "medium": 0, "high": 0}
    for row in seen:
        level = row["risk_level"] or "low"
        if level in ("high", "medium", "low"):
            summary[level] += 1
    return {
        "summary": summary,
        "rows": [
            {"employee": r["employee"], "employee_name": r.get("employee_name") or r["employee"], "score": r["score"], "risk_level": r["risk_level"], "scored_on": r["scored_on"]}
            for r in seen
        ],
        "hint": "Run 'bench --site hr.localhost execute hr_ext.tasks.score_attrition' to (re)compute scores." if not seen else None,
    }


@frappe.whitelist()
def scores_by_team(company=None, department=None) -> list:
    """Per-employee latest scores, optionally filtered, for finer dashboards."""
    filters = {}
    if company:
        filters["company"] = company
    if department:
        filters["department"] = department
    employees = frappe.get_all("Employee", filters=filters, or_filters=None, pluck="name")  # keep simple
    out = []
    for emp in employees:
        rec = frappe.db.get_value(
            "Attrition Risk Score",
            {"employee": emp},
            ["score", "risk_level", "scored_on"],
            order_by="scored_on desc, modified desc",
        )
        if rec:
            out.append({"employee": emp, "score": rec[0], "risk_level": rec[1], "scored_on": str(rec[2])})
    return out