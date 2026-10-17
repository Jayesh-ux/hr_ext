"""Country payroll rules engine (pure Python — no Frappe dependency).

A declarative, configuration-driven estimator for gross-to-net payroll math
(progressive income tax slabs, social security contributions, currency
conversion). It is a *companion* to ERPNext/HRMS payroll (Salary Structure /
Salary Slip), not a replacement: it powers "what is my take-home" answers in
the conversational layer and annotates salary slips with an estimate.

New countries are added by dropping a JSON file into ``country_data/`` — no
code changes required.
"""
from __future__ import annotations

import json
import os
from typing import Optional

DEFAULT_RULES_DIR = os.path.join(os.path.dirname(__file__), "country_data")
DEFAULT_RULES = {
    "standard_exemption": 0.0,
    "taxable_exclusions": 0.0,
    "health_cess": 0.0,
    "exchange_rate": 1.0,
    "periods_per_year": 12,
    "rebate": {"threshold": 0.0, "max_amount": 0.0},
    "social_security": {
        "employee_rate": 0.0,
        "employer_rate": 0.0,
        "annual_cap": 0.0,
        "supplemental_rate": 0.0,
    },
    # Country-specific statutory deductions (e.g. India ESI, state Professional
    # Tax). Each entry is declarative; see compute_statutory_deductions.
    "statutory_deductions": [],
}
SUPPORTED_FREQUENCIES = ("monthly", "biweekly", "weekly")


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_rule(country: str, rules_dir: Optional[str] = None) -> dict:
    """Load and normalise a country rule dict. Unknown countries raise FileNotFoundError."""
    country_id = (country or "").strip().lower()
    if not country_id:
        raise ValueError("country is required")
    path = os.path.join(rules_dir or DEFAULT_RULES_DIR, f"{country_id}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No payroll rule configured for country: {country_id}")
    rule = _load(path)
    for key, default in DEFAULT_RULES.items():
        if key not in rule:
            rule[key] = default
        elif isinstance(default, dict):
            merged = dict(default)
            merged.update(rule[key] or {})
            rule[key] = merged
    return rule


def list_countries(rules_dir: Optional[str] = None) -> list:
    out = []
    for fn in sorted(os.listdir(rules_dir or DEFAULT_RULES_DIR)):
        if fn.endswith(".json"):
            out.append(fn[: -len(".json")])
    return out


def validate_rule(rule: dict) -> list:
    """Cheap sanity checks on a rule dict; returns a list of problems (empty if OK)."""
    problems = []
    if not rule.get("country"):
        problems.append("missing country")
    if not rule.get("currency"):
        problems.append("missing currency")
    slabs = rule.get("slabs") or []
    if not slabs:
        problems.append("missing slabs")
    prev = 0.0
    for i, slab in enumerate(slabs):
        try:
            rate = float(slab.get("rate", 0.0))
        except (TypeError, ValueError):
            problems.append(f"slab {i}: bad rate")
            continue
        if not (0.0 <= rate <= 1.0):
            problems.append(f"slab {i}: rate {rate} outside 0..1")
        up_to = slab.get("up_to")
        if up_to is not None:
            try:
                up_to = float(up_to)
            except (TypeError, ValueError):
                problems.append(f"slab {i}: bad up_to")
                continue
            if up_to < prev:
                problems.append(f"slab {i}: up_to {up_to} < previous {prev}")
            prev = up_to
    for key, low, high in (("employee_rate", 0.0, 1.0), ("employer_rate", 0.0, 1.0), ("supplemental_rate", 0.0, 1.0)):
        rate = float(rule.get("social_security", {}).get(key, 0.0))
        if not (low <= rate <= high):
            problems.append(f"social_security.{key} outside 0..1")
    return problems


