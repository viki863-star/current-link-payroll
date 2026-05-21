import os
from datetime import date, datetime
from pathlib import Path
from io import BytesIO
import base64

from flask import (
    current_app, flash, redirect, render_template, request,
    send_file, session, url_for, jsonify
)
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from ..database import open_db
from ..routes import (
    _login_required, _audit_log, _touch_admin_workspace, _current_month_value,
    ValidationError, _parse_decimal, _normalize_month, _next_month_value,
    _advance_summary, _outstanding_advance, _timesheet_total_for_month,
    _calculate_salary_preview, _default_salary_form, _salary_form_from_row,
    _salary_preview_from_row, format_month_label, _driver_month_calendar,
    _timesheet_month_summary, _driver_kata_month_data,
    SALARY_MODE_OPTIONS, PAYMENT_SOURCES
)
from . import hr_bp
from .forms import (
    employee_form_data, validate_employee_form,
    EMPLOYEE_TYPES, DEPARTMENTS, DESIGNATIONS, STATUS_OPTIONS,
    GENDER_OPTIONS, SHIFT_OPTIONS, CONTRACT_TYPE_OPTIONS
)
from .services import (
    migrate_drivers_to_employees, save_employee_photo,
    employee_search_filter, next_employee_id,
    employee_departments, employee_types
)


def ensure_employees_table():
    db = open_db()
    try:
        migrate_drivers_to_employees(db)
    except Exception:
        pass


def _fetch_employee(db, employee_id):
    return db.execute(
        "SELECT * FROM employees WHERE employee_id = ?",
        (employee_id.strip().upper(),),
    ).fetchone()


def _employee_photo_url(app, employee):
    if not employee:
        return None
    if employee.get("photo_data") and employee.get("photo_content_type"):
        return f"data:{employee['photo_content_type']};base64,{employee['photo_data']}"
    return None


# ── HR Dashboard ────────────────────────────────────────────────

@hr_bp.route("/hr")
@_login_required("admin")
def hr_dashboard():
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    employees = db.execute(
        "SELECT employee_id, full_name, status FROM employees ORDER BY full_name"
    ).fetchall()

    total = len(employees)
    active = sum(1 for e in employees if (e["status"] or "").lower() == "active")
    inactive = total - active

    stored_this_month = db.execute(
        "SELECT COUNT(*) AS c FROM salary_store WHERE salary_month = ?",
        (_current_month_value(),),
    ).fetchone()["c"] or 0

    advances_pending = db.execute(
        "SELECT COUNT(*) AS c FROM driver_transactions WHERE txn_type IN ('advance','loan')"
    ).fetchone()["c"] or 0

    return render_template(
        "hr/dashboard.html",
        total=total,
        active_count=active,
        inactive_count=inactive,
        stored_this_month=stored_this_month,
        advances_pending=advances_pending,
    )


# ── Employee List ────────────────────────────────────────────────

@hr_bp.route("/hr/employees")
@_login_required("admin")
def employee_list():
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    department_filter = request.args.get("department", "").strip()
    employee_type_filter = request.args.get("type", "").strip()

    where_sql, params = employee_search_filter(query, status_filter, department_filter, employee_type_filter)

    employees = db.execute(
        f"""
        SELECT employee_id, full_name, phone_number, email, employee_type,
               department, designation, join_date, basic_salary, status, photo_name
        FROM employees
        {where_sql}
        ORDER BY CASE WHEN status = 'Active' THEN 0 ELSE 1 END, full_name ASC
        """,
        params,
    ).fetchall()

    all_departments = employee_departments(db)
    all_types = employee_types(db)

    total = len(employees)
    active = sum(1 for e in employees if (e["status"] or "").lower() == "active")
    inactive = total - active

    return render_template(
        "hr/employee_list.html",
        employees=employees,
        query=query,
        status_filter=status_filter,
        department_filter=department_filter,
        employee_type_filter=employee_type_filter,
        departments=all_departments,
        employee_types=all_types,
        status_options=STATUS_OPTIONS,
        total=total,
        active_count=active,
        inactive_count=inactive,
    )


# ── Add Employee ─────────────────────────────────────────────────

