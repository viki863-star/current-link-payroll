"""
Customer Quotation PDF Template
================================
Standalone template for generating professional quotation documents.

Usage:
    from quotation_design import generate_quotation_pdf
    generate_quotation_pdf(company, party, quotation, items, output_path)
"""

from base_design import *

# ── Default Terms & Conditions ────────────────────────────────────────────────────
DEFAULT_TC_LINES = [
    "This quotation is valid for 15 days from the date of issue.",
    "Payment is due within 30 days from the date of invoice.",
    "Any alteration or cancellation of order must be notified in writing.",
    "All disputes are subject to UAE jurisdiction.",
    "Delivery / service execution as per agreed schedule.",
    "Rates are exclusive of any applicable taxes unless stated otherwise.",
]


def generate_quotation_pdf(
    company: dict,
    party: dict,
    quotation: dict,
    items: list,
    output_path: str,
) -> str:
    """Generate a standalone Customer Quotation PDF.

    Args:
        company:     Company profile dict (company_name, trn_no, address, etc.)
        party:       Customer/party dict (customer_name, trn, phone, email, etc.)
        quotation:   Quotation data dict with keys:
                       quotation_no, quotation_date, sub_total, vat_percent,
                       vat_amount, total_amount, status, notes, terms, location
        items:       List of dicts, each with keys:
                       description, quantity, rate, unit, amount
        output_path: Absolute path for the output PDF file.

    Returns:
        Absolute path to the generated PDF.
    """
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    from io import BytesIO

    company = company or {}
    party = party or {}
    quotation = quotation or {}

    cn = company.get("company_name", "COMPANY NAME")
    c_addr = company.get("address") or ""
    c_ph = company.get("phone_number") or ""
    c_em = company.get("email") or ""
    c_trn = company.get("trn_no") or "-"
    tc = company.get("theme_color") or "#1a3a5c"
    try:
        TH = colors.HexColor(tc)
    except Exception:
        TH = colors.HexColor("#1a3a5c")
    BG = colors.HexColor("#f8fafc")
    WH = colors.white
    C3 = colors.HexColor("#e2e8f0")
    C4 = colors.HexColor("#0f172a")
    C5 = colors.HexColor("#64748b")
    C6 = colors.HexColor("#dc2626")

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

    safe = lambda v, d="\u2014": str(v) if v else d

    # ── Build document ───────────────────────────────────────────────────────────
    buf = BytesIO()
    LM, RM, TM, BM = 18 * mm, 18 * mm, 15 * mm, 12 * mm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM
    els = []

    q_no = quotation.get("quotation_no") or "-"
    q_dt = quotation.get("quotation_date") or "-"

    # ── 1. HEADER ────────────────────────────────────────────────────────────────
    ci_lines = []
    if c_addr:
        ci_lines.append(f"<font size=7 color='#64748b'>{c_addr}</font>")
    c_contact = []
    if c_ph:
        c_contact.append(f"Phone: {c_ph}")
    if c_em:
        c_contact.append(f"Email: {c_em}")
    if c_contact:
        ci_lines.append('<font size=7 color="#64748b">' + " &middot; ".join(c_contact) + "</font>")
    ci_lines.append(f"<font size=7 color='#64748b'><b>TRN: {c_trn}</b></font>")
    ci_html = f"<font size=12><b>{cn}</b></font><br/>" + "<br/>".join(ci_lines)
    co_p = Paragraph(ci_html, S("CO", fontSize=12, fontName="Helvetica-Bold", textColor=TH, leading=16))

    rh = Paragraph(
        f"<b>QUOTATION</b><br/><font size=7 color='#64748b'># {q_no}<br/>{q_dt}</font>",
        S("TI", fontSize=16, fontName="Helvetica-Bold", textColor=TH, leading=20, alignment=TA_RIGHT),
    )

    ht = Table([[co_p, rh]], colWidths=[W * 0.65, W * 0.35])
    ht.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    els.append(ht)

    bl = Table([[""]], colWidths=[W], rowHeights=[3])
    bl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TH), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    els.append(bl)
    els.append(Spacer(1, 5 * mm))

    # ── 2. CUSTOMER AND QUOTATION INFO CARDS ─────────────────────────────────────
    def card(title, pairs):
        cw = W * 0.50
        r = [[Paragraph(f"<b>{title}</b>", S("_ch", fontSize=6.5, fontName="Helvetica-Bold", textColor=C5, leading=9)), Paragraph("", S("_cs", fontSize=2, leading=2))]]
        for a, b in pairs:
            r.append([
                Paragraph(a, S("_cl", fontSize=7.5, textColor=C5, leading=11)),
                Paragraph(f"{b}", S("_cv", fontSize=8, fontName="Helvetica-Bold", textColor=C4, leading=11.5)),
            ])
        t = Table(r, colWidths=[cw * 0.28, cw * 0.72])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("BOX", (0, 0), (-1, -1), 0.5, C3),
        ]))
        return t

    bd = [("Customer", safe(party.get("customer_name") or party.get("party_name"))), ("TRN", safe(party.get("trn")))]
    if party.get("phone"):
        bd.append(("Phone", party["phone"]))
    if party.get("email"):
        bd.append(("Email", party["email"]))
    if party.get("address"):
        bd.append(("Address", party["address"]))

    id_ = [
        ("Quotation #", q_no),
        ("Date", q_dt),
        ("Status", (quotation.get("status") or "PENDING").upper()),
    ]
    if quotation.get("location"):
        id_.append(("Location", quotation["location"]))

    iw = Table([[card("CUSTOMER", bd), Spacer(1, 4 * mm), card("QUOTATION INFO", id_)]], colWidths=[W * 0.50, 4 * mm, W * 0.50])
    iw.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    els.append(iw)
    els.append(Spacer(1, 5 * mm))

    # ── 3. ITEMS TABLE ───────────────────────────────────────────────────────────
    fs = 7.0
    num_rows = len(items) + 1
    if num_rows > 0:
        avail_pt = A4[1] - TM - BM - 50 * mm
        target = avail_pt / num_rows
        fs = max(4.0, min(7.0, target / 2.8))
    ldr = fs * 1.35
    pad_t = max(1.5, fs * 0.5)
    pad_b = max(1.5, fs * 0.5)

    DH = colors.HexColor("#1e293b")
    cw = [10 * mm, 52 * mm, 16 * mm, 16 * mm, 22 * mm, 26 * mm]

    def _pc(t, **kw):
        kw.setdefault("fontSize", fs)
        kw.setdefault("leading", ldr)
        return Paragraph(str(t), S("_pc", **kw))

    def _fmt_amount(v):
        s = f"{float(v or 0):,.4f}".rstrip("0").rstrip(".")
        if "." not in s:
            s += ".00"
        else:
            ipart, dpart = s.split(".")
            if len(dpart) < 2:
                s += "0" * (2 - len(dpart))
        return s

    hdr = [
        Paragraph("<b>#</b>", S("_h0", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=ldr)),
        Paragraph("<b>Description</b>", S("_h1", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, leading=ldr)),
        Paragraph("<b>Qty</b>", S("_h2", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=ldr)),
        Paragraph("<b>Unit</b>", S("_hu", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=ldr)),
        Paragraph("<b>Rate<br/>(AED)</b>", S("_h3", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=ldr)),
        Paragraph("<b>Amount<br/>(AED)</b>", S("_h4", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=ldr)),
    ]
    rws = [hdr]
    amt_vals = []
    for idx, it in enumerate(items):
        rt = (it.get("rate_text") or "").strip()
        rate_val = float(rt) if rt else float(it.get("rate") or 0)
        rate_disp = rt if rt else f"{it.get('rate') or 0:,.4f}".rstrip("0").rstrip(".")
        amt_val = float(it.get("quantity") or 0) * rate_val
        amt_vals.append(amt_val)
        rws.append([
            _pc(str(idx + 1), alignment=TA_CENTER, fontName="Helvetica-Bold"),
            _pc(it.get("description") or "\u2014"),
            _pc(f"{it.get('quantity') or 0:,.2f}", alignment=TA_CENTER),
            _pc((it.get("unit") or "hr").upper(), alignment=TA_CENTER),
            _pc(rate_disp, alignment=TA_RIGHT),
            _pc(_fmt_amount(amt_val), alignment=TA_RIGHT),
        ])

    itt = Table(rws, colWidths=cw, repeatRows=1)
    itt.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), DH), ("TEXTCOLOR", (0, 0), (-1, 0), WH),
        ("BOX", (0, 0), (-1, -1), 0.5, C3),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C3),
        ("TOPPADDING", (0, 0), (-1, -1), pad_t), ("BOTTOMPADDING", (0, 0), (-1, -1), pad_b),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WH, BG]),
    ]))
    els.append(itt)

    # ── 4. TOTALS ────────────────────────────────────────────────────────────────
    sub = round(sum(amt_vals), 2) if amt_vals else (quotation.get("sub_total") or quotation.get("amount") or 0)
    vat = quotation.get("vat_amount") or 0
    tot = quotation.get("total_amount") or sub
    vp = quotation.get("vat_percent") or 0

    tw = 90 * mm
    trows = [
        [Paragraph("Sub Total", S("_st", fontSize=9, textColor=C5, leading=14)),
         Paragraph(f"<b>AED {sub:,.2f}</b>", S("_stv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=14, alignment=TA_RIGHT))],
        [Paragraph(f"VAT @ {vp:.0f}%", S("_vt", fontSize=9, textColor=C5, leading=14)),
         Paragraph(f"<b>AED {vat:,.2f}</b>", S("_vtv", fontSize=9, fontName="Helvetica-Bold", textColor=C6, leading=14, alignment=TA_RIGHT))],
        [Paragraph("<b>Total</b>", S("_td", fontSize=11, fontName="Helvetica-Bold", textColor=C4, leading=16)),
         Paragraph(f"<b>AED {tot:,.2f}</b>", S("_tdv", fontSize=13, fontName="Helvetica-Bold", textColor=TH, leading=18, alignment=TA_RIGHT))],
    ]
    tt = Table(trows, colWidths=[tw * 0.45, tw * 0.55])
    tt.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("BOX", (0, 0), (-1, -1), 0.5, C3),
        ("LINEABOVE", (0, 2), (-1, 2), 2, TH),
    ]))

    ft = Table([["", tt]], colWidths=[W - tw, tw])
    ft.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    els.append(Spacer(1, 2 * mm))
    els.append(ft)

    # ── 5. NOTES (if any) ────────────────────────────────────────────────────────
    if quotation.get("notes"):
        els.append(Spacer(1, 3 * mm))
        nb = Table([[Paragraph(f"<b>Notes:</b> {quotation['notes']}", S("NW", fontSize=9, textColor=C4, leading=13))]], colWidths=[W])
        nb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BG), ("BOX", (0, 0), (-1, -1), 0.5, C3), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        els.append(nb)

    # ── 6. TERMS & CONDITIONS ────────────────────────────────────────────────────
    els.append(Spacer(1, 3 * mm))
    tc_lines = []
    if quotation.get("terms"):
        for _tl in str(quotation["terms"]).split("\n"):
            if _tl.strip():
                tc_lines.append(_tl.strip())
    tc_lines += DEFAULT_TC_LINES

    t_head = Paragraph("<b>Terms &amp; Conditions:</b>", S("TW", fontSize=9, textColor=C4, leading=14))
    t_rows = [[t_head]]
    for i, tline in enumerate(tc_lines, 1):
        txt = str(tline).replace("<li>", "").replace("</li>", "")
        t_rows.append([Paragraph(f"<font color='#b45309'>{i}.</font>  {txt}", S("TW", fontSize=9, textColor=C4, leading=14, leftIndent=14, firstLineIndent=-14, spaceAfter=2))])
    tb = Table(t_rows, colWidths=[W])
    tb.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffbeb")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#fde68a")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (-1, -1), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    els.append(tb)

    # ── 7. SIGNATURES ────────────────────────────────────────────────────────────
    els.append(Spacer(1, 3 * mm))
    sg = ParagraphStyle("SG", fontSize=10, alignment=TA_CENTER, leading=15)
    st = Table([
        [Paragraph(f"<b>Authorized Signatory</b><br/><font size=8 color='#64748b'>{cn}</font><br/>___________________________", sg),
         Paragraph("<br/>", sg)],
    ], colWidths=[W * 0.6, W * 0.4])
    st.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    els.append(st)

    # ── Build ────────────────────────────────────────────────────────────────────
    doc.build(els)
    pdf_data = buf.getvalue()
    buf.close()

    with open(output_path, "wb") as f:
        f.write(pdf_data)
    return str(output_path)
