import os, base64, re, math
from datetime import date, datetime
from flask import render_template, request, redirect, url_for, flash, current_app, send_file, session, jsonify
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
    """)
    for col, dtype in [("lpo_no", "TEXT"), ("lpo_date", "TEXT")]:
        try:
            db.execute(f"ALTER TABLE customer_invoices ADD COLUMN {col} {dtype}")
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
    return f"INV-{n:02d}"

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
    _ensure_tables()
    db = _get_db()
    total = db.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    active = db.execute("SELECT COUNT(*) FROM customers WHERE status='active'").fetchone()[0]
    total_receivable = db.execute("SELECT COALESCE(SUM(total_amount),0) FROM customer_invoices").fetchone()[0]
    inv_count = db.execute("SELECT COUNT(*) FROM customer_invoices").fetchone()[0]
    recent = db.execute("""SELECT i.*, c.customer_name FROM customer_invoices i
        JOIN customers c ON i.customer_id=c.id ORDER BY i.created_at DESC LIMIT 10""").fetchall()
    db.close()
    return render_template("customer/dashboard.html", total=total, active=active,
        total_receivable=total_receivable, inv_count=inv_count, recent_invoices=recent)

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
    total_inv = db.execute("SELECT COALESCE(SUM(total_amount),0) FROM customer_invoices WHERE customer_id=?", (cid,)).fetchone()[0]
    total_paid = db.execute("SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE customer_id=?", (cid,)).fetchone()[0]
    balance = round(total_inv - total_paid, 2)
    db.close()
    return render_template("customer/profile.html", c=c, active_tab=tab, invoices=invoices,
        payments=payments, contracts=contracts, quotations=quotations, lpos=lpos, docs=docs,
        total_inv=total_inv, total_paid=total_paid, balance=balance)

# ─── INVOICES ───

@customer_bp.route("/<int:cid>/invoice/add", methods=["GET", "POST"])
def customer_invoice_add(cid):
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    db = _get_db()
    next_no = _next_invoice_no(db)
    lpos = db.execute("SELECT id,lpo_no,lpo_date,amount FROM customer_lpos WHERE customer_id=? AND status!='closed' ORDER BY lpo_date DESC", (cid,)).fetchall()
    if request.method == "POST":
        inv_date = request.form.get("invoice_date", date.today().isoformat())
        inv_no = request.form.get("invoice_no", "").strip() or next_no
        existing = db.execute("SELECT id FROM customer_invoices WHERE invoice_no=?", (inv_no,)).fetchone()
        if existing:
            flash(f"Invoice number '{inv_no}' already exists. Use a different number.", "error")
            db.close()
            return render_template("customer/invoice_form.html", c=c, inv={}, lpos=lpos, today=date.today().isoformat(), next_no=next_no)
        vat_pct = float(request.form.get("vat_percent", 5))
        lpo_no = request.form.get("lpo_no", "").strip() or None
        lpo_date = request.form.get("lpo_date", "").strip() or None
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
            return render_template("customer/invoice_form.html", c=c, inv={}, lpos=lpos, today=date.today().isoformat(), next_no=next_no)
        vat_amt = round(sub_total * vat_pct / 100, 2)
        total = round(sub_total + vat_amt, 2)
        c_inv = db.execute("""INSERT INTO customer_invoices (customer_id,invoice_no,invoice_date,amount,vat_percent,vat_amount,total_amount,lpo_no,lpo_date,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid, inv_no, inv_date, sub_total, vat_pct, vat_amt, total, lpo_no, lpo_date, notes))
        inv_id = c_inv.lastrowid
        for idx, it in enumerate(items):
            db.execute("INSERT INTO customer_invoice_items (invoice_id,description,quantity,rate,amount,sort_order) VALUES (?,?,?,?,?,?)",
                (inv_id, it["desc"], it["qty"], it["rate"], it["amt"], idx))
        db.commit()
        db.close()
        flash(f"Invoice {inv_no} created.", "success")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="invoices"))
    db.close()
    return render_template("customer/invoice_form.html", c=c, inv={}, lpos=lpos, today=date.today().isoformat(), next_no=next_no)

