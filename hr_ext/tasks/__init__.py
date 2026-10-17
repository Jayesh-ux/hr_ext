"""Scheduler entry points (feature 3 + 4).

The scheduler itself cannot run under this sandbox (proot/non-worker), so these
functions are invoked directly by ``bench --site hr.localhost execute
hr_ext.tasks.<fn>`` and by unit tests. On a real Docker host the same functions
run from ``scheduler_events`` in hooks.py.
"""
from __future__ import annotations

import frappe


def score_attrition() -> dict:
    """Recompute attrition risk for every active employee."""
    from hr_ext.analytics.scoring import score_all_employees

    scored = score_all_employees()
    return {"scored": scored}


def sweep_nudges() -> dict:
    """Evaluate and dispatch nudges for every active employee (mock channel in sandbox)."""
    from hr_ext.nudges import notify

    return notify.run_schedule()


def daily_maintenance() -> dict:
    """One daily job: score attrition, then emit nudges. Wired to scheduler_events."""
    result = {"scoring": 0, "nudges": {}}
    try:
        result["scoring"] = score_attrition()["scored"]
    except Exception:
        frappe.log_error(title="hr_ext daily scoring failed", message=frappe.get_traceback())
    try:
        result["nudges"] = sweep_nudges()
    except Exception:
        frappe.log_error(title="hr_ext daily nudge sweep failed", message=frappe.get_traceback())
    return result