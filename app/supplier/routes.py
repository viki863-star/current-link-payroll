import os
import base64
from io import BytesIO
from datetime import date, datetime

from flask import (
    redirect,
    render_template,
    request,
    session,
    url_for,
    send_file,
    flash,
    current_app,
)

from . import supplier_bp

MAINTENANCE_CATEGORIES = [
    "Engine", "Transmission", "Brakes", "Tires", "Electrical",
    "AC", "Body", "Fuel System", "Suspension", "Inspection",
    "Oil Change", "Battery", "Lights", "Other",
]

SUPPLIER_TYPES = [
    ("with_invoice", "With Invoice (VAT)"),
    ("without_invoice", "Without Invoice (Cash)"),
]

SUPPLIER_CATEGORIES = [
    "Spare Parts", "Tires", "Lubricants", "Fuel",
    "Services", "Transport", "Stationery", "Food & Beverage",
    "Cleaning", "Safety Equipment", "Tools", "Other",
]

PAYMENT_METHODS = ["Cash", "Bank Transfer", "Cheque", "Card"]


# ── Helpers ──────────────────────────────────────────────

def _get_db():
    import sqlite3

    db_path = current_app.config.get("DATABASE") or "payroll.db"
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    return db


def _ensure_tables():
    db = _get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_code TEXT UNIQUE NOT NULL,
            supplier_name TEXT NOT NULL,
            supplier_type TEXT NOT NULL DEFAULT 'with_invoice',
            contact_person TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            trn TEXT,
            payment_terms TEXT DEFAULT 'Due on receipt',
            category TEXT,
            bank_name TEXT,
            bank_account TEXT,
            iban TEXT,
            status TEXT NOT NULL DEFAULT 'Active',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS supplier_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            invoice_no TEXT NOT NULL,
            invoice_date TEXT NOT NULL,
            due_date TEXT,
            amount REAL NOT NULL,
            vat_percentage REAL DEFAULT 5.0,
            vat_amount REAL DEFAULT 0.0,
            total_amount REAL NOT NULL,
            description TEXT,
            attachment_name TEXT,
            attachment_data TEXT,
            attachment_type TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            payment_date TEXT,
            payment_method TEXT,
            payment_ref TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );

        CREATE TABLE IF NOT EXISTS supplier_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            expense_date TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT,
            description TEXT,
            receipt_name TEXT,
            receipt_data TEXT,
            receipt_type TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            approved_by TEXT,
            approved_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );

        CREATE TABLE IF NOT EXISTS supplier_payment_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            invoice_id INTEGER,
            payment_date TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'Cash',
            reference_no TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
            FOREIGN KEY (invoice_id) REFERENCES supplier_invoices(id)
        );

        CREATE TABLE IF NOT EXISTS supplier_loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            entry_date TEXT NOT NULL,
            loan_type TEXT NOT NULL DEFAULT 'given',
            amount REAL NOT NULL,
            payment_method TEXT DEFAULT 'Cash',
            reference_no TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );
    """)

    db.executescript("""
        CREATE TABLE IF NOT EXISTS supplier_lpos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            lpo_no TEXT NOT NULL,
            lpo_date TEXT NOT NULL,
            amount REAL DEFAULT 0,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );
        CREATE TABLE IF NOT EXISTS supplier_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            doc_type TEXT NOT NULL,
            doc_name TEXT NOT NULL,
            doc_ref TEXT,
            file_data TEXT,
            file_type TEXT,
            expiry_date TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );
    """)

    db.executescript("""
        CREATE TABLE IF NOT EXISTS supplier_quotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            quotation_no TEXT NOT NULL,
            quotation_date TEXT NOT NULL,
            amount REAL DEFAULT 0,
            description TEXT,
            file_data TEXT,
            file_type TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );
    """)

    db.executescript("""
        CREATE TABLE IF NOT EXISTS supplier_quotation_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quotation_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            qty REAL DEFAULT 1,
            basis_type TEXT DEFAULT 'trip',
            shift_type TEXT DEFAULT 'single',
            day_rate REAL DEFAULT 0,
            night_rate REAL DEFAULT 0,
            amount REAL DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (quotation_id) REFERENCES supplier_quotations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS supplier_lpo_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lpo_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            qty REAL DEFAULT 1,
            basis_type TEXT DEFAULT 'trip',
            shift_type TEXT DEFAULT 'single',
            day_rate REAL DEFAULT 0,
            night_rate REAL DEFAULT 0,
            amount REAL DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (lpo_id) REFERENCES supplier_lpos(id) ON DELETE CASCADE
        );
    """)

    for col, dtype in [("lpo_id", "INTEGER")]:
        try:
            db.execute(f"ALTER TABLE supplier_invoices ADD COLUMN {col} {dtype}")
        except Exception:
            pass

    for col, dtype in [("lpo_type", "TEXT DEFAULT 'fixed'"), ("quotation_id", "INTEGER")]:
        try:
            db.execute(f"ALTER TABLE supplier_lpos ADD COLUMN {col} {dtype}")
        except Exception:
            pass

    for col, dtype in [("earning_type", "TEXT DEFAULT 'fixed'"), ("quantity", "REAL"), ("rate", "REAL")]:
        try:
            db.execute(f"ALTER TABLE supplier_expenses ADD COLUMN {col} {dtype}")
        except Exception:
            pass

    for col, dtype in [("deduct_from_balance", "INTEGER DEFAULT 0")]:
        try:
            db.execute(f"ALTER TABLE supplier_loans ADD COLUMN {col} {dtype}")
        except Exception:
            pass

    db.execute("""CREATE TABLE IF NOT EXISTS owner_funds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount REAL NOT NULL,
        fund_date TEXT NOT NULL,
        description TEXT,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    for col, dtype in [("owner_name", "TEXT DEFAULT 'Owner'"), ("transaction_type", "TEXT DEFAULT 'deposit'")]:
        try:
            db.execute(f"ALTER TABLE owner_funds ADD COLUMN {col} {dtype}")
        except Exception:
            pass

    for col, dtype in [("fund_source", "TEXT DEFAULT 'cash_bank'")]:
        try:
            db.execute(f"ALTER TABLE supplier_payment_records ADD COLUMN {col} {dtype}")
        except Exception:
            pass
        try:
            db.execute(f"ALTER TABLE supplier_expenses ADD COLUMN {col} {dtype}")
        except Exception:
            pass
        try:
            db.execute(f"ALTER TABLE supplier_loans ADD COLUMN {col} {dtype}")
        except Exception:
            pass

    db.commit()
    db.close()


# ═══════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/")
def supplier_dashboard():
    _ensure_tables()
    db = _get_db()

    suppliers = db.execute("SELECT * FROM suppliers ORDER BY supplier_name").fetchall()
    total = len(suppliers)
    active = sum(1 for s in suppliers if s["status"] == "Active")
    with_inv = sum(1 for s in suppliers if s["supplier_type"] == "with_invoice")
    without_inv = sum(1 for s in suppliers if s["supplier_type"] == "without_invoice")

    total_outstanding = db.execute(
        "SELECT COALESCE(SUM(total_amount),0) FROM supplier_invoices WHERE status IN ('pending','approved')"
    ).fetchone()[0]

    recent_invoices = db.execute(
        """SELECT si.*, s.supplier_name FROM supplier_invoices si
           JOIN suppliers s ON s.id = si.supplier_id
           ORDER BY si.created_at DESC LIMIT 5"""
    ).fetchall()

    db.close()
    return render_template(
        "supplier/dashboard.html",
        suppliers=suppliers,
        total=total,
        active=active,
        with_inv=with_inv,
        without_inv=without_inv,
        total_outstanding=total_outstanding,
        recent_invoices=recent_invoices,
    )


