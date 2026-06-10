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
from app import csrf

from ..database import open_db


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
    return open_db()


def _schema_db():
    """Open a separate connection for schema setup to isolate transaction aborts."""
    from ..database import _connect_postgres, _connect_sqlite, DatabaseAdapter
    backend = current_app.config.get("DATABASE_BACKEND", "sqlite")
    if backend == "postgres":
        conn = _connect_postgres(current_app.config["DATABASE_URL"])
    else:
        conn = _connect_sqlite(current_app.config["DATABASE_PATH"])
    return DatabaseAdapter(conn, backend)


def _ensure_tables():
    db = _schema_db()
    backend = current_app.config.get("DATABASE_BACKEND", "sqlite")
    id_col = "id BIGSERIAL PRIMARY KEY" if backend == "postgres" else "id INTEGER PRIMARY KEY AUTOINCREMENT"
    now_val = "CURRENT_TIMESTAMP" if backend == "postgres" else "(datetime('now'))"
    real_type = "DOUBLE PRECISION" if backend == "postgres" else "REAL"

    db.executescript(f"""
        CREATE TABLE IF NOT EXISTS suppliers (
            {id_col},
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
            created_at TEXT NOT NULL DEFAULT {now_val}
        );

        CREATE TABLE IF NOT EXISTS supplier_invoices (
            {id_col},
            supplier_id INTEGER NOT NULL,
            invoice_no TEXT NOT NULL,
            invoice_date TEXT NOT NULL,
            due_date TEXT,
            amount {real_type} NOT NULL,
            vat_percentage {real_type} DEFAULT 5.0,
            vat_amount {real_type} DEFAULT 0.0,
            total_amount {real_type} NOT NULL,
            description TEXT,
            attachment_name TEXT,
            attachment_data TEXT,
            attachment_type TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            payment_date TEXT,
            payment_method TEXT,
            payment_ref TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT {now_val},
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );

        CREATE TABLE IF NOT EXISTS supplier_expenses (
            {id_col},
            supplier_id INTEGER NOT NULL,
            expense_date TEXT NOT NULL,
            amount {real_type} NOT NULL,
            category TEXT,
            description TEXT,
            receipt_name TEXT,
            receipt_data TEXT,
            receipt_type TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            approved_by TEXT,
            approved_at TEXT,
            created_at TEXT NOT NULL DEFAULT {now_val},
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );

        CREATE TABLE IF NOT EXISTS supplier_payment_records (
            {id_col},
            supplier_id INTEGER NOT NULL,
            invoice_id INTEGER,
            payment_date TEXT NOT NULL,
            amount {real_type} NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'Cash',
            reference_no TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT {now_val},
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
            FOREIGN KEY (invoice_id) REFERENCES supplier_invoices(id)
        );

        CREATE TABLE IF NOT EXISTS supplier_loans (
            {id_col},
            supplier_id INTEGER NOT NULL,
            entry_date TEXT NOT NULL,
            loan_type TEXT NOT NULL DEFAULT 'given',
            amount {real_type} NOT NULL,
            payment_method TEXT DEFAULT 'Cash',
            reference_no TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT {now_val},
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );
    """)

    db.executescript(f"""
        CREATE TABLE IF NOT EXISTS supplier_lpos (
            {id_col},
            supplier_id INTEGER NOT NULL,
            lpo_no TEXT NOT NULL,
            lpo_date TEXT NOT NULL,
            amount {real_type} DEFAULT 0,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT {now_val},
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );
        CREATE TABLE IF NOT EXISTS supplier_documents (
            {id_col},
            supplier_id INTEGER NOT NULL,
            doc_type TEXT NOT NULL,
            doc_name TEXT NOT NULL,
            doc_ref TEXT,
            file_data TEXT,
            file_type TEXT,
            expiry_date TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT {now_val},
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );
    """)

    db.executescript(f"""
        CREATE TABLE IF NOT EXISTS supplier_quotations (
            {id_col},
            supplier_id INTEGER NOT NULL,
            quotation_no TEXT NOT NULL,
            quotation_date TEXT NOT NULL,
            amount {real_type} DEFAULT 0,
            description TEXT,
            file_data TEXT,
            file_type TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT {now_val},
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );
    """)

    db.executescript(f"""
        CREATE TABLE IF NOT EXISTS supplier_quotation_items (
            {id_col},
            quotation_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            qty {real_type} DEFAULT 1,
            basis_type TEXT DEFAULT 'trip',
            shift_type TEXT DEFAULT 'single',
            day_rate {real_type} DEFAULT 0,
            night_rate {real_type} DEFAULT 0,
            amount {real_type} DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (quotation_id) REFERENCES supplier_quotations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS supplier_lpo_items (
            {id_col},
            lpo_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            qty {real_type} DEFAULT 1,
            basis_type TEXT DEFAULT 'trip',
            shift_type TEXT DEFAULT 'single',
            day_rate {real_type} DEFAULT 0,
            night_rate {real_type} DEFAULT 0,
            amount {real_type} DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (lpo_id) REFERENCES supplier_lpos(id) ON DELETE CASCADE
        );
    """)

    db.commit()

    for col, dtype in [("lpo_id", "INTEGER")]:
        try:
            db.execute(f"ALTER TABLE supplier_invoices ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    for col, dtype in [("lpo_type", "TEXT DEFAULT 'fixed'"), ("quotation_id", "INTEGER")]:
        try:
            db.execute(f"ALTER TABLE supplier_lpos ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    for col, dtype in [("earning_type", "TEXT DEFAULT 'fixed'"), ("quantity", real_type), ("rate", real_type)]:
        try:
            db.execute(f"ALTER TABLE supplier_expenses ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    for col, dtype in [("vehicle_no", "TEXT")]:
        try:
            db.execute(f"ALTER TABLE supplier_expenses ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    for col, dtype in [("invoice_ids", "TEXT"), ("fund_source", "TEXT DEFAULT 'cash_bank'")]:
        try:
            db.execute(f"ALTER TABLE supplier_payment_records ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    for col, dtype in [("deduct_from_balance", "INTEGER DEFAULT 0")]:
        try:
            db.execute(f"ALTER TABLE supplier_loans ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    db.execute(f"""CREATE TABLE IF NOT EXISTS owner_funds (
        {id_col},
        amount {real_type} NOT NULL,
        fund_date TEXT NOT NULL,
        description TEXT,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT {now_val}
    )""")

    for col, dtype in [("owner_name", "TEXT DEFAULT 'Owner'"), ("transaction_type", "TEXT DEFAULT 'deposit'")]:
        try:
            db.execute(f"ALTER TABLE owner_funds ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    for col, dtype in [("fund_source", "TEXT DEFAULT 'cash_bank'")]:
        try:
            db.execute(f"ALTER TABLE supplier_payment_records ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        try:
            db.execute(f"ALTER TABLE supplier_expenses ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        try:
            db.execute(f"ALTER TABLE supplier_loans ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    for col, dtype in [("is_deleted", "INTEGER DEFAULT 0")]:
        try:
            db.execute(f"ALTER TABLE suppliers ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    db.commit()
    db.close()
    # One-time migration runs only when suppliers table is empty
    try:
        check = _get_db().execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
        if check == 0:
            sync_parties_to_suppliers()
            _migrate_old_supplier_data()
    except Exception:
        pass


def sync_parties_to_suppliers():
    """Copy suppliers from main app's parties+supplier_profile into supplier blueprint's suppliers table."""
    db = _get_db()
    rows = db.execute(
        "SELECT p.party_code, p.party_name, p.contact_person, p.phone_number, p.email, "
        "p.trn_no, p.address, p.notes, p.status, p.created_at, "
        "COALESCE(pr.supplier_mode, 'Normal') AS supplier_mode "
        "FROM parties p "
        "LEFT JOIN supplier_profile pr ON pr.party_code = p.party_code "
        "WHERE LOWER(p.party_roles) LIKE LOWER(?)",
        ("%supplier%",)
    ).fetchall()

    for r in rows:
        supplier_type = "without_invoice" if (r["supplier_mode"] or "").lower() == "cash" else "with_invoice"
        existing = db.execute(
            "SELECT id FROM suppliers WHERE supplier_code = ?", (r["party_code"],)
        ).fetchone()
        if existing:
            db.execute(
                """UPDATE suppliers SET supplier_name=?, supplier_type=?,
                   contact_person=?, phone=?, email=?, trn=?, address=?,
                   notes=?, status=? WHERE supplier_code=?""",
                (r["party_name"], supplier_type, r["contact_person"],
                 r["phone_number"], r["email"], r["trn_no"], r["address"],
                 r["notes"], r["status"], r["party_code"]),
            )
        else:
            db.execute(
                """INSERT INTO suppliers (supplier_code, supplier_name, supplier_type,
                   contact_person, phone, email, trn, address, notes, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (r["party_code"], r["party_name"], supplier_type,
                 r["contact_person"], r["phone_number"], r["email"],
                 r["trn_no"], r["address"], r["notes"], r["status"],
                 r["created_at"] or "CURRENT_TIMESTAMP"),
            )
    db.commit()


def _migrate_old_supplier_data():
    """Migrate invoices, payments from PostgreSQL main tables to supplier blueprint tables."""
    new = _get_db()

    new_suppliers = {r["supplier_code"]: r["id"] for r in new.execute("SELECT supplier_code, id FROM suppliers").fetchall()}

    # ── Invoices from supplier_invoice_submissions ──
    try:
        old_inv = new.execute(
            "SELECT s.submission_no, s.external_invoice_no, s.invoice_date, s.total_amount, "
            "s.subtotal, s.vat_amount, s.notes, s.review_status, s.created_at, s.party_code "
            "FROM supplier_invoice_submissions s"
        ).fetchall()
    except Exception:
        old_inv = []
    for inv in old_inv:
        sup_id = new_suppliers.get(inv["party_code"])
        if not sup_id:
            continue
        existing = new.execute("SELECT id FROM supplier_invoices WHERE invoice_no=? AND supplier_id=?",
                               (inv["submission_no"], sup_id)).fetchone()
        if not existing:
            new.execute(
                """INSERT INTO supplier_invoices (supplier_id, invoice_no, invoice_date, amount,
                   vat_amount, total_amount, description, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP))""",
                (sup_id, inv["submission_no"], inv["invoice_date"],
                 inv["subtotal"], inv["vat_amount"], inv["total_amount"],
                 inv["notes"], inv["review_status"], inv["created_at"]),
            )

    # ── Payments from supplier_payments ──
    try:
        old_pay = new.execute(
            "SELECT p.payment_no, p.party_code, p.entry_date, p.amount, "
            "p.payment_method, p.reference, p.notes, p.created_at "
            "FROM supplier_payments p"
        ).fetchall()
    except Exception:
        old_pay = []
    for pay in old_pay:
        sup_id = new_suppliers.get(pay["party_code"])
        if not sup_id:
            continue
        existing = new.execute("SELECT id FROM supplier_payment_records WHERE reference_no=? AND supplier_id=? AND amount=?",
                               (pay["payment_no"], sup_id, pay["amount"])).fetchone()
        if not existing:
            new.execute(
                """INSERT INTO supplier_payment_records (supplier_id, payment_date, amount,
                   payment_method, reference_no, notes, created_at)
                   VALUES (?,?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP))""",
                (sup_id, pay["entry_date"], pay["amount"],
                 pay["payment_method"], pay["payment_no"], pay["notes"], pay["created_at"]),
            )

    # ── Vouchers as Expenses ──
    try:
        old_vouch = new.execute(
            "SELECT v.voucher_no, v.party_code, v.period_month, v.issue_date, v.total_amount, "
            "v.notes, v.created_at "
            "FROM supplier_vouchers v"
        ).fetchall()
    except Exception:
        old_vouch = []
    for v in old_vouch:
        sup_id = new_suppliers.get(v["party_code"])
        if not sup_id:
            continue
        existing = new.execute("SELECT id FROM supplier_expenses WHERE expense_date=? AND amount=? AND supplier_id=?",
                               (v["issue_date"], v["total_amount"], sup_id)).fetchone()
        if not existing:
            new.execute(
                """INSERT INTO supplier_expenses (supplier_id, expense_date, amount, category, description, created_at)
                   VALUES (?,?,?,'Services',?,COALESCE(?,CURRENT_TIMESTAMP))""",
                (sup_id, v["issue_date"], v["total_amount"], v["notes"], v["created_at"]),
            )

    # ── Cash Supplier Trips as Invoices ──
    try:
        cash_trips = new.execute(
            "SELECT trip_no, party_code, entry_date, total_amount, notes, created_at "
            "FROM cash_supplier_trips"
        ).fetchall()
    except Exception:
        cash_trips = []
    for t in cash_trips:
        sup_id = new_suppliers.get(t["party_code"])
        if not sup_id:
            continue
        existing = new.execute("SELECT id FROM supplier_invoices WHERE invoice_no=? AND supplier_id=?",
                               (t["trip_no"], sup_id)).fetchone()
        if not existing:
            new.execute(
                """INSERT INTO supplier_invoices (supplier_id, invoice_no, invoice_date, amount, total_amount, description, status, created_at)
                   VALUES (?,?,?,?,?,?,'paid',COALESCE(?,CURRENT_TIMESTAMP))""",
                (sup_id, t["trip_no"], t["entry_date"], t["total_amount"],
                 t["total_amount"], t["notes"], t["created_at"]),
            )

    # ── Cash Supplier Debits as Loans ──
    try:
        cash_debits = new.execute(
            "SELECT debit_no, party_code, entry_date, debit_type, amount, description, notes, created_at "
            "FROM cash_supplier_debits"
        ).fetchall()
    except Exception:
        cash_debits = []
    for d in cash_debits:
        sup_id = new_suppliers.get(d["party_code"])
        if not sup_id:
            continue
        existing = new.execute("SELECT id FROM supplier_loans WHERE entry_date=? AND amount=? AND supplier_id=?",
                               (d["entry_date"], d["amount"], sup_id)).fetchone()
        if not existing:
            new.execute(
                """INSERT INTO supplier_loans (supplier_id, entry_date, loan_type, amount, notes, created_at)
                   VALUES (?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP))""",
                (sup_id, d["entry_date"], d["debit_type"], d["amount"], d["notes"], d["created_at"]),
            )

    # ── Cash Supplier Payments ──
    try:
        cash_pay = new.execute(
            "SELECT payment_no, party_code, entry_date, amount, payment_method, reference, notes, created_at "
            "FROM cash_supplier_payments"
        ).fetchall()
    except Exception:
        cash_pay = []
    for p in cash_pay:
        sup_id = new_suppliers.get(p["party_code"])
        if not sup_id:
            continue
        existing = new.execute("SELECT id FROM supplier_payment_records WHERE reference_no=? AND supplier_id=? AND amount=?",
                               (p["payment_no"], sup_id, p["amount"])).fetchone()
        if not existing:
            new.execute(
                """INSERT INTO supplier_payment_records (supplier_id, payment_date, amount, payment_method, reference_no, notes, created_at)
                   VALUES (?,?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP))""",
                (sup_id, p["entry_date"], p["amount"], p["payment_method"],
                 p["payment_no"], p["notes"], p["created_at"]),
            )

    # ── LPOs from lpos table ──
    try:
        old_lpos = new.execute(
            "SELECT l.lpo_no, l.party_code, l.issue_date, l.amount, l.description, l.status, l.notes, l.created_at "
            "FROM lpos l"
        ).fetchall()
    except Exception:
        old_lpos = []
    for l in old_lpos:
        sup_id = new_suppliers.get(l["party_code"])
        if not sup_id:
            continue
        existing = new.execute("SELECT id FROM supplier_lpos WHERE lpo_no=? AND supplier_id=?",
                               (l["lpo_no"], sup_id)).fetchone()
        if not existing:
            new.execute(
                """INSERT INTO supplier_lpos (supplier_id, lpo_no, lpo_date, amount, description, status, notes, created_at)
                   VALUES (?,?,?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP))""",
                (sup_id, l["lpo_no"], l["issue_date"], l["amount"],
                 l["description"], l["status"], l["notes"], l["created_at"]),
            )

    # ── Quotations from supplier_quotation_submissions ──
    try:
        old_q = new.execute(
            "SELECT q.quotation_no, q.party_code, q.quotation_date, q.job_title, q.amount, q.notes, q.created_at "
            "FROM supplier_quotation_submissions q"
        ).fetchall()
    except Exception:
        old_q = []
    for q in old_q:
        sup_id = new_suppliers.get(q["party_code"])
        if not sup_id:
            continue
        existing = new.execute("SELECT id FROM supplier_quotations WHERE quotation_no=? AND supplier_id=?",
                               (q["quotation_no"], sup_id)).fetchone()
        if not existing:
            new.execute(
                """INSERT INTO supplier_quotations (supplier_id, quotation_no, quotation_date, amount, description, notes, created_at)
                   VALUES (?,?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP))""",
                (sup_id, q["quotation_no"], q["quotation_date"], q["amount"],
                 q["job_title"], q["notes"], q["created_at"]),
            )

    # ── Agreements as Documents ──
    try:
        old_ag = new.execute(
            "SELECT a.agreement_no, a.party_code, a.agreement_kind, a.start_date, a.end_date, "
            "a.amount, a.scope, a.notes, a.status, a.created_at "
            "FROM agreements a"
        ).fetchall()
    except Exception:
        old_ag = []
    for a in old_ag:
        sup_id = new_suppliers.get(a["party_code"])
        if not sup_id:
            continue
        content = f"Agreement: {a['agreement_no']} ({a['agreement_kind']})\nScope: {a['scope']}\nAmount: {a['amount']}\nPeriod: {a['start_date']} to {a['end_date'] or 'Open'}\nStatus: {a['status']}"
        existing = new.execute("SELECT id FROM supplier_documents WHERE doc_ref=? AND supplier_id=?",
                               (a["agreement_no"], sup_id)).fetchone()
        if not existing:
            new.execute(
                """INSERT INTO supplier_documents (supplier_id, doc_type, doc_name, doc_ref, notes, created_at)
                   VALUES (?,'Agreement',?,?,?,COALESCE(?,CURRENT_TIMESTAMP))""",
                (sup_id, a["agreement_no"], a["agreement_no"], content, a["created_at"]),
            )

    new.commit()



# ═══════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/")
def supplier_dashboard():
    try:
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

        return render_template(
            "supplier/dashboard.html",
            suppliers=suppliers,
            total=total,
            active=active,
            with_invoice_count=with_inv,
            without_invoice_count=without_inv,
            total_outstanding=total_outstanding,
            recent_invoices=recent_invoices,
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return f"<h2>Supplier Dashboard Error</h2><pre>{e}\n\n{tb}</pre>", 500


# ═══════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/list")
def supplier_list():
    _ensure_tables()
    db = _get_db()
    q = request.args.get("q", "").strip()
    typ = request.args.get("type", "")
    show_all = request.args.get("show", "") == "all"
    sql = "SELECT * FROM suppliers"
    params = []
    conditions = []
    if not show_all:
        conditions.append("COALESCE(is_deleted,0) = 0")
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
    sql += " ORDER BY COALESCE(is_deleted,0), supplier_name"
    suppliers = db.execute(sql, params).fetchall()

    return render_template("supplier/list.html", suppliers=suppliers, q=q, typ=typ, show_all=show_all)


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

        flash(f"Supplier {data['supplier_name']} added.", "success")
        return redirect(url_for("supplier.supplier_list"))


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

        flash("Supplier updated.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id))


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
        "SELECT COALESCE(SUM(amount),0) FROM supplier_loans WHERE supplier_id = ? AND loan_type='given'",
        (sup_id,),
    ).fetchone()[0]
    loan_recovered = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM supplier_loans WHERE supplier_id = ? AND loan_type='recovered'",
        (sup_id,),
    ).fetchone()[0]
    loan_given_sep = 0
    loan_recovered_sep = 0

    net_balance = round(inv_total + expense_total - paid_total, 2)

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


    company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()

    # Monthly chart data
    monthly_map = {}
    for inv in invoices:
        m = inv["invoice_date"][:7]
        monthly_map[m] = monthly_map.get(m, 0) + inv["total_amount"]
    for e in expenses:
        m = e["expense_date"][:7]
        monthly_map[m] = monthly_map.get(m, 0) + e["amount"]
    chart_months = sorted(monthly_map.keys())
    chart_values = [round(monthly_map[m], 2) for m in chart_months]

    return render_template(
        "supplier/profile.html",
        s=s,
        company=company,
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
        chart_months=chart_months,
        chart_values=chart_values,
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

    preselected_lpo = request.args.get("lpo_id", "").strip()
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
               attachment_name, attachment_data, attachment_type, notes, lpo_id, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sup_id, invoice_no, invoice_date, due_date or None,
             amount_f, vat_pct_f, vat_amt, total, description,
             attachment_name, attachment_data, attachment_type, notes,
             int(lpo_id) if lpo_id and lpo_id != "none" else None,
             'approved'),
        )
        db.commit()

        flash("Invoice added.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="invoices"))


    lpos = _get_db().execute("SELECT * FROM supplier_lpos WHERE supplier_id=? AND status='open' ORDER BY lpo_date DESC", (sup_id,)).fetchall()
    preselected = int(preselected_lpo) if preselected_lpo.isdigit() else None
    return render_template("supplier/invoice_form.html", s=s, inv={}, lpos=lpos, categories=SUPPLIER_CATEGORIES, preselected_lpo=preselected)


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

        flash("Invoice updated.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="invoices"))


    lpos = _get_db().execute("SELECT * FROM supplier_lpos WHERE supplier_id=? ORDER BY lpo_date DESC", (sup_id,)).fetchall()
    return render_template("supplier/invoice_form.html", s=s, inv=inv, lpos=lpos, categories=SUPPLIER_CATEGORIES)


@supplier_bp.route("/invoices/<int:inv_id>/attachment")
def supplier_invoice_attachment(inv_id):
    db = _get_db()
    inv = db.execute("SELECT * FROM supplier_invoices WHERE id = ?", (inv_id,)).fetchone()

    if not inv or not inv["attachment_data"]:
        flash("Attachment not found.", "error")
        return redirect(url_for("supplier.supplier_dashboard"))
    data = base64.b64decode(inv["attachment_data"])
    return send_file(
        BytesIO(data),
        mimetype=inv["attachment_type"] or "application/octet-stream",
        as_attachment=True,
        download_name=inv["attachment_name"] or f"invoice_{inv_id}",
    )


@supplier_bp.route("/<int:sup_id>/invoices/<int:inv_id>/delete", methods=["POST"])
def supplier_invoice_delete(sup_id, inv_id):
    _ensure_tables()
    db = _get_db()
    try:
        db.execute("UPDATE supplier_payment_records SET invoice_id=NULL WHERE invoice_id=? AND supplier_id=?", (inv_id, sup_id))
        db.execute("DELETE FROM supplier_invoices WHERE id=? AND supplier_id=?", (inv_id, sup_id))
        db.commit()
        flash("Invoice deleted.", "info")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting invoice: {e}", "error")
    return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="earnings"))


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

        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))
    lpos = db.execute(
        "SELECT sl.*, sq.quotation_no FROM supplier_lpos sl LEFT JOIN supplier_quotations sq ON sl.quotation_id=sq.id WHERE sl.supplier_id = ? ORDER BY sl.lpo_date DESC",
        (sup_id,),
    ).fetchall()

    return render_template("supplier/lpo_list.html", s=s, lpos=lpos)


@supplier_bp.route("/<int:sup_id>/lpos/add", methods=["GET", "POST"])
def supplier_lpo_add(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:

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
            company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
            return render_template("supplier/lpo_form.html", s=s, company=company, lpo={}, lpo_types=LPO_TYPES, quotations=[], qitems=[])
        qid = int(quotation_id) if quotation_id and quotation_id != "none" else None

        row = db.execute(
            "INSERT INTO supplier_lpos (supplier_id, lpo_no, lpo_date, lpo_type, quotation_id, amount, description, notes) VALUES (?,?,?,?,?,?,?,?) RETURNING id",
            (sup_id, lpo_no, lpo_date, lpo_type, qid, 0, description, notes),
        ).fetchone()
        lpo_id = row["id"]

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

        flash("LPO added.", "success")
        return redirect(url_for("supplier.supplier_lpo_list", sup_id=sup_id))

    quotations = db.execute("SELECT * FROM supplier_quotations WHERE supplier_id=? ORDER BY quotation_date DESC", (sup_id,)).fetchall()
    company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()

    return render_template("supplier/lpo_form.html", s=s, company=company, lpo={}, lpo_types=LPO_TYPES, quotations=quotations, qitems=[])


@supplier_bp.route("/<int:sup_id>/lpos/<int:lpo_id>/edit", methods=["GET", "POST"])
def supplier_lpo_edit(sup_id, lpo_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    lpo = db.execute("SELECT * FROM supplier_lpos WHERE id=? AND supplier_id=?", (lpo_id, sup_id)).fetchone()
    if not s or not lpo:
        flash("LPO not found.", "error")
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
            company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
            return render_template("supplier/lpo_form.html", s=s, company=company, lpo=lpo, lpo_types=LPO_TYPES, quotations=[], qitems=[])
        qid = int(quotation_id) if quotation_id and quotation_id != "none" else None

        total_amount = 0
        db.execute("DELETE FROM supplier_lpo_items WHERE lpo_id=?", (lpo_id,))

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

        db.execute("UPDATE supplier_lpos SET lpo_no=?, lpo_date=?, lpo_type=?, quotation_id=?, amount=?, description=?, notes=? WHERE id=?",
                   (lpo_no, lpo_date, lpo_type, qid, round(total_amount, 2), description, notes, lpo_id))
        db.commit()

        flash("LPO updated.", "success")
        return redirect(url_for("supplier.supplier_lpo_list", sup_id=sup_id))

    items = db.execute("SELECT * FROM supplier_lpo_items WHERE lpo_id=? ORDER BY sort_order", (lpo_id,)).fetchall()
    quotations = db.execute("SELECT * FROM supplier_quotations WHERE supplier_id=? ORDER BY quotation_date DESC", (sup_id,)).fetchall()
    company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()

    return render_template("supplier/lpo_form.html", s=s, company=company, lpo=lpo, items=items, lpo_types=LPO_TYPES, quotations=quotations, qitems=[])


@supplier_bp.route("/<int:sup_id>/lpos/<int:lpo_id>/delete", methods=["POST"])
def supplier_lpo_delete(sup_id, lpo_id):
    _ensure_tables()
    db = _get_db()
    try:
        db.execute("DELETE FROM supplier_lpos WHERE id=? AND supplier_id=?", (lpo_id, sup_id))
        db.commit()
        flash("LPO deleted.", "info")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting LPO: {e}", "error")
    return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="lpos"))


@supplier_bp.route("/<int:sup_id>/lpos/<int:lpo_id>/close", methods=["POST"])
def supplier_lpo_close(sup_id, lpo_id):
    _ensure_tables()
    db = _get_db()
    db.execute("UPDATE supplier_lpos SET status='closed' WHERE id=? AND supplier_id=?", (lpo_id, sup_id))
    db.commit()

    flash("LPO closed.", "info")
    return redirect(url_for("supplier.supplier_lpo_list", sup_id=sup_id))


@supplier_bp.route("/<int:sup_id>/lpos/<int:lpo_id>/pdf")
def supplier_lpo_pdf(sup_id, lpo_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.platypus import Image as RLImage
    from reportlab.lib.units import cm
    from io import BytesIO
    import base64

    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    lpo = db.execute("SELECT * FROM supplier_lpos WHERE id=? AND supplier_id=?", (lpo_id, sup_id)).fetchone()
    items = db.execute("SELECT * FROM supplier_lpo_items WHERE lpo_id=? ORDER BY sort_order", (lpo_id,)).fetchall()
    quotation = None
    if lpo and lpo["quotation_id"]:
        quotation = db.execute("SELECT * FROM supplier_quotations WHERE id=?", (lpo["quotation_id"],)).fetchone()
    try:
        company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    except Exception:
        company = None

    if not s or not lpo:
        flash("LPO not found.", "error")
        return redirect(url_for("supplier.supplier_lpo_list", sup_id=sup_id))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm)
    avail = A4[0] - 4*cm  # ~146mm

    NAVY = colors.HexColor("#1a3a5c")
    LINE = colors.HexColor("#e2e8f0")
    MUTED = colors.HexColor("#94a3b8")
    DARK = colors.HexColor("#0f172a")

    # Styles
    s_hdr = ParagraphStyle("hdr", fontSize=11, fontName="Helvetica-Bold", textColor=NAVY, leading=14)
    s_hdr_sm = ParagraphStyle("hsm", fontSize=7.5, textColor=MUTED, leading=10)
    s_title = ParagraphStyle("tit", fontSize=16, fontName="Helvetica-Bold", alignment=TA_RIGHT, textColor=NAVY, leading=18)
    s_info = ParagraphStyle("inf", fontSize=9, textColor=DARK, leading=12, spaceAfter=2)
    s_info_lbl = ParagraphStyle("ibl", fontSize=7, textColor=colors.HexColor("#64748b"), leading=9, spaceAfter=0)
    s_sec = ParagraphStyle("sec", fontSize=10, fontName="Helvetica-Bold", textColor=colors.HexColor("#0f2b52"), leading=12, spaceAfter=4, spaceBefore=8)
    s_cell = ParagraphStyle("cel", fontSize=8, leading=10, spaceAfter=0)
    s_cell_b = ParagraphStyle("celb", fontSize=8, fontName="Helvetica-Bold", leading=10, spaceAfter=0, alignment=TA_CENTER)
    s_cell_r = ParagraphStyle("celr", fontSize=8, leading=10, spaceAfter=0, alignment=TA_RIGHT)
    s_sign = ParagraphStyle("sgn", fontSize=8, alignment=TA_CENTER, leading=10, textColor=DARK)
    s_foot = ParagraphStyle("fot", fontSize=6.5, textColor=MUTED, alignment=TA_CENTER, leading=8)

    type_labels = dict(LPO_TYPES)
    lpo_type_str = type_labels.get(lpo["lpo_type"], lpo["lpo_type"] or "Fixed Amount")
    basis_labels = {"trip": "Trip", "hour": "Hour", "monthly": "Monthly", "fixed": "Fixed", "other": "Other"}
    total_amt = lpo["amount"] or 0

    cn = (company["company_name"] if company else "CURRENT LINK TRANSPORT") or "CURRENT LINK TRANSPORT"
    c_addr = (company["address"] if company else "") or ""
    c_trn = (company["trn_no"] if company else "XXXXXXXXXX") or "XXXXXXXXXX"
    c_ph = (company["phone_number"] if company else "") or ""
    c_em = (company["email"] if company else "") or ""

    logo_img = None
    if company and company.get("logo_data"):
        try:
            logo_img = RLImage(BytesIO(base64.b64decode(company["logo_data"])), width=22*mm, height=22*mm)
        except Exception:
            logo_img = None

    els = []

    # ── HEADER ──
    co_lines = []
    if c_addr: co_lines.append("<font size=7>" + c_addr + "</font>")
    parts = []
    if c_ph: parts.append("Phone: " + c_ph)
    if c_em: parts.append("Email: " + c_em)
    if parts: co_lines.append("<font size=7>" + " &middot; ".join(parts) + "</font>")
    co_lines.append("<font size=7><b>TRN:</b> " + c_trn + "</font>")
    co_html = cn + "<br/>" + "<br/>".join(co_lines)
    if logo_img:
        hdr_data = [[logo_img, Paragraph(co_html, s_hdr), Paragraph("LOCAL PURCHASE ORDER<br/><font size=8>LPO #: <b>" + lpo['lpo_no'] + "</b></font>", s_title)]]
        hdr_tbl = Table(hdr_data, colWidths=[2.2*cm, None, None])
    else:
        hdr_data = [[Paragraph(co_html, s_hdr), Paragraph("LOCAL PURCHASE ORDER<br/><font size=8>LPO #: <b>" + lpo['lpo_no'] + "</b></font>", s_title)]]
        hdr_tbl = Table(hdr_data, colWidths=[None, None])
    hdr_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LINEBELOW", (0,0), (-1,0), 2.5, NAVY),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
    ]))
    els.append(hdr_tbl)
    els.append(Spacer(1, 3*mm))

    # ── INFO section as simple table ──
    els.append(Paragraph("LPO INFORMATION", s_sec))
    info_rows = [
        [Paragraph("LPO Number", s_info_lbl), Paragraph(lpo['lpo_no'], s_info),
         Paragraph("Date", s_info_lbl), Paragraph(lpo['lpo_date'], s_info),
         Paragraph("Basis / Type", s_info_lbl), Paragraph(lpo_type_str, s_info)],
        [Paragraph("Quotation", s_info_lbl), Paragraph((quotation['quotation_no'] if quotation else "-"), s_info),
         Paragraph("Supplier", s_info_lbl), Paragraph(s['supplier_name'], s_info),
         Paragraph("Status", s_info_lbl), Paragraph("<font color='#e65100'><b>" + lpo['status'].upper() + "</b></font>", s_info)],
    ]
    info_tbl = Table(info_rows, colWidths=[None, None, None, None, None, None])
    info_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOX", (0,0), (-1,-1), 0.5, LINE),
        ("INNERGRID", (0,0), (-1,-1), 0.3, LINE),
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING", (0,0), (-1,-1), 5),
        ("RIGHTPADDING", (0,0), (-1,-1), 5),
    ]))
    els.append(info_tbl)
    els.append(Spacer(1, 3*mm))

    # ── ITEMS TABLE ──
    els.append(Paragraph("SERVICE / WORK ITEMS", s_sec))
    i_hdr = [Paragraph("<b>#</b>", s_cell_b), Paragraph("<b>Description</b>", s_cell),
             Paragraph("<b>QTY</b>", s_cell_b), Paragraph("<b>Basis</b>", s_cell),
             Paragraph("<b>Rate (AED)</b>", s_cell_b), Paragraph("<b>Amount</b>", s_cell_b)]
    i_rows = [i_hdr]
    for idx, it in enumerate(items):
        i_rows.append([
            Paragraph(str(idx+1), s_cell_b), Paragraph(it["description"], s_cell),
            Paragraph(str(it["qty"]), s_cell_b),
            Paragraph(basis_labels.get(it["basis_type"], it["basis_type"]), s_cell),
            Paragraph(f"{it['day_rate'] or 0:,.2f}", s_cell_r),
            Paragraph(f"{it['amount'] or 0:,.2f}", ParagraphStyle("cr3", fontSize=8, fontName="Helvetica-Bold", leading=10, spaceAfter=0, alignment=TA_RIGHT)),
        ])
    i_rows.append([
        Paragraph("", s_cell), Paragraph("<b>TOTAL</b>", ParagraphStyle("tl", fontSize=10, fontName="Helvetica-Bold", alignment=TA_RIGHT, leading=13)),
        Paragraph("", s_cell), Paragraph("", s_cell), Paragraph("", s_cell),
        Paragraph(f"<b>{total_amt:,.2f}</b>", ParagraphStyle("tv", fontSize=11, fontName="Helvetica-Bold", alignment=TA_RIGHT, textColor=NAVY, leading=14)),
    ])
    i_tbl = Table(i_rows, colWidths=[None]*6, repeatRows=1)
    i_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BOX", (0,0), (-1,-1), 0.5, LINE),
        ("INNERGRID", (0,0), (-1,-2), 0.3, LINE),
        ("BACKGROUND", (0,0), (-1,0), NAVY),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#f0f4f8")),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING", (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
    ]))
    els.append(i_tbl)
    els.append(Spacer(1, 2*mm))

    # ── TOTAL & AMOUNT IN WORDS ──
    def num_to_words(n):
        if n == 0: return "Zero Only"
        ones = ["","One","Two","Three","Four","Five","Six","Seven","Eight","Nine",
                "Ten","Eleven","Twelve","Thirteen","Fourteen","Fifteen","Sixteen",
                "Seventeen","Eighteen","Nineteen"]
        tens = ["","","Twenty","Thirty","Forty","Fifty","Sixty","Seventy","Eighty","Ninety"]
        def cvt(x):
            if x < 20: return ones[x]
            if x < 100: return tens[x//10] + (" " + ones[x%10] if x%10 else "")
            if x < 1000: return ones[x//100] + " Hundred" + (" " + cvt(x%100) if x%100 else "")
            if x < 100000: return cvt(x//1000) + " Thousand" + (" " + cvt(x%1000) if x%1000 else "")
            return cvt(x//100000) + " Lakh" + (" " + cvt(x%100000) if x%100000 else "")
        ip = int(n); dp = round((n - ip) * 100)
        w = cvt(ip)
        if dp: w += f" and {dp}/100"
        return "AED " + w + " Only"

    # Simple bordered boxes for total and words
    total_p = Paragraph("Total: AED " + f"{total_amt:,.2f}", ParagraphStyle("tb", fontSize=13, fontName="Helvetica-Bold", alignment=TA_RIGHT, textColor=NAVY, leading=16))
    total_box = Table([[total_p]], colWidths=[None])
    total_box.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f0f4f8")),
        ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#dde4ec")),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 10), ("RIGHTPADDING", (0,0), (-1,-1), 10),
    ]))
    els.append(total_box)
    els.append(Spacer(1, 2*mm))

    words_p = Paragraph("<b>Amount in Words:</b> " + num_to_words(total_amt), ParagraphStyle("wrds", fontSize=8.5, textColor=colors.HexColor("#64748b"), leading=11))
    words_box = Table([[words_p]], colWidths=[None])
    words_box.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ("BOX", (0,0), (-1,-1), 0.5, LINE),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 8), ("RIGHTPADDING", (0,0), (-1,-1), 8),
    ]))
    els.append(words_box)
    els.append(Spacer(1, 3*mm))

    # ── NOTES & TERMS ──
    desc_text = lpo["description"] or ""
    notes_text = lpo["notes"] or ""
    if desc_text or notes_text:
        els.append(Paragraph("DESCRIPTION &amp; TERMS", s_sec))
        if desc_text:
            els.append(Paragraph("<b>Scope / Notes</b><br/>" + desc_text, ParagraphStyle("nts", fontSize=8, textColor=colors.HexColor("#334155"), leading=11, spaceAfter=4)))
        if notes_text:
            els.append(Paragraph("<b>Special Terms</b><br/>" + notes_text, ParagraphStyle("stn", fontSize=8, textColor=colors.HexColor("#334155"), leading=11, spaceAfter=4)))

    # ── Standard Terms ──
    els.append(Spacer(1, 2*mm))
    std_terms = [
        "Payment as per agreed payment terms.",
        "VAT @ 5% will be charged separately as per UAE Federal Law.",
        "This LPO is valid for 30 days from the date of issue.",
        "Services/goods must be delivered as per the specifications mentioned above.",
        "Any changes or amendments to this LPO require written confirmation.",
        "Delivery location: As per agreement.",
    ]
    t_html = "<b>Terms &amp; Conditions</b><br/>" + "<br/>".join([chr(8226) + " " + t for t in std_terms])
    els.append(Paragraph(t_html, ParagraphStyle("st", fontSize=7.5, textColor=colors.HexColor("#64748b"), leading=11, leftIndent=6)))

    # ── SIGNATURES ──
    els.append(Spacer(1, 5*mm))
    sig_rows = [[
        Paragraph("_________________________<br/><b>Company Sign &amp; Stamp</b><br/><font size=7>Date: _____/_____/_____</font>", s_sign),
        Paragraph("", s_sign),
        Paragraph("_________________________<br/><b>Supplier Sign &amp; Stamp</b><br/><font size=7>Date: _____/_____/_____</font>", s_sign),
    ]]
    sig_tbl = Table(sig_rows, colWidths=[None, 20, None])
    sig_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LINEABOVE", (0,0), (0,0), 0.5, colors.HexColor("#999")),
        ("LINEABOVE", (2,0), (2,0), 0.5, colors.HexColor("#999")),
    ]))
    els.append(sig_tbl)

    # ── FOOTER ──
    els.append(Spacer(1, 4*mm))
    els.append(Paragraph("This is a computer-generated document. No signature required for electronic transmission.", s_foot))
    els.append(Paragraph("Generated on: " + datetime.now().strftime("%d-%b-%Y %H:%M"), ParagraphStyle("gn", fontSize=6, textColor=colors.HexColor("#aaa"), alignment=TA_CENTER, leading=8, spaceAfter=0)))

    doc.build(els)
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

        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))
    quotations = db.execute(
        "SELECT * FROM supplier_quotations WHERE supplier_id = ? ORDER BY quotation_date DESC",
        (sup_id,),
    ).fetchall()

    return render_template("supplier/quotation_list.html", s=s, quotations=quotations)


