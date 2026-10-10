from datetime import date, datetime, timedelta
from pathlib import Path
from io import BytesIO
import base64
import tempfile

from flask import (
    current_app, flash, redirect, render_template, request,
    send_file, url_for
)
from werkzeug.security import generate_password_hash

from ..database import open_db
from ..routes import (
    _login_required, _audit_log, _touch_admin_workspace, _current_month_value,
    ValidationError, _parse_decimal, _normalize_month,
    _advance_summary, _timesheet_total_for_month,
    _calculate_salary_preview, _default_salary_form, _salary_form_from_row,
    _salary_preview_from_row, format_month_label,
    _driver_kata_month_data, _regenerate_kata_for_driver,
    SALARY_MODE_OPTIONS, PAYMENT_SOURCES
)
from . import hr_bp
from .forms import (
    employee_form_data, validate_employee_form,
    EMPLOYEE_TYPES, DEPARTMENTS, DESIGNATIONS, STATUS_OPTIONS,
    GENDER_OPTIONS, SHIFT_OPTIONS, CONTRACT_TYPE_OPTIONS
)
from .services import (
    sync_drivers_to_employees, save_employee_photo,
    employee_search_filter, next_employee_id,
    employee_departments, employee_types,
    sync_field_staff_to_employees,
    EMPLOYEE_SCHEMA, EMPLOYEE_SCHEMA_POSTGRES
)


_hr_tables_ensured = False