def compute_tax(taxable_income: float, rule: dict) -> tuple:
    """Progressive tax on annual taxable income plus health cess.

    A config-driven rebate (see the ``rebate`` block, e.g. India's section 87A)
    is applied to the slab tax before cess: if taxable income is at or below
    ``threshold`` the slab tax is reduced by up to ``max_amount``; just above the
    threshold a marginal relief caps the tax at the income above the threshold so
    crossing the limit does not create a cliff.

    Returns (total, breakdown) where breakdown is a list of per-slab dicts.
    """
    taxable_income = max(0.0, float(taxable_income))
    slabs = rule.get("slabs") or []
    total = 0.0
    prev = 0.0
    breakdown = []
    for slab in slabs:
        if taxable_income <= prev:
            break
        up_to = slab.get("up_to")
        top = taxable_income if up_to is None else min(taxable_income, float(up_to))
        band = max(0.0, top - prev)
        rate = float(slab.get("rate", 0.0))
        amount = band * rate
        total += amount
        prev = top
        breakdown.append(
            {
                "from": round(prev - band, 2),
                "to": None if up_to is None else round(top, 2),
                "rate": rate,
                "band": round(band, 2),
                "amount": round(amount, 2),
            }
        )
    rebate = rule.get("rebate") or {}
    threshold = float(rebate.get("threshold", 0.0) or 0.0)
    max_amount = float(rebate.get("max_amount", 0.0) or 0.0)
    if threshold > 0 and total > 0:
        if taxable_income <= threshold:
            total = max(0.0, total - max_amount)
        elif max_amount > 0:
            total = min(total, max(0.0, taxable_income - threshold))
    cess = total * float(rule.get("health_cess", 0.0))
    return round(total + cess, 2), breakdown


def compute_social_security(annual_gross: float, rule: dict) -> tuple:
    """Social security contributions. Returns (employee_annual, employer_annual).

    The primary ``employee_rate``/``employer_rate`` apply to earnings up to
    ``annual_cap`` (0 means uncapped); ``supplemental_rate`` (e.g. Medicare in
    the US) applies to the full annual gross.
    """
    gross = max(0.0, float(annual_gross))
    ss = rule.get("social_security", {})
    cap = float(ss.get("annual_cap", 0.0) or 0.0)
    capped = gross if cap <= 0 else min(gross, cap)
    supp = float(ss.get("supplemental_rate", 0.0) or 0.0)
    employee = capped * float(ss.get("employee_rate", 0.0) or 0.0) + gross * supp
    employer = capped * float(ss.get("employer_rate", 0.0) or 0.0) + gross * supp
    return round(employee, 2), round(employer, 2)


def compute_statutory_deductions(monthly_gross: float, periods_per_year: int, rule: dict) -> tuple:
    """Country-specific statutory deductions beyond income tax and social security.

    Config-driven via ``rule["statutory_deductions"]`` (a list). Two kinds are
    supported:

    - ``percent_of_wage``: an employee/employer percentage of gross, optionally
      gated by a monthly ``wage_ceiling_monthly`` (e.g. India ESI applies only
      when monthly gross <= Rs 21,000, else nil).
    - ``monthly_slab``: a fixed monthly amount chosen by a gross slab, with an
      optional ``annual_cap`` (e.g. Maharashtra Professional Tax).

    Returns (employee_annual, employer_annual, breakdown). Empty list -> zeros.
    """
    gross = max(0.0, float(monthly_gross))
    p = int(periods_per_year or rule.get("periods_per_year", 12))
    employee_total = 0.0
    employer_total = 0.0
    breakdown = []
    for item in rule.get("statutory_deductions") or []:
        kind = item.get("kind")
        name = item.get("name")
        if kind == "percent_of_wage":
            ceiling = float(item.get("wage_ceiling_monthly", 0) or 0)
            applicable = not (ceiling > 0 and gross > ceiling)
            employee = gross * p * float(item.get("employee_rate", 0.0) or 0.0) if applicable else 0.0
            employer = gross * p * float(item.get("employer_rate", 0.0) or 0.0) if applicable else 0.0
            breakdown.append(
                {
                    "name": name,
                    "kind": kind,
                    "applicable": applicable,
                    "employee_annual": round(employee, 2),
                    "employer_annual": round(employer, 2),
                }
            )
        elif kind == "monthly_slab":
            amount = 0.0
            for slab in item.get("slabs") or []:
                up_to = slab.get("up_to")
                if up_to is None or gross <= float(up_to):
                    amount = float(slab.get("amount", 0.0) or 0.0)
                    break
            annual = amount * p
            cap = float(item.get("annual_cap", 0.0) or 0.0)
            if cap > 0:
                annual = min(annual, cap)
            breakdown.append(
                {
                    "name": name,
                    "kind": kind,
                    "jurisdiction": item.get("jurisdiction"),
                    "applicable": amount > 0,
                    "monthly": round(amount, 2),
                    "employee_annual": round(annual, 2),
                    "employer_annual": 0.0,
                }
            )
            employee = annual
            employer = 0.0
        else:
            continue
        employee_total += employee
        employer_total += employer
    return round(employee_total, 2), round(employer_total, 2), breakdown


