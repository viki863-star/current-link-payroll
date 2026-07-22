import sqlite3
from datetime import date, datetime
from pathlib import Path

from flask import (
    current_app, flash, redirect, render_template, request,
    send_file, url_for, session
)
from werkzeug.security import generate_password_hash

from ..database import open_db
from ..routes import _login_required, _touch_admin_workspace
from ..pdf_service import generate_fuel_report_pdf
from . import fleet_bp


VEHICLE_TYPES = ["Tanker", "Trailer", "Box Truck", "Flatbed", "Crane", "Other"]
OWNERSHIP_TYPES = ["Standard", "Partnership"]
MAINTENANCE_CATEGORIES = ["Oil Change", "Tyre", "Engine", "Body", "Electrical", "Brakes", "AC", "Other"]


_fleet_tables_ensured = False

def ensure_fleet_tables():
    global _fleet_tables_ensured
    if _fleet_tables_ensured:
        return
    _fleet_tables_ensured = True
    db = open_db()
    db.execute("SELECT 1 FROM vehicles LIMIT 1")
    _migrate_vehicle_master(db)
    # Clean up blank staff entries
    db.execute("DELETE FROM field_staff WHERE staff_id IS NULL OR staff_id = ''")
    db.commit()
    # Drop FK constraints on PostgreSQL so staff can be deleted without losing data
    try:
        db.execute("ALTER TABLE maintenance_jobs DROP CONSTRAINT IF EXISTS maintenance_jobs_staff_id_fkey")
    except Exception:
        pass
    try:
        db.execute("ALTER TABLE maintenance_jobs DROP CONSTRAINT IF EXISTS fk_maintenance_jobs_staff_id")
    except Exception:
        pass
    try:
        db.execute("ALTER TABLE maintenance_jobs ALTER COLUMN staff_id DROP NOT NULL")
    except Exception:
        pass
    try:
        db.execute("ALTER TABLE maintenance_jobs ALTER COLUMN staff_id SET DEFAULT ''")
    except Exception:
        pass
    # Create vehicle_documents table
    id_col = "id INTEGER PRIMARY KEY AUTOINCREMENT" if db.backend == "sqlite" else "id SERIAL PRIMARY KEY"
    default_ts = "CURRENT_TIMESTAMP"
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS vehicle_documents (
            {id_col},
            plate_no TEXT NOT NULL,
            doc_name TEXT NOT NULL,
            doc_type TEXT,
            doc_data TEXT,
            uploaded_at TEXT DEFAULT {default_ts},
            notes TEXT
        )
    """)
    real_type = "REAL"
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS fuel_entries (
            {id_col},
            vehicle_plate TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            gallons {real_type} NOT NULL,
            rate_per_gallon {real_type} NOT NULL,
            total_amount {real_type} NOT NULL,
            supplier_id INTEGER,
            supplier_name TEXT NOT NULL,
            notes TEXT,
            source_expense_id INTEGER,
            created_at TEXT DEFAULT {default_ts}
        )
    """)
    db.commit()
    # Fix existing fuel expenses — change earning_type from 'trip' to 'Fuel'
    try:
        db.execute(
            "UPDATE supplier_expenses SET earning_type = 'Fuel' WHERE category = 'Fuel' AND earning_type = 'trip'"
        )
        db.commit()
    except Exception:
        pass


def _migrate_vehicle_master(db):
    """Copy vehicles from old vehicle_master table into vehicles table."""
    try:
        old = db.execute("SELECT id, vehicle_id, vehicle_no, vehicle_type, make_model, status, shift_mode, ownership_mode, source_type, source_party_code, source_asset_code, partner_party_code, partner_name, company_share_percent, partner_share_percent, notes FROM vehicle_master").fetchall()
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
    v = db.execute("SELECT plate_no, vehicle_type, model, year, ownership_type, partner_name, partner_percent, status, notes FROM vehicles WHERE plate_no = ?", (plate_no,)).fetchone()
    if not v:
        vm = db.execute("SELECT id, vehicle_id, vehicle_no, vehicle_type, make_model, status, shift_mode, ownership_mode, source_type, source_party_code, source_asset_code, partner_party_code, partner_name, company_share_percent, partner_share_percent, notes FROM vehicle_master WHERE vehicle_no = ?", (plate_no,)).fetchone()
        if vm:
            v = {
                "plate_no": vm["vehicle_no"],
                "vehicle_type": vm["vehicle_type"],
                "model": vm["make_model"],
                "ownership_type": vm["ownership_mode"],
                "partner_name": vm["partner_name"],
                "partner_percent": vm.get("partner_share_percent"),
                "status": vm["status"],
                "notes": vm["notes"],
                "vehicle_id": vm["vehicle_id"],
            }
        else:
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
    paper_count = db.execute(
        """SELECT COUNT(*) AS c FROM maintenance_papers mp
           JOIN vehicle_master vm ON vm.vehicle_id = mp.vehicle_id
           WHERE vm.vehicle_no = ? AND mp.review_status = 'Approved'""",
        (plate_no,),
    ).fetchone()["c"] or 0
    total_cost = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS t FROM maintenance_jobs WHERE vehicle_id = ? AND status = 'approved'",
        (plate_no,),
    ).fetchone()["t"] or 0
    paper_cost = db.execute(
        """SELECT COALESCE(SUM(mp.total_amount),0) AS t FROM maintenance_papers mp
           JOIN vehicle_master vm ON vm.vehicle_id = mp.vehicle_id
           WHERE vm.vehicle_no = ? AND mp.review_status = 'Approved'""",
        (plate_no,),
    ).fetchone()["t"] or 0
    v["job_count"] = job_count + paper_count
    fuel_cost = 0
    try:
        fuel_cost = float(
            db.execute(
                "SELECT COALESCE(SUM(total_amount),0) AS t FROM fuel_entries WHERE vehicle_plate = ?",
                (plate_no,),
            ).fetchone()["t"] or 0
        )
    except Exception:
        pass
    parts_cost = 0
    try:
        parts_cost = float(
            db.execute(
                "SELECT COALESCE(SUM(net_amount),0) AS t FROM supplier_bills WHERE vehicle_plate = ?",
                (plate_no,),
            ).fetchone()["t"] or 0
        )
    except Exception:
        pass
    v["total_cost"] = float(total_cost) + float(paper_cost) + fuel_cost + parts_cost
    return v


def _all_employees_drivers():
    db = open_db()
    return db.execute(
        "SELECT employee_id, full_name FROM employees WHERE employee_type = 'Driver' AND status = 'Active' ORDER BY full_name"
    ).fetchall()


# ── Fleet Dashboard ─────────────────────────────────────────────