@supplier_bp.route("/<int:sup_id>/quotations/add", methods=["GET", "POST"])
def supplier_quotation_add(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:

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

        row = db.execute(
            "INSERT INTO supplier_quotations (supplier_id, quotation_no, quotation_date, amount, description, file_data, file_type, notes) VALUES (?,?,?,?,?,?,?,?) RETURNING id",
            (sup_id, q_no, q_date, 0, description, file_data, file_type, notes),
        ).fetchone()
        q_id = row["id"]

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

        flash("Quotation added.", "success")
        return redirect(url_for("supplier.supplier_quotation_list", sup_id=sup_id))


    return render_template("supplier/quotation_form.html", s=s, quotation={})


@supplier_bp.route("/<int:sup_id>/quotations/<int:q_id>/items")
def supplier_quotation_items_api(sup_id, q_id):
    _ensure_tables()
    db = _get_db()
    items = db.execute("SELECT * FROM supplier_quotation_items WHERE quotation_id=? ORDER BY sort_order", (q_id,)).fetchall()

    from flask import jsonify
    return jsonify([dict(i) for i in items])


@supplier_bp.route("/<int:sup_id>/quotations/<int:q_id>/download")
def supplier_quotation_download(sup_id, q_id):
    _ensure_tables()
    db = _get_db()
    q = db.execute("SELECT * FROM supplier_quotations WHERE id=? AND supplier_id=?", (q_id, sup_id)).fetchone()

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

        vehicle_no = request.form.get("vehicle_no", "").strip()

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
               receipt_name, receipt_data, receipt_type, earning_type, quantity, rate, fund_source, vehicle_no, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sup_id, expense_date, amount, category, description,
             receipt_name, receipt_data, receipt_type, earning_type, qty_f, rate_f, fund_source, vehicle_no or None,
             'approved'),
        )
        db.commit()

        flash("Expense added.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="expenses"))


    return render_template("supplier/expense_form.html", s=s, exp={}, today=date.today().isoformat())


@supplier_bp.route("/<int:sup_id>/expenses/<int:exp_id>/approve", methods=["POST"])
def supplier_expense_approve(sup_id, exp_id):
    _ensure_tables()
    db = _get_db()
    db.execute("UPDATE supplier_expenses SET status='approved' WHERE id=? AND supplier_id=?", (exp_id, sup_id))
    db.commit()

    flash("Expense approved.", "success")
    return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="expenses"))