def estimate_salary(
    monthly_gross: float,
    rule: dict,
    periods_per_year: Optional[int] = None,
    exchange_rate_override: Optional[float] = None,
    base_currency: str = "INR",
    social_security_applies: Optional[bool] = None,
) -> dict:
    """Estimate annual/monthly net pay for a monthly gross under a country rule.

    Parameters
    ----------
    monthly_gross : float
        Gross pay per pay period (monthly).
    rule : dict
        Country rule from :func:`load_rule`.
    periods_per_year : int, optional
        Number of pay periods; defaults to ``rule.periods_per_year`` (12).
    exchange_rate_override : float, optional
        Local -> base currency rate; defaults to ``rule.exchange_rate``.
    social_security_applies : bool, optional
        Whether social security is levied at all. Some schemes cover only a
        subset of employees (UAE GPSSA covers GCC nationals only), declared via
        ``social_security.applies_to``. When the rule declares a restricted
        ``applies_to`` and this is left ``None``, the contribution is *not*
        applied (the conservative default for the expatriate majority).
    """
    p = int(periods_per_year or rule.get("periods_per_year", 12))
    monthly_gross = max(0.0, float(monthly_gross))
    annual_gross = monthly_gross * p
    exemptions = float(rule.get("standard_exemption", 0.0)) + float(rule.get("taxable_exclusions", 0.0))
    taxable = max(0.0, annual_gross - exemptions)
    income_tax, tax_breakdown = compute_tax(taxable, rule)
    ss_applies = _resolve_ss_applies(rule, social_security_applies)
    if ss_applies:
        ss_employee, ss_employer = compute_social_security(annual_gross, rule)
    else:
        ss_employee = ss_employer = 0.0
    stat_employee, stat_employer, stat_breakdown = compute_statutory_deductions(monthly_gross, p, rule)
    total_deductions = income_tax + ss_employee + stat_employee
    annual_net = annual_gross - total_deductions
    monthly_net = annual_net / p
    fx = exchange_rate_override if exchange_rate_override is not None else float(rule.get("exchange_rate", 1.0) or 1.0)
    effective_tax_rate = income_tax / annual_gross if annual_gross else 0.0
    cess_rate = float(rule.get("health_cess", 0.0) or 0.0)
    health_cess = income_tax * cess_rate / (1.0 + cess_rate) if cess_rate else 0.0

    return {
        "country": rule.get("country"),
        "currency": rule.get("currency"),
        "base_currency": base_currency,
        "periods_per_year": p,
        "monthly_gross": round(monthly_gross, 2),
        "annual_gross": round(annual_gross, 2),
        "taxable_income": round(taxable, 2),
        "standard_exemption": round(exemptions, 2),
        "income_tax_annual": income_tax,
        "health_cess_annual": round(health_cess, 2),
        "social_security_applied": ss_applies,
        "social_security_employee_annual": ss_employee,
        "social_security_employer_annual": ss_employer,
        "statutory_deductions_employee_annual": stat_employee,
        "statutory_deductions_employer_annual": stat_employer,
        "statutory_breakdown": stat_breakdown,
        "total_deductions_annual": round(total_deductions, 2),
        "net_annual": round(annual_net, 2),
        "net_monthly": round(monthly_net, 2),
        "net_monthly_in_base": round(monthly_net * fx, 2),
        "effective_tax_rate": round(effective_tax_rate, 4),
        "breakdown": tax_breakdown,
    }


def _resolve_ss_applies(rule: dict, requested: Optional[bool]) -> bool:
    """Decide whether social security applies given the rule's ``applies_to``.

    ``applies_to`` empty/unset -> always applies. A restricted scheme with no
    caller answer defaults to *not applying* (do not deduct what may not be due).
    """
    applies_to = (rule.get("social_security") or {}).get("applies_to")
    if not applies_to:
        return True
    if requested is None:
        return False
    return bool(requested)


def format_estimate(est: dict, language: str = "en") -> str:
    """Plain-text summary of an estimate, used by the conversational layer."""
    text = (
        f"{est['net_monthly']:,.2f} {est['currency']} net per month "
        f"(gross {est['monthly_gross']:,.2f} {est['currency']}) for {est['country']}; "
        f"~{est['net_monthly_in_base']:,.2f} {est['base_currency']}."
    )
    source = est.get("exchange_rate_source")
    if source:
        text += f" FX source: {source}."
    return text