@fleet_bp.route("/fleet")
@_login_required("admin")
def fleet_dashboard():
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()

    vehicles = db.execute("SELECT plate_no, vehicle_type, model, year, ownership_type, partner_name, partner_percent, status, notes FROM vehicles ORDER BY plate_no").fetchall()
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
    paper_cost = db.execute(
        "SELECT COALESCE(SUM(total_amount),0) AS t FROM maintenance_papers WHERE review_status = 'Approved'"
    ).fetchone()["t"] or 0
    total_maintenance_cost = float(total_maintenance_cost) + float(paper_cost)

    recent_jobs = db.execute(
        "SELECT mj.*, COALESCE(v.plate_no, mj.vehicle_id) AS plate_no, v.vehicle_type, s.full_name AS staff_name FROM maintenance_jobs mj LEFT JOIN vehicles v ON v.plate_no = mj.vehicle_id JOIN field_staff s ON s.staff_id = mj.staff_id WHERE mj.status = 'approved' ORDER BY mj.created_at DESC LIMIT 10"
    ).fetchall()

    top_vehicles = db.execute(
        """SELECT COALESCE(v.plate_no, mj.vehicle_id) AS plate_no,
                  v.vehicle_type,
                  SUM(mj.amount) AS total_spent,
                  COUNT(mj.id) AS job_count
           FROM maintenance_jobs mj
           LEFT JOIN vehicles v ON v.plate_no = mj.vehicle_id
           WHERE mj.status = 'approved'
           GROUP BY COALESCE(v.plate_no, mj.vehicle_id), v.vehicle_type
           ORDER BY total_spent DESC
           LIMIT 10"""
    ).fetchall()

    total_pending_cost = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS t FROM maintenance_jobs WHERE status='pending'"
    ).fetchone()["t"] or 0

    # Staff balances
    staff_balances = db.execute("""
        SELECT fs.staff_id, fs.full_name, fs.phone,
            COALESCE(adv.total_adv, 0) AS total_received,
            COALESCE(mj.total_jobs, 0) + COALESCE(mp.total_papers, 0) AS total_spent
        FROM field_staff fs
        LEFT JOIN (SELECT staff_code, SUM(amount) AS total_adv FROM maintenance_staff_advances GROUP BY staff_code) adv ON adv.staff_code = fs.staff_id
        LEFT JOIN (SELECT staff_id, SUM(amount) AS total_jobs FROM maintenance_jobs WHERE status = 'approved' GROUP BY staff_id) mj ON mj.staff_id = fs.staff_id
        LEFT JOIN (SELECT technician_code, SUM(total_amount) AS total_papers FROM maintenance_papers WHERE review_status='Approved' GROUP BY technician_code) mp ON mp.technician_code = fs.staff_id
        WHERE fs.staff_id IS NOT NULL AND fs.staff_id != '' AND fs.staff_id != 'admin'
        ORDER BY fs.full_name
    """).fetchall()

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
        top_vehicles=top_vehicles,
        total_pending_cost=float(total_pending_cost),
        staff_balances=staff_balances,
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
                ORDER BY v.ownership_type, v.plate_no""",
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
        current_app.logger.error("Fleet error: %s", e, exc_info=True)
        flash("An error occurred loading the fleet dashboard.", "error")
        return redirect(url_for("dashboard"))


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

@fleet_bp.route("/fleet/vehicles/<path:plate_no>/edit", methods=["GET", "POST"])
@_login_required("admin")
def vehicle_edit(plate_no):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    try:
        v = db.execute("SELECT plate_no, vehicle_type, model, year, ownership_type, partner_name, partner_percent, status, notes FROM vehicles WHERE plate_no = ?", (plate_no,)).fetchone()
    except Exception as e:
        flash(f"Database error: {e}", "error")
        return redirect(url_for("fleet.vehicle_list"))
    if not v:
        flash("Vehicle not found.", "error")
        return redirect(url_for("fleet.vehicle_list"))
    try:
        drivers = _all_employees_drivers()
    except Exception as e:
        flash(f"Error loading drivers: {e}", "error")
        return redirect(url_for("fleet.vehicle_list"))

    if request.method == "POST":
        new_plate = request.form.get("plate_no", "").strip().upper()
        vehicle_type = request.form.get("vehicle_type", "").strip()
        model = request.form.get("model", "").strip()
        year = request.form.get("year", "").strip()
        ownership_type = request.form.get("ownership_type", "").strip()
        partner_name = request.form.get("partner_name", "").strip()
        partner_percent = request.form.get("partner_percent", "").strip()
        status = request.form.get("status", "").strip()
        notes = request.form.get("notes", "").strip()

        if not new_plate:
            flash("Plate number is required.", "error")
            return render_template("fleet/vehicle_form.html", v=v, drivers=drivers, vehicle_types=VEHICLE_TYPES, ownership_types=OWNERSHIP_TYPES, page_title="Edit Vehicle", submit_label="Save Changes")

        if new_plate != plate_no:
            existing = db.execute("SELECT plate_no FROM vehicles WHERE plate_no = ?", (new_plate,)).fetchone()
            if existing:
                flash(f"Plate number {new_plate} already exists.", "error")
                return render_template("fleet/vehicle_form.html", v=v, drivers=drivers, vehicle_types=VEHICLE_TYPES, ownership_types=OWNERSHIP_TYPES, page_title="Edit Vehicle", submit_label="Save Changes")
            try:
                db.execute(
                    "INSERT INTO vehicles (plate_no, vehicle_type, model, year, ownership_type, partner_name, partner_percent, status, notes) SELECT ?, vehicle_type, model, year, ownership_type, partner_name, partner_percent, status, notes FROM vehicles WHERE plate_no=?",
                    (new_plate, plate_no),
                )
                db.execute(
                    "UPDATE maintenance_jobs SET vehicle_id=? WHERE vehicle_id=?",
                    (new_plate, plate_no),
                )
                db.execute(
                    "UPDATE vehicle_assignments SET vehicle_id=? WHERE vehicle_id=?",
                    (new_plate, plate_no),
                )
                db.execute("DELETE FROM vehicles WHERE plate_no=?", (plate_no,))
            except Exception as e:
                flash(f"Could not update plate number: {e}", "error")
                return render_template("fleet/vehicle_form.html", v=v, drivers=drivers, vehicle_types=VEHICLE_TYPES, ownership_types=OWNERSHIP_TYPES, page_title="Edit Vehicle", submit_label="Save Changes")
        else:
            db.execute(
                "UPDATE vehicles SET vehicle_type=?, model=?, year=?, ownership_type=?, partner_name=?, partner_percent=?, status=?, notes=? WHERE plate_no=?",
                (vehicle_type, model, int(year) if year else None, ownership_type, partner_name if ownership_type == "Partnership" else None, float(partner_percent) if partner_percent and ownership_type == "Partnership" else None, status, notes, plate_no),
            )
        db.commit()
        flash("Vehicle updated.", "success")
        return redirect(url_for("fleet.vehicle_profile", plate_no=new_plate))

    return render_template("fleet/vehicle_form.html", v=v, drivers=drivers, vehicle_types=VEHICLE_TYPES, ownership_types=OWNERSHIP_TYPES, page_title="Edit Vehicle", submit_label="Save Changes")


# ── Vehicle Profile ─────────────────────────────────────────────

@fleet_bp.route("/fleet/vehicles/<path:plate_no>")
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
    highlight = request.args.get("highlight", "")

    # Driver history
    driver_history = db.execute(
        """SELECT va.*, e.full_name AS driver_name FROM vehicle_assignments va
           JOIN employees e ON e.employee_id = va.driver_id
           WHERE va.vehicle_id = ? ORDER BY va.assigned_from DESC""",
        (plate_no,),
    ).fetchall()

    # Approved jobs (maintenance_jobs + maintenance_papers)
    approved_jobs = db.execute(
        """SELECT mj.*, COALESCE(s.full_name, 'Admin') AS staff_name FROM maintenance_jobs mj
           LEFT JOIN field_staff s ON s.staff_id = mj.staff_id
           WHERE mj.vehicle_id = ? AND mj.status = 'approved'
           ORDER BY mj.created_at DESC""",
        (plate_no,),
    ).fetchall()

    raw_papers = db.execute(
        """SELECT mp.paper_no AS id, vm.vehicle_no AS vehicle_id, mp.vehicle_id AS edit_vehicle_id,
                  mp.technician_code AS staff_id,
                  mp.total_amount AS amount, mp.work_summary AS description,
                  mp.review_status AS status, mp.notes AS admin_notes,
                  mp.attachment_path AS attachment_name, mp.created_at,
                  'Maintenance' AS category, '' AS attachment_type,
                  NULL AS attachment_data,
                  COALESCE(s.full_name, '') AS staff_name
           FROM maintenance_papers mp
           JOIN vehicle_master vm ON vm.vehicle_id = mp.vehicle_id
           LEFT JOIN field_staff s ON s.staff_id = mp.technician_code
           WHERE vm.vehicle_no = ?
             AND mp.review_status IN ('Approved', 'Pending')
           ORDER BY mp.created_at DESC""",
        (plate_no,),
    ).fetchall()
    maintenance_papers_list = []
    for r in raw_papers:
        d = dict(r)
        if isinstance(d.get("created_at"), datetime):
            d["created_at"] = d["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        maintenance_papers_list.append(d)

    approved_jobs_list = []
    for r in approved_jobs:
        d = dict(r)
        if isinstance(d.get("created_at"), datetime):
            d["created_at"] = d["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        approved_jobs_list.append(d)

    combined = sorted(
        approved_jobs_list + maintenance_papers_list,
        key=lambda x: (x.get("created_at") or ""),
        reverse=True,
    )

    documents = db.execute(
        "SELECT id, plate_no, doc_name, doc_type, doc_data, uploaded_at, notes FROM vehicle_documents WHERE plate_no = ? ORDER BY uploaded_at DESC",
        (plate_no,),
    ).fetchall()

    fuel_entries = db.execute(
        "SELECT id, vehicle_plate, entry_date, gallons, rate_per_gallon, total_amount, supplier_id, supplier_name, notes, source_expense_id, created_at FROM fuel_entries WHERE vehicle_plate = ? ORDER BY entry_date DESC, id DESC",
        (plate_no,),
    ).fetchall()
    fuel_total_gallons = sum(f["gallons"] for f in fuel_entries) if fuel_entries else 0
    fuel_total_amount = sum(f["total_amount"] for f in fuel_entries) if fuel_entries else 0
    suppliers = db.execute("SELECT id, supplier_name FROM suppliers WHERE status = 'Active' ORDER BY supplier_name").fetchall()

    # Supplier bills (Parts) for this vehicle
    try:
        supplier_bills = db.execute(
            """SELECT sb.*, s.supplier_name FROM supplier_bills sb
               JOIN suppliers s ON s.id = sb.supplier_id
               WHERE sb.vehicle_plate = ? ORDER BY sb.bill_date DESC, sb.id DESC""",
            (plate_no,),
        ).fetchall()
    except Exception:
        supplier_bills = []
    parts_total_amount = sum(b["total_amount"] for b in supplier_bills) if supplier_bills else 0
    parts_total_vat = sum(b["vat_amount"] for b in supplier_bills) if supplier_bills else 0
    parts_total_net = sum(b["net_amount"] for b in supplier_bills) if supplier_bills else 0

    return render_template(
        "fleet/vehicle_profile.html",
        v=v,
        active_tab=active_tab,
        highlight=highlight,
        driver_history=driver_history,
        approved_jobs=approved_jobs_list,
        maintenance_papers_list=maintenance_papers_list,
        combined_jobs=combined,
        all_drivers=_all_employees_drivers(),
        documents=documents,
        fuel_entries=fuel_entries,
        fuel_total_gallons=fuel_total_gallons,
        fuel_total_amount=fuel_total_amount,
        supplier_bills=supplier_bills,
        parts_total_amount=parts_total_amount,
        parts_total_vat=parts_total_vat,
        parts_total_net=parts_total_net,
        suppliers=suppliers,
        date=date,
    )


# ── Delete Vehicle ────────────────────────────────────────────

@fleet_bp.route("/fleet/vehicles/<path:plate_no>/delete", methods=["POST"])
@_login_required("admin")
def vehicle_delete(plate_no):
    _touch_admin_workspace("fleet")
    db = open_db()
    v = _vehicle_full(plate_no)
    if not v:
        flash("Vehicle not found.", "error")
        return redirect(url_for("fleet.vehicle_list"))
    db.execute("DELETE FROM vehicle_assignments WHERE vehicle_id = ?", (plate_no,))
    db.execute("DELETE FROM vehicles WHERE plate_no = ?", (plate_no,))
    db.commit()
    flash(f"Vehicle {plate_no} deleted.", "success")
    return redirect(url_for("fleet.vehicle_list"))


# ── Assign/Replace Driver ───────────────────────────────────────

@fleet_bp.route("/fleet/vehicles/<path:plate_no>/assign", methods=["POST"])
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
        staff = db.execute("SELECT staff_id, full_name, phone, username, password_hash, is_active FROM field_staff WHERE staff_id = ? AND is_active = 1", (staff_id,)).fetchone()
        if not staff:
            session.pop("staff_id", None)
            return redirect(url_for("fleet.staff_login"))
        return f(*args, **kwargs)
    return wrapper


# ── Vehicle Documents ─────────────────────────────────────────────

@fleet_bp.route("/fleet/vehicles/<path:plate_no>/documents/upload", methods=["POST"])
@_login_required("admin")
def vehicle_document_upload(plate_no):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    v = _vehicle_full(plate_no)
    if not v:
        flash("Vehicle not found.", "error")
        return redirect(url_for("fleet.vehicle_list"))
    doc_name = request.form.get("doc_name", "").strip()
    notes = request.form.get("notes", "").strip()
    if not doc_name:
        flash("Document name is required.", "error")
        return redirect(url_for("fleet.vehicle_profile", plate_no=plate_no))
    import base64
    doc_data = None
    doc_type = None
    if "doc_file" in request.files:
        f = request.files["doc_file"]
        if f.filename:
            doc_data = base64.b64encode(f.read()).decode("utf-8")
            doc_type = f.content_type
    db.execute(
        "INSERT INTO vehicle_documents (plate_no, doc_name, doc_type, doc_data, notes) VALUES (?,?,?,?,?)",
        (plate_no, doc_name, doc_type, doc_data, notes),
    )
    db.commit()
    flash(f"Document '{doc_name}' uploaded.", "success")
    return redirect(url_for("fleet.vehicle_profile", plate_no=plate_no))


@fleet_bp.route("/fleet/vehicles/<path:plate_no>/documents/<int:doc_id>/delete", methods=["POST"])
@_login_required("admin")
def vehicle_document_delete(plate_no, doc_id):
    _touch_admin_workspace("fleet")
    db = open_db()
    db.execute("DELETE FROM vehicle_documents WHERE id = ? AND plate_no = ?", (doc_id, plate_no))
    db.commit()
    flash("Document deleted.", "success")
    return redirect(url_for("fleet.vehicle_profile", plate_no=plate_no))


@fleet_bp.route("/fleet/vehicles/<path:plate_no>/documents/<int:doc_id>/view")
@_login_required("admin")
def vehicle_document_view(plate_no, doc_id):
    db = open_db()
    doc = db.execute("SELECT id, plate_no, doc_name, doc_type, doc_data, uploaded_at, notes FROM vehicle_documents WHERE id = ? AND plate_no = ?", (doc_id, plate_no)).fetchone()
    if not doc or not doc["doc_data"]:
        flash("Document not found.", "error")
        return redirect(url_for("fleet.vehicle_profile", plate_no=plate_no))
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

# FIELD STAFF PORTAL (separate login)
# ═════════════════════════════════════════════════════════════════

@fleet_bp.route("/staff/login", methods=["GET", "POST"])
def staff_login():
    return redirect(url_for("technician_login"))


staff_login.csrf_exempt = True


@fleet_bp.route("/staff/logout")
def staff_logout():
    return redirect(url_for("logout"))


@fleet_bp.route("/staff/dashboard")
def staff_dashboard():
    return redirect(url_for("technician_portal"))


@fleet_bp.route("/staff/jobs/new", methods=["GET", "POST"])
@_staff_login_required
def staff_job_new():
    db = open_db()
    staff_id = session["staff_id"]
    vehicles = db.execute("SELECT plate_no, vehicle_type, model, year, ownership_type, partner_name, partner_percent, status, notes FROM vehicles WHERE status = 'Active' ORDER BY vehicle_type, plate_no").fetchall()

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
        try:
            from app.notification_service import add_notification
            add_notification(
                title=f"Job submitted for approval",
                type="success",
                role="technician",
                message=f"{category} — AED {amount} on {vehicle_id or 'N/A'}",
            )
            add_notification(
                title=f"New job submitted by {session.get('staff_name','Field Staff')}",
                type="pending_approvals",
                role="admin",
                message=f"{category} — AED {amount} on {vehicle_id or 'N/A'}",
                link="/fleet/approvals",
            )
        except:
            pass
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
    job = db.execute("SELECT id, vehicle_id, staff_id, amount, category, description, attachment_name, attachment_data, attachment_type, status, admin_notes, approved_at FROM maintenance_jobs WHERE id = ? AND staff_id = ? AND status = 'pending'", (job_id, staff_id)).fetchone()
    if not job:
        flash("Job not found or cannot be edited.", "error")
        return redirect(url_for("fleet.staff_jobs"))

    vehicles = db.execute("SELECT plate_no, vehicle_type, model, year, ownership_type, partner_name, partner_percent, status, notes FROM vehicles WHERE status = 'Active' ORDER BY vehicle_type, plate_no").fetchall()

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

def _sync_field_staff_to_technician(db, staff_id, full_name, phone, username, pw_hash, is_active):
    status = "Active" if is_active else "Inactive"

    existing = db.execute(
        "SELECT technician_code FROM technicians WHERE technician_code = ?",
        (staff_id,),
    ).fetchone()
    if existing:
        db.execute("""
            UPDATE technicians
            SET user_id = ?, password_hash = ?, phone_number = ?,
                specialization = ?, status = ?
            WHERE technician_code = ?
        """, (username, pw_hash, phone, full_name, status, staff_id))
        return

    user_taken = db.execute(
        "SELECT technician_code FROM technicians WHERE user_id = ?",
        (username,),
    ).fetchone()
    if user_taken:
        db.execute("""
            UPDATE technicians
            SET technician_code = ?, password_hash = ?, phone_number = ?,
                specialization = ?, status = ?
            WHERE user_id = ?
        """, (staff_id, pw_hash, phone, full_name, status, username))
        return

    db.execute("""
        INSERT INTO technicians
        (technician_code, party_code, user_id, password_hash, phone_number, specialization, status)
        VALUES (?, NULL, ?, ?, ?, ?, ?)
    """, (staff_id, username, pw_hash, phone, full_name, status))


def _import_field_staff_from_sqlite(db):
    backend = current_app.config.get("DATABASE_BACKEND", "sqlite")
    if backend != "postgres":
        return
    existing = db.execute("SELECT COUNT(*) AS c FROM field_staff").fetchone()["c"] or 0
    if existing > 0:
        return
    try:
        sqlite_path = Path(current_app.config.get("DATABASE", "payroll.db"))
        if not sqlite_path.exists():
            sqlite_path = Path(current_app.root_path).parent / "payroll.db"
        if not sqlite_path.exists():
            return
        sdb = sqlite3.connect(str(sqlite_path))
        sdb.row_factory = sqlite3.Row
    except Exception:
        return

    try:
        old_staff = sdb.execute("SELECT staff_id, full_name, phone, username, password_hash, is_active FROM field_staff").fetchall()
    except Exception:
        old_staff = []

    for s in old_staff:
        try:
            pw_hash = s["password_hash"] or generate_password_hash("changeme123")
            db.execute(
                """INSERT INTO field_staff (staff_id, full_name, phone, username, password_hash, is_active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))""",
                (s["staff_id"], s["full_name"], s["phone"] or "", s["username"],
                 pw_hash, s["is_active"], s.get("created_at")),
            )
        except Exception:
            pass
    if old_staff:
        db.commit()

    try:
        old_jobs = sdb.execute("SELECT id, vehicle_id, staff_id, amount, category, description, attachment_name, attachment_data, attachment_type, status, admin_notes, approved_at FROM maintenance_jobs").fetchall()
    except Exception:
        old_jobs = []

    existing_papers = set()
    try:
        rows = db.execute("SELECT paper_no FROM maintenance_papers").fetchall()
        existing_papers = {r["paper_no"] for r in rows}
    except Exception:
        pass

    for j in old_jobs:
        pno = f"PAPER-{j['id']:04d}"
        if pno in existing_papers:
            continue
        status_map = {"pending": "Pending", "approved": "Approved", "rejected": "Rejected"}
        rev_status = status_map.get(j["status"], "Pending")
        paper_date = (j["created_at"] or "")[:10] or "2025-01-01"
        try:
            db.execute("""
                INSERT INTO maintenance_papers
                (paper_no, paper_date, vehicle_id, technician_code, work_summary,
                 total_amount, review_status, payment_status, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?)
            """, (pno, paper_date, j["vehicle_id"], j["staff_id"],
                  j["description"] or "", j["amount"], rev_status,
                  j["admin_notes"] or "", j["created_at"]))
            existing_papers.add(pno)
        except Exception:
            pass
    if old_jobs:
        db.commit()

    try:
        sdb.close()
    except Exception:
        pass


def _import_maintenance_staff_from_sqlite(db):
    backend = current_app.config.get("DATABASE_BACKEND", "sqlite")
    if backend != "postgres":
        return
    try:
        sqlite_path = Path(current_app.config.get("DATABASE", "payroll.db"))
        if not sqlite_path.exists():
            sqlite_path = Path(current_app.root_path).parent / "payroll.db"
        if not sqlite_path.exists():
            return
        sdb = sqlite3.connect(str(sqlite_path))
        sdb.row_factory = sqlite3.Row
    except Exception:
        return
    try:
        old_staff = sdb.execute("SELECT id, staff_id, full_name, phone, role, status, created_at FROM maintenance_staff").fetchall()
    except Exception:
        old_staff = []
    for s in old_staff:
        code = s["staff_code"]
        existing = db.execute("SELECT staff_code FROM maintenance_staff WHERE staff_code = ?", (code,)).fetchone()
        if existing:
            continue
        try:
            db.execute("""
                INSERT INTO maintenance_staff (staff_code, staff_name, phone_number, status, notes, created_at)
                VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """, (code, s["staff_name"], s["phone_number"] or "", s["status"] or "Active",
                  s["notes"] or "", s.get("created_at")))
        except Exception:
            pass
        already = db.execute("SELECT staff_id FROM field_staff WHERE staff_id = ?", (code,)).fetchone()
        if already:
            continue
        name = s["staff_name"]
        username = (code + name)[:20].lower().replace("-", "").replace(" ", "")
        pw_hash = generate_password_hash("changeme123")
        try:
            db.execute("""
                INSERT INTO field_staff (staff_id, full_name, phone, username, password_hash, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (code, name, s["phone_number"] or "", username, pw_hash))
        except Exception:
            continue
        try:
            db.execute("""
                INSERT INTO technicians (technician_code, party_code, user_id, password_hash, phone_number, specialization, status)
                VALUES (?, NULL, ?, ?, ?, ?, 'Active')
            """, (code, username, pw_hash, s["phone_number"] or "", name))
        except Exception:
            pass
    db.execute("""
        UPDATE maintenance_papers mp
        SET technician_code = fs.staff_id
        FROM field_staff fs
        WHERE mp.technician_code IS NULL
        AND mp.staff_code IS NOT NULL
        AND mp.staff_code = fs.staff_id
    """)
    if old_staff:
        db.commit()
    try:
        sdb.close()
    except Exception:
        pass


