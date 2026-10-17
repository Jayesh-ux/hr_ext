"""Conversational layer API (feature 1).

``handle_message`` is the single entry point shared by all channels (WhatsApp,
Slack, Teams, Mock). It:
  1. resolves the employee (explicit ``employee`` or the session user's link),
  2. classifies intent (optional LLM first, rule-based parser as the always-on
     fallback — both are pure and unit-tested),
  3. optionally *executes* the intent against HRMS doctypes,
  4. renders a localised response via the i18n chatbot layer.

Channel transports live in ``hr_ext/channels`` and are wired here through the
channel name; the same handler runs behind a Meta/API/Slack/Teams webhook on a
real host without code changes.
"""
from __future__ import annotations

import frappe
from frappe import _

from hr_ext.i18n import chatbot as i18n
from hr_ext.nlp import intents, llm
from hr_ext.payroll.hooks import estimate_for_employee

TEMPLATES = {
    "leave_apply_confirmation": "Sure {name}, I've applied for your leave from {from_date} to {to_date}.",
    "leave_balance_response": "Your available {leave_type} balance is {balance} days.",
    "attendance_status_response": "Your attendance for today is: {status}.",
    "expense_claim_confirmation": "Expense claim request received for {amount} ({currency}). Draft created as {name}.",
    "salary_information_response": "Your estimated take-home for a monthly gross of {gross} ({currency}) is {net} ({currency}) in {country}, assuming standard deductions.",
    "help_response": "I can help with leave, attendance, expense claims and salary estimates. Try 'I need leave tomorrow'.",
    "employee_not_found": "I couldn't find an employee record linked to your user. Please contact HR.",
    "missing_params": "I understood you, but I'm missing details. Could you clarify your request?",
}

DEFAULT_LEAVE_TYPE = "Casual Leave"


# --------------------------------------------------------------------------- #
# employee resolution
# --------------------------------------------------------------------------- #
def _employee_for_user(user: str | None, employee: str | None = None) -> str | None:
    if employee and frappe.db.exists("Employee", employee):
        return employee
    if user:
        return frappe.db.get_value("Employee", {"user_id": user}, "name")
    return None


def _employee_name(employee: str) -> str:
    return frappe.db.get_value("Employee", employee, "employee_name") or employee


# --------------------------------------------------------------------------- #
# lang / channel helpers
# --------------------------------------------------------------------------- #
def _llm_config() -> dict:
    if not frappe.db.exists("DocType", "HR Ext Settings"):
        return {}
    doc = frappe.get_single("HR Ext Settings")
    enabled = bool(doc.get("llm_enabled"))
    return {
        "enabled": enabled,
        "endpoint": doc.get("llm_endpoint") or "",
        "api_key": doc.get_password("llm_api_key") if doc.get("llm_api_key") else "",
        "model": doc.get("llm_model") or "",
    }


def _classify(text: str) -> intents.Intent:
    cfg = _llm_config()
    if cfg["enabled"] and cfg.get("endpoint"):
        action = llm.classify(text, cfg["endpoint"], cfg.get("api_key"), cfg.get("model"))
        if action in llm.VALID_ACTIONS:
            return intents.Intent(action, f"{action}_confirmation", 0.95, {}, text)
    return intents.parse(text)


def _resolve_template_key(action: str) -> str:
    mapping = {
        "leave_apply": "leave_apply_confirmation",
        "leave_balance": "leave_balance_response",
        "attendance_status": "attendance_status_response",
        "expense_claim": "expense_claim_confirmation",
        "salary_information": "salary_information_response",
        "help": "help_response",
    }
    return mapping.get(action, "help_response")


# --------------------------------------------------------------------------- #
# intent execution
# --------------------------------------------------------------------------- #
def _execute_leave_apply(employee: str, params: dict) -> dict:
    from_date = params.get("from_date")
    to_date = params.get("to_date") or from_date
    leave_type = params.get("leave_type") or DEFAULT_LEAVE_TYPE
    if not frappe.db.exists("Leave Type", leave_type):
        leave_type = DEFAULT_LEAVE_TYPE
    if not from_date:
        return {"ok": False, "template": "missing_params"}
    doc = frappe.get_doc(
        {
            "doctype": "Leave Application",
            "employee": employee,
            "from_date": from_date,
            "to_date": to_date,
            "leave_type": leave_type,
            "posting_date": frappe.utils.today(),
            "description": "Created via the conversational layer (hr_ext).",
        }
    )
    doc.insert(ignore_permissions=True)
    return {
        "ok": True,
        "template": "leave_apply_confirmation",
        "doc": doc.name,
        "params": {
            "name": _employee_name(employee),
            "from_date": from_date,
            "to_date": to_date or from_date,
        },
    }


def _leave_balance(employee: str, leave_type: str) -> float:
    if not frappe.db.exists("Leave Type", leave_type):
        leave_type = DEFAULT_LEAVE_TYPE
    leave_type = _actual_leave_type(leave_type)
    allocated = frappe.get_all(
        "Leave Allocation",
        filters={"employee": employee, "leave_type": leave_type, "docstatus": 1},
        pluck="new_leaves_allocated",
        order_by="from_date desc",
    )
    total = sum(float(a or 0) for a in allocated)
    consumed = frappe.db.sql(
        """select sum(total_leave_days) from `tabLeave Application`
           where employee=%s and leave_type=%s and docstatus=1
           and status in ('Approved','Sanctioned','On Leave')""",
        (employee, leave_type),
    )[0][0] or 0
    return round(float(total) - float(consumed), 2)


def _actual_leave_type(leave_type: str) -> str:
    if frappe.db.exists("Leave Type", leave_type):
        return leave_type
    return DEFAULT_LEAVE_TYPE


