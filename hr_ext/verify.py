"""Host-only verification helpers (run on a real Docker host).

These cover the four things the authoring sandbox could not run: scheduler/worker
execution, a real e-mail delivery, PDF rendering, and nudge routing to a real HR
user. Invoke from ``docker/verify-host.sh`` or directly:

    bench --site <site> execute hr_ext.verify.check_scheduler
"""
from __future__ import annotations

import os

import frappe


def check_scheduler() -> dict:
    """Show the scheduler wiring and whether the scheduler is switched on."""
    try:
        enabled = bool(frappe.db.get_single_value("System Settings", "enable_scheduler"))
    except Exception:
        enabled = None
    return {"scheduler_enabled": enabled, "scheduler_events": frappe.get_hooks("scheduler_events")}


def run_daily_job() -> dict:
    """Execute the scheduled daily job once (scoring + nudge sweep)."""
    from hr_ext.tasks import daily_maintenance

    return daily_maintenance()


def send_test_email(to: str | None = None) -> dict:
    """Deliver one nudge e-mail through the ``email`` channel adapter."""
    to = to or frappe.db.get_value("User", frappe.session.user, "email") or "test@example.com"
    os.environ["HR_EXT_EMAIL_NOW"] = "1"  # synchronous so the test can assert delivery
    from hr_ext.channels import get_adapter
    from hr_ext.nudges import notify

    adapter = get_adapter("email", creds={"_email_sender": notify._email_sender})
    result = adapter.send(to, "hr_ext nudge delivery test", "Test nudge e-mail from hr_ext (feature 4).")
    return result.as_dict()


def render_test_pdf() -> dict:
    """Render a PDF to prove the wkhtmltopdf print pipeline works."""
    from frappe.utils.pdf import get_pdf

    pdf = get_pdf("<h1>hr_ext</h1><p>PDF print pipeline test.</p>")
    return {"pdf_bytes": len(pdf), "ok": len(pdf) > 1000}


def show_nudge_routing() -> dict:
    """Confirm nudges route to a real HR user (not the Administrator fallback)."""
    return {
        "nudge_hr_user": frappe.db.get_single_value("HR Ext Settings", "nudge_hr_user"),
        "default_country": frappe.db.get_single_value("HR Ext Settings", "default_country"),
    }


def fx_evidence(ensure: bool = True) -> dict:
    """Demonstrate every FX resolution path for AED and USD.

    With ``ensure=True`` (default) it temporarily creates ERPNext ``Currency
    Exchange`` records so the ``Currency Exchange`` and inverse paths can be
    observed, then removes them and shows the ``fallback:rule.exchange_rate``
    path. ``base`` (1:1) is always shown. Returns a dict of evidence.
    """
    from hr_ext.payroll.engine import estimate_salary, load_rule
    from hr_ext.payroll.hooks import base_exchange_rate

    evidence = {"base": {}, "currency_exchange": {}, "inverse": {}, "fallback": {}}
    evidence["base"] = dict(zip(("rate", "source"), base_exchange_rate("INR")))
    evidence["base"]["note"] = "same currency, no conversion"

    created = []
    try:
        if ensure:
            for cur, rate in (("AED", 22.67), ("USD", 83.4)):
                existing = frappe.db.get_value(
                    "Currency Exchange",
                    {"from_currency": cur, "to_currency": "INR", "date": frappe.utils.today()},
                    "name",
                )
                if not existing:
                    doc = frappe.get_doc(
                        {
                            "doctype": "Currency Exchange",
                            "from_currency": cur,
                            "to_currency": "INR",
                            "exchange_rate": rate,
                            "date": frappe.utils.today(),
                        }
                    )
                    doc.insert(ignore_permissions=True)
                    created.append(doc.name)
            frappe.db.commit()

        for cur in ("AED", "USD"):
            rate, source = base_exchange_rate(cur)
            evidence["currency_exchange"][cur] = {"rate": rate, "source": source}
            # inverse: store INR->CUR and read CUR->INR
            inv = frappe.db.get_value(
                "Currency Exchange",
                {"from_currency": "INR", "to_currency": cur},
                "name",
            )
            if not inv:
                doc = frappe.get_doc(
                    {
                        "doctype": "Currency Exchange",
                        "from_currency": "INR",
                        "to_currency": cur,
                        "exchange_rate": 1.0 / (22.67 if cur == "AED" else 83.4),
                        "date": frappe.utils.today(),
                    }
                )
                doc.insert(ignore_permissions=True)
                inv = doc.name
            # remove the direct record so only the inverse remains
            direct = frappe.db.get_value(
                "Currency Exchange",
                {"from_currency": cur, "to_currency": "INR"},
                "name",
            )
            if direct:
                frappe.delete_doc("Currency Exchange", direct, force=True, ignore_permissions=True)
            rate, source = base_exchange_rate(cur)
            evidence["inverse"][cur] = {"rate": rate, "source": source}
            frappe.delete_doc("Currency Exchange", inv, force=True, ignore_permissions=True)
            frappe.db.commit()

        for cur in ("AED", "USD"):
            rate, source = base_exchange_rate(cur)
            evidence["fallback"][cur] = {"rate": rate, "source": source}
            rule = load_rule("uae" if cur == "AED" else "usa")
            sample = float(rule.get("exchange_rate", 1.0) or 1.0)
            est = estimate_salary(
                20000.0 if cur == "AED" else 8000.0,
                rule,
                exchange_rate_override=sample,
                social_security_applies=False,
            )
            evidence["fallback"][cur]["rule_sample_rate"] = sample
            evidence["fallback"][cur]["net_in_base"] = est.get("net_monthly_in_base")
    finally:
        for name in created:
            if frappe.db.exists("Currency Exchange", name):
                frappe.delete_doc("Currency Exchange", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    return evidence