def _import_orphaned_maintenance_jobs(db):
    orphan_staff = db.execute("""
        SELECT DISTINCT mj.staff_id FROM maintenance_jobs mj
        LEFT JOIN field_staff fs ON fs.staff_id = mj.staff_id
        WHERE fs.staff_id IS NULL
    """).fetchall()
    for row in orphan_staff:
        staff_id = row["staff_id"]
        sample = db.execute(
            "SELECT mj.* FROM maintenance_jobs mj WHERE mj.staff_id = ? LIMIT 1",
            (staff_id,),
        ).fetchone()
        if not sample:
            continue
        name = f"Staff {staff_id}"
        username = staff_id.lower()
        pw_hash = generate_password_hash("changeme123")
        try:
            db.execute("""
                INSERT INTO field_staff (staff_id, full_name, phone, username, password_hash, is_active)
                VALUES (?, ?, '', ?, ?, 1)
            """, (staff_id, name, username, pw_hash))
        except Exception:
            continue
        try:
            db.execute("""
                INSERT INTO technicians (technician_code, party_code, user_id, password_hash, phone_number, specialization, status)
                VALUES (?, NULL, ?, ?, '', ?, 'Active')
            """, (staff_id, username, pw_hash, name))
        except Exception:
            pass
    if orphan_staff:
        db.commit()


