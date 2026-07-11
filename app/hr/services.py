import os
from datetime import date
from pathlib import Path
from flask import current_app
from werkzeug.security import generate_password_hash


EMPLOYEE_COLUMNS = """
    employee_id TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    email TEXT,
    employee_type TEXT NOT NULL DEFAULT 'Staff',
    department TEXT DEFAULT 'Other',
    designation TEXT DEFAULT 'Staff',
    gender TEXT,
    shift TEXT DEFAULT 'Morning',
    contract_type TEXT DEFAULT 'Permanent',
    join_date TEXT NOT NULL,
    basic_salary REAL NOT NULL DEFAULT 0,
    ot_rate REAL NOT NULL DEFAULT 0,
    nationality TEXT,
    iqama_no TEXT,
    passport_no TEXT,
    bank_name TEXT,
    bank_account TEXT,
    iban TEXT,
    emergency_contact TEXT,
    emergency_name TEXT,
    address TEXT,
    photo_name TEXT,
    photo_data TEXT,
    photo_content_type TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    termination_date TEXT,
    remarks TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
"""

EMPLOYEE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    {EMPLOYEE_COLUMNS}
);
"""

EMPLOYEE_SCHEMA_POSTGRES = f"""
CREATE TABLE IF NOT EXISTS employees (
    id SERIAL PRIMARY KEY,
    {EMPLOYEE_COLUMNS}
);
"""


def sync_drivers_to_employees(db):
    backend = db.backend

    # Get drivers table columns (backend-agnostic)
    if backend == "postgres":
        cols = db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'drivers'"
        ).fetchall()
        columns = [r["column_name"] for r in cols]
    else:
        try:
            columns = [c[1] for c in db.execute("PRAGMA table_info(drivers)").fetchall()]
        except Exception:
            columns = []

    drivers = db.execute("SELECT * FROM drivers").fetchall()
    for d in drivers:
        emp_id = d["driver_id"]
        name = d["full_name"]
        phone = (d.get("phone_number") if "phone_number" in columns else d["phone_number"]) or ""
        duty_start = (d.get("duty_start") if "duty_start" in columns else "") or date.today().isoformat()
        salary = (d.get("basic_salary") if "basic_salary" in columns else 0) or 0
        ot = (d.get("ot_rate") if "ot_rate" in columns else 0) or 0
        photo_name = (d.get("photo_name") if "photo_name" in columns else None)
        photo_data = (d.get("photo_data") if "photo_data" in columns else None)
        photo_ct = (d.get("photo_content_type") if "photo_content_type" in columns else None)
        status = (d.get("status") if "status" in columns else "Active") or "Active"
        termination_date = (d.get("termination_date") if "termination_date" in columns else None)
        remarks = d.get("remarks") if "remarks" in columns else None
        shift = (d.get("shift") if "shift" in columns else "Morning") or "Morning"
        created = d.get("created_at") if "created_at" in columns else None

        existing = db.execute(
            "SELECT id, join_date FROM employees WHERE employee_id = ?",
            (emp_id,),
        ).fetchone()

        if existing:
            if not duty_start:
                duty_start = existing["join_date"] if "join_date" in existing else date.today().isoformat()
            db.execute(
                """
                UPDATE employees SET
                    full_name=?, phone_number=?, join_date=?, basic_salary=?,
                    ot_rate=?, photo_name=?, photo_data=?, photo_content_type=?,
                    status=?, termination_date=?, remarks=?, shift=?
                WHERE employee_id=?
                """,
                (name, phone, duty_start, salary, ot,
                 photo_name, photo_data, photo_ct, status, termination_date, remarks, shift, emp_id),
            )
        else:
            db.execute(
                """
                INSERT INTO employees (
                    employee_id, full_name, phone_number, employee_type,
                    department, designation, join_date, basic_salary, ot_rate,
                    photo_name, photo_data, photo_content_type, status, termination_date,
                    remarks, shift, created_at
                ) VALUES (?, ?, ?, 'Driver', 'Transport', 'Driver', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                """,
                (emp_id, name, phone, duty_start, salary, ot,
                 photo_name, photo_data, photo_ct, status, termination_date, remarks, shift, created),
            )
    db.commit()


def save_employee_photo(app, employee_id, full_name, photo_file):
    if not photo_file or not photo_file.filename:
        return None

    ext = Path(photo_file.filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        return None

    photo_dir = Path(app.config.get("DRIVER_FILES_DIR", "")) / "employee_photos"
    photo_dir.mkdir(parents=True, exist_ok=True)

    safe_name = f"{employee_id}_{full_name.replace(' ', '_')}{ext}"
    photo_path = photo_dir / safe_name
    photo_file.save(str(photo_path))

    with open(photo_path, "rb") as f:
        import base64
        photo_data = base64.b64encode(f.read()).decode("utf-8")

    return {
        "photo_name": safe_name,
        "photo_data": photo_data,
        "photo_content_type": f"image/{ext[1:] if ext[1:] != 'jpg' else 'jpeg'}",
    }


def employee_search_filter(query, status_filter, department_filter, employee_type_filter):
    conditions = []
    params = []

    if query:
        conditions.append(
            "(e.employee_id LIKE ? OR e.full_name LIKE ? OR e.phone_number LIKE ? OR e.department LIKE ? OR e.designation LIKE ? OR EXISTS (SELECT 1 FROM vehicle_assignments va2 JOIN vehicles v2 ON v2.plate_no = va2.vehicle_id WHERE va2.driver_id = e.employee_id AND v2.plate_no LIKE ?) OR EXISTS (SELECT 1 FROM drivers d2 WHERE d2.driver_id = e.employee_id AND d2.vehicle_no LIKE ?))"
        )
        like_q = f"%{query}%"
        params.extend([like_q, like_q, like_q, like_q, like_q, like_q, like_q])

    if status_filter:
        conditions.append("e.status = ?")
        params.append(status_filter)

    if department_filter:
        conditions.append("e.department = ?")
        params.append(department_filter)

    if employee_type_filter:
        conditions.append("e.employee_type = ?")
        params.append(employee_type_filter)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    return where, params


def next_employee_id(db):
    # Get all existing employee IDs to find the maximum numeric suffix
    existing_ids = db.execute(
        "SELECT employee_id FROM employees WHERE employee_id LIKE 'EMP-%'"
    ).fetchall()
    
    if not existing_ids:
        return "EMP-0001"
    
    # Extract numeric suffixes and find the maximum
    max_num = 0
    for row in existing_ids:
        emp_id = row["employee_id"]
        try:
            num = int(emp_id.split("-")[-1])
            if num > max_num:
                max_num = num
        except (ValueError, IndexError):
            continue
    
    # Generate next ID and ensure it doesn't exist
    next_num = max_num + 1
    new_id = f"EMP-{next_num:04d}"
    
    # Double-check the new ID doesn't exist (handle race conditions)
    while db.execute("SELECT employee_id FROM employees WHERE employee_id = ?", (new_id,)).fetchone():
        next_num += 1
        new_id = f"EMP-{next_num:04d}"
    
    return new_id


def employee_departments(db):
    rows = db.execute(
        "SELECT DISTINCT department FROM employees WHERE department IS NOT NULL AND department != '' ORDER BY department"
    ).fetchall()
    return [r["department"] for r in rows]


def employee_types(db):
    rows = db.execute(
        "SELECT DISTINCT employee_type FROM employees WHERE employee_type IS NOT NULL AND employee_type != '' ORDER BY employee_type"
    ).fetchall()
    return [r["employee_type"] for r in rows]


def sync_field_staff_to_employees(db):
    """Sync field_staff table into employees as 'Field Staff' type."""
    try:
        staff = db.execute("SELECT * FROM field_staff").fetchall()
    except Exception:
        return
    for s in staff:
        emp_id = s["staff_id"]
        name = s["full_name"]
        phone = s["phone"] or ""
        active = "Active" if s.get("is_active", 1) else "Inactive"
        created = s.get("created_at") or None

        existing = db.execute(
            "SELECT id FROM employees WHERE employee_id = ?", (emp_id,)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE employees SET full_name=?, phone_number=?, status=? WHERE employee_id=?",
                (name, phone, active, emp_id),
            )
        else:
            db.execute(
                """INSERT INTO employees (employee_id, full_name, phone_number, employee_type,
                   department, designation, join_date, status, created_at)
                   VALUES (?,?,?,'Field Staff','Field Staff','Field Staff',CURRENT_DATE,?,COALESCE(?,CURRENT_TIMESTAMP))""",
                (emp_id, name, phone, active, created),
            )
