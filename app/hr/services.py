import os
from datetime import date
from pathlib import Path
from flask import current_app
from werkzeug.security import generate_password_hash


EMPLOYEE_SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    remarks TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def sync_drivers_to_employees(db):
    db.executescript(EMPLOYEE_SCHEMA)

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
        remarks = d.get("remarks") if "remarks" in columns else None
        shift = (d.get("shift") if "shift" in columns else "Morning") or "Morning"
        created = d.get("created_at") if "created_at" in columns else None

        existing = db.execute(
            "SELECT id FROM employees WHERE employee_id = ?",
            (emp_id,),
        ).fetchone()

        if existing:
            db.execute(
                """
                UPDATE employees SET
                    full_name=?, phone_number=?, join_date=?, basic_salary=?,
                    ot_rate=?, photo_name=?, photo_data=?, photo_content_type=?,
                    status=?, remarks=?, shift=?
                WHERE employee_id=?
                """,
                (name, phone, duty_start, salary, ot,
                 photo_name, photo_data, photo_ct, status, remarks, shift, emp_id),
            )
        else:
            db.execute(
                """
                INSERT INTO employees (
                    employee_id, full_name, phone_number, employee_type,
                    department, designation, join_date, basic_salary, ot_rate,
                    photo_name, photo_data, photo_content_type, status, remarks,
                    shift, created_at
                ) VALUES (?, ?, ?, 'Driver', 'Transport', 'Driver', ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                """,
                (emp_id, name, phone, duty_start, salary, ot,
                 photo_name, photo_data, photo_ct, status, remarks, shift, created),
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
            "(employee_id LIKE ? OR full_name LIKE ? OR phone_number LIKE ? OR department LIKE ? OR designation LIKE ?)"
        )
        like_q = f"%{query}%"
        params.extend([like_q, like_q, like_q, like_q, like_q])

    if status_filter:
        conditions.append("status = ?")
        params.append(status_filter)

    if department_filter:
        conditions.append("department = ?")
        params.append(department_filter)

    if employee_type_filter:
        conditions.append("employee_type = ?")
        params.append(employee_type_filter)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    return where, params


def next_employee_id(db):
    last = db.execute(
        "SELECT employee_id FROM employees ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last is None:
        return "EMP-0001"
    last_id = last["employee_id"]
    try:
        num = int(last_id.split("-")[-1]) + 1
    except (ValueError, IndexError):
        num = 1
    return f"EMP-{num:04d}"


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