@fleet_bp.route("/fleet/maintenance-entry", methods=["GET", "POST"])
@_login_required("admin")
def fleet_maintenance_entry():
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    vehicles = db.execute("SELECT plate_no, vehicle_type, model FROM vehicles ORDER BY plate_no").fetchall()
    # Ensure admin pseudo-staff exists for direct entries
    if not db.execute("SELECT staff_id FROM field_staff WHERE staff_id='admin'").fetchone():
        try:
            db.execute("INSERT INTO field_staff (staff_id, full_name, username, password_hash, phone, is_active) VALUES ('admin','System Admin','admin','',NULL,1)")
            db.commit()
        except Exception:
            pass
    if request.method == "POST":
        import base64
        vehicle_id = request.form.get("vehicle_id", "").strip()
        amount = request.form.get("amount", "0").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        entry_date = request.form.get("entry_date", "").strip() or date.today().isoformat()
        if not vehicle_id:
            flash("Please select a vehicle.", "error")
            return render_template("fleet/fleet_maintenance_entry.html", vehicles=vehicles, today=date.today().isoformat())
        try:
            amount = float(amount) if amount else 0
        except ValueError:
            amount = 0
        attachment_name = None
        attachment_data = None
        attachment_type = None
        if request.files and "attachment" in request.files:
            f = request.files["attachment"]
            if f and f.filename:
                attachment_name = f.filename
                attachment_data = base64.b64encode(f.read()).decode("utf-8")
                attachment_type = f.content_type or "application/octet-stream"
        db.execute(
            "INSERT INTO maintenance_jobs (vehicle_id, staff_id, amount, category, description, status, created_at, attachment_name, attachment_data, attachment_type) VALUES (?, ?, ?, ?, ?, 'approved', ?, ?, ?, ?)",
            (vehicle_id, 'admin', amount, category, description, entry_date, attachment_name, attachment_data, attachment_type)
        )
        db.commit()
        db.close()
        flash(f"Maintenance entry added and approved for vehicle {vehicle_id}.", "success")
        return redirect(url_for("fleet.vehicle_profile", plate_no=vehicle_id))
    return render_template("fleet/fleet_maintenance_entry.html", vehicles=vehicles, today=date.today().isoformat())


@fleet_bp.route("/fleet/vehicles/<path:plate_no>/add-maintenance", methods=["POST"])
@_login_required("admin")
def vehicle_add_maintenance(plate_no):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    v = _vehicle_full(plate_no)
    if not v:
        flash("Vehicle not found.", "error")
        return redirect(url_for("fleet.vehicle_list"))
    import base64
    amount = request.form.get("amount", "0").strip()
    category = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()
    entry_date = request.form.get("entry_date", "").strip() or date.today().isoformat()
    try:
        amount = float(amount) if amount else 0
    except ValueError:
        amount = 0
    attachment_name = None
    attachment_data = None
    attachment_type = None
    if request.files and "attachment" in request.files:
        f = request.files["attachment"]
        if f and f.filename:
            attachment_name = f.filename
            attachment_data = base64.b64encode(f.read()).decode("utf-8")
            attachment_type = f.content_type or "application/octet-stream"
    db.execute(
        "INSERT INTO maintenance_jobs (vehicle_id, staff_id, amount, category, description, status, created_at, attachment_name, attachment_data, attachment_type) VALUES (?, ?, ?, ?, ?, 'approved', ?, ?, ?, ?)",
        (plate_no, 'admin', amount, category, description, entry_date, attachment_name, attachment_data, attachment_type)
    )
    db.commit()
    db.close()
    flash(f"Maintenance entry added for {plate_no}.", "success")
    return redirect(url_for("fleet.vehicle_profile", plate_no=plate_no, tab="jobs"))


@fleet_bp.route("/fleet/staff")
@_login_required("admin")
def fleet_staff_list():
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    _import_field_staff_from_sqlite(db)
    _import_maintenance_staff_from_sqlite(db)
    _import_orphaned_maintenance_jobs(db)

    unsynced = db.execute("""
        SELECT fs.* FROM field_staff fs
        LEFT JOIN technicians t ON t.technician_code = fs.staff_id
        WHERE t.technician_code IS NULL
    """).fetchall()
    for row in unsynced:
        pw_hash = row["password_hash"] or generate_password_hash("changeme123")
        _sync_field_staff_to_technician(
            db, row["staff_id"], row["full_name"],
            row["phone"] or "", row["username"],
            pw_hash, row["is_active"],
        )
    if unsynced:
        db.commit()

    staff_list = db.execute("""
        SELECT fs.*,
            COALESCE(ec.entry_count, 0) AS entry_count,
            COALESCE(ac.advance_count, 0) AS advance_count
        FROM field_staff fs
        LEFT JOIN (
            SELECT technician_code, COUNT(*) AS entry_count
            FROM maintenance_papers GROUP BY technician_code
        ) ec ON ec.technician_code = fs.staff_id
        LEFT JOIN (
            SELECT staff_code, COUNT(*) AS advance_count
            FROM maintenance_staff_advances GROUP BY staff_code
        ) ac ON ac.staff_code = fs.staff_id
        WHERE fs.staff_id IS NOT NULL AND fs.staff_id != ''
        ORDER BY fs.full_name
    """).fetchall()
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
        _sync_field_staff_to_technician(db, staff_id, full_name, phone, username, pw_hash, 1)
        db.commit()
        flash(f"Staff {full_name} added.", "success")
        return redirect(url_for("fleet.fleet_staff_list"))

    return render_template("fleet/fleet_staff_form.html", page_title="Add Field Staff", submit_label="Add Staff", s={})


@fleet_bp.route("/fleet/staff/<staff_id>/delete", methods=["POST"])
@_login_required("admin")
def fleet_staff_delete(staff_id):
    _touch_admin_workspace("fleet")
    db = open_db()
    s = db.execute("SELECT staff_id, full_name, phone, username, password_hash, is_active FROM field_staff WHERE staff_id = ?", (staff_id,)).fetchone()
    if not s:
        flash("Staff not found.", "error")
        return redirect(url_for("fleet.fleet_staff_list"))
    # Nullify references so submitted data is preserved
    ALLOWED_TABLES = {"maintenance_jobs", "maintenance_papers", "maintenance_staff_advances"}
    ALLOWED_FIELDS = {"staff_id", "technician_code", "staff_code"}
    for tbl, col in [("maintenance_jobs", "staff_id"), ("maintenance_papers", "technician_code"), ("maintenance_staff_advances", "staff_code")]:
        if tbl not in ALLOWED_TABLES or col not in ALLOWED_FIELDS:
            continue
        try:
            db.execute(f"UPDATE {tbl} SET {col}='' WHERE {col}=?", (staff_id,))
        except Exception:
            try:
                db.execute(f"UPDATE {tbl} SET {col}=NULL WHERE {col}=?", (staff_id,))
            except Exception:
                pass
    db.execute("DELETE FROM field_staff WHERE staff_id = ?", (staff_id,))
    db.execute("DELETE FROM technicians WHERE technician_code = ?", (staff_id,))
    db.commit()
    flash(f"Staff {s['full_name']} deleted. Submitted data preserved.", "success")
    return redirect(url_for("fleet.fleet_staff_list"))


