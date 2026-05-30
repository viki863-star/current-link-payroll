import os, base64, re, math
from datetime import date, datetime
from flask import render_template, request, redirect, url_for, flash, current_app, send_file, session, jsonify
from markupsafe import Markup
from . import customer_bp

def _get_db():
    import sqlite3
    db_path = current_app.config.get("DATABASE") or "payroll.db"
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    return db

def _ensure_tables():
    db = _get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            customer_code TEXT,
            contact_person TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            trn TEXT,
            trade_license TEXT,
            credit_limit REAL DEFAULT 0,
            payment_terms TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS customer_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            invoice_no TEXT,
            invoice_date TEXT NOT NULL,
            amount REAL NOT NULL,
            vat_percent REAL DEFAULT 5,
            vat_amount REAL DEFAULT 0,
            total_amount REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS customer_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            invoice_id INTEGER,
            payment_date TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT DEFAULT 'Cash',
            reference_no TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS customer_contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            contract_no TEXT,
            contract_date TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            contract_type TEXT DEFAULT 'rental',
            amount REAL,
            status TEXT NOT NULL DEFAULT 'active',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS customer_quotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            quotation_no TEXT,
            quotation_date TEXT NOT NULL,
            amount REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS customer_lpos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            lpo_no TEXT,
            lpo_date TEXT NOT NULL,
            amount REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS customer_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            doc_type TEXT,
            doc_name TEXT,
            file_data TEXT,
            file_type TEXT,
            expiry_date TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS customer_invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            description TEXT,
            quantity REAL DEFAULT 1,
            rate REAL DEFAULT 0,
            amount REAL DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (invoice_id) REFERENCES customer_invoices(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS service_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL UNIQUE,
            default_rate REAL DEFAULT 0,
            category TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    # seed service_items from existing invoice items
    try:
        db.execute("""
            INSERT OR IGNORE INTO service_items (description)
            SELECT DISTINCT TRIM(description) FROM customer_invoice_items
            WHERE description IS NOT NULL AND TRIM(description) != ''
        """)
        db.commit()
    except Exception:
        pass
    for col, dtype in [("lpo_no", "TEXT"), ("lpo_date", "TEXT"), ("project_no", "TEXT"),
                       ("invoice_template", "TEXT DEFAULT 'standard'"), ("discount", "REAL DEFAULT 0"),
                       ("ref_no", "TEXT")]:
        try:
            db.execute(f"ALTER TABLE customer_invoices ADD COLUMN {col} {dtype}")
        except Exception:
            pass
    for col, dtype in [("capacity_gallon", "TEXT"), ("unit", "TEXT"),
                       ("vat_percent_item", "REAL"), ("vat_amount_item", "REAL"),
                       ("total_incl_vat", "REAL")]:
        try:
            db.execute(f"ALTER TABLE customer_invoice_items ADD COLUMN {col} {dtype}")
        except Exception:
            pass
    for col, dtype in [("logo_data", "TEXT"), ("logo_type", "TEXT"), ("theme_color", "TEXT DEFAULT '#0F2B52'"),
                       ("bank_name", "TEXT"), ("bank_account_name", "TEXT"), ("bank_account_number", "TEXT"),
                       ("iban", "TEXT")]:
        try:
            db.execute(f"ALTER TABLE company_profile ADD COLUMN {col} {dtype}")
        except Exception:
            pass
    try:
        db.execute("ALTER TABLE customer_invoices DROP COLUMN status")
    except Exception:
        pass
    try:
        db.execute("ALTER TABLE customer_invoices DROP COLUMN paid")
    except Exception:
        pass
    db.execute("""CREATE TABLE IF NOT EXISTS invoice_sequence (last_number INTEGER DEFAULT 0)""")
    db.execute("INSERT INTO invoice_sequence (last_number) SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM invoice_sequence)")
    db.execute("""
        CREATE TABLE IF NOT EXISTS customer_credit_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            credit_note_no TEXT,
            credit_note_date TEXT NOT NULL,
            invoice_id INTEGER,
            amount REAL NOT NULL DEFAULT 0,
            vat_percent REAL DEFAULT 0,
            vat_amount REAL DEFAULT 0,
            total_amount REAL NOT NULL DEFAULT 0,
            reason TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)
    db.commit()
    db.close()

# ─── HELPERS ───

def _next_code(db):
    last = db.execute("SELECT customer_code FROM customers ORDER BY id DESC LIMIT 1").fetchone()
    if last and last["customer_code"]:
        m = re.search(r'(\d+)', last["customer_code"])
        n = int(m.group(1)) + 1 if m else 1
    else:
        n = 1
    return f"CUS-{n:04d}"

def _next_invoice_no(db):
    db.execute("UPDATE invoice_sequence SET last_number = last_number + 1")
    n = db.execute("SELECT last_number FROM invoice_sequence").fetchone()[0]
    return f"NS{n + 883}"

def _get_customer_or_404(cid):
    db = _get_db()
    c = db.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    db.close()
    if not c:
        flash("Customer not found.", "error")
        return None
    return c

# ─── DASHBOARD ───

@customer_bp.route("/")
def customer_dashboard():
    from ..routes import _touch_admin_workspace
    _touch_admin_workspace("customers")
    _ensure_tables()
    db = _get_db()
    total = db.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    active = db.execute("SELECT COUNT(*) FROM customers WHERE status='active'").fetchone()[0]
    total_receivable = db.execute("SELECT COALESCE(SUM(total_amount),0) FROM customer_invoices").fetchone()[0]
    total_cn = db.execute("SELECT COALESCE(SUM(total_amount),0) FROM customer_credit_notes").fetchone()[0]
    inv_count = db.execute("SELECT COUNT(*) FROM customer_invoices").fetchone()[0]
    paid_total = db.execute("SELECT COALESCE(SUM(amount),0) FROM customer_payments").fetchone()[0]
    recent = db.execute("""SELECT i.*, c.customer_name FROM customer_invoices i
        JOIN customers c ON i.customer_id=c.id ORDER BY i.created_at DESC LIMIT 8""").fetchall()
    recent_pmts = db.execute("""SELECT p.*, c.customer_name FROM customer_payments p
        JOIN customers c ON p.customer_id=c.id ORDER BY p.created_at DESC LIMIT 6""").fetchall()
    monthly = db.execute("""
        SELECT substr(invoice_date,1,7) AS mon,
               COUNT(*) AS cnt, COALESCE(SUM(total_amount),0) AS tot
        FROM customer_invoices GROUP BY mon ORDER BY mon DESC LIMIT 12
    """).fetchall()
    top_customers = db.execute("""
        SELECT c.id, c.customer_name, COUNT(i.id) AS inv_cnt,
               COALESCE(SUM(i.total_amount),0) AS total
        FROM customers c LEFT JOIN customer_invoices i ON i.customer_id=c.id
        GROUP BY c.id ORDER BY total DESC LIMIT 5
    """).fetchall()
    db.close()
    return render_template("customer/dashboard.html",
        total=total, active=active,
        total_receivable=total_receivable, total_cn=total_cn,
        inv_count=inv_count, paid_total=paid_total,
        outstanding=total_receivable - paid_total - total_cn,
        recent_invoices=recent, recent_payments=recent_pmts,
        monthly_trend=monthly, top_customers=top_customers)

# ─── CUSTOMER CRUD ───

@customer_bp.route("/add", methods=["GET", "POST"])
def customer_add():
    _ensure_tables()
    db = _get_db()
    if request.method == "POST":
        name = request.form.get("customer_name", "").strip()
        if not name:
            flash("Customer name is required.", "error")
            code = _next_code(db)
            db.close()
            return render_template("customer/form.html", cus={}, code=code)
        code = request.form.get("customer_code", "").strip() or _next_code(db)
        c = db.execute("""INSERT INTO customers (customer_name,customer_code,contact_person,phone,email,address,trn,trade_license,credit_limit,payment_terms,status,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, code, request.form.get("contact_person"), request.form.get("phone"),
             request.form.get("email"), request.form.get("address"), request.form.get("trn"),
             request.form.get("trade_license"), float(request.form.get("credit_limit", 0) or 0),
             request.form.get("payment_terms"), request.form.get("status", "active"), request.form.get("notes")))
        new_id = c.lastrowid
        db.commit()
        db.close()
        flash("Customer added.", "success")
        return redirect(url_for("customer.customer_profile", cid=new_id))
    code = _next_code(db)
    db.close()
    return render_template("customer/form.html", cus={}, code=code)

@customer_bp.route("/<int:cid>/edit", methods=["GET", "POST"])
def customer_edit(cid):
    _ensure_tables()
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    if request.method == "POST":
        db = _get_db()
        db.execute("""UPDATE customers SET customer_name=?,contact_person=?,phone=?,email=?,address=?,trn=?,trade_license=?,credit_limit=?,payment_terms=?,status=?,notes=? WHERE id=?""",
            (request.form.get("customer_name"), request.form.get("contact_person"), request.form.get("phone"),
             request.form.get("email"), request.form.get("address"), request.form.get("trn"),
             request.form.get("trade_license"), float(request.form.get("credit_limit", 0) or 0),
             request.form.get("payment_terms"), request.form.get("status", "active"), request.form.get("notes"), cid))
        db.commit()
        db.close()
        flash("Customer updated.", "success")
        return redirect(url_for("customer.customer_profile", cid=cid))
    return render_template("customer/form.html", cus=c)

@customer_bp.route("/<int:cid>")
def customer_profile(cid):
    _ensure_tables()
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    db = _get_db()
    tab = request.args.get("tab", "overview")
    invoices = db.execute("SELECT * FROM customer_invoices WHERE customer_id=? ORDER BY invoice_date DESC", (cid,)).fetchall()
    payments = db.execute("SELECT p.*, i.invoice_no FROM customer_payments p LEFT JOIN customer_invoices i ON p.invoice_id=i.id WHERE p.customer_id=? ORDER BY p.payment_date DESC", (cid,)).fetchall()
    contracts = db.execute("SELECT * FROM customer_contracts WHERE customer_id=? ORDER BY contract_date DESC", (cid,)).fetchall()
    quotations = db.execute("SELECT * FROM customer_quotations WHERE customer_id=? ORDER BY quotation_date DESC", (cid,)).fetchall()
    lpos = db.execute("SELECT * FROM customer_lpos WHERE customer_id=? ORDER BY lpo_date DESC", (cid,)).fetchall()
    docs = db.execute("SELECT * FROM customer_documents WHERE customer_id=? ORDER BY created_at DESC", (cid,)).fetchall()
    credit_notes = db.execute("SELECT * FROM customer_credit_notes WHERE customer_id=? ORDER BY credit_note_date DESC", (cid,)).fetchall()
    total_inv = db.execute("SELECT COALESCE(SUM(total_amount),0) FROM customer_invoices WHERE customer_id=?", (cid,)).fetchone()[0]
    total_paid = db.execute("SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE customer_id=?", (cid,)).fetchone()[0]
    total_cn = db.execute("SELECT COALESCE(SUM(total_amount),0) FROM customer_credit_notes WHERE customer_id=?", (cid,)).fetchone()[0]
    balance = round(total_inv - total_paid - total_cn, 2)
    db.close()
    return render_template("customer/profile.html", c=c, active_tab=tab, invoices=invoices,
        payments=payments, contracts=contracts, quotations=quotations, lpos=lpos, docs=docs,
        credit_notes=credit_notes,
        total_inv=total_inv, total_paid=total_paid, total_cn=total_cn, balance=balance)

# ─── INVOICES ───

@customer_bp.route("/<int:cid>/invoice/add", methods=["GET", "POST"])
def customer_invoice_add(cid):
    _ensure_tables()
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    db = _get_db()
    next_no = _next_invoice_no(db)
    lpos = db.execute("SELECT id,lpo_no,lpo_date,amount FROM customer_lpos WHERE customer_id=? AND status!='closed' ORDER BY lpo_date DESC", (cid,)).fetchall()
    svc_items = db.execute("SELECT description FROM service_items ORDER BY description LIMIT 500").fetchall()
    if request.method == "POST":
        inv_date = request.form.get("invoice_date", date.today().isoformat())
        inv_no = request.form.get("invoice_no", "").strip() or next_no
        existing = db.execute("SELECT id FROM customer_invoices WHERE invoice_no=?", (inv_no,)).fetchone()
        if existing:
            flash(f"Invoice number '{inv_no}' already exists. Use a different number.", "error")
            db.close()
            return render_template("customer/invoice_form.html", c=c, inv={}, lpos=lpos, svc_items=svc_items, today=date.today().isoformat(), next_no=next_no)
        vat_pct = float(request.form.get("vat_percent", 5))
        lpo_no = request.form.get("lpo_no", "").strip() or None
        lpo_date = request.form.get("lpo_date", "").strip() or None
        project_no = request.form.get("project_no", "").strip() or None
        notes = request.form.get("notes", "").strip()
        descs = request.form.getlist("item_desc[]")
        qtys = request.form.getlist("item_qty[]")
        rates = request.form.getlist("item_rate[]")
        items = []
        sub_total = 0
        for i in range(len(descs)):
            desc = descs[i].strip()
            qty = float(qtys[i]) if i < len(qtys) and qtys[i].strip() else 1
            rate = float(rates[i]) if i < len(rates) and rates[i].strip() else 0
            if desc or rate > 0:
                amt = round(qty * rate, 2)
                sub_total += amt
                items.append({"desc": desc, "qty": qty, "rate": rate, "amt": amt})
        if not items:
            flash("At least one line item is required.", "error")
            db.close()
            return render_template("customer/invoice_form.html", c=c, inv={}, lpos=lpos, svc_items=svc_items, today=date.today().isoformat(), next_no=next_no)
        vat_amt = round(sub_total * vat_pct / 100, 2)
        total = round(sub_total + vat_amt, 2)
        c_inv = db.execute("""INSERT INTO customer_invoices (customer_id,invoice_no,invoice_date,amount,vat_percent,vat_amount,total_amount,lpo_no,lpo_date,project_no,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, inv_no, inv_date, sub_total, vat_pct, vat_amt, total, lpo_no, lpo_date, project_no, notes))
        inv_id = c_inv.lastrowid
        for idx, it in enumerate(items):
            db.execute("INSERT INTO customer_invoice_items (invoice_id,description,quantity,rate,amount,sort_order) VALUES (?,?,?,?,?,?)",
                (inv_id, it["desc"], it["qty"], it["rate"], it["amt"], idx))
            if it["desc"]:
                try:
                    db.execute("INSERT OR IGNORE INTO service_items (description, default_rate) VALUES (?,?)", (it["desc"], it["rate"]))
                except Exception:
                    pass
        db.commit()
        db.close()
        flash(f"Invoice {inv_no} created.", "success")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="invoices"))
    db.close()
    return render_template("customer/invoice_form.html", c=c, inv={}, lpos=lpos, svc_items=svc_items, today=date.today().isoformat(), next_no=next_no)

@customer_bp.route("/service-items/search")
def service_items_search():
    _ensure_tables()
    q = request.args.get("q", "").strip()
    db = _get_db()
    if q:
        items = db.execute(
            "SELECT id, description, default_rate FROM service_items WHERE description LIKE ? ORDER BY description LIMIT 20",
            (f"%{q}%",)
        ).fetchall()
    else:
        items = db.execute(
            "SELECT id, description, default_rate FROM service_items ORDER BY description LIMIT 50"
        ).fetchall()
    db.close()
    return jsonify([{"id": r["id"], "description": r["description"], "rate": r["default_rate"]} for r in items])

# ─── NOUROL INVOICE ───

@customer_bp.route("/<int:cid>/invoice/<int:iid>/edit", methods=["GET", "POST"])
def customer_invoice_edit(cid, iid):
    _ensure_tables()
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    db = _get_db()
    inv = db.execute("SELECT * FROM customer_invoices WHERE id=? AND customer_id=?", (iid, cid)).fetchone()
    items = db.execute("SELECT * FROM customer_invoice_items WHERE invoice_id=? ORDER BY sort_order", (iid,)).fetchall()
    lpos = db.execute("SELECT id,lpo_no,lpo_date,amount FROM customer_lpos WHERE customer_id=? AND status!='closed' ORDER BY lpo_date DESC", (cid,)).fetchall()
    svc_items = db.execute("SELECT description FROM service_items ORDER BY description LIMIT 500").fetchall()
    if not inv:
        db.close()
        flash("Invoice not found.", "error")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="invoices"))
    if request.method == "POST":
        inv_date = request.form.get("invoice_date", date.today().isoformat())
        inv_no = request.form.get("invoice_no", "").strip() or inv["invoice_no"]
        dup = db.execute("SELECT id FROM customer_invoices WHERE invoice_no=? AND id!=?", (inv_no, iid)).fetchone()
        if dup:
            flash(f"Invoice number '{inv_no}' already in use.", "error")
            db.close()
            return render_template("customer/invoice_form.html", c=c, inv=inv, items=items, lpos=lpos, svc_items=svc_items, today=date.today().isoformat(), edit=True)
        vat_pct = float(request.form.get("vat_percent", 5))
        lpo_no = request.form.get("lpo_no", "").strip() or None
        lpo_date = request.form.get("lpo_date", "").strip() or None
        project_no = request.form.get("project_no", "").strip() or None
        notes = request.form.get("notes", "").strip()
        descs = request.form.getlist("item_desc[]")
        qtys = request.form.getlist("item_qty[]")
        rates = request.form.getlist("item_rate[]")
        new_items = []
        sub_total = 0
        for i in range(len(descs)):
            desc = descs[i].strip()
            qty = float(qtys[i]) if i < len(qtys) and qtys[i].strip() else 1
            rate = float(rates[i]) if i < len(rates) and rates[i].strip() else 0
            if desc or rate > 0:
                amt = round(qty * rate, 2)
                sub_total += amt
                new_items.append({"desc": desc, "qty": qty, "rate": rate, "amt": amt})
        if not new_items:
            flash("At least one line item is required.", "error")
            db.close()
            return render_template("customer/invoice_form.html", c=c, inv=inv, items=items, lpos=lpos, svc_items=svc_items, today=date.today().isoformat(), edit=True)
        vat_amt = round(sub_total * vat_pct / 100, 2)
        total = round(sub_total + vat_amt, 2)
        db.execute("""UPDATE customer_invoices SET invoice_no=?,invoice_date=?,amount=?,vat_percent=?,vat_amount=?,total_amount=?,lpo_no=?,lpo_date=?,project_no=?,notes=? WHERE id=?""",
            (inv_no, inv_date, sub_total, vat_pct, vat_amt, total, lpo_no, lpo_date, project_no, notes, iid))
        db.execute("DELETE FROM customer_invoice_items WHERE invoice_id=?", (iid,))
        for idx, it in enumerate(new_items):
            db.execute("INSERT INTO customer_invoice_items (invoice_id,description,quantity,rate,amount,sort_order) VALUES (?,?,?,?,?,?)",
                (iid, it["desc"], it["qty"], it["rate"], it["amt"], idx))
            if it["desc"]:
                try:
                    db.execute("INSERT OR IGNORE INTO service_items (description, default_rate) VALUES (?,?)", (it["desc"], it["rate"]))
                except Exception:
                    pass
        db.commit()
        db.close()
        flash(f"Invoice {inv_no} updated.", "success")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="invoices"))
    db.close()
    return render_template("customer/invoice_form.html", c=c, inv=inv, items=items, lpos=lpos, svc_items=svc_items, today=date.today().isoformat(), edit=True)

@customer_bp.route("/<int:cid>/invoice/<int:iid>")
def customer_invoice_view(cid, iid):
    _ensure_tables()
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    db = _get_db()
    inv = db.execute("SELECT * FROM customer_invoices WHERE id=? AND customer_id=?", (iid, cid)).fetchone()
    if not inv:
        db.close()
        flash("Invoice not found.", "error")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="invoices"))
    items = db.execute("SELECT * FROM customer_invoice_items WHERE invoice_id=? ORDER BY sort_order", (iid,)).fetchall()
    company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    db.close()
    try:
        tmpl_t = inv["invoice_template"] or "standard"
    except (IndexError, KeyError):
        tmpl_t = "standard"
    tmpl = "customer/invoice_view.html"
    sum_taxable = sum(it["amount"] or 0 for it in items)
    sum_vat = sum(it["vat_amount_item"] or 0 for it in items)
    sum_total = sum((it["total_incl_vat"] or (it["amount"] or 0) + (it["vat_amount_item"] or 0)) for it in items)
    return render_template(tmpl, c=c, inv=inv, items=items, company=company, sum_taxable=sum_taxable, sum_vat=sum_vat, sum_total=sum_total)

@customer_bp.route("/<int:cid>/invoice/<int:iid>/pdf")
def customer_invoice_pdf(cid, iid):
    import tempfile
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from io import BytesIO

    _logo_tmp_files = []
    _ensure_tables()
    db = _get_db()
    c = db.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    inv = db.execute("SELECT * FROM customer_invoices WHERE id=? AND customer_id=?", (iid, cid)).fetchone()
    items = db.execute("SELECT * FROM customer_invoice_items WHERE invoice_id=? ORDER BY sort_order", (iid,)).fetchall()
    company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    db.close()
    if not c or not inv:
        flash("Invoice not found.", "error")
        return redirect(url_for("customer.customer_dashboard"))

    buf = BytesIO()
    LM, RM, TM, BM = 18*mm, 18*mm, 15*mm, 12*mm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM

    tc = company["theme_color"] or "#1a3a5c" if company else "#1a3a5c"
    try: TH = colors.HexColor(tc)
    except: TH = colors.HexColor("#1a3a5c")
    WH = colors.white; BG = colors.HexColor("#f8fafc")
    C3 = colors.HexColor("#e2e8f0"); C4 = colors.HexColor("#0f172a")
    C5 = colors.HexColor("#64748b"); C6 = colors.HexColor("#dc2626")

    cn = company["company_name"] if company else "AL SAQR TRANSPORT"
    c_addr = (company["address"] or "") if company else ""
    c_ph = (company["phone_number"] or "") if company else ""
    c_em = (company["email"] or "") if company else ""
    c_trn = company["trn_no"] or "—" if company else "—"

    def S(name, **kw):
        kw.setdefault("fontSize", 8)
        kw.setdefault("leading", 12)
        return ParagraphStyle(name, **kw)

    def L(t, **kw):
        kw.setdefault("textColor", C5)
        return Paragraph(str(t), S("_L", **kw))

    def V(t, **kw):
        kw.setdefault("fontName", "Helvetica-Bold")
        kw.setdefault("textColor", C4)
        kw.setdefault("fontSize", 8.5)
        return Paragraph(str(t), S("_V", **kw))

    def C(t, **kw):
        kw.setdefault("alignment", TA_CENTER)
        return Paragraph(str(t), S("_C", **kw))

    def R(t, **kw):
        kw.setdefault("alignment", TA_RIGHT)
        return Paragraph(str(t), S("_R", **kw))

    def RB(t, **kw):
        kw.setdefault("fontName", "Helvetica-Bold")
        kw.setdefault("alignment", TA_RIGHT)
        return Paragraph(f"<b>{t}</b>", S("_RB", **kw))

    safe = lambda v, d="—": str(v) if v else d
    els = []
    inv_no = inv["invoice_no"] or "—"
    inv_dt = inv["invoice_date"] or "—"

    # ═══════════════════════════════════
    # 1. HEADER (matching web view)
    # ═══════════════════════════════════
    logo = None; LW = 0
    if company and company["logo_data"]:
        try:
            lb = base64.b64decode(company["logo_data"])
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            f.write(lb); f.close()
            logo = Image(f.name, width=90, height=90)
            LW = 90
            _logo_tmp_files.append(f.name)
        except: pass

    # Company info lines (matching web: address, phone/email, TRN on separate lines)
    ci_lines = []
    if c_addr: ci_lines.append(f"<font size=7 color='#64748b'>{c_addr}</font>")
    c_contact = []
    if c_ph: c_contact.append(f"Phone: {c_ph}")
    if c_em: c_contact.append(f"Email: {c_em}")
    if c_contact: ci_lines.append('<font size=7 color="#64748b">' + ' &middot; '.join(c_contact) + '</font>')
    ci_lines.append(f"<font size=7 color='#64748b'><b>TRN: {c_trn}</b></font>")
    ci_html = f"<font size=12><b>{cn}</b></font><br/>" + "<br/>".join(ci_lines)
    co_p = Paragraph(ci_html, S("CO", fontSize=12, fontName="Helvetica-Bold", textColor=TH, leading=16))

    if logo:
        lh = Table([[logo, Spacer(1, 4*mm), co_p]], colWidths=[LW, 4*mm, W*0.65 - LW - 4*mm])
        lh.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    else:
        lh = co_p

    rh = Paragraph(
        f"<b>TAX INVOICE</b><br/>"
        f"<font size=7 color='#64748b'># {inv_no}<br/>{inv_dt}</font>",
        S("TI", fontSize=16, fontName="Helvetica-Bold", textColor=TH, leading=20, alignment=TA_RIGHT))

    ht = Table([[lh, rh]], colWidths=[W*0.65, W*0.35])
    ht.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ht)

    # Bottom border line (matching web: 3px solid theme-color)
    bl = Table([[""]], colWidths=[W], rowHeights=[3])
    bl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(bl)
    els.append(Spacer(1, 5*mm))

    # ═══════════════════════════════════
    # 2. BILL TO / INVOICE INFO (matching web)
    # ═══════════════════════════════════
    def card(title, pairs):
        cw = W*0.50
        r = [[
            Paragraph(f"<b>{title}</b>", S("_ch", fontSize=6.5, fontName="Helvetica-Bold", textColor=C5, leading=9)),
            Paragraph("", S("_cs", fontSize=2, leading=2)),
        ]]
        for a, b in pairs:
            r.append([
                Paragraph(a, S("_cl", fontSize=7.5, textColor=C5, leading=11)),
                Paragraph(f"{b}", S("_cv", fontSize=8, fontName="Helvetica-Bold", textColor=C4, leading=11.5)),
            ])
        t = Table(r, colWidths=[cw*0.28, cw*0.72])
        t.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
            ("LEFTPADDING",(0,0),(-1,-1),10), ("RIGHTPADDING",(0,0),(-1,-1),10),
            ("BOX",(0,0),(-1,-1),0.5,colors.HexColor("#e2e8f0")),
        ]))
        return t

    bd = [("Customer", safe(c["customer_name"])), ("TRN", safe(c["trn"]))]
    if c["phone"]: bd.append(("Phone", c["phone"]))
    if c["email"]: bd.append(("Email", c["email"]))
    if c["address"]: bd.append(("Address", c["address"]))
    id_ = [("Invoice #", inv_no), ("Date", inv_dt)]
    if inv["lpo_no"]: id_.append(("LPO No.", inv["lpo_no"]))
    if inv["lpo_date"]: id_.append(("LPO Date", inv["lpo_date"]))
    try:
        if inv["project_no"]: id_.append(("Project No.", inv["project_no"]))
    except (IndexError, KeyError):
        pass
    try:
        if inv["ref_no"]: id_.append(("Ref No.", inv["ref_no"]))
    except (IndexError, KeyError):
        pass

    iw = Table([[card("BILL TO", bd), Spacer(1, 4*mm), card("INVOICE INFO", id_)]], colWidths=[W*0.50, 4*mm, W*0.50])
    iw.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(iw)
    els.append(Spacer(1, 5*mm))

    # ═══════════════════════════════════
    # 3. ITEMS TABLE
    # ═══════════════════════════════════
    DH = colors.HexColor("#1e293b")
    cw = [10*mm, 44*mm, 20*mm, 20*mm, 22*mm, 14*mm, 20*mm, 22*mm]
    hdr = [
        Paragraph("<b>#</b>", S("_h0", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=10)),
        Paragraph("<b>Description</b>", S("_h1", fontSize=7, fontName="Helvetica-Bold", textColor=WH, leading=10)),
        Paragraph("<b>QTY</b>", S("_h2", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=10)),
        Paragraph("<b>Unit Price</b>", S("_h3", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        Paragraph("<b>Taxable Amt</b>", S("_h4", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        Paragraph("<b>VAT %</b>", S("_h5", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=10)),
        Paragraph("<b>VAT Amt</b>", S("_h6", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        Paragraph("<b>Total Incl.</b>", S("_h7", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
    ]
    rws = [hdr]
    for idx, it in enumerate(items):
        vp_item = it["vat_percent_item"] or inv["vat_percent"] or 5
        va_item = it["vat_amount_item"] or (it["amount"] * vp_item / 100)
        ti_item = it["total_incl_vat"] or (it["amount"] + va_item)
        rws.append([
            C(str(idx+1), fontSize=7, fontName="Helvetica-Bold"),
            L(it["description"] or "—", fontSize=7),
            R(f"{it['quantity'] or 0:,.2f}", fontSize=7),
            R(f"{it['rate'] or 0:,.3f}", fontSize=7),
            R(f"{it['amount'] or 0:,.2f}", fontSize=7),
            C(f"{vp_item:.2f}%", fontSize=7),
            R(f"{va_item:,.2f}", fontSize=7, textColor=C6),
            RB(f"{ti_item:,.2f}", fontSize=7),
        ])

    sub = inv["amount"] or 0; vat = inv["vat_amount"] or 0; tot = inv["total_amount"] or 0; vp = inv["vat_percent"] or 0

    itt = Table(rws, colWidths=cw, repeatRows=1)
    itt.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BACKGROUND",(0,0),(-1,0),DH), ("TEXTCOLOR",(0,0),(-1,0),WH),
        ("BOX",(0,0),(-1,-1),0.5,C3),
        ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WH, colors.HexColor("#f8fafc")]),
    ]))
    els.append(itt)

    # ═══════════════════════════════════
    # 4. TOTALS (matching web)
    # ═══════════════════════════════════
    tw = 90*mm
    trows = [
        [Paragraph("Sub Total", S("_st", fontSize=9, textColor=C5, leading=14)),
         Paragraph(f"<b>AED {sub:,.2f}</b>", S("_stv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=14, alignment=TA_RIGHT))],
        [Paragraph(f"VAT @ {vp:.0f}%", S("_vt", fontSize=9, textColor=C5, leading=14)),
         Paragraph(f"<b>AED {vat:,.2f}</b>", S("_vtv", fontSize=9, fontName="Helvetica-Bold", textColor=C6, leading=14, alignment=TA_RIGHT))],
        [Paragraph("<b>Total Due</b>", S("_td", fontSize=11, fontName="Helvetica-Bold", textColor=C4, leading=16)),
         Paragraph(f"<b>AED {tot:,.2f}</b>", S("_tdv", fontSize=13, fontName="Helvetica-Bold", textColor=TH, leading=18, alignment=TA_RIGHT))],
    ]
    tt = Table(trows, colWidths=[tw*0.45, tw*0.55])
    tt.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),12), ("RIGHTPADDING",(0,0),(-1,-1),12),
        ("BOX",(0,0),(-1,-1),0.5,colors.HexColor("#e2e8f0")),
        ("LINEABOVE",(0,2),(-1,2),2,TH),
    ]))

    ft = Table([["", tt]], colWidths=[W - tw, tw])
    ft.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(Spacer(1, 3*mm))
    els.append(ft)

    # ═══════════════════════════════════
    # 5. AMOUNT IN WORDS
    # ═══════════════════════════════════
    def n2w(n):
        if n == 0: return "Zero"
        o = ["","One","Two","Three","Four","Five","Six","Seven","Eight","Nine","Ten","Eleven","Twelve",
             "Thirteen","Fourteen","Fifteen","Sixteen","Seventeen","Eighteen","Nineteen"]
        t = ["","","Twenty","Thirty","Forty","Fifty","Sixty","Seventy","Eighty","Ninety"]
        sc = ["","Thousand","Million","Billion"]
        def h(num):
            r = ""
            if num >= 100: r += o[num//100] + " Hundred"; num %= 100
            if num and r: r += " "
            if num >= 20: r += t[num//10]; num %= 10
            if num and r: r += " "
            if num > 0: r += o[num]
            return r.strip()
        ip = int(n)
        dp = min(int(round((n - ip) * 100)), 99)
        if ip == 0: w = "Zero"
        else:
            w = ""; i = 0
            while ip > 0:
                ck = ip % 1000
                if ck:
                    cw = h(ck)
                    if sc[i]: cw += " " + sc[i]
                    w = cw + (" " + w if w else "")
                ip //= 1000; i += 1
        if dp: w += f" and {dp:02d}/100"
        return "AED " + w + " Only"

    els.append(Spacer(1, 4*mm))
    ab = Table([[Paragraph(f"<b>Amount in Words:</b> {n2w(tot)}", S("AW", fontSize=9, textColor=C4, leading=13))]], colWidths=[W])
    ab.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),BG),("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    els.append(ab)

    if inv["notes"]:
        els.append(Spacer(1, 3*mm))
        nb = Table([[Paragraph(f"<b>Notes:</b> {inv['notes']}", S("NW", fontSize=9, textColor=C4, leading=13))]], colWidths=[W])
        nb.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#f8fafc")),("BOX",(0,0),(-1,-1),0.5,colors.HexColor("#e2e8f0")),("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
        els.append(nb)

    # ═══════════════════════════════════
    # 6. BANK DETAILS (single column label-value pairs)
    # ═══════════════════════════════════
    if company and (company["bank_name"] or company["bank_account_name"] or company["bank_account_number"] or company["iban"]):
        bk_items = []
        if company["bank_name"]: bk_items.append(("Bank", company["bank_name"]))
        if company["bank_account_name"]: bk_items.append(("Account", company["bank_account_name"]))
        if company["bank_account_number"]: bk_items.append(("A/C No.", company["bank_account_number"]))
        if company["iban"]: bk_items.append(("IBAN", company["iban"]))
        if company["swift_code"]: bk_items.append(("Swift", company["swift_code"]))
        if bk_items:
            els.append(Spacer(1, 2*mm))
            els.append(Paragraph("<b>BANK DETAILS</b>", S("BD", fontSize=8, fontName="Helvetica-Bold", textColor=C5, leading=10, spaceAfter=2)))
            bk_rows = [[
                Paragraph(f"<font color='#64748b'>{lbl}:</font>", S("_bkl", fontSize=8, textColor=C5, leading=12)),
                Paragraph(f"<b>{val}</b>", S("_bkv", fontSize=8, fontName="Helvetica-Bold", textColor=C4, leading=12)),
            ] for lbl, val in bk_items]
            bkt = Table(bk_rows, colWidths=[22*mm, W - 22*mm])
            bkt.setStyle(TableStyle([
                ("VALIGN",(0,0),(-1,-1),"TOP"),
                ("TOPPADDING",(0,0),(-1,-1),1.5), ("BOTTOMPADDING",(0,0),(-1,-1),1.5),
                ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
            ]))
            els.append(bkt)

    # ═══════════════════════════════════
    # 7. SIGNATURES
    # ═══════════════════════════════════
    els.append(Spacer(1, 10*mm))
    sg = ParagraphStyle("SG", fontSize=9, alignment=TA_CENTER, leading=14)
    sgt = Table([[
        Paragraph("_________________________<br/><br/><b>Authorized Signatory</b><br/><font size=7 color='#6b7280'>Stamp</font>", sg),
        C("", fontSize=4),
        Paragraph("_________________________<br/><br/><b>Customer Signature</b><br/><font size=7 color='#6b7280'>Accepted By</font>", sg),
    ]], colWidths=[W*0.35, W*0.30, W*0.35])
    sgt.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LINEABOVE",(0,0),(0,0),0.5,C5), ("LINEABOVE",(2,0),(2,0),0.5,C5),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
    ]))
    els.append(sgt)

    # ═══════════════════════════════════
    # 8. FOOTER
    # ═══════════════════════════════════
    els.append(Spacer(1, 8*mm))
    pp = []
    if company:
        parts = []
        if company["bank_name"]: parts.append(f"Bank: <b>{company['bank_name']}</b>")
        if company["bank_account_number"]: parts.append(f"A/C: <b>{company['bank_account_number']}</b>")
        if company["iban"]: parts.append(f"IBAN: <b>{company['iban']}</b>")
        if parts:
            pp.append(Paragraph("Payable at: " + " | ".join(parts), S("FP", fontSize=7.5, textColor=C4, alignment=TA_CENTER, leading=10)))

    pp.append(Paragraph(
        "This is a computer-generated Tax Invoice. Valid without signature.",
        S("FN", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=9)))

    fh = Table([[""]], colWidths=[W], rowHeights=[0.5])
    fh.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(fh)
    els.append(Spacer(1, 2*mm))
    for p in pp:
        els.append(p)
        els.append(Spacer(1, 1*mm))

    doc.build(els)
    for f in _logo_tmp_files:
        try: os.remove(f)
        except: pass
    pdf_data = buf.getvalue(); buf.close()
    return send_file(BytesIO(pdf_data), mimetype="application/pdf", as_attachment=True, download_name=f"Invoice_{inv_no}.pdf")

@customer_bp.route("/<int:cid>/invoice/<int:iid>/delete", methods=["POST"])
def customer_invoice_delete(cid, iid):
    db = _get_db()
    db.execute("DELETE FROM customer_invoice_items WHERE invoice_id=?", (iid,))
    db.execute("DELETE FROM customer_invoices WHERE id=? AND customer_id=?", (iid, cid))
    db.commit()
    db.close()
    flash("Invoice deleted.", "success")
    return redirect(url_for("customer.customer_profile", cid=cid, tab="invoices"))

# ─── CREDIT NOTES ───

@customer_bp.route("/<int:cid>/credit-note/add", methods=["GET", "POST"])
def customer_credit_note_add(cid):
    _ensure_tables()
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    db = _get_db()
    invoices = db.execute("SELECT id,invoice_no,total_amount,invoice_date FROM customer_invoices WHERE customer_id=? ORDER BY invoice_date DESC", (cid,)).fetchall()

    if request.method == "POST":
        cn_date = request.form.get("credit_note_date", date.today().isoformat())
        cn_no = request.form.get("credit_note_no", "").strip()
        inv_id = request.form.get("invoice_id") or None
        amount = float(request.form.get("amount", 0) or 0)
        vat_pct = float(request.form.get("vat_percent", 0) or 0)
        reason = request.form.get("reason", "").strip()
        notes = request.form.get("notes", "").strip()

        if not cn_no:
            flash("Credit note number is required.", "error")
            db.close()
            return render_template("customer/credit_note_form.html", c=c, invoices=invoices, today=date.today().isoformat())
        if amount <= 0:
            flash("Amount must be greater than zero.", "error")
            db.close()
            return render_template("customer/credit_note_form.html", c=c, invoices=invoices, today=date.today().isoformat())

        vat_amt = round(amount * vat_pct / 100, 2)
        total = round(amount + vat_amt, 2)

        db.execute(
            "INSERT INTO customer_credit_notes (customer_id, credit_note_no, credit_note_date, invoice_id, amount, vat_percent, vat_amount, total_amount, reason, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cid, cn_no, cn_date, inv_id, amount, vat_pct, vat_amt, total, reason or None, notes or None),
        )
        db.commit()
        db.close()
        flash(f"Credit Note {cn_no} created.", "success")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="credit_notes"))

    db.close()
    return render_template("customer/credit_note_form.html", c=c, invoices=invoices, today=date.today().isoformat())

@customer_bp.route("/<int:cid>/credit-note/<int:cnid>/delete", methods=["POST"])
def customer_credit_note_delete(cid, cnid):
    _ensure_tables()
    db = _get_db()
    row = db.execute("SELECT credit_note_no FROM customer_credit_notes WHERE id=? AND customer_id=?", (cnid, cid)).fetchone()
    if row:
        db.execute("DELETE FROM customer_credit_notes WHERE id=?", (cnid,))
        db.commit()
        flash(f"Credit Note {row['credit_note_no']} deleted.", "success")
    else:
        flash("Credit note not found.", "error")
    db.close()
    return redirect(url_for("customer.customer_profile", cid=cid, tab="credit_notes"))

# ─── PAYMENTS ───

@customer_bp.route("/<int:cid>/payment/add", methods=["GET", "POST"])
def customer_payment_add(cid):
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    db = _get_db()
    invoices_raw = db.execute(
        "SELECT i.id,i.invoice_no,i.invoice_date,i.total_amount,COALESCE(SUM(p.amount),0) AS paid FROM customer_invoices i LEFT JOIN customer_payments p ON p.invoice_id=i.id WHERE i.customer_id=? GROUP BY i.id ORDER BY i.invoice_date DESC",
        (cid,),
    ).fetchall()
    invoices = []
    for inv in invoices_raw:
        d = dict(inv)
        d["balance"] = round(d["total_amount"] - d["paid"], 2)
        invoices.append(d)
    total_balance = round(sum(d["total_amount"] for d in invoices) - sum(d["paid"] for d in invoices), 2)
    if request.method == "POST":
        pmt_date = request.form.get("payment_date", date.today().isoformat())
        method = request.form.get("payment_method", "Cheque")
        ref = request.form.get("reference_no", "").strip()
        notes = request.form.get("notes", "").strip()
        inv_ids = request.form.getlist("inv_ids")
        created_ids = []
        total_alloc = 0
        for inv_id in inv_ids:
            alloc_key = f"alloc_{inv_id}"
            alloc_amt = float(request.form.get(alloc_key, 0) or 0)
            if alloc_amt > 0:
                cur = db.execute(
                    "INSERT INTO customer_payments (customer_id,invoice_id,payment_date,amount,payment_method,reference_no,notes) VALUES (?,?,?,?,?,?,?)",
                    (cid, int(inv_id), pmt_date, alloc_amt, method, ref or None, notes or None),
                )
                created_ids.append(str(cur.lastrowid))
                total_alloc += alloc_amt
        if created_ids:
            db.commit()
            ids_param = ",".join(created_ids)
            flash(f"Payment of AED {total_alloc:.2f} recorded.", "success")
            undo_url = url_for('customer.customer_payment_undo', cid=cid, ids=ids_param)
            flash(Markup(f'<a href="{undo_url}" style="color:#fff;text-decoration:underline;font-weight:700">Undo this payment</a>'), "info")
        else:
            flash("No amount allocated to any invoice.", "error")
        db.close()
        return redirect(url_for("customer.customer_profile", cid=cid, tab="payments"))
    db.close()
    return render_template("customer/payment_form.html", c=c, invoices=invoices, today=date.today().isoformat(), balance=total_balance)

@customer_bp.route("/<int:cid>/payment/undo")
def customer_payment_undo(cid):
    ids_str = request.args.get("ids", "")
    if ids_str:
        db = _get_db()
        ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
        for pid in ids:
            db.execute("DELETE FROM customer_payments WHERE id=? AND customer_id=?", (pid, cid))
        db.commit()
        db.close()
        flash(f"Payment undone — {len(ids)} record(s) deleted.", "warning")
    return redirect(url_for("customer.customer_profile", cid=cid, tab="payments"))

@customer_bp.route("/<int:cid>/payment/<int:pid>/delete", methods=["POST"])
def customer_payment_delete(cid, pid):
    db = _get_db()
    db.execute("DELETE FROM customer_payments WHERE id=? AND customer_id=?", (pid, cid))
    db.commit()
    db.close()
    flash("Payment deleted.", "success")
    return redirect(url_for("customer.customer_profile", cid=cid, tab="payments"))

# ─── CONTRACTS ───

@customer_bp.route("/<int:cid>/contract/add", methods=["GET", "POST"])
def customer_contract_add(cid):
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    db = _get_db()
    if request.method == "POST":
        db.execute("INSERT INTO customer_contracts (customer_id,contract_no,contract_date,start_date,end_date,contract_type,amount,status,notes) VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, request.form.get("contract_no"), request.form.get("contract_date", date.today().isoformat()),
             request.form.get("start_date"), request.form.get("end_date"), request.form.get("contract_type", "rental"),
             float(request.form.get("amount", 0) or 0), request.form.get("status", "active"), request.form.get("notes")))
        db.commit()
        db.close()
        flash("Contract added.", "success")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="contracts"))
    db.close()
    return render_template("customer/contract_form.html", c=c, contract={}, today=date.today().isoformat())

@customer_bp.route("/<int:cid>/contract/<int:ctid>/close", methods=["POST"])
def customer_contract_close(cid, ctid):
    db = _get_db()
    db.execute("UPDATE customer_contracts SET status='closed' WHERE id=? AND customer_id=?", (ctid, cid))
    db.commit()
    db.close()
    flash("Contract closed.", "success")
    return redirect(url_for("customer.customer_profile", cid=cid, tab="contracts"))

# ─── QUOTATIONS ───

@customer_bp.route("/<int:cid>/quotation/add", methods=["GET", "POST"])
def customer_quotation_add(cid):
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    db = _get_db()
    if request.method == "POST":
        db.execute("INSERT INTO customer_quotations (customer_id,quotation_no,quotation_date,amount,status,notes) VALUES (?,?,?,?,?,?)",
            (cid, request.form.get("quotation_no"), request.form.get("quotation_date", date.today().isoformat()),
             float(request.form.get("amount", 0) or 0), request.form.get("status", "pending"), request.form.get("notes")))
        db.commit()
        db.close()
        flash("Quotation added.", "success")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="quotations"))
    db.close()
    return render_template("customer/quotation_form.html", c=c, q={}, today=date.today().isoformat())

@customer_bp.route("/<int:cid>/quotation/<int:qid>/delete", methods=["POST"])
def customer_quotation_delete(cid, qid):
    db = _get_db()
    db.execute("DELETE FROM customer_quotations WHERE id=? AND customer_id=?", (qid, cid))
    db.commit()
    db.close()
    flash("Quotation deleted.", "success")
    return redirect(url_for("customer.customer_profile", cid=cid, tab="quotations"))

# ─── LPOs ───

@customer_bp.route("/<int:cid>/lpo/add", methods=["GET", "POST"])
def customer_lpo_add(cid):
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    db = _get_db()
    if request.method == "POST":
        db.execute("INSERT INTO customer_lpos (customer_id,lpo_no,lpo_date,amount,status,notes) VALUES (?,?,?,?,?,?)",
            (cid, request.form.get("lpo_no"), request.form.get("lpo_date", date.today().isoformat()),
             float(request.form.get("amount", 0) or 0), request.form.get("status", "pending"), request.form.get("notes")))
        db.commit()
        db.close()
        flash("LPO added.", "success")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="lpos"))
    db.close()
    return render_template("customer/lpo_form.html", c=c, lpo={}, today=date.today().isoformat())

@customer_bp.route("/<int:cid>/lpo/<int:lid>/close", methods=["POST"])
def customer_lpo_close(cid, lid):
    db = _get_db()
    db.execute("UPDATE customer_lpos SET status='closed' WHERE id=? AND customer_id=?", (lid, cid))
    db.commit()
    db.close()
    flash("LPO closed.", "success")
    return redirect(url_for("customer.customer_profile", cid=cid, tab="lpos"))

# ─── DOCUMENTS ───

@customer_bp.route("/<int:cid>/doc/add", methods=["GET", "POST"])
def customer_doc_add(cid):
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    if request.method == "POST":
        doc_type = request.form.get("doc_type", "Other")
        doc_name = request.form.get("doc_name", "").strip()
        expiry = request.form.get("expiry_date", "").strip() or None
        file = request.files.get("file")
        file_data = None
        file_type = None
        if file and file.filename:
            file_data = base64.b64encode(file.read()).decode("utf-8")
            file_type = file.content_type
        db = _get_db()
        db.execute("INSERT INTO customer_documents (customer_id,doc_type,doc_name,file_data,file_type,expiry_date) VALUES (?,?,?,?,?,?)",
            (cid, doc_type, doc_name, file_data, file_type, expiry))
        db.commit()
        db.close()
        flash("Document uploaded.", "success")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="documents"))
    return render_template("customer/doc_form.html", c=c)

@customer_bp.route("/<int:cid>/doc/<int:did>/download")
def customer_doc_download(cid, did):
    db = _get_db()
    doc = db.execute("SELECT * FROM customer_documents WHERE id=? AND customer_id=?", (did, cid)).fetchone()
    db.close()
    if not doc or not doc["file_data"]:
        flash("Document not found.", "error")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="documents"))
    import io
    data = base64.b64decode(doc["file_data"])
    return send_file(io.BytesIO(data), mimetype=doc["file_type"] or "application/octet-stream",
        as_attachment=True, download_name=doc["doc_name"] or f"doc_{did}")

@customer_bp.route("/<int:cid>/doc/<int:did>/delete", methods=["POST"])
def customer_doc_delete(cid, did):
    db = _get_db()
    db.execute("DELETE FROM customer_documents WHERE id=? AND customer_id=?", (did, cid))
    db.commit()
    db.close()
    flash("Document deleted.", "success")
    return redirect(url_for("customer.customer_profile", cid=cid, tab="documents"))

# ─── KATA / STATEMENT ───

@customer_bp.route("/<int:cid>/kata")
def customer_kata(cid):
    _ensure_tables()
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    from_date = request.args.get("from", "")
    to_date = request.args.get("to", "")
    db = _get_db()
    entries = []
    inv_q = """SELECT i.id, i.invoice_date as d, i.invoice_no as ref, i.total_amount as dr,
                      COALESCE((SELECT SUM(p2.amount) FROM customer_payments p2 WHERE p2.invoice_id = i.id),0) as cr
               FROM customer_invoices i WHERE i.customer_id=?"""
    inv_p = [cid]
    if from_date: inv_q += " AND i.invoice_date>=?"; inv_p.append(from_date)
    if to_date: inv_q += " AND i.invoice_date<=?"; inv_p.append(to_date)
    inv_q += " ORDER BY i.invoice_date, i.id"
    for inv in db.execute(inv_q, inv_p).fetchall():
        d = dict(inv)
        d["type"] = "Invoice"
        entries.append(d)
    cn_q = "SELECT credit_note_date as d, credit_note_no as ref, 'Credit Note' as type, 0 as dr, total_amount as cr FROM customer_credit_notes WHERE customer_id=?"
    cn_p = [cid]
    if from_date: cn_q += " AND credit_note_date>=?"; cn_p.append(from_date)
    if to_date: cn_q += " AND credit_note_date<=?"; cn_p.append(to_date)
    cn_q += " ORDER BY credit_note_date"
    for cn in db.execute(cn_q, cn_p).fetchall():
        entries.append(dict(cn))
    unalloc_pmt_q = "SELECT payment_date as d, reference_no as ref, 'Unallocated Payment' as type, 0 as dr, amount as cr FROM customer_payments WHERE customer_id=? AND invoice_id IS NULL"
    unalloc_pmt_p = [cid]
    if from_date: unalloc_pmt_q += " AND payment_date>=?"; unalloc_pmt_p.append(from_date)
    if to_date: unalloc_pmt_q += " AND payment_date<=?"; unalloc_pmt_p.append(to_date)
    unalloc_pmt_q += " ORDER BY payment_date"
    for pmt in db.execute(unalloc_pmt_q, unalloc_pmt_p).fetchall():
        entries.append(dict(pmt))
    entries.sort(key=lambda x: (x.get("d",""), x.get("type","")))
    balance = 0
    for e in entries:
        balance += (e.get("dr",0) or 0) - (e.get("cr",0) or 0)
        e["bal"] = round(balance, 2)
    db.close()
    return render_template("customer/kata.html", c=c, entries=entries, from_date=from_date, to_date=to_date)

@customer_bp.route("/<int:cid>/soa/pdf")
def customer_soa_pdf(cid):
    _ensure_tables()
    import tempfile
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from io import BytesIO

    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    from_date = request.args.get("from", "")
    to_date = request.args.get("to", "")
    db = _get_db()
    company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    entries = []
    inv_q = """SELECT i.id, i.invoice_date as d, i.invoice_no as ref, i.total_amount as dr,
                      COALESCE((SELECT SUM(p2.amount) FROM customer_payments p2 WHERE p2.invoice_id = i.id),0) as cr
               FROM customer_invoices i WHERE i.customer_id=?"""
    inv_p = [cid]
    if from_date: inv_q += " AND i.invoice_date>=?"; inv_p.append(from_date)
    if to_date: inv_q += " AND i.invoice_date<=?"; inv_p.append(to_date)
    inv_q += " ORDER BY i.invoice_date, i.id"
    for inv in db.execute(inv_q, inv_p).fetchall():
        d = dict(inv)
        d["type"] = "Invoice"
        entries.append(d)
    cn_q = "SELECT credit_note_date as d, credit_note_no as ref, 'Credit Note' as type, 0 as dr, total_amount as cr FROM customer_credit_notes WHERE customer_id=?"
    cn_p = [cid]
    if from_date: cn_q += " AND credit_note_date>=?"; cn_p.append(from_date)
    if to_date: cn_q += " AND credit_note_date<=?"; cn_p.append(to_date)
    cn_q += " ORDER BY credit_note_date"
    for cn in db.execute(cn_q, cn_p).fetchall():
        entries.append(dict(cn))
    unalloc_pmt_q = "SELECT payment_date as d, reference_no as ref, 'Unallocated Payment' as type, 0 as dr, amount as cr FROM customer_payments WHERE customer_id=? AND invoice_id IS NULL"
    unalloc_pmt_p = [cid]
    if from_date: unalloc_pmt_q += " AND payment_date>=?"; unalloc_pmt_p.append(from_date)
    if to_date: unalloc_pmt_q += " AND payment_date<=?"; unalloc_pmt_p.append(to_date)
    unalloc_pmt_q += " ORDER BY payment_date"
    for pmt in db.execute(unalloc_pmt_q, unalloc_pmt_p).fetchall():
        entries.append(dict(pmt))
    entries.sort(key=lambda x: (x.get("d",""), x.get("type","")))
    bal = 0
    for e in entries:
        bal += (e.get("dr",0) or 0) - (e.get("cr",0) or 0)
        e["bal"] = round(bal, 2)
    db.close()
    total_dr = sum(e.get("dr",0) or 0 for e in entries)
    total_cr = sum(e.get("cr",0) or 0 for e in entries)
    closing = round(total_dr - total_cr, 2)

    _logo_tmp_files = []
    buf = BytesIO()
    LM, RM, TM, BM = 18*mm, 18*mm, 15*mm, 15*mm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM

    tc = company["theme_color"] or "#1a3a5c" if company else "#1a3a5c"
    try: TH = colors.HexColor(tc)
    except: TH = colors.HexColor("#1a3a5c")
    BG = colors.HexColor("#f4f6f9"); WH = colors.white; C3 = colors.HexColor("#d1d5db")
    C4 = colors.HexColor("#111827"); C5 = colors.HexColor("#6b7280"); CG = colors.HexColor("#1a7d1a")
    CR = colors.HexColor("#c62828")

    def F(name, **kw):
        kw.setdefault("fontSize", 8); kw.setdefault("leading", 12)
        return ParagraphStyle(name, **kw)

    els = []
    cn = company["company_name"] if company else "COMPANY"
    trn = company["trn_no"] or "—" if company else "—"

    # ══════════════════════════════
    # HEADER (matches invoice style)
    # ══════════════════════════════
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

    # ══════════════════════════════
    # CUSTOMER INFO
    # ══════════════════════════════
    cinfo = [
        [Paragraph("<b>Customer</b>", F("_cl", fontSize=8, fontName="Helvetica-Bold", textColor=C4, leading=11)),
         Paragraph(f"<b>{c['customer_name']}</b>", F("_cv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=12))],
    ]
    if c["trn"]: cinfo.append([Paragraph("TRN", F("_l", fontSize=7.5, textColor=C5, leading=10)), Paragraph(c["trn"], F("_v", fontSize=8.5, textColor=C4, leading=11))])
    if c["address"]: cinfo.append([Paragraph("Address", F("_l", fontSize=7.5, textColor=C5, leading=10)), Paragraph(c["address"], F("_v", fontSize=8.5, textColor=C4, leading=11))])
    if c["phone"]: cinfo.append([Paragraph("Phone", F("_l", fontSize=7.5, textColor=C5, leading=10)), Paragraph(c["phone"], F("_v", fontSize=8.5, textColor=C4, leading=11))])
    ct = Table(cinfo, colWidths=[50, W - 50])
    ct.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ct)

    # ══════════════════════════════
    # SUMMARY CARDS
    # ══════════════════════════════
    els.append(Spacer(1, 3*mm))
    sdata = [[
        Paragraph(f"<b>Total Invoiced</b><br/><font size=10 color='#1a3a5c'>AED {total_dr:,.2f}</font>", F("_s1", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Total Paid</b><br/><font size=10 color='#1a7d1a'>AED {total_cr:,.2f}</font>", F("_s2", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Outstanding</b><br/><font size=10 color='#c62828'>AED {closing if closing > 0 else 0:,.2f}</font>", F("_s3", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Transactions</b><br/><font size=10>{len(entries)}</font>", F("_s4", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
    ]]
    st = Table(sdata, colWidths=[W/4, W/4, W/4, W/4])
    st.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5),
        ("BACKGROUND",(0,0),(-1,-1),BG),
    ]))
    els.append(st)
    els.append(Spacer(1, 3*mm))

    if from_date or to_date:
        rng = f"Period: {from_date or '…'} to {to_date or '…'}"
        els.append(Paragraph(
            f"<font size=7 color='#6b7280'>{rng}</font>",
            F("_pr", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=9)))
        els.append(Spacer(1, 2*mm))

    # ══════════════════════════════
    # STATEMENT TABLE
    # ══════════════════════════════
    colw = [45, 38, 65, 38, W - 45 - 38 - 65 - 38 - 65 - 75, 65, 75]
    hdr = [
        Paragraph("<b>Date</b>", F("_h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=10)),
        Paragraph("<b>Month</b>", F("_h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=10)),
        Paragraph("<b>Invoice #</b>", F("_h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, leading=10)),
        Paragraph("<b>Type</b>", F("_h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=10)),
        Paragraph("<b>Dr (AED)</b>", F("_h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        Paragraph("<b>Cr (AED)</b>", F("_h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        Paragraph("<b>Balance (AED)</b>", F("_h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
    ]
    rws = [hdr]
    rws.append([
        Paragraph("", F("_o", fontSize=7, leading=10)), Paragraph("", F("_o")),
        Paragraph("", F("_o")), Paragraph("Opening Balance", F("_ol", fontSize=7, textColor=C5, leading=10)),
        Paragraph("", F("_o")), Paragraph("", F("_o")),
        Paragraph("<b>0.00</b>", F("_ob", fontSize=7, fontName="Helvetica-Bold", textColor=C4, alignment=TA_RIGHT, leading=10)),
    ])
    for e in entries:
        d = str(e.get("d",""))
        month = d[:7] if d and len(d) >= 7 else ""
        bal_val = e.get("bal",0) or 0
        bal_display = "0.00" if bal_val <= 0 else f"{bal_val:,.2f}"
        bal_color = "#c62828" if bal_val > 0 else "#1a7d1a"
        rws.append([
            Paragraph(d, F("_d", fontSize=7, leading=10)),
            Paragraph(f"<font color='{C5}'>{month}</font>" if month else "", F("_m", fontSize=6.5, textColor=C5, leading=10)),
            Paragraph(str(e.get("ref","—")), F("_r", fontSize=7, fontName="Helvetica-Bold", textColor=C4, leading=10)),
            Paragraph(f"<font color=\"{'#1a56db' if e['type']=='Invoice' else '#e65100' if e['type']=='Credit Note' else '#c62828' if e['type']=='Unallocated Payment' else '#1a7d1a'}\">{e['type']}</font>", F("_t", fontSize=7, alignment=TA_CENTER, leading=10)),
            Paragraph(f"<b>{e.get('dr',0) or 0:,.2f}</b>" if e.get("dr") else '<font color="#cccccc">—</font>', F("_dr", fontSize=7, textColor="#c62828" if e.get("dr") else C5, alignment=TA_RIGHT, leading=10)),
            Paragraph(f"<b>{e.get('cr',0) or 0:,.2f}</b>" if e.get("cr") else '<font color="#cccccc">—</font>', F("_cr", fontSize=7, textColor="#1a7d1a" if e.get("cr") else C5, alignment=TA_RIGHT, leading=10)),
            Paragraph(f"<b>{bal_display}</b>", F("_bl", fontSize=7, fontName="Helvetica-Bold", textColor=bal_color, alignment=TA_RIGHT, leading=10)),
        ])

    # ── CLOSING ROW (inside main table for perfect alignment) ──
    rws.append([
        Paragraph("<b>Closing Balance</b>", F("_cb", fontSize=8, fontName="Helvetica-Bold", textColor=WH, leading=11)),
        Paragraph("", F("_x", fontSize=7, leading=10)),
        Paragraph("", F("_x", fontSize=7, leading=10)),
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

    # ══════════════════════════════
    # FOOTER
    # ══════════════════════════════
    els.append(Spacer(1, 8*mm))
    fh = Table([[""]], colWidths=[W], rowHeights=[0.5])
    fh.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(fh)
    els.append(Spacer(1, 2*mm))
    ft_txt = "This is a computer-generated Statement of Account."
    if from_date or to_date:
        rng = f"Period: {from_date or '…'} to {to_date or '…'}"
        ft_txt += f" | {rng}"
    els.append(Paragraph(ft_txt, F("_ft", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=9)))

    doc.build(els)
    for f in _logo_tmp_files:
        try: os.remove(f)
        except: pass
    pdf_data = buf.getvalue(); buf.close()
    return send_file(BytesIO(pdf_data), mimetype="application/pdf", as_attachment=True, download_name=f"SOA_{c['customer_name']}.pdf")

# ─── LIST ───

@customer_bp.route("/list")
def customer_list():
    _ensure_tables()
    db = _get_db()
    search = request.args.get("search", "").strip()
    if search:
        customers = db.execute("SELECT * FROM customers WHERE customer_name LIKE ? OR phone LIKE ? OR email LIKE ? ORDER BY customer_name",
            (f"%{search}%", f"%{search}%", f"%{search}%")).fetchall()
    else:
        customers = db.execute("SELECT * FROM customers ORDER BY customer_name").fetchall()
    db.close()
    return render_template("customer/list.html", customers=customers, search=search)


# ═══════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════

@customer_bp.route("/settings", methods=["GET", "POST"])
def settings():
    _ensure_tables()
    db = _get_db()
    db.execute("CREATE TABLE IF NOT EXISTS company_profile (id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT)")
    for col, dtype in [("legal_name", "TEXT"), ("trade_license_no", "TEXT"), ("trade_license_expiry", "TEXT"),
                       ("trn_no", "TEXT"), ("vat_status", "TEXT"), ("phone_number", "TEXT"),
                       ("email", "TEXT"), ("address", "TEXT"), ("bank_name", "TEXT"),
                       ("bank_account_name", "TEXT"), ("bank_account_number", "TEXT"), ("iban", "TEXT"),
                       ("swift_code", "TEXT"), ("invoice_terms", "TEXT"), ("base_currency", "TEXT"),
                       ("financial_year_label", "TEXT"), ("financial_year_start", "TEXT"),
                       ("financial_year_end", "TEXT"), ("logo_data", "TEXT"), ("logo_type", "TEXT"),
                       ("theme_color", "TEXT DEFAULT '#0F2B52'")]:
        try:
            db.execute(f"ALTER TABLE company_profile ADD COLUMN {col} {dtype}")
        except Exception:
            pass
    company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "save_company":
            name = request.form.get("company_name", "").strip()
            if company:
                db.execute("""UPDATE company_profile SET company_name=?,legal_name=?,trade_license_no=?,trade_license_expiry=?,
                    trn_no=?,vat_status=?,phone_number=?,email=?,address=?,bank_name=?,bank_account_name=?,
                    bank_account_number=?,iban=?,swift_code=?,invoice_terms=?,base_currency=?,
                    financial_year_label=?,financial_year_start=?,financial_year_end=? WHERE id=?""",
                    (name, request.form.get("legal_name"), request.form.get("trade_license_no"),
                     request.form.get("trade_license_expiry"), request.form.get("trn_no"),
                     request.form.get("vat_status", "Registered"), request.form.get("phone_number"),
                     request.form.get("email"), request.form.get("address"), request.form.get("bank_name"),
                     request.form.get("bank_account_name"), request.form.get("bank_account_number"),
                     request.form.get("iban"), request.form.get("swift_code"),
                     request.form.get("invoice_terms"), request.form.get("base_currency", "AED"),
                     request.form.get("financial_year_label"), request.form.get("financial_year_start"),
                     request.form.get("financial_year_end"), company["id"]))
            else:
                db.execute("""INSERT INTO company_profile (company_name,legal_name,trade_license_no,trade_license_expiry,
                    trn_no,vat_status,phone_number,email,address,bank_name,bank_account_name,
                    bank_account_number,iban,swift_code,invoice_terms,base_currency,
                    financial_year_label,financial_year_start,financial_year_end)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (name, request.form.get("legal_name"), request.form.get("trade_license_no"),
                     request.form.get("trade_license_expiry"), request.form.get("trn_no"),
                     request.form.get("vat_status", "Registered"), request.form.get("phone_number"),
                     request.form.get("email"), request.form.get("address"), request.form.get("bank_name"),
                     request.form.get("bank_account_name"), request.form.get("bank_account_number"),
                     request.form.get("iban"), request.form.get("swift_code"),
                     request.form.get("invoice_terms"), request.form.get("base_currency", "AED"),
                     request.form.get("financial_year_label"), request.form.get("financial_year_start"),
                     request.form.get("financial_year_end")))
            db.commit()
            flash("Company details saved.", "success")
        elif action == "save_bank":
            if company:
                db.execute("""UPDATE company_profile SET bank_name=?,bank_account_name=?,bank_account_number=?,iban=?,swift_code=? WHERE id=?""",
                    (request.form.get("bank_name"), request.form.get("bank_account_name"),
                     request.form.get("bank_account_number"), request.form.get("iban"),
                     request.form.get("swift_code"), company["id"]))
            else:
                db.execute("""INSERT INTO company_profile (company_name,bank_name,bank_account_name,bank_account_number,iban,swift_code)
                    VALUES ('My Company',?,?,?,?,?)""",
                    (request.form.get("bank_name"), request.form.get("bank_account_name"),
                     request.form.get("bank_account_number"), request.form.get("iban"),
                     request.form.get("swift_code")))
            db.commit()
            flash("Bank details saved.", "success")
        elif action == "save_logo":
            file = request.files.get("logo_file")
            if file and file.filename:
                logo_data = base64.b64encode(file.read()).decode("utf-8")
                logo_type = file.content_type
                if company:
                    db.execute("UPDATE company_profile SET logo_data=?,logo_type=? WHERE id=?", (logo_data, logo_type, company["id"]))
                else:
                    db.execute("INSERT INTO company_profile (company_name,logo_data,logo_type) VALUES ('My Company',?,?)", (logo_data, logo_type))
                db.commit()
                flash("Logo updated.", "success")
        elif action == "remove_logo":
            if company:
                db.execute("UPDATE company_profile SET logo_data=NULL,logo_type=NULL WHERE id=?", (company["id"],))
                db.commit()
                flash("Logo removed.", "success")
        elif action == "save_theme":
            theme_color = request.form.get("theme_color", "#0F2B52").strip()
            if company:
                db.execute("UPDATE company_profile SET theme_color=? WHERE id=?", (theme_color, company["id"]))
            else:
                db.execute("INSERT INTO company_profile (company_name,theme_color) VALUES ('My Company',?)", (theme_color,))
            db.commit()
            flash("Theme updated.", "success")
        db.close()
        return redirect(url_for("customer.settings"))
    company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    db.close()
    return render_template("customer/settings.html", company=company)

@customer_bp.route("/download-backup")
def download_db_backup():
    import glob
    from ..backup_service import create_backup_now, latest_backup_file
    root = current_app.config.get("GENERATED_BACKUP_DIR") or os.path.join(os.path.dirname(current_app.config.get("DATABASE", "payroll.db")), "backups")
    if not os.path.isdir(root):
        os.makedirs(root, exist_ok=True)
    files = sorted(glob.glob(os.path.join(root, "**", "*.sql"), recursive=True) + glob.glob(os.path.join(root, "**", "*.zip"), recursive=True), key=os.path.getmtime, reverse=True)
    if not files:
        result = create_backup_now("daily", current_app)
        if not result["ok"]:
            flash(result["message"], "error")
            return redirect(url_for("customer.settings"))
    files = sorted(glob.glob(os.path.join(root, "**", "*.sql"), recursive=True) + glob.glob(os.path.join(root, "**", "*.zip"), recursive=True), key=os.path.getmtime, reverse=True)
    if not files:
        flash("No backup file available.", "error")
        return redirect(url_for("customer.settings"))
    return send_file(files[0], as_attachment=True)

@customer_bp.route("/tax-report")
def customer_tax_report():
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
    customers = db.execute(f"""
        SELECT c.id, c.customer_name, c.trn, c.customer_code, c.status,
               COUNT(i.id) AS invoice_count,
               COALESCE(SUM(i.amount),0) AS total_taxable,
               COALESCE(SUM(i.vat_amount),0) AS total_vat,
               COALESCE(SUM(i.total_amount),0) AS total_invoiced
        FROM customers c
        LEFT JOIN customer_invoices i ON i.customer_id = c.id {where}
        GROUP BY c.id
        ORDER BY c.customer_name
    """, params).fetchall()
    invoices = db.execute(f"""
        SELECT i.invoice_date, i.invoice_no, c.customer_name,
               i.amount AS net_sale, i.vat_amount, i.total_amount
        FROM customer_invoices i
        JOIN customers c ON c.id = i.customer_id
        WHERE 1=1 {where.replace('i.','')}
        ORDER BY i.invoice_date DESC, i.invoice_no DESC
    """, params).fetchall()
    invoices_where = ""
    invoices_params = []
    if from_filter:
        invoices_where += " AND i.invoice_date >= ?"
        invoices_params.append(from_filter)
    if to_filter:
        invoices_where += " AND i.invoice_date <= ?"
        invoices_params.append(to_filter)
    invoices = db.execute(f"""
        SELECT i.invoice_date, i.invoice_no, c.customer_name,
               i.amount AS net_sale, i.vat_amount, i.total_amount
        FROM customer_invoices i
        JOIN customers c ON c.id = i.customer_id
        WHERE 1=1 {invoices_where}
        ORDER BY i.invoice_date DESC, i.invoice_no DESC
    """, invoices_params).fetchall()
    total_taxable = sum(r["total_taxable"] for r in customers)
    total_vat = sum(r["total_vat"] for r in customers)
    total_invoiced = sum(r["total_invoiced"] for r in customers)
    db.close()
    return render_template(
        "customer/tax_report.html",
        customers=customers,
        invoices=invoices,
        total_taxable=total_taxable,
        total_vat=total_vat,
        total_invoiced=total_invoiced,
        from_filter=from_filter,
        to_filter=to_filter,
    )

@customer_bp.route("/tax-report/export/excel")
def customer_tax_report_excel():
    _ensure_tables()
    db = _get_db()
    from_filter = request.args.get("from", "")
    to_filter = request.args.get("to", "")
    where = ""; params = []
    if from_filter: where += " AND i.invoice_date >= ?"; params.append(from_filter)
    if to_filter: where += " AND i.invoice_date <= ?"; params.append(to_filter)
    invoices = db.execute(f"""
        SELECT i.invoice_date, i.invoice_no, c.customer_name,
               i.amount AS net_sale, i.vat_amount, i.total_amount
        FROM customer_invoices i
        JOIN customers c ON c.id = i.customer_id
        WHERE 1=1 {where.replace('i.','')}
        ORDER BY i.invoice_date DESC, i.invoice_no DESC
    """, params).fetchall()
    total_taxable = sum(r["net_sale"] or 0 for r in invoices)
    total_vat = sum(r["vat_amount"] or 0 for r in invoices)
    total_invoiced = sum(r["total_amount"] or 0 for r in invoices)
    db.close()

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from io import BytesIO
    wb = Workbook()
    ws = wb.active
    ws.title = "Tax Report"

    hf = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    hfill = PatternFill("solid", fgColor="1a3a5c")
    center = Alignment(horizontal="center", vertical="center")
    right = Alignment(horizontal="right", vertical="center")
    thin = Side(style="thin", color="d8e4f5")
    border = Border(top=thin, left=thin, right=thin, bottom=thin)

    heads = ["Date", "Invoice No", "Customer", "Net Sale (AED)", "VAT (AED)", "Gross Sale (AED)"]
    for ci, h in enumerate(heads, 1):
        c = ws.cell(row=1, column=ci, value=h)
        c.font = hf; c.fill = hfill; c.alignment = center; c.border = border

    period = f"{from_filter or 'All'} to {to_filter or 'All'}"
    ws.cell(row=2, column=1, value=f"Period: {period}").font = Font(italic=True, color="6b7280", size=10)

    for ri, inv in enumerate(invoices, 3):
        vals = [inv["invoice_date"], inv["invoice_no"], inv["customer_name"],
                inv["net_sale"] or 0, inv["vat_amount"] or 0, inv["total_amount"] or 0]
        for ci, v in enumerate(vals, 1):
            c = ws.cell(row=ri, column=ci, value=v)
            c.border = border
            if ci >= 4: c.alignment = right; c.number_format = '#,##0.00'
            if ci == 5: c.font = Font(color="f7931e")

    tr = 3 + len(invoices)
    totals = ["", "", "TOTALS", total_taxable, total_vat, total_invoiced]
    tf = Font(bold=True, size=11)
    tfill = PatternFill("solid", fgColor="f5f8fe")
    for ci, v in enumerate(totals, 1):
        c = ws.cell(row=tr, column=ci, value=v)
        c.font = tf; c.fill = tfill; c.border = border
        if ci >= 4: c.alignment = right; c.number_format = '#,##0.00'

    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 30
    for col in ["D","E","F"]: ws.column_dimensions[col].width = 18

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fn = f"Tax_Report_{from_filter or 'start'}_to_{to_filter or 'end'}.xlsx"
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name=fn)