@hr_bp.route("/hr/employees/new", methods=["GET", "POST"])
@_login_required("admin")
def employee_new():
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    values = employee_form_data()
    if not values["employee_id"]:
        values["employee_id"] = next_employee_id(db)

    if request.method == "POST":
        errors = validate_employee_form(values)
        if errors:
            for err in errors:
                flash(err, "error")
            return render_template(
                "hr/employee_form.html",
                values=values,
                page_title="Add Employee",
                submit_label="Save Employee",
                edit_mode=False,
                employee_types=EMPLOYEE_TYPES,
                departments=DEPARTMENTS,
                designations=DESIGNATIONS,
                status_options=STATUS_OPTIONS,
                gender_options=GENDER_OPTIONS,
                shift_options=SHIFT_OPTIONS,
                contract_options=CONTRACT_TYPE_OPTIONS,
            )

        salary = float(values["basic_salary"])
        ot_rate = float(values.get("ot_rate", 0) or 0)

        uploaded_photo = save_employee_photo(
            current_app._get_current_object(), values["employee_id"],
            values["full_name"], request.files.get("photo_file")
        )

        db.execute(
            """
            INSERT INTO employees (
                employee_id, full_name, phone_number, email,
                employee_type, department, designation, gender,
                shift, contract_type, join_date, basic_salary, ot_rate,
                nationality, iqama_no, passport_no,
                bank_name, bank_account, iban,
                emergency_contact, emergency_name, address,
                photo_name, photo_data, photo_content_type,
                status, remarks
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values["employee_id"], values["full_name"], values["phone_number"], values["email"] or None,
                values["employee_type"], values["department"], values["designation"], values["gender"] or None,
                values["shift"] or "Morning", values["contract_type"] or "Permanent",
                values["join_date"], salary, ot_rate,
                values["nationality"] or None, values["iqama_no"] or None, values["passport_no"] or None,
                values["bank_name"] or None, values["bank_account"] or None, values["iban"] or None,
                values["emergency_contact"] or None, values["emergency_name"] or None, values["address"] or None,
                uploaded_photo["photo_name"] if uploaded_photo else None,
                uploaded_photo["photo_data"] if uploaded_photo else None,
                uploaded_photo["photo_content_type"] if uploaded_photo else None,
                values["status"], values["remarks"] or None,
            ),
        )

        _audit_log(
            db, "employee_created",
            entity_type="employee",
            entity_id=values["employee_id"],
            details=f"{values['full_name']} / {values['employee_type']} / {values['department']}",
        )
        db.commit()
        flash(f"Employee {values['employee_id']} - {values['full_name']} created successfully.", "success")
        return redirect(url_for("hr.employee_detail", employee_id=values["employee_id"]))

    return render_template(
        "hr/employee_form.html",
        values=values,
        page_title="Add Employee",
        submit_label="Save Employee",
        edit_mode=False,
        employee_types=EMPLOYEE_TYPES,
        departments=DEPARTMENTS,
        designations=DESIGNATIONS,
        status_options=STATUS_OPTIONS,
        gender_options=GENDER_OPTIONS,
        shift_options=SHIFT_OPTIONS,
        contract_options=CONTRACT_TYPE_OPTIONS,
    )


# ── Employee Detail (Profile + 3 Tabs) ───────────────────────────

@hr_bp.route("/hr/employees/<employee_id>")
@_login_required("admin")
def employee_detail(employee_id):
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))

    return redirect(url_for("hr.employee_transactions", employee_id=employee_id))


# ── Transactions Tab ─────────────────────────────────────────────

@hr_bp.route("/hr/employees/<employee_id>/transactions", methods=["GET", "POST"])
@_login_required("admin")
def employee_transactions(employee_id):
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))

    eid = employee["employee_id"]
    today = date.today().isoformat()
    form_values = {
        "entry_date": today,
        "amount": "",
        "source": "Cash",
        "given_by": "",
        "details": "",
    }

    if request.method == "POST":
        form_values = {
            "entry_date": request.form.get("entry_date", today).strip() or today,
            "amount": request.form.get("amount", "0").strip(),
            "source": request.form.get("source", "Cash").strip(),
            "given_by": request.form.get("given_by", "").strip(),
            "details": request.form.get("details", "").strip(),
        }
        try:
            amount = _parse_decimal(form_values["amount"], "Amount", minimum=0.01)
            if not form_values["given_by"]:
                raise ValidationError("Given by (person name) is required.")
            if not form_values["details"]:
                raise ValidationError("Details / reason is required.")
            txn_type = request.form.get("txn_type", "Advance").strip()
            salary_month = request.form.get("salary_month", "").strip() or _current_month_value()

            db.execute(
                """
                INSERT INTO driver_transactions
                    (driver_id, entry_date, salary_month, txn_type, source, given_by, amount, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (eid, form_values["entry_date"], salary_month, txn_type, form_values["source"],
                 form_values["given_by"], amount, form_values["details"]),
            )
            _audit_log(
                db, "employee_transaction_created",
                entity_type="employee_transaction",
                entity_id=eid,
                details=f"AED {amount:.2f} / {form_values['source']} / {form_values['details']}",
            )
            db.commit()
            flash(f"Transaction of AED {amount:.2f} recorded for {employee['full_name']}.", "success")
            return redirect(url_for("hr.employee_transactions", employee_id=eid))
        except ValidationError as exc:
            flash(str(exc), "error")

    transactions = db.execute(
        """
        SELECT id, entry_date, salary_month, txn_type, source, given_by, amount, details, created_at
        FROM driver_transactions
        WHERE driver_id = ?
        ORDER BY entry_date DESC, id DESC
        LIMIT 50
        """,
        (eid,),
    ).fetchall()

    total_advance = db.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM driver_transactions WHERE driver_id = ?",
        (eid,),
    ).fetchone()[0]

    photo_url = _employee_photo_url(current_app._get_current_object(), employee)

    return render_template(
        "hr/employee_detail.html",
        employee=employee,
        photo_url=photo_url,
        active_tab="transactions",
        txn_form=form_values,
        transactions=transactions,
        total_advance=total_advance,
    )