@fleet_bp.route("/fleet/staff/<staff_id>/edit", methods=["GET", "POST"])
@_login_required("admin")
def fleet_staff_edit(staff_id):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    s = db.execute("SELECT staff_id, full_name, phone, username, password_hash, is_active FROM field_staff WHERE staff_id = ?", (staff_id,)).fetchone()
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
            pw_hash = s["password_hash"]
            db.execute("UPDATE field_staff SET full_name=?, phone=?, username=?, is_active=? WHERE staff_id=?",
                       (full_name, phone, username, is_active, staff_id))
        _sync_field_staff_to_technician(db, staff_id, full_name, phone, username, pw_hash, is_active)
        db.commit()
        flash("Staff updated.", "success")
        return redirect(url_for("fleet.fleet_staff_list"))

    return render_template("fleet/fleet_staff_form.html", page_title="Edit Staff", submit_label="Save Changes", s=s)


# ── ADMIN: Cash Receipts ────────────────────────────────────────


@fleet_bp.route("/fleet/staff/<staff_id>/advances/<int:advance_id>/delete", methods=["POST"])
@_login_required("admin")
def fleet_staff_advance_delete(staff_id, advance_id):
    _touch_admin_workspace("fleet")
    db = open_db()
    a = db.execute("SELECT id, amount, funding_source, reference, notes, entry_date, created_at, staff_code FROM maintenance_staff_advances WHERE id = ? AND staff_code = ?", (advance_id, staff_id)).fetchone()
    if a:
        db.execute("DELETE FROM maintenance_staff_advances WHERE id = ?", (advance_id,))
        db.commit()
        flash("Advance deleted.", "success")
    return redirect(url_for("fleet.fleet_staff_profile", staff_id=staff_id))


@fleet_bp.route("/fleet/staff/<staff_id>/advances/<int:advance_id>/edit", methods=["GET", "POST"])
@_login_required("admin")
def fleet_staff_advance_edit(staff_id, advance_id):
    _touch_admin_workspace("fleet")
    db = open_db()
    s = db.execute("SELECT staff_id, full_name, phone, username, password_hash, is_active FROM field_staff WHERE staff_id = ?", (staff_id,)).fetchone()
    if not s:
        flash("Staff not found.", "error")
        return redirect(url_for("fleet.fleet_staff_list"))
    a = db.execute("SELECT id, amount, funding_source, reference, notes, entry_date, created_at, staff_code FROM maintenance_staff_advances WHERE id = ? AND staff_code = ?", (advance_id, staff_id)).fetchone()
    if not a:
        flash("Advance not found.", "error")
        return redirect(url_for("fleet.fleet_staff_profile", staff_id=staff_id))

    if request.method == "POST":
        amount = request.form.get("amount", "").strip()
        entry_date = request.form.get("entry_date", "").strip()
        entry_time = request.form.get("entry_time", "").strip()
        funding_source = request.form.get("funding_source", "").strip() or "Owner Fund"
        given_by = request.form.get("given_by", "").strip()
        notes = request.form.get("notes", "").strip()

        if not amount:
            flash("Amount is required.", "error")
            return render_template("fleet/fleet_advance_edit.html", s=s, a=a, today=date.today().isoformat(), now=datetime.now())

        full_dt = f"{entry_date} {entry_time}" if entry_time else entry_date
        db.execute(
            "UPDATE maintenance_staff_advances SET amount=?, entry_date=?, funding_source=?, reference=?, notes=? WHERE id=?",
            (float(amount), full_dt, funding_source, given_by or session.get("username", "Admin"), notes or "", advance_id),
        )
        db.commit()
        flash("Advance updated.", "success")
        return redirect(url_for("fleet.fleet_staff_profile", staff_id=staff_id))

    return render_template("fleet/fleet_advance_edit.html", s=s, a=a, today=date.today().isoformat(), now=datetime.now())


# ── ADMIN: Staff Profile ─────────────────────────────────────────

@fleet_bp.route("/fleet/staff/<staff_id>/profile", methods=["GET", "POST"])
@_login_required("admin")
def fleet_staff_profile(staff_id):
    import traceback
    try:
        _touch_admin_workspace("fleet")
        ensure_fleet_tables()
        db = open_db()
        s = db.execute("SELECT staff_id, full_name, phone, username, password_hash, is_active FROM field_staff WHERE staff_id = ?", (staff_id,)).fetchone()
        if not s:
            flash("Staff not found.", "error")
            return redirect(url_for("fleet.fleet_staff_list"))

        if request.method == "POST":
            amount = request.form.get("amount", "").strip()
            entry_date = request.form.get("entry_date", "").strip() or date.today().isoformat()
            entry_time = request.form.get("entry_time", "").strip()
            funding_source = request.form.get("funding_source", "").strip() or "Owner Fund"
            given_by = request.form.get("given_by", "").strip()
            notes = request.form.get("notes", "").strip()

            if not amount:
                flash("Amount is required.", "error")
                return redirect(url_for("fleet.fleet_staff_profile", staff_id=staff_id))

            last = db.execute("SELECT advance_no FROM maintenance_staff_advances ORDER BY id DESC LIMIT 1").fetchone()
            num = 1
            if last:
                num = int(last["advance_no"].split("-")[1]) + 1
            adv_no = f"ADV-{num:04d}"
            full_dt = f"{entry_date} {entry_time}" if entry_time else entry_date
            db.execute(
                "INSERT INTO maintenance_staff_advances (advance_no, staff_code, entry_date, funding_source, amount, reference, notes) VALUES (?,?,?,?,?,?,?)",
                (adv_no, staff_id, full_dt, funding_source, float(amount), given_by or session.get("username", "Admin"), notes or ""),
            )
            db.commit()
            flash(f"AED {amount} given to {s['full_name']}.", "success")
            return redirect(url_for("fleet.fleet_staff_profile", staff_id=staff_id))

        month_filter = request.args.get("month", "")
        date_from = request.args.get("date_from", "")
        date_to = request.args.get("date_to", "")
        today_str = date.today().isoformat()
        current_month = today_str[:7]
        filter_month = month_filter[:7] if month_filter else ""

        card_received = db.execute(
            "SELECT COALESCE(SUM(amount),0) AS t FROM maintenance_staff_advances WHERE staff_code = ?",
            (staff_id,),
        ).fetchone()["t"] or 0

        card_jobs = db.execute(
            "SELECT COALESCE(SUM(amount),0) AS t FROM maintenance_jobs WHERE staff_id = ? AND status = 'approved'",
            (staff_id,),
        ).fetchone()["t"] or 0

        card_papers = db.execute(
            "SELECT COALESCE(SUM(mp.total_amount),0) AS t FROM maintenance_papers mp WHERE mp.technician_code = ? AND mp.review_status = 'Approved'",
            (staff_id,),
        ).fetchone()["t"] or 0

        card_spent = float(card_jobs) + float(card_papers)
        card_balance = card_received - card_spent

        # Build date-filter WHERE clause
        date_where = ""
        date_params = []
        if filter_month:
            date_where += " AND substr(CAST(mj.created_at AS TEXT),1,7) = ?"
            date_params.append(filter_month)
        else:
            if date_from:
                date_where += " AND substr(CAST(mj.created_at AS TEXT),1,10) >= ?"
                date_params.append(date_from)
            if date_to:
                date_where += " AND substr(CAST(mj.created_at AS TEXT),1,10) <= ?"
                date_params.append(date_to)
        jobs = db.execute(f"""
            SELECT mj.*, v.vehicle_type FROM maintenance_jobs mj
            LEFT JOIN vehicles v ON v.plate_no = mj.vehicle_id
            WHERE mj.staff_id = ?{date_where} ORDER BY mj.created_at DESC
        """, (staff_id, *date_params)).fetchall()

        paper_where = ""
        paper_params = []
        if filter_month:
            paper_where += " AND substr(CAST(mp.created_at AS TEXT),1,7) = ?"
            paper_params.append(filter_month)
        else:
            if date_from:
                paper_where += " AND substr(CAST(mp.created_at AS TEXT),1,10) >= ?"
                paper_params.append(date_from)
            if date_to:
                paper_where += " AND substr(CAST(mp.created_at AS TEXT),1,10) <= ?"
                paper_params.append(date_to)
        raw_papers = db.execute(f"""
            SELECT mp.id, mp.paper_no, vm.vehicle_no AS vehicle_id, mp.technician_code AS staff_id,
                   mp.total_amount AS amount, mp.work_summary AS description,
                   mp.review_status AS status, mp.notes AS admin_notes,
                   mp.created_at, 'Maintenance' AS category
            FROM maintenance_papers mp
            LEFT JOIN vehicle_master vm ON vm.vehicle_id = mp.vehicle_id
            WHERE mp.technician_code = ?{paper_where}
            ORDER BY mp.created_at DESC
        """, (staff_id, *paper_params)).fetchall()

        items = []
        for j in jobs:
            d = dict(j)
            d["_type"] = "job"
            d["_id"] = f"job_{j['id']}"
            items.append(d)
        for p in raw_papers:
            d = dict(p)
            if isinstance(d.get("created_at"), datetime):
                d["created_at"] = d["created_at"].strftime("%Y-%m-%d %H:%M:%S")
            d["_type"] = "paper"
            d["_id"] = f"paper_{p['id']}"
            items.append(d)
        items.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)

        adv_where = ""
        adv_params = []
        if filter_month:
            adv_where += " AND substr(entry_date,1,7) = ?"
            adv_params.append(filter_month)
        else:
            if date_from:
                adv_where += " AND substr(entry_date,1,10) >= ?"
                adv_params.append(date_from)
            if date_to:
                adv_where += " AND substr(entry_date,1,10) <= ?"
                adv_params.append(date_to)
        advances = db.execute(f"""
            SELECT id, amount, funding_source, reference, notes, entry_date, created_at, staff_code FROM maintenance_staff_advances WHERE staff_code = ?{adv_where} ORDER BY entry_date DESC
        """, (staff_id, *adv_params)).fetchall()

        cash_items = []
        for a in advances:
            d = dict(a)
            d["_type"] = "advance"
            d["_id"] = f"advance_{a['id']}"
            d["_date"] = str(a.get("entry_date", ""))
            d["_amount"] = a["amount"]
            d["_source"] = a.get("funding_source", "Advance")
            d["_notes"] = a.get("notes", "")
            d["_given_by"] = a.get("reference", "")
            cash_items.append(d)
        cash_items.sort(key=lambda x: x["_date"], reverse=True)

        months = db.execute(
            "SELECT DISTINCT substr(entry_date,1,7) AS m FROM maintenance_staff_advances WHERE staff_code = ? ORDER BY m DESC",
            (staff_id,),
        ).fetchall()

        month_name = "All Time"

        return render_template(
            "fleet/fleet_staff_profile.html",
            s=s,
            card_received=card_received,
            card_spent=card_spent,
            card_balance=card_balance,
            month_name=month_name,
            is_filtered=bool(filter_month),
            items=items,
            cash_items=cash_items,
            months=[r["m"] for r in months],
            filter_month=filter_month,
            date_from=date_from,
            date_to=date_to,
            current_month=current_month,
            today=date.today().isoformat(),
            now=datetime.now(),
        )
    except Exception as e:
        tb = traceback.format_exc()
        current_app.logger.error("Profile error for %s:\n%s", staff_id, tb)
        flash(f"Error: {e}", "error")
        return redirect(url_for("fleet.fleet_staff_list"))