@supplier_bp.route("/<int:sup_id>/expenses/<int:exp_id>/edit", methods=["GET", "POST"])
def supplier_expense_edit(sup_id, exp_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    exp = db.execute("SELECT * FROM supplier_expenses WHERE id=? AND supplier_id=?", (exp_id, sup_id)).fetchone()
    if not s or not exp:
        flash("Expense not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    if request.method == "POST":
        expense_date = request.form.get("expense_date", "").strip() or date.today().isoformat()
        earning_type = request.form.get("earning_type", "fixed").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        qty = request.form.get("quantity", "").strip()
        rate = request.form.get("rate", "").strip()
        vehicle_no = request.form.get("vehicle_no", "").strip()

        if earning_type in ("trip", "hour"):
            qty_f = float(qty) if qty else 0
            rate_f = float(rate) if rate else 0
            amount = round(qty_f * rate_f, 2)
        else:
            amount = float(request.form.get("amount", 0))
            qty_f = None
            rate_f = None

        if not category:
            flash("Category is required.", "error")
            return render_template("supplier/expense_form.html", s=s, exp=exp)

        db.execute(
            "UPDATE supplier_expenses SET expense_date=?, amount=?, category=?, description=?, earning_type=?, quantity=?, rate=?, vehicle_no=? WHERE id=?",
            (expense_date, amount, category, description, earning_type, qty_f, rate_f, vehicle_no or None, exp_id),
        )
        db.commit()
        flash("Earning updated.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="earnings"))

    return render_template("supplier/expense_form.html", s=s, exp=exp, today=exp["expense_date"])


@supplier_bp.route("/<int:sup_id>/expenses/<int:exp_id>/delete", methods=["POST"])
def supplier_expense_delete(sup_id, exp_id):
    _ensure_tables()
    db = _get_db()
    try:
        db.execute("DELETE FROM supplier_expenses WHERE id=? AND supplier_id=?", (exp_id, sup_id))
        db.commit()
        flash("Earning deleted.", "info")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting earning: {e}", "error")
    return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="earnings"))


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

    if request.method == "POST":
        payment_date = request.form.get("payment_date", "").strip() or date.today().isoformat()
        amount = request.form.get("amount", "").strip()
        invoice_ids = request.form.getlist("invoice_ids")
        payment_method = request.form.get("payment_method", "Cash").strip()
        reference_no = request.form.get("reference_no", "").strip()
        notes = request.form.get("notes", "").strip()

        if not amount:
            flash("Payment amount is required.", "error")
            return render_template("supplier/payment_form.html", s=s, pay={}, invoices=unpaid, methods=PAYMENT_METHODS, today=date.today().isoformat())

        amount_f = float(amount)
        fund_source = request.form.get("fund_source", "cash_bank").strip()
        invoice_ids_str = ",".join(invoice_ids)

        # Ensure columns exist
        try:
            db.execute("ALTER TABLE supplier_payment_records ADD COLUMN invoice_ids TEXT")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        try:
            db.execute("ALTER TABLE supplier_payment_records ADD COLUMN fund_source TEXT DEFAULT 'cash_bank'")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

        # Create one payment record for the batch
        db.execute(
            "INSERT INTO supplier_payment_records (supplier_id, invoice_id, invoice_ids, payment_date, amount, payment_method, reference_no, notes, fund_source) VALUES (?,?,?,?,?,?,?,?,?)",
            (sup_id, None, invoice_ids_str, payment_date, amount_f, payment_method, reference_no, notes, fund_source),
        )

        # Mark all selected invoices as paid
        for inv_id_str in invoice_ids:
            inv_id = int(inv_id_str.strip()) if inv_id_str.strip().isdigit() else None
            if inv_id:
                db.execute(
                    "UPDATE supplier_invoices SET status='paid', payment_date=?, payment_method=?, payment_ref=? WHERE id=?",
                    (payment_date, payment_method, reference_no, inv_id),
                )

        db.commit()

        inv_count = len(invoice_ids)
        flash(f"Payment of AED {amount_f:.2f} recorded against {inv_count} invoice(s).", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="payments"))


    return render_template("supplier/payment_form.html", s=s, pay={}, invoices=unpaid, methods=PAYMENT_METHODS, today=date.today().isoformat())


