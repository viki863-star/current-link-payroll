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
from ..routes import _next_reference_code


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
            earning_type TEXT DEFAULT 'fixed',
            quantity {real_type},
            rate {real_type},
            vehicle_no TEXT,
            fund_source TEXT DEFAULT 'cash_bank',
            status TEXT NOT NULL DEFAULT 'pending',
            payment_date TEXT,
            payment_method TEXT,
            payment_ref TEXT,
            approved_by TEXT,
            approved_at TEXT,
            created_at TEXT NOT NULL DEFAULT {now_val},
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );

        CREATE TABLE IF NOT EXISTS supplier_payment_records (
            {id_col},
            supplier_id INTEGER NOT NULL,
            invoice_id INTEGER,
            invoice_ids TEXT,
            expense_ids TEXT,
            fund_source TEXT DEFAULT 'cash_bank',
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
        CREATE TABLE IF NOT EXISTS supplier_bills (
            {id_col},
            supplier_id INTEGER NOT NULL,
            vehicle_plate TEXT NOT NULL,
            bill_no TEXT NOT NULL,
            bill_date TEXT NOT NULL,
            description TEXT,
            total_amount {real_type} NOT NULL,
            vat_percentage {real_type} DEFAULT 0,
            vat_amount {real_type} DEFAULT 0,
            discount {real_type} DEFAULT 0,
            net_amount {real_type} NOT NULL,
            source_expense_id INTEGER,
            created_at TEXT NOT NULL DEFAULT {now_val},
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );

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

    # Migrate vat columns to supplier_bills
    for col, dtype in [("vat_percentage", f"{real_type} DEFAULT 0"), ("vat_amount", f"{real_type} DEFAULT 0")]:
        try:
            db.execute(f"ALTER TABLE supplier_bills ADD COLUMN {col} {dtype}")
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

    for col, dtype in [("cheque_number", "TEXT"), ("cheque_date", "TEXT")]:
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

    for col, dtype in [("discount", "REAL DEFAULT 0")]:
        try:
            db.execute(f"ALTER TABLE supplier_payment_records ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    for col, dtype in [("fund_source", "TEXT DEFAULT 'cash_bank'"), ("bank_name", "TEXT"), ("cheque_drawer", "TEXT")]:
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

    for col, dtype in [("is_tax_bill", "INTEGER DEFAULT 0")]:
        try:
            db.execute(f"ALTER TABLE supplier_expenses ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    # Convert ALL bill-linked expenses to show as Invoice in profile
    try:
        db.execute(
            """UPDATE supplier_expenses
               SET earning_type='invoice', is_tax_bill=1, amount=(
                   SELECT b.total_amount FROM supplier_bills b WHERE b.source_expense_id=supplier_expenses.id
               )
               WHERE id IN (
                   SELECT source_expense_id FROM supplier_bills
                   WHERE source_expense_id IS NOT NULL
               ) AND earning_type != 'invoice'"""
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    for col, dtype in [("fund_source", "TEXT DEFAULT 'cash_bank'"), ("bank_name", "TEXT"), ("cheque_drawer", "TEXT")]:
        try:
            db.execute(f"ALTER TABLE supplier_loans ADD COLUMN {col} {dtype}")
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    for col, dtype in [("location", "TEXT"), ("contact_details", "TEXT")]:
        try:
            db.execute(f"ALTER TABLE supplier_quotations ADD COLUMN {col} {dtype}")
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
        from ..routes import _touch_admin_workspace
        _touch_admin_workspace("suppliers")
        db = _get_db()

        suppliers = db.execute("SELECT * FROM suppliers ORDER BY supplier_name").fetchall()
        total = len(suppliers)
        active = sum(1 for s in suppliers if s["status"] == "Active")
        with_inv = sum(1 for s in suppliers if s["supplier_type"] == "with_invoice")
        without_inv = sum(1 for s in suppliers if s["supplier_type"] == "without_invoice")

        total_invoiced = db.execute(
            "SELECT COALESCE(SUM(total_amount),0) FROM supplier_invoices"
        ).fetchone()[0] or 0

        total_outstanding = db.execute(
            "SELECT COALESCE(SUM(total_amount),0) FROM supplier_invoices WHERE status IN ('pending','approved')"
        ).fetchone()[0] or 0

        paid_total = db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM supplier_payment_records"
        ).fetchone()[0] or 0

        inv_count = db.execute(
            "SELECT COUNT(*) FROM supplier_invoices"
        ).fetchone()[0]

        recent_invoices = db.execute(
            """SELECT si.*, s.supplier_name FROM supplier_invoices si
               JOIN suppliers s ON s.id = si.supplier_id
               ORDER BY si.created_at DESC LIMIT 8"""
        ).fetchall()

        recent_payments = db.execute(
            """SELECT p.*, s.supplier_name FROM supplier_payment_records p
               JOIN suppliers s ON p.supplier_id = s.id
               ORDER BY p.created_at DESC LIMIT 6"""
        ).fetchall()

        monthly_trend = db.execute("""
            SELECT substr(invoice_date,1,7) AS mon,
                   COUNT(*) AS cnt, COALESCE(SUM(total_amount),0) AS tot
            FROM supplier_invoices GROUP BY mon ORDER BY mon DESC LIMIT 12
        """).fetchall()

        top_suppliers = db.execute("""
            SELECT s.id, s.supplier_name, COUNT(si.id) AS inv_cnt,
                   COALESCE(SUM(si.total_amount),0) AS total
            FROM suppliers s
            LEFT JOIN supplier_invoices si ON si.supplier_id = s.id
            GROUP BY s.id, s.supplier_name ORDER BY total DESC LIMIT 5
        """).fetchall()

        return render_template(
            "supplier/dashboard.html",
            total=total,
            active=active,
            with_invoice_count=with_inv,
            without_invoice_count=without_inv,
            total_invoiced=total_invoiced,
            total_outstanding=total_outstanding,
            paid_total=paid_total,
            inv_count=inv_count,
            recent_invoices=recent_invoices,
            recent_payments=recent_payments,
            monthly_trend=monthly_trend,
            top_suppliers=top_suppliers,
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
    status_filter = request.args.get("status", "").strip().lower()
    sql = "SELECT * FROM suppliers"
    params = []
    conditions = []
    if status_filter == "blocked":
        conditions.append("COALESCE(is_deleted,0) = 0 AND status = 'Inactive'")
    elif status_filter == "deleted":
        conditions.append("COALESCE(is_deleted,0) = 1")
    else:
        conditions.append("COALESCE(is_deleted,0) = 0 AND status = 'Active'")
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

    return render_template("supplier/list.html", suppliers=suppliers, q=q, typ=typ, status_filter=status_filter)


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
    dl = request.args.get("download", "0") == "1"
    return send_file(
        BytesIO(data),
        mimetype=inv["attachment_type"] or "application/octet-stream",
        as_attachment=dl,
        download_name=inv["attachment_name"] or f"invoice_{inv_id}",
    )


@supplier_bp.route("/expenses/<int:exp_id>/attachment")
def supplier_expense_attachment(exp_id):
    db = _get_db()
    exp = db.execute("SELECT * FROM supplier_expenses WHERE id = ?", (exp_id,)).fetchone()

    if not exp or not exp["receipt_data"]:
        flash("Attachment not found.", "error")
        return redirect(url_for("supplier.supplier_dashboard"))
    data = base64.b64decode(exp["receipt_data"])
    dl = request.args.get("download", "0") == "1"
    return send_file(
        BytesIO(data),
        mimetype=exp["receipt_type"] or "application/octet-stream",
        as_attachment=dl,
        download_name=exp["receipt_name"] or f"expense_{exp_id}",
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
    ("daily", "Daily"),
    ("weekly", "Weekly"),
    ("monthly", "Monthly"),
    ("kg", "Kg"),
    ("gallon", "Gallon"),
    ("lump", "Lump Sum"),
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
    suggested_lpo = _next_reference_code(db, "supplier_lpos", "lpo_no", "LPO")

    return render_template("supplier/lpo_form.html", s=s, company=company, lpo={}, lpo_types=LPO_TYPES, quotations=quotations, qitems=[], suggested_lpo=suggested_lpo)


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
    return redirect(url_for("supplier.supplier_lpo_list", sup_id=sup_id))


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
    from datetime import datetime

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
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=1.2*cm, bottomMargin=1.2*cm)
    avail_w = A4[0] - 3.6*cm

    NAVY = colors.HexColor("#1a3a5c")
    LINE = colors.HexColor("#dce1e8")
    MUTED = colors.HexColor("#8896a8")
    DARK = colors.HexColor("#1e293b")
    ACCENT = colors.HexColor("#2563eb")
    LIGHT_BG = colors.HexColor("#f8f9fb")
    WHITE = colors.white

    type_labels = dict(LPO_TYPES)
    lpo_type_str = type_labels.get(lpo["lpo_type"], lpo["lpo_type"] or "Fixed Amount")
    basis_labels = {"trip": "Trip", "hour": "Hour", "daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "kg": "Kg", "gallon": "Gallon", "lump": "Lump Sum", "fixed": "Fixed", "other": "Other"}
    total_amt = lpo["amount"] or 0

    cn = (company["company_name"] if company else "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING") or "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING"
    c_addr = (company["address"] if company else "") or ""
    c_trn = (company["trn_no"] if company else "XXXXXXXXXX") or "XXXXXXXXXX"
    c_ph = (company["phone_number"] if company else "") or ""
    c_em = (company["email"] if company else "") or ""

    logo_img = None
    if company and company.get("logo_data"):
        try:
            logo_img = RLImage(BytesIO(base64.b64decode(company["logo_data"])), width=20*mm, height=20*mm)
        except Exception:
            logo_img = None

    els = []

    # ═══════════════════════════════════════════════════════
    #  HEADER
    # ═══════════════════════════════════════════════════════
    company_info = "<font size=11><b>" + cn + "</b></font>"
    addr_parts = []
    if c_addr: addr_parts.append(c_addr)
    if c_ph: addr_parts.append("Tel: " + c_ph)
    if c_em: addr_parts.append(c_em)
    if addr_parts:
        company_info += "<br/><font size=7 color='#556b82'>" + " | ".join(addr_parts) + "</font>"
    company_info += "<br/><font size=7 color='#556b82'><b>TRN:</b> " + c_trn + "</font>"

    title_block = (
        "<font size=18 color='#1a3a5c'><b>LOCAL PURCHASE ORDER</b></font><br/>"
        "<font size=7 color='#8896a8'>LPO NO:  </font>"
        "<font size=11 color='#1a3a5c'><b>" + lpo['lpo_no'] + "</b></font>"
    )

    if logo_img:
        hdr_data = [[logo_img, Paragraph(company_info, ParagraphStyle("ci", fontSize=9, leading=12, textColor=DARK)),
                     Paragraph(title_block, ParagraphStyle("tb", alignment=TA_RIGHT, leading=20))]]
        hdr_tbl = Table(hdr_data, colWidths=[20*mm, None, 75*mm])
    else:
        hdr_data = [[Paragraph(company_info, ParagraphStyle("ci", fontSize=9, leading=12, textColor=DARK)),
                     Paragraph(title_block, ParagraphStyle("tb", alignment=TA_RIGHT, leading=20))]]
        hdr_tbl = Table(hdr_data, colWidths=[None, 75*mm])
    hdr_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 2.5, NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(hdr_tbl)
    els.append(Spacer(1, 3.5*mm))

    # ═══════════════════════════════════════════════════════
    #  TWO-COLUMN INFO SECTION
    # ═══════════════════════════════════════════════════════
    lbl_style = ParagraphStyle("lbl", fontSize=6.5, textColor=MUTED, leading=8, spaceAfter=0)
    val_style = ParagraphStyle("val", fontSize=9, textColor=DARK, leading=12, spaceAfter=2)

    # Left column: Supplier details
    sup_lines = [
        Paragraph("<b>SUPPLIER</b>", ParagraphStyle("sh", fontSize=9, fontName="Helvetica-Bold", textColor=NAVY, leading=11, spaceAfter=3)),
        Paragraph("Name", lbl_style), Paragraph(s["supplier_name"], val_style),
    ]
    if s.get("address"): sup_lines += [Paragraph("Address", lbl_style), Paragraph(s["address"], val_style)]
    if s.get("trn"): sup_lines += [Paragraph("TRN", lbl_style), Paragraph(s["trn"], val_style)]
    if s.get("phone"): sup_lines += [Paragraph("Phone", lbl_style), Paragraph(s["phone"], val_style)]
    if s.get("email"): sup_lines += [Paragraph("Email", lbl_style), Paragraph(s["email"], val_style)]
    sup_lines.append(Spacer(1, 1*mm))
    if s.get("payment_terms"):
        sup_lines += [Paragraph("Payment Terms", lbl_style), Paragraph(s["payment_terms"], val_style)]

    sup_cell = Table([[x] for x in sup_lines], colWidths=[None])
    sup_cell.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    # Right column: LPO details
    lpo_lines = [
        Paragraph("<b>LPO DETAILS</b>", ParagraphStyle("sh", fontSize=9, fontName="Helvetica-Bold", textColor=NAVY, leading=11, spaceAfter=3)),
        Paragraph("LPO No", lbl_style), Paragraph(lpo["lpo_no"], val_style),
        Paragraph("Date", lbl_style), Paragraph(lpo["lpo_date"], val_style),
        Paragraph("Basis / Type", lbl_style), Paragraph(lpo_type_str, val_style),
    ]
    if quotation:
        lpo_lines += [Paragraph("Quotation Ref", lbl_style),
                      Paragraph(quotation["quotation_no"], val_style)]
    lpo_lines += [
        Paragraph("Status", lbl_style),
        Paragraph("<font color='#c2410c'><b>" + lpo["status"].upper() + "</b></font>",
                   ParagraphStyle("sv", fontSize=9, leading=12, spaceAfter=2)),
    ]
    lpo_cell = Table([[x] for x in lpo_lines], colWidths=[None])
    lpo_cell.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    info_tbl = Table([[sup_cell, lpo_cell]], colWidths=[avail_w * 0.48, avail_w * 0.52])
    info_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    els.append(info_tbl)
    els.append(Spacer(1, 4*mm))

    # ═══════════════════════════════════════════════════════
    #  ITEMS TABLE
    # ═══════════════════════════════════════════════════════
    s_sec = ParagraphStyle("sec", fontSize=9, fontName="Helvetica-Bold", textColor=NAVY, leading=11, spaceAfter=4)
    els.append(Paragraph("SERVICE / WORK ITEMS", s_sec))

    col_w = [
        10*mm,   # #
        avail_w - 10*mm - 18*mm - 16*mm - 22*mm - 22*mm,  # Description (remaining)
        18*mm,   # QTY
        16*mm,   # Basis
        22*mm,   # Rate
        22*mm,   # Amount
    ]

    b9 = ParagraphStyle("b9", fontSize=8, fontName="Helvetica-Bold", leading=10, spaceAfter=0, alignment=TA_CENTER)
    b9l = ParagraphStyle("b9l", fontSize=8, fontName="Helvetica-Bold", leading=10, spaceAfter=0)
    c9 = ParagraphStyle("c9", fontSize=8, leading=10, spaceAfter=0)
    c9r = ParagraphStyle("c9r", fontSize=8, leading=10, spaceAfter=0, alignment=TA_RIGHT)

    i_hdr = [
        Paragraph("#", b9), Paragraph("Description", ParagraphStyle("b9hl", fontSize=8, fontName="Helvetica-Bold", leading=10, textColor=WHITE, spaceAfter=0)),
        Paragraph("QTY", b9), Paragraph("Basis", ParagraphStyle("b9h", fontSize=8, fontName="Helvetica-Bold", leading=10, textColor=WHITE, spaceAfter=0, alignment=TA_CENTER)),
        Paragraph("Rate (AED)", b9), Paragraph("Amount", b9),
    ]
    i_rows = [i_hdr]
    alt_bg = colors.HexColor("#f4f6f9")
    for idx, it in enumerate(items):
        bg = alt_bg if idx % 2 == 1 else WHITE
        i_rows.append([
            Paragraph(str(idx + 1), ParagraphStyle("cn", fontSize=8, fontName="Helvetica-Bold", leading=10, spaceAfter=0, alignment=TA_CENTER)),
            Paragraph(it["description"], c9),
            Paragraph(str(it["qty"]), b9),
            Paragraph(basis_labels.get(it["basis_type"], it["basis_type"]), ParagraphStyle("cx", fontSize=8, leading=10, spaceAfter=0, alignment=TA_CENTER)),
            Paragraph(f"{it['day_rate'] or 0:,.2f}", c9r),
            Paragraph(f"{it['amount'] or 0:,.2f}", ParagraphStyle("crb", fontSize=8, fontName="Helvetica-Bold", leading=10, spaceAfter=0, alignment=TA_RIGHT)),
        ])

    i_rows.append([
        Paragraph("", c9),
        Paragraph("<b>TOTAL</b>", ParagraphStyle("ttl", fontSize=10, fontName="Helvetica-Bold", alignment=TA_RIGHT, leading=13, textColor=DARK)),
        Paragraph("", c9), Paragraph("", c9), Paragraph("", c9),
        Paragraph(f"<b>{total_amt:,.2f}</b>",
                   ParagraphStyle("ttv", fontSize=11, fontName="Helvetica-Bold", alignment=TA_RIGHT, textColor=NAVY, leading=14)),
    ])

    i_tbl = Table(i_rows, colWidths=col_w, repeatRows=1)
    i_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("INNERGRID", (0, 0), (-1, -2), 0.3, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("BACKGROUND", (0, -1), (-1, -1), LIGHT_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    for idx in range(1, len(i_rows) - 1):
        if idx % 2 == 1:
            i_tbl.setStyle(TableStyle([("BACKGROUND", (0, idx), (-1, idx), alt_bg)]))
    els.append(i_tbl)
    els.append(Spacer(1, 3*mm))

    # ═══════════════════════════════════════════════════════
    #  TOTAL & AMOUNT IN WORDS
    # ═══════════════════════════════════════════════════════
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
            if x < 1000000: return cvt(x//1000) + " Thousand" + (" " + cvt(x%1000) if x%1000 else "")
            return cvt(x//1000000) + " Million" + (" " + cvt(x%1000000) if x%1000000 else "")
        ip = int(n); dp = round((n - ip) * 100)
        w = cvt(ip)
        if dp: w += f" and {dp}/100"
        return "AED " + w + " Only"

    summary_data = [
        [Paragraph("Total Amount (AED)", ParagraphStyle("tsl", fontSize=8, textColor=MUTED, leading=10, spaceAfter=0)),
         Paragraph(f"<b>{total_amt:,.2f}</b>",
                   ParagraphStyle("tsv", fontSize=14, fontName="Helvetica-Bold", alignment=TA_RIGHT, textColor=NAVY, leading=17))],
        [Paragraph("Amount in Words", ParagraphStyle("awl", fontSize=8, textColor=MUTED, leading=10, spaceAfter=0)),
         Paragraph(f"<b>{num_to_words(total_amt)}</b>",
                   ParagraphStyle("awv", fontSize=8.5, textColor=DARK, leading=11, alignment=TA_RIGHT))],
    ]
    summary_tbl = Table(summary_data, colWidths=[avail_w * 0.55, avail_w * 0.45])
    summary_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    els.append(summary_tbl)
    els.append(Spacer(1, 4*mm))

    # ═══════════════════════════════════════════════════════
    #  NOTES / SPECIAL TERMS
    # ═══════════════════════════════════════════════════════
    desc_text = lpo["description"] or ""
    notes_text = lpo["notes"] or ""
    if desc_text or notes_text:
        els.append(Paragraph("NOTES &amp; SPECIAL TERMS", s_sec))
        if desc_text:
            els.append(Paragraph(desc_text, ParagraphStyle("nts", fontSize=8, textColor=DARK, leading=11, spaceAfter=4, leftIndent=4)))
        if notes_text:
            els.append(Paragraph(notes_text, ParagraphStyle("stn", fontSize=8, textColor=DARK, leading=11, spaceAfter=4, leftIndent=4)))
        els.append(Spacer(1, 2*mm))

    # ═══════════════════════════════════════════════════════
    #  STANDARD TERMS & CONDITIONS
    # ═══════════════════════════════════════════════════════
    els.append(Paragraph("TERMS &amp; CONDITIONS", s_sec))
    std_terms = [
        "Payment shall be made as per agreed payment terms mentioned above.",
        "Value Added Tax (VAT) at 5% will be charged separately as per UAE Federal Tax Authority regulations.",
        "This Local Purchase Order is valid for 30 days from the date of issue.",
        "Services / Goods must be delivered in accordance with the specifications and quantities mentioned in this LPO.",
        "Any changes, modifications, or amendments to this LPO shall require prior written confirmation from both parties.",
        "Delivery location and schedule shall be as mutually agreed between the parties.",
        "The supplier shall provide all necessary documentation including valid VAT invoice upon delivery.",
        "Discrepancies or claims regarding this LPO must be raised within 5 working days of receipt.",
    ]
    terms_data = []
    for i, t in enumerate(std_terms):
        terms_data.append([
            Paragraph(f"{i+1}.", ParagraphStyle("tn", fontSize=7.5, textColor=MUTED, leading=10, spaceAfter=1, alignment=TA_RIGHT)),
            Paragraph(t, ParagraphStyle("tt", fontSize=7.5, textColor=DARK, leading=10, spaceAfter=1)),
        ])
    terms_tbl = Table(terms_data, colWidths=[8*mm, avail_w - 8*mm])
    terms_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(terms_tbl)
    els.append(Spacer(1, 6*mm))

    # ═══════════════════════════════════════════════════════
    #  SIGNATURES
    # ═══════════════════════════════════════════════════════
    els.append(Paragraph("AUTHORIZATION", ParagraphStyle("as", fontSize=9, fontName="Helvetica-Bold", textColor=NAVY, leading=11, spaceAfter=4)))

    sig_style = ParagraphStyle("sg", fontSize=8, alignment=TA_CENTER, leading=11, textColor=DARK, spaceAfter=0)

    sig_data = [[
        Table([
            [Spacer(1, 8*mm)],
            [Paragraph("_" * 30, ParagraphStyle("sl", fontSize=8, textColor=MUTED, alignment=TA_CENTER, leading=4))],
            [Paragraph("<b>COMPANY SIGNATURE &amp; STAMP</b>", sig_style)],
            [Paragraph("Name: _______________________", sig_style)],
            [Paragraph("Date: _______________________", sig_style)],
        ], colWidths=[70*mm]),
        Table([
            [Spacer(1, 8*mm)],
            [Paragraph("_" * 30, ParagraphStyle("sl", fontSize=8, textColor=MUTED, alignment=TA_CENTER, leading=4))],
            [Paragraph("<b>SUPPLIER SIGNATURE &amp; STAMP</b>", sig_style)],
            [Paragraph("Name: _______________________", sig_style)],
            [Paragraph("Date: _______________________", sig_style)],
        ], colWidths=[70*mm]),
    ]]
    sig_tbl = Table(sig_data, colWidths=[avail_w * 0.5, avail_w * 0.5])
    sig_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(sig_tbl)
    els.append(Spacer(1, 6*mm))

    # ═══════════════════════════════════════════════════════
    #  FOOTER
    # ═══════════════════════════════════════════════════════
    els.append(Paragraph(
        "This is a computer-generated document and does not require a physical signature for electronic transmission.",
        ParagraphStyle("fot", fontSize=6.5, textColor=MUTED, alignment=TA_CENTER, leading=8)))
    els.append(Paragraph(
        "Generated on: " + datetime.now().strftime("%d-%b-%Y %I:%M %p"),
        ParagraphStyle("gn", fontSize=6, textColor=colors.HexColor("#b0b8c4"), alignment=TA_CENTER, leading=7, spaceAfter=0)))

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
        location = request.form.get("location", "").strip()
        contact_details = request.form.get("contact_details", "").strip()
        description = request.form.get("description", "").strip()
        notes = request.form.get("notes", "").strip()
        if not q_no or not q_date:
            flash("Quotation number and date are required.", "error")
            company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
            return render_template("supplier/quotation_form.html", s=s, company=company, quotation={})

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
            "INSERT INTO supplier_quotations (supplier_id, quotation_no, quotation_date, amount, description, file_data, file_type, notes, location, contact_details) VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id",
            (sup_id, q_no, q_date, 0, description, file_data, file_type, notes, location, contact_details),
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


    company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    return render_template("supplier/quotation_form.html", s=s, company=company, quotation={})


@supplier_bp.route("/<int:sup_id>/quotations/<int:q_id>/items")
def supplier_quotation_items_api(sup_id, q_id):
    _ensure_tables()
    db = _get_db()
    items = db.execute("SELECT * FROM supplier_quotation_items WHERE quotation_id=? ORDER BY sort_order", (q_id,)).fetchall()

    from flask import jsonify
    return jsonify([dict(i) for i in items])


@supplier_bp.route("/<int:sup_id>/quotations/<int:q_id>/download")
@supplier_bp.route("/<int:sup_id>/quotations/<int:q_id>/pdf")
def supplier_quotation_pdf(sup_id, q_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.platypus import Image as RLImage
    from reportlab.lib.units import cm
    from io import BytesIO
    import os, base64

    _ensure_tables()
    db = _get_db()
    q = db.execute("SELECT * FROM supplier_quotations WHERE id=? AND supplier_id=?", (q_id, sup_id)).fetchone()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    items = db.execute("SELECT * FROM supplier_quotation_items WHERE quotation_id=? ORDER BY sort_order", (q_id,)).fetchall()
    try:
        company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    except Exception:
        company = None

    if not q or not s:
        flash("Quotation not found.", "error")
        return redirect(url_for("supplier.supplier_quotation_list", sup_id=sup_id))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm)

    NAVY = colors.HexColor("#1a3a5c")
    LINE = colors.HexColor("#e2e8f0")
    MUTED = colors.HexColor("#94a3b8")
    DARK = colors.HexColor("#0f172a")

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

    basis_labels = {"trip": "Trip", "hour": "Hour", "daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "kg": "Kg", "gallon": "Gallon", "lump": "Lump Sum", "fixed": "Fixed", "other": "Other"}
    total_amt = q["amount"] or 0

    cn = (company["company_name"] if company else "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING") or "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING"
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
        hdr_data = [[logo_img, Paragraph(co_html, s_hdr), Paragraph("QUOTATION<br/><font size=8>#: <b>" + q['quotation_no'] + "</b></font>", s_title)]]
        hdr_tbl = Table(hdr_data, colWidths=[2.2*cm, None, None])
    else:
        hdr_data = [[Paragraph(co_html, s_hdr), Paragraph("QUOTATION<br/><font size=8>#: <b>" + q['quotation_no'] + "</b></font>", s_title)]]
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

    # ── INFO section ──
    els.append(Paragraph("QUOTATION INFORMATION", s_sec))
    info_rows = [
        [Paragraph("Quotation No.", s_info_lbl), Paragraph(q['quotation_no'], s_info),
         Paragraph("Date", s_info_lbl), Paragraph(q['quotation_date'], s_info),
         Paragraph("", s_info_lbl), Paragraph("", s_info)],
        [Paragraph("Supplier", s_info_lbl), Paragraph(s['supplier_name'], s_info),
         Paragraph("Location / Work Site", s_info_lbl), Paragraph(q.get('location') or '—', s_info),
         Paragraph("", s_info_lbl), Paragraph("", s_info)],
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

    # ── SUB TOTAL / VAT / TOTAL ──
    sub_total = total_amt
    vat_pct = 5
    vat_amt = round(sub_total * vat_pct / 100, 2)
    grand_total = round(sub_total + vat_amt, 2)

    s_sm = ParagraphStyle("sm", fontSize=9, alignment=TA_RIGHT, leading=12)
    s_sm_b = ParagraphStyle("smb", fontSize=9, fontName="Helvetica-Bold", alignment=TA_RIGHT, leading=12)
    s_sm_l = ParagraphStyle("sml", fontSize=9, textColor=MUTED, alignment=TA_RIGHT, leading=12)

    totals_rows = [
        [Paragraph("Sub Total", s_sm_l), Paragraph(f"AED {sub_total:,.2f}", s_sm)],
        [Paragraph(f"VAT @ {vat_pct}%", s_sm_l), Paragraph(f"AED {vat_amt:,.2f}", s_sm)],
        [Paragraph("", s_sm), Paragraph("", s_sm)],
        [Paragraph("<b>Total</b>", s_sm_b), Paragraph(f"<b>AED {grand_total:,.2f}</b>", ParagraphStyle("tv2", fontSize=11, fontName="Helvetica-Bold", alignment=TA_RIGHT, textColor=NAVY, leading=14))],
    ]
    totals_tbl = Table(totals_rows, colWidths=[None, 4*cm])
    totals_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LINEBELOW", (0,0), (-1,-2), 0.3, colors.HexColor("#ddd")),
        ("LINEBELOW", (0,-1), (-1,-1), 1.5, NAVY),
        ("TOPPADDING", (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    els.append(totals_tbl)
    els.append(Spacer(1, 2*mm))

    # ── AMOUNT IN WORDS ──
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
            if x < 1000000: return cvt(x//1000) + " Thousand" + (" " + cvt(x%1000) if x%1000 else "")
            return cvt(x//1000000) + " Million" + (" " + cvt(x%1000000) if x%1000000 else "")
        ip = int(n); dp = round((n - ip) * 100)
        w = cvt(ip)
        if dp: w += f" and {dp}/100"
        return "AED " + w + " Only"

    words_p = Paragraph("<b>Amount in Words:</b> " + num_to_words(grand_total), ParagraphStyle("wrds", fontSize=8.5, textColor=colors.HexColor("#64748b"), leading=11))
    words_box = Table([[words_p]], colWidths=[None])
    words_box.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ("BOX", (0,0), (-1,-1), 0.5, LINE),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 8), ("RIGHTPADDING", (0,0), (-1,-1), 8),
    ]))
    els.append(words_box)
    els.append(Spacer(1, 3*mm))

    # ── CONTACT DETAILS & TERMS ──
    contact_text = q.get("contact_details") or ""
    if contact_text:
        els.append(Paragraph("CONTACT DETAILS", s_sec))
        contact_display = "<b>Contact Person:</b> Mr. Nasrullah<br/>" + contact_text
        els.append(Paragraph(contact_display, ParagraphStyle("cnt", fontSize=8, textColor=colors.HexColor("#334155"), leading=11, spaceAfter=4)))

    desc_text = q["description"] or ""
    notes_text = q["notes"] or ""
    if desc_text or notes_text:
        els.append(Paragraph("SCOPE &amp; TERMS", s_sec))
        if desc_text:
            els.append(Paragraph("<b>Scope / Notes</b><br/>" + desc_text, ParagraphStyle("nts", fontSize=8, textColor=colors.HexColor("#334155"), leading=11, spaceAfter=4)))
        if notes_text:
            els.append(Paragraph("<b>Special Terms</b><br/>" + notes_text, ParagraphStyle("stn", fontSize=8, textColor=colors.HexColor("#334155"), leading=11, spaceAfter=4)))

    # ── Standard Terms ──
    els.append(Spacer(1, 2*mm))
    std_terms = [
        "This quotation is valid for 15 days from the date of issue.",
        "VAT @ 5% will be charged separately as per UAE Federal Law.",
        "Payment as per agreed payment terms.",
        "Location of work as mentioned above unless otherwise agreed.",
        "Any changes to scope require a revised quotation.",
    ]
    t_html = "<b>Terms &amp; Conditions</b><br/>" + "<br/>".join([chr(8226) + " " + t for t in std_terms])
    els.append(Paragraph(t_html, ParagraphStyle("st", fontSize=7.5, textColor=colors.HexColor("#64748b"), leading=11, leftIndent=6)))

    # ── AUTHORIZED SIGNATORY ──
    els.append(Spacer(1, 6*mm))
    s_stamp_path = os.path.join(current_app.root_path, 'static', 'Stamp.png')
    s_sign_path = os.path.join(current_app.root_path, 'static', 'Sign (1).png')
    s_auth_cells = []
    s_auth_cells.append(Paragraph("_________________________", s_sign))
    if os.path.exists(s_stamp_path):
        s_auth_cells.append(RLImage(s_stamp_path, width=38, height=38))
    if os.path.exists(s_sign_path):
        s_auth_cells.append(RLImage(s_sign_path, width=38, height=38))
    s_auth_cells.append(Paragraph("<b>Authorized Signatory</b><br/><font size=6>" + cn + "</font>", s_sign))
    s_auth_cell = Table([[c] for c in s_auth_cells], colWidths=[5*cm])
    s_auth_cell.setStyle(TableStyle([
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    sig_tbl = Table([[
        s_auth_cell,
        Paragraph("", s_sign),
        Paragraph("_________________________<br/><b>Customer Sign &amp; Stamp</b><br/><font size=7>Date: _____/_____/_____</font>", s_sign),
    ]], colWidths=[5*cm, 2*cm, 5*cm])
    sig_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    els.append(sig_tbl)

    # ── FOOTER ──
    els.append(Spacer(1, 4*mm))
    els.append(Paragraph("This is a computer-generated quotation. No signature required for electronic transmission.", s_foot))
    els.append(Paragraph("Generated on: " + datetime.now().strftime("%d-%b-%Y %H:%M"), ParagraphStyle("gn", fontSize=6, textColor=colors.HexColor("#aaa"), alignment=TA_CENTER, leading=8, spaceAfter=0)))

    doc.build(els)
    pdf_data = buf.getvalue()
    buf.close()

    return send_file(
        BytesIO(pdf_data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"Quotation_{q['quotation_no']}.pdf",
    )


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

        try:
            receipt_name = exp["receipt_name"]
            receipt_data = exp["receipt_data"]
            receipt_type = exp["receipt_type"]
        except Exception:
            receipt_name = receipt_data = receipt_type = None
        if "receipt" in request.files:
            file = request.files["receipt"]
            if file.filename:
                receipt_name = file.filename
                receipt_data = base64.b64encode(file.read()).decode("utf-8")
                receipt_type = file.content_type

        db.execute(
            "UPDATE supplier_expenses SET expense_date=?, amount=?, category=?, description=?, earning_type=?, quantity=?, rate=?, vehicle_no=?, receipt_name=?, receipt_data=?, receipt_type=? WHERE id=?",
            (expense_date, amount, category, description, earning_type, qty_f, rate_f, vehicle_no or None, receipt_name, receipt_data, receipt_type, exp_id),
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

    unpaid_expenses = db.execute(
        "SELECT id, description, amount, category, earning_type FROM supplier_expenses WHERE supplier_id = ? AND status IN ('pending','approved') ORDER BY expense_date",
        (sup_id,),
    ).fetchall()

    if request.method == "POST":
        payment_date = request.form.get("payment_date", "").strip() or date.today().isoformat()
        amount = request.form.get("amount", "").strip()
        invoice_ids = request.form.getlist("invoice_ids")
        expense_ids = request.form.getlist("expense_ids")
        payment_method = request.form.get("payment_method", "Cash").strip()
        reference_no = request.form.get("reference_no", "").strip()
        notes = request.form.get("notes", "").strip()
        cheque_number = request.form.get("cheque_number", "").strip()
        cheque_date = request.form.get("cheque_date", "").strip()

        if not amount:
            flash("Payment amount is required.", "error")
            return render_template("supplier/payment_form.html", s=s, pay={}, invoices=unpaid, expenses=unpaid_expenses, methods=PAYMENT_METHODS, today=date.today().isoformat())

        if not notes:
            flash("Details / description is required for this payment.", "error")
            return render_template("supplier/payment_form.html", s=s, pay={}, invoices=unpaid, expenses=unpaid_expenses, methods=PAYMENT_METHODS, today=date.today().isoformat())

        amount_f = float(amount)
        fund_source = request.form.get("fund_source", "cash_bank").strip()
        invoice_ids_str = ",".join(invoice_ids)
        expense_ids_str = ",".join(expense_ids)

        # Ensure columns exist
        for col,dtype in [("invoice_ids","TEXT"),("fund_source","TEXT DEFAULT 'cash_bank'"),("expense_ids","TEXT"),("cheque_number","TEXT"),("cheque_date","TEXT")]:
            try:
                db.execute(f"ALTER TABLE supplier_payment_records ADD COLUMN {col} {dtype}")
                db.commit()
            except:
                try: db.rollback()
                except: pass
        for col,dtype in [("discount","REAL DEFAULT 0")]:
            try:
                db.execute(f"ALTER TABLE supplier_payment_records ADD COLUMN {col} {dtype}")
                db.commit()
            except:
                try: db.rollback()
                except: pass
        for col,dtype in [("payment_date","TEXT"),("payment_method","TEXT"),("payment_ref","TEXT")]:
            try:
                db.execute(f"ALTER TABLE supplier_expenses ADD COLUMN {col} {dtype}")
                db.commit()
            except:
                try: db.rollback()
                except: pass

        discount = request.form.get("discount", "0").strip()
        discount_f = float(discount) if discount else 0

        # Create one payment record for the batch
        db.execute(
            "INSERT INTO supplier_payment_records (supplier_id, invoice_id, invoice_ids, expense_ids, payment_date, amount, payment_method, reference_no, notes, fund_source, cheque_number, cheque_date, discount) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sup_id, None, invoice_ids_str, expense_ids_str, payment_date, amount_f, payment_method, reference_no, notes, fund_source, cheque_number or None, cheque_date or None, discount_f),
        )

        # Mark all selected invoices as paid
        for inv_id_str in invoice_ids:
            inv_id = int(inv_id_str.strip()) if inv_id_str.strip().isdigit() else None
            if inv_id:
                db.execute(
                    "UPDATE supplier_invoices SET status='paid', payment_date=?, payment_method=?, payment_ref=? WHERE id=?",
                    (payment_date, payment_method, reference_no, inv_id),
                )

        # Mark all selected expenses as paid
        for exp_id_str in expense_ids:
            exp_id = int(exp_id_str.strip()) if exp_id_str.strip().isdigit() else None
            if exp_id:
                db.execute(
                    "UPDATE supplier_expenses SET status='paid', payment_date=?, payment_method=?, payment_ref=? WHERE id=?",
                    (payment_date, payment_method, reference_no, exp_id),
                )

        db.commit()

        inv_count = len(invoice_ids)
        exp_count = len(expense_ids)
        parts = []
        if inv_count: parts.append(f"{inv_count} invoice(s)")
        if exp_count: parts.append(f"{exp_count} earning(s)")
        flash(f"Payment of AED {amount_f:.2f} recorded against {' and '.join(parts)}.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="payments"))


    return render_template("supplier/payment_form.html", s=s, pay={}, invoices=unpaid, expenses=unpaid_expenses, methods=PAYMENT_METHODS, today=date.today().isoformat())


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
    expense_rows = []
    if pay.get("expense_ids"):
        ids = [x.strip() for x in pay["expense_ids"].split(",") if x.strip().isdigit()]
        if ids:
            placeholders = ",".join("?" * len(ids))
            expense_rows = db.execute(
                f"SELECT id, description, amount, earning_type, category FROM supplier_expenses WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
    try:
        company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    except Exception:
        company = None
    return render_template("supplier/payment_voucher.html", s=s, pay=pay, inv=inv, invoices=invoices, expense_rows=expense_rows, company=company, today=date.today().isoformat())


@supplier_bp.route("/<int:sup_id>/payments/<int:pay_id>/cheque")
def supplier_cheque_print(sup_id, pay_id):
    _ensure_tables()
    db = _get_db()
    s = db.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
    pay = db.execute("SELECT * FROM supplier_payment_records WHERE id = ? AND supplier_id = ?", (pay_id, sup_id)).fetchone()
    if not s or not pay:
        flash("Payment not found.", "error")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id))
    try:
        company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    except Exception:
        company = None

    def num_to_words(n):
        if n == 0: return "Zero"
        ones = ["","One","Two","Three","Four","Five","Six","Seven","Eight","Nine","Ten","Eleven","Twelve","Thirteen","Fourteen","Fifteen","Sixteen","Seventeen","Eighteen","Nineteen"]
        tens = ["","","Twenty","Thirty","Forty","Fifty","Sixty","Seventy","Eighty","Ninety"]
        def cvt(x):
            if x < 20: return ones[x]
            if x < 100: return tens[x//10] + (" " + ones[x%10] if x%10 else "")
            if x < 1000: return ones[x//100] + " Hundred" + (" " + cvt(x%100) if x%100 else "")
            if x < 1000000: return cvt(x//1000) + " Thousand" + (" " + cvt(x%1000) if x%1000 else "")
            return cvt(x//1000000) + " Million" + (" " + cvt(x%1000000) if x%1000000 else "")
        ip = int(n); dp = round((n - ip) * 100)
        w = cvt(ip)
        if dp: w += f" and {dp}/100"
        return w

    disc = float(pay.get("discount") or 0)
    amt = max(0, (pay["amount"] or 0) - disc)
    amount_words = num_to_words(amt)
    return render_template("supplier/cheque_print.html", s=s, pay=pay, company=company, amount_words=amount_words, net_amt=amt)


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

    unpaid_expenses = db.execute(
        "SELECT id, description, amount, category, earning_type FROM supplier_expenses WHERE supplier_id = ? AND status IN ('pending','approved') ORDER BY expense_date",
        (sup_id,),
    ).fetchall()

    if request.method == "POST":
        payment_date = request.form.get("payment_date", "").strip() or date.today().isoformat()
        amount = request.form.get("amount", "").strip()
        invoice_ids = request.form.getlist("invoice_ids")
        expense_ids = request.form.getlist("expense_ids")
        payment_method = request.form.get("payment_method", "Cash").strip()
        reference_no = request.form.get("reference_no", "").strip()
        notes = request.form.get("notes", "").strip()
        if not amount:
            flash("Payment amount is required.", "error")
            return render_template("supplier/payment_form.html", s=s, pay=pay, invoices=unpaid, expenses=unpaid_expenses, methods=PAYMENT_METHODS, today=date.today().isoformat())
        amount_f = float(amount)
        fund_source = request.form.get("fund_source", "cash_bank").strip()

        # Unlink old invoices/expenses
        if pay.get("invoice_ids"):
            for iid in pay["invoice_ids"].split(","):
                iid = iid.strip()
                if iid:
                    db.execute("UPDATE supplier_invoices SET status='approved', payment_date=NULL, payment_method=NULL, payment_ref=NULL WHERE id=? AND status='paid'", (iid,))
        if pay.get("invoice_id"):
            db.execute("UPDATE supplier_invoices SET status='approved', payment_date=NULL, payment_method=NULL, payment_ref=NULL WHERE id=? AND status='paid'", (pay["invoice_id"],))
        if pay.get("expense_ids"):
            for eid in pay["expense_ids"].split(","):
                eid = eid.strip()
                if eid:
                    db.execute("UPDATE supplier_expenses SET status='approved', payment_date=NULL, payment_method=NULL, payment_ref=NULL WHERE id=? AND status='paid'", (eid,))

        # Link new invoices/expenses
        for iid in invoice_ids:
            if iid:
                db.execute("UPDATE supplier_invoices SET status='paid', payment_date=?, payment_method=?, payment_ref=? WHERE id=?", (payment_date, payment_method, reference_no, iid))
        for eid in expense_ids:
            if eid:
                db.execute("UPDATE supplier_expenses SET status='paid', payment_date=?, payment_method=?, payment_ref=? WHERE id=?", (payment_date, payment_method, reference_no, eid))

        discount = request.form.get("discount", "0").strip()
        discount_f = float(discount) if discount else 0
        cheque_number = request.form.get("cheque_number", "").strip()
        cheque_date = request.form.get("cheque_date", "").strip()
        invoice_ids_str = ",".join(invoice_ids)
        expense_ids_str = ",".join(expense_ids)
        db.execute(
            "UPDATE supplier_payment_records SET payment_date=?, amount=?, invoice_id=NULL, invoice_ids=?, expense_ids=?, payment_method=?, reference_no=?, notes=?, fund_source=?, cheque_number=?, cheque_date=?, discount=? WHERE id=?",
            (payment_date, amount_f, invoice_ids_str, expense_ids_str, payment_method, reference_no, notes, fund_source, cheque_number or None, cheque_date or None, discount_f, pay_id),
        )
        db.commit()
        flash("Payment updated.", "success")
        return redirect(url_for("supplier.supplier_profile", sup_id=sup_id, tab="payments"))

    return render_template("supplier/payment_form.html", s=s, pay=pay, invoices=unpaid, expenses=unpaid_expenses, methods=PAYMENT_METHODS, today=date.today().isoformat())


@supplier_bp.route("/<int:sup_id>/payments/<int:pay_id>/delete", methods=["POST"])
def supplier_payment_delete(sup_id, pay_id):
    _ensure_tables()
    db = _get_db()
    try:
        pay = db.execute("SELECT * FROM supplier_payment_records WHERE id=? AND supplier_id=?", (pay_id, sup_id)).fetchone()
        db.execute("DELETE FROM supplier_payment_records WHERE id=? AND supplier_id=?", (pay_id, sup_id))
        if pay:
            # Revert invoices
            for iid in (pay.get("invoice_ids") or "").split(","):
                iid = iid.strip()
                if iid:
                    db.execute("UPDATE supplier_invoices SET status='approved', payment_date=NULL, payment_method=NULL, payment_ref=NULL WHERE id=? AND status='paid'", (iid,))
            if pay.get("invoice_id"):
                db.execute("UPDATE supplier_invoices SET status='approved', payment_date=NULL, payment_method=NULL, payment_ref=NULL WHERE id=? AND status='paid'", (pay["invoice_id"],))
            # Revert expenses
            for eid in (pay.get("expense_ids") or "").split(","):
                eid = eid.strip()
                if eid:
                    db.execute("UPDATE supplier_expenses SET status='approved', payment_date=NULL, payment_method=NULL, payment_ref=NULL WHERE id=? AND status='paid'", (eid,))
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
        "SELECT id, invoice_date as dt, invoice_no as ref, total_amount as amt, vat_amount, description, status FROM supplier_invoices WHERE supplier_id = ?",
        (sup_id,),
    ).fetchall():
        parts = [f"Invoice: {inv['ref']}"]
        if inv['description']:
            parts.append(inv['description'])
        ledger.append({
            "date": inv["dt"],
            "type": "invoice",
            "description": " — ".join(parts),
            "debit": 0,
            "credit": inv["amt"],
            "ref": inv["ref"],
        })

    # Expenses — increase balance
    for exp in db.execute(
        "SELECT id, expense_date as dt, category as ref, amount as amt, earning_type, quantity, rate, vehicle_no, description FROM supplier_expenses WHERE supplier_id = ?",
        (sup_id,),
    ).fetchall():
        if exp["description"]:
            desc = exp["description"]
            if exp["vehicle_no"]:
                desc += f" [{exp['vehicle_no']}]"
        else:
            if exp["earning_type"] == "trip":
                desc = f"Trip: {exp['quantity']} x {exp['rate']}"
            elif exp["earning_type"] == "hour":
                desc = f"Hours: {exp['quantity']} x {exp['rate']}"
            else:
                desc = f"Expense: {exp['ref']}"
            if exp["vehicle_no"]:
                desc += f" [{exp['vehicle_no']}]"
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
        """SELECT pr.id, pr.payment_date as dt, pr.amount as amt, pr.payment_method as ref,
                  pr.reference_no, pr.notes, pr.invoice_id, inv.invoice_no
           FROM supplier_payment_records pr
           LEFT JOIN supplier_invoices inv ON inv.id = pr.invoice_id
           WHERE pr.supplier_id = ?""",
        (sup_id,),
    ).fetchall():
        if pay["notes"]:
            desc = pay["notes"]
        else:
            parts = [f"Payment: {pay['ref']}"]
            if pay["reference_no"]:
                parts.append(pay["reference_no"])
            if pay["invoice_no"]:
                parts.append(f"→ {pay['invoice_no']}")
            desc = " — ".join(parts)
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
        "SELECT id, invoice_date as dt, invoice_no as ref, total_amount as amt, description, status FROM supplier_invoices WHERE supplier_id = ?",
        (sup_id,),
    ).fetchall():
        parts = [f"Invoice: {inv['ref']}"]
        if inv['description']:
            parts.append(inv['description'])
        ledger.append({"date": inv["dt"], "type": "Invoice", "ref": " — ".join(parts), "dr": 0, "cr": inv["amt"]})
    for exp in db.execute(
        "SELECT id, expense_date as dt, category as ref, amount as amt, earning_type, quantity, rate, vehicle_no, description FROM supplier_expenses WHERE supplier_id = ?",
        (sup_id,),
    ).fetchall():
        if exp["description"]:
            d = exp["description"]
            if exp["vehicle_no"]:
                d += f" [{exp['vehicle_no']}]"
        else:
            if exp["earning_type"] == "trip":
                d = f"Trip: {exp['quantity']} x {exp['rate']}"
            elif exp["earning_type"] == "hour":
                d = f"Hours: {exp['quantity']} x {exp['rate']}"
            else:
                d = f"Expense: {exp['ref']}"
            if exp["vehicle_no"]:
                d += f" [{exp['vehicle_no']}]"
        ledger.append({"date": exp["dt"], "type": "Expense", "ref": d, "dr": 0, "cr": exp["amt"]})
    for pay in db.execute(
        "SELECT id, payment_date as dt, payment_method as ref, amount as amt, reference_no, notes, invoice_id FROM supplier_payment_records WHERE supplier_id = ?",
        (sup_id,),
    ).fetchall():
        if pay["notes"]:
            d = pay["notes"]
        else:
            parts = [f"Payment: {pay['ref']}"]
            if pay["reference_no"]:
                parts.append(pay["reference_no"])
            d = " — ".join(parts)
        ledger.append({"date": pay["dt"], "type": "Payment", "ref": d, "dr": pay["amt"], "cr": 0})

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
    colw = [50, W - 50 - 55 - 55 - 65, 55, 55, 65]
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
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=f"SOA_{s['supplier_name']}.pdf")


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
        return redirect(url_for("supplier.supplier_list"))
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


# ═══════════════════════════════════════════════════════════
# SUPPLIER BILLS (Parts/Service bills per vehicle)
# ═══════════════════════════════════════════════════════════

@supplier_bp.route("/bills")
def supplier_bill_list():
    _ensure_tables()
    db = _get_db()
    supplier_filter = request.args.get("supplier", "")
    vehicle_filter = request.args.get("vehicle", "")
    month_filter = request.args.get("month", "")
    params = []
    where = ""
    if supplier_filter:
        where += " AND sb.supplier_id = ?"
        params.append(supplier_filter)
    if vehicle_filter:
        where += " AND sb.vehicle_plate = ?"
        params.append(vehicle_filter)
    if month_filter:
        where += " AND substr(sb.bill_date,1,7) = ?"
        params.append(month_filter)
    bills = db.execute(f"""
        SELECT sb.*, s.supplier_name FROM supplier_bills sb
        JOIN suppliers s ON s.id = sb.supplier_id
        WHERE 1=1{where}
        ORDER BY sb.bill_date DESC, sb.id DESC
    """, params).fetchall()
    suppliers = db.execute("SELECT id, supplier_name FROM suppliers ORDER BY supplier_name").fetchall()
    vehicles = db.execute("SELECT plate_no FROM vehicles ORDER BY plate_no").fetchall()
    total_amount = sum(b["total_amount"] for b in bills) if bills else 0
    total_vat = sum(b["vat_amount"] for b in bills) if bills else 0
    total_discount = sum(b["discount"] for b in bills) if bills else 0
    total_net = sum(b["net_amount"] for b in bills) if bills else 0
    return render_template(
        "supplier/bill_list.html",
        bills=bills,
        suppliers=suppliers,
        vehicles=vehicles,
        supplier_filter=supplier_filter,
        vehicle_filter=vehicle_filter,
        month_filter=month_filter,
        total_amount=total_amount,
        total_vat=total_vat,
        total_discount=total_discount,
        total_net=total_net,
    )


@supplier_bp.route("/bills/add", methods=["GET", "POST"])
def supplier_bill_add():
    _ensure_tables()
    db = _get_db()
    if request.method == "POST":
        supplier_id = request.form.get("supplier_id", "").strip()
        vehicle_plate = request.form.get("vehicle_plate", "").strip()
        bill_no = request.form.get("bill_no", "").strip()
        bill_date = request.form.get("bill_date", "").strip()
        description = request.form.get("description", "").strip()
        is_tax_bill = request.form.get("is_tax_bill") == "on"
        amount_excl = float(request.form.get("amount", 0) or 0)
        discount = float(request.form.get("discount", 0) or 0)
        if not supplier_id or not vehicle_plate or not bill_no or not bill_date or amount_excl <= 0:
            flash("Please fill all required fields.", "error")
            return redirect(url_for("supplier.supplier_bill_add"))
        supplier = db.execute("SELECT id, supplier_name FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not supplier:
            flash("Supplier not found.", "error")
            return redirect(url_for("supplier.supplier_bill_add"))
        if is_tax_bill:
            total_amount = round(amount_excl * 1.05, 2)
            vat_amount = round(amount_excl * 0.05, 2)
            vat_percentage = 5
        else:
            total_amount = amount_excl
            vat_amount = 0
            vat_percentage = 0
        net_amount = round(amount_excl - discount, 2)
        bill_desc = f"Bill {bill_no} — {vehicle_plate}"
        if description:
            bill_desc += f" ({description})"
        exp_earning_type = 'invoice'
        exp_amount = total_amount
        if db.backend == "postgres":
            bill_result = db.execute(
                """INSERT INTO supplier_bills (supplier_id, vehicle_plate, bill_no, bill_date, description, total_amount, vat_percentage, vat_amount, discount, net_amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
                (supplier["id"], vehicle_plate, bill_no, bill_date, description, total_amount, vat_percentage, vat_amount, discount, net_amount),
            )
            bill_id = bill_result.fetchone()[0]
            exp_result = db.execute(
                """INSERT INTO supplier_expenses (supplier_id, expense_date, amount, category, description, earning_type, quantity, rate, vehicle_no, status, is_tax_bill)
                   VALUES (?, ?, ?, 'Parts', ?, ?, NULL, NULL, ?, 'approved', ?) RETURNING id""",
                (supplier["id"], bill_date, exp_amount, bill_desc, exp_earning_type, vehicle_plate, 1 if is_tax_bill else 0),
            )
            expense_id = exp_result.fetchone()[0]
        else:
            db.execute(
                """INSERT INTO supplier_bills (supplier_id, vehicle_plate, bill_no, bill_date, description, total_amount, vat_percentage, vat_amount, discount, net_amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (supplier["id"], vehicle_plate, bill_no, bill_date, description, total_amount, vat_percentage, vat_amount, discount, net_amount),
            )
            bill_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute(
                """INSERT INTO supplier_expenses (supplier_id, expense_date, amount, category, description, earning_type, quantity, rate, vehicle_no, status, is_tax_bill)
                   VALUES (?, ?, ?, 'Parts', ?, ?, NULL, NULL, ?, 'approved', ?)""",
                (supplier["id"], bill_date, exp_amount, bill_desc, exp_earning_type, vehicle_plate, 1 if is_tax_bill else 0),
            )
            expense_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("UPDATE supplier_bills SET source_expense_id = ? WHERE id = ?", (expense_id, bill_id))
        db.commit()
        flash(f"Bill #{bill_no} added — AED {net_amount}", "success")
        return redirect(url_for("supplier.supplier_bill_list"))
    suppliers = db.execute("SELECT id, supplier_name FROM suppliers WHERE status = 'Active' ORDER BY supplier_name").fetchall()
    vehicles = db.execute("SELECT plate_no FROM vehicles ORDER BY plate_no").fetchall()
    return render_template("supplier/bill_form.html", suppliers=suppliers, vehicles=vehicles, bill=None)


@supplier_bp.route("/bills/<int:bill_id>/edit", methods=["GET", "POST"])
def supplier_bill_edit(bill_id):
    _ensure_tables()
    db = _get_db()
    bill = db.execute("SELECT * FROM supplier_bills WHERE id = ?", (bill_id,)).fetchone()
    if not bill:
        flash("Bill not found.", "error")
        return redirect(url_for("supplier.supplier_bill_list"))
    if request.method == "POST":
        supplier_id = request.form.get("supplier_id", "").strip()
        vehicle_plate = request.form.get("vehicle_plate", "").strip()
        bill_no = request.form.get("bill_no", "").strip()
        bill_date = request.form.get("bill_date", "").strip()
        description = request.form.get("description", "").strip()
        is_tax_bill = request.form.get("is_tax_bill") == "on"
        amount_excl = float(request.form.get("amount", 0) or 0)
        discount = float(request.form.get("discount", 0) or 0)
        if not supplier_id or not vehicle_plate or not bill_no or not bill_date or amount_excl <= 0:
            flash("Please fill all required fields.", "error")
            return redirect(url_for("supplier.supplier_bill_edit", bill_id=bill_id))
        supplier = db.execute("SELECT id, supplier_name FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not supplier:
            flash("Supplier not found.", "error")
            return redirect(url_for("supplier.supplier_bill_edit", bill_id=bill_id))
        if is_tax_bill:
            total_amount = round(amount_excl * 1.05, 2)
            vat_amount = round(amount_excl * 0.05, 2)
            vat_percentage = 5
        else:
            total_amount = amount_excl
            vat_amount = 0
            vat_percentage = 0
        net_amount = round(amount_excl - discount, 2)
        bill_desc = f"Bill {bill_no} — {vehicle_plate}"
        if description:
            bill_desc += f" ({description})"
        db.execute(
            """UPDATE supplier_bills SET supplier_id=?, vehicle_plate=?, bill_no=?, bill_date=?, description=?, total_amount=?, vat_percentage=?, vat_amount=?, discount=?, net_amount=?
               WHERE id=?""",
            (supplier["id"], vehicle_plate, bill_no, bill_date, description, total_amount, vat_percentage, vat_amount, discount, net_amount, bill_id),
        )
        if bill["source_expense_id"]:
            exp_earning_type = 'invoice'
            exp_amount = total_amount
            db.execute(
                """UPDATE supplier_expenses SET expense_date=?, amount=?, category='Parts', description=?, earning_type=?, quantity=NULL, rate=NULL, vehicle_no=?, is_tax_bill=?
                   WHERE id=?""",
                (bill_date, exp_amount, bill_desc, exp_earning_type, vehicle_plate, 1 if is_tax_bill else 0, bill["source_expense_id"]),
            )
        db.commit()
        flash(f"Bill #{bill_no} updated.", "success")
        return redirect(url_for("supplier.supplier_bill_list"))
    suppliers = db.execute("SELECT id, supplier_name FROM suppliers WHERE status = 'Active' ORDER BY supplier_name").fetchall()
    vehicles = db.execute("SELECT plate_no FROM vehicles ORDER BY plate_no").fetchall()
    return render_template("supplier/bill_edit.html", suppliers=suppliers, vehicles=vehicles, bill=bill)


@supplier_bp.route("/bills/batch", methods=["POST"])
def supplier_bills_batch():
    _ensure_tables()
    db = _get_db()
    supplier_id = request.form.get("batch_supplier", "").strip()
    if not supplier_id:
        flash("Missing supplier.", "error")
        return redirect(url_for("supplier.supplier_bill_add"))
    supplier = db.execute("SELECT id, supplier_name FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if not supplier:
        flash("Supplier not found.", "error")
        return redirect(url_for("supplier.supplier_bill_add"))
    import re
    v_keys = [k for k in request.form.keys() if re.match(r'^v_\d+$', k)]
    if not v_keys:
        flash("No bill rows found.", "error")
        return redirect(url_for("supplier.supplier_bill_add"))
    count = 0
    for vk in v_keys:
        idx = vk.split("_", 1)[1]
        vehicle_plate = request.form.get(f"v_{idx}", "").strip()
        bill_no = request.form.get(f"bn_{idx}", "").strip()
        bill_date = request.form.get(f"bd_{idx}", "").strip()
        description = request.form.get(f"desc_{idx}", "").strip()
        amount_excl = float(request.form.get(f"amt_{idx}", 0) or 0)
        discount = float(request.form.get(f"disc_{idx}", 0) or 0)
        is_tax = request.form.get(f"tax_{idx}") == "on"
        if not vehicle_plate or not bill_no or not bill_date or amount_excl <= 0:
            continue
        if is_tax:
            total_amount = round(amount_excl * 1.05, 2)
            vat_amount = round(amount_excl * 0.05, 2)
            vat_percentage = 5
        else:
            total_amount = amount_excl
            vat_amount = 0
            vat_percentage = 0
        net_amount = round(amount_excl - discount, 2)
        bill_desc = f"Bill {bill_no} — {vehicle_plate}"
        if description:
            bill_desc += f" ({description})"
        exp_earning_type = 'invoice'
        exp_amount = total_amount
        if db.backend == "postgres":
            br = db.execute(
                """INSERT INTO supplier_bills (supplier_id, vehicle_plate, bill_no, bill_date, description, total_amount, vat_percentage, vat_amount, discount, net_amount)
                   VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (supplier["id"], vehicle_plate, bill_no, bill_date, description, total_amount, vat_percentage, vat_amount, discount, net_amount),
            )
            bill_id = br.fetchone()[0]
            er = db.execute(
                """INSERT INTO supplier_expenses (supplier_id, expense_date, amount, category, description, earning_type, quantity, rate, vehicle_no, status, is_tax_bill)
                   VALUES (?,?,?,'Parts',?,?,NULL,NULL,?,'approved',?) RETURNING id""",
                (supplier["id"], bill_date, exp_amount, bill_desc, exp_earning_type, vehicle_plate, 1 if is_tax else 0),
            )
            expense_id = er.fetchone()[0]
        else:
            db.execute(
                """INSERT INTO supplier_bills (supplier_id, vehicle_plate, bill_no, bill_date, description, total_amount, vat_percentage, vat_amount, discount, net_amount)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (supplier["id"], vehicle_plate, bill_no, bill_date, description, total_amount, vat_percentage, vat_amount, discount, net_amount),
            )
            bill_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute(
                """INSERT INTO supplier_expenses (supplier_id, expense_date, amount, category, description, earning_type, quantity, rate, vehicle_no, status, is_tax_bill)
                   VALUES (?,?,?,'Parts',?,?,NULL,NULL,?,'approved',?)""",
                (supplier["id"], bill_date, exp_amount, bill_desc, exp_earning_type, vehicle_plate, 1 if is_tax else 0),
            )
            expense_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("UPDATE supplier_bills SET source_expense_id = ? WHERE id = ?", (expense_id, bill_id))
        count += 1
    db.commit()
    flash(f"{count} bill(s) added successfully for {supplier['supplier_name']}.", "success")
    return redirect(url_for("supplier.supplier_bill_list"))


@supplier_bp.route("/bills/<int:bill_id>/delete", methods=["POST"])
def supplier_bill_delete(bill_id):
    _ensure_tables()
    db = _get_db()
    bill = db.execute("SELECT * FROM supplier_bills WHERE id = ?", (bill_id,)).fetchone()
    if not bill:
        flash("Bill not found.", "error")
        return redirect(url_for("supplier.supplier_bill_list"))
    if bill["source_expense_id"]:
        db.execute("DELETE FROM supplier_expenses WHERE id = ?", (bill["source_expense_id"],))
    db.execute("DELETE FROM supplier_bills WHERE id = ?", (bill_id,))
    db.commit()
    flash(f"Bill #{bill['bill_no']} deleted.", "info")
    return redirect(url_for("supplier.supplier_bill_list"))