@fleet_bp.route("/fleet/staff/<staff_id>/advances/pdf")
def fleet_staff_advances_pdf(staff_id):
    import traceback
    try:
        from app.pdf_service import generate_field_staff_advances_pdf
        _touch_admin_workspace("fleet")
        ensure_fleet_tables()
        db = open_db()
        s = db.execute("SELECT staff_id, full_name, phone, username, password_hash, is_active FROM field_staff WHERE staff_id = ?", (staff_id,)).fetchone()
        if not s:
            flash("Staff not found.", "error")
            return redirect(url_for("fleet.fleet_staff_list"))
        filter_month = request.args.get("month", "")
        date_from = request.args.get("date_from", "")
        date_to = request.args.get("date_to", "")
        date_params = []
        where_adv = ""
        if filter_month:
            where_adv += " AND substr(entry_date,1,7) = ?"
            date_params.append(filter_month[:7])
        else:
            if date_from:
                where_adv += " AND substr(entry_date,1,10) >= ?"
                date_params.append(date_from)
            if date_to:
                where_adv += " AND substr(entry_date,1,10) <= ?"
                date_params.append(date_to)
        if not date_params:
            where_adv = " AND substr(entry_date,1,7) = ?"
            date_params.append(date.today().isoformat()[:7])
        advances = db.execute(f"SELECT id, amount, funding_source, reference, notes, entry_date, created_at, staff_code FROM maintenance_staff_advances WHERE staff_code = ?{where_adv} ORDER BY entry_date DESC", (staff_id, *date_params)).fetchall()
        total = sum(a["amount"] for a in advances) if advances else 0

        # Jobs/papers filter same period
        jp_where = ""
        jp_params = []
        if filter_month:
            jp_where += " AND substr(CAST(mj.created_at AS TEXT),1,7) = ?"
            jp_params.append(filter_month[:7])
        else:
            if date_from:
                jp_where += " AND substr(CAST(mj.created_at AS TEXT),1,10) >= ?"
                jp_params.append(date_from)
            if date_to:
                jp_where += " AND substr(CAST(mj.created_at AS TEXT),1,10) <= ?"
                jp_params.append(date_to)
        if not jp_params:
            jp_where = " AND substr(CAST(mj.created_at AS TEXT),1,7) = ?"
            jp_params.append(date.today().isoformat()[:7])
        jobs_data = db.execute(f"""
            SELECT mj.id, mj.vehicle_id, mj.amount, mj.created_at, v.plate_no
            FROM maintenance_jobs mj
            LEFT JOIN vehicles v ON v.plate_no = mj.vehicle_id
            WHERE mj.staff_id = ? AND mj.status = 'approved'{jp_where}
            ORDER BY mj.created_at DESC
        """, (staff_id, *jp_params)).fetchall()
        pp_where = jp_where.replace("mj.created_at", "mp.created_at")
        papers_data = db.execute(f"""
            SELECT mp.id, vm.vehicle_no AS vehicle_id, mp.total_amount AS amount, mp.created_at
            FROM maintenance_papers mp
            LEFT JOIN vehicle_master vm ON vm.vehicle_id = mp.vehicle_id
            WHERE mp.technician_code = ? AND mp.review_status = 'Approved'{pp_where}
            ORDER BY mp.created_at DESC
        """, (staff_id, *jp_params)).fetchall()

        from pathlib import Path
        from flask import current_app
        output_dir = Path(current_app.config["GENERATED_DIR"]) / "staff_advances"
        import os
        company = db.execute("SELECT company_name, legal_name, trade_license_no, trade_license_expiry, trn_no, vat_status, address, phone_number, email, bank_name, bank_account_name, bank_account_number, iban, swift_code, invoice_terms, base_currency, logo_data, logo_type, theme_color FROM company_profile LIMIT 1").fetchone()
        base_url = request.host_url.rstrip("/")
        pdf_path = generate_field_staff_advances_pdf(s, advances, jobs_data, papers_data, total, filter_month, date_from, date_to, str(output_dir), current_app.config["STATIC_ASSETS_DIR"], company_profile=company, base_url=base_url)
        relative_path = Path(pdf_path).relative_to(current_app.config["GENERATED_DIR"]).as_posix()
        return redirect(url_for("public_file", filename=relative_path))
    except Exception as e:
        tb = traceback.format_exc()
        current_app.logger.error("Profile PDF error for %s:\n%s", staff_id, tb)
        flash(f"PDF Error: {e}", "error")
        return redirect(url_for("fleet.fleet_staff_profile", staff_id=staff_id))


@fleet_bp.route("/fleet/staff/<staff_id>/jobs/pdf")
def fleet_staff_jobs_pdf(staff_id):
    import traceback
    try:
        from app.pdf_service import generate_field_staff_jobs_pdf
        _touch_admin_workspace("fleet")
        ensure_fleet_tables()
        db = open_db()
        s = db.execute("SELECT staff_id, full_name, phone, username, password_hash, is_active FROM field_staff WHERE staff_id = ?", (staff_id,)).fetchone()
        if not s:
            flash("Staff not found.", "error")
            return redirect(url_for("fleet.fleet_staff_list"))
        filter_month = request.args.get("month", "")
        date_from = request.args.get("date_from", "")
        date_to = request.args.get("date_to", "")
        jp_where = ""
        jp_params = []
        if filter_month:
            jp_where += " AND substr(CAST(mj.created_at AS TEXT),1,7) = ?"
            jp_params.append(filter_month[:7])
        else:
            if date_from:
                jp_where += " AND substr(CAST(mj.created_at AS TEXT),1,10) >= ?"
                jp_params.append(date_from)
            if date_to:
                jp_where += " AND substr(CAST(mj.created_at AS TEXT),1,10) <= ?"
                jp_params.append(date_to)
        jobs = db.execute(f"""
            SELECT mj.*, v.vehicle_type FROM maintenance_jobs mj
            LEFT JOIN vehicles v ON v.plate_no = mj.vehicle_id
            WHERE mj.staff_id = ?{jp_where}
            ORDER BY mj.created_at DESC
        """, (staff_id, *jp_params)).fetchall()
        total_amount = sum(j["amount"] for j in jobs) if jobs else 0
        from pathlib import Path
        from flask import current_app
        output_dir = Path(current_app.config["GENERATED_DIR"]) / "staff_jobs"
        company = db.execute("SELECT company_name, legal_name, trade_license_no, trade_license_expiry, trn_no, vat_status, address, phone_number, email, bank_name, bank_account_name, bank_account_number, iban, swift_code, invoice_terms, base_currency, logo_data, logo_type, theme_color FROM company_profile LIMIT 1").fetchone()
        base_url = request.host_url.rstrip("/")
        pdf_path = generate_field_staff_jobs_pdf(s, jobs, total_amount, filter_month, date_from, date_to, str(output_dir), current_app.config["STATIC_ASSETS_DIR"], company_profile=company, base_url=base_url)
        relative_path = Path(pdf_path).relative_to(current_app.config["GENERATED_DIR"]).as_posix()
        return redirect(url_for("public_file", filename=relative_path))
    except Exception as e:
        tb = traceback.format_exc()
        current_app.logger.error("Jobs PDF error for %s:\n%s", staff_id, tb)
        flash(f"PDF Error: {e}", "error")
        return redirect(url_for("fleet.fleet_staff_profile", staff_id=staff_id))


@fleet_bp.route("/fleet/staff/<staff_id>/delete-data", methods=["POST"])
@_login_required("admin")
def fleet_staff_delete_data(staff_id):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    s = db.execute("SELECT staff_id, full_name, phone, username, password_hash, is_active FROM field_staff WHERE staff_id = ?", (staff_id,)).fetchone()
    if not s:
        flash("Staff not found.", "error")
        return redirect(url_for("fleet.fleet_staff_list"))
    types = request.form.getlist("delete_types")
    deleted = []
    if "advances" in types:
        db.execute("DELETE FROM maintenance_staff_advances WHERE staff_code = ?", (staff_id,))
        deleted.append("Advances")
    if "jobs" in types:
        db.execute("DELETE FROM maintenance_jobs WHERE staff_id = ?", (staff_id,))
        deleted.append("Portal Jobs")
    if "papers" in types:
        paper_nos = [r[0] for r in db.execute("SELECT paper_no FROM maintenance_papers WHERE technician_code = ?", (staff_id,)).fetchall()]
        for pn in paper_nos:
            db.execute("DELETE FROM maintenance_paper_lines WHERE paper_no = ?", (pn,))
        db.execute("DELETE FROM maintenance_papers WHERE technician_code = ?", (staff_id,))
        deleted.append("Maintenance Papers")
    db.commit()
    if deleted:
        flash(f"Deleted: {', '.join(deleted)} for {s['full_name']}.", "success")
    else:
        flash("No data type selected.", "error")
    return redirect(url_for("fleet.fleet_staff_profile", staff_id=staff_id))