@customer_bp.route("/<int:cid>/invoice/<int:iid>/edit", methods=["GET", "POST"])
def customer_invoice_edit(cid, iid):
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    db = _get_db()
    inv = db.execute("SELECT * FROM customer_invoices WHERE id=? AND customer_id=?", (iid, cid)).fetchone()
    items = db.execute("SELECT * FROM customer_invoice_items WHERE invoice_id=? ORDER BY sort_order", (iid,)).fetchall()
    lpos = db.execute("SELECT id,lpo_no,lpo_date,amount FROM customer_lpos WHERE customer_id=? AND status!='closed' ORDER BY lpo_date DESC", (cid,)).fetchall()
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
            return render_template("customer/invoice_form.html", c=c, inv=inv, items=items, lpos=lpos, today=date.today().isoformat(), edit=True)
        vat_pct = float(request.form.get("vat_percent", 5))
        lpo_no = request.form.get("lpo_no", "").strip() or None
        lpo_date = request.form.get("lpo_date", "").strip() or None
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
            return render_template("customer/invoice_form.html", c=c, inv=inv, items=items, lpos=lpos, today=date.today().isoformat(), edit=True)
        vat_amt = round(sub_total * vat_pct / 100, 2)
        total = round(sub_total + vat_amt, 2)
        db.execute("""UPDATE customer_invoices SET invoice_no=?,invoice_date=?,amount=?,vat_percent=?,vat_amount=?,total_amount=?,lpo_no=?,lpo_date=?,notes=? WHERE id=?""",
            (inv_no, inv_date, sub_total, vat_pct, vat_amt, total, lpo_no, lpo_date, notes, iid))
        db.execute("DELETE FROM customer_invoice_items WHERE invoice_id=?", (iid,))
        for idx, it in enumerate(new_items):
            db.execute("INSERT INTO customer_invoice_items (invoice_id,description,quantity,rate,amount,sort_order) VALUES (?,?,?,?,?,?)",
                (iid, it["desc"], it["qty"], it["rate"], it["amt"], idx))
        db.commit()
        db.close()
        flash(f"Invoice {inv_no} updated.", "success")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="invoices"))
    db.close()
    return render_template("customer/invoice_form.html", c=c, inv=inv, items=items, lpos=lpos, today=date.today().isoformat(), edit=True)