# ═══════════════════════════════════════════════════════════
# PAYMENT VOUCHER PDF
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/<int:sup_id>/payments/<int:pay_id>/voucher")
def supplier_payment_voucher(sup_id, pay_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    pay = db.execute("SELECT * FROM supplier_payment_records WHERE id = ? AND supplier_id = ?", (pay_id, sup_id)).fetchone()
    if not s or not pay:
        flash("Payment not found.", "error")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id))
    invoices = []
    if pay.get("invoice_ids"):
        ids = [x.strip() for x in pay["invoice_ids"].split(",") if x.strip().isdigit()]
        if ids:
            placeholders = ",".join("?" * len(ids))
            invoices = db.execute(
                f"SELECT id, invoice_no, invoice_date, total_amount FROM supplier_invoices WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
    inv = db.execute("SELECT * FROM supplier_invoices WHERE id = ?", (pay["invoice_id"],)).fetchone() if pay["invoice_id"] else None
    try:
        company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    except Exception:
        company = None
    return render_template("supplier/payment_voucher.html", s=s, pay=pay, inv=inv, invoices=invoices, company=company, today=date.today().isoformat())


@supplier_bp.route("/<int:sup_id>/payments/<int:pay_id>/edit", methods=["GET", "POST"])
def supplier_payment_edit(sup_id, pay_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    pay = db.execute("SELECT * FROM supplier_payment_records WHERE id=? AND supplier_id=?", (pay_id, sup_id)).fetchone()
    if not s or not pay:
        flash("Payment not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    unpaid = db.execute(
        "SELECT id, invoice_no, total_amount FROM supplier_invoices WHERE supplier_id = ? ORDER BY invoice_date",
        (sup_id,),
    ).fetchall()

    if request.method == "POST":
        payment_date = request.form.get("payment_date", "").strip() or date.today().isoformat()
        amount = request.form.get("amount", "").strip()
        invoice_id = request.form.get("invoice_id", "").strip()
        payment_method = request.form.get("payment_method", "Cash").strip()
        reference_no = request.form.get("reference_no", "").strip()
        notes = request.form.get("notes", "").strip()
        if not amount:
            flash("Payment amount is required.", "error")
            return render_template("supplier/payment_form.html", s=s, pay=pay, invoices=unpaid, methods=PAYMENT_METHODS, today=date.today().isoformat())
        amount_f = float(amount)
        inv_id_val = int(invoice_id) if invoice_id.isdigit() else None
        fund_source = request.form.get("fund_source", "cash_bank").strip()

        db.execute(
            "UPDATE supplier_payment_records SET payment_date=?, amount=?, invoice_id=?, payment_method=?, reference_no=?, notes=?, fund_source=? WHERE id=?",
            (payment_date, amount_f, inv_id_val, payment_method, reference_no, notes, fund_source, pay_id),
        )
        db.commit()
        flash("Payment updated.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="payments"))

    return render_template("supplier/payment_form.html", s=s, pay=pay, invoices=unpaid, methods=PAYMENT_METHODS, today=date.today().isoformat())


@supplier_bp.route("/<int:sup_id>/payments/<int:pay_id>/delete", methods=["POST"])
def supplier_payment_delete(sup_id, pay_id):
    _ensure_tables()
    db = _get_db()
    try:
        pay = db.execute("SELECT * FROM supplier_payment_records WHERE id=? AND supplier_id=?", (pay_id, sup_id)).fetchone()
        db.execute("DELETE FROM supplier_payment_records WHERE id=? AND supplier_id=?", (pay_id, sup_id))
        if pay and pay["invoice_id"]:
            db.execute("UPDATE supplier_invoices SET status='approved', payment_date=NULL, payment_method=NULL, payment_ref=NULL WHERE id=?", (pay["invoice_id"],))
        db.commit()
        flash("Payment deleted.", "info")
    except Exception as e:
        db.rollback()
        flash(f"Error deleting payment: {e}", "error")
    return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="payments"))

csrf.exempt(supplier_payment_delete)

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

        if not amount:
            flash("Amount is required.", "error")
            return render_template("supplier/loan_form.html", s=s, loan={}, methods=PAYMENT_METHODS)

        fund_source = request.form.get("fund_source", "cash_bank").strip()
        db.execute(
            "INSERT INTO supplier_loans (supplier_id, entry_date, loan_type, amount, payment_method, reference_no, notes, fund_source) VALUES (?,?,?,?,?,?,?,?)",
            (sup_id, entry_date, loan_type, float(amount), payment_method, reference_no, notes, fund_source),
        )
        db.commit()

        flash("Loan entry recorded.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="loans"))


    return render_template("supplier/loan_form.html", s=s, loan={}, methods=PAYMENT_METHODS)


@supplier_bp.route("/<int:sup_id>/loans/<int:loan_id>/edit", methods=["GET", "POST"])
def supplier_loan_edit(sup_id, loan_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    loan = db.execute("SELECT * FROM supplier_loans WHERE id=? AND supplier_id=?", (loan_id, sup_id)).fetchone()
    if not s or not loan:
        flash("Loan entry not found.", "error")
        return redirect(url_for("supplier.supplier_list"))

    if request.method == "POST":
        entry_date = request.form.get("entry_date", "").strip() or date.today().isoformat()
        loan_type = request.form.get("loan_type", "given").strip()
        amount = request.form.get("amount", "").strip()
        payment_method = request.form.get("payment_method", "Cash").strip()
        reference_no = request.form.get("reference_no", "").strip()
        notes = request.form.get("notes", "").strip()
        fund_source = request.form.get("fund_source", "cash_bank").strip()

        if not amount:
            flash("Amount is required.", "error")
            return render_template("supplier/loan_form.html", s=s, loan=loan, methods=PAYMENT_METHODS)

        db.execute(
            "UPDATE supplier_loans SET entry_date=?, loan_type=?, amount=?, payment_method=?, reference_no=?, notes=?, fund_source=? WHERE id=?",
            (entry_date, loan_type, float(amount), payment_method, reference_no, notes, fund_source, loan_id),
        )
        db.commit()
        flash("Loan entry updated.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="loans"))

    return render_template("supplier/loan_form.html", s=s, loan=loan, methods=PAYMENT_METHODS)


@supplier_bp.route("/<int:sup_id>/loans/<int:loan_id>/delete", methods=["POST"])
def supplier_loan_delete(sup_id, loan_id):
    db = _get_db()
    try:
        loan = db.execute("SELECT * FROM supplier_loans WHERE id=? AND supplier_id=?", (loan_id, sup_id)).fetchone()
        if not loan:
            flash(f"Loan #{loan_id} not found.", "error")
            return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="loans"))

        # Delete all duplicate entries with same date/amount/notes (edit bug created copies)
        result = db.execute(
            "DELETE FROM supplier_loans WHERE supplier_id=? AND entry_date=? AND amount=? AND notes=?",
            (sup_id, loan["entry_date"], loan["amount"], loan["notes"]),
        )
        total = result.cursor.rowcount
        db.commit()
        flash(f"{total} loan entr{'y' if total == 1 else 'ies'} deleted.", "info")
    except Exception as e:
        try: db.rollback()
        except: pass
        flash(f"Delete error: {e}", "error")
    return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="loans"))