@fleet_bp.route("/fleet/staff/<staff_id>/delete-items", methods=["POST"])
@_login_required("admin")
def fleet_staff_delete_items(staff_id):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    s = db.execute("SELECT staff_id, full_name, phone, username, password_hash, is_active FROM field_staff WHERE staff_id = ?", (staff_id,)).fetchone()
    if not s:
        flash("Staff not found.", "error")
        return redirect(url_for("fleet.fleet_staff_list"))
    item_ids = request.form.getlist("item_ids")
    deleted = []
    for item in item_ids:
        parts = item.split("_", 1)
        if len(parts) != 2:
            continue
        prefix, record_id = parts
        try:
            record_id = int(record_id)
        except ValueError:
            continue
        if prefix == "job":
            db.execute("DELETE FROM maintenance_jobs WHERE id = ? AND staff_id = ?", (record_id, staff_id))
            deleted.append(f"job #{record_id}")
        elif prefix == "paper":
            row = db.execute("SELECT paper_no FROM maintenance_papers WHERE id = ? AND technician_code = ?", (record_id, staff_id)).fetchone()
            if row:
                db.execute("DELETE FROM maintenance_paper_lines WHERE paper_no = ?", (row[0],))
            db.execute("DELETE FROM maintenance_papers WHERE id = ? AND technician_code = ?", (record_id, staff_id))
            deleted.append(f"paper #{record_id}")
        elif prefix == "advance":
            db.execute("DELETE FROM maintenance_staff_advances WHERE id = ? AND staff_code = ?", (record_id, staff_id))
            deleted.append(f"advance #{record_id}")
    db.commit()
    if deleted:
        flash(f"Deleted {len(deleted)} item(s): {', '.join(deleted[:10])}{'...' if len(deleted) > 10 else ''}", "success")
    else:
        flash("No items selected.", "error")
    return redirect(url_for("fleet.fleet_staff_profile", staff_id=staff_id))


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

    pending_total = float(
        db.execute("SELECT COALESCE(SUM(amount),0) FROM maintenance_jobs WHERE status = 'pending'").fetchone()[0] or 0
    )

    recent_approved = db.execute(
        """SELECT mj.*, COALESCE(v.plate_no, mj.vehicle_id) AS plate_no, s.full_name AS staff_name
           FROM maintenance_jobs mj
           LEFT JOIN vehicles v ON v.plate_no = mj.vehicle_id
           JOIN field_staff s ON s.staff_id = mj.staff_id
           WHERE mj.status IN ('approved','rejected')
           ORDER BY mj.created_at DESC LIMIT 20""",
    ).fetchall()

    return render_template("fleet/fleet_approvals.html", pending_jobs=pending_jobs, pending_total=pending_total, recent_approved=recent_approved)


@fleet_bp.route("/fleet/jobs/approve-all", methods=["POST"])
@_login_required("admin")
def fleet_job_approve_all():
    _touch_admin_workspace("fleet")
    db = open_db()
    pending = db.execute("SELECT id, category, amount, staff_id FROM maintenance_jobs WHERE status='pending'").fetchall()
    if not pending:
        flash("No pending jobs to approve.", "info")
        return redirect(url_for("fleet.fleet_approvals"))
    now = datetime.now().isoformat()
    db.execute("UPDATE maintenance_jobs SET status='approved', approved_at=? WHERE status='pending'", (now,))
    db.commit()
    try:
        from app.notification_service import add_notification
        add_notification(title=f"All {len(pending)} pending jobs approved", type="success", role="admin", link="/fleet/approvals")
        notified = set()
        for j in pending:
            sid = j["staff_id"]
            if sid and sid not in notified:
                notified.add(sid)
                add_notification(title=f"Your job{'s' if len(pending)>1 else ''} approved", type="success", role="technician")
    except:
        pass
    flash(f"All {len(pending)} pending jobs approved.", "success")
    return redirect(url_for("fleet.fleet_approvals"))


