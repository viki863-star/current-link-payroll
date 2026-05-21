from datetime import date, datetime
from pathlib import Path

from flask import (
    current_app, flash, redirect, render_template, request,
    send_file, url_for, session
)
from werkzeug.security import generate_password_hash, check_password_hash

from ..database import open_db
from ..routes import _login_required, _touch_admin_workspace
from . import fleet_bp


VEHICLE_TYPES = ["Tanker", "Trailer", "Box Truck", "Flatbed", "Other"]
OWNERSHIP_TYPES = ["Standard", "Partnership"]
MAINTENANCE_CATEGORIES = ["Oil Change", "Tyre", "Engine", "Body", "Electrical", "Brakes", "AC", "Other"]


def ensure_fleet_tables():
    db = open_db()
    db.execute("SELECT 1 FROM vehicles LIMIT 1")
    _migrate_vehicle_master(db)


def _migrate_vehicle_master(db):
    """Copy vehicles from old vehicle_master table into vehicles table."""
    try:
        old = db.execute("SELECT * FROM vehicle_master").fetchall()
    except Exception:
        return
    for v in old:
        existing = db.execute("SELECT plate_no FROM vehicles WHERE plate_no = ?", (v["vehicle_no"],)).fetchone()
        if existing:
            continue
        partner_percent = None
        try:
            partner_percent = float(v.get("partner_share_percent") or 0)
        except (ValueError, TypeError):
            pass
        try:
            db.execute(
                """INSERT INTO vehicles (plate_no, vehicle_type, model, ownership_type, partner_name, partner_percent, status, notes, created_at)
                   VALUES (?,?,?,?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP))""",
                (v["vehicle_no"], v["vehicle_type"], v["make_model"],
                 v["ownership_mode"], v["partner_name"], partner_percent,
                 v["status"], v["notes"], v["created_at"]),
            )
        except Exception:
            pass
    db.commit()


def _vehicle_full(plate_no):
    db = open_db()
    v = db.execute("SELECT * FROM vehicles WHERE plate_no = ?", (plate_no,)).fetchone()
    if not v:
        return None
    driver = db.execute(
        """SELECT e.*, va.assigned_from FROM vehicle_assignments va
           JOIN employees e ON e.employee_id = va.driver_id
           WHERE va.vehicle_id = ? AND va.is_current = 1""",
        (plate_no,),
    ).fetchone()
    v["current_driver"] = driver
    job_count = db.execute(
        "SELECT COUNT(*) AS c FROM maintenance_jobs WHERE vehicle_id = ? AND status = 'approved'",
        (plate_no,),
    ).fetchone()["c"] or 0
    total_cost = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS t FROM maintenance_jobs WHERE vehicle_id = ? AND status = 'approved'",
        (plate_no,),
    ).fetchone()["t"] or 0
    v["job_count"] = job_count
    v["total_cost"] = total_cost
    return v


def _all_employees_drivers():
    db = open_db()
    return db.execute(
        "SELECT employee_id, full_name FROM employees WHERE employee_type = 'Driver' AND status = 'Active' ORDER BY full_name"
    ).fetchall()


def _all_staff():
    db = open_db()
    return db.execute("SELECT * FROM field_staff ORDER BY full_name").fetchall()


# ── Fleet Dashboard ─────────────────────────────────────────────