csrf.exempt(supplier_loan_delete)


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

    return render_template(
        "supplier/loans_list.html",
        s=s,
        loans=loans,
        total_given=total_given,
        total_recovered=total_recovered,
        net=total_given - total_recovered,
    )


# ═══════════════════════════════════════════════════════════
# SOA (Statement of Account)
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/<int:sup_id>/soa")
def supplier_soa(sup_id):
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


    return render_template(
        "supplier/kata.html",
        s=s,
        ledger=ledger,
        total_credit=total_credit,
        total_debit=total_debit,
        closing=closing,
    )


@supplier_bp.route("/<int:sup_id>/soa/pdf")
def supplier_soa_pdf(sup_id):
    _ensure_tables()
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from io import BytesIO
    import tempfile, os, base64

    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))
    company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()

    ledger = []
    for inv in db.execute(
        "SELECT id, invoice_date as dt, invoice_no as ref, total_amount as amt, status FROM supplier_invoices WHERE supplier_id = ?",
        (sup_id,),
    ).fetchall():
        ledger.append({"date": inv["dt"], "type": "Invoice", "ref": inv["ref"], "dr": 0, "cr": inv["amt"]})
    for exp in db.execute(
        "SELECT id, expense_date as dt, category as ref, amount as amt, earning_type FROM supplier_expenses WHERE supplier_id = ?",
        (sup_id,),
    ).fetchall():
        ledger.append({"date": exp["dt"], "type": "Expense", "ref": exp["ref"], "dr": 0, "cr": exp["amt"]})
    for pay in db.execute(
        "SELECT id, payment_date as dt, payment_method as ref, amount as amt FROM supplier_payment_records WHERE supplier_id = ?",
        (sup_id,),
    ).fetchall():
        ledger.append({"date": pay["dt"], "type": "Payment", "ref": pay["ref"], "dr": pay["amt"], "cr": 0})

    ledger.sort(key=lambda x: x["date"])
    running = 0
    for row in ledger:
        running += row["cr"] - row["dr"]
        row["bal"] = round(running, 2)
    db.close()

    total_cr = sum(r["cr"] for r in ledger)
    total_dr = sum(r["dr"] for r in ledger)
    closing = round(total_cr - total_dr, 2)

    _logo_tmp_files = []
    buf = BytesIO()
    LM, RM, TM, BM = 18*mm, 18*mm, 15*mm, 15*mm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM

    tc = company["theme_color"] or "#1a3a5c" if company else "#1a3a5c"
    try: TH = colors.HexColor(tc)
    except: TH = colors.HexColor("#1a3a5c")
    BG = colors.HexColor("#f4f6f9"); WH = colors.white; C3 = colors.HexColor("#d1d5db")
    C4 = colors.HexColor("#111827"); C5 = colors.HexColor("#6b7280")

    def F(name, **kw):
        kw.setdefault("fontSize", 8); kw.setdefault("leading", 12)
        return ParagraphStyle(name, **kw)

    def C(t, **kw):
        kw.setdefault("alignment", TA_CENTER)
        return Paragraph(str(t), F("_C", **kw))
    def R(t, **kw):
        kw.setdefault("alignment", TA_RIGHT)
        return Paragraph(str(t), F("_R", **kw))
    def L(t, **kw):
        kw.setdefault("textColor", C5)
        return Paragraph(str(t), F("_L", **kw))

    els = []
    cn = company["company_name"] if company else "COMPANY"
    trn = company["trn_no"] or "—" if company else "—"

    logo = None; LW = 0
    if company and company["logo_data"]:
        try:
            lb = base64.b64decode(company["logo_data"])
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            f.write(lb); f.close()
            logo = Image(f.name, width=50, height=50)
            LW = 50
            _logo_tmp_files.append(f.name)
        except: pass

    cl = [f"<font size=11><b>{cn}</b></font>"]
    addr = company["address"] or ""; ph = company["phone_number"] or ""; em = company["email"] or ""
    parts = [x for x in [addr] if x]
    cparts = [x for x in [ph, em, f"TRN: {trn}"] if x and x != f"TRN: —"]
    if parts or cparts:
        info = " &middot; ".join(parts + cparts)
        cl.append(f"<font size=6.5 color='#6b7280'>{info}</font>")
    co_p = Paragraph("<br/>".join(cl), F("CO", fontSize=11, fontName="Helvetica-Bold", textColor=TH, leading=13))
    if logo:
        lh = Table([[logo, Spacer(1, 3*mm), co_p]], colWidths=[LW, 3*mm, W*0.65 - LW - 3*mm])
        lh.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    else:
        lh = co_p
    rh = Paragraph(
        f"<b>STATEMENT<br/>OF ACCOUNT</b>",
        F("TI", fontSize=14, fontName="Helvetica-Bold", textColor=TH, leading=18, alignment=TA_RIGHT))
    ht = Table([[lh, rh]], colWidths=[W*0.65, W*0.35])
    ht.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ht)
    els.append(Spacer(1, 2*mm))
    hr = Table([[""]], colWidths=[W], rowHeights=[2])
    hr.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(hr)
    els.append(Spacer(1, 4*mm))

    # ── Supplier Info ──
    sinfo = [
        [Paragraph("<b>Supplier</b>", F("_cl", fontSize=8, fontName="Helvetica-Bold", textColor=C4, leading=11)),
         Paragraph(f"<b>{s['supplier_name']}</b>", F("_cv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=12))],
    ]
    if s["trn"]: sinfo.append([Paragraph("TRN", F("_l", fontSize=7.5, textColor=C5, leading=10)), Paragraph(s["trn"], F("_v", fontSize=8.5, textColor=C4, leading=11))])
    if s["address"]: sinfo.append([Paragraph("Address", F("_l", fontSize=7.5, textColor=C5, leading=10)), Paragraph(s["address"], F("_v", fontSize=8.5, textColor=C4, leading=11))])
    if s["phone"]: sinfo.append([Paragraph("Phone", F("_l", fontSize=7.5, textColor=C5, leading=10)), Paragraph(s["phone"], F("_v", fontSize=8.5, textColor=C4, leading=11))])
    st_info = Table(sinfo, colWidths=[50, W - 50])
    st_info.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(st_info)

    # ── Summary ──
    els.append(Spacer(1, 3*mm))
    sdata = [[
        Paragraph(f"<b>Total Credited (Owed)</b><br/><font size=10 color='#e65100'>AED {total_cr:,.2f}</font>", F("_s1", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Total Paid</b><br/><font size=10 color='#1a7d1a'>AED {total_dr:,.2f}</font>", F("_s2", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Balance</b><br/><font size=10 color='#c62828'>AED {closing if closing > 0 else 0:,.2f}</font>", F("_s3", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Transactions</b><br/><font size=10>{len(ledger)}</font>", F("_s4", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
    ]]
    st_sum = Table(sdata, colWidths=[W/4, W/4, W/4, W/4])
    st_sum.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5),
        ("BACKGROUND",(0,0),(-1,-1),BG),
    ]))
    els.append(st_sum)
    els.append(Spacer(1, 3*mm))

    # ── Statement Table ──
    colw = [50, 65, W - 50 - 65 - 65 - 75, 65, 75]
    hdr = [
        Paragraph("<b>Date</b>", F("_h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=10)),
        Paragraph("<b>Description</b>", F("_h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, leading=10)),
        Paragraph("<b>Dr (AED)</b>", F("_h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        Paragraph("<b>Cr (AED)</b>", F("_h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        Paragraph("<b>Balance (AED)</b>", F("_h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
    ]
    rws = [hdr]
    rws.append([
        Paragraph("", F("_o", fontSize=7, leading=10)),
        Paragraph("Opening Balance", F("_ol", fontSize=7, textColor=C5, leading=10)),
        Paragraph("", F("_o")), Paragraph("", F("_o")),
        Paragraph("<b>0.00</b>", F("_ob", fontSize=7, fontName="Helvetica-Bold", textColor=C4, alignment=TA_RIGHT, leading=10)),
    ])
    for e in ledger:
        bal_val = e.get("bal",0) or 0
        bal_display = "0.00" if bal_val <= 0 else f"{bal_val:,.2f}"
        bal_color = "#e65100" if bal_val > 0 else "#1a7d1a"
        rws.append([
            Paragraph(str(e["date"]), F("_d", fontSize=7, leading=10)),
            Paragraph(f"{e['type']}: {e['ref']}", F("_r", fontSize=7, textColor=C4, leading=10)),
            Paragraph(f"<b>{e['dr']:,.2f}</b>" if e['dr'] else '<font color="#ccc">—</font>', F("_dr", fontSize=7, textColor="#1a7d1a" if e['dr'] else C5, alignment=TA_RIGHT, leading=10)),
            Paragraph(f"<b>{e['cr']:,.2f}</b>" if e['cr'] else '<font color="#ccc">—</font>', F("_cr", fontSize=7, textColor="#e65100" if e['cr'] else C5, alignment=TA_RIGHT, leading=10)),
            Paragraph(f"<b>{bal_display}</b>", F("_bl", fontSize=7, fontName="Helvetica-Bold", textColor=bal_color, alignment=TA_RIGHT, leading=10)),
        ])
    rws.append([
        Paragraph("<b>Closing Balance</b>", F("_cb", fontSize=8, fontName="Helvetica-Bold", textColor=WH, leading=11)),
        Paragraph("", F("_x", fontSize=7, leading=10)),
        Paragraph(f"<b>{total_dr:,.2f}</b>", F("_cd", fontSize=8, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=11)),
        Paragraph(f"<b>{total_cr:,.2f}</b>", F("_cc", fontSize=8, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=11)),
        Paragraph(f"<b>{(closing if closing > 0 else 0):,.2f}</b>", F("_ccl", fontSize=8, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=11)),
    ])
    it = Table(rws, colWidths=colw, repeatRows=1)
    it.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BACKGROUND",(0,0),(-1,0),TH), ("TEXTCOLOR",(0,0),(-1,0),WH),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),2), ("BOTTOMPADDING",(0,0),(-1,-1),2),
        ("LEFTPADDING",(0,0),(-1,-1),3), ("RIGHTPADDING",(0,0),(-1,-1),3),
        ("BACKGROUND",(0,-1),(-1,-1),TH), ("TEXTCOLOR",(0,-1),(-1,-1),WH),
        ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
        ("ROWBACKGROUNDS",(0,1),(-2,-2),[WH, BG]),
    ]))
    els.append(it)

    # ── Signatures ──
    els.append(Spacer(1, 8*mm))
    s_sg = ParagraphStyle("SSG", fontSize=9, alignment=TA_CENTER, leading=14)
    s_stamp_path = os.path.join(current_app.root_path, 'static', 'Stamp.png')
    s_sign_path = os.path.join(current_app.root_path, 'static', 'Sign (1).png')
    s_auth_cells = []
    s_auth_cells.append(Paragraph("_________________________", s_sg))
    if os.path.exists(s_stamp_path):
        s_auth_cells.append(Image(s_stamp_path, width=40, height=40))
    if os.path.exists(s_sign_path):
        s_auth_cells.append(Image(s_sign_path, width=40, height=40))
    s_auth_cells.append(Paragraph("<b>Authorized Signatory</b>", s_sg))
    s_auth_cell = Table([[c] for c in s_auth_cells], colWidths=[W*0.35])
    s_auth_cell.setStyle(TableStyle([
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),0),
        ("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))
    soa_sig = Table([[
        s_auth_cell,
        C("", fontSize=4),
        Paragraph("", s_sg),
    ]], colWidths=[W*0.35, W*0.30, W*0.35])
    soa_sig.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LINEABOVE",(0,0),(0,0),0.5,C5), ("LINEABOVE",(2,0),(2,0),0.5,C5),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
    ]))
    els.append(soa_sig)

    # ── Footer ──
    els.append(Spacer(1, 8*mm))
    fh = Table([[""]], colWidths=[W], rowHeights=[0.5])
    fh.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(fh)
    els.append(Spacer(1, 2*mm))
    ft_txt = "This is a computer-generated Statement of Account."
    els.append(Paragraph(f"<font size=7 color='#6b7280'>{ft_txt}</font>", F("_ft", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=9)))

    doc.build(els)
    for fp in _logo_tmp_files:
        try: os.unlink(fp)
        except: pass
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=f"SOA_{s['supplier_code'] or sup_id}.pdf")


# ═══════════════════════════════════════════════════════════
# DELETE
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/bulk-delete", methods=["POST"])
def supplier_bulk_delete():
    _ensure_tables()
    raw = request.form.getlist("selected_ids")
    ids = [int(x) for x in raw if x.isdigit()]
    if not ids:
        flash("No suppliers selected.", "error")
        return redirect(url_for("supplier.supplier_list"))
    db = _get_db()
    placeholders = ",".join("?" * len(ids))
    db.execute(f"UPDATE suppliers SET is_deleted=1, status='Deleted' WHERE id IN ({placeholders})", ids)
    db.commit()
    flash(f"{len(ids)} supplier(s) moved to trash.", "info")
    return redirect(url_for("supplier.supplier_list"))

@supplier_bp.route("/<int:sup_id>/delete", methods=["POST"])
def supplier_delete(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        flash("Supplier not found.", "error")
    else:
        db.execute("UPDATE suppliers SET is_deleted=1, status='Deleted' WHERE id = ?", (sup_id,))
        db.commit()
        flash(f"Supplier {s['supplier_name']} moved to trash.", "info")
    return redirect(url_for("supplier.supplier_list"))

@supplier_bp.route("/<int:sup_id>/restore", methods=["POST"])
def supplier_restore(sup_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    if not s:
        flash("Supplier not found.", "error")
    else:
        db.execute("UPDATE suppliers SET is_deleted=0, status='Active' WHERE id = ?", (sup_id,))
        db.commit()
        flash(f"Supplier {s['supplier_name']} restored.", "success")
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

        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_list"))
    docs = db.execute(
        "SELECT * FROM supplier_documents WHERE supplier_id = ? ORDER BY created_at DESC",
        (sup_id,),
    ).fetchall()

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

        flash("Document uploaded.", "success")
        return redirect(url_for("supplier.supplier_doc_list", sup_id=sup_id))


    return render_template("supplier/doc_form.html", s=s, doc={}, doc_types=DOC_TYPES)


@supplier_bp.route("/<int:sup_id>/documents/<int:doc_id>/download")
def supplier_doc_download(sup_id, doc_id):
    _ensure_tables()
    db = _get_db()
    doc = db.execute("SELECT * FROM supplier_documents WHERE id=? AND supplier_id=?", (doc_id, sup_id)).fetchone()

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

    flash("Document deleted.", "info")
    return redirect(url_for("supplier.supplier_doc_list", sup_id=sup_id))


@supplier_bp.route("/purchase-report")
def supplier_purchase_report():
    _ensure_tables()
    db = _get_db()
    from_filter = request.args.get("from", "")
    to_filter = request.args.get("to", "")
    where = ""
    params = []
    if from_filter:
        where += " AND i.invoice_date >= ?"
        params.append(from_filter)
    if to_filter:
        where += " AND i.invoice_date <= ?"
        params.append(to_filter)
    invoices = db.execute(f"""
        SELECT i.invoice_date, i.invoice_no, s.supplier_name,
               i.amount AS net_sale, i.vat_amount, i.total_amount
        FROM supplier_invoices i
        JOIN suppliers s ON s.id = i.supplier_id
        WHERE 1=1 {where}
        ORDER BY i.invoice_date DESC, i.invoice_no DESC
    """, params).fetchall()
    total_net = sum(r["net_sale"] for r in invoices)
    total_vat = sum(r["vat_amount"] for r in invoices)
    total_gross = sum(r["total_amount"] for r in invoices)
    db.close()
    return render_template(
        "supplier/purchase_report.html",
        invoices=invoices,
        total_net=total_net,
        total_vat=total_vat,
        total_gross=total_gross,
        from_filter=from_filter,
        to_filter=to_filter,
    )