@fleet_bp.route("/fleet/jobs/<int:job_id>/approve", methods=["POST"])
@_login_required("admin")
def fleet_job_approve(job_id):
    _touch_admin_workspace("fleet")
    db = open_db()
    job = db.execute("SELECT id, vehicle_id, staff_id, amount, category, description, attachment_name, attachment_data, attachment_type, status, admin_notes, approved_at FROM maintenance_jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        flash("Job not found.", "error")
        return redirect(url_for("fleet.fleet_approvals"))
    db.execute(
        "UPDATE maintenance_jobs SET status = 'approved', approved_at = ? WHERE id = ?",
        (datetime.now().isoformat(), job_id),
    )
    db.commit()
    try:
        from app.notification_service import add_notification
        add_notification(
            title=f"Job #{job_id} approved",
            type="success",
            role="admin",
            message=job.get("category","") + " — AED " + str(job.get("amount","")),
            link="/fleet/approvals",
        )
        try:
            staff_id = job.get("staff_id")
            staff_name = "Technician"
            if staff_id:
                s = db.execute("SELECT full_name FROM field_staff WHERE staff_id=?", (staff_id,)).fetchone()
                if s: staff_name = s[0]
        except:
            staff_name = "Technician"
        add_notification(
            title=f"Job #{job_id} approved by admin",
            type="success",
            role="technician",
            message=job.get("category","") + " — AED " + str(job.get("amount","")),
        )
    except:
        pass
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
    try:
        from app.notification_service import add_notification
        add_notification(
            title=f"Job #{job_id} rejected",
            type="error",
            role="admin",
            message=notes,
            link="/fleet/approvals",
        )
        try:
            job = db.execute("SELECT id, vehicle_id, staff_id, amount, category, description, attachment_name, attachment_data, attachment_type, status, admin_notes, approved_at FROM maintenance_jobs WHERE id = ?", (job_id,)).fetchone()
            staff_id = job.get("staff_id") if job else None
        except:
            staff_id = None
        add_notification(
            title=f"Job #{job_id} rejected by admin",
            type="error",
            role="technician",
            message=notes,
        )
    except:
        pass
    flash(f"Job #{job_id} rejected.", "info")
    return redirect(url_for("fleet.fleet_approvals"))


# ── Serve Attachment ────────────────────────────────────────────

@fleet_bp.route("/fleet/attachment/<int:job_id>")
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
# FUEL MANAGEMENT
# ═════════════════════════════════════════════════════════════════

@fleet_bp.route("/fleet/fuel")
@_login_required("admin")
def fuel_list():
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    vehicle_filter = request.args.get("vehicle", "")
    month_filter = request.args.get("month", "")
    params = []
    where = ""
    if vehicle_filter:
        where += " AND fe.vehicle_plate = ?"
        params.append(vehicle_filter)
    if month_filter:
        where += " AND substr(fe.entry_date,1,7) = ?"
        params.append(month_filter)
    entries = db.execute(f"""
        SELECT fe.* FROM fuel_entries fe
        WHERE 1=1{where}
        ORDER BY fe.entry_date DESC, fe.id DESC
    """, params).fetchall()
    vehicles = db.execute("SELECT plate_no FROM vehicles ORDER BY plate_no").fetchall()
    total_gallons = sum(e["gallons"] for e in entries) if entries else 0
    total_amount = sum(e["total_amount"] for e in entries) if entries else 0
    return render_template(
        "fleet/fuel_list.html",
        entries=entries,
        vehicles=vehicles,
        vehicle_filter=vehicle_filter,
        month_filter=month_filter,
        total_gallons=total_gallons,
        total_amount=total_amount,
    )


@fleet_bp.route("/fleet/fuel/report/pdf")
@_login_required("admin")
def fuel_report_pdf():
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    vehicle_filter = request.args.get("vehicle", "")
    month_filter = request.args.get("month", "")
    params = []
    where = ""
    if vehicle_filter:
        where += " AND fe.vehicle_plate = ?"
        params.append(vehicle_filter)
    if month_filter:
        where += " AND substr(fe.entry_date,1,7) = ?"
        params.append(month_filter)
    entries = db.execute(f"""
        SELECT fe.* FROM fuel_entries fe
        WHERE 1=1{where}
        ORDER BY fe.entry_date DESC, fe.id DESC
    """, params).fetchall()
    output_dir = current_app.config.get("GENERATED_BACKUP_DIR", "/tmp")
    company = db.execute("SELECT company_name, legal_name, trade_license_no, trade_license_expiry, trn_no, vat_status, address, phone_number, email, bank_name, bank_account_name, bank_account_number, iban, swift_code, invoice_terms, base_currency, logo_data, logo_type, theme_color FROM company_profile LIMIT 1").fetchone()
    cp = dict(company) if company else {}
    assets_dir = str(Path(current_app.root_path).parent / "app" / "static")
    pdf_path = generate_fuel_report_pdf(
        entries=entries,
        vehicle_filter=vehicle_filter,
        month_filter=month_filter,
        output_dir=output_dir,
        assets_dir=assets_dir,
        company_profile=cp,
    )
    return send_file(pdf_path, as_attachment=True, download_name=f"fuel_report_{month_filter or 'all'}.pdf")


@fleet_bp.route("/fleet/fuel/add", methods=["GET", "POST"])
@_login_required("admin")
def fuel_add():
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    if request.method == "POST":
        vehicle_plate = request.form.get("vehicle_plate", "").strip()
        entry_date = request.form.get("entry_date", "").strip()
        gallons = float(request.form.get("gallons", 0) or 0)
        rate = float(request.form.get("rate_per_gallon", 0) or 0)
        # Auto-calculate rate from total_amount if provided
        total_amount = request.form.get("total_amount", "").strip()
        if total_amount:
            amt = float(total_amount or 0)
            if rate <= 0 and gallons > 0:
                rate = round(amt / gallons, 3)
        supplier_id = request.form.get("supplier_id", "").strip()
        notes = request.form.get("notes", "").strip()
        if not vehicle_plate or not entry_date or gallons <= 0 or rate <= 0 or not supplier_id:
            flash("Please fill all required fields.", "error")
            return redirect(url_for("fleet.fuel_add"))
        supplier = db.execute("SELECT id, supplier_name FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not supplier:
            flash("Supplier not found.", "error")
            return redirect(url_for("fleet.fuel_add"))
        total = round(gallons * rate, 2)
        fuel_desc = f"{gallons} GLN × {rate} = AED {total} — {vehicle_plate}"
        if db.backend == "postgres":
            fuel_result = db.execute(
                """INSERT INTO fuel_entries (vehicle_plate, entry_date, gallons, rate_per_gallon, total_amount, supplier_id, supplier_name, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
                (vehicle_plate, entry_date, gallons, rate, total, supplier["id"], supplier["supplier_name"], notes),
            )
            fuel_id = fuel_result.fetchone()[0]
            exp_result = db.execute(
                """INSERT INTO supplier_expenses (supplier_id, expense_date, amount, category, description, earning_type, quantity, rate, vehicle_no, status)
                   VALUES (?, ?, ?, 'Fuel', ?, 'Fuel', ?, ?, ?, 'approved') RETURNING id""",
                (supplier["id"], entry_date, total, notes or fuel_desc, gallons, rate, vehicle_plate),
            )
            expense_id = exp_result.fetchone()[0]
        else:
            db.execute(
                """INSERT INTO fuel_entries (vehicle_plate, entry_date, gallons, rate_per_gallon, total_amount, supplier_id, supplier_name, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (vehicle_plate, entry_date, gallons, rate, total, supplier["id"], supplier["supplier_name"], notes),
            )
            fuel_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute(
                """INSERT INTO supplier_expenses (supplier_id, expense_date, amount, category, description, earning_type, quantity, rate, vehicle_no, status)
                   VALUES (?, ?, ?, 'Fuel', ?, 'Fuel', ?, ?, ?, 'approved')""",
                (supplier["id"], entry_date, total, notes or fuel_desc, gallons, rate, vehicle_plate),
            )
            expense_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("UPDATE fuel_entries SET source_expense_id = ? WHERE id = ?", (expense_id, fuel_id))
        db.commit()
        flash(f"Fuel entry added: {gallons} GLN × {rate} = AED {total}", "success")
        return redirect(url_for("fleet.fuel_list"))
    vehicles = db.execute("SELECT plate_no FROM vehicles ORDER BY plate_no").fetchall()
    suppliers = db.execute("SELECT id, supplier_name FROM suppliers WHERE status = 'Active' ORDER BY supplier_name").fetchall()
    return render_template("fleet/fuel_form.html", vehicles=vehicles, suppliers=suppliers, entry=None)


@fleet_bp.route("/fleet/fuel/<int:entry_id>/edit", methods=["GET", "POST"])
@_login_required("admin")
def fuel_edit(entry_id):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    entry = db.execute("SELECT id, vehicle_plate, entry_date, gallons, rate_per_gallon, total_amount, supplier_id, supplier_name, notes, source_expense_id, created_at FROM fuel_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        flash("Fuel entry not found.", "error")
        return redirect(url_for("fleet.fuel_list"))
    if request.method == "POST":
        vehicle_plate = request.form.get("vehicle_plate", "").strip()
        entry_date = request.form.get("entry_date", "").strip()
        gallons = float(request.form.get("gallons", 0) or 0)
        rate = float(request.form.get("rate_per_gallon", 0) or 0)
        # Auto-calculate rate from total_amount if provided
        total_amount = request.form.get("total_amount", "").strip()
        if total_amount:
            amt = float(total_amount or 0)
            if rate <= 0 and gallons > 0:
                rate = round(amt / gallons, 3)
        supplier_id = request.form.get("supplier_id", "").strip()
        notes = request.form.get("notes", "").strip()
        if not vehicle_plate or not entry_date or gallons <= 0 or rate <= 0 or not supplier_id:
            flash("Please fill all required fields.", "error")
            return redirect(url_for("fleet.fuel_edit", entry_id=entry_id))
        supplier = db.execute("SELECT id, supplier_name FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not supplier:
            flash("Supplier not found.", "error")
            return redirect(url_for("fleet.fuel_edit", entry_id=entry_id))
        total = round(gallons * rate, 2)
        db.execute(
            """UPDATE fuel_entries SET vehicle_plate=?, entry_date=?, gallons=?, rate_per_gallon=?, total_amount=?, supplier_id=?, supplier_name=?, notes=?
               WHERE id=?""",
            (vehicle_plate, entry_date, gallons, rate, total, supplier["id"], supplier["supplier_name"], notes, entry_id),
        )
        # Update linked supplier_expenses
        if entry["source_expense_id"]:
            fuel_desc = f"{gallons} GLN × {rate} = AED {total} — {vehicle_plate}"
            db.execute(
                """UPDATE supplier_expenses SET expense_date=?, amount=?, quantity=?, rate=?, vehicle_no=?, description=?, earning_type=?, category=?
                   WHERE id=?""",
                (entry_date, total, gallons, rate, vehicle_plate, notes or fuel_desc, 'Fuel', 'Fuel', entry["source_expense_id"]),
            )
        db.commit()
        flash("Fuel entry updated.", "success")
        return redirect(url_for("fleet.fuel_list"))
    vehicles = db.execute("SELECT plate_no FROM vehicles ORDER BY plate_no").fetchall()
    suppliers = db.execute("SELECT id, supplier_name FROM suppliers WHERE status = 'Active' ORDER BY supplier_name").fetchall()
    return render_template("fleet/fuel_form.html", vehicles=vehicles, suppliers=suppliers, entry=entry)


@fleet_bp.route("/fleet/fuel/<int:entry_id>/delete", methods=["POST"])
@_login_required("admin")
def fuel_delete(entry_id):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    entry = db.execute("SELECT id, vehicle_plate, entry_date, gallons, rate_per_gallon, total_amount, supplier_id, supplier_name, notes, source_expense_id, created_at FROM fuel_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        flash("Fuel entry not found.", "error")
        return redirect(url_for("fleet.fuel_list"))
    if entry["source_expense_id"]:
        db.execute("DELETE FROM supplier_expenses WHERE id = ?", (entry["source_expense_id"],))
    db.execute("DELETE FROM fuel_entries WHERE id = ?", (entry_id,))
    db.commit()
    flash("Fuel entry deleted.", "info")
    return redirect(url_for("fleet.fuel_list"))


@fleet_bp.route("/fleet/fuel/supplier/<int:supplier_id>")
@_login_required("admin")
def fuel_supplier_statement(supplier_id):
    _touch_admin_workspace("fleet")
    ensure_fleet_tables()
    db = open_db()
    supplier = db.execute("SELECT id, supplier_name FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if not supplier:
        flash("Supplier not found.", "error")
        return redirect(url_for("fleet.fuel_list"))
    month_filter = request.args.get("month", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    params = [supplier_id]
    where = ""
    if month_filter:
        where += " AND substr(fe.entry_date,1,7) = ?"
        params.append(month_filter[:7])
    else:
        if date_from:
            where += " AND fe.entry_date >= ?"
            params.append(date_from)
        if date_to:
            where += " AND fe.entry_date <= ?"
            params.append(date_to)
    entries = db.execute(f"""
        SELECT fe.* FROM fuel_entries fe
        WHERE fe.supplier_id = ?{where}
        ORDER BY fe.entry_date DESC, fe.id DESC
    """, params).fetchall()
    total_gallons = sum(e["gallons"] for e in entries) if entries else 0
    total_amount = sum(e["total_amount"] for e in entries) if entries else 0
    return render_template(
        "fleet/fuel_supplier_statement.html",
        supplier=supplier,
        entries=entries,
        month_filter=month_filter,
        date_from=date_from,
        date_to=date_to,
        total_gallons=total_gallons,
        total_amount=total_amount,
    )


@fleet_bp.route("/fleet/fuel/supplier/<int:supplier_id>/pdf")
@_login_required("admin")
def fuel_supplier_statement_pdf(supplier_id):
    flash("PDF coming soon.", "info")
    return redirect(url_for("fleet.fuel_supplier_statement", supplier_id=supplier_id))

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

    vehicles = db.execute("SELECT plate_no, vehicle_type, model, year, ownership_type, partner_name, partner_percent, status, notes FROM vehicles ORDER BY vehicle_type, plate_no").fetchall()

    if request.method == "POST":
        vehicle_id = request.form.get("vehicle_id", "").strip()
        amount = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        status = request.form.get("status", "").strip()

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

        new_status = status if status in ("pending", "approved", "rejected") else job["status"]
        db.execute(
            """UPDATE maintenance_jobs
               SET vehicle_id=?, amount=?, category=?, description=?,
                   attachment_name=?, attachment_data=?, attachment_type=?,
                   status=?
               WHERE id=?""",
            (vehicle_id or "N/A", float(amount), category, description,
             attachment_name, attachment_data, attachment_type, new_status, job_id),
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


@fleet_bp.route("/fleet/jobs/<int:job_id>/revert", methods=["POST"])
@_login_required("admin")
def fleet_job_revert(job_id):
    _touch_admin_workspace("fleet")
    db = open_db()
    db.execute("UPDATE maintenance_jobs SET status='pending' WHERE id=?", (job_id,))
    db.commit()
    flash("Job reverted to pending.", "success")
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
