"""Frappe glue for the country payroll engine (feature 2).

Wired by ``hooks.py`` to fire on Salary Slip submission: it annotates the slip
with the configured country-rule estimate as an informational comment. It never
alters payroll amounts — the estimator is a companion to ERPNext payroll, and
the factual (legally binding) figures remain those computed by HRMS.
"""
from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from hr_ext.payroll.engine import estimate_salary, format_estimate, load_rule


def employee_country(employee: str) -> str:
    """Country of the employee, falling back to the HR Ext default setting.

    Checks custom field ``hr_ext_payroll_country`` (rule id like india/uae/usa) first,
    then version-provided ``country`` column on Employee, else HR Ext default.
    """
    country = None
    if frappe.db.has_column("Employee", "hr_ext_payroll_country"):
        country = frappe.db.get_value("Employee", employee, "hr_ext_payroll_country")
    if not country and frappe.db.has_column("Employee", "country"):
        country = frappe.db.get_value("Employee", employee, "country")
    if country:
        country = str(country).strip().lower()
        if country:
            return country
    default_country = frappe.db.get_single_value("HR Ext Settings", "default_country")
    if default_country:
        return str(default_country).strip().lower()
    return "india"


GCC_COUNTRIES = {
    "United Arab Emirates",
    "UAE",
    "Saudi Arabia",
    "Kuwait",
    "Qatar",
    "Bahrain",
    "Oman",
}


# Nationality is read from the shipped Custom Field first, then any
# version-provided column. We warn at most once per process so a missing field
# does not flood the Error Log on every salary slip.
_NATIONALITY_FIELDS = ("hr_ext_nationality", "nationality", "country")
_NATIONALITY_WARNED = False


def _existing_nationality_fields() -> list[str]:
    return [f for f in _NATIONALITY_FIELDS if frappe.db.has_column("Employee", f)]


def employee_nationality(employee: str) -> str | None:
    """Best-effort nationality of an employee, or ``None`` when unknown.

    Reads the shipped Custom Field ``hr_ext_nationality`` first, then any
    version-provided ``nationality``/``country`` column. If none exists, emits a
    single warning per process and degrades safely (returns ``None`` so
    nationality-restricted schemes such as UAE GPSSA do not apply).
    """
    global _NATIONALITY_WARNED
    fields = _existing_nationality_fields()
    if not fields:
        if not _NATIONALITY_WARNED:
            _NATIONALITY_WARNED = True
            frappe.log_error(
                title="hr_ext payroll: no nationality field on Employee",
                message=(
                    "None of the nationality fields "
                    f"{_NATIONALITY_FIELDS} exist on Employee; nationality-restricted "
                    "social security will not apply. Install the hr_ext fixtures "
                    "(Custom Field) to add hr_ext_nationality."
                ),
            )
        return None
    for field in fields:
        try:
            value = frappe.db.get_value("Employee", employee, field)
            if value:
                return value
        except Exception:
            if not _NATIONALITY_WARNED:
                _NATIONALITY_WARNED = True
                frappe.log_error(
                    title="hr_ext payroll nationality lookup failed",
                    message=f"Could not read '{field}' for {employee}: {frappe.get_traceback()}",
                )
    return None


def social_security_applies(employee: str, rule: dict) -> bool | None:
    """Whether a restricted social-security scheme covers this employee.

    Returns ``None`` for unrestricted schemes (engine always applies).
    For restricted schemes (``applies_to``), return ``True`` only if confirmed
    eligible; if nationality is missing or lookup fails, treat as non-national
    and return ``False`` (do not withhold). The missing-field case is warned
    once by :func:`employee_nationality` rather than on every slip.
    """
    applies_to = (rule.get("social_security") or {}).get("applies_to")
    if not applies_to:
        return None
    nationality = employee_nationality(employee)
    if not nationality:
        return False
    if applies_to == "gcc_national":
        return nationality in GCC_COUNTRIES
    return False


def base_exchange_rate(from_currency: str | None, to_currency: str = "INR") -> tuple[float | None, str]:
    """Latest ERPNext ``Currency Exchange`` rate and its source.

    Returns (rate, source) where source is 'Currency Exchange' or
    'fallback:rule.exchange_rate'. Falls back to rule's sample when missing.
    """
    if not from_currency or from_currency == to_currency:
        return 1.0, "base (1:1)"
    rate = frappe.db.get_value(
        "Currency Exchange",
        {"from_currency": from_currency, "to_currency": to_currency},
        "exchange_rate",
        order_by="date desc",
    )
    if rate:
        return float(rate), "Currency Exchange"
    inverse = frappe.db.get_value(
        "Currency Exchange",
        {"from_currency": to_currency, "to_currency": from_currency},
        "exchange_rate",
        order_by="date desc",
    )
    if inverse:
        return 1.0 / float(inverse), "Currency Exchange (inverse)"
    return None, "fallback:rule.exchange_rate"


def estimate_for_employee(employee: str, months_per_year: int | None = None) -> dict | None:
    """Estimate take-home for an employee's current gross pay under their country rule."""
    country = employee_country(employee)
    try:
        rule = load_rule(country)
    except FileNotFoundError:
        return None
    gross = _monthly_gross(employee)
    if not gross:
        return None
    fx, fx_source = base_exchange_rate(rule.get("currency"))
    est = estimate_salary(
        gross,
        rule,
        periods_per_year=months_per_year,
        exchange_rate_override=fx if fx is not None else float(rule.get("exchange_rate", 1.0) or 1.0),
        social_security_applies=social_security_applies(employee, rule),
    )
    est["exchange_rate"] = est.get("net_monthly_in_base") / est["net_monthly"] if est["net_monthly"] else 1.0
    est["exchange_rate_source"] = fx_source if fx is not None else "fallback:rule.exchange_rate"
    return est


def _monthly_gross(employee: str) -> float | None:
    assignment = frappe.db.sql(
        """select base from `tabSalary Structure Assignment`
           where employee=%s and docstatus<2 and base>0
           order by from_date desc, creation desc limit 1""",
        employee,
        as_dict=True,
    )
    if assignment:
        return float(assignment[0]["base"])
    return None


def on_salary_slip_submit(doc, method=None):
    if not doc.employee or not doc.name:
        return
    try:
        gross = float(doc.base_gross_pay or doc.gross_pay or 0.0)
        country = employee_country(doc.employee)
        rule = load_rule(country)
        fx, fx_source = base_exchange_rate(rule.get("currency"))
        est = estimate_salary(
            gross,
            rule,
            social_security_applies=social_security_applies(doc.employee, rule),
            exchange_rate_override=fx if fx is not None else float(rule.get("exchange_rate", 1.0) or 1.0),
        )
        try:
            est["exchange_rate"] = est.get("net_monthly_in_base") / est["net_monthly"] if est["net_monthly"] else 1.0
            est["exchange_rate_source"] = fx_source if fx is not None else "fallback:rule.exchange_rate"
        except Exception:
            pass
        summary = format_estimate(est)
        doc.add_comment(
            "Comment",
            text=f"Country-rule estimate ({country}): {summary} (informational; execute/scheduled hooks untested in sandbox)",
        )
    except Exception:
        frappe.log_error(title="hr_ext payroll estimate annotate failed", message=frappe.get_traceback())