@customer_bp.route("/<int:cid>/invoice/<int:iid>")
def customer_invoice_view(cid, iid):
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
    return render_template("customer/invoice_view.html", c=c, inv=inv, items=items, company=company)

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
    BG = colors.HexColor("#f4f6f9"); WH = colors.white; C3 = colors.HexColor("#d1d5db")
    C4 = colors.HexColor("#111827"); C5 = colors.HexColor("#6b7280"); C6 = colors.HexColor("#dc2626")

    cn = company["company_name"] if company else "COMPANY"
    trn = company["trn_no"] or "—" if company else "—"
    addr = (company["address"] or "") if company else ""
    ph = (company["phone_number"] or "") if company else ""
    em = (company["email"] or "") if company else ""

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
    # 1. HEADER
    # ═══════════════════════════════════
    logo = None; LW = 0
    if company and company["logo_data"]:
        try:
            lb = base64.b64decode(company["logo_data"])
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            f.write(lb); f.close()
            logo = Image(f.name, width=55, height=55)
            LW = 55
            _logo_tmp_files.append(f.name)
        except: pass

    addr_ph = [x for x in [addr] if x]
    contact_ph = [x for x in [ph, em]] if (ph or em) else []
    if contact_ph and addr_ph: info = " &middot; ".join(addr_ph + contact_ph)
    elif addr_ph: info = addr_ph[0]
    elif contact_ph: info = " &middot; ".join(contact_ph)
    else: info = ""
    if trn and trn != "—":
        if info: info += " &middot; "
        info += f"TRN: {trn}"
    co_p = Paragraph(
        f"<font size=11><b>{cn}</b></font><br/>"
        f"<font size=6.5 color='#6b7280'>{info}</font>",
        S("CO", fontSize=11, fontName="Helvetica-Bold", textColor=TH, leading=14))

    if logo:
        lh = Table([[logo, Spacer(1, 3*mm), co_p]], colWidths=[LW, 3*mm, W*0.65 - LW - 3*mm])
        lh.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    else:
        lh = co_p

    rh = Paragraph(
        f"<b>TAX INVOICE</b><br/>"
        f"<font size=7 color='#6b7280'># {inv_no}<br/>{inv_dt}</font>",
        S("TI", fontSize=16, fontName="Helvetica-Bold", textColor=TH, leading=20, alignment=TA_RIGHT))

    ht = Table([[lh, rh]], colWidths=[W*0.65, W*0.35])
    ht.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ht)
    els.append(Spacer(1, 3*mm))

    hr = Table([[""]], colWidths=[W], rowHeights=[2.5])
    hr.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(hr)
    els.append(Spacer(1, 5*mm))

    # ═══════════════════════════════════
    # 2. BILL TO / INVOICE INFO
    # ═══════════════════════════════════
    def card(title, pairs):
        cw = W*0.47
        r = [[
            Paragraph(f"<b>{title}</b>", S("_ch", fontSize=7, fontName="Helvetica-Bold", textColor=C5, leading=10)),
            Paragraph("", S("_cs", fontSize=4, leading=4)),
        ]]
        for a, b in pairs:
            r.append([
                Paragraph(a, S("_cl", fontSize=8, textColor=C5, leading=11)),
                Paragraph(f"<b>{b}</b>", S("_cv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=12, alignment=TA_RIGHT)),
            ])
        t = Table(r, colWidths=[cw*0.40, cw*0.60])
        t.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
            ("LEFTPADDING",(0,0),(-1,-1),8), ("RIGHTPADDING",(0,0),(-1,-1),8),
            ("BOX",(0,0),(-1,-1),0.5,C3),
        ]))
        return t

    bd = [("Customer", safe(c["customer_name"])), ("TRN", safe(c["trn"]))]
    if c["phone"]: bd.append(("Phone", c["phone"]))
    if c["address"]: bd.append(("Address", c["address"]))
    id_ = [("Invoice #", inv_no), ("Date", inv_dt)]
    if inv["lpo_no"]: id_.append(("LPO No.", inv["lpo_no"]))
    if inv["lpo_date"]: id_.append(("LPO Date", inv["lpo_date"]))

    iw = Table([[card("BILL TO", bd), Spacer(1, 4*mm), card("INVOICE INFO", id_)]], colWidths=[W*0.47, 4*mm, W*0.53])
    iw.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(iw)
    els.append(Spacer(1, 5*mm))

    # ═══════════════════════════════════
    # 3. ITEMS TABLE
    # ═══════════════════════════════════
    cw = [14, W - 14 - 50 - 68 - 82, 50, 68, 82]
    hdr = [
        Paragraph("<b>#</b>", S("_h0", fontSize=8, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=11)),
        Paragraph("<b>Description</b>", S("_h1", fontSize=8, fontName="Helvetica-Bold", textColor=WH, leading=11)),
        Paragraph("<b>QTY</b>", S("_h2", fontSize=8, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=11)),
        Paragraph("<b>Rate (AED)</b>", S("_h3", fontSize=8, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=11)),
        Paragraph("<b>Amount (AED)</b>", S("_h4", fontSize=8, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=11)),
    ]
    rws = [hdr]
    for idx, it in enumerate(items):
        rws.append([
            C(str(idx+1), fontSize=8, fontName="Helvetica-Bold"),
            L(it["description"] or "—", fontSize=8),
            C(f"{it['quantity'] or 0:,.2f}", fontSize=8),
            R(f"{it['rate'] or 0:,.2f}", fontSize=8),
            RB(f"{it['amount'] or 0:,.2f}", fontSize=8),
        ])

    sub = inv["amount"] or 0; vat = inv["vat_amount"] or 0; tot = inv["total_amount"] or 0; vp = inv["vat_percent"] or 0

    itt = Table(rws, colWidths=cw, repeatRows=1)
    itt.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BACKGROUND",(0,0),(-1,0),TH), ("TEXTCOLOR",(0,0),(-1,0),WH),
        ("BOX",(0,0),(-1,-1),0.5,C3),
        ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),3.5), ("BOTTOMPADDING",(0,0),(-1,-1),3.5),
        ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WH, BG]),
    ]))
    els.append(itt)

    # ═══════════════════════════════════
    # 4. TOTALS
    # ═══════════════════════════════════
    tw = 90*mm
    trows = [
        [Paragraph("Sub Total", S("_st", fontSize=9, textColor=C5, leading=12)),
         Paragraph(f"<b>AED {sub:,.2f}</b>", S("_stv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=12, alignment=TA_RIGHT))],
        [Paragraph(f"VAT @ {vp:.0f}%", S("_vt", fontSize=9, textColor=C5, leading=12)),
         Paragraph(f"<b>AED {vat:,.2f}</b>", S("_vtv", fontSize=9, fontName="Helvetica-Bold", textColor=C6, leading=12, alignment=TA_RIGHT))],
        [Paragraph("<b>Total Due</b>", S("_td", fontSize=11, fontName="Helvetica-Bold", textColor=TH, leading=15)),
         Paragraph(f"<b>AED {tot:,.2f}</b>", S("_tdv", fontSize=13, fontName="Helvetica-Bold", textColor=TH, leading=17, alignment=TA_RIGHT))],
    ]
    tt = Table(trows, colWidths=[tw*0.45, tw*0.55])
    tt.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),10), ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("BACKGROUND",(0,0),(-1,-1),BG),
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
        nb = Table([[Paragraph(f"<b>Notes:</b> {inv['notes']}", S("NW", fontSize=9, textColor=C4, leading=12))]], colWidths=[W])
        nb.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),BG),("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        els.append(nb)

    # ═══════════════════════════════════
    # 6. BANK DETAILS
    # ═══════════════════════════════════
    if company:
        bk = []
        for lb, ky in [("Bank Name","bank_name"),("Account Name","bank_account_name"),
                       ("Account No.","bank_account_number"),("IBAN","iban")]:
            v = company[ky] or "—"
            bk.append([L(lb, fontSize=7.5), V(v, fontSize=8.5)])
        if bk:
            els.append(Spacer(1, 4*mm))
            els.append(Paragraph("<b>BANK DETAILS</b>", S("BD", fontSize=10, fontName="Helvetica-Bold", textColor=TH, leading=13, spaceAfter=3)))
            bkt = Table(bk, colWidths=[65, W - 65])
            bkt.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),1.5),("BOTTOMPADDING",(0,0),(-1,-1),1.5),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
            els.append(bkt)

    # ═══════════════════════════════════
    # 7. SIGNATURES
    # ═══════════════════════════════════
    els.append(Spacer(1, 7*mm))
    sg = ParagraphStyle("SG", fontSize=9, alignment=TA_CENTER, leading=13)
    sgt = Table([[
        Paragraph("_________________________<br/><b>Authorized Signatory</b><br/><font size=7 color='#6b7280'>Stamp</font>", sg),
        C("", fontSize=4),
        Paragraph("_________________________<br/><b>Customer Signature</b><br/><font size=7 color='#6b7280'>Accepted By</font>", sg),
    ]], colWidths=[W*0.40, W*0.20, W*0.40])
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