# ═══════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/list")
def supplier_list():
    _ensure_tables()
    db = _get_db()
    q = request.args.get("q", "").strip()
    typ = request.args.get("type", "")
    sql = "SELECT * FROM suppliers"
    params = []
    conditions = []
    if q:
        conditions.append(
            "(supplier_name LIKE ? OR supplier_code LIKE ? OR phone LIKE ? OR email LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like])
    if typ:
        conditions.append("supplier_type = ?")
        params.append(typ)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY supplier_name"
    suppliers = db.execute(sql, params).fetchall()
    db.close()
    return render_template("supplier/list.html", suppliers=suppliers, q=q, typ=typ)


# ═══════════════════════════════════════════════════════════
# ADD / EDIT SUPPLIER
# ═══════════════════════════════════════════════════════════

def _next_code(db):
    row = db.execute("SELECT MAX(CAST(SUBSTR(supplier_code,4) AS INTEGER)) FROM suppliers").fetchone()[0]
    next_num = (row or 0) + 1
    return f"SUP{next_num:04d}"


@supplier_bp.route("/add", methods=["GET", "POST"])
def supplier_add():
    _ensure_tables()
    db = _get_db()
    code = _next_code(db)

    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in (
            "supplier_name", "supplier_type", "contact_person", "phone", "email",
            "address", "trn", "payment_terms", "category", "bank_name",
            "bank_account", "iban", "notes",
        )}
        if not data["supplier_name"]:
            flash("Supplier name is required.", "error")
            return render_template("supplier/form.html", s=data, code=code, is_edit=False)

        db.execute(
            """INSERT INTO suppliers (supplier_code, supplier_name, supplier_type, contact_person,
               phone, email, address, trn, payment_terms, category, bank_name, bank_account, iban, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (code, data["supplier_name"], data["supplier_type"], data["contact_person"],
             data["phone"], data["email"], data["address"], data["trn"],
             data["payment_terms"], data["category"], data["bank_name"],
             data["bank_account"], data["iban"], data["notes"]),
        )
        db.commit()
        db.close()
        flash(f"Supplier {data['supplier_name']} added.", "success")
        return redirect(url_for("supplier.supplier_list"))

    db.close()
    return render_template("supplier/form.html", s={}, code=code, is_edit=False)


@supplier_bp.route("/<int:sup_id>/edit", methods=["GET", "POST"])
def supplier_edit(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in (
            "supplier_name", "supplier_type", "contact_person", "phone", "email",
            "address", "trn", "payment_terms", "category", "bank_name",
            "bank_account", "iban", "notes", "status",
        )}
        if not data["supplier_name"]:
            flash("Supplier name is required.", "error")
            return render_template("supplier/form.html", s=s, code=s["supplier_code"], is_edit=True)

        db.execute(
            """UPDATE suppliers SET supplier_name=?, supplier_type=?, contact_person=?, phone=?, email=?,
               address=?, trn=?, payment_terms=?, category=?, bank_name=?, bank_account=?, iban=?, notes=?, status=?
               WHERE id=?""",
            (data["supplier_name"], data["supplier_type"], data["contact_person"],
             data["phone"], data["email"], data["address"], data["trn"],
             data["payment_terms"], data["category"], data["bank_name"],
             data["bank_account"], data["iban"], data["notes"], data["status"], sup_id),
        )
        db.commit()
        db.close()
        flash("Supplier updated.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id))

    db.close()
    return render_template("supplier/form.html", s=s, code=s["supplier_code"], is_edit=True)


# ═══════════════════════════════════════════════════════════
# PROFILE (tabs: Overview, Invoices, Expenses, Payments)
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/<int:sup_id>")
def supplier_profile(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    active_tab = request.args.get("tab", "overview")

    invoices = db.execute(
        "SELECT * FROM supplier_invoices WHERE supplier_id = ? ORDER BY invoice_date DESC",
        (sup_id,),
    ).fetchall()

    expenses = db.execute(
        "SELECT * FROM supplier_expenses WHERE supplier_id = ? ORDER BY expense_date DESC",
        (sup_id,),
    ).fetchall()

    payments = db.execute(
        "SELECT * FROM supplier_payment_records WHERE supplier_id = ? ORDER BY payment_date DESC",
        (sup_id,),
    ).fetchall()

    inv_total = db.execute(
        "SELECT COALESCE(SUM(total_amount),0) FROM supplier_invoices WHERE supplier_id = ?",
        (sup_id,),
    ).fetchone()[0]

    paid_total = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM supplier_payment_records WHERE supplier_id = ?",
        (sup_id,),
    ).fetchone()[0]

    expense_total = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM supplier_expenses WHERE supplier_id = ?",
        (sup_id,),
    ).fetchone()[0]

    loans = db.execute(
        "SELECT * FROM supplier_loans WHERE supplier_id = ? ORDER BY entry_date DESC",
        (sup_id,),
    ).fetchall()
    loan_given = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM supplier_loans WHERE supplier_id = ? AND loan_type='given' AND deduct_from_balance=1",
        (sup_id,),
    ).fetchone()[0]
    loan_recovered = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM supplier_loans WHERE supplier_id = ? AND loan_type='recovered' AND deduct_from_balance=1",
        (sup_id,),
    ).fetchone()[0]
    loan_given_sep = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM supplier_loans WHERE supplier_id = ? AND loan_type='given' AND deduct_from_balance=0",
        (sup_id,),
    ).fetchone()[0]
    loan_recovered_sep = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM supplier_loans WHERE supplier_id = ? AND loan_type='recovered' AND deduct_from_balance=0",
        (sup_id,),
    ).fetchone()[0]

    net_balance = round(inv_total + expense_total - paid_total - loan_given + loan_recovered, 2)

    lpos = db.execute(
        "SELECT sl.*, sq.quotation_no, (SELECT COUNT(*) FROM supplier_invoices si WHERE si.lpo_id=sl.id) as inv_count FROM supplier_lpos sl LEFT JOIN supplier_quotations sq ON sl.quotation_id=sq.id WHERE sl.supplier_id = ? ORDER BY sl.lpo_date DESC",
        (sup_id,),
    ).fetchall()

    docs = db.execute(
        "SELECT * FROM supplier_documents WHERE supplier_id = ? ORDER BY created_at DESC",
        (sup_id,),
    ).fetchall()

    quotations = db.execute(
        "SELECT * FROM supplier_quotations WHERE supplier_id = ? ORDER BY quotation_date DESC",
        (sup_id,),
    ).fetchall()

    db.close()
    return render_template(
        "supplier/profile.html",
        s=s,
        active_tab=active_tab,
        invoices=invoices,
        expenses=expenses,
        payments=payments,
        loans=loans,
        lpos=lpos,
        docs=docs,
        quotations=quotations,
        lpo_types=LPO_TYPES,
        inv_total=inv_total,
        paid_total=paid_total,
        expense_total=expense_total,
        loan_given=loan_given,
        loan_recovered=loan_recovered,
        loan_given_sep=loan_given_sep,
        loan_recovered_sep=loan_recovered_sep,
        net_balance=net_balance,
        today=date.today().isoformat(),
    )


# ═══════════════════════════════════════════════════════════
# INVOICES
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/<int:sup_id>/invoices/add", methods=["GET", "POST"])
def supplier_invoice_add(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    if request.method == "POST":
        invoice_no = request.form.get("invoice_no", "").strip()
        invoice_date = request.form.get("invoice_date", "").strip()
        due_date = request.form.get("due_date", "").strip()
        amount = request.form.get("amount", "").strip()
        vat_pct = request.form.get("vat_percentage", "5").strip()
        lpo_id = request.form.get("lpo_id", "").strip()
        description = request.form.get("description", "").strip()
        notes = request.form.get("notes", "").strip()

        if not invoice_no or not invoice_date or not amount:
            flash("Invoice number, date, and amount are required.", "error")
            return render_template("supplier/invoice_form.html", s=s, inv={}, lpos=[], categories=SUPPLIER_CATEGORIES)

        amount_f = float(amount)
        vat_pct_f = float(vat_pct)
        vat_amt = round(amount_f * vat_pct_f / 100, 2)
        total = round(amount_f + vat_amt, 2)

        attachment_name = None
        attachment_data = None
        attachment_type = None
        if "attachment" in request.files:
            file = request.files["attachment"]
            if file.filename:
                attachment_name = file.filename
                attachment_data = base64.b64encode(file.read()).decode("utf-8")
                attachment_type = file.content_type

        db.execute(
            """INSERT INTO supplier_invoices (supplier_id, invoice_no, invoice_date, due_date,
               amount, vat_percentage, vat_amount, total_amount, description,
               attachment_name, attachment_data, attachment_type, notes, lpo_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sup_id, invoice_no, invoice_date, due_date or None,
             amount_f, vat_pct_f, vat_amt, total, description,
             attachment_name, attachment_data, attachment_type, notes,
             int(lpo_id) if lpo_id and lpo_id != "none" else None),
        )
        db.commit()
        db.close()
        flash("Invoice added.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="invoices"))

    db.close()
    lpos = _get_db().execute("SELECT * FROM supplier_lpos WHERE supplier_id=? AND status='open' ORDER BY lpo_date DESC", (sup_id,)).fetchall()
    return render_template("supplier/invoice_form.html", s=s, inv={}, lpos=lpos, categories=SUPPLIER_CATEGORIES)


@supplier_bp.route("/<int:sup_id>/invoices/<int:inv_id>/edit", methods=["GET", "POST"])
def supplier_invoice_edit(sup_id, inv_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    inv = db.execute("SELECT * FROM supplier_invoices WHERE id = ? AND supplier_id = ?", (inv_id, sup_id)).fetchone()
    if not s or not inv:
        flash("Invoice not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    if request.method == "POST":
        invoice_no = request.form.get("invoice_no", "").strip()
        invoice_date = request.form.get("invoice_date", "").strip()
        due_date = request.form.get("due_date", "").strip()
        amount = request.form.get("amount", "").strip()
        vat_pct = request.form.get("vat_percentage", "5").strip()
        lpo_id = request.form.get("lpo_id", "").strip()
        description = request.form.get("description", "").strip()
        status = request.form.get("status", "pending").strip()
        payment_date = request.form.get("payment_date", "").strip()
        payment_method = request.form.get("payment_method", "").strip()
        payment_ref = request.form.get("payment_ref", "").strip()
        notes = request.form.get("notes", "").strip()

        amount_f = float(amount)
        vat_pct_f = float(vat_pct)
        vat_amt = round(amount_f * vat_pct_f / 100, 2)
        total = round(amount_f + vat_amt, 2)

        attachment_name = inv["attachment_name"]
        attachment_data = inv["attachment_data"]
        attachment_type = inv["attachment_type"]
        if "attachment" in request.files:
            file = request.files["attachment"]
            if file.filename:
                attachment_name = file.filename
                attachment_data = base64.b64encode(file.read()).decode("utf-8")
                attachment_type = file.content_type

        db.execute(
            """UPDATE supplier_invoices SET invoice_no=?, invoice_date=?, due_date=?,
               amount=?, vat_percentage=?, vat_amount=?, total_amount=?, description=?,
               attachment_name=?, attachment_data=?, attachment_type=?, status=?,
               payment_date=?, payment_method=?, payment_ref=?, notes=?, lpo_id=?
               WHERE id=?""",
            (invoice_no, invoice_date, due_date or None,
             amount_f, vat_pct_f, vat_amt, total, description,
             attachment_name, attachment_data, attachment_type, status,
             payment_date or None, payment_method, payment_ref, notes,
             int(lpo_id) if lpo_id and lpo_id != "none" else None, inv_id),
        )
        db.commit()
        db.close()
        flash("Invoice updated.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="invoices"))

    db.close()
    lpos = _get_db().execute("SELECT * FROM supplier_lpos WHERE supplier_id=? ORDER BY lpo_date DESC", (sup_id,)).fetchall()
    return render_template("supplier/invoice_form.html", s=s, inv=inv, lpos=lpos, categories=SUPPLIER_CATEGORIES)


@supplier_bp.route("/invoices/<int:inv_id>/attachment")
def supplier_invoice_attachment(inv_id):
    db = _get_db()
    inv = db.execute("SELECT * FROM supplier_invoices WHERE id = ?", (inv_id,)).fetchone()
    db.close()
    if not inv or not inv["attachment_data"]:
        flash("Attachment not found.", "error")
        return redirect(url_for("supplier.supplier_dashboard"))
    data = base64.b64decode(inv["attachment_data"])
    return send_file(
        BytesIO(data),
        mimetype=inv["attachment_type"] or "application/octet-stream",
        as_attachment=False,
        download_name=inv["attachment_name"] or f"invoice_{inv_id}",
    )


# ═══════════════════════════════════════════════════════════
# LPO (Local Purchase Order)
# ═══════════════════════════════════════════════════════════

LPO_TYPES = [
    ("trip", "Trip Basis"),
    ("hour", "Hour Basis"),
    ("monthly", "Monthly"),
    ("fixed", "Fixed Amount"),
    ("other", "Other"),
]


@supplier_bp.route("/<int:sup_id>/lpos")
def supplier_lpo_list(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        db.close()
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))
    lpos = db.execute(
        "SELECT sl.*, sq.quotation_no FROM supplier_lpos sl LEFT JOIN supplier_quotations sq ON sl.quotation_id=sq.id WHERE sl.supplier_id = ? ORDER BY sl.lpo_date DESC",
        (sup_id,),
    ).fetchall()
    db.close()
    return render_template("supplier/lpo_list.html", s=s, lpos=lpos)


@supplier_bp.route("/<int:sup_id>/lpos/add", methods=["GET", "POST"])
def supplier_lpo_add(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        db.close()
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    if request.method == "POST":
        lpo_no = request.form.get("lpo_no", "").strip()
        lpo_date = request.form.get("lpo_date", "").strip()
        lpo_type = request.form.get("lpo_type", "fixed").strip()
        quotation_id = request.form.get("quotation_id", "").strip()
        description = request.form.get("description", "").strip()
        notes = request.form.get("notes", "").strip()
        if not lpo_no or not lpo_date:
            flash("LPO number and date are required.", "error")
            return render_template("supplier/lpo_form.html", s=s, lpo={}, lpo_types=LPO_TYPES, quotations=[], qitems=[])
        qid = int(quotation_id) if quotation_id and quotation_id != "none" else None

        cur = db.execute(
            "INSERT INTO supplier_lpos (supplier_id, lpo_no, lpo_date, lpo_type, quotation_id, amount, description, notes) VALUES (?,?,?,?,?,?,?,?)",
            (sup_id, lpo_no, lpo_date, lpo_type, qid, 0, description, notes),
        )
        lpo_id = cur.lastrowid

        total_amount = 0
        descriptions = request.form.getlist("item_desc[]")
        qtys = request.form.getlist("item_qty[]")
        basis_types = request.form.getlist("item_basis[]")
        rates = request.form.getlist("item_rate[]")

        for i in range(len(descriptions)):
            desc = descriptions[i].strip()
            if not desc:
                continue
            qty = float(qtys[i]) if qtys[i] else 1
            basis = basis_types[i] if i < len(basis_types) else "trip"
            rate = float(rates[i]) if i < len(rates) and rates[i] else 0
            amt = round(qty * rate, 2)
            total_amount += amt
            db.execute(
                "INSERT INTO supplier_lpo_items (lpo_id, description, qty, basis_type, day_rate, amount, sort_order) VALUES (?,?,?,?,?,?,?)",
                (lpo_id, desc, qty, basis, rate, amt, i),
            )

        db.execute("UPDATE supplier_lpos SET amount=? WHERE id=?", (round(total_amount, 2), lpo_id))
        db.commit()
        db.close()
        flash("LPO added.", "success")
        return redirect(url_for("supplier.supplier_lpo_list", sup_id=sup_id))

    quotations = db.execute("SELECT * FROM supplier_quotations WHERE supplier_id=? ORDER BY quotation_date DESC", (sup_id,)).fetchall()
    db.close()
    return render_template("supplier/lpo_form.html", s=s, lpo={}, lpo_types=LPO_TYPES, quotations=quotations, qitems=[])


@supplier_bp.route("/<int:sup_id>/lpos/<int:lpo_id>/close", methods=["POST"])
def supplier_lpo_close(sup_id, lpo_id):
    _ensure_tables()
    db = _get_db()
    db.execute("UPDATE supplier_lpos SET status='closed' WHERE id=? AND supplier_id=?", (lpo_id, sup_id))
    db.commit()
    db.close()
    flash("LPO closed.", "info")
    return redirect(url_for("supplier.supplier_lpo_list", sup_id=sup_id))


@supplier_bp.route("/<int:sup_id>/lpos/<int:lpo_id>/pdf")
def supplier_lpo_pdf(sup_id, lpo_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm, cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from io import BytesIO

    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    lpo = db.execute("SELECT * FROM supplier_lpos WHERE id=? AND supplier_id=?", (lpo_id, sup_id)).fetchone()
    items = db.execute("SELECT * FROM supplier_lpo_items WHERE lpo_id=? ORDER BY sort_order", (lpo_id,)).fetchall()
    quotation = None
    if lpo and lpo["quotation_id"]:
        quotation = db.execute("SELECT * FROM supplier_quotations WHERE id=?", (lpo["quotation_id"],)).fetchone()
    db.close()

    if not s or not lpo:
        flash("LPO not found.", "error")
        return redirect(url_for("supplier.supplier_lpo_list", sup_id=sup_id))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()

    # Styles
    s_title = ParagraphStyle("Title", fontSize=18, fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=2, textColor=colors.HexColor("#1a3a5c"))
    s_subtitle = ParagraphStyle("Sub", fontSize=8, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)
    s_label = ParagraphStyle("Lbl", fontSize=8, textColor=colors.HexColor("#555"), spaceAfter=1)
    s_field = ParagraphStyle("Fld", fontSize=9.5, fontName="Helvetica-Bold", spaceAfter=3)
    s_sec = ParagraphStyle("Sec", fontSize=11, fontName="Helvetica-Bold", spaceAfter=6, spaceBefore=10, textColor=colors.HexColor("#1a3a5c"))
    s_cell = ParagraphStyle("Cell", fontSize=8.5, spaceAfter=0)
    s_cell_bold = ParagraphStyle("CellB", fontSize=8.5, fontName="Helvetica-Bold", spaceAfter=0, alignment=TA_CENTER)
    s_total = ParagraphStyle("Tot", fontSize=12, fontName="Helvetica-Bold", spaceAfter=2, alignment=TA_RIGHT)
    s_sign = ParagraphStyle("Sign", fontSize=8.5, alignment=TA_CENTER, spaceBefore=4)
    s_footer = ParagraphStyle("Foot", fontSize=7, textColor=colors.grey, alignment=TA_CENTER)

    type_labels = dict(LPO_TYPES)
    lpo_type_str = type_labels.get(lpo["lpo_type"], lpo["lpo_type"] or "Fixed Amount")

    basis_labels = {"trip": "Trip", "hour": "Hour", "monthly": "Monthly", "fixed": "Fixed", "other": "Other"}

    elements = []

    # ═══ HEADER ═══
    hdr_data = [[
        Paragraph("AL SAQR TRANSPORT<br/><font size=7>P.O. Box XXXXX, Dubai, UAE<br/>TRN: XXXXXXXXXX</font>",
            ParagraphStyle("Co", fontSize=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#1a3a5c"))),
        Paragraph("LOCAL PURCHASE ORDER<br/><font size=10>LPO #: <b>{}</b></font>".format(lpo['lpo_no']),
            ParagraphStyle("LpoHdr", fontSize=14, fontName="Helvetica-Bold", alignment=TA_RIGHT, textColor=colors.HexColor("#1a3a5c"))),
    ]]
    hdr_table = Table(hdr_data, colWidths=[230, 140])
    hdr_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#1a3a5c")),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(hdr_table)
    elements.append(Spacer(1, 3*mm))

    # ═══ INFO ROW ═══
    info_data = [
        [Paragraph("LPO Date", s_label), Paragraph(lpo['lpo_date'], s_field),
         Paragraph("Basis", s_label), Paragraph(lpo_type_str, s_field),
         Paragraph("Status", s_label), Paragraph(f"<b>{lpo['status'].upper()}</b>", s_field)],
    ]
    info_tbl = Table(info_data, colWidths=[45, 95, 40, 85, 40, 65])
    info_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#ccc")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ddd")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8f9fa")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(info_tbl)
    elements.append(Spacer(1, 4*mm))

    # ═══ SUPPLIER ═══
    elements.append(Paragraph("SUPPLIER INFORMATION", s_sec))
    sup_data = [
        [Paragraph("Supplier Name", s_label), Paragraph(f"<b>{s['supplier_name']}</b>", s_field), Paragraph("TRN", s_label), Paragraph(f"{s['trn'] or '—'}", s_field)],
        [Paragraph("Contact", s_label), Paragraph(f"{s['contact_person'] or s['phone'] or '—'}", s_field), Paragraph("Phone", s_label), Paragraph(f"{s['phone'] or '—'}", s_field)],
        [Paragraph("Address", s_label), Paragraph(f"{s['address'] or '—'}", s_field), Paragraph("", s_label), Paragraph("", s_field)],
    ]
    sup_tbl = Table(sup_data, colWidths=[60, 140, 40, 130])
    sup_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    elements.append(sup_tbl)
    elements.append(Spacer(1, 4*mm))

    # ═══ ITEMS TABLE ═══
    elements.append(Paragraph("SERVICE / WORK DETAILS", s_sec))

    item_hdr = [
        Paragraph("<b>#</b>", s_cell_bold),
        Paragraph("<b>Description</b>", ParagraphStyle("CH", fontSize=8.5, fontName="Helvetica-Bold", spaceAfter=0)),
        Paragraph("<b>QTY</b>", s_cell_bold),
        Paragraph("<b>Basis</b>", s_cell_bold),
        Paragraph("<b>Rate (AED)</b>", s_cell_bold),
        Paragraph("<b>Amount</b>", s_cell_bold),
    ]
    item_rows = [item_hdr]
    for idx, it in enumerate(items):
        basis_txt = basis_labels.get(it["basis_type"], it["basis_type"])
        rate = it["day_rate"] or 0
        amt = it["amount"] or 0
        item_rows.append([
            Paragraph(str(idx+1), s_cell_bold),
            Paragraph(it["description"], s_cell),
            Paragraph(f"{it['qty']:,.0f}", s_cell_bold),
            Paragraph(basis_txt, s_cell),
            Paragraph(f"{rate:,.2f}", ParagraphStyle("CR", fontSize=8.5, spaceAfter=0, alignment=TA_RIGHT)),
            Paragraph(f"{amt:,.2f}", ParagraphStyle("CR3", fontSize=8.5, fontName="Helvetica-Bold", spaceAfter=0, alignment=TA_RIGHT)),
        ])

    # Totals row
    total_amt = lpo["amount"] or 0
    item_rows.append([
        Paragraph("", s_cell),
        Paragraph("<b>TOTAL</b>", ParagraphStyle("TotL", fontSize=9, fontName="Helvetica-Bold", spaceAfter=0, alignment=TA_RIGHT)),
        Paragraph("", s_cell),
        Paragraph("", s_cell),
        Paragraph("", s_cell),
        Paragraph(f"<b>{total_amt:,.2f}</b>", ParagraphStyle("TotR", fontSize=10, fontName="Helvetica-Bold", spaceAfter=0, alignment=TA_RIGHT, textColor=colors.HexColor("#1a3a5c"))),
    ])

    col_w = [14, 160, 40, 55, 65, 70]
    items_tbl = Table(item_rows, colWidths=col_w, repeatRows=1)
    items_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#ccc")),
        ("INNERGRID", (0, 0), (-1, -2), 0.3, colors.HexColor("#eee")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f0f4f8")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#fafafa")]),
    ]))
    elements.append(items_tbl)

    if lpo["description"]:
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph(f"<b>Notes:</b> {lpo['description']}", ParagraphStyle("Notes", fontSize=8.5, textColor=colors.HexColor("#555"), spaceAfter=2)))

    if quotation:
        elements.append(Paragraph(f"<i>Based on Quotation: {quotation['quotation_no']} dated {quotation['quotation_date']}</i>",
            ParagraphStyle("QRef", fontSize=8, textColor=colors.grey, spaceAfter=4)))

    elements.append(Spacer(1, 6*mm))

    # ═══ AMOUNT IN WORDS ═══
    def num_to_words(n):
        if n == 0: return "Zero"
        ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
                "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
                "Seventeen", "Eighteen", "Nineteen"]
        tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
        def convert(num):
            if num < 20: return ones[num]
            if num < 100: return tens[num//10] + (" " + ones[num%10] if num%10 else "")
            if num < 1000: return ones[num//100] + " Hundred" + (" " + convert(num%100) if num%100 else "")
            return ""
        int_part = int(n)
        dec_part = round((n - int_part) * 100)
        words = convert(int_part)
        if dec_part:
            words += f" and {dec_part}/100"
        return "AED " + words + " Only"

    elements.append(Paragraph(f"<b>Amount in Words:</b> {num_to_words(total_amt)}",
        ParagraphStyle("Words", fontSize=9, textColor=colors.HexColor("#555"), spaceAfter=6, spaceBefore=4)))

    # ═══ TERMS ═══
    elements.append(Paragraph("TERMS & CONDITIONS", s_sec))
    terms = [
        "Payment as per agreed payment terms.",
        "VAT @ 5% will be charged separately as per UAE Federal Law.",
        "This LPO is valid for 30 days from the date of issue.",
        "Services/goods must be delivered as per the specifications mentioned above.",
        "Any changes or amendments to this LPO require written confirmation.",
        "Delivery location: As per agreement.",
    ]
    for t in terms:
        elements.append(Paragraph(f"&bull; {t}", ParagraphStyle("Terms", fontSize=8.5, leftIndent=12, spaceAfter=1.5, textColor=colors.HexColor("#444"))))
    elements.append(Spacer(1, 8*mm))

    # ═══ SIGNATURES ═══
    sign_data = [[
        Paragraph("_________________________<br/><b>Company Sign &amp; Stamp</b><br/>Date: _____/_____/_____", s_sign),
        Paragraph("", s_sign),
        Paragraph("_________________________<br/><b>Supplier Sign &amp; Stamp</b><br/>Date: _____/_____/_____", s_sign),
    ]]
    sign_tbl = Table(sign_data, colWidths=[170, 30, 170])
    sign_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (0, 0), 0.5, colors.HexColor("#999")),
        ("LINEABOVE", (2, 0), (2, 0), 0.5, colors.HexColor("#999")),
    ]))
    elements.append(sign_tbl)

    # ═══ FOOTER ═══
    elements.append(Spacer(1, 8*mm))
    elements.append(Paragraph("This is a computer-generated document. No signature required for electronic transmission.", s_footer))
    elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%d-%b-%Y %H:%M')}", ParagraphStyle("Gen", fontSize=6.5, textColor=colors.HexColor("#aaa"), alignment=TA_CENTER, spaceAfter=0)))

    doc.build(elements)
    pdf_data = buf.getvalue()
    buf.close()

    return send_file(
        BytesIO(pdf_data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"LPO_{lpo['lpo_no']}.pdf",
    )


# ═══════════════════════════════════════════════════════════
# QUOTATIONS
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/<int:sup_id>/quotations")
def supplier_quotation_list(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        db.close()
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))
    quotations = db.execute(
        "SELECT * FROM supplier_quotations WHERE supplier_id = ? ORDER BY quotation_date DESC",
        (sup_id,),
    ).fetchall()
    db.close()
    return render_template("supplier/quotation_list.html", s=s, quotations=quotations)


