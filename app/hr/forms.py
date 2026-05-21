import re
from datetime import date
from flask import request


EMPLOYEE_TYPES = ["Driver", "Staff", "Admin", "Technician", "Supervisor", "Manager"]
DEPARTMENTS = ["Transport", "Logistics", "Admin", "Accounts", "HR", "Maintenance", "Management", "Sales", "Other"]
DESIGNATIONS = [
    "Driver", "Senior Driver", "Supervisor", "Coordinator", "Manager", "Accountant",
    "Cashier", "Admin Staff", "Technician", "Mechanic", "Helper", "Cleaner", "Security", "Other"
]
STATUS_OPTIONS = ["Active", "Inactive", "On Leave", "Terminated"]
GENDER_OPTIONS = ["Male", "Female"]
SHIFT_OPTIONS = ["Morning", "Evening", "Night", "Rotating"]
CONTRACT_TYPE_OPTIONS = ["Permanent", "Contract", "Probation", "Daily Wage"]


REQUIRED_EMPLOYEE_FIELDS = [
    "employee_id", "full_name", "phone_number", "designation",
    "department", "employee_type", "basic_salary", "join_date"
]


def employee_form_data():
    return {
        "employee_id": request.form.get("employee_id", "").strip().upper(),
        "full_name": request.form.get("full_name", "").strip().title(),
        "phone_number": request.form.get("phone_number", "").strip(),
        "email": request.form.get("email", "").strip().lower(),
        "employee_type": request.form.get("employee_type", "").strip(),
        "department": request.form.get("department", "").strip(),
        "designation": request.form.get("designation", "").strip(),
        "gender": request.form.get("gender", "").strip(),
        "shift": request.form.get("shift", "").strip(),
        "contract_type": request.form.get("contract_type", "").strip(),
        "join_date": request.form.get("join_date", "").strip(),
        "basic_salary": request.form.get("basic_salary", "").strip(),
        "ot_rate": request.form.get("ot_rate", "0").strip(),
        "nationality": request.form.get("nationality", "").strip(),
        "iqama_no": request.form.get("iqama_no", "").strip(),
        "passport_no": request.form.get("passport_no", "").strip(),
        "bank_name": request.form.get("bank_name", "").strip(),
        "bank_account": request.form.get("bank_account", "").strip(),
        "iban": request.form.get("iban", "").strip(),
        "emergency_contact": request.form.get("emergency_contact", "").strip(),
        "emergency_name": request.form.get("emergency_name", "").strip(),
        "address": request.form.get("address", "").strip(),
        "remarks": request.form.get("remarks", "").strip(),
        "status": request.form.get("status", "Active").strip(),
    }


def validate_employee_form(form):
    errors = []
    for field in REQUIRED_EMPLOYEE_FIELDS:
        if field == "basic_salary":
            continue
        if not form.get(field):
            label = field.replace("_", " ").title()
            errors.append(f"{label} is required.")

    if not form.get("employee_id"):
        errors.append("Employee ID is required.")
    elif not re.match(r"^[A-Z0-9\-]+$", form["employee_id"]):
        errors.append("Employee ID must contain only letters, numbers, and hyphens.")

    if not form.get("full_name"):
        errors.append("Full name is required.")

    phone = form.get("phone_number", "")
    if not phone:
        errors.append("Phone number is required.")
    elif not re.match(r"^\+?[0-9\s\-]{7,20}$", phone):
        errors.append("Enter a valid phone number.")

    salary_str = form.get("basic_salary", "0")
    try:
        salary = float(salary_str)
        if salary <= 0:
            errors.append("Basic salary must be greater than zero.")
    except ValueError:
        errors.append("Basic salary must be a valid number.")

    join_date = form.get("join_date", "")
    if join_date:
        try:
            from datetime import datetime
            datetime.strptime(join_date, "%Y-%m-%d")
        except ValueError:
            errors.append("Join date must be in YYYY-MM-DD format.")

    return errors