@fleet_bp.route("/fleet")
@_login_required("admin")
def fleet_dashboard():
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()

    vehicles = db.execute("SELECT * FROM vehicles ORDER BY plate_no").fetchall()
    total = len(vehicles)
    active_v = sum(1 for v in vehicles if (v["status"] or "").lower() == "active")
    standard = sum(1 for v in vehicles if v["ownership_type"] == "Standard")
    partnership = sum(1 for v in vehicles if v["ownership_type"] == "Partnership")

    pending_jobs = db.execute(
        "SELECT mj.*, COALESCE(v.plate_no, mj.vehicle_id) AS plate_no, v.vehicle_type, s.full_name AS staff_name FROM maintenance_jobs mj LEFT JOIN vehicles v ON v.plate_no = mj.vehicle_id JOIN field_staff s ON s.staff_id = mj.staff_id WHERE mj.status = 'pending' ORDER BY mj.created_at DESC"
    ).fetchall()

    pending_count = len(pending_jobs)

    total_maintenance_cost = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS t FROM maintenance_jobs WHERE status = 'approved'"
    ).fetchone()["t"] or 0

    recent_jobs = db.execute(
        "SELECT mj.*, COALESCE(v.plate_no, mj.vehicle_id) AS plate_no, v.vehicle_type, s.full_name AS staff_name FROM maintenance_jobs mj LEFT JOIN vehicles v ON v.plate_no = mj.vehicle_id JOIN field_staff s ON s.staff_id = mj.staff_id WHERE mj.status = 'approved' ORDER BY mj.created_at DESC LIMIT 10"
    ).fetchall()

    return render_template(
        "fleet/dashboard.html",
        vehicles=vehicles,
        total=total,
        active_count=active_v,
        standard_count=standard,
        partnership_count=partnership,
        pending_jobs=pending_jobs,
        pending_count=pending_count,
        total_maintenance_cost=total_maintenance_cost,
        recent_jobs=recent_jobs,
    )


# ── Vehicle List ────────────────────────────────────────────────