# ── Store Salary Tab ─────────────────────────────────────────────

@hr_bp.route("/hr/employees/<employee_id>/salary-store", methods=["GET", "POST"])
@_login_required("admin")
def employee_salary_store(employee_id):
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))

    eid = employee["employee_id"]

    # Build a driver-like dict for salary helpers
    driver_like = {
        "driver_id": eid,
        "basic_salary": employee["basic_salary"] or 0,
        "ot_rate": employee["ot_rate"] or 0,
        "duty_start": employee["join_date"],
    }

    selected_month = request.args.get("month", "").strip() or _current_month_value()
    existing_row = db.execute(
        "SELECT * FROM salary_store WHERE driver_id = ? AND salary_month = ?",
        (eid, selected_month),
    ).fetchone()

    form = _default_salary_form(selected_month, employee.get("join_date"))
    preview = _calculate_salary_preview(driver_like, form)
    if existing_row is not None:
        form = _salary_form_from_row(existing_row)
        preview = _salary_preview_from_row(existing_row)

    if request.method == "POST":
        form = {
            "entry_date": request.form.get("entry_date", date.today().isoformat()).strip() or date.today().isoformat(),
            "salary_month": _normalize_month(request.form.get("salary_month", selected_month).strip() or selected_month),
            "ot_month": "",
            "salary_mode": (request.form.get("salary_mode", "full").strip() or "full").lower(),
            "prorata_start_date": request.form.get("prorata_start_date", "").strip(),
            "prorata_end_date": request.form.get("prorata_end_date", "").strip(),
            "ot_hours": request.form.get("ot_hours", "0").strip() or "0",
            "personal_vehicle": request.form.get("personal_vehicle", "0").strip() or "0",
            "personal_vehicle_note": request.form.get("personal_vehicle_note", "").strip(),
            "remarks": request.form.get("remarks", "").strip(),
        }
        form["ot_month"] = _previous_month_value(form["salary_month"])
        try:
            preview = _calculate_salary_preview(driver_like, form)
        except ValidationError as exc:
            flash(str(exc), "error")
        else:
            action = request.form.get("action", "calculate")
            if action == "save":
                existing_month_row = db.execute(
                    "SELECT id FROM salary_store WHERE driver_id = ? AND salary_month = ?",
                    (eid, form["salary_month"]),
                ).fetchone()

                db.execute(
                    """
                    INSERT INTO salary_store (
                        driver_id, entry_date, salary_month, ot_month, salary_mode, prorata_start_date,
                        salary_days, daily_rate, monthly_basic_salary, basic_salary, ot_hours, ot_rate,
                        ot_amount, personal_vehicle, personal_vehicle_note, net_salary, remarks
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(driver_id, salary_month) DO UPDATE SET
                        entry_date = excluded.entry_date, ot_month = excluded.ot_month,
                        salary_mode = excluded.salary_mode, prorata_start_date = excluded.prorata_start_date,
                        salary_days = excluded.salary_days, daily_rate = excluded.daily_rate,
                        monthly_basic_salary = excluded.monthly_basic_salary,
                        basic_salary = excluded.basic_salary, ot_hours = excluded.ot_hours,
                        ot_rate = excluded.ot_rate, ot_amount = excluded.ot_amount,
                        personal_vehicle = excluded.personal_vehicle,
                        personal_vehicle_note = excluded.personal_vehicle_note,
                        net_salary = excluded.net_salary, remarks = excluded.remarks
                    """,
                    (
                        eid, form["entry_date"], form["salary_month"],
                        preview["ot_month"], preview["salary_mode"],
                        preview["prorata_start_date"] or None,
                        preview["salary_days"], preview["daily_rate"],
                        preview["monthly_basic_salary"], preview["basic_salary"],
                        preview["ot_hours"], preview["ot_rate"],
                        preview["ot_amount"], preview["personal_vehicle"],
                        preview["personal_vehicle_note"] or None,
                        preview["net_salary"], form["remarks"],
                    ),
                )
                _audit_log(
                    db, "employee_salary_store_saved",
                    entity_type="salary_store",
                    entity_id=f"{eid}:{form['salary_month']}",
                    details=f"{preview['salary_mode_label']} / net AED {preview['net_salary']:.2f}",
                )
                db.commit()
                if existing_month_row:
                    flash("Salary updated for this month.", "success")
                else:
                    flash("Salary stored successfully.", "success")
                return redirect(url_for("hr.employee_salary_store", employee_id=eid, month=form["salary_month"]))

    salary_rows = db.execute(
        """
        SELECT id, entry_date, salary_month, ot_month, salary_mode, prorata_start_date,
               salary_days, daily_rate, monthly_basic_salary, basic_salary, ot_hours,
               ot_amount, personal_vehicle, personal_vehicle_note, net_salary, remarks
        FROM salary_store
        WHERE driver_id = ?
        ORDER BY salary_month DESC
        LIMIT 12
        """,
        (eid,),
    ).fetchall()

    timesheet_hours = _timesheet_total_for_month(db, eid, form["salary_month"])
    photo_url = _employee_photo_url(current_app._get_current_object(), employee)

    return render_template(
        "hr/employee_detail.html",
        employee=employee,
        photo_url=photo_url,
        active_tab="salary_store",
        salary_form=form,
        salary_preview=preview,
        salary_rows=salary_rows,
        selected_month_label=format_month_label(form["salary_month"]),
        timesheet_hours=timesheet_hours,
        existing_month=existing_row is not None,
        salary_mode_options=SALARY_MODE_OPTIONS,
    )