def ensure_employees_table():
    global _hr_tables_ensured
    if _hr_tables_ensured:
        return
    _hr_tables_ensured = True
    db = open_db()
    backend = current_app.config.get("DATABASE_BACKEND", "sqlite")

    try:
        schema = EMPLOYEE_SCHEMA_POSTGRES if backend == "postgres" else EMPLOYEE_SCHEMA
        db.executescript(schema)
        db.commit()
    except Exception as e:
        import traceback
        current_app.logger.error("ensure_employees_table schema error: %s\n%s", e, traceback.format_exc())

    # Migration: add missing columns for tables created before schema was expanded
    employee_cols = [
        ("employee_id", "TEXT"),
        ("email", "TEXT"),
        ("gender", "TEXT"),
        ("shift", "TEXT DEFAULT 'Morning'"),
        ("contract_type", "TEXT DEFAULT 'Permanent'"),
        ("nationality", "TEXT"),
        ("iqama_no", "TEXT"),
        ("passport_no", "TEXT"),
        ("bank_name", "TEXT"),
        ("bank_account", "TEXT"),
        ("iban", "TEXT"),
        ("emergency_contact", "TEXT"),
        ("emergency_name", "TEXT"),
        ("address", "TEXT"),
        ("photo_name", "TEXT"),
        ("photo_data", "TEXT"),
        ("photo_content_type", "TEXT"),
        ("termination_date", "TEXT"),
        ("remarks", "TEXT"),
        ("updated_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
        # Driver / operator documents (additive — never touches existing rows)
        ("driving_license_no", "TEXT"),
        ("driving_license_expiry", "TEXT"),
        ("driving_license_front", "TEXT"),
        ("driving_license_front_type", "TEXT"),
        ("driving_license_back", "TEXT"),
        ("driving_license_back_type", "TEXT"),
        ("emirates_id_no", "TEXT"),
        ("emirates_id_front", "TEXT"),
        ("emirates_id_front_type", "TEXT"),
        ("emirates_id_back", "TEXT"),
        ("emirates_id_back_type", "TEXT"),
    ]
    for col_name, col_type in employee_cols:
        try:
            if backend == "postgres":
                db.execute(f"ALTER TABLE employees ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
            else:
                db.execute(f"ALTER TABLE employees ADD COLUMN {col_name} {col_type}")
            db.commit()
        except Exception:
            db.rollback()

    try:
        sync_drivers_to_employees(db)
    except Exception:
        db.rollback()

    try:
        sync_field_staff_to_employees(db)
    except Exception:
        db.rollback()


def _fetch_employee(db, employee_id):
    return db.execute(
        "SELECT id, employee_id, full_name, phone_number, email, employee_type, department, designation, gender, shift, contract_type, join_date, basic_salary, ot_rate, nationality, iqama_no, passport_no, bank_name, bank_account, iban, emergency_contact, emergency_name, address, photo_name, photo_data, photo_content_type, status, termination_date, remarks, driving_license_no, driving_license_expiry, driving_license_front, driving_license_front_type, driving_license_back, driving_license_back_type, emirates_id_no, emirates_id_front, emirates_id_front_type, emirates_id_back, emirates_id_back_type, updated_at FROM employees WHERE UPPER(employee_id) = ?",
        (employee_id.strip().upper(),),
    ).fetchone()


def _sync_employee_to_field_staff(db, staff_id, full_name, phone, status):
    from werkzeug.security import generate_password_hash
    username = staff_id.lower()
    pw_hash = generate_password_hash("changeme123")
    is_active = 1 if status == "Active" else 0
    try:
        existing = db.execute("SELECT staff_id FROM field_staff WHERE staff_id = ?", (staff_id,)).fetchone()
        if existing:
            db.execute("UPDATE field_staff SET full_name=?, phone=?, is_active=? WHERE staff_id=?", (full_name, phone or "", is_active, staff_id))
        else:
            db.execute("INSERT INTO field_staff (staff_id, full_name, phone, username, password_hash, is_active) VALUES (?,?,?,?,?,?)", (staff_id, full_name, phone or "", username, pw_hash, is_active))
    except Exception:
        pass


def _employee_photo_url(app, employee):
    if not employee:
        return None
    if employee.get("photo_data") and employee.get("photo_content_type"):
        return f"data:{employee['photo_content_type']};base64,{employee['photo_data']}"
    if employee.get("photo_url"):
        return employee["photo_url"]
    if employee.get("photo_name"):
        try:
            import base64
            from pathlib import Path
            photo_dir = Path(app.config.get("DRIVER_FILES_DIR", "")) / "employee_photos"
            photo_path = photo_dir / employee["photo_name"]
            if photo_path.exists():
                ct = "image/jpeg"
                ext = photo_path.suffix.lower()
                if ext == ".png": ct = "image/png"
                elif ext == ".gif": ct = "image/gif"
                elif ext == ".webp": ct = "image/webp"
                with open(photo_path, "rb") as f:
                    data = base64.b64encode(f.read()).decode("utf-8")
                return f"data:{ct};base64,{data}"
        except Exception:
            pass
    return None


# ── HR Dashboard ────────────────────────────────────────────────

@hr_bp.route("/hr")
@_login_required("admin")
def hr_dashboard():
    try:
        _touch_admin_workspace("hr")
        ensure_employees_table()
        db = open_db()

        employees = db.execute(
            "SELECT employee_id, full_name, employee_type, department, status, join_date FROM employees ORDER BY full_name"
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

        # ── Department breakdown ──
        dept_rows = db.execute(
            "SELECT department, COUNT(*) AS c FROM employees GROUP BY department ORDER BY c DESC"
        ).fetchall()
        departments = {r["department"]: r["c"] for r in dept_rows}

        # ── Type breakdown ──
        type_rows = db.execute(
            "SELECT employee_type, COUNT(*) AS c FROM employees GROUP BY employee_type ORDER BY c DESC"
        ).fetchall()
        employee_types_dict = {r["employee_type"]: r["c"] for r in type_rows}

        # ── Monthly salary store trend (last 6 months) ──
        from datetime import date
        trend_months = []
        trend_counts = []
        today = date.today()
        for i in range(5, -1, -1):
            m = today.month - i
            y = today.year
            if m < 1:
                m += 12
                y -= 1
            ym = f"{y:04d}-{m:02d}"
            cnt = db.execute(
                "SELECT COUNT(*) AS c FROM salary_store WHERE salary_month = ?", (ym,)
            ).fetchone()["c"] or 0
            trend_months.append(ym)
            trend_counts.append(cnt)

        # ── Active drivers payroll amount this month ──
        payroll_row = db.execute(
            "SELECT COALESCE(SUM(ss.net_salary), 0) AS total FROM salary_store ss JOIN employees e ON e.employee_id = ss.driver_id WHERE ss.salary_month = ? AND LOWER(e.status) = 'active'",
            (_current_month_value(),),
        ).fetchone()
        payroll_amount = payroll_row["total"] if payroll_row else 0

        # ── Salary Paid vs Unpaid (last completed month) ──
        # Same source as /hr/paid-salary-report: a salary counts as PAID only
        # when money actually moved (salary_slips.actual_paid_amount or an
        # owner-fund entry "Salary Slip <month> — <name>") — never merely
        # because a slip exists. Keeps dashboard and report in agreement.
        from datetime import date as _date
        _today = _date.today()
        _prev_month = _today.month - 1 if _today.month > 1 else 12
        _prev_year = _today.year if _today.month > 1 else _today.year - 1
        cm = f"{_prev_year:04d}-{_prev_month:02d}"
        # with_advance=False: the dashboard never shows the advance column and
        # balance/paid/status don't depend on it — skips ~100 per-employee
        # advance queries and cuts /hr render time roughly in half.
        cm_rows = _paid_salary_report_rows(db, cm, with_advance=False)
        cm_run = [r for r in cm_rows if r["status"] != "Not Run"]
        salary_run_count = len(cm_run)
        salary_paid_count = sum(1 for r in cm_run if r["paid"] > 0)
        # Released % is measured against the WHOLE active staff: anyone whose
        # salary has not gone out (run-but-unpaid OR not run yet) counts as
        # unpaid, so the gauge reads "how much of my staff got paid".
        salary_unpaid_count = max(active - salary_paid_count, 0)
        salary_paid_amount = sum(r["paid"] for r in cm_rows)
        salary_unpaid_amount = sum(r["balance"] for r in cm_rows)

        # ── Monthly paid/unpaid trend (last 6 months) ──
        paid_trend_months = []
        paid_trend_paid = []
        paid_trend_unpaid = []
        for i in range(5, -1, -1):
            m = today.month - i
            y = today.year
            if m < 1:
                m += 12
                y -= 1
            ym = f"{y:04d}-{m:02d}"
            m_rows = _paid_salary_report_rows(db, ym, with_advance=False)
            m_run = [r for r in m_rows if r["status"] != "Not Run"]
            p_cnt = sum(1 for r in m_run if r["paid"] > 0)
            paid_trend_months.append(ym)
            paid_trend_paid.append(p_cnt)
            paid_trend_unpaid.append(len(m_run) - p_cnt)

        # ── Recent employees ──
        recent = db.execute(
            "SELECT employee_id, full_name, employee_type, department, join_date, status FROM employees ORDER BY id DESC LIMIT 5"
        ).fetchall()

        # ── Count by status ──
        on_leave = sum(1 for e in employees if (e["status"] or "").lower() == "on leave")
        terminated = sum(1 for e in employees if (e["status"] or "").lower() == "terminated")

        # ── Document (DL / Emirates ID) coverage across active staff ──
        # Additive: the columns come from ensure_employees_table() above; if any
        # is missing the block renders as zeros and the card hides itself.
        docs_active = docs_uploaded = docs_dl = docs_eid = 0
        try:
            row = db.execute(
                """SELECT COUNT(*) AS c,
                          COALESCE(SUM(CASE WHEN COALESCE(driving_license_front,'') <> ''
                                              OR COALESCE(driving_license_back,'') <> ''
                                         THEN 1 ELSE 0 END), 0) AS dl,
                          COALESCE(SUM(CASE WHEN COALESCE(emirates_id_front,'') <> ''
                                              OR COALESCE(emirates_id_back,'') <> ''
                                         THEN 1 ELSE 0 END), 0) AS eid,
                          COALESCE(SUM(CASE WHEN COALESCE(driving_license_front,'') <> ''
                                              OR COALESCE(driving_license_back,'') <> ''
                                              OR COALESCE(emirates_id_front,'') <> ''
                                              OR COALESCE(emirates_id_back,'') <> ''
                                         THEN 1 ELSE 0 END), 0) AS done
                   FROM employees WHERE LOWER(status) = 'active'"""
            ).fetchone()
            if row:
                docs_active = row["c"] or 0
                docs_dl = row["dl"] or 0
                docs_eid = row["eid"] or 0
                docs_uploaded = row["done"] or 0
        except Exception:
            docs_active = docs_uploaded = docs_dl = docs_eid = 0

        return render_template(
            "hr/dashboard.html",
            total=total,
            active_count=active,
            inactive_count=inactive,
            on_leave=on_leave,
            terminated=terminated,
            stored_this_month=stored_this_month,
            payroll_amount=payroll_amount,
            advances_pending=advances_pending,
            departments=departments,
            employee_types=employee_types_dict,
            trend_months=trend_months,
            trend_counts=trend_counts,
            salary_run_count=salary_run_count,
            salary_paid_count=salary_paid_count,
            salary_paid_amount=salary_paid_amount,
            salary_unpaid_count=salary_unpaid_count,
            salary_unpaid_amount=salary_unpaid_amount,
            paid_trend_months=paid_trend_months,
            paid_trend_paid=paid_trend_paid,
            paid_trend_unpaid=paid_trend_unpaid,
            _prev_year=_prev_year,
            _prev_month=_prev_month,
            recent_employees=recent,
            employees=employees,
            today=date.today().isoformat(),
            docs_active=docs_active,
            docs_uploaded=docs_uploaded,
            docs_dl=docs_dl,
            docs_eid=docs_eid,
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        current_app.logger.error("HR dashboard error: %s | type=%s\n%s", e, type(e).__name__, tb)
        flash(f"HR Dashboard error: {type(e).__name__}: {e}\n\nTraceback:\n{tb[:2000]}", "error")
        return redirect(url_for("dashboard"))


# ── Quick Transaction (record advance/loan/payment for any employee) ──────

@hr_bp.route("/hr/transactions/quick", methods=["GET", "POST"])
@_login_required("admin")
def quick_transaction():
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()
    today = date.today().isoformat()

    employees = db.execute(
        "SELECT employee_id, full_name, employee_type, department, status FROM employees ORDER BY full_name"
    ).fetchall()

    if request.method == "POST":
        employee_id = request.form.get("employee_id", "").strip()
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

            employee = _fetch_employee(db, employee_id)
            if employee is None:
                raise ValidationError("Please select a valid employee.")

            result = db.execute(
                """INSERT INTO driver_transactions (driver_id, entry_date, salary_month, txn_type, source, given_by, amount, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (employee_id, form_values["entry_date"], salary_month, txn_type, form_values["source"],
                 form_values["given_by"], amount, form_values["details"]),
            )
            new_txn_id = result.lastrowid
            if form_values["source"] == "Owner Fund" and new_txn_id:
                try:
                    db.execute(
                        """INSERT INTO owner_fund_entries (owner_name, entry_date, amount, received_by, payment_method, transaction_type, details, source_table, source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (form_values["given_by"], form_values["entry_date"], amount,
                         form_values["given_by"], "Cash", "OUT",
                         form_values["details"], "driver_transactions", new_txn_id),
                    )
                except Exception:
                    pass
            _audit_log(db, "employee_transaction_created", entity_type="employee_transaction", entity_id=employee_id, details=f"AED {amount:.2f} / {form_values['source']} / {form_values['details']}")
            db.commit()
            flash(f"AED {amount:.2f} recorded for {employee['full_name']} ({employee_id}).", "success")
            return redirect(url_for("hr.hr_dashboard"))
        except ValidationError as exc:
            flash(str(exc), "error")

    db.close()
    return render_template(
        "hr/quick_transaction.html",
        employees=employees,
        today=today,
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
    shift_filter = request.args.get("shift", "").strip()

    status_counts = db.execute(
        "SELECT LOWER(status) AS st, COUNT(*) AS c FROM employees GROUP BY LOWER(status)"
    ).fetchall()
    total_active = sum(r["c"] for r in status_counts if r["st"] == "active")
    total_inactive = sum(r["c"] for r in status_counts if r["st"] in ("inactive", "on leave"))
    total_terminated = sum(r["c"] for r in status_counts if r["st"] == "terminated")

    if not status_filter:
        status_filter = "Active"

    where_sql, params = employee_search_filter(query, status_filter, department_filter, employee_type_filter)

    # Shift counts for the tab pills — respect every active filter EXCEPT shift
    shift_counts = {}
    try:
        _sc_rows = db.execute(
            f"""
            SELECT CASE WHEN e.shift IS NULL OR TRIM(e.shift) = '' THEN 'Morning'
                        ELSE TRIM(e.shift) END AS sh,
                   COUNT(*) AS c
            FROM employees e
            {where_sql}
            GROUP BY sh
            """,
            params,
        ).fetchall()
        shift_counts = {r["sh"]: r["c"] for r in _sc_rows}
    except Exception:
        shift_counts = {}

    if shift_filter:
        _cond = ("CASE WHEN e.shift IS NULL OR TRIM(e.shift) = '' THEN 'Morning' "
                 "ELSE TRIM(e.shift) END = ?")
        where_sql = (f"{where_sql} AND {_cond}" if where_sql else f"WHERE {_cond}")
        params = list(params) + [shift_filter]

    employees = db.execute(
        f"""
        SELECT e.employee_id, e.full_name, e.phone_number, e.email, e.employee_type,
               e.department, e.designation, e.join_date, e.basic_salary, e.status, e.photo_name, e.termination_date,
               e.shift,
               COALESCE(
                   (SELECT v.plate_no FROM vehicle_assignments va
                    JOIN vehicles v ON v.plate_no = va.vehicle_id
                    WHERE va.driver_id = e.employee_id
                    ORDER BY va.id DESC LIMIT 1),
                   (SELECT d.vehicle_no FROM drivers d WHERE d.driver_id = e.employee_id LIMIT 1)
               ) AS plate_no
        FROM employees e
        {where_sql}
        ORDER BY e.full_name ASC
        """,
        params,
    ).fetchall()

    all_departments = employee_departments(db)
    all_types = employee_types(db)

    return render_template(
        "hr/employee_list.html",
        employees=employees,
        query=query,
        status_filter=status_filter,
        department_filter=department_filter,
        employee_type_filter=employee_type_filter,
        shift_filter=shift_filter,
        shift_counts=shift_counts,
        departments=all_departments,
        employee_types=all_types,
        status_options=STATUS_OPTIONS,
        total_active=total_active,
        total_inactive=total_inactive,
        total_terminated=total_terminated,
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
        try:
            values["employee_id"] = next_employee_id(db)
        except Exception as exc:
            import traceback
            current_app.logger.error("next_employee_id failed: %s\n%s", exc, traceback.format_exc())
            values["employee_id"] = ""

    # Get vehicles if table exists, otherwise empty list
    try:
        vehicles = db.execute("SELECT plate_no, vehicle_type, model, vehicle_category, vehicle_sub_type FROM vehicles WHERE status = 'Active' ORDER BY plate_no").fetchall()
    except Exception:
        vehicles = []

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
                vehicles=vehicles,
                assigned_vehicle=values.get("vehicle_id", ""),
            )

        try:
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
                    status, termination_date, remarks
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    values["status"], values["termination_date"] or None, values["remarks"] or None,
                ),
            )

            db.execute(
                """
                INSERT INTO drivers (
                    driver_id, full_name, phone_number, vehicle_no, shift, vehicle_type,
                    basic_salary, ot_rate, duty_start, photo_name, photo_data, photo_content_type,
                    status, termination_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(driver_id) DO UPDATE SET
                    full_name=excluded.full_name,
                    phone_number=excluded.phone_number,
                    shift=excluded.shift,
                    basic_salary=excluded.basic_salary,
                    ot_rate=excluded.ot_rate,
                    photo_name=excluded.photo_name,
                    photo_data=excluded.photo_data,
                    photo_content_type=excluded.photo_content_type,
                    status=excluded.status,
                    termination_date=excluded.termination_date
                """,
                (
                    values["employee_id"], values["full_name"], values["phone_number"] or None,
                    values.get("vehicle_id", "") or "",
                    values["shift"] or "Morning",
                    values.get("vehicle_type", "Car") or "Car",
                    salary, ot_rate,
                    values["join_date"] or None,
                    uploaded_photo["photo_name"] if uploaded_photo else None,
                    uploaded_photo["photo_data"] if uploaded_photo else None,
                    uploaded_photo["photo_content_type"] if uploaded_photo else None,
                    values["status"], values["termination_date"] or None,
                ),
            )

            if values["vehicle_id"]:
                db.execute(
                    "UPDATE vehicle_assignments SET is_current = 0, assigned_until = ? WHERE driver_id = ? AND is_current = 1",
                    (date.today().isoformat(), values["employee_id"]),
                )
                db.execute(
                    "INSERT INTO vehicle_assignments (vehicle_id, driver_id, assigned_from, is_current) VALUES (?, ?, ?, 1)",
                    (values["vehicle_id"], values["employee_id"], date.today().isoformat()),
                )
                db.execute("UPDATE drivers SET vehicle_no = ? WHERE driver_id = ?", (values["vehicle_id"], values["employee_id"]))

            if values["employee_type"] == "Field Staff":
                _sync_employee_to_field_staff(db, values["employee_id"], values["full_name"], values["phone_number"], values["status"])

            _audit_log(
                db, "employee_created",
                entity_type="employee",
                entity_id=values["employee_id"],
                details=f"{values['full_name']} / {values['employee_type']} / {values['department']}",
            )
            db.commit()
            flash(f"Employee {values['employee_id']} - {values['full_name']} created successfully.", "success")
            return redirect(url_for("hr.employee_detail", employee_id=values["employee_id"]))
        except Exception as e:
            db.rollback()
            import traceback
            current_app.logger.error(f"Employee creation failed: {e}\n{traceback.format_exc()}")
            flash(f"Error creating employee: {str(e)}", "error")
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
                vehicles=vehicles,
                assigned_vehicle=values.get("vehicle_id", ""),
            )


    # For new employees, no assigned vehicle query needed
    assigned_vehicle = None
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
        vehicles=vehicles,
        assigned_vehicle="",
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


def _build_soa(db, employee_id: str, employee, truth: dict) -> dict:
    """Live Statement of Account — current position only (old history collapsed).

    Answers the three questions a driver actually asks: kitna salary abhi baki
    hai, advance kitna baqi hai, aur net kis taraf paisa jayega.
    """
    store_rows = db.execute(
        "SELECT id, salary_month, net_salary FROM salary_store "
        "WHERE driver_id = ? ORDER BY salary_month ASC, id ASC",
        (employee_id,),
    ).fetchall()
    slipped_store_ids = set()
    for r in db.execute(
        "SELECT DISTINCT salary_store_id FROM salary_slips WHERE driver_id = ?",
        (employee_id,),
    ).fetchall():
        if r["salary_store_id"]:
            slipped_store_ids.add(int(r["salary_store_id"]))
    slipped_months = {s["salary_month"] for s in truth["slips"]}

    # Money leaves the office in two ways: (1) advance booked in
    # driver_transactions, later recovered by cutting salary, and (2) salary
    # handed over as cash in the office. A slip that was generated but whose
    # cash never left the office still counts as owed — never as paid.
    unpaid_by_month: dict = {}
    _name = (employee.get("full_name") or employee_id).strip().lower()
    for s in db.execute(
        "SELECT id, salary_month, salary_after_deduction, actual_paid_amount "
        "FROM salary_slips WHERE driver_id = ? ORDER BY id ASC",
        (employee_id,),
    ).fetchall():
        payable = float(s["salary_after_deduction"] or 0) or 0.0
        paid = float(s["actual_paid_amount"] or 0) or 0.0
        # Same resolution the paid-salary report uses: the entry booked against
        # this slip, or the "Salary Slip <month> — <name>" owner-fund row.
        try:
            of_rows = db.execute(
                "SELECT id, source_id, owner_name, details, amount "
                "FROM owner_fund_entries "
                "WHERE amount > 0 AND (source_id = ? OR details LIKE ?)",
                (s["id"], f"Salary Slip {s['salary_month']}%"),
            ).fetchall()
        except Exception:
            of_rows = []
        seen = set()
        for fr in of_rows:
            try:
                fid = int(fr["id"])
            except (TypeError, ValueError):
                continue
            if fid in seen:
                continue
            matched = False
            try:
                if fr["source_id"] not in (None, "") and int(fr["source_id"]) == int(s["id"]):
                    matched = True
            except (TypeError, ValueError):
                matched = False
            if not matched:
                owner = (fr["owner_name"] or "").strip().lower()
                parts = (fr["details"] or "").split("—", 1)
                detail_name = parts[1].strip().lower() if len(parts) > 1 else ""
                matched = bool(_name) and (owner == _name or detail_name == _name)
            if matched:
                seen.add(fid)
                paid += float(fr["amount"] or 0)
        unpaid = round(max(payable - paid, 0.0), 2)
        if unpaid > 0.01:
            _m = s["salary_month"]
            unpaid_by_month[_m] = round(unpaid_by_month.get(_m, 0.0) + unpaid, 2)

    months = {}
    for r in store_rows:
        mid = int(r["id"])
        months[r["salary_month"]] = {
            "month": r["salary_month"],
            "net": round(float(r["net_salary"] or 0), 2),
            "issued": mid in slipped_store_ids or r["salary_month"] in slipped_months,
            "unpaid": unpaid_by_month.get(r["salary_month"], 0.0),
        }
    for s in truth["slips"]:
        if s["salary_month"] not in months:
            months[s["salary_month"]] = {
                "month": s["salary_month"],
                "net": s["total_deducted"],
                "issued": True,
                "unpaid": unpaid_by_month.get(s["salary_month"], 0.0),
            }

    month_list = [months[m] for m in sorted(months)]
    pending = [m for m in month_list if not m["issued"]]
    settled = [m for m in month_list if m["issued"]]

    pending_total = round(sum(m["net"] for m in pending), 2)
    unpaid_total = round(sum(m["unpaid"] for m in month_list), 2)
    balance = truth["outstanding"]
    given = truth["total_given"]
    recovered = truth["total_deducted"]
    # Salary the company still owes = months never run + the part of the run
    # months that was never actually handed over as cash in the office.
    salary_owed = round(pending_total + unpaid_total, 2)
    net_to_driver = round(salary_owed - balance, 2)
    unpaid_months = [m for m in month_list if m["unpaid"] > 0.01]
    unpaid_labels = ", ".join(m["month"] for m in unpaid_months)

    if settled:
        first, last = settled[0]["month"], settled[-1]["month"]
        settled_label = first if first == last else f"{first} - {last}"
    else:
        settled_label = "—"

    pending_labels = ", ".join(m["month"] for m in pending)

    return {
        "statement_date": date.today().isoformat(),
        "driver_name": employee.get("full_name") or employee_id,
        "driver_id": employee_id,
        "designation": employee.get("employee_type") or "Driver",
        "given": given,
        "recovered": recovered,
        "balance": balance,
        "recovery_pct": round(recovered / given * 100, 2) if given > 0 else 0.0,
        "months": list(reversed(month_list)),          # latest first
        "pending": pending,
        "pending_labels": pending_labels,
        "pending_total": pending_total,
        "pending_count": len(pending),
        "unpaid_total": unpaid_total,
        "unpaid_labels": unpaid_labels,
        "unpaid_count": len(unpaid_months),
        "salary_owed": salary_owed,
        "settled_count": len(settled),
        "settled_label": settled_label,
        "net_to_driver": net_to_driver,
        "company_owes": net_to_driver > 0,
    }


# ── Transactions Tab ─────────────────────────────────────────────

def _kata_truth(db, employee_id: str) -> dict:
    """Money-truth statement: advances given vs salary actually deducted.

    Computed live from driver_transactions + salary_slips.total_deductions with a
    fresh per-slip FIFO allocation, so the view never depends on cached
    remaining_amount / is_fully_deducted flags (those go stale when a slip is
    regenerated). Read-only — never writes.
    """
    txns = db.execute(
        "SELECT id, entry_date, salary_month, txn_type, source, given_by, amount, details "
        "FROM driver_transactions WHERE driver_id = ? ORDER BY entry_date ASC, id ASC",
        (employee_id,),
    ).fetchall()
    slips = db.execute(
        "SELECT salary_month, total_deductions, actual_paid_amount, generated_at FROM salary_slips "
        "WHERE driver_id = ? ORDER BY salary_month ASC, id ASC",
        (employee_id,),
    ).fetchall()

    total_given = round(sum(float(t["amount"] or 0) for t in txns), 2)
    slip_rows = [
        {"salary_month": s["salary_month"],
         "total_deducted": round(float(s["total_deductions"] or 0), 2),
         "actual_paid": round(float(s["actual_paid_amount"] or 0), 2),
         "generated_at": str(s["generated_at"] or "")}
        for s in slips
    ]
    total_deducted = round(sum(s["total_deducted"] for s in slip_rows), 2)

    # Per-slip FIFO: each slip's deduction consumes the oldest advances first.
    remaining_by_txn = {int(t["id"]): float(t["amount"] or 0) for t in txns}
    deducted_in: dict = {int(t["id"]): [] for t in txns}
    for s in slip_rows:
        need = s["total_deducted"]
        if need <= 0:
            continue
        for t in txns:
            if need <= 0.001:
                break
            tid = int(t["id"])
            avail = remaining_by_txn[tid]
            if avail <= 0.001:
                continue
            take = min(avail, need)
            remaining_by_txn[tid] = avail - take
            need -= take
            deducted_in[tid].append(s["salary_month"])

    rows = []
    for t in txns:
        amt = float(t["amount"] or 0)
        ded = round(amt - remaining_by_txn[int(t["id"])], 2)
        rem = round(max(amt - ded, 0.0), 2)
        if rem <= 0.01:
            status = "cleared"
        elif ded > 0.01:
            status = "partial"
        else:
            status = "outstanding"
        rows.append({
            "id": int(t["id"]),
            "entry_date": t["entry_date"],
            "salary_month": t["salary_month"],
            "txn_type": t["txn_type"],
            "source": t["source"],
            "given_by": t["given_by"],
            "amount": amt,
            "details": t["details"],
            "deducted": ded,
            "remaining": rem,
            "status": status,
            "deducted_in": deducted_in[int(t["id"])],
        })

    return {
        "rows": rows,
        "slips": slip_rows,
        "total_given": total_given,
        "total_deducted": total_deducted,
        "outstanding": round(max(total_given - total_deducted, 0.0), 2),
    }


def _rebuild_fifo_allocations(db, employee_id: str) -> None:
    """Rebuild the advance-allocation ledger so it matches the money truth.

    Truth = every slip's salary_slips.total_deductions, applied oldest advance
    first, slips in month order. Rewrites driver_transaction_deductions and the
    cached remaining_amount / is_fully_deducted flags on driver_transactions.

    This only repairs the *allocation* bookkeeping — salary amounts, payments and
    slip totals are never touched. Call inside a transaction (POST only).
    """
    txns = db.execute(
        "SELECT id, entry_date, amount, details FROM driver_transactions "
        "WHERE driver_id = ? ORDER BY entry_date ASC, id ASC",
        (employee_id,),
    ).fetchall()
    if not txns:
        return
    slips = db.execute(
        "SELECT id, salary_month, total_deductions FROM salary_slips "
        "WHERE driver_id = ? ORDER BY salary_month ASC, id ASC",
        (employee_id,),
    ).fetchall()

    remaining = {int(t["id"]): round(float(t["amount"] or 0), 2) for t in txns}
    db.execute("DELETE FROM driver_transaction_deductions WHERE driver_id = ?", (employee_id,))

    for s in slips:
        need = round(float(s["total_deductions"] or 0), 2)
        if need <= 0.005:
            continue
        for t in txns:
            if need <= 0.005:
                break
            tid = int(t["id"])
            if remaining[tid] <= 0.005:
                continue
            take = round(min(remaining[tid], need), 2)
            remaining[tid] = round(remaining[tid] - take, 2)
            need = round(need - take, 2)
            db.execute(
                "INSERT INTO driver_transaction_deductions "
                "(driver_id, transaction_id, salary_slip_id, amount_deducted, deduction_date, salary_month, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    employee_id, tid, s["id"], take,
                    (t["entry_date"] or "")[:10] or s["salary_month"],
                    s["salary_month"],
                    f"FIFO: {t['details'] or t['entry_date']}",
                ),
            )

    for t in txns:
        tid = int(t["id"])
        rem = remaining[tid]
        db.execute(
            "UPDATE driver_transactions SET remaining_amount = ?, is_fully_deducted = ? WHERE id = ?",
            (rem, 1 if rem <= 0.005 else 0, tid),
        )


def _driver_hisab_ledger(db, employee_id: str, truth: dict) -> list:
    """Month-by-month running advance ledger — latest month first.

    Each row: salary stored that month, advance given, amount deducted, amount
    actually paid, and the advance balance that remains *after* that month.
    """
    months = {}

    def _slot(m):
        if not m:
            return None
        e = months.get(m)
        if e is None:
            e = months[m] = {
                "salary_month": m, "salary": 0.0, "given": 0.0,
                "deducted": 0.0, "paid": 0.0, "slip_count": 0, "store_id": None,
            }
        return e

    for r in truth["rows"]:
        e = _slot((r["entry_date"] or "")[:7])
        if e:
            e["given"] += r["amount"]
    for s in truth["slips"]:
        e = _slot(s["salary_month"])
        if e:
            e["deducted"] += s["total_deducted"]
            e["paid"] += s["actual_paid"]
            e["slip_count"] += 1
    for sr in db.execute(
        "SELECT id, salary_month, net_salary FROM salary_store WHERE driver_id = ? ORDER BY id ASC",
        (employee_id,),
    ).fetchall():
        e = _slot(sr["salary_month"])
        if e:
            e["salary"] += float(sr["net_salary"] or 0)
            e["store_id"] = sr["id"]  # highest id wins = latest stored version

    balance = 0.0
    out = []
    for m in sorted(months):
        e = months[m]
        for k in ("salary", "given", "deducted", "paid"):
            e[k] = round(e[k], 2)
        balance = round(balance + e["given"] - e["deducted"], 2)
        e["balance_after"] = round(max(balance, 0.0), 2)
        out.append(e)
    out.reverse()
    return out


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
        edit_id = request.form.get("edit_id", "").strip()
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

            if edit_id and edit_id.isdigit():
                old_txn = db.execute("SELECT source FROM driver_transactions WHERE id=? AND driver_id=?", (int(edit_id), eid)).fetchone()
                old_source = old_txn["source"] if old_txn else None
                db.execute(
                    """UPDATE driver_transactions SET entry_date=?, salary_month=?, txn_type=?, source=?, given_by=?, amount=?, details=? WHERE id=? AND driver_id=?""",
                    (form_values["entry_date"], salary_month, txn_type, form_values["source"],
                     form_values["given_by"], amount, form_values["details"], int(edit_id), eid),
                )
                new_source = form_values["source"]
                if old_source != new_source:
                    existing_of = db.execute(
                        "SELECT id FROM owner_fund_entries WHERE source_table='driver_transactions' AND source_id=?",
                        (int(edit_id),),
                    ).fetchone()
                    if new_source == "Owner Fund" and not existing_of:
                        db.execute(
                            """INSERT INTO owner_fund_entries (owner_name, entry_date, amount, received_by, payment_method, transaction_type, details, source_table, source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (form_values["given_by"], form_values["entry_date"], amount,
                             form_values["given_by"], "Cash", "OUT",
                             form_values["details"], "driver_transactions", int(edit_id)),
                        )
                    elif old_source == "Owner Fund" and existing_of:
                        db.execute("DELETE FROM owner_fund_entries WHERE id=?", (existing_of["id"],))
                elif new_source == "Owner Fund":
                    db.execute(
                        """UPDATE owner_fund_entries SET owner_name=?, entry_date=?, amount=?, details=? WHERE source_table='driver_transactions' AND source_id=?""",
                        (form_values["given_by"], form_values["entry_date"], amount, form_values["details"], int(edit_id)),
                    )
                _audit_log(db, "employee_transaction_updated", entity_type="employee_transaction", entity_id=eid, details=f"AED {amount:.2f} / txn#{edit_id}")
                db.commit()
                flash(f"Transaction #{edit_id} updated.", "success")
                return redirect(url_for("hr.employee_transactions", employee_id=eid))
            else:
                result = db.execute(
                    """INSERT INTO driver_transactions (driver_id, entry_date, salary_month, txn_type, source, given_by, amount, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (eid, form_values["entry_date"], salary_month, txn_type, form_values["source"],
                     form_values["given_by"], amount, form_values["details"]),
                )
                new_txn_id = result.lastrowid
                if form_values["source"] == "Owner Fund" and new_txn_id:
                    try:
                        db.execute(
                            """INSERT INTO owner_fund_entries (owner_name, entry_date, amount, received_by, payment_method, transaction_type, details, source_table, source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (form_values["given_by"], form_values["entry_date"], amount,
                             form_values["given_by"], "Cash", "OUT",
                             form_values["details"], "driver_transactions", new_txn_id),
                        )
                    except Exception:
                        pass
                _audit_log(db, "employee_transaction_created", entity_type="employee_transaction", entity_id=eid, details=f"AED {amount:.2f} / {form_values['source']} / {form_values['details']}")
                db.commit()
                flash(f"Transaction of AED {amount:.2f} recorded for {employee['full_name']}.", "success")
                return redirect(url_for("hr.employee_transactions", employee_id=eid))
        except ValidationError as exc:
            flash(str(exc), "error")

    transactions = db.execute(
        """SELECT id, entry_date, salary_month, txn_type, source, given_by, amount, details, created_at FROM driver_transactions WHERE driver_id = ? ORDER BY entry_date DESC, id DESC LIMIT 50""",
        (eid,),
    ).fetchall()

    truth = _kata_truth(db, eid)
    total_advance = truth["total_given"]
    txn_statement = {r["id"]: r for r in truth["rows"]}

    edit_txn = None
    edit_id = request.args.get("edit", "").strip()
    if edit_id and edit_id.isdigit():
        edit_txn = db.execute("SELECT id, driver_id, entry_date, salary_month, txn_type, source, given_by, amount, details FROM driver_transactions WHERE id = ? AND driver_id = ?", (int(edit_id), eid)).fetchone()

    photo_url = _employee_photo_url(current_app._get_current_object(), employee)

    # Fetch current vehicle directly (same logic as edit page)
    current_vehicle = None
    if employee.get("employee_type") in ("Driver", "Crane Operator"):
        veh_row = db.execute(
            "SELECT va.vehicle_id, va.assigned_from, v.plate_no, v.vehicle_type, v.model "
            "FROM vehicle_assignments va JOIN vehicles v ON v.plate_no = va.vehicle_id "
            "WHERE va.driver_id = ? AND va.is_current = 1 LIMIT 1",
            (eid,),
        ).fetchone()
        if not veh_row:
            veh_row = db.execute(
                "SELECT va.vehicle_id, va.assigned_from, v.plate_no, v.vehicle_type, v.model "
                "FROM vehicle_assignments va JOIN vehicles v ON v.plate_no = va.vehicle_id "
                "WHERE va.driver_id = ? ORDER BY va.id DESC LIMIT 1",
                (eid,),
            ).fetchone()
        if not veh_row:
            legacy = db.execute("SELECT vehicle_no FROM drivers WHERE driver_id = ? LIMIT 1", (eid,)).fetchone()
            if legacy and legacy["vehicle_no"]:
                veh_row = db.execute("SELECT plate_no AS vehicle_id, NULL AS assigned_from, plate_no, vehicle_type, model FROM vehicles WHERE plate_no = ? LIMIT 1", (legacy["vehicle_no"],)).fetchone()
                if not veh_row:
                    current_vehicle = {"vehicle_id": legacy["vehicle_no"], "assigned_from": "", "plate_no": legacy["vehicle_no"], "vehicle_type": "", "model": ""}
        if veh_row:
            current_vehicle = dict(veh_row)

    return render_template(
        "hr/employee_detail.html",
        employee=employee,
        photo_url=photo_url,
        active_tab="transactions",
        txn_form=form_values,
        transactions=transactions,
        total_advance=total_advance,
        total_deducted=truth["total_deducted"],
        txn_outstanding=truth["outstanding"],
        txn_statement=txn_statement,
        edit_txn=edit_txn,
        current_vehicle=current_vehicle,
    )


@hr_bp.route("/hr/employees/<employee_id>/transactions/<int:txn_id>/delete", methods=["POST"])
@_login_required("admin")
def employee_transaction_delete(employee_id, txn_id):
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    txn = db.execute("SELECT id, driver_id, entry_date, salary_month, txn_type, source, given_by, amount, details FROM driver_transactions WHERE id=? AND driver_id=?", (txn_id, employee_id)).fetchone()
    if txn is None:
        flash("Transaction not found.", "error")
        return redirect(url_for("hr.employee_transactions", employee_id=employee_id))

    # Check for linked owner fund entry
    owner_fund_entry = db.execute(
        "SELECT id, owner_name, entry_date, amount, received_by, payment_method, details FROM owner_fund_entries WHERE source_table='driver_transactions' AND source_id=?",
        (txn_id,),
    ).fetchone()

    delete_owner_fund = request.form.get("delete_owner_fund") == "yes"
    try:
        db.execute("DELETE FROM driver_transactions WHERE id=? AND driver_id=?", (txn_id, employee_id))
        if delete_owner_fund and owner_fund_entry:
            db.execute("DELETE FROM owner_fund_entries WHERE id=?", (owner_fund_entry["id"],))
            of_detail = f" + owner fund #{owner_fund_entry['id']}"
        else:
            of_detail = ""
        _audit_log(db, "employee_transaction_deleted", entity_type="employee_transaction", entity_id=employee_id, details=f"txn#{txn_id}{of_detail}")
        db.commit()
        if delete_owner_fund and owner_fund_entry:
            flash("Transaction + linked Owner Fund entry deleted.", "info")
        else:
            flash("Transaction deleted.", "info")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting transaction: {e}", "error")
    return redirect(url_for("hr.employee_transactions", employee_id=employee_id))


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
        "SELECT id, driver_id, entry_date, salary_month, ot_month, salary_mode, prorata_start_date, salary_days, daily_rate, monthly_basic_salary, basic_salary, ot_hours, ot_rate, ot_amount, ot_type, ot_trips, personal_vehicle, personal_vehicle_note, net_salary, remarks FROM salary_store WHERE driver_id = ? AND salary_month = ?",
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
            "basic_salary": request.form.get("basic_salary", "").strip(),
            "prorata_start_date": request.form.get("prorata_start_date", "").strip(),
            "prorata_end_date": request.form.get("prorata_end_date", "").strip(),
            "ot_hours": request.form.get("ot_hours", "0").strip() or "0",
            "ot_type": (request.form.get("ot_type", "hours").strip() or "hours").lower(),
            "ot_trips": request.form.get("ot_trips", "0").strip() or "0",
            "personal_vehicle": request.form.get("personal_vehicle", "0").strip() or "0",
            "personal_vehicle_note": request.form.get("personal_vehicle_note", "").strip(),
            "remarks": request.form.get("remarks", "").strip(),
        }
        form["ot_month"] = _previous_month_value(form["salary_month"])
        if form["basic_salary"]:
            driver_like["basic_salary"] = float(form["basic_salary"])
        try:
            preview = _calculate_salary_preview(driver_like, form)
        except ValidationError as exc:
            flash(str(exc), "error")
        else:
            if employee.get("termination_date") and (employee.get("status") or "").lower() == "terminated":
                term_date = employee["termination_date"]
                if term_date < form["salary_month"] + "-01":
                    flash(f"Cannot store salary: employee was terminated on {term_date}. Select a month on or before {term_date[:7]}.", "error")
                    return redirect(url_for("hr.employee_salary_store", employee_id=eid, month=form["salary_month"]))
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
                        ot_amount, ot_type, ot_trips, personal_vehicle, personal_vehicle_note, net_salary, remarks
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(driver_id, salary_month) DO UPDATE SET
                        entry_date = excluded.entry_date, ot_month = excluded.ot_month,
                        salary_mode = excluded.salary_mode, prorata_start_date = excluded.prorata_start_date,
                        salary_days = excluded.salary_days, daily_rate = excluded.daily_rate,
                        monthly_basic_salary = excluded.monthly_basic_salary,
                        basic_salary = excluded.basic_salary, ot_hours = excluded.ot_hours,
                        ot_rate = excluded.ot_rate, ot_amount = excluded.ot_amount,
                        ot_type = excluded.ot_type, ot_trips = excluded.ot_trips,
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
                        preview["ot_amount"], preview["ot_type"],
                        preview["ot_trips"], preview["personal_vehicle"],
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


@hr_bp.route("/hr/employees/<employee_id>/salary-store/<int:store_id>/delete", methods=["POST"])
@_login_required("admin")
def employee_salary_store_delete(employee_id, store_id):
    _touch_admin_workspace("hr")
    ensure_employees_table()
    try:
        db = open_db()
        employee = _fetch_employee(db, employee_id)
        if employee is None:
            flash("Employee not found.", "error")
            return redirect(url_for("hr.employee_list"))

        eid = employee["employee_id"]
        row = db.execute(
            "SELECT id, driver_id, entry_date, salary_month, ot_month, salary_mode, prorata_start_date, salary_days, daily_rate, monthly_basic_salary, basic_salary, ot_hours, ot_rate, ot_amount, ot_type, ot_trips, personal_vehicle, personal_vehicle_note, net_salary, remarks FROM salary_store WHERE id = ? AND driver_id = ?",
            (store_id, eid),
        ).fetchone()
        if row is None:
            flash("Salary store not found.", "error")
        else:
            db.execute("DELETE FROM salary_payments WHERE salary_store_id = ? AND driver_id = ?", (store_id, eid))
            slip_ids = db.execute("SELECT id FROM salary_slips WHERE salary_store_id = ? AND driver_id = ?", (store_id, eid)).fetchall()
            for s in slip_ids:
                deductions_to_reverse = db.execute(
                    "SELECT id, transaction_id, amount_deducted FROM driver_transaction_deductions WHERE salary_slip_id = ?",
                    (s["id"],),
                ).fetchall()
                for ded in deductions_to_reverse:
                    txn = db.execute(
                        "SELECT id, amount, remaining_amount FROM driver_transactions WHERE id = ?",
                        (ded["transaction_id"],),
                    ).fetchone()
                    if txn:
                        current_remaining = float(txn["remaining_amount"] or txn["amount"])
                        new_remaining = round(current_remaining + float(ded["amount_deducted"]), 2)
                        original_amount = float(txn["amount"])
                        db.execute(
                            "UPDATE driver_transactions SET remaining_amount = ?, is_fully_deducted = 0 WHERE id = ?",
                            (min(new_remaining, original_amount), txn["id"]),
                        )
                db.execute("DELETE FROM owner_fund_entries WHERE source_table='salary_slips' AND source_id=?", (s["id"],))
                db.execute("DELETE FROM driver_transaction_deductions WHERE salary_slip_id = ?", (s["id"],))
                db.execute("DELETE FROM salary_slip_deductions WHERE salary_slip_id = ?", (s["id"],))
            db.execute("DELETE FROM salary_slips WHERE salary_store_id = ? AND driver_id = ?", (store_id, eid))
            db.execute("DELETE FROM salary_store WHERE id = ? AND driver_id = ?", (store_id, eid))
            _audit_log(db, "employee_salary_store_deleted", entity_type="salary_store", entity_id=f"{eid}:{row['salary_month']}")
            db.commit()
            from flask import current_app
            driver_row = db.execute("SELECT driver_id, full_name FROM drivers WHERE driver_id = ?", (eid,)).fetchone()
            _regenerate_kata_for_driver(current_app._get_current_object(), db, dict(driver_row) if driver_row else {"driver_id": eid, "full_name": eid})
            flash(f"Salary store for {row['salary_month']} deleted.", "success")
    except Exception as ex:
        flash(f"Error deleting salary store: {ex}", "error")
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

    # ── Driver money truth + running hisab ledger (shown on the slip page) ──
    truth = _kata_truth(db, eid)
    ledger = _driver_hisab_ledger(db, eid, truth)

    salary_rows = db.execute(
        "SELECT id, driver_id, entry_date, salary_month, ot_month, salary_mode, prorata_start_date, salary_days, daily_rate, monthly_basic_salary, basic_salary, ot_hours, ot_rate, ot_amount, ot_type, ot_trips, personal_vehicle, personal_vehicle_note, net_salary, remarks FROM salary_store WHERE driver_id = ? ORDER BY salary_month DESC",
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
        "paid_now": True,
        "deduction_mode": "manual",
        "selected_txn_ids": [],
    }

    if selected_salary_id:
        selected_salary = db.execute(
            "SELECT id, driver_id, entry_date, salary_month, ot_month, salary_mode, prorata_start_date, salary_days, daily_rate, monthly_basic_salary, basic_salary, ot_hours, ot_rate, ot_amount, ot_type, ot_trips, personal_vehicle, personal_vehicle_note, net_salary, remarks FROM salary_store WHERE id = ? AND driver_id = ?",
            (selected_salary_id, eid),
        ).fetchone()
        if selected_salary is not None:
            existing_slip = db.execute(
                """
                SELECT id, driver_id, salary_store_id, salary_month, source_filter, total_deductions, available_advance, remaining_advance, salary_after_deduction, actual_paid_amount, company_balance_due, payment_source, paid_by, net_payable, pdf_path, generated_at FROM salary_slips
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
                # Tick reflects reality: only ticked when cash actually left.
                try:
                    _paid_fund = db.execute(
                        "SELECT 1 FROM owner_fund_entries WHERE source_table = 'salary_slips' "
                        "AND source_id = ? AND amount > 0 LIMIT 1",
                        (existing_slip["id"],),
                    ).fetchone()
                    values["paid_now"] = bool(_paid_fund) or (
                        float(existing_slip["actual_paid_amount"] or 0) > 0
                    )
                except Exception:
                    pass

    # Load driver transactions for selection
    driver_txns = db.execute(
        "SELECT id, driver_id, entry_date, salary_month, txn_type, source, given_by, amount, details FROM driver_transactions WHERE driver_id = ? ORDER BY entry_date ASC",
        (eid,),
    ).fetchall()

    # For each transaction, compute how much has been deducted already
    deducted_txn_ids = set()
    for txn in driver_txns:
        already = float(db.execute(
            "SELECT COALESCE(SUM(amount_deducted), 0) FROM salary_slip_deductions WHERE driver_transaction_id = ?",
            (txn["id"],),
        ).fetchone()[0])
        remaining = float(txn["amount"]) - already
        txn["_already_deducted"] = already
        txn["_remaining"] = max(remaining, 0.0)
        txn["_is_fully_deducted"] = remaining <= 0.001
        if txn["_is_fully_deducted"]:
            deducted_txn_ids.add(txn["id"])

    # If existing slip, pre-select its linked transactions
    selected_txn_ids = set()
    if existing_slip:
        linked = db.execute(
            "SELECT driver_transaction_id FROM salary_slip_deductions WHERE salary_slip_id = ?",
            (existing_slip["id"],),
        ).fetchall()
        selected_txn_ids = {r["driver_transaction_id"] for r in linked}

    if request.method == "POST":
        selected_salary_id = request.form.get("salary_store_id", "").strip()
        deduction_amount = float(request.form.get("deduction_amount", "0").strip() or "0")
        selected_ids_int = []
        values = {
            "deduction_amount": f"{deduction_amount:.2f}",
            "payment_date": request.form.get("payment_date", date.today().isoformat()).strip() or date.today().isoformat(),
            "actual_paid_amount": request.form.get("actual_paid_amount", "").strip(),
            "payment_source": request.form.get("payment_source", PAYMENT_SOURCES[0]).strip() or PAYMENT_SOURCES[0],
            "paid_by": request.form.get("paid_by", "").strip(),
            "payment_notes": request.form.get("payment_notes", "").strip(),
            # Checkbox semantics: the real form always sends paid_now_submitted,
            # so an untick means "cash never left the office". Anything without
            # the flag (older clients, API callers) keeps the old behaviour.
            "paid_now": (
                request.form.get("paid_now") in ("on", "1", "true", "True")
                if request.form.get("paid_now_submitted")
                else True
            ),
            "deduction_mode": "manual",
            "selected_txn_ids": [],
        }

        if not selected_salary_id:
            flash("Select a stored salary month first.", "error")
        else:
            selected_salary = db.execute(
                "SELECT id, driver_id, entry_date, salary_month, ot_month, salary_mode, prorata_start_date, salary_days, daily_rate, monthly_basic_salary, basic_salary, ot_hours, ot_rate, ot_amount, ot_type, ot_trips, personal_vehicle, personal_vehicle_note, net_salary, remarks FROM salary_store WHERE id = ? AND driver_id = ?",
                (selected_salary_id, eid),
            ).fetchone()
            existing_slip = db.execute(
                """
                SELECT id, driver_id, salary_store_id, salary_month, source_filter, total_deductions, available_advance, remaining_advance, salary_after_deduction, actual_paid_amount, company_balance_due, payment_source, paid_by, net_payable, pdf_path, generated_at FROM salary_slips
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
                        company = db.execute("SELECT company_name, legal_name, trade_license_no, trade_license_expiry, trn_no, vat_status, address, phone_number, email, bank_name, bank_account_name, bank_account_number, iban, swift_code, invoice_terms, base_currency, logo_data, logo_type, theme_color FROM company_profile LIMIT 1").fetchone()
                        company_profile = dict(company) if company else None

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
                            result = db.execute(
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
                            slip_id = result.lastrowid
                            if not slip_id:
                                # sqlite adapter exposes no lastrowid — re-select
                                # the slip we just created (same store + driver).
                                _slip_ref = db.execute(
                                    "SELECT id FROM salary_slips WHERE salary_store_id = ? "
                                    "AND driver_id = ? ORDER BY id DESC LIMIT 1",
                                    (selected_salary["id"], eid),
                                ).fetchone()
                                slip_id = _slip_ref["id"] if _slip_ref else None

                        # Save linked transactions to salary_slip_deductions
                        db.execute("DELETE FROM salary_slip_deductions WHERE salary_slip_id = ?", (slip_id,))
                        if selected_ids_int:
                            for txn_id in selected_ids_int:
                                txn = db.execute("SELECT id, driver_id, entry_date, salary_month, txn_type, source, given_by, amount, details FROM driver_transactions WHERE id = ? AND driver_id = ?", (txn_id, eid)).fetchone()
                                if txn:
                                    already = float(db.execute(
                                        "SELECT COALESCE(SUM(amount_deducted), 0) FROM salary_slip_deductions WHERE driver_transaction_id = ?",
                                        (txn["id"],),
                                    ).fetchone()[0])
                                    remaining = max(float(txn["amount"]) - already, 0.0)
                                    if remaining > 0.001:
                                        db.execute(
                                            "INSERT INTO salary_slip_deductions (salary_slip_id, driver_transaction_id, amount_deducted) VALUES (?,?,?)",
                                            (slip_id, txn["id"], remaining),
                                        )

                        fund_details = (
                            f"Salary Slip {selected_salary['salary_month']} — "
                            f"{employee['full_name']}"
                        )
                        # Owner Fund OUT entry is booked ONLY when the cash
                        # actually left the office. Tick off "Office mein cash
                        # diya" and the slip still generates, but nothing is
                        # marked paid — the amount simply stays owed to the
                        # driver (instead of falsely showing it was handed over).
                        if values["payment_source"] == "Owner Fund" and values["paid_now"]:
                            slip_row_check = db.execute("SELECT id, driver_id, salary_store_id, salary_month, source_filter, total_deductions, available_advance, remaining_advance, salary_after_deduction, actual_paid_amount, company_balance_due, payment_source, paid_by, net_payable, pdf_path, generated_at FROM salary_slips WHERE id = ?", (slip_id,)).fetchone()
                            of_amount = float(salary_after_deduction)
                            # Reuse this month's payment instead of duplicating it:
                            # either the entry already linked to this slip, or an
                            # orphan left behind when an older slip was deleted
                            # (same payee + same month + same amount) — re-point it.
                            existing_of = db.execute(
                                "SELECT id, source_id FROM owner_fund_entries "
                                "WHERE source_table='salary_slips' "
                                "AND (source_id = ? OR (details = ? AND ABS(amount - ?) < 0.01)) "
                                "ORDER BY id LIMIT 1",
                                (slip_id, fund_details, of_amount),
                            ).fetchone()
                            if existing_of:
                                if existing_of["source_id"] != slip_id:
                                    db.execute(
                                        "UPDATE owner_fund_entries SET source_id=? WHERE id=?",
                                        (slip_id, existing_of["id"]),
                                    )
                            else:
                                of_paid_by = values["paid_by"] or employee["full_name"]
                                db.execute(
                                    """INSERT INTO owner_fund_entries (owner_name, entry_date, amount, received_by, payment_method, transaction_type, details, source_table, source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                    (of_paid_by, values["payment_date"], of_amount,
                                     of_paid_by, "Cash", "OUT",
                                     fund_details,
                                     "salary_slips", slip_id),
                                )
                        elif not values["paid_now"]:
                            # Cash never left the office — pull back the payment
                            # this flow booked earlier for this exact slip.
                            stale_of = db.execute(
                                "SELECT id FROM owner_fund_entries "
                                "WHERE source_table='salary_slips' AND source_id = ? "
                                "AND details = ?",
                                (slip_id, fund_details),
                            ).fetchall()
                            for _sf in stale_of:
                                db.execute("DELETE FROM owner_fund_entries WHERE id = ?", (_sf["id"],))
                            if stale_of:
                                _audit_log(
                                    db, "employee_salary_slip_payment_cancelled",
                                    entity_type="salary_slip",
                                    entity_id=f"{eid}:{selected_salary['salary_month']}",
                                    details=(f"Owner unticked paid — AED {salary_after_deduction:.2f} "
                                             f"not handed over, salary stays owed"),
                                )

                        slip_row = db.execute("SELECT id, driver_id, salary_store_id, salary_month, source_filter, total_deductions, available_advance, remaining_advance, salary_after_deduction, actual_paid_amount, company_balance_due, payment_source, paid_by, net_payable, pdf_path, generated_at FROM salary_slips WHERE id = ?", (slip_id,)).fetchone()
                        driver_display = {"driver_id": eid, "full_name": employee["full_name"],
                                          "basic_salary": employee["basic_salary"] or 0,
                                          "vehicle_no": "", "shift": employee.get("shift", ""),
                                          "duty_start": employee.get("join_date", "")}

                        dr = db.execute("SELECT vehicle_no, photo_name, photo_data, photo_content_type FROM drivers WHERE driver_id=?", (eid,)).fetchone()
                        if dr:
                            driver_display["vehicle_no"] = dr["vehicle_no"] or ""
                            driver_display["photo_data"] = dr["photo_data"] or ""
                            driver_display["photo_name"] = dr["photo_name"] or ""

                        if not driver_display.get("photo_data"):
                            emp_photo = employee.get("photo_data") or ""
                            if emp_photo:
                                driver_display["photo_data"] = emp_photo
                                driver_display["photo_name"] = employee.get("photo_name") or ""

                        generated_dir = current_app.config["GENERATED_DIR"]
                        slip_output_dir = str(Path(generated_dir) / "salary_slips")
                        _ap = float(salary_after_deduction) if values["paid_now"] else 0.0
                        pdf_path = generate_salary_slip_pdf(
                            driver_display,
                            selected_salary,
                            {
                                "available_advance": float(available_advance),
                                "deduction_amount": float(deduction_amount),
                                "remaining_advance": float(remaining_advance),
                                "salary_after_deduction": float(salary_after_deduction),
                                "actual_paid_amount": _ap,
                                "company_balance_due": max(float(salary_after_deduction) - _ap, 0.0),
                                "payment_source": values["payment_source"],
                                "paid_by": values["paid_by"] or "",
                                "net_payable": float(salary_after_deduction),
                                "_vehicle_no": (dr["vehicle_no"] or "") if dr else "",
                                "_photo_name": driver_display.get("photo_name", ""),
                                "_photo_data": driver_display.get("photo_data", ""),
                            },
                            slip_output_dir,
                            current_app.config["STATIC_ASSETS_DIR"],
                            generated_dir,
                            company_profile=company_profile,
                        )
                        relative_pdf = Path(pdf_path).relative_to(current_app.config["GENERATED_DIR"]).as_posix() if pdf_path else ""
                        db.execute("UPDATE salary_slips SET pdf_path=? WHERE id=?", (relative_pdf, slip_id))
                        _audit_log(db, "employee_salary_slip_generated", entity_type="salary_slip",
                                   entity_id=f"{eid}:{selected_salary['salary_month']}",
                                   details=f"Deduction AED {deduction_amount:.2f} / Payable AED {salary_after_deduction:.2f}")
                        # Rebuild the advance-allocation ledger straight from the
                        # truth (each slip's total_deductions, oldest advance first).
                        # This replaces the old reversal + FIFO pair, which piled up
                        # duplicate rows on every regenerate and left stale
                        # remaining_amount / is_fully_deducted flags behind.
                        _rebuild_fifo_allocations(db, eid)
                        db.commit()
                        flash(f"Salary slip generated for {selected_salary['salary_month']}.", "success")
                        return redirect(url_for("hr.employee_salary_slip", employee_id=eid))

    photo_url = _employee_photo_url(current_app._get_current_object(), employee)

    slip_existing_deduction = float(existing_slip["total_deductions"]) if existing_slip else 0.0
    slip_hero_salary = float(selected_salary["net_salary"]) if selected_salary else (
        float(salary_rows[0]["net_salary"]) if salary_rows else 0.0
    )

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
        slip_driver_txns=driver_txns,
        slip_selected_txn_ids=selected_txn_ids,
        slip_truth=truth,
        slip_ledger=ledger,
        slip_existing_deduction=slip_existing_deduction,
        slip_hero_salary=slip_hero_salary,
    )


@hr_bp.route("/hr/employees/<employee_id>/salary-slip/<int:store_id>/delete", methods=["GET", "POST"])
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
        "SELECT id, driver_id, salary_store_id, salary_month, source_filter, total_deductions, available_advance, remaining_advance, salary_after_deduction, actual_paid_amount, company_balance_due, payment_source, paid_by, net_payable, pdf_path, generated_at FROM salary_slips WHERE salary_store_id = ? AND driver_id = ?",
        (store_id, eid),
    ).fetchone()
    if slip is None:
        flash("Salary slip not found.", "error")
        return redirect(url_for("hr.employee_salary_slip", employee_id=eid, salary_store_id=store_id))

    owner_fund_entry = db.execute(
        "SELECT id, owner_name, entry_date, amount, received_by, payment_method, details FROM owner_fund_entries WHERE source_table='salary_slips' AND source_id=?",
        (slip["id"],),
    ).fetchone()

    if request.method == "GET":
        # Confirm page: shows the slip and asks whether the linked Owner Fund
        # payment entry should be deleted as well (kept when not confirmed).
        return render_template(
            "hr/delete_transaction_confirm.html",
            txn=slip,
            is_salary_slip=True,
            owner_fund_entry=owner_fund_entry,
            employee_id=eid,
        )

    delete_owner_fund = request.form.get("delete_owner_fund") == "yes"

    # ── Reverse FIFO deductions: restore remaining_amount on transactions ──
    deductions_to_reverse = db.execute(
        "SELECT id, transaction_id, amount_deducted FROM driver_transaction_deductions WHERE salary_slip_id = ?",
        (slip["id"],),
    ).fetchall()
    reversed_count = 0
    for ded in deductions_to_reverse:
        txn = db.execute(
            "SELECT id, amount, remaining_amount, is_fully_deducted FROM driver_transactions WHERE id = ?",
            (ded["transaction_id"],),
        ).fetchone()
        if txn:
            current_remaining = float(txn["remaining_amount"] or txn["amount"])
            new_remaining = round(current_remaining + float(ded["amount_deducted"]), 2)
            original_amount = float(txn["amount"])
            db.execute(
                "UPDATE driver_transactions SET remaining_amount = ?, is_fully_deducted = ? WHERE id = ?",
                (min(new_remaining, original_amount), 1 if new_remaining <= 0 else 0, txn["id"]),
            )
            reversed_count += 1

    db.execute("DELETE FROM driver_transaction_deductions WHERE salary_slip_id = ?", (slip["id"],))
    db.execute("DELETE FROM salary_slip_deductions WHERE salary_slip_id = ?", (slip["id"],))
    if delete_owner_fund and owner_fund_entry:
        db.execute("DELETE FROM owner_fund_entries WHERE id=?", (owner_fund_entry["id"],))
        of_detail = f" + owner fund #{owner_fund_entry['id']}"
    else:
        of_detail = " (Owner Fund entry kept)" if owner_fund_entry else ""
    db.execute("DELETE FROM salary_slips WHERE id = ?", (slip["id"],))
    # Rebuild remaining advances from truth so flags stay consistent after a delete.
    _rebuild_fifo_allocations(db, eid)
    _audit_log(db, "employee_salary_slip_deleted", entity_type="salary_slip",
                entity_id=f"{eid}:{slip['salary_month']}",
                details=f"store#{store_id}{of_detail}")
    db.commit()
    reversal_note = f" ({reversed_count} deduction(s) reversed)" if reversed_count > 0 else ""
    flash(f"Salary slip for {slip['salary_month']} deleted.{of_detail}{reversal_note}", "success")
    return redirect(url_for("hr.employee_salary_slip", employee_id=eid, salary_store_id=store_id))


@hr_bp.route("/hr/employees/<employee_id>/salary-slip/<int:store_id>/salary-card")
@_login_required("admin")
def employee_salary_card(employee_id, store_id):
    """Generate a simple visual salary card PDF for sharing with driver via WhatsApp."""
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()
    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))
    eid = employee["employee_id"]

    slip = db.execute(
        "SELECT id, driver_id, salary_store_id, salary_month, total_deductions, available_advance, remaining_advance, salary_after_deduction, actual_paid_amount, company_balance_due, payment_source, paid_by, net_payable FROM salary_slips WHERE salary_store_id = ? AND driver_id = ?",
        (store_id, eid),
    ).fetchone()
    if slip is None:
        flash("Salary slip not found.", "error")
        return redirect(url_for("hr.employee_salary_slip", employee_id=eid, salary_store_id=store_id))

    salary_row = db.execute(
        "SELECT * FROM salary_store WHERE driver_id = ? AND id = ?",
        (eid, store_id),
    ).fetchone()

    # Fetch advances
    all_advances = db.execute(
        "SELECT id, entry_date, salary_month, txn_type, source, given_by, amount, details, remaining_amount, is_fully_deducted FROM driver_transactions WHERE driver_id = ? ORDER BY entry_date ASC, id ASC",
        (eid,),
    ).fetchall()

    # Fetch THIS slip's per-transaction deductions
    this_slip_deductions = db.execute(
        "SELECT transaction_id, amount_deducted FROM driver_transaction_deductions WHERE salary_slip_id = ?",
        (slip["id"],),
    ).fetchall()
    this_slip_ded_map = {}
    for d in this_slip_deductions:
        tid = d["transaction_id"]
        this_slip_ded_map[tid] = this_slip_ded_map.get(tid, 0.0) + float(d["amount_deducted"])

    # Fetch ALL deduction history per transaction (across all slips)
    all_deductions = db.execute(
        "SELECT d.transaction_id, d.amount_deducted, d.salary_month FROM driver_transaction_deductions d JOIN salary_slips ss ON ss.id = d.salary_slip_id WHERE ss.driver_id = ? ORDER BY d.salary_month ASC",
        (eid,),
    ).fetchall()
    all_ded_map = {}
    for d in all_deductions:
        tid = d["transaction_id"]
        if tid not in all_ded_map:
            all_ded_map[tid] = {"total": 0.0, "months": []}
        all_ded_map[tid]["total"] += float(d["amount_deducted"])
        all_ded_map[tid]["months"].append(d["salary_month"])

    # Build advance summary with deduction info
    advances_list = []
    total_adv = 0.0
    for a in all_advances:
        amt = float(a["amount"])
        rem = float(a["remaining_amount"] or amt)
        ded_total = all_ded_map.get(a["id"], {}).get("total", 0.0)
        ded_this_month = this_slip_ded_map.get(a["id"], 0.0)
        total_adv += amt
        advances_list.append({
            "entry_date": a["entry_date"],
            "amount": amt,
            "deducted_total": ded_total,
            "deducted_this_month": ded_this_month,
            "remaining": rem,
            "details": a["details"],
            "source": a["source"],
            "deducted_in_months": all_ded_map.get(a["id"], {}).get("months", []),
        })

    # Month-wise deduction summary
    month_deductions = db.execute(
        "SELECT ss.salary_month, ss.total_deductions FROM salary_slips ss WHERE ss.driver_id = ? ORDER BY ss.salary_month ASC",
        (eid,),
    ).fetchall()

    basic = float(salary_row["basic_salary"] or 0) if salary_row else 0.0
    ot = float(salary_row["ot_amount"] or 0) if salary_row else 0.0
    pv = float(salary_row["personal_vehicle"] or 0) if salary_row else 0.0
    net_sal = float(salary_row["net_salary"] or 0) if salary_row else 0.0
    this_ded = float(slip["total_deductions"] or 0)
    net_paid = float(slip["actual_paid_amount"] or 0)
    outstanding = float(slip["company_balance_due"] or 0)

    # Calculate previous balance (total remaining before this slip)
    total_remaining_before = sum(a["amount"] for a in advances_list) - sum(a["deducted_total"] for a in advances_list)
    prev_balance = max(total_remaining_before, 0.0)

    company = db.execute("SELECT company_name, logo_data, logo_type, theme_color FROM company_profile LIMIT 1").fetchone()
    company_profile = dict(company) if company else None

    from ..pdf_service import generate_driver_salary_card_pdf
    output_dir = Path(current_app.config["GENERATED_DIR"]) / "salary_cards"
    pdf_path = generate_driver_salary_card_pdf(
        driver_name=employee["full_name"],
        driver_id=eid,
        month=slip["salary_month"],
        basic_salary=basic,
        ot_amount=ot,
        personal_vehicle=pv,
        total_salary=net_sal,
        total_advances=total_adv,
        total_deducted=this_ded,
        net_paid=net_paid,
        outstanding_balance=outstanding,
        previous_balance=prev_balance,
        advances_list=advances_list,
        month_deductions=[dict(m) for m in month_deductions],
        output_dir=str(output_dir),
        assets_dir=current_app.config["STATIC_ASSETS_DIR"],
        company_profile=company_profile,
    )
    if pdf_path:
        rel = Path(pdf_path).relative_to(current_app.config["GENERATED_DIR"]).as_posix()
        pdf_url = url_for("generated_file", filename=rel)
        return redirect(pdf_url)

    flash("Error generating salary card.", "error")
    return redirect(url_for("hr.employee_salary_slip", employee_id=eid, salary_store_id=store_id))


@hr_bp.route("/hr/employees/<employee_id>/salary-slip/<int:store_id>/deduction-statement")
@_login_required("admin")
def employee_deduction_statement(employee_id, store_id):
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()
    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))
    eid = employee["employee_id"]
    salary_store_row = db.execute("SELECT id, driver_id, entry_date, salary_month, ot_month, salary_mode, prorata_start_date, salary_days, daily_rate, monthly_basic_salary, basic_salary, ot_hours, ot_rate, ot_amount, ot_type, ot_trips, personal_vehicle, personal_vehicle_note, net_salary, remarks FROM salary_store WHERE id = ? AND driver_id = ?", (store_id, eid)).fetchone()
    if not salary_store_row:
        flash("Salary store not found.", "error")
        return redirect(url_for("hr.employee_salary_slip", employee_id=eid))
    slip = db.execute("SELECT id, driver_id, salary_store_id, salary_month, source_filter, total_deductions, available_advance, remaining_advance, salary_after_deduction, actual_paid_amount, company_balance_due, payment_source, paid_by, net_payable, pdf_path, generated_at FROM salary_slips WHERE salary_store_id = ? AND driver_id = ? ORDER BY id DESC LIMIT 1", (store_id, eid)).fetchone()
    if not slip:
        flash("Salary slip not found. Generate slip first.", "error")
        return redirect(url_for("hr.employee_salary_slip", employee_id=eid, salary_store_id=store_id))
    driver_display = {"driver_id": eid, "full_name": employee["full_name"], "basic_salary": employee["basic_salary"] or 0}
    company = db.execute("SELECT company_name, legal_name, trade_license_no, trade_license_expiry, trn_no, vat_status, address, phone_number, email, bank_name, bank_account_name, bank_account_number, iban, swift_code, invoice_terms, base_currency, logo_data, logo_type, theme_color FROM company_profile LIMIT 1").fetchone()
    company_profile = dict(company) if company else None
    # Get deducted transactions
    deducted = db.execute(
        """SELECT dt.*, sd.amount_deducted
           FROM salary_slip_deductions sd
           JOIN driver_transactions dt ON dt.id = sd.driver_transaction_id
           WHERE sd.salary_slip_id = ?""",
        (slip["id"],),
    ).fetchall()
    from ..pdf_service import generate_deduction_statement_pdf
    pdf_path = generate_deduction_statement_pdf(
        driver_display, salary_store_row, slip, deducted,
        str(Path(current_app.config["GENERATED_DIR"]) / "salary_slips"),
        current_app.config["STATIC_ASSETS_DIR"],
        company_profile=company_profile,
    )
    if pdf_path:
        rel = Path(pdf_path).relative_to(current_app.config["GENERATED_DIR"]).as_posix()
        return redirect(url_for("generated_file", filename=rel))
    flash("Could not generate deduction statement.", "error")
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

    # Money-truth statement — computed every time (latest, month-independent)
    truth = _kata_truth(db, eid)
    kata_total_given = truth["total_given"]
    kata_total_deducted = truth["total_deducted"]
    kata_outstanding = truth["outstanding"]
    soa = _build_soa(db, eid, employee, truth)

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
    deduction_history = []

    if selected_month:
        active_entries, closed_entries, summary_ret = _driver_kata_month_data(db, eid, selected_month)
        entries = active_entries + closed_entries
        summary = summary_ret

        salary_row = db.execute(
            "SELECT id, driver_id, entry_date, salary_month, ot_month, salary_mode, prorata_start_date, salary_days, daily_rate, monthly_basic_salary, basic_salary, ot_hours, ot_rate, ot_amount, ot_type, ot_trips, personal_vehicle, personal_vehicle_note, net_salary, remarks FROM salary_store WHERE driver_id = ? AND salary_month = ?",
            (eid, selected_month),
        ).fetchone()

        slip_row = db.execute(
            "SELECT id, driver_id, salary_store_id, salary_month, source_filter, total_deductions, available_advance, remaining_advance, salary_after_deduction, actual_paid_amount, company_balance_due, payment_source, paid_by, net_payable, pdf_path, generated_at FROM salary_slips WHERE driver_id = ? AND salary_month = ? ORDER BY id DESC LIMIT 1",
            (eid, selected_month),
        ).fetchone()

        month_start = f"{selected_month}-01"
        _y, _m = int(selected_month[:4]), int(selected_month[5:7])
        next_month_start = f"{_y + (1 if _m == 12 else 0)}-{(_m % 12) + 1:02d}-01"

        given_before = round(sum(r["amount"] for r in truth["rows"] if (r["entry_date"] or "")[:10] < month_start), 2)
        given_through = round(sum(r["amount"] for r in truth["rows"] if (r["entry_date"] or "")[:10] < next_month_start), 2)

        prev_deductions = round(sum(s["total_deducted"] for s in truth["slips"] if s["salary_month"] < selected_month), 2)
        deducted_through = round(sum(s["total_deducted"] for s in truth["slips"] if s["salary_month"] <= selected_month), 2)

        this_deduction = round(deducted_through - prev_deductions, 2)

        # Month-scoped running balance (statement view for the selected month)
        kata_prev_remaining = max(given_before - prev_deductions, 0.0)
        kata_this_deduction = this_deduction
        kata_remaining = max(given_through - deducted_through, 0.0)

        # Latest all-time truth — independent of the selected month
        kata_total_given = truth["total_given"]
        kata_total_deducted = truth["total_deducted"]
        kata_outstanding = truth["outstanding"]

        kata_advances = [
            {
                "entry_date": r["entry_date"],
                "amount": r["amount"],
                "source": r["source"],
                "given_by": r["given_by"],
                "details": r["details"],
                "remaining": r["remaining"],
                "deducted": r["deducted"],
                "status": r["status"],
                "deducted_in": r["deducted_in"],
            }
            for r in truth["rows"]
        ]

        # Deduction history: month-wise from actual salary slips (always present)
        _running = 0.0
        _history_asc = []
        for _s in truth["slips"]:
            _running = round(_running + _s["total_deducted"], 2)
            _history_asc.append({
                "salary_month": _s["salary_month"],
                "txn_date": (_s["generated_at"] or "")[:10],
                "txn_details": "Salary slip deduction",
                "txn_amount": _s["total_deducted"],
                "amount_deducted": _s["total_deducted"],
                "running": _running,
            })
        deduction_history = list(reversed(_history_asc))

    pdf_url = None
    from ..pdf_service import generate_driver_soa_pdf

    driver_display = {
        "driver_id": eid,
        "full_name": employee["full_name"],
        "basic_salary": employee["basic_salary"] or 0,
        "employee_type": employee.get("employee_type") or "Driver",
    }
    company = db.execute("SELECT company_name, legal_name, trade_license_no, trade_license_expiry, trn_no, vat_status, address, phone_number, email, bank_name, bank_account_name, bank_account_number, iban, swift_code, invoice_terms, base_currency, logo_data, logo_type, theme_color FROM company_profile LIMIT 1").fetchone()
    company_profile = dict(company) if company else None

    pdf_path = generate_driver_soa_pdf(
        driver_display, soa, company_profile,
        str(Path(current_app.config["GENERATED_DIR"]) / "kata_pdfs"),
        current_app.config["STATIC_ASSETS_DIR"],
    )
    if pdf_path:
        rel = Path(pdf_path).relative_to(current_app.config["GENERATED_DIR"]).as_posix()
        pdf_url = url_for("generated_file", filename=rel)

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
        kata_total_given=kata_total_given,
        kata_total_deducted=kata_total_deducted,
        kata_outstanding=kata_outstanding,
        kata_deduction_history=deduction_history,
        kata_pdf_url=pdf_url,
        soa=soa,
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

    # Get vehicles if table exists, otherwise empty list
    try:
        vehicles = db.execute("SELECT plate_no, vehicle_type, model FROM vehicles WHERE status = 'Active' ORDER BY plate_no").fetchall()
    except Exception:
        vehicles = []
    assigned = db.execute("SELECT vehicle_id FROM vehicle_assignments WHERE driver_id = ? AND is_current = 1 LIMIT 1", (employee_id,)).fetchone()
    assigned_vehicle = assigned["vehicle_id"] if assigned else ""
    if not assigned_vehicle:
        legacy = db.execute("SELECT vehicle_no FROM drivers WHERE driver_id = ? LIMIT 1", (employee_id,)).fetchone()
        if legacy and legacy["vehicle_no"]:
            assigned_vehicle = legacy["vehicle_no"]

    if request.method == "POST":
        values = employee_form_data()
        values["employee_id"] = employee_id

        # Upload photo FIRST so it survives validation errors
        uploaded_photo = None
        try:
            uploaded_photo = save_employee_photo(
                current_app._get_current_object(), employee_id,
                request.form.get("full_name", "").strip().title(),
                request.files.get("photo_file"))
        except Exception as exc:
            flash(f"Photo upload failed: {exc}", "error")

        errors = validate_employee_form(values)
        if errors:
            for err in errors:
                flash(err, "error")
            assigned_vehicle = values.get("vehicle_id", "")
            # Save photo to DB even if other fields fail validation
            if uploaded_photo:
                try:
                    db.execute(
                        "UPDATE employees SET photo_name=?, photo_data=?, photo_content_type=?, updated_at=CURRENT_TIMESTAMP WHERE UPPER(employee_id)=?",
                        (uploaded_photo["photo_name"], uploaded_photo["photo_data"],
                         uploaded_photo["photo_content_type"], employee_id),
                    )
                    db.commit()
                except Exception:
                    db.rollback()
        else:
            salary = float(values["basic_salary"])
            ot_rate = float(values.get("ot_rate", 0) or 0)
            if values.get("status", "").lower() == "terminated":
                if not values.get("termination_date"):
                    values["termination_date"] = date.today().isoformat()
            else:
                values["termination_date"] = ""

            try:
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
                        status=?, termination_date=?, remarks=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE UPPER(employee_id)=?
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
                        values["status"], values["termination_date"] or None, values["remarks"] or None,
                        employee_id,
                    ),
                )
            except Exception as exc:
                flash(f"Database error updating employee: {exc}", "error")
                db.rollback()
                return redirect(url_for("hr.employee_edit", employee_id=employee_id))

            # Always sync status/termination to drivers table so sync_drivers_to_employees doesn't revert it
            try:
                db.execute(
                    "UPDATE drivers SET status=?, termination_date=?, basic_salary=?, ot_rate=?, shift=?, full_name=?, phone_number=? WHERE UPPER(driver_id)=?",
                    (values["status"], values["termination_date"] or None, salary, ot_rate,
                     values["shift"] or "Morning", values["full_name"], values["phone_number"] or None, employee_id),
                )
            except Exception:
                pass  # drivers table may not exist

            if values.get("employee_type") in ("Driver", "Crane Operator"):
                if values["vehicle_id"]:
                    db.execute(
                        "UPDATE vehicle_assignments SET is_current = 0, assigned_until = ? WHERE driver_id = ? AND is_current = 1",
                        (date.today().isoformat(), employee_id),
                    )
                    existing = db.execute(
                        "SELECT id FROM vehicle_assignments WHERE vehicle_id = ? AND driver_id = ? AND is_current = 1",
                        (values["vehicle_id"], employee_id),
                    ).fetchone()
                    if not existing:
                        db.execute(
                            "INSERT INTO vehicle_assignments (vehicle_id, driver_id, assigned_from, is_current) VALUES (?, ?, ?, 1)",
                            (values["vehicle_id"], employee_id, date.today().isoformat()),
                        )
                    db.execute("UPDATE drivers SET vehicle_no = ? WHERE driver_id = ?", (values["vehicle_id"], employee_id))
                else:
                    db.execute(
                        "UPDATE vehicle_assignments SET is_current = 0, assigned_until = ? WHERE driver_id = ? AND is_current = 1",
                        (date.today().isoformat(), employee_id),
                    )
                    db.execute("UPDATE drivers SET vehicle_no = '' WHERE driver_id = ?", (employee_id,))

            if values.get("employee_type") == "Field Staff":
                _sync_employee_to_field_staff(db, employee_id, values["full_name"], values["phone_number"], values["status"])
            else:
                try:
                    db.execute("DELETE FROM field_staff WHERE staff_id = ?", (employee_id,))
                except Exception:
                    pass

            _audit_log(db, "employee_updated", entity_type="employee", entity_id=employee_id, details=f"{values['full_name']} updated")
            db.commit()

            # Verify the update took effect
            check = _fetch_employee(db, employee_id)
            current_app.logger.info(f"Employee {employee_id} updated: status={check['status'] if check else 'NOT FOUND'}")
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
        vehicles=vehicles,
        assigned_vehicle=assigned_vehicle,
    )