def _today_attendance(employee: str) -> str:
    status = frappe.db.get_value(
        "Attendance",
        {"employee": employee, "attendance_date": frappe.utils.today(), "docstatus": 1},
        "status",
    )
    return status or "Not marked"


def _default_expense_type(company: str | None = None) -> str | None:
    if company:
        configured = frappe.get_all(
            "Expense Claim Account",
            filters={"company": company, "default_account": ["is", "set"]},
            pluck="parent",
        )
        if configured:
            return configured[0]
    for name in ("Others", "Travel", "Food", "Calls", "Medical"):
        if frappe.db.exists("Expense Claim Type", name):
            return name
    rows = frappe.get_all("Expense Claim Type", limit=1, pluck="name")
    return rows[0] if rows else None


def _execute_expense_claim(employee: str, params: dict) -> dict:
    amount = params.get("amount")
    if not amount:
        return {"ok": False, "template": "missing_params"}
    company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        companies = frappe.get_all("Company", limit=1, pluck="name")
        company = companies[0] if companies else None
    expense_type = _default_expense_type(company)
    if not expense_type:
        return {"ok": False, "template": "missing_params"}
    doc = frappe.get_doc(
        {
            "doctype": "Expense Claim",
            "employee": employee,
            "company": company,
            "posting_date": frappe.utils.today(),
            "approval_status": "Draft",
        }
    )
    doc.append(
        "expenses",
        {
            "expense_date": frappe.utils.today(),
            "expense_type": expense_type,
            "amount": amount,
            "sanctioned_amount": amount,
        },
    )
    doc.insert(ignore_permissions=True)
    currency = frappe.get_cached_value("Company", company, "default_currency") or "INR"
    return {
        "ok": True,
        "template": "expense_claim_confirmation",
        "doc": doc.name,
        "params": {"amount": amount, "currency": currency, "name": doc.name},
    }


def _execute_salary(employee: str) -> dict:
    est = estimate_for_employee(employee)
    if not est:
        return {"ok": False, "template": "missing_params"}
    return {
        "ok": True,
        "template": "salary_information_response",
        "params": {
            "gross": est["monthly_gross"],
            "net": est["net_monthly"],
            "currency": est["currency"],
            "country": est["country"].title() if est["country"] else "",
        },
        "extra": {"estimate": est},
    }


def _execute(intent: intents.Intent, employee: str | None, run: bool) -> dict:
    action = intent.action
    if action == "leave_apply":
        if not employee:
            return {"ok": False, "template": "employee_not_found"}
        if not run:
            return {
                "ok": True,
                "template": "leave_apply_confirmation",
                "params": {
                    "name": _employee_name(employee),
                    "from_date": intent.params.get("from_date") or "—",
                    "to_date": intent.params.get("to_date") or intent.params.get("from_date") or "—",
                },
                "extra": {"dry_run": True},
            }
        return _execute_leave_apply(employee, intent.params)
    if action == "leave_balance":
        if not employee:
            return {"ok": False, "template": "employee_not_found"}
        leave_type = intent.params.get("leave_type") or DEFAULT_LEAVE_TYPE
        balance = _leave_balance(employee, leave_type)
        return {"ok": True, "template": "leave_balance_response", "params": {"leave_type": leave_type, "balance": balance}}
    if action == "attendance_status":
        if not employee:
            return {"ok": False, "template": "employee_not_found"}
        return {"ok": True, "template": "attendance_status_response", "params": {"status": _today_attendance(employee)}}
    if action == "expense_claim":
        if not employee:
            return {"ok": False, "template": "employee_not_found"}
        if not run:
            company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
            if not company:
                companies = frappe.get_all("Company", limit=1, pluck="name")
                company = companies[0] if companies else None
            currency = frappe.get_cached_value("Company", company, "default_currency") if company else "INR"
            return {
                "ok": True,
                "template": "expense_claim_confirmation",
                "params": {"amount": intent.params.get("amount") or "—", "currency": currency or "—", "name": "(dry-run)"},
            }
        return _execute_expense_claim(employee, intent.params)
    if action == "salary_information":
        if not employee:
            return {"ok": False, "template": "employee_not_found"}
        return _execute_salary(employee)
    return {"ok": True, "template": "help_response", "params": {}}


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def handle_message(text, language="en", channel="mock", execute=False, user=None, employee=None):
    """Process one natural-language message and return a localised reply."""
    execute = str(execute).lower() in ("1", "true", "yes")
    employee = _employee_for_user(user or frappe.session.user, employee)
    intent = _classify(text or "")
    outcome = _execute(intent, employee, run=execute)
    template = outcome.get("template") or _resolve_template_key(intent.action)
    params = outcome.get("params") or {}
    response = i18n.render(TEMPLATES.get(template, template), params, language or "en")
    payload = intent.as_dict()
    for key in ("doc", "extra", "params"):
        if outcome.get(key) is not None:
            payload[key] = outcome[key]
    return {
        "intent": payload,
        "response": response,
        "template": template,
        "language": language or "en",
        "channel": channel or "mock",
        "employee": employee,
    }


@frappe.whitelist()
def available_channels():
    from hr_ext.channels import available_channels as _available

    return {"channels": _available()}


@frappe.whitelist()
def leave_balance(employee=None, leave_type=None):
    employee = _employee_for_user(frappe.session.user, employee)
    if not employee:
        frappe.throw(_("No employee record linked to your user."))
    return {
        "employee": employee,
        "leave_type": (leave_type or DEFAULT_LEAVE_TYPE),
        "balance": _leave_balance(employee, leave_type or DEFAULT_LEAVE_TYPE),
    }