@customer_bp.route("/tax-report/export/pdf")
def customer_tax_report_pdf():
    _ensure_tables()
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from io import BytesIO

    db = _get_db()
    from_filter = request.args.get("from", "")
    to_filter = request.args.get("to", "")
    where = ""; params = []
    if from_filter: where += " AND i.invoice_date >= ?"; params.append(from_filter)
    if to_filter: where += " AND i.invoice_date <= ?"; params.append(to_filter)
    company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    invoices = db.execute(f"""
        SELECT i.invoice_date, i.invoice_no, c.customer_name,
               i.amount AS net_sale, i.vat_amount, i.total_amount
        FROM customer_invoices i
        JOIN customers c ON c.id = i.customer_id
        WHERE 1=1 {where.replace('i.','')}
        ORDER BY i.invoice_date DESC, i.invoice_no DESC
    """, params).fetchall()
    total_taxable = sum(r["net_sale"] or 0 for r in invoices)
    total_vat = sum(r["vat_amount"] or 0 for r in invoices)
    total_invoiced = sum(r["total_amount"] or 0 for r in invoices)
    db.close()

    buf = BytesIO()
    LM, RM, TM, BM = 15*mm, 15*mm, 15*mm, 15*mm
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = landscape(A4)[0] - LM - RM

    tc = company["theme_color"] or "#1a3a5c" if company else "#1a3a5c"
    try: TH = colors.HexColor(tc)
    except: TH = colors.HexColor("#1a3a5c")
    WH = colors.white; C5 = colors.HexColor("#6b7280")
    CR = colors.HexColor("#c62828")

    def F(name, **kw):
        kw.setdefault("fontSize", 7); kw.setdefault("leading", 10)
        return ParagraphStyle(name, **kw)

    els = []
    cn = company["company_name"] if company else "Tax Report"
    els.append(Paragraph(f"<b>{cn}</b>", F("T", fontSize=12, textColor=TH, spaceAfter=2)))
    period = f"Period: {from_filter or 'Start'} to {to_filter or 'End'}"
    els.append(Paragraph(period, F("P", fontSize=7, textColor=C5, spaceAfter=10)))
    els.append(Spacer(1, 3*mm))

    hdr = ["Date", "Invoice No", "Customer", "Net Sale", "VAT", "Gross Sale"]
    data = [hdr]
    for inv in invoices:
        data.append([
            inv["invoice_date"] or "—",
            inv["invoice_no"] or "—",
            inv["customer_name"],
            f"{inv['net_sale'] or 0:,.2f}",
            f"{inv['vat_amount'] or 0:,.2f}",
            f"{inv['total_amount'] or 0:,.2f}",
        ])

    data.append(["", "", "TOTALS", f"{total_taxable:,.2f}", f"{total_vat:,.2f}", f"{total_invoiced:,.2f}"])

    col_w = [W*0.12, W*0.14, W*0.30, W*0.14, W*0.14, W*0.16]
    tbl = Table(data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 7),
        ("BACKGROUND", (0,0), (-1,0), TH),
        ("TEXTCOLOR", (0,0), (-1,0), WH),
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ("ALIGN", (3,0), (-1,-1), "RIGHT"),
        ("TEXTCOLOR", (3,1), (3,-2), CR),
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
        ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#f5f8fe")),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#d8e4f5")),
    ]))
    els.append(tbl)

    doc.build(els)
    buf.seek(0)
    fn = f"Tax_Report_{from_filter or 'start'}_to_{to_filter or 'end'}.pdf"
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=fn)