@hr_bp.route("/hr/employees/<employee_id>/delete", methods=["POST"])
@_login_required("admin")
def employee_delete(employee_id):
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()
    employee_id = employee_id.strip().upper()

    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))

    try:
        # Clean up related data
        db.execute("DELETE FROM driver_transaction_deductions WHERE driver_id = ?", (employee_id,))
        db.execute("DELETE FROM salary_slip_deductions WHERE driver_id = ?", (employee_id,))
        db.execute("DELETE FROM salary_store WHERE driver_id = ?", (employee_id,))
        db.execute("DELETE FROM salary_slips WHERE driver_id = ?", (employee_id,))
        db.execute("DELETE FROM salary_payments WHERE driver_id = ?", (employee_id,))
        db.execute("DELETE FROM driver_transactions WHERE driver_id = ?", (employee_id,))
        db.execute("DELETE FROM vehicle_assignments WHERE driver_id = ?", (employee_id,))
        db.execute("DELETE FROM drivers WHERE driver_id = ?", (employee_id,))
        db.execute("DELETE FROM cash_receipts WHERE staff_id = ?", (employee_id,))
        db.execute("DELETE FROM field_staff WHERE staff_id = ?", (employee_id,))
        db.execute("DELETE FROM employees WHERE employee_id = ?", (employee_id,))
        db.execute("DELETE FROM audit_logs WHERE entity_id = ? AND entity_type = 'employee'", (employee_id,))
        db.commit()
        _audit_log(db, "employee_deleted", entity_type="employee", entity_id=employee_id, details=f"{employee['full_name']} deleted")
        flash(f"Employee {employee['full_name']} ({employee_id}) deleted permanently.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting employee: {e}", "error")

    return redirect(url_for("hr.employee_list"))