@hr_bp.route("/hr/employees/<employee_id>/salary-store/<int:store_id>/delete", methods=["GET", "POST"])
@_login_required("admin")
def employee_salary_store_delete(employee_id, store_id):
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()
    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))
    eid = employee["employee_id"]
    row = db.execute(
        "SELECT * FROM salary_store WHERE id = ? AND driver_id = ?",
        (store_id, eid),
    ).fetchone()
    if row is None:
        flash("Salary store not found.", "error")
    else:
        slip = db.execute(
            "SELECT id FROM salary_slips WHERE salary_store_id = ? AND driver_id = ? LIMIT 1",
            (store_id, eid),
        ).fetchone()
        if slip:
            flash("Cannot delete: salary slip already generated for this month. Delete the slip first.", "error")
        else:
            db.execute("DELETE FROM salary_store WHERE id = ? AND driver_id = ?", (store_id, eid))
            _audit_log(db, "employee_salary_store_deleted", entity_type="salary_store", entity_id=f"{eid}:{row['salary_month']}")
            db.commit()
            flash(f"Salary store for {row['salary_month']} deleted.", "success")
    return redirect(url_for("hr.employee_salary_store", employee_id=eid))


def _previous_month_value(month_value: str) -> str:
    y, m = int(month_value[:4]), int(month_value[5:7])
    m -= 1
    if m == 0:
        y -= 1
        m = 12
    return f"{y:04d}-{m:02d}"