@supplier_bp.route("/<int:sup_id>/quotations/add", methods=["GET", "POST"])
def supplier_quotation_add(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        db.close()
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    if request.method == "POST":
        q_no = request.form.get("quotation_no", "").strip()
        q_date = request.form.get("quotation_date", "").strip()
        description = request.form.get("description", "").strip()
        notes = request.form.get("notes", "").strip()
        if not q_no or not q_date:
            flash("Quotation number and date are required.", "error")
            return render_template("supplier/quotation_form.html", s=s, quotation={})

        file_data = None
        file_type = None
        if "file" in request.files:
            f = request.files["file"]
            if f.filename:
                file_data = base64.b64encode(f.read()).decode("utf-8")
                file_type = f.content_type

        total_amount = 0
        descriptions = request.form.getlist("item_desc[]")
        qtys = request.form.getlist("item_qty[]")
        basis_types = request.form.getlist("item_basis[]")
        rates = request.form.getlist("item_rate[]")

        cur = db.execute(
            "INSERT INTO supplier_quotations (supplier_id, quotation_no, quotation_date, amount, description, file_data, file_type, notes) VALUES (?,?,?,?,?,?,?,?)",
            (sup_id, q_no, q_date, 0, description, file_data, file_type, notes),
        )
        q_id = cur.lastrowid

        for i in range(len(descriptions)):
            desc = descriptions[i].strip()
            if not desc:
                continue
            qty = float(qtys[i]) if qtys[i] else 1
            basis = basis_types[i] if i < len(basis_types) else "trip"
            rate = float(rates[i]) if i < len(rates) and rates[i] else 0
            amt = round(qty * rate, 2)
            total_amount += amt
            db.execute(
                "INSERT INTO supplier_quotation_items (quotation_id, description, qty, basis_type, day_rate, amount, sort_order) VALUES (?,?,?,?,?,?,?)",
                (q_id, desc, qty, basis, rate, amt, i),
            )

        db.execute("UPDATE supplier_quotations SET amount=? WHERE id=?", (total_amount, q_id))
        db.commit()
        db.close()
        flash("Quotation added.", "success")
        return redirect(url_for("supplier.supplier_quotation_list", sup_id=sup_id))

    db.close()
    return render_template("supplier/quotation_form.html", s=s, quotation={})


@supplier_bp.route("/<int:sup_id>/quotations/<int:q_id>/items")
def supplier_quotation_items_api(sup_id, q_id):
    _ensure_tables()
    db = _get_db()
    items = db.execute("SELECT * FROM supplier_quotation_items WHERE quotation_id=? ORDER BY sort_order", (q_id,)).fetchall()
    db.close()
    from flask import jsonify
    return jsonify([dict(i) for i in items])


@supplier_bp.route("/<int:sup_id>/quotations/<int:q_id>/download")
def supplier_quotation_download(sup_id, q_id):
    _ensure_tables()
    db = _get_db()
    q = db.execute("SELECT * FROM supplier_quotations WHERE id=? AND supplier_id=?", (q_id, sup_id)).fetchone()
    db.close()
    if not q or not q["file_data"]:
        flash("Quotation file not found.", "error")
        return redirect(url_for("supplier.supplier_quotation_list", sup_id=sup_id))
    data = base64.b64decode(q["file_data"])
    return send_file(
        BytesIO(data),
        mimetype=q["file_type"] or "application/octet-stream",
        as_attachment=True,
        download_name=f"Quotation_{q['quotation_no']}.pdf",
    )


@supplier_bp.route("/<int:sup_id>/quotations/<int:q_id>/delete", methods=["POST"])
def supplier_quotation_delete(sup_id, q_id):
    _ensure_tables()
    db = _get_db()
    db.execute("DELETE FROM supplier_quotations WHERE id=? AND supplier_id=?", (q_id, sup_id))
    db.commit()
    db.close()
    flash("Quotation deleted.", "info")
    return redirect(url_for("supplier.supplier_quotation_list", sup_id=sup_id))


# ═══════════════════════════════════════════════════════════
# EXPENSES (for suppliers without invoice)
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/<int:sup_id>/expenses/add", methods=["GET", "POST"])
def supplier_expense_add(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    if request.method == "POST":
        expense_date = request.form.get("expense_date", "").strip() or date.today().isoformat()
        earning_type = request.form.get("earning_type", "fixed").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()

        qty = request.form.get("quantity", "").strip()
        rate = request.form.get("rate", "").strip()

        if earning_type == "trip":
            if not qty or not rate:
                flash("Trip count and rate are required.", "error")
                return render_template("supplier/expense_form.html", s=s, exp={})
            qty_f = float(qty)
            rate_f = float(rate)
            amount = round(qty_f * rate_f, 2)
        elif earning_type == "hour":
            if not qty or not rate:
                flash("Hours and rate are required.", "error")
                return render_template("supplier/expense_form.html", s=s, exp={})
            qty_f = float(qty)
            rate_f = float(rate)
            amount = round(qty_f * rate_f, 2)
        else:
            amount = request.form.get("amount", "").strip()
            qty_f = None
            rate_f = None
            if not amount:
                flash("Amount is required.", "error")
                return render_template("supplier/expense_form.html", s=s, exp={})
            amount = float(amount)

        if not category:
            flash("Category is required.", "error")
            return render_template("supplier/expense_form.html", s=s, exp={})

        receipt_name = None
        receipt_data = None
        receipt_type = None
        if "receipt" in request.files:
            file = request.files["receipt"]
            if file.filename:
                receipt_name = file.filename
                receipt_data = base64.b64encode(file.read()).decode("utf-8")
                receipt_type = file.content_type

        fund_source = request.form.get("fund_source", "cash_bank").strip()
        db.execute(
            """INSERT INTO supplier_expenses (supplier_id, expense_date, amount, category, description,
               receipt_name, receipt_data, receipt_type, earning_type, quantity, rate, fund_source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sup_id, expense_date, amount, category, description,
             receipt_name, receipt_data, receipt_type, earning_type, qty_f, rate_f, fund_source),
        )
        db.commit()
        db.close()
        flash("Expense added.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="expenses"))

    db.close()
    return render_template("supplier/expense_form.html", s=s, exp={})


@supplier_bp.route("/<int:sup_id>/expenses/<int:exp_id>/approve", methods=["POST"])
def supplier_expense_approve(sup_id, exp_id):
    _ensure_tables()
    db = _get_db()
    db.execute("UPDATE supplier_expenses SET status='approved' WHERE id=? AND supplier_id=?", (exp_id, sup_id))
    db.commit()
    db.close()
    flash("Expense approved.", "success")
    return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="expenses"))


# ═══════════════════════════════════════════════════════════
# PAYMENTS
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/<int:sup_id>/payments/add", methods=["GET", "POST"])
def supplier_payment_add(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    unpaid = db.execute(
        "SELECT id, invoice_no, total_amount FROM supplier_invoices WHERE supplier_id = ? AND status IN ('pending','approved') ORDER BY invoice_date",
        (sup_id,),
    ).fetchall()

    qarz_given = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM supplier_loans WHERE supplier_id = ? AND loan_type='given' AND deduct_from_balance=1",
        (sup_id,),
    ).fetchone()[0]
    qarz_recovered = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM supplier_loans WHERE supplier_id = ? AND loan_type='recovered' AND deduct_from_balance=1",
        (sup_id,),
    ).fetchone()[0]
    qarz_balance = round(qarz_given - qarz_recovered, 2)

    if request.method == "POST":
        payment_date = request.form.get("payment_date", "").strip() or date.today().isoformat()
        amount = request.form.get("amount", "").strip()
        invoice_id = request.form.get("invoice_id", "").strip()
        payment_method = request.form.get("payment_method", "Cash").strip()
        reference_no = request.form.get("reference_no", "").strip()
        notes = request.form.get("notes", "").strip()
        deduct_qarz = request.form.get("deduct_qarz")

        if not amount:
            flash("Payment amount is required.", "error")
            return render_template("supplier/payment_form.html", s=s, pay={}, invoices=unpaid, methods=PAYMENT_METHODS, qarz_balance=qarz_balance)

        amount_f = float(amount)
        inv_id_val = int(invoice_id) if invoice_id.isdigit() else None

        # If deducting qarz from this payment
        deduct_amt = 0
        if deduct_qarz and qarz_balance > 0:
            deduct_amt = min(qarz_balance, amount_f)
            db.execute(
                "INSERT INTO supplier_loans (supplier_id, entry_date, loan_type, amount, payment_method, reference_no, notes, deduct_from_balance) VALUES (?,?,?,?,?,?,?,?)",
                (sup_id, payment_date, "recovered", deduct_amt, payment_method, reference_no, f"Deducted from payment of {amount}", 1),
            )

        fund_source = request.form.get("fund_source", "cash_bank").strip()

        db.execute(
            "INSERT INTO supplier_payment_records (supplier_id, invoice_id, payment_date, amount, payment_method, reference_no, notes, fund_source) VALUES (?,?,?,?,?,?,?,?)",
            (sup_id, inv_id_val, payment_date, amount_f, payment_method, reference_no, notes, fund_source),
        )

        if inv_id_val:
            db.execute(
                "UPDATE supplier_invoices SET status='paid', payment_date=?, payment_method=?, payment_ref=? WHERE id=?",
                (payment_date, payment_method, reference_no, inv_id_val),
            )

        db.commit()
        db.close()
        flash("Payment recorded." + (f" Qarz {deduct_amt} deducted." if deduct_amt else ""), "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="payments"))

    db.close()
    return render_template("supplier/payment_form.html", s=s, pay={}, invoices=unpaid, methods=PAYMENT_METHODS, qarz_balance=qarz_balance)


# ═══════════════════════════════════════════════════════════
# LOANS / QARZ
# ═══════════════════════════════════════════════════════════

def _next_loan_ref(db):
    row = db.execute("SELECT COUNT(*) FROM supplier_loans").fetchone()[0]
    return f"LOAN{row + 1:04d}"


@supplier_bp.route("/<int:sup_id>/loans/add", methods=["GET", "POST"])
def supplier_loan_add(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    if request.method == "POST":
        entry_date = request.form.get("entry_date", "").strip() or date.today().isoformat()
        loan_type = request.form.get("loan_type", "given").strip()
        amount = request.form.get("amount", "").strip()
        payment_method = request.form.get("payment_method", "Cash").strip()
        reference_no = request.form.get("reference_no", "").strip()
        notes = request.form.get("notes", "").strip()
        deduct = 1 if request.form.get("deduct_from_balance") else 0

        if not amount:
            flash("Amount is required.", "error")
            return render_template("supplier/loan_form.html", s=s, loan={}, methods=PAYMENT_METHODS)

        fund_source = request.form.get("fund_source", "cash_bank").strip()
        db.execute(
            "INSERT INTO supplier_loans (supplier_id, entry_date, loan_type, amount, payment_method, reference_no, notes, deduct_from_balance, fund_source) VALUES (?,?,?,?,?,?,?,?,?)",
            (sup_id, entry_date, loan_type, float(amount), payment_method, reference_no, notes, deduct, fund_source),
        )
        db.commit()
        db.close()
        flash("Loan entry recorded.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="loans"))

    db.close()
    return render_template("supplier/loan_form.html", s=s, loan={}, methods=PAYMENT_METHODS)


@supplier_bp.route("/<int:sup_id>/loans")
def supplier_loans_list(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))
    loans = db.execute(
        "SELECT * FROM supplier_loans WHERE supplier_id = ? ORDER BY entry_date DESC",
        (sup_id,),
    ).fetchall()
    total_given = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM supplier_loans WHERE supplier_id = ? AND loan_type='given'",
        (sup_id,),
    ).fetchone()[0]
    total_recovered = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM supplier_loans WHERE supplier_id = ? AND loan_type='recovered'",
        (sup_id,),
    ).fetchone()[0]
    db.close()
    return render_template(
        "supplier/loans_list.html",
        s=s,
        loans=loans,
        total_given=total_given,
        total_recovered=total_recovered,
        net=total_given - total_recovered,
    )


# ═══════════════════════════════════════════════════════════
# KATA (Running Statement)
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/<int:sup_id>/kata")
def supplier_kata(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    ledger = []

    # Invoices — increase balance (we owe supplier)
    for inv in db.execute(
        "SELECT id, invoice_date as dt, invoice_no as ref, total_amount as amt, status FROM supplier_invoices WHERE supplier_id = ?",
        (sup_id,),
    ).fetchall():
        ledger.append({
            "date": inv["dt"],
            "type": "invoice",
            "description": f"Invoice: {inv['ref']} ({inv['status']})",
            "debit": 0,
            "credit": inv["amt"],
            "ref": inv["ref"],
        })

    # Expenses — increase balance
    for exp in db.execute(
        "SELECT id, expense_date as dt, category as ref, amount as amt, earning_type, quantity, rate FROM supplier_expenses WHERE supplier_id = ?",
        (sup_id,),
    ).fetchall():
        desc = f"Expense: {exp['ref']}"
        if exp["earning_type"] == "trip":
            desc = f"Trip: {exp['quantity']} x {exp['rate']} ({exp['ref']})"
        elif exp["earning_type"] == "hour":
            desc = f"Hours: {exp['quantity']} x {exp['rate']} ({exp['ref']})"
        ledger.append({
            "date": exp["dt"],
            "type": "expense",
            "description": desc,
            "debit": 0,
            "credit": exp["amt"],
            "ref": "",
        })

    # Payments — decrease balance
    for pay in db.execute(
        """SELECT pr.id, pr.payment_date as dt, pr.amount as amt, pr.payment_method as ref, pr.invoice_id, inv.invoice_no
           FROM supplier_payment_records pr
           LEFT JOIN supplier_invoices inv ON inv.id = pr.invoice_id
           WHERE pr.supplier_id = ?""",
        (sup_id,),
    ).fetchall():
        desc = f"Payment ({pay['ref']})"
        if pay["invoice_no"]:
            desc += f" → {pay['invoice_no']}"
        ledger.append({
            "date": pay["dt"],
            "type": "payment",
            "description": desc,
            "debit": pay["amt"],
            "credit": 0,
            "ref": pay["ref"],
        })

    # Loans — Qarz
    for loan in db.execute(
        "SELECT id, entry_date as dt, loan_type, amount as amt, reference_no as ref, notes, deduct_from_balance FROM supplier_loans WHERE supplier_id = ?",
        (sup_id,),
    ).fetchall():
        tag = " ✓" if loan["deduct_from_balance"] else " (Separate)"
        if loan["loan_type"] == "given":
            ledger.append({
                "date": loan["dt"],
                "type": "loan_given" if loan["deduct_from_balance"] else "loan_given_sep",
                "description": f"Qarz Given{tag}: {loan['notes'] or ''}",
                "debit": loan["amt"] if loan["deduct_from_balance"] else 0,
                "credit": 0,
                "ref": loan["ref"],
            })
        else:
            ledger.append({
                "date": loan["dt"],
                "type": "loan_recovered" if loan["deduct_from_balance"] else "loan_recovered_sep",
                "description": f"Qarz Recovered{tag}: {loan['notes'] or ''}",
                "debit": 0 if loan["deduct_from_balance"] else 0,
                "credit": loan["amt"] if loan["deduct_from_balance"] else 0,
                "ref": loan["ref"],
            })

    # Sort by date
    ledger.sort(key=lambda x: x["date"])

    # Calculate running balance
    running = 0
    for row in ledger:
        running += row["credit"] - row["debit"]
        row["balance"] = round(running, 2)

    total_credit = sum(r["credit"] for r in ledger)
    total_debit = sum(r["debit"] for r in ledger)
    closing = round(total_credit - total_debit, 2)

    db.close()
    return render_template(
        "supplier/kata.html",
        s=s,
        ledger=ledger,
        total_credit=total_credit,
        total_debit=total_debit,
        closing=closing,
    )


# ═══════════════════════════════════════════════════════════
# DELETE
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/<int:sup_id>/delete", methods=["POST"])
def supplier_delete(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        flash("Supplier not found.", "error")
    else:
        db.execute("DELETE FROM supplier_payment_records WHERE supplier_id = ?", (sup_id,))
        db.execute("DELETE FROM supplier_expenses WHERE supplier_id = ?", (sup_id,))
        db.execute("DELETE FROM supplier_invoices WHERE supplier_id = ?", (sup_id,))
        db.execute("DELETE FROM supplier_loans WHERE supplier_id = ?", (sup_id,))
        db.execute("DELETE FROM supplier_lpos WHERE supplier_id = ?", (sup_id,))
        db.execute("DELETE FROM supplier_documents WHERE supplier_id = ?", (sup_id,))
        db.execute("DELETE FROM suppliers WHERE id = ?", (sup_id,))
        db.commit()
        flash(f"Supplier {s['supplier_name']} deleted.", "info")
    db.close()
    return redirect(url_for("supplier.supplier_list"))


# ═══════════════════════════════════════════════════════════
# OWNER FUND
# ═══════════════════════════════════════════════════════════

FUND_SOURCES = [
    ("cash_bank", "Cash / Bank"),
    ("owner_fund", "Owner Fund"),
]

@supplier_bp.route("/owner-fund")
def owner_fund_dashboard():
    return redirect(url_for("owner_fund"))


@supplier_bp.route("/owner-fund/add", methods=["GET", "POST"])
def owner_fund_add():
    _ensure_tables()
    if request.method == "POST":
        amount = request.form.get("amount", "").strip()
        fund_date = request.form.get("fund_date", "").strip() or date.today().isoformat()
        owner_name = request.form.get("owner_name", "Owner").strip()
        transaction_type = request.form.get("transaction_type", "deposit").strip()
        description = request.form.get("description", "").strip()
        notes = request.form.get("notes", "").strip()
        if not amount or float(amount) <= 0:
            flash("Valid amount is required.", "error")
            return redirect(url_for("owner_fund"))
        db = _get_db()
        db.execute(
            "INSERT INTO owner_funds (amount, fund_date, owner_name, transaction_type, description, notes) VALUES (?,?,?,?,?,?)",
            (float(amount), fund_date, owner_name, transaction_type, description, notes),
        )
        db.commit()
        db.close()
        flash("Owner fund entry added.", "success")
        return redirect(url_for("owner_fund"))
    return redirect(url_for("owner_fund"))


# ═══════════════════════════════════════════════════════════
# DOCUMENTS
# ═══════════════════════════════════════════════════════════

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@supplier_bp.route("/<int:sup_id>/documents")
def supplier_doc_list(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        db.close()
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))
    docs = db.execute(
        "SELECT * FROM supplier_documents WHERE supplier_id = ? ORDER BY created_at DESC",
        (sup_id,),
    ).fetchall()
    db.close()
    return render_template("supplier/doc_list.html", s=s, docs=docs, today=date.today().isoformat())


DOC_TYPES = [
    "Trade License", "VAT Certificate", "ICV Certificate",
    "Chamber of Commerce", "Insurance", "LPO Document", "Other",
]

@supplier_bp.route("/<int:sup_id>/documents/add", methods=["GET", "POST"])
def supplier_doc_add(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        db.close()
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    if request.method == "POST":
        doc_type = request.form.get("doc_type", "").strip()
        doc_name = request.form.get("doc_name", "").strip()
        doc_ref = request.form.get("doc_ref", "").strip()
        expiry_date = request.form.get("expiry_date", "").strip()
        notes = request.form.get("notes", "").strip()
        if not doc_type or not doc_name:
            flash("Document type and name are required.", "error")
            return render_template("supplier/doc_form.html", s=s, doc={}, doc_types=DOC_TYPES)

        file_data = None
        file_type = None
        if "file" in request.files:
            f = request.files["file"]
            if f.filename:
                file_data = base64.b64encode(f.read()).decode("utf-8")
                file_type = f.content_type

        db.execute(
            "INSERT INTO supplier_documents (supplier_id, doc_type, doc_name, doc_ref, file_data, file_type, expiry_date, notes) VALUES (?,?,?,?,?,?,?,?)",
            (sup_id, doc_type, doc_name, doc_ref or None, file_data, file_type, expiry_date or None, notes),
        )
        db.commit()
        db.close()
        flash("Document uploaded.", "success")
        return redirect(url_for("supplier.supplier_doc_list", sup_id=sup_id))

    db.close()
    return render_template("supplier/doc_form.html", s=s, doc={}, doc_types=DOC_TYPES)


@supplier_bp.route("/<int:sup_id>/documents/<int:doc_id>/download")
def supplier_doc_download(sup_id, doc_id):
    _ensure_tables()
    db = _get_db()
    doc = db.execute("SELECT * FROM supplier_documents WHERE id=? AND supplier_id=?", (doc_id, sup_id)).fetchone()
    db.close()
    if not doc:
        flash("Document not found.", "error")
        return redirect(url_for("supplier.supplier_list"))
    if not doc["file_data"]:
        flash("No file attached.", "warning")
        return redirect(url_for("supplier.supplier_doc_list", sup_id=sup_id))
    data = base64.b64decode(doc["file_data"])
    return send_file(
        BytesIO(data),
        mimetype=doc["file_type"] or "application/octet-stream",
        as_attachment=True,
        download_name=doc["doc_name"],
    )


@supplier_bp.route("/<int:sup_id>/documents/<int:doc_id>/delete", methods=["POST"])
def supplier_doc_delete(sup_id, doc_id):
    _ensure_tables()
    db = _get_db()
    db.execute("DELETE FROM supplier_documents WHERE id=? AND supplier_id=?", (doc_id, sup_id))
    db.commit()
    db.close()
    flash("Document deleted.", "info")
    return redirect(url_for("supplier.supplier_doc_list", sup_id=sup_id))