@hr_bp.route("/hr/employees/<employee_id>/restore", methods=["GET", "POST"])
@_login_required("admin")
def employee_restore(employee_id):
    import traceback
    try:
        _touch_admin_workspace("hr")
        ensure_employees_table()
        db = open_db()
        employee_id = employee_id.strip().upper()

        existing = _fetch_employee(db, employee_id)
        if existing:
            flash(f"Employee {employee_id} already exists.", "success")
            return redirect(url_for("hr.employee_edit", employee_id=employee_id))

        tech = db.execute("SELECT id, technician_code, party_code, user_id, password_hash, phone_number, specialization, status FROM technicians WHERE technician_code = ?", (employee_id,)).fetchone()
        if not tech:
            flash(f"No data found for {employee_id} in technicians table.", "error")
            return redirect(url_for("hr.employee_list"))

        name = tech["specialization"] or f"Staff {employee_id}"
        phone = tech["phone_number"] or ""
        username = tech["user_id"] or employee_id.lower()
        pw_hash = tech["password_hash"] or generate_password_hash("changeme123")
        is_active = 1 if tech.get("status") == "Active" else 0
        raw_created = tech.get("created_at")
        if isinstance(raw_created, (datetime, date)):
            join_date = raw_created.strftime("%Y-%m-%d")
        elif raw_created:
            join_date = str(raw_created).split(" ")[0]
        else:
            join_date = date.today().isoformat()

        try:
            db.execute("""
                INSERT INTO field_staff (staff_id, full_name, phone, username, password_hash, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (employee_id, name, phone, username, pw_hash, is_active))
        except Exception as e:
            current_app.logger.warning("restore field_staff: %s", e)

        try:
            db.execute("""
                INSERT INTO employees (employee_id, full_name, phone_number, employee_type, department, designation, status, join_date, basic_salary, ot_rate)
                VALUES (?, ?, ?, 'Field Staff', 'Field Staff', 'Field Staff', ?, ?, 0, 0)
            """, (employee_id, name, phone, "Active" if is_active else "Inactive", join_date))
        except Exception as e:
            current_app.logger.warning("restore employees: %s", e)
            db.rollback()
            flash(f"Restore failed (employees): {e}", "error")
            return redirect(url_for("hr.employee_list"))

        db.commit()
        flash(f"Employee {name} ({employee_id}) restored successfully.", "success")
        return redirect(url_for("hr.employee_edit", employee_id=employee_id))
    except Exception as e:
        current_app.logger.error("restore error: %s\n%s", e, traceback.format_exc())
        flash(f"Restore error: {e}", "error")
        return redirect(url_for("hr.employee_list"))


@hr_bp.route("/hr/employees/download/excel")
@_login_required("admin")
def employee_list_excel():
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    department_filter = request.args.get("department", "").strip()
    employee_type_filter = request.args.get("type", "").strip()
    shift_filter = request.args.get("shift", "").strip()

    where_sql, params = employee_search_filter(query, status_filter, department_filter, employee_type_filter, shift_filter)

    employees = db.execute(
        f"""
        SELECT e.employee_id, e.full_name, e.phone_number, e.email, e.employee_type,
               e.department, e.designation, e.join_date, e.basic_salary, e.status, e.termination_date,
               e.shift,
               COALESCE(
                   (SELECT v.plate_no FROM vehicle_assignments va
                    JOIN vehicles v ON v.plate_no = va.vehicle_id
                    WHERE va.driver_id = e.employee_id
                    ORDER BY va.id DESC LIMIT 1),
                   (SELECT d.vehicle_no FROM drivers d WHERE d.driver_id = e.employee_id LIMIT 1)
               ) AS plate_no
        FROM employees e
        {where_sql}
        ORDER BY e.full_name ASC
        """,
        params,
    ).fetchall()

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from io import BytesIO

    wb = Workbook()
    ws = wb.active
    ws.title = "Employees"

    hf = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    hfill = PatternFill("solid", fgColor="1a3a5c")
    center = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="d8e4f5")
    border = Border(top=thin, left=thin, right=thin, bottom=thin)

    heads = ["Employee ID", "Full Name", "Phone", "Email", "Type", "Department", "Designation", "Join Date", "Salary (AED)", "Vehicle Number", "Status", "Termination Date", "Shift"]
    for ci, h in enumerate(heads, 1):
        c = ws.cell(row=1, column=ci, value=h)
        c.font = hf; c.fill = hfill; c.alignment = center; c.border = border

    for ri, emp in enumerate(employees, 2):
        vals = [emp["employee_id"], emp["full_name"], emp["phone_number"] or "", emp["email"] or "",
                emp["employee_type"], emp["department"], emp["designation"],
                emp["join_date"], emp["basic_salary"] or 0, emp["plate_no"] or "", emp["status"] or "",
                emp["termination_date"] or "", (emp["shift"] or "Morning")]
        for ci, v in enumerate(vals, 1):
            c = ws.cell(row=ri, column=ci, value=v)
            c.border = border
            if ci == 9:
                c.number_format = '#,##0.00'
                c.alignment = Alignment(horizontal="right", vertical="center")

    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 26
    ws.column_dimensions["E"].width = 14
    ws.column_dimensions["F"].width = 16
    ws.column_dimensions["G"].width = 16
    ws.column_dimensions["H"].width = 14
    ws.column_dimensions["I"].width = 16
    ws.column_dimensions["J"].width = 16
    ws.column_dimensions["K"].width = 12
    ws.column_dimensions["L"].width = 18
    ws.column_dimensions["M"].width = 12

    # Vehicle Number only applies to drivers / operators — centre it for readability
    vnum_align = Alignment(horizontal="center", vertical="center")
    for ri in range(2, len(employees) + 2):
        ws.cell(row=ri, column=10).alignment = vnum_align
    ws.cell(row=1, column=10).alignment = center

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="employees.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@hr_bp.route("/hr/employees/download/pdf")
@_login_required("admin")
def employee_list_pdf():
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    department_filter = request.args.get("department", "").strip()
    employee_type_filter = request.args.get("type", "").strip()
    shift_filter = request.args.get("shift", "").strip()

    where_sql, params = employee_search_filter(query, status_filter, department_filter, employee_type_filter, shift_filter)

    employees = db.execute(
        f"""
        SELECT e.employee_id, e.full_name, e.phone_number, e.email, e.employee_type,
               e.department, e.designation, e.join_date, e.basic_salary, e.status, e.termination_date,
               e.shift,
               COALESCE(
                   (SELECT v.plate_no FROM vehicle_assignments va
                    JOIN vehicles v ON v.plate_no = va.vehicle_id
                    WHERE va.driver_id = e.employee_id
                    ORDER BY va.id DESC LIMIT 1),
                   (SELECT d.vehicle_no FROM drivers d WHERE d.driver_id = e.employee_id LIMIT 1)
               ) AS plate_no
        FROM employees e
        {where_sql}
        ORDER BY e.full_name ASC
        """,
        params,
    ).fetchall()

    try:
        company = db.execute("SELECT company_name, legal_name, trade_license_no, trade_license_expiry, trn_no, vat_status, address, phone_number, email, bank_name, bank_account_name, bank_account_number, iban, swift_code, invoice_terms, base_currency, logo_data, logo_type, theme_color FROM company_profile LIMIT 1").fetchone()
        company_profile = dict(company) if company else None
    except Exception:
        company_profile = None

    from ..pdf_service import _generate_employee_list_pdf
    from pathlib import Path
    from flask import current_app

    output_dir = Path(current_app.config["GENERATED_DIR"]) / "temp"
    pdf_path = _generate_employee_list_pdf(employees, str(output_dir), company_profile)
    return send_file(pdf_path, as_attachment=True, download_name="employees.pdf", mimetype="application/pdf")


@hr_bp.app_template_global()
def employee_current_vehicle(employee_id):
    from ..database import open_db
    try:
        d = open_db()
        row = d.execute(
            "SELECT va.vehicle_id, va.assigned_from, v.plate_no, v.vehicle_type, v.model "
            "FROM vehicle_assignments va JOIN vehicles v ON v.plate_no = va.vehicle_id "
            "WHERE va.driver_id = ? AND va.is_current = 1 LIMIT 1",
            (employee_id,),
        ).fetchone()
        if not row:
            row = d.execute(
                "SELECT va.vehicle_id, va.assigned_from, v.plate_no, v.vehicle_type, v.model "
                "FROM vehicle_assignments va JOIN vehicles v ON v.plate_no = va.vehicle_id "
                "WHERE va.driver_id = ? ORDER BY va.id DESC LIMIT 1",
                (employee_id,),
            ).fetchone()
        if not row:
            legacy = d.execute("SELECT vehicle_no FROM drivers WHERE driver_id = ? LIMIT 1", (employee_id,)).fetchone()
            if legacy and legacy["vehicle_no"]:
                row = d.execute("SELECT plate_no AS vehicle_id, NULL AS assigned_from, plate_no, vehicle_type, model FROM vehicles WHERE plate_no = ? LIMIT 1", (legacy["vehicle_no"],)).fetchone()
                if not row:
                    row = {"vehicle_id": legacy["vehicle_no"], "assigned_from": "", "plate_no": legacy["vehicle_no"], "vehicle_type": "", "model": ""}
        d.close()
        return dict(row) if row else None
    except Exception:
        return None

@hr_bp.app_template_global()
def employee_vehicle_history(employee_id):
    from ..database import open_db
    try:
        d = open_db()
        rows = d.execute(
            "SELECT va.vehicle_id, va.assigned_from, va.assigned_until, v.plate_no, v.vehicle_type, v.model FROM vehicle_assignments va JOIN vehicles v ON v.plate_no = va.vehicle_id WHERE va.driver_id = ? ORDER BY va.id DESC",
            (employee_id,),
        ).fetchall()
        d.close()
        return [dict(r) for r in rows]
    except Exception:
        return []

# ── Salary Dashboard ──────────────────────────────────────────────

def _salary_dashboard_data(status_filter=""):
    db = open_db()

    where = ""
    params = []
    if status_filter == "active":
        where = "WHERE LOWER(status) = 'active'"
    elif status_filter == "inactive":
        where = "WHERE LOWER(status) IN ('inactive','on leave')"
    elif status_filter == "terminated":
        where = "WHERE LOWER(status) = 'terminated'"

    employees = db.execute(
        f"SELECT employee_id, full_name, department, status, termination_date, shift FROM employees {where} ORDER BY full_name"
    ).fetchall()

    va_rows = db.execute(
        "SELECT driver_id, vehicle_id FROM vehicle_assignments WHERE is_current = 1"
    ).fetchall()
    vehicle_by_emp = {r["driver_id"]: r["vehicle_id"] for r in va_rows}

    dr_rows = db.execute(
        "SELECT driver_id, vehicle_no, shift FROM drivers WHERE vehicle_no IS NOT NULL AND vehicle_no != '' AND vehicle_no != '0'"
    ).fetchall()
    shift_by_emp = {}
    for r in dr_rows:
        if r["driver_id"] not in vehicle_by_emp or not vehicle_by_emp[r["driver_id"]]:
            vehicle_by_emp[r["driver_id"]] = r["vehicle_no"]
        if r["shift"]:
            shift_by_emp[r["driver_id"]] = r["shift"]

    store_rows = db.execute(
        "SELECT driver_id, salary_month, net_salary, ot_amount, monthly_basic_salary, basic_salary FROM salary_store"
    ).fetchall()
    store_by_emp = {}
    ot_hist = {}
    basic_by_emp = {}
    for r in store_rows:
        store_by_emp.setdefault(r["driver_id"], {})[r["salary_month"]] = r["net_salary"]
        ot_hist.setdefault(r["driver_id"], []).append((r["salary_month"], float(r["ot_amount"] or 0)))
        bs = float(r["monthly_basic_salary"] or r["basic_salary"] or 0)
        if bs > 0:
            basic_by_emp.setdefault(r["driver_id"], []).append((r["salary_month"], bs))
    ot_sort = {}
    for eid, lst in ot_hist.items():
        lst.sort(key=lambda x: x[0], reverse=True)
        ot_sort[eid] = lst
    basic_sort = {}
    for eid, lst in basic_by_emp.items():
        lst.sort(key=lambda x: x[0], reverse=True)
        basic_sort[eid] = lst

    slip_rows = db.execute(
        "SELECT driver_id, salary_month, salary_after_deduction, actual_paid_amount "
        "FROM salary_slips WHERE salary_after_deduction > 0 OR actual_paid_amount > 0"
    ).fetchall()
    paid_by_emp = {}
    for r in slip_rows:
        paid_by_emp.setdefault(r["driver_id"], set()).add(r["salary_month"])

    pay_rows = db.execute(
        "SELECT driver_id, salary_month FROM salary_payments WHERE amount > 0"
    ).fetchall()
    pay_by_emp = {}
    for r in pay_rows:
        pay_by_emp.setdefault(r["driver_id"], set()).add(r["salary_month"])

    month_rows = db.execute(
        "SELECT DISTINCT salary_month FROM salary_store UNION "
        "SELECT DISTINCT salary_month FROM salary_slips UNION "
        "SELECT DISTINCT salary_month FROM salary_payments "
        "ORDER BY salary_month DESC"
    ).fetchall()
    available_months = [r["salary_month"] for r in month_rows]

    emp_list = []
    for emp in employees:
        eid = emp["employee_id"]
        term_date = emp.get("termination_date") or ""
        term_month = term_date[:7] if term_date and len(term_date) >= 7 else ""

        statuses = {}
        amounts = {}
        for m in available_months:
            emp_is_terminated = (emp["status"] or "").lower() == "terminated"
            if emp_is_terminated and term_month and m > term_month:
                statuses[m] = "No Record"
                amounts[m] = 0.0
            else:
                if eid in paid_by_emp and m in paid_by_emp[eid]:
                    statuses[m] = "Paid"
                elif eid in store_by_emp and m in store_by_emp[eid]:
                    statuses[m] = "Unpaid"
                else:
                    statuses[m] = "Pending"
                amounts[m] = float(store_by_emp[eid][m]) if eid in store_by_emp and m in store_by_emp[eid] else 0.0
        ot_history = ot_sort.get(eid, [])
        est = 0.0
        if ot_history:
            recent = [x[1] for x in ot_history[:3] if x[1] > 0]
            if recent:
                est = sum(recent) / len(recent)
        basic_list = basic_sort.get(eid, [])
        basic_val = basic_list[0][1] if basic_list else 0.0
        emp_list.append({
            "id": eid,
            "name": emp["full_name"],
            "department": emp["department"] or "",
            "emp_status": emp["status"] or "",
            "term_date": term_date,
            "statuses": statuses,
            "amounts": amounts,
            "estimated": round(est, 0),
            "basic_salary": basic_val,
            "vehicle": vehicle_by_emp.get(eid, ""),
            "shift": shift_by_emp.get(eid, emp["shift"] or ""),
        })

    db.close()
    return emp_list, available_months


def _format_month_options(months):
    names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    return [(m, f"{names[int(m.split('-')[1])-1]} {m.split('-')[0]}") for m in months]


@hr_bp.route("/hr/salary-dashboard")
@_login_required("admin")
def salary_dashboard():
    _touch_admin_workspace("hr")
    ensure_employees_table()
    sf = request.args.get("status", "active")
    sel_month_raw = request.args.get("month", "")
    emp_list, available_months = _salary_dashboard_data(status_filter=sf)
    return render_template(
        "hr/employee_salary_dashboard.html",
        employees=emp_list,
        months=_format_month_options(available_months),
        selected_status=sf,
        sel_month=sel_month_raw or (available_months[0] if available_months else ""),
    )


@hr_bp.route("/hr/salary-dashboard/download/excel")
@_login_required("admin")
def salary_dashboard_excel():
    _touch_admin_workspace("hr")
    ensure_employees_table()

    sf = request.args.get("status", "all")
    selected_month = request.args.get("month", "")
    emp_list, available_months = _salary_dashboard_data(status_filter=sf)
    if not selected_month and available_months:
        selected_month = available_months[0]

    # Real payment truth for the selected month — same source as the paid
    # salary report (salary_slips.actual_paid_amount + owner fund entries).
    paid_truth = {}
    if selected_month:
        try:
            _tdb = open_db()
            for _r in _paid_salary_report_rows(_tdb, selected_month, with_advance=False):
                paid_truth[_r["employee_id"]] = _r
            _tdb.close()
        except Exception:
            paid_truth = {}

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from io import BytesIO

    wb = Workbook()
    ws = wb.active
    ws.title = "Salary Status"

    hf = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    hfill = PatternFill("solid", fgColor="1a3a5c")
    hfill_green = PatternFill("solid", fgColor="059669")
    hfill_red = PatternFill("solid", fgColor="DC2626")
    hfill_amber = PatternFill("solid", fgColor="D97706")
    center = Alignment(horizontal="center", vertical="center")
    right = Alignment(horizontal="right", vertical="center")
    thin = Side(style="thin", color="d8e4f5")
    border = Border(top=thin, left=thin, right=thin, bottom=thin)

    heads = ["#", "Employee Name", "Department", "Vehicle", "Shift", "Status", "Basic Salary", "Est. OT (AI)", "Total (Basic+OT)", "Stored Salary", "Actually Paid", "Balance Due", "Salary Status"]
    for ci, h in enumerate(heads, 1):
        c = ws.cell(row=1, column=ci, value=h)
        c.font = hf; c.fill = hfill; c.alignment = center; c.border = border

    status_fills = {
        "Paid": PatternFill("solid", fgColor="D5F5E3"),
        "Unpaid": PatternFill("solid", fgColor="FADBD8"),
        "Pending": PatternFill("solid", fgColor="FDEBD0"),
        "No Record": PatternFill("solid", fgColor="F2F3F4"),
    }

    row_idx = 2

    def _vehicle_sort_key(emp):
        v = emp.get("vehicle") or ""
        import re
        nums = re.findall(r'\d+', v)
        num = int(nums[-1]) if nums else 0
        shift_order = {"Morning": 0, "Day": 0, "Night": 1, "General": 2}
        so = shift_order.get(emp.get("shift", ""), 2)
        return (num, so, v)

    emp_list.sort(key=_vehicle_sort_key)

    from collections import Counter
    vehicle_driver_count = Counter()
    for emp in emp_list:
        v = emp.get("vehicle", "")
        if v and v not in ("0", "0000"):
            vehicle_driver_count[v] += 1

    err_fill = PatternFill("solid", fgColor="FDEDEC")
    err_font = Font(name="Calibri", bold=True, color="DC2626", size=11)
    totals = {"basic": 0.0, "est": 0.0, "total": 0.0, "stored": 0.0, "paid": 0.0, "balance": 0.0}

    for emp in emp_list:
        st = emp["statuses"].get(selected_month, "No Record")
        if st == "No Record":
            continue
        amt = emp["amounts"].get(selected_month, 0)
        est = emp.get("estimated", 0)
        basic = emp.get("basic_salary", 0)
        total = basic + est
        truth = paid_truth.get(emp["id"]) or {}
        stored = float(amt or 0) or float(truth.get("net_salary") or 0)
        paid = float(truth.get("paid") or 0)
        if truth:
            balance = float(truth.get("balance") or 0)
        else:
            balance = max(stored - paid, 0.0)
        vals = [row_idx - 1, emp["name"], emp["department"], emp.get("vehicle", ""), emp.get("shift", ""), emp["emp_status"], basic, est, total if total > 0 else "", stored, paid, balance, st]
        totals["basic"] += float(basic or 0)
        totals["est"] += float(est or 0)
        totals["total"] += float(total or 0)
        totals["stored"] += stored
        totals["paid"] += paid
        totals["balance"] += balance
        veh = emp.get("vehicle", "")
        is_overloaded = veh and veh not in ("0", "0000") and vehicle_driver_count.get(veh, 0) > 2
        for ci, v in enumerate(vals, 1):
            c = ws.cell(row=row_idx, column=ci, value=v)
            c.border = border
            if ci in (7, 8, 9, 10, 11, 12):
                c.number_format = '#,##0.00'
                c.alignment = right
            if is_overloaded:
                c.fill = err_fill
                if ci == 4:
                    c.font = err_font
            else:
                sf = status_fills.get(st)
                if sf:
                    c.fill = sf
        row_idx += 1

    # TOTAL row — sums of every amount column
    if row_idx > 2:
        tfont = Font(name="Calibri", bold=True, color="1a3a5c", size=11)
        tfill = PatternFill("solid", fgColor="D5E8F5")
        for ci in range(1, len(heads) + 1):
            c = ws.cell(row=row_idx, column=ci)
            c.border = border
            c.font = tfont
            c.fill = tfill
        ws.cell(row=row_idx, column=1, value="TOTAL")
        ws.cell(row=row_idx, column=1).alignment = center
        for ci, key in ((7, "basic"), (8, "est"), (9, "total"), (10, "stored"), (11, "paid"), (12, "balance")):
            c = ws.cell(row=row_idx, column=ci, value=round(totals[key], 2))
            c.number_format = '#,##0.00'
            c.alignment = right
        row_idx += 1

    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 32
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 14
    ws.column_dimensions["E"].width = 12
    ws.column_dimensions["F"].width = 14
    ws.column_dimensions["G"].width = 16
    ws.column_dimensions["H"].width = 16
    ws.column_dimensions["I"].width = 18
    ws.column_dimensions["J"].width = 16
    ws.column_dimensions["K"].width = 16
    ws.column_dimensions["L"].width = 16
    ws.column_dimensions["M"].width = 18
    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"salary_status_{selected_month}.xlsx" if selected_month else "salary_status.xlsx"
    return send_file(buf, as_attachment=True, download_name=fname, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Driver / Operator documents: Driving License + Emirates ID ─────

_ID_MAX_BYTES = 5 * 1024 * 1024
_ID_TYPE_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_ID_ALLOWED_TYPES = set(_ID_TYPE_BY_EXT.values())
# uploaded side field -> column that stores its content type
_ID_FIELD_COLUMNS = {
    "driving_license_front": "driving_license_front_type",
    "driving_license_back": "driving_license_back_type",
    "emirates_id_front": "emirates_id_front_type",
    "emirates_id_back": "emirates_id_back_type",
}
_ID_SQL_COLUMNS = (
    "employee_id, full_name, employee_type, department, status, "
    "driving_license_no, driving_license_expiry, driving_license_front, driving_license_back, "
    "emirates_id_no, emirates_id_front, emirates_id_back"
)

# has_license / has_eid are 1/0 flags so the listing never loads image blobs.
# NOTE: bound params for the LIKE patterns — psycopg3 rejects a literal '%' in SQL.
_ID_STATUS_COLUMNS = """
    SELECT employee_id, full_name, employee_type, department, status,
           driving_license_no, emirates_id_no,
           CASE WHEN length(COALESCE(driving_license_front, '')) > 0
                   OR length(COALESCE(driving_license_back, '')) > 0
                THEN 1 ELSE 0 END AS has_license,
           CASE WHEN length(COALESCE(emirates_id_front, '')) > 0
                   OR length(COALESCE(emirates_id_back, '')) > 0
                THEN 1 ELSE 0 END AS has_eid,
           COALESCE(
               (SELECT va.vehicle_id FROM vehicle_assignments va
                 WHERE va.driver_id = employees.employee_id AND va.is_current = 1 LIMIT 1),
               (SELECT d.vehicle_no FROM drivers d
                 WHERE d.driver_id = employees.employee_id
                   AND COALESCE(d.vehicle_no, '') <> ''
                   AND COALESCE(d.vehicle_no, '') <> '0' LIMIT 1),
               ''
           ) AS vehicle
    FROM employees
"""

# active drivers & operators only (also feeds the bulk ZIP download)
_DRIVER_IDS_SQL = _ID_STATUS_COLUMNS + """WHERE (LOWER(employee_type) LIKE ?
       OR LOWER(employee_type) LIKE ?)
     AND LOWER(status) = 'active'
    ORDER BY full_name
"""
_DRIVER_IDS_PARAMS = ("%driver%", "%operator%")

# active employees only — those with nothing uploaded come first
_ALL_IDS_SQL = _ID_STATUS_COLUMNS + """WHERE LOWER(status) = 'active'
    ORDER BY has_license, has_eid, full_name
"""


def _read_id_upload(file_storage):
    """Validate one uploaded side image -> (base64, content_type, error)."""
    if file_storage is None or not getattr(file_storage, "filename", ""):
        return None, None, None
    ext = Path(file_storage.filename).suffix.lower()
    ctype = (file_storage.content_type or "").lower()
    if ctype not in _ID_ALLOWED_TYPES:
        ctype = _ID_TYPE_BY_EXT.get(ext, "")
    if ctype not in _ID_ALLOWED_TYPES:
        return None, None, f"{file_storage.filename}: only JPG, PNG or WEBP images are allowed."
    raw = file_storage.read()
    if not raw:
        return None, None, f"{file_storage.filename}: file is empty."
    if len(raw) > _ID_MAX_BYTES:
        return None, None, f"{file_storage.filename}: bigger than 5 MB."
    return base64.b64encode(raw).decode("ascii"), ctype, None


def _company_name(db):
    try:
        row = db.execute("SELECT company_name FROM company_profile LIMIT 1").fetchone()
        return (row["company_name"] if row else "") or ""
    except Exception:
        return ""


def _current_vehicle(db, employee_id):
    row = db.execute(
        "SELECT vehicle_id FROM vehicle_assignments WHERE is_current = 1 AND driver_id = ?",
        (employee_id,),
    ).fetchone()
    if row and row["vehicle_id"]:
        return {"vehicle_id": row["vehicle_id"]}
    legacy = db.execute(
        "SELECT vehicle_no FROM drivers WHERE driver_id = ? LIMIT 1", (employee_id,)
    ).fetchone()
    if legacy and legacy["vehicle_no"]:
        return {"vehicle_id": legacy["vehicle_no"]}
    return None


@hr_bp.route("/hr/employees/<employee_id>/ids", methods=["GET", "POST"])
@_login_required("admin")
def employee_ids(employee_id):
    """Profile tab: view / upload Driving License (front+back) and Emirates ID."""
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))

    if request.method == "POST":
        updates = {
            "driving_license_no": request.form.get("driving_license_no", "").strip() or None,
            "driving_license_expiry": request.form.get("driving_license_expiry", "").strip() or None,
            "emirates_id_no": request.form.get("emirates_id_no", "").strip() or None,
        }
        errors = []
        saved = 0
        for field, type_column in _ID_FIELD_COLUMNS.items():
            b64, ctype, error = _read_id_upload(request.files.get(field))
            if error:
                errors.append(error)
            elif b64:
                updates[field] = b64
                updates[type_column] = ctype
                saved += 1

        if updates:
            assignments = ", ".join(f"{column} = ?" for column in updates)
            db.execute(
                f"UPDATE employees SET {assignments} WHERE UPPER(employee_id) = ?",
                (*updates.values(), employee_id.strip().upper()),
            )
            db.commit()
            try:
                _audit_log(
                    db,
                    "employee_documents_updated",
                    entity_type="employee",
                    entity_id=employee_id.strip().upper(),
                    details=f"{saved} image(s) uploaded",
                )
                db.commit()
            except Exception:
                db.rollback()

        if errors:
            flash(" ".join(errors), "error")
            if saved:
                flash(f"{saved} image(s) uploaded — fix the files listed above and save again.", "success")
        elif saved:
            flash(f"{saved} image(s) saved.", "success")
        else:
            flash("Document details saved.", "success")

        return redirect(url_for("hr.employee_ids", employee_id=employee_id))

    photo_url = _employee_photo_url(current_app._get_current_object(), employee)
    return render_template(
        "hr/employee_detail.html",
        employee=employee,
        photo_url=photo_url,
        active_tab="ids",
        current_vehicle=_current_vehicle(db, employee["employee_id"]),
    )


@hr_bp.route("/hr/employees/<employee_id>/ids/pdf")
@_login_required("admin")
def employee_ids_pdf(employee_id):
    """One merged PDF: driving license front/back + Emirates ID front/back."""
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()
    employee = _fetch_employee(db, employee_id)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("hr.employee_list"))

    from .license_pdf import build_employee_ids_pdf

    payload = dict(employee)
    assigned = _current_vehicle(db, employee["employee_id"])
    payload["vehicle"] = (assigned or {}).get("vehicle_id", "") or ""
    pdf_bytes = build_employee_ids_pdf(_company_name(db), payload)
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in employee_id) or "employee"
    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=f"{safe_id}_License_EID.pdf",
        mimetype="application/pdf",
    )


@hr_bp.route("/hr/driver-ids")
@_login_required("admin")
def driver_ids():
    """Who among drivers/operators has uploaded a licence / Emirates ID."""
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()
    people = [dict(r) for r in db.execute(_DRIVER_IDS_SQL, _DRIVER_IDS_PARAMS).fetchall()]
    for person in people:
        person["has_license"] = bool(person["has_license"])
        person["has_eid"] = bool(person["has_eid"])
        person["has_any"] = person["has_license"] or person["has_eid"]

    return render_template(
        "hr/driver_ids.html",
        people=people,
        total=len(people),
        with_license=sum(1 for p in people if p["has_license"]),
        with_eid=sum(1 for p in people if p["has_eid"]),
        ready=sum(1 for p in people if p["has_any"]),
    )


@hr_bp.route("/hr/id-status")
@_login_required("admin")
def id_status():
    """Upload status of Driving Licence / Emirates ID for every employee."""
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()
    people = [dict(r) for r in db.execute(_ALL_IDS_SQL).fetchall()]
    for person in people:
        person["has_license"] = bool(person["has_license"])
        person["has_eid"] = bool(person["has_eid"])
        person["has_any"] = person["has_license"] or person["has_eid"]

    # the bulk ZIP stays limited to drivers and operators
    ready = sum(
        1
        for r in db.execute(_DRIVER_IDS_SQL, _DRIVER_IDS_PARAMS).fetchall()
        if r["has_license"] or r["has_eid"]
    )

    return render_template(
        "hr/driver_ids.html",
        people=people,
        total=len(people),
        with_license=sum(1 for p in people if p["has_license"]),
        with_eid=sum(1 for p in people if p["has_eid"]),
        ready=ready,
        with_any=sum(1 for p in people if p["has_any"]),
        heading="Document upload status — active employees",
        subtitle=(
            "Every active employee — who has uploaded their Driving Licence and Emirates ID, "
            "and who has not. Click a row to open that employee's License & ID tab. "
            "The ZIP download covers active drivers and operators only."
        ),
        total_label="Active employees",
        back_url=url_for("hr.hr_dashboard"),
        back_label="HR Dashboard",
        empty_msg="No active employees found.",
    )


@hr_bp.route("/hr/driver-ids/download")
@_login_required("admin")
def driver_ids_download():
    """ZIP with one merged PDF (licence + EID, both sides) per driver/operator."""
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()
    rows = db.execute(_DRIVER_IDS_SQL, _DRIVER_IDS_PARAMS).fetchall()
    vehicle_by_id = {r["employee_id"]: (r["vehicle"] or "") for r in rows}
    ids = [r["employee_id"] for r in rows if r["has_license"] or r["has_eid"]]
    if not ids:
        flash("No Driving License or Emirates ID uploaded yet — nothing to download.", "error")
        return redirect(url_for("hr.driver_ids"))

    from .license_pdf import write_ids_zip

    company = _company_name(db)

    def _one_at_a_time():
        for emp_id in ids:
            row = db.execute(f"SELECT {_ID_SQL_COLUMNS} FROM employees WHERE employee_id = ?", (emp_id,)).fetchone()
            if row:
                payload = dict(row)
                payload["vehicle"] = vehicle_by_id.get(emp_id, "")
                yield payload

    tmp = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    write_ids_zip(company, _one_at_a_time(), tmp)
    tmp.seek(0)
    response = send_file(
        tmp,
        as_attachment=True,
        download_name=f"driver_ids_{date.today().isoformat()}.zip",
        mimetype="application/zip",
    )
    response.call_on_close(tmp.close)
    return response


# ── Paid salary report (paid / balance / OT / advance) ────────────

def _report_months(db):
    rows = db.execute(
        "SELECT DISTINCT salary_month FROM salary_store UNION "
        "SELECT DISTINCT salary_month FROM salary_slips UNION "
        "SELECT DISTINCT salary_month FROM salary_payments "
        "ORDER BY salary_month DESC"
    ).fetchall()
    return [r["salary_month"] for r in rows]


def _last_closed_month():
    """Previous calendar month, e.g. '2026-09' during October 2026."""
    first_of_month = date.today().replace(day=1)
    return (first_of_month - timedelta(days=1)).strftime("%Y-%m")


def _paid_salary_report_rows(db, month, with_advance=True):
    store_rows = db.execute(
        "SELECT driver_id, net_salary, ot_amount, monthly_basic_salary, basic_salary "
        "FROM salary_store WHERE salary_month = ?",
        (month,),
    ).fetchall()
    slip_rows = db.execute(
        "SELECT id, driver_id, total_deductions, available_advance, remaining_advance, "
        "salary_after_deduction, actual_paid_amount, company_balance_due, payment_source, "
        "paid_by, net_payable FROM salary_slips WHERE salary_month = ?",
        (month,),
    ).fetchall()

    store_by = {r["driver_id"]: r for r in store_rows}
    slip_by = {}
    slip_ids = {}
    for r in slip_rows:  # keep the newest slip when a month was regenerated
        slip_by[r["driver_id"]] = r
        try:
            slip_ids[int(r["id"])] = r["driver_id"]
        except (TypeError, ValueError):
            pass

    emps = {
        r["employee_id"]: r
        for r in db.execute(
            "SELECT employee_id, full_name, employee_type, department, status FROM employees"
        ).fetchall()
    }

    # Salaries handed over are booked in owner_fund_entries
    # ("Salary Slip <month> - <name>", source_table = 'salary_slips'), while
    # salary_slips.actual_paid_amount only holds slips paid through the run flow.
    # Both sources are summed (verified: never both for the same slip).
    fund_by_driver = {}
    if slip_by:
        by_name = {}
        for emp_row in emps.values():
            key = (emp_row["full_name"] or "").strip().lower()
            if key:
                by_name.setdefault(key, emp_row["employee_id"])
        try:
            fund_rows = db.execute(
                "SELECT source_id, owner_name, details, entry_date, amount, payment_method "
                "FROM owner_fund_entries WHERE details LIKE ?",
                (f"Salary Slip {month}%",),
            ).fetchall()
        except Exception:
            fund_rows = []
        for fr in fund_rows:
            amount = float(fr["amount"] or 0)
            if amount <= 0:
                continue
            fund_driver = None
            try:
                if fr["source_id"] not in (None, ""):
                    fund_driver = slip_ids.get(int(fr["source_id"]))
            except (TypeError, ValueError):
                fund_driver = None
            if not fund_driver:
                name = (fr["owner_name"] or "").strip().lower()
                if not name and fr["details"] and "—" in fr["details"]:
                    name = fr["details"].split("—", 1)[1].strip().lower()
                fund_driver = by_name.get(name)
            if not fund_driver:
                continue
            entry = fund_by_driver.setdefault(
                fund_driver, {"amount": 0.0, "paid_on": "", "method": ""}
            )
            entry["amount"] += amount
            if (fr["entry_date"] or "") > entry["paid_on"]:
                entry["paid_on"] = fr["entry_date"] or ""
            if not entry["method"]:
                entry["method"] = fr["payment_method"] or ""

    vehicles = {}
    for r in db.execute(
        "SELECT driver_id, vehicle_id FROM vehicle_assignments WHERE is_current = 1"
    ).fetchall():
        if r["vehicle_id"]:
            vehicles[r["driver_id"]] = r["vehicle_id"]
    for r in db.execute(
        "SELECT driver_id, vehicle_no FROM drivers "
        "WHERE vehicle_no IS NOT NULL AND vehicle_no != '' AND vehicle_no != '0'"
    ).fetchall():
        vehicles.setdefault(r["driver_id"], r["vehicle_no"])

    ordered_ids = list(store_by)
    ordered_ids += [d for d in slip_by if d not in store_by]
    # every employee must show up, even when the month's salary was never run
    ordered_ids += [d for d in emps if d not in store_by and d not in slip_by]

    rows = []
    for driver_id in ordered_ids:
        store = store_by.get(driver_id)
        slip = slip_by.get(driver_id)
        emp = emps.get(driver_id)

        net_salary = float((store["net_salary"] if store else 0) or 0)
        if not net_salary and slip:
            net_salary = float(slip["net_payable"] or 0)
        basic = 0.0
        if store:
            basic = float(store["monthly_basic_salary"] or store["basic_salary"] or 0)
        ot_amount = float((store["ot_amount"] if store else 0) or 0)
        deductions = float(slip["total_deductions"] if slip else 0) or 0
        paid = float(slip["actual_paid_amount"] if slip else 0) or 0
        payable = float(slip["salary_after_deduction"] if slip else net_salary) or 0
        fund = fund_by_driver.get(driver_id)
        if fund:
            paid += fund["amount"]
        balance = max(payable - paid, 0.0)
        advance = 0.0
        if with_advance:
            try:
                advance = float(_advance_summary(db, driver_id)["remaining_advance"])
            except Exception:
                advance = 0.0

        if not slip and paid <= 0:
            status = "Not Run"
        elif paid <= 0 and payable <= 0:
            status = "Nil"
        elif paid <= 0:
            status = "Unpaid"
        elif paid + 0.01 < payable:
            status = "Partial"
        else:
            status = "Paid"

        source = (slip["payment_source"] if slip else "") or ""
        paid_on = ""
        if fund:
            paid_on = fund["paid_on"]
            if not source and fund["amount"] > 0:
                source = (
                    f"Owner Fund ({fund['method']})" if fund["method"] else "Owner Fund"
                )

        rows.append(
            {
                "employee_id": driver_id,
                "name": emp["full_name"] if emp else driver_id,
                "department": (emp["department"] if emp else "") or "",
                "employee_type": (emp["employee_type"] if emp else "") or "",
                "emp_status": (emp["status"] if emp else "") or "",
                "vehicle": vehicles.get(driver_id, ""),
                "basic": basic,
                "net_salary": net_salary,
                "ot_amount": ot_amount,
                "advance": advance,
                "deductions": deductions,
                "paid": paid,
                "balance": balance,
                "status": status,
                "payment_source": source,
                "paid_on": paid_on,
                "paid_by": (slip["paid_by"] if slip else "") or "",
            }
        )
    rows.sort(key=lambda r: r["employee_id"])
    return rows


def _report_totals(rows):
    keys = ("basic", "net_salary", "ot_amount", "advance", "deductions", "paid", "balance")
    return {key: sum(float(r[key]) for r in rows) for key in keys}


def _report_context(db):
    months = _report_months(db)
    default_month = _last_closed_month()
    month = request.args.get("month", "").strip()
    if not month or month not in months:
        month = default_month if default_month in months else (months[0] if months else default_month)
    return month, months


@hr_bp.route("/hr/paid-salary-report")
@_login_required("admin")
def paid_salary_report():
    """Last month's paid salaries with balance, OT and outstanding advance."""
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    month, months = _report_context(db)
    month2 = request.args.get("month2", "").strip()
    if month2 not in months or month2 == month:
        month2 = ""

    sections = []
    for m in [month] + ([month2] if month2 else []):
        section_rows = _paid_salary_report_rows(db, m)
        sections.append(
            {
                "month": m,
                "label": format_month_label(m),
                "rows": section_rows,
                "totals": _report_totals(section_rows),
                "paid_count": sum(
                    1 for r in section_rows if r["status"] in ("Paid", "Partial")
                ),
            }
        )

    return render_template(
        "hr/paid_salary_report.html",
        sections=sections,
        report_title=" + ".join(s["label"] for s in sections),
        month=month,
        month2=month2,
        month_options=_format_month_options(months),
    )


@hr_bp.route("/hr/paid-salary-report/excel")
@_login_required("admin")
def paid_salary_report_excel():
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    month, months = _report_context(db)
    month2 = request.args.get("month2", "").strip()
    if month2 not in months or month2 == month:
        month2 = ""
    selected = [month] + ([month2] if month2 else [])
    sections = []
    for m in selected:
        section_rows = _paid_salary_report_rows(db, m)
        sections.append(
            (format_month_label(m), section_rows, _report_totals(section_rows))
        )

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "Paid Salary"

    head_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    head_fill = PatternFill("solid", fgColor="1a3a5c")
    total_fill = PatternFill("solid", fgColor="e8eef7")
    center = Alignment(horizontal="center", vertical="center")
    right = Alignment(horizontal="right", vertical="center")
    thin = Side(style="thin", color="d8e4f5")
    border = Border(top=thin, left=thin, right=thin, bottom=thin)

    heads = [
        "#", "Employee ID", "Name", "Department", "Vehicle", "Status",
        "Basic Salary", "Net Salary", "OT Amount", "Advance (Due)",
        "Deductions", "Actual Paid", "Paid On", "Balance Due", "Payment Status",
    ]

    status_fill = {
        "Paid": PatternFill("solid", fgColor="D5F5E3"),
        "Partial": PatternFill("solid", fgColor="FDEBD0"),
        "Unpaid": PatternFill("solid", fgColor="FADBD8"),
        "Nil": PatternFill("solid", fgColor="F2F3F4"),
        "Not Run": PatternFill("solid", fgColor="F2F3F4"),
    }

    def _write_section(sheet, start, label, rows, totals, show_label):
        r = start
        if show_label:
            cell = sheet.cell(row=r, column=1, value=label)
            cell.font = Font(name="Calibri", bold=True, size=12, color="1a3a5c")
            cell.alignment = Alignment(horizontal="left", vertical="center")
            sheet.merge_cells(
                start_row=r, start_column=1, end_row=r, end_column=len(heads)
            )
            r += 1

        for ci, head in enumerate(heads, 1):
            cell = sheet.cell(row=r, column=ci, value=head)
            cell.font = head_font
            cell.fill = head_fill
            cell.alignment = center
            cell.border = border
        r += 1

        for idx, row in enumerate(rows, 1):
            values = [
                idx, row["employee_id"], row["name"], row["department"], row["vehicle"],
                row["emp_status"], row["basic"], row["net_salary"], row["ot_amount"],
                row["advance"], row["deductions"], row["paid"], row["paid_on"],
                row["balance"], row["status"],
            ]
            for ci, value in enumerate(values, 1):
                cell = sheet.cell(row=r, column=ci, value=value)
                cell.border = border
                if ci in (7, 8, 9, 10, 11, 12, 14):
                    cell.number_format = "#,##0.00"
                    cell.alignment = right
                elif ci in (1, 6, 13, 15):
                    cell.alignment = center
            fill = status_fill.get(row["status"])
            if fill:
                sheet.cell(row=r, column=15).fill = fill
            r += 1

        sheet.cell(row=r, column=1, value="TOTAL").font = Font(bold=True)
        for ci, key in ((7, "basic"), (8, "net_salary"), (9, "ot_amount"), (10, "advance"),
                        (11, "deductions"), (12, "paid"), (14, "balance")):
            cell = sheet.cell(row=r, column=ci, value=totals[key])
            cell.font = Font(bold=True)
            cell.number_format = "#,##0.00"
            cell.alignment = right
        for ci in range(1, len(heads) + 1):
            cell = sheet.cell(row=r, column=ci)
            cell.fill = total_fill
            cell.border = border
        return r + 3  # gap before the next month's section

    show_labels = len(sections) > 1
    row_ptr = 1
    for label, rows, totals in sections:
        row_ptr = _write_section(ws, row_ptr, label, rows, totals, show_labels)

    widths = [5, 14, 30, 16, 12, 12, 14, 14, 12, 15, 13, 14, 13, 14, 15]
    from openpyxl.utils import get_column_letter

    for ci, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = width
    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = "paid_salary_report_" + "_".join(selected) + ".xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@hr_bp.app_template_global()
def employee_photo_url(employee):
    if not employee:
        return None
    if employee.get("photo_data") and employee.get("photo_content_type"):
        return f"data:{employee['photo_content_type']};base64,{employee['photo_data']}"
    return None