# ── Run Salary / Salary Slip Tab ─────────────────────────────────

@hr_bp.route("/hr/employees/<employee_id>/salary-slip", methods=["GET", "POST"])
@_login_required("admin")
def employee_salary_slip(employee_id):
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))

    eid = employee["employee_id"]

    salary_rows = db.execute(
        "SELECT * FROM salary_store WHERE driver_id = ? ORDER BY salary_month DESC",
        (eid,),
    ).fetchall()

    slip_store_ids = {
        r["salary_store_id"]
        for r in db.execute(
            "SELECT DISTINCT salary_store_id FROM salary_slips WHERE driver_id = ?", (eid,)
        ).fetchall()
    }

    selected_salary_id = request.args.get("salary_store_id", "").strip()
    if not selected_salary_id and salary_rows:
        selected_salary_id = str(salary_rows[0]["id"])

    selected_salary = None
    existing_slip = None
    existing_payment = None
    advance_summary = _advance_summary(db, eid)
    available_advance = advance_summary["remaining_advance"]

    values = {
        "deduction_amount": "0.00",
        "payment_date": date.today().isoformat(),
        "actual_paid_amount": "",
        "payment_source": PAYMENT_SOURCES[0],
        "paid_by": "",
        "payment_notes": "",
    }

    if selected_salary_id:
        selected_salary = db.execute(
            "SELECT * FROM salary_store WHERE id = ? AND driver_id = ?",
            (selected_salary_id, eid),
        ).fetchone()
        if selected_salary is not None:
            existing_slip = db.execute(
                """
                SELECT * FROM salary_slips
                WHERE salary_store_id = ? AND driver_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (selected_salary_id, eid),
            ).fetchone()
            available_advance = _advance_summary(
                db, eid, exclude_salary_store_id=int(selected_salary_id),
            )["remaining_advance"]
            if existing_slip:
                values["deduction_amount"] = f"{float(existing_slip['total_deductions']):.2f}"

    if request.method == "POST":
        selected_salary_id = request.form.get("salary_store_id", "").strip()
        values = {
            "deduction_amount": request.form.get("deduction_amount", "0").strip() or "0",
            "payment_date": request.form.get("payment_date", date.today().isoformat()).strip() or date.today().isoformat(),
            "actual_paid_amount": request.form.get("actual_paid_amount", "").strip(),
            "payment_source": request.form.get("payment_source", PAYMENT_SOURCES[0]).strip() or PAYMENT_SOURCES[0],
            "paid_by": request.form.get("paid_by", "").strip(),
            "payment_notes": request.form.get("payment_notes", "").strip(),
        }

        if not selected_salary_id:
            flash("Select a stored salary month first.", "error")
        else:
            selected_salary = db.execute(
                "SELECT * FROM salary_store WHERE id = ? AND driver_id = ?",
                (selected_salary_id, eid),
            ).fetchone()
            existing_slip = db.execute(
                """
                SELECT * FROM salary_slips
                WHERE salary_store_id = ? AND driver_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (selected_salary_id, eid),
            ).fetchone()
            available_advance = _advance_summary(
                db, eid, exclude_salary_store_id=int(selected_salary_id),
            )["remaining_advance"]

            try:
                deduction_amount = _parse_decimal(values["deduction_amount"], "Deduction", required=False, default=0.0, minimum=0.0)
            except ValidationError as exc:
                flash(str(exc), "error")
                deduction_amount = None

            if deduction_amount is not None and selected_salary is not None:
                if deduction_amount < 0 or deduction_amount > available_advance + 0.001:
                    flash(f"Deduction must be between 0 and {available_advance:,.2f}.", "error")
                else:
                    salary_after_deduction = float(selected_salary["net_salary"]) - deduction_amount
                    if salary_after_deduction < 0:
                        flash("Deduction cannot exceed salary amount.", "error")
                    else:
                        remaining_advance = max(available_advance - deduction_amount, 0.0)
                        from ..pdf_service import generate_salary_slip_pdf
                        company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()

                        if existing_slip is not None:
                            db.execute(
                                """
                                UPDATE salary_slips
                                SET total_deductions=?, available_advance=?, remaining_advance=?,
                                    salary_after_deduction=?, net_payable=?,
                                    generated_at=CURRENT_TIMESTAMP
                                WHERE id=? AND driver_id=?
                                """,
                                (deduction_amount, available_advance, remaining_advance,
                                 salary_after_deduction, salary_after_deduction,
                                 existing_slip["id"], eid),
                            )
                            slip_id = existing_slip["id"]
                        else:
                            db.execute(
                                """
                                INSERT INTO salary_slips (
                                    driver_id, salary_store_id, salary_month, source_filter,
                                    total_deductions, available_advance, remaining_advance,
                                    salary_after_deduction, actual_paid_amount,
                                    company_balance_due, payment_source, paid_by, net_payable, pdf_path
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (eid, selected_salary["id"], selected_salary["salary_month"], "",
                                 deduction_amount, available_advance, remaining_advance,
                                 salary_after_deduction, 0.0, salary_after_deduction,
                                 values["payment_source"], values["paid_by"] or None,
                                 salary_after_deduction, ""),
                            )
                            slip_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

                        slip_row = db.execute("SELECT * FROM salary_slips WHERE id = ?", (slip_id,)).fetchone()
                        driver_display = {"driver_id": eid, "full_name": employee["full_name"],
                                          "basic_salary": employee["basic_salary"] or 0,
                                          "vehicle_no": "", "shift": employee.get("shift", ""),
                                          "duty_start": employee.get("join_date", "")}

                        generated_dir = current_app.config["GENERATED_DIR"]
                        slip_output_dir = str(Path(generated_dir) / "salary_slips")
                        pdf_path = generate_salary_slip_pdf(
                            driver_display,
                            selected_salary,
                            {
                                "available_advance": float(available_advance),
                                "deduction_amount": float(deduction_amount),
                                "remaining_advance": float(remaining_advance),
                                "salary_after_deduction": float(salary_after_deduction),
                                "actual_paid_amount": float(salary_after_deduction),
                                "company_balance_due": float(salary_after_deduction),
                                "payment_source": values["payment_source"],
                                "paid_by": values["paid_by"] or "",
                                "net_payable": float(salary_after_deduction),
                            },
                            slip_output_dir,
                            current_app.config["STATIC_ASSETS_DIR"],
                            generated_dir,
                        )
                        relative_pdf = Path(pdf_path).relative_to(current_app.config["GENERATED_DIR"]).as_posix() if pdf_path else ""
                        db.execute("UPDATE salary_slips SET pdf_path=? WHERE id=?", (relative_pdf, slip_id))
                        _audit_log(db, "employee_salary_slip_generated", entity_type="salary_slip",
                                   entity_id=f"{eid}:{selected_salary['salary_month']}",
                                   details=f"Deduction AED {deduction_amount:.2f} / Payable AED {salary_after_deduction:.2f}")
                        db.commit()
                        flash(f"Salary slip generated for {selected_salary['salary_month']}.", "success")
                        return redirect(url_for("hr.employee_salary_slip", employee_id=eid))

    photo_url = _employee_photo_url(current_app._get_current_object(), employee)

    return render_template(
        "hr/employee_detail.html",
        employee=employee,
        photo_url=photo_url,
        active_tab="salary_slip",
        slip_salary_rows=salary_rows,
        slip_selected_salary=selected_salary,
        slip_existing_slip=existing_slip,
        slip_values=values,
        slip_available_advance=available_advance,
        slip_advance_summary=advance_summary,
        slip_store_ids=slip_store_ids,
    )


@hr_bp.route("/hr/employees/<employee_id>/salary-slip/<int:store_id>/delete", methods=["GET"])
@_login_required("admin")
def employee_salary_slip_delete(employee_id, store_id):
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()
    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))
    eid = employee["employee_id"]
    slip = db.execute(
        "SELECT * FROM salary_slips WHERE salary_store_id = ? AND driver_id = ?",
        (store_id, eid),
    ).fetchone()
    if slip is None:
        flash("Salary slip not found.", "error")
    else:
        db.execute("DELETE FROM salary_slips WHERE id = ?", (slip["id"],))
        _audit_log(db, "employee_salary_slip_deleted", entity_type="salary_slip",
                    entity_id=f"{eid}:{slip['salary_month']}")
        db.commit()
        flash(f"Salary slip for {slip['salary_month']} deleted.", "success")
    return redirect(url_for("hr.employee_salary_slip", employee_id=eid, salary_store_id=store_id))


# ── Employee Kata ────────────────────────────────────────────────

@hr_bp.route("/hr/employees/<employee_id>/kata")
@_login_required("admin")
def employee_kata(employee_id):
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))

    eid = employee["employee_id"]

    available_months = db.execute(
        """
        SELECT DISTINCT salary_month FROM (
            SELECT salary_month FROM salary_store WHERE driver_id = ?
            UNION
            SELECT salary_month FROM salary_slips WHERE driver_id = ?
            UNION
            SELECT COALESCE(salary_month, SUBSTR(entry_date, 1, 7)) AS salary_month
            FROM driver_transactions WHERE driver_id = ?
        ) ORDER BY salary_month DESC
        """,
        (eid, eid, eid),
    ).fetchall()

    selected_month = request.args.get("month", "").strip()
    if not selected_month and available_months:
        selected_month = available_months[0]["salary_month"]

    entries = []
    summary = {}
    salary_row = None
    slip_row = None
    kata_advances = []
    kata_prev_remaining = 0.0
    kata_this_deduction = 0.0
    kata_remaining = 0.0

    if selected_month:
        active_entries, closed_entries, summary_ret = _driver_kata_month_data(db, eid, selected_month)
        entries = active_entries + closed_entries
        summary = summary_ret

        salary_row = db.execute(
            "SELECT * FROM salary_store WHERE driver_id = ? AND salary_month = ?",
            (eid, selected_month),
        ).fetchone()

        slip_row = db.execute(
            "SELECT * FROM salary_slips WHERE driver_id = ? AND salary_month = ? ORDER BY id DESC LIMIT 1",
            (eid, selected_month),
        ).fetchone()

        all_advances = db.execute(
            "SELECT * FROM driver_transactions WHERE driver_id = ? ORDER BY entry_date ASC, id ASC",
            (eid,),
        ).fetchall()

        total_advance_amount = sum(float(r["amount"]) for r in all_advances)

        prev_deductions = float(db.execute(
            "SELECT COALESCE(SUM(total_deductions), 0) FROM salary_slips WHERE driver_id = ? AND salary_month < ?",
            (eid, selected_month),
        ).fetchone()[0])

        this_deduction = float(slip_row["total_deductions"]) if slip_row else 0.0

        remaining_before = max(total_advance_amount - prev_deductions, 0.0)
        remaining_after = max(remaining_before - this_deduction, 0.0)

        kata_prev_remaining = remaining_before
        kata_this_deduction = this_deduction
        kata_remaining = remaining_after

        deduction_left = prev_deductions + this_deduction
        for a in all_advances:
            amt = float(a["amount"])
            if deduction_left <= 0:
                kata_advances.append({
                    "entry_date": a["entry_date"],
                    "amount": amt,
                    "source": a["source"],
                    "given_by": a["given_by"],
                    "details": a["details"],
                    "remaining": amt,
                    "deducted": 0.0,
                    "status": "outstanding",
                })
            elif deduction_left >= amt:
                kata_advances.append({
                    "entry_date": a["entry_date"],
                    "amount": amt,
                    "source": a["source"],
                    "given_by": a["given_by"],
                    "details": a["details"],
                    "remaining": 0.0,
                    "deducted": amt,
                    "status": "cleared",
                })
                deduction_left -= amt
            else:
                kata_advances.append({
                    "entry_date": a["entry_date"],
                    "amount": amt,
                    "source": a["source"],
                    "given_by": a["given_by"],
                    "details": a["details"],
                    "remaining": amt - deduction_left,
                    "deducted": deduction_left,
                    "status": "partial",
                })
                deduction_left = 0.0

    pdf_url = None
    if request.args.get("download") == "pdf" and selected_month:
        from ..pdf_service import generate_simple_kata_pdf

        driver_display = {
            "driver_id": eid,
            "full_name": employee["full_name"],
            "basic_salary": employee["basic_salary"] or 0,
        }
        pdf_path = generate_simple_kata_pdf(
            driver_display,
            salary_row,
            kata_advances,
            kata_prev_remaining,
            kata_this_deduction,
            kata_remaining,
            selected_month,
            str(Path(current_app.config["GENERATED_DIR"]) / "kata_pdfs"),
            current_app.config["STATIC_ASSETS_DIR"],
        )
        if pdf_path:
            relative_path = Path(pdf_path).relative_to(current_app.config["GENERATED_DIR"]).as_posix()
            pdf_url = url_for("generated_file", filename=relative_path)

    photo_url = _employee_photo_url(current_app._get_current_object(), employee)

    return render_template(
        "hr/employee_detail.html",
        employee=employee,
        photo_url=photo_url,
        active_tab="kata",
        kata_available_months=available_months,
        kata_selected_month=selected_month,
        kata_entries=entries,
        kata_summary=summary,
        kata_salary_row=salary_row,
        kata_slip_row=slip_row,
        kata_advances=kata_advances,
        kata_prev_remaining=kata_prev_remaining,
        kata_this_deduction=kata_this_deduction,
        kata_remaining=kata_remaining,
        kata_pdf_url=pdf_url,
    )


# ── Employee Edit ────────────────────────────────────────────────

@hr_bp.route("/hr/employees/<employee_id>/edit", methods=["GET", "POST"])
@_login_required("admin")
def employee_edit(employee_id):
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    employee_id = employee_id.strip().upper()
    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))

    if request.method == "POST":
        values = employee_form_data()
        values["employee_id"] = employee_id
        errors = validate_employee_form(values)
        if errors:
            for err in errors:
                flash(err, "error")
        else:
            salary = float(values["basic_salary"])
            ot_rate = float(values.get("ot_rate", 0) or 0)
            uploaded_photo = save_employee_photo(
                current_app._get_current_object(), employee_id,
                values["full_name"], request.files.get("photo_file"))

            db.execute(
                """
                UPDATE employees SET
                    full_name=?, phone_number=?, email=?,
                    employee_type=?, department=?, designation=?, gender=?,
                    shift=?, contract_type=?, join_date=?,
                    basic_salary=?, ot_rate=?,
                    nationality=?, iqama_no=?, passport_no=?,
                    bank_name=?, bank_account=?, iban=?,
                    emergency_contact=?, emergency_name=?, address=?,
                    photo_name=COALESCE(?, photo_name),
                    photo_data=COALESCE(?, photo_data),
                    photo_content_type=COALESCE(?, photo_content_type),
                    status=?, remarks=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE employee_id=?
                """,
                (
                    values["full_name"], values["phone_number"], values["email"] or None,
                    values["employee_type"], values["department"], values["designation"], values["gender"] or None,
                    values["shift"] or "Morning", values["contract_type"] or "Permanent",
                    values["join_date"], salary, ot_rate,
                    values["nationality"] or None, values["iqama_no"] or None, values["passport_no"] or None,
                    values["bank_name"] or None, values["bank_account"] or None, values["iban"] or None,
                    values["emergency_contact"] or None, values["emergency_name"] or None, values["address"] or None,
                    uploaded_photo["photo_name"] if uploaded_photo else None,
                    uploaded_photo["photo_data"] if uploaded_photo else None,
                    uploaded_photo["photo_content_type"] if uploaded_photo else None,
                    values["status"], values["remarks"] or None,
                    employee_id,
                ),
            )
            _audit_log(db, "employee_updated", entity_type="employee", entity_id=employee_id, details=f"{values['full_name']} updated")
            db.commit()
            flash("Employee updated successfully.", "success")
            return redirect(url_for("hr.employee_detail", employee_id=employee_id))

    values = dict(employee)
    for key in ("basic_salary", "ot_rate"):
        try:
            values[key] = f"{float(values[key] or 0):.2f}" if values.get(key) else "0"
        except (ValueError, TypeError):
            values[key] = "0"

    return render_template(
        "hr/employee_form.html",
        values=values,
        page_title="Edit Employee",
        submit_label="Update Employee",
        edit_mode=True,
        employee_types=EMPLOYEE_TYPES,
        departments=DEPARTMENTS,
        designations=DESIGNATIONS,
        status_options=STATUS_OPTIONS,
        gender_options=GENDER_OPTIONS,
        shift_options=SHIFT_OPTIONS,
        contract_options=CONTRACT_TYPE_OPTIONS,
    )


@hr_bp.app_template_global()
def employee_photo_url(employee):
    if not employee:
        return None
    if employee.get("photo_data") and employee.get("photo_content_type"):
        return f"data:{employee['photo_content_type']};base64,{employee['photo_data']}"
    return None