@fleet_bp.route("/fleet/vehicles")
@_login_required("admin")
def vehicle_list():
    try:
        _touch_admin_workspace("fleet")
        ensure_fleet_tables()
        db = open_db()

        q = request.args.get("q", "").strip()
        type_filter = request.args.get("type", "").strip()
        ownership_filter = request.args.get("ownership", "").strip()
        status_filter = request.args.get("status", "").strip()

        where = []
        params = []
        if q:
            where.append("(plate_no LIKE ? OR vehicle_type LIKE ? OR model LIKE ? OR partner_name LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like, like])
        if type_filter:
            where.append("vehicle_type = ?")
            params.append(type_filter)
        if ownership_filter:
            where.append("ownership_type = ?")
            params.append(ownership_filter)
        if status_filter:
            where.append("status = ?")
            params.append(status_filter)

        where_sql = " AND ".join(where) if where else "TRUE"

        vehicles = db.execute(
            f"""SELECT v.*, va.driver_id, e.full_name AS driver_name
                FROM vehicles v
                LEFT JOIN vehicle_assignments va ON va.vehicle_id = v.plate_no AND va.is_current = 1
                LEFT JOIN employees e ON e.employee_id = va.driver_id
                WHERE {where_sql}
                ORDER BY v.plate_no""",
            params,

        ).fetchall()

        vehicle_types = [r[0] for r in db.execute("SELECT DISTINCT vehicle_type FROM vehicles ORDER BY vehicle_type").fetchall()]
        ownership_types = [r[0] for r in db.execute("SELECT DISTINCT ownership_type FROM vehicles ORDER BY ownership_type").fetchall()]
        stats = {"total": len(vehicles), "active": sum(1 for v in vehicles if (v["status"] or "").lower() == "active")}

        return render_template(
            "fleet/vehicle_list.html",
            vehicles=vehicles,
            stats=stats,
            q=q,
            type_filter=type_filter,
            ownership_filter=ownership_filter,
            status_filter=status_filter,
            vehicle_types=vehicle_types,
            ownership_types=ownership_types,
            VEHICLE_TYPES=VEHICLE_TYPES,
            OWNERSHIP_TYPES=OWNERSHIP_TYPES,
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return f"<h2>Fleet Error</h2><pre>{e}\n\n{tb}</pre>", 500


# ── Add Vehicle ─────────────────────────────────────────────────

@fleet_bp.route("/fleet/vehicles/add", methods=["GET", "POST"])
@_login_required("admin")
def vehicle_add():
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    drivers = _all_employees_drivers()

    if request.method == "POST":
        plate_no = request.form.get("plate_no", "").strip().upper()
        vehicle_type = request.form.get("vehicle_type", "").strip()
        model = request.form.get("model", "").strip()
        year = request.form.get("year", "").strip()
        ownership_type = request.form.get("ownership_type", "").strip()
        partner_name = request.form.get("partner_name", "").strip()
        partner_percent = request.form.get("partner_percent", "").strip()
        driver_id = request.form.get("driver_id", "").strip()
        notes = request.form.get("notes", "").strip()

        if not plate_no or not vehicle_type:
            flash("Plate number and vehicle type are required.", "error")
            return render_template("fleet/vehicle_form.html", v=request.form, drivers=drivers, vehicle_types=VEHICLE_TYPES, ownership_types=OWNERSHIP_TYPES, page_title="Add Vehicle", submit_label="Add Vehicle")

        existing = db.execute("SELECT plate_no FROM vehicles WHERE plate_no = ?", (plate_no,)).fetchone()
        if existing:
            flash(f"Vehicle {plate_no} already exists.", "error")
            return render_template("fleet/vehicle_form.html", v=request.form, drivers=drivers, vehicle_types=VEHICLE_TYPES, ownership_types=OWNERSHIP_TYPES, page_title="Add Vehicle", submit_label="Add Vehicle")

        db.execute(
            "INSERT INTO vehicles (plate_no, vehicle_type, model, year, ownership_type, partner_name, partner_percent, status, notes) VALUES (?,?,?,?,?,?,?,'Active',?)",
            (plate_no, vehicle_type, model, int(year) if year else None, ownership_type, partner_name if ownership_type == "Partnership" else None, float(partner_percent) if partner_percent and ownership_type == "Partnership" else None, notes),
        )
        db.commit()

        if driver_id:
            db.execute(
                "INSERT INTO vehicle_assignments (vehicle_id, driver_id, assigned_from, is_current) VALUES (?,?,?,1)",
                (plate_no, driver_id, date.today().isoformat()),
            )
            db.commit()

        flash(f"Vehicle {plate_no} added.", "success")
        return redirect(url_for("fleet.vehicle_profile", plate_no=plate_no))

    return render_template("fleet/vehicle_form.html", v={}, drivers=drivers, vehicle_types=VEHICLE_TYPES, ownership_types=OWNERSHIP_TYPES, page_title="Add Vehicle", submit_label="Add Vehicle")


# ── Edit Vehicle ────────────────────────────────────────────────

@fleet_bp.route("/fleet/vehicles/<plate_no>/edit", methods=["GET", "POST"])
@_login_required("admin")
def vehicle_edit(plate_no):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    v = db.execute("SELECT * FROM vehicles WHERE plate_no = ?", (plate_no,)).fetchone()
    if not v:
        flash("Vehicle not found.", "error")
        return redirect(url_for("fleet.vehicle_list"))
    drivers = _all_employees_drivers()

    if request.method == "POST":
        vehicle_type = request.form.get("vehicle_type", "").strip()
        model = request.form.get("model", "").strip()
        year = request.form.get("year", "").strip()
        ownership_type = request.form.get("ownership_type", "").strip()
        partner_name = request.form.get("partner_name", "").strip()
        partner_percent = request.form.get("partner_percent", "").strip()
        status = request.form.get("status", "").strip()
        notes = request.form.get("notes", "").strip()

        db.execute(
            "UPDATE vehicles SET vehicle_type=?, model=?, year=?, ownership_type=?, partner_name=?, partner_percent=?, status=?, notes=? WHERE plate_no=?",
            (vehicle_type, model, int(year) if year else None, ownership_type, partner_name if ownership_type == "Partnership" else None, float(partner_percent) if partner_percent and ownership_type == "Partnership" else None, status, notes, plate_no),
        )
        db.commit()
        flash("Vehicle updated.", "success")
        return redirect(url_for("fleet.vehicle_profile", plate_no=plate_no))

    return render_template("fleet/vehicle_form.html", v=v, drivers=drivers, vehicle_types=VEHICLE_TYPES, ownership_types=OWNERSHIP_TYPES, page_title="Edit Vehicle", submit_label="Save Changes")


# ── Vehicle Profile ─────────────────────────────────────────────

@fleet_bp.route("/fleet/vehicles/<plate_no>")
@_login_required("admin")
def vehicle_profile(plate_no):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    v = _vehicle_full(plate_no)
    if not v:
        flash("Vehicle not found.", "error")
        return redirect(url_for("fleet.vehicle_list"))

    active_tab = request.args.get("tab", "overview")

    # Driver history
    driver_history = db.execute(
        """SELECT va.*, e.full_name AS driver_name FROM vehicle_assignments va
           JOIN employees e ON e.employee_id = va.driver_id
           WHERE va.vehicle_id = ? ORDER BY va.assigned_from DESC""",
        (plate_no,),
    ).fetchall()

    # Approved jobs
    approved_jobs = db.execute(
        """SELECT mj.*, s.full_name AS staff_name FROM maintenance_jobs mj
           JOIN field_staff s ON s.staff_id = mj.staff_id
           WHERE mj.vehicle_id = ? AND mj.status = 'approved'
           ORDER BY mj.created_at DESC""",
        (plate_no,),
    ).fetchall()

    return render_template(
        "fleet/vehicle_profile.html",
        v=v,
        active_tab=active_tab,
        driver_history=driver_history,
        approved_jobs=approved_jobs,
        all_drivers=_all_employees_drivers(),
    )


# ── Assign/Replace Driver ───────────────────────────────────────

@fleet_bp.route("/fleet/vehicles/<plate_no>/assign", methods=["POST"])
@_login_required("admin")
def vehicle_assign_driver(plate_no):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()

    driver_id = request.form.get("driver_id", "").strip()
    assigned_from = request.form.get("assigned_from", "").strip() or date.today().isoformat()

    if not driver_id:
        flash("Please select a driver.", "error")
        return redirect(url_for("fleet.vehicle_profile", plate_no=plate_no))

    # Close current assignment
    db.execute(
        "UPDATE vehicle_assignments SET assigned_until = ?, is_current = 0 WHERE vehicle_id = ? AND is_current = 1",
        (assigned_from, plate_no),
    )
    # Insert new assignment
    db.execute(
        "INSERT INTO vehicle_assignments (vehicle_id, driver_id, assigned_from, is_current) VALUES (?,?,?,1)",
        (plate_no, driver_id, assigned_from),
    )
    db.commit()

    flash(f"Driver assigned to {plate_no}.", "success")
    return redirect(url_for("fleet.vehicle_profile", plate_no=plate_no, tab="driver"))


# ── Field Staff: Staff Login ────────────────────────────────────

def _staff_login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        staff_id = session.get("staff_id")
        if not staff_id:
            return redirect(url_for("fleet.staff_login"))
        db = open_db()
        staff = db.execute("SELECT * FROM field_staff WHERE staff_id = ? AND is_active = 1", (staff_id,)).fetchone()
        if not staff:
            session.pop("staff_id", None)
            return redirect(url_for("fleet.staff_login"))
        return f(*args, **kwargs)
    return wrapper


# ═════════════════════════════════════════════════════════════════
# FIELD STAFF PORTAL (separate login)
# ═════════════════════════════════════════════════════════════════

@fleet_bp.route("/staff/login", methods=["GET", "POST"])
def staff_login():
    # Clear any admin session to avoid sidebar conflict
    session.pop("role", None)

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        db = open_db()
        staff = db.execute(
            "SELECT * FROM field_staff WHERE username = ? AND is_active = 1", (username,)
        ).fetchone()
        if staff:
            if check_password_hash(staff["password_hash"], password):
                session["staff_id"] = staff["staff_id"]
                session["staff_name"] = staff["full_name"]
                flash("Welcome, " + staff["full_name"], "success")
                return redirect(url_for("fleet.staff_dashboard"))
        flash("Invalid username or password.", "error")
        return redirect(url_for("fleet.staff_login"))

    return render_template("fleet/staff_login.html")


staff_login.csrf_exempt = True


@fleet_bp.route("/staff/logout")
def staff_logout():
    session.pop("staff_id", None)
    session.pop("staff_name", None)
    return redirect(url_for("fleet.staff_login"))


@fleet_bp.route("/staff/dashboard")
@_staff_login_required
def staff_dashboard():
    db = open_db()
    staff_id = session["staff_id"]

    cash_receipts = db.execute(
        "SELECT * FROM cash_receipts WHERE staff_id = ? ORDER BY receipt_date DESC", (staff_id,)
    ).fetchall()
    total_received = sum(r["amount"] for r in cash_receipts)

    jobs = db.execute(
        "SELECT * FROM maintenance_jobs WHERE staff_id = ? ORDER BY created_at DESC", (staff_id,)
    ).fetchall()
    total_spent = sum(j["amount"] for j in jobs)
    pending_count = sum(1 for j in jobs if j["status"] == "pending")
    approved_count = sum(1 for j in jobs if j["status"] == "approved")

    balance = total_received - total_spent

    return render_template(
        "fleet/staff_dashboard.html",
        cash_receipts=cash_receipts,
        total_received=total_received,
        jobs=jobs,
        total_spent=total_spent,
        pending_count=pending_count,
        approved_count=approved_count,
        balance=balance,
    )


@fleet_bp.route("/staff/jobs/new", methods=["GET", "POST"])
@_staff_login_required
def staff_job_new():
    db = open_db()
    staff_id = session["staff_id"]
    vehicles = db.execute("SELECT * FROM vehicles WHERE status = 'Active' ORDER BY vehicle_type, plate_no").fetchall()

    if request.method == "POST":
        vehicle_id = request.form.get("vehicle_id", "").strip()
        amount = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()

        if not amount or not category:
            flash("Amount and category are required.", "error")
            return render_template("fleet/staff_job_new.html", vehicles=vehicles, categories=MAINTENANCE_CATEGORIES, v=request.form)

        attachment_name = None
        attachment_data = None
        attachment_type = None
        if "attachment" in request.files:
            file = request.files["attachment"]
            if file.filename:
                import base64
                attachment_name = file.filename
                attachment_data = base64.b64encode(file.read()).decode("utf-8")
                attachment_type = file.content_type

        db.execute(
            "INSERT INTO maintenance_jobs (vehicle_id, staff_id, amount, category, description, attachment_name, attachment_data, attachment_type, status) VALUES (?,?,?,?,?,?,?,?,'pending')",
            (vehicle_id or "N/A", staff_id, float(amount), category, description, attachment_name, attachment_data, attachment_type),
        )
        db.commit()
        flash("Job submitted for approval.", "success")
        return redirect(url_for("fleet.staff_dashboard"))

    return render_template("fleet/staff_job_new.html", vehicles=vehicles, categories=MAINTENANCE_CATEGORIES, v={})


staff_job_new.csrf_exempt = True


@fleet_bp.route("/staff/jobs")
@_staff_login_required
def staff_jobs():
    db = open_db()
    staff_id = session["staff_id"]
    jobs = db.execute(
        """SELECT mj.*, v.vehicle_type FROM maintenance_jobs mj
           LEFT JOIN vehicles v ON v.plate_no = mj.vehicle_id
           WHERE mj.staff_id = ? ORDER BY mj.created_at DESC""",
        (staff_id,),
    ).fetchall()
    return render_template("fleet/staff_jobs.html", jobs=jobs)


# ── Staff: Edit Job (only pending, own jobs) ────────────────────

@fleet_bp.route("/staff/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@_staff_login_required
def staff_job_edit(job_id):
    db = open_db()
    staff_id = session["staff_id"]
    job = db.execute("SELECT * FROM maintenance_jobs WHERE id = ? AND staff_id = ? AND status = 'pending'", (job_id, staff_id)).fetchone()
    if not job:
        flash("Job not found or cannot be edited.", "error")
        return redirect(url_for("fleet.staff_jobs"))

    vehicles = db.execute("SELECT * FROM vehicles WHERE status = 'Active' ORDER BY vehicle_type, plate_no").fetchall()

    if request.method == "POST":
        vehicle_id = request.form.get("vehicle_id", "").strip()
        amount = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()

        if not amount or not category:
            flash("Amount and category are required.", "error")
            return render_template("fleet/staff_job_edit.html", job=job, vehicles=vehicles, categories=MAINTENANCE_CATEGORIES)

        attachment_name = job["attachment_name"]
        attachment_data = job["attachment_data"]
        attachment_type = job["attachment_type"]
        if "attachment" in request.files:
            file = request.files["attachment"]
            if file.filename:
                import base64
                attachment_name = file.filename
                attachment_data = base64.b64encode(file.read()).decode("utf-8")
                attachment_type = file.content_type

        db.execute(
            "UPDATE maintenance_jobs SET vehicle_id=?, amount=?, category=?, description=?, attachment_name=?, attachment_data=?, attachment_type=? WHERE id=?",
            (vehicle_id or "N/A", float(amount), category, description, attachment_name, attachment_data, attachment_type, job_id),
        )
        db.commit()
        flash("Job updated.", "success")
        return redirect(url_for("fleet.staff_jobs"))

    return render_template("fleet/staff_job_edit.html", job=job, vehicles=vehicles, categories=MAINTENANCE_CATEGORIES)


staff_job_edit.csrf_exempt = True


# ── Staff: Delete Job (only pending, own jobs) ──────────────────

@fleet_bp.route("/staff/jobs/<int:job_id>/delete", methods=["POST"])
@_staff_login_required
def staff_job_delete(job_id):
    db = open_db()
    staff_id = session["staff_id"]
    job = db.execute("SELECT id FROM maintenance_jobs WHERE id = ? AND staff_id = ? AND status = 'pending'", (job_id, staff_id)).fetchone()
    if not job:
        flash("Job not found or cannot be deleted.", "error")
    else:
        db.execute("DELETE FROM maintenance_jobs WHERE id = ?", (job_id,))
        db.commit()
        flash("Job deleted.", "info")
    return redirect(url_for("fleet.staff_jobs"))


staff_job_delete.csrf_exempt = True


# ═════════════════════════════════════════════════════════════════
# ADMIN: Field Staff Management
# ═════════════════════════════════════════════════════════════════

@fleet_bp.route("/fleet/staff")
@_login_required("admin")
def fleet_staff_list():
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    staff_list = db.execute("SELECT * FROM field_staff ORDER BY full_name").fetchall()
    return render_template("fleet/fleet_staff_list.html", staff_list=staff_list)


@fleet_bp.route("/fleet/staff/add", methods=["GET", "POST"])
@_login_required("admin")
def fleet_staff_add():
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()

    if request.method == "POST":
        staff_id = request.form.get("staff_id", "").strip().upper()
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not staff_id or not full_name or not username or not password:
            flash("Staff ID, name, username, and password are required.", "error")
            return render_template("fleet/fleet_staff_form.html", page_title="Add Field Staff", submit_label="Add Staff", s=request.form)

        existing = db.execute("SELECT staff_id FROM field_staff WHERE staff_id = ?", (staff_id,)).fetchone()
        if existing:
            flash("Staff ID already exists.", "error")
            return render_template("fleet/fleet_staff_form.html", page_title="Add Field Staff", submit_label="Add Staff", s=request.form)

        existing_user = db.execute("SELECT staff_id FROM field_staff WHERE username = ?", (username,)).fetchone()
        if existing_user:
            flash("Username already taken.", "error")
            return render_template("fleet/fleet_staff_form.html", page_title="Add Field Staff", submit_label="Add Staff", s=request.form)

        pw_hash = generate_password_hash(password)
        db.execute(
            "INSERT INTO field_staff (staff_id, full_name, phone, username, password_hash) VALUES (?,?,?,?,?)",
            (staff_id, full_name, phone, username, pw_hash),
        )
        db.commit()
        flash(f"Staff {full_name} added.", "success")
        return redirect(url_for("fleet.fleet_staff_list"))

    return render_template("fleet/fleet_staff_form.html", page_title="Add Field Staff", submit_label="Add Staff", s={})


@fleet_bp.route("/fleet/staff/<staff_id>/edit", methods=["GET", "POST"])
@_login_required("admin")
def fleet_staff_edit(staff_id):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    s = db.execute("SELECT * FROM field_staff WHERE staff_id = ?", (staff_id,)).fetchone()
    if not s:
        flash("Staff not found.", "error")
        return redirect(url_for("fleet.fleet_staff_list"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        is_active = 1 if request.form.get("is_active") else 0

        if not full_name or not username:
            flash("Name and username are required.", "error")
            return render_template("fleet/fleet_staff_form.html", page_title="Edit Staff", submit_label="Save Changes", s=request.form)

        if password:
            pw_hash = generate_password_hash(password)
            db.execute("UPDATE field_staff SET full_name=?, phone=?, username=?, password_hash=?, is_active=? WHERE staff_id=?",
                       (full_name, phone, username, pw_hash, is_active, staff_id))
        else:
            db.execute("UPDATE field_staff SET full_name=?, phone=?, username=?, is_active=? WHERE staff_id=?",
                       (full_name, phone, username, is_active, staff_id))
        db.commit()
        flash("Staff updated.", "success")
        return redirect(url_for("fleet.fleet_staff_list"))

    return render_template("fleet/fleet_staff_form.html", page_title="Edit Staff", submit_label="Save Changes", s=s)


# ── ADMIN: Cash Receipts ────────────────────────────────────────

@fleet_bp.route("/fleet/staff/<staff_id>/receipts", methods=["GET", "POST"])
@_login_required("admin")
def fleet_staff_receipts(staff_id):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    s = db.execute("SELECT * FROM field_staff WHERE staff_id = ?", (staff_id,)).fetchone()
    if not s:
        flash("Staff not found.", "error")
        return redirect(url_for("fleet.fleet_staff_list"))

    if request.method == "POST":
        given_by = request.form.get("given_by", "").strip()
        amount = request.form.get("amount", "").strip()
        receipt_date = request.form.get("receipt_date", "").strip() or date.today().isoformat()
        notes = request.form.get("notes", "").strip()

        if not given_by or not amount:
            flash("Given by and amount are required.", "error")
            return redirect(url_for("fleet.fleet_staff_receipts", staff_id=staff_id))

        db.execute(
            "INSERT INTO cash_receipts (staff_id, given_by, amount, receipt_date, notes) VALUES (?,?,?,?,?)",
            (staff_id, given_by, float(amount), receipt_date, notes),
        )
        db.commit()
        flash(f"AED {amount} receipt added.", "success")
        return redirect(url_for("fleet.fleet_staff_receipts", staff_id=staff_id))

    receipts = db.execute(
        "SELECT * FROM cash_receipts WHERE staff_id = ? ORDER BY receipt_date DESC", (staff_id,)
    ).fetchall()
    total = sum(r["amount"] for r in receipts)
    return render_template("fleet/fleet_staff_receipts.html", s=s, receipts=receipts, total=total)


# ── ADMIN: Pending Approvals ────────────────────────────────────

@fleet_bp.route("/fleet/approvals")
@_login_required("admin")
def fleet_approvals():
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()

    pending_jobs = db.execute(
        """SELECT mj.*, v.vehicle_type, COALESCE(v.plate_no, mj.vehicle_id) AS plate_no, s.full_name AS staff_name
           FROM maintenance_jobs mj
           LEFT JOIN vehicles v ON v.plate_no = mj.vehicle_id
           JOIN field_staff s ON s.staff_id = mj.staff_id
           WHERE mj.status = 'pending'
           ORDER BY mj.created_at DESC""",
    ).fetchall()

    recent_approved = db.execute(
        """SELECT mj.*, COALESCE(v.plate_no, mj.vehicle_id) AS plate_no, s.full_name AS staff_name
           FROM maintenance_jobs mj
           LEFT JOIN vehicles v ON v.plate_no = mj.vehicle_id
           JOIN field_staff s ON s.staff_id = mj.staff_id
           WHERE mj.status IN ('approved','rejected')
           ORDER BY mj.created_at DESC LIMIT 20""",
    ).fetchall()

    return render_template("fleet/fleet_approvals.html", pending_jobs=pending_jobs, recent_approved=recent_approved)


@fleet_bp.route("/fleet/jobs/<int:job_id>/approve", methods=["POST"])
@_login_required("admin")
def fleet_job_approve(job_id):
    _touch_admin_workspace("fleet")
    db = open_db()
    job = db.execute("SELECT * FROM maintenance_jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        flash("Job not found.", "error")
        return redirect(url_for("fleet.fleet_approvals"))
    db.execute(
        "UPDATE maintenance_jobs SET status = 'approved', approved_at = ? WHERE id = ?",
        (datetime.now().isoformat(), job_id),
    )
    db.commit()
    flash(f"Job #{job_id} approved.", "success")
    return redirect(url_for("fleet.fleet_approvals"))


@fleet_bp.route("/fleet/jobs/<int:job_id>/reject", methods=["POST"])
@_login_required("admin")
def fleet_job_reject(job_id):
    _touch_admin_workspace("fleet")
    db = open_db()
    notes = request.form.get("admin_notes", "").strip() or "Rejected by admin"
    db.execute(
        "UPDATE maintenance_jobs SET status = 'rejected', admin_notes = ? WHERE id = ?",
        (notes, job_id),
    )
    db.commit()
    flash(f"Job #{job_id} rejected.", "info")
    return redirect(url_for("fleet.fleet_approvals"))


# ── Serve Attachment ────────────────────────────────────────────

@fleet_bp.route("/fleet/attachment/<int:job_id>")
@_login_required("admin")
def fleet_attachment(job_id):
    db = open_db()
    job = db.execute("SELECT attachment_data, attachment_name, attachment_type FROM maintenance_jobs WHERE id = ?", (job_id,)).fetchone()
    if not job or not job["attachment_data"]:
        flash("Attachment not found.", "error")
        return redirect(url_for("fleet.fleet_approvals"))
    import base64
    from io import BytesIO
    data = base64.b64decode(job["attachment_data"])
    return send_file(
        BytesIO(data),
        mimetype=job["attachment_type"] or "application/octet-stream",
        as_attachment=False,
        download_name=job["attachment_name"] or f"attachment_{job_id}",
    )


# ═════════════════════════════════════════════════════════════════
# ADMIN: Edit / Delete Jobs
# ═════════════════════════════════════════════════════════════════

@fleet_bp.route("/fleet/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@_login_required("admin")
def fleet_job_edit(job_id):
    _touch_admin_workspace("fleet")
    db = open_db()
    job = db.execute("""SELECT mj.*, v.vehicle_type, fs.full_name as staff_name
                        FROM maintenance_jobs mj
                        LEFT JOIN vehicles v ON v.plate_no = mj.vehicle_id
                        JOIN field_staff fs ON fs.staff_id = mj.staff_id
                        WHERE mj.id = ?""", (job_id,)).fetchone()
    if not job:
        flash("Job not found.", "error")
        return redirect(url_for("fleet.fleet_approvals"))

    vehicles = db.execute("SELECT * FROM vehicles ORDER BY vehicle_type, plate_no").fetchall()

    if request.method == "POST":
        vehicle_id = request.form.get("vehicle_id", "").strip()
        amount = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()

        attachment_name = job["attachment_name"]
        attachment_data = job["attachment_data"]
        attachment_type = job["attachment_type"]
        if "attachment" in request.files:
            file = request.files["attachment"]
            if file.filename:
                import base64
                attachment_name = file.filename
                attachment_data = base64.b64encode(file.read()).decode("utf-8")
                attachment_type = file.content_type

        db.execute(
            """UPDATE maintenance_jobs
               SET vehicle_id=?, amount=?, category=?, description=?,
                   attachment_name=?, attachment_data=?, attachment_type=?
               WHERE id=?""",
            (vehicle_id or "N/A", float(amount), category, description,
             attachment_name, attachment_data, attachment_type, job_id),
        )
        db.commit()
        flash("Job updated.", "success")
        return redirect(url_for("fleet.fleet_approvals"))

    return render_template("fleet/fleet_job_edit.html", job=job, vehicles=vehicles)


@fleet_bp.route("/fleet/jobs/<int:job_id>/delete", methods=["POST"])
@_login_required("admin")
def fleet_job_delete(job_id):
    _touch_admin_workspace("fleet")
    db = open_db()
    job = db.execute("SELECT id FROM maintenance_jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        flash("Job not found.", "error")
    else:
        db.execute("DELETE FROM maintenance_jobs WHERE id = ?", (job_id,))
        db.commit()
        flash("Job deleted.", "info")
    return redirect(url_for("fleet.fleet_approvals"))


# ═════════════════════════════════════════════════════════════════
# ENDPOINT: Staff can view their own attachment
# ═════════════════════════════════════════════════════════════════

@fleet_bp.route("/staff/attachment/<int:job_id>")
@_staff_login_required
def staff_attachment(job_id):
    db = open_db()
    staff_id = session["staff_id"]
    job = db.execute(
        "SELECT attachment_data, attachment_name, attachment_type FROM maintenance_jobs WHERE id = ? AND staff_id = ?",
        (job_id, staff_id),
    ).fetchone()
    if not job or not job["attachment_data"]:
        flash("Attachment not found.", "error")
        return redirect(url_for("fleet.staff_jobs"))
    import base64
    from io import BytesIO
    data = base64.b64decode(job["attachment_data"])
    return send_file(
        BytesIO(data),
        mimetype=job["attachment_type"] or "application/octet-stream",
        as_attachment=False,
        download_name=job["attachment_name"] or f"attachment_{job_id}",
    )