# ─── PAYMENTS ───

@customer_bp.route("/<int:cid>/payment/add", methods=["GET", "POST"])
def customer_payment_add(cid):
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    db = _get_db()
    invoices = db.execute("SELECT id,invoice_no,total_amount FROM customer_invoices WHERE customer_id=? ORDER BY invoice_date DESC", (cid,)).fetchall()
    if request.method == "POST":
        inv_id = request.form.get("invoice_id") or None
        amt = float(request.form.get("amount", 0))
        pmt_date = request.form.get("payment_date", date.today().isoformat())
        db.execute("INSERT INTO customer_payments (customer_id,invoice_id,payment_date,amount,payment_method,reference_no,notes) VALUES (?,?,?,?,?,?,?)",
            (cid, inv_id, pmt_date, amt, request.form.get("payment_method", "Cash"), request.form.get("reference_no"), request.form.get("notes")))
        db.commit()
        db.close()
        flash("Payment added.", "success")
        return redirect(url_for("customer.customer_profile", cid=cid, tab="payments"))
    db.close()
    return render_template("customer/payment_form.html", c=c, invoices=invoices, today=date.today().isoformat())

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
    c = _get_customer_or_404(cid)
    if not c: return redirect(url_for("customer.customer_dashboard"))
    from_date = request.args.get("from", "")
    to_date = request.args.get("to", "")
    db = _get_db()
    entries = []
    inv_q = "SELECT invoice_date as d, invoice_no as ref, 'Invoice' as type, total_amount as dr, 0 as cr FROM customer_invoices WHERE customer_id=?"
    inv_p = [cid]
    if from_date: inv_q += " AND invoice_date>=?"; inv_p.append(from_date)
    if to_date: inv_q += " AND invoice_date<=?"; inv_p.append(to_date)
    inv_q += " ORDER BY invoice_date"
    for inv in db.execute(inv_q, inv_p).fetchall():
        entries.append(dict(inv))
    pmt_q = "SELECT p.payment_date as d, COALESCE(i.invoice_no,'') as ref, 'Payment' as type, 0 as dr, p.amount as cr FROM customer_payments p LEFT JOIN customer_invoices i ON p.invoice_id=i.id WHERE p.customer_id=?"
    pmt_p = [cid]
    if from_date: pmt_q += " AND p.payment_date>=?"; pmt_p.append(from_date)
    if to_date: pmt_q += " AND p.payment_date<=?"; pmt_p.append(to_date)
    pmt_q += " ORDER BY p.payment_date"
    for pmt in db.execute(pmt_q, pmt_p).fetchall():
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
    inv_q = "SELECT invoice_date as d, invoice_no as ref, 'Invoice' as type, total_amount as dr, 0 as cr FROM customer_invoices WHERE customer_id=?"
    inv_p = [cid]
    if from_date: inv_q += " AND invoice_date>=?"; inv_p.append(from_date)
    if to_date: inv_q += " AND invoice_date<=?"; inv_p.append(to_date)
    inv_q += " ORDER BY invoice_date"
    for inv in db.execute(inv_q, inv_p).fetchall():
        entries.append(dict(inv))
    pmt_q = "SELECT p.payment_date as d, COALESCE(i.invoice_no,'') as ref, 'Payment' as type, 0 as dr, p.amount as cr FROM customer_payments p LEFT JOIN customer_invoices i ON p.invoice_id=i.id WHERE p.customer_id=?"
    pmt_p = [cid]
    if from_date: pmt_q += " AND p.payment_date>=?"; pmt_p.append(from_date)
    if to_date: pmt_q += " AND p.payment_date<=?"; pmt_p.append(to_date)
    pmt_q += " ORDER BY p.payment_date"
    for pmt in db.execute(pmt_q, pmt_p).fetchall():
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
        Paragraph(f"<b>Outstanding</b><br/><font size=10 color='#c62828'>AED {closing:,.2f}</font>", F("_s3", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
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
    colw = [50, 72, 45, W - 50 - 72 - 45 - 72 - 80, 72, 80]
    hdr = [
        Paragraph("<b>Date</b>", F("_h", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=11)),
        Paragraph("<b>Invoice #</b>", F("_h", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, leading=11)),
        Paragraph("<b>Type</b>", F("_h", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=11)),
        Paragraph("<b>Dr (AED)</b>", F("_h", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=11)),
        Paragraph("<b>Cr (AED)</b>", F("_h", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=11)),
        Paragraph("<b>Balance (AED)</b>", F("_h", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=11)),
    ]
    rws = [hdr]
    rws.append([
        Paragraph("", F("_o", fontSize=7, leading=10)), Paragraph("", F("_o")),
        Paragraph("Opening Balance", F("_ol", fontSize=7, textColor=C5, leading=10)),
        Paragraph("", F("_o")), Paragraph("", F("_o")),
        Paragraph("<b>0.00</b>", F("_ob", fontSize=7.5, fontName="Helvetica-Bold", textColor=C4, alignment=TA_RIGHT, leading=11)),
    ])
    for e in entries:
        rws.append([
            Paragraph(str(e.get("d","")), F("_d", fontSize=7.5, leading=11)),
            Paragraph(str(e.get("ref","—")), F("_r", fontSize=7.5, fontName="Helvetica-Bold", textColor=C4, leading=11)),
            Paragraph(f"<font color=\"{'#1a56db' if e['type']=='Invoice' else '#1a7d1a'}\">{e['type']}</font>", F("_t", fontSize=7.5, alignment=TA_CENTER, leading=11)),
            Paragraph(f"<b>{e.get('dr',0):,.2f}</b>" if e.get("dr") else "—", F("_dr", fontSize=7.5, textColor="#c62828" if e.get("dr") else C5, alignment=TA_RIGHT, leading=11)),
            Paragraph(f"<b>{e.get('cr',0):,.2f}</b>" if e.get("cr") else "—", F("_cr", fontSize=7.5, textColor="#1a7d1a" if e.get("cr") else C5, alignment=TA_RIGHT, leading=11)),
            Paragraph(f"<b>{e['bal']:,.2f}</b>", F("_bl", fontSize=7.5, fontName="Helvetica-Bold", textColor="#c62828" if e['bal']>0 else "#1a7d1a", alignment=TA_RIGHT, leading=11)),
        ])

    it = Table(rws, colWidths=colw, repeatRows=1)
    it.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BACKGROUND",(0,0),(-1,0),TH), ("TEXTCOLOR",(0,0),(-1,0),WH),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),2.5), ("BOTTOMPADDING",(0,0),(-1,-1),2.5),
        ("LEFTPADDING",(0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WH, BG]),
    ]))
    els.append(it)

    # ── CLOSING ROW ──
    cd = [[
        Paragraph("<b>Closing Balance</b>", F("_cb", fontSize=9, fontName="Helvetica-Bold", textColor=WH, leading=12)),
        Paragraph(f"<b>AED {total_dr:,.2f}</b>", F("_cd", fontSize=9, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=12)),
        Paragraph(f"<b>AED {total_cr:,.2f}</b>", F("_cc", fontSize=9, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=12)),
        Paragraph(f"<b>AED {closing:,.2f}</b>", F("_ccl", fontSize=9, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=12)),
    ]]
    cl_t = Table(cd, colWidths=[colw[0]+colw[1]+colw[2], colw[3], colw[4], colw[5]])
    cl_t.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BACKGROUND",(0,0),(-1,-1),TH),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4),
    ]))
    els.append(cl_t)

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
