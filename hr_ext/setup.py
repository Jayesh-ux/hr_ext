"""One-time site provisioning for hr_ext (used by the Docker init job).

Frappe glue only: reads settings and writes the single ``HR Ext Settings``
document. Idempotent — safe to re-run.

Run:
    bench --site <site> execute hr_ext.setup.configure
"""
from __future__ import annotations

import os

import frappe

HR_ROLES = ("HR Manager", "HR User", "System Manager")


def _first_hr_user() -> str | None:
    rows = frappe.db.sql(
        """
        select hr.parent
        from `tabHas Role` hr
        join `tabUser` u on u.name = hr.parent
        where hr.role in %(roles)s
          and u.enabled = 1
          and u.name not in ('Administrator', 'Guest')
        order by field(hr.role, 'HR Manager', 'HR User', 'System Manager')
        limit 1
        """,
        {"roles": HR_ROLES},
    )
    return rows[0][0] if rows else None


def configure():
    """Point nudges at a real HR user and set payroll defaults.

    Environment variables (all optional):
        HR_EXT_NUDGE_HR_USER   user/email that should receive HR nudges
        HR_EXT_DEFAULT_COUNTRY payroll country id (e.g. ``india``)
    """
    settings = frappe.get_single("HR Ext Settings")

    desired_hr_user = os.environ.get("HR_EXT_NUDGE_HR_USER") or settings.nudge_hr_user
    if not desired_hr_user or desired_hr_user == "Administrator":
        desired_hr_user = _first_hr_user() or settings.nudge_hr_user or "Administrator"
    if not frappe.db.exists("User", desired_hr_user):
        frappe.throw(f"HR_EXT_NUDGE_HR_USER {desired_hr_user!r} is not an existing user")
    settings.nudge_hr_user = desired_hr_user

    country = os.environ.get("HR_EXT_DEFAULT_COUNTRY")
    if country:
        settings.default_country = country

    settings.save(ignore_permissions=True)  # single doctype; Administrator job
    frappe.db.commit()
    result = {"nudge_hr_user": settings.nudge_hr_user, "default_country": settings.default_country}
    print(f"[hr_ext.setup.configure] {result}")
    return result
