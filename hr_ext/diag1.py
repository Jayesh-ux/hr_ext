import frappe

def run():
    out = {}
    roles = ["HR Manager","HR User","Leave Approver","Expense Approver","Accounts User","Accounts Manager","Employee","Employee Self Service","System Manager","Interviewer","Recruiter"]
    out["roles"] = {r: bool(frappe.db.exists("Role", r)) for r in roles}
    emp_fields = [f.fieldname for f in frappe.get_meta("Employee").fields]
    out["employee_fields"] = [f for f in ["user_id","leave_approver","expense_approver","reports_to","holiday_list","date_of_joining","status","company","department","designation","employment_type","hr_ext_nationality","scheduled_confirmation_date","final_confirmation_date","gender","date_of_birth","branch","grade","default_shift"] if f in emp_fields]
    out["employee_missing"] = [f for f in ["leave_approver","expense_approver","hr_ext_nationality"] if f not in emp_fields]
    out["job_applicant_fields"] = [f.fieldname for f in frappe.get_meta("Job Applicant").fields]
    out["leave_type"] = frappe.get_all("Leave Type", pluck="name")
    out["holiday_lists"] = frappe.get_all("Holiday List", fields=["name","from_date","to_date","weekly_off"])
    out["salary_structures"] = frappe.get_all("Salary Structure", fields=["name","company"])
    out["designation"] = frappe.get_all("Designation", pluck="name")
    out["department"] = frappe.get_all("Department", pluck="name")
    out["employment_type"] = frappe.get_all("Employment Type", pluck="name")
    out["salary_components"] = frappe.get_all("Salary Component", fields=["name","type"])
    out["expense_claim_type"] = frappe.get_all("Expense Claim Type", pluck="name")
    out["job_opening_fields"] = [f.fieldname for f in frappe.get_meta("Job Opening").fields]
    out["allow_impersonation_setting"] = frappe.db.get_single_value("System Settings", "allow_impersonation") if "allow_impersonation" in [f.fieldname for f in frappe.get_meta("System Settings").fields] else "NO_FIELD"
    return out
