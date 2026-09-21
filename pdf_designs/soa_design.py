"""
Statement of Account (SOA) PDF Template
=========================================
Standalone template for generating customer statement of account documents.

Usage:
    from soa_design import generate_soa_pdf
    generate_soa_pdf(company, customer, entries, totals, output_path)
"""

from base_design import *

from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from io import BytesIO


def generate_soa_pdf(
    company: dict,
    customer: dict,
    entries: list,
    totals: dict,
    output_path: str,
    from_date: str = "",
    to_date: str = "",
) -> str:
    """Generate a standalone Statement of Account PDF.

    Args:
        company:    Company profile dict (company_name, trn_no, address, etc.)
        customer:   Customer dict (customer_name, trn, address, phone, etc.)
        entries:    List of transaction dicts, each with keys:
                      d (date), ref, type, dr, cr, bal
        totals:     Dict with keys: total_dr, total_cr, closing
        output_path: Absolute path for the output PDF file.
        from_date:  Filter start date (optional).
        to_date:    Filter end date (optional).

    Returns:
        Absolute path to the generated PDF.
    """
    company = company or {}
    customer = customer or {}
    entries = list(entries or [])
    totals = totals or {}

    tc = company.get("theme_color") or "#1a3a5c"
    try:
        TH = colors.HexColor(tc)
    except Exception:
        TH = colors.HexColor("#1a3a5c")
    BG = colors.HexColor("#f4f6f9")
    WH = colors.white
    C3 = colors.HexColor("#d1d5db")
    C4 = colors.HexColor("#111827")
    C5 = colors.HexColor("#6b7280")
    CG = colors.HexColor("#1a7d1a")
    CR = colors.HexColor("#c62828")

    total_dr = totals.get("total_dr", 0.0)
    total_cr = totals.get("total_cr", 0.0)
    closing = totals.get("closing", round(total_dr - total_cr, 2))

    def F(name, **kw):
        kw.setdefault("fontSize", 8)
        kw.setdefault("leading", 12)
        return ParagraphStyle(name, **kw)

    def C(t, **kw):
        kw.setdefault("alignment", TA_CENTER)
        return Paragraph(str(t), F("_C", **kw))

    def R(t, **kw):
        kw.setdefault("alignment", TA_RIGHT)
        return Paragraph(str(t), F("_R", **kw))

    # ── Build document ───────────────────────────────────────────────────────────
    buf = BytesIO()
    LM, RM, TM, BM = 18 * mm, 18 * mm, 15 * mm, 15 * mm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM
    els = []

    cn = company.get("company_name", "COMPANY NAME")
    trn = company.get("trn_no") or "\u2014"
    cust_name = customer.get("customer_name") or customer.get("party_name") or "-"

    # ── 1. HEADER ────────────────────────────────────────────────────────────────
    cl = [f"<font size=11><b>{cn}</b></font>"]
    addr = company.get("address") or ""
    ph = company.get("phone_number") or ""
    em = company.get("email") or ""
    parts = [x for x in [addr] if x]
    cparts = [x for x in [ph, em, f"TRN: {trn}"] if x and x != "TRN: \u2014"]
    if parts or cparts:
        info = " &middot; ".join(parts + cparts)
        cl.append(f"<font size=6.5 color='#6b7280'>{info}</font>")
    co_p = Paragraph("<br/>".join(cl), F("CO", fontSize=11, fontName="Helvetica-Bold", textColor=TH, leading=13))

    rh = Paragraph(
        "<b>STATEMENT<br/>OF ACCOUNT</b>",
        F("TI", fontSize=14, fontName="Helvetica-Bold", textColor=TH, leading=18, alignment=TA_RIGHT),
    )
    ht = Table([[co_p, rh]], colWidths=[W * 0.65, W * 0.35])
    ht.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    els.append(ht)
    els.append(Spacer(1, 2 * mm))

    # ── Accent line ──────────────────────────────────────────────────────────────
    hr = Table([[""]], colWidths=[W], rowHeights=[2])
    hr.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TH), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    els.append(hr)
    els.append(Spacer(1, 4 * mm))

    # ── 2. CUSTOMER INFO ─────────────────────────────────────────────────────────
    cinfo = [
        [Paragraph("<b>Customer</b>", F("_cl", fontSize=8, fontName="Helvetica-Bold", textColor=C4, leading=11)),
         Paragraph(f"<b>{cust_name}</b>", F("_cv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=12))],
    ]
    if customer.get("trn"):
        cinfo.append([Paragraph("TRN", F("_l", fontSize=7.5, textColor=C5, leading=10)), Paragraph(customer["trn"], F("_v", fontSize=8.5, textColor=C4, leading=11))])
    if customer.get("address"):
        cinfo.append([Paragraph("Address", F("_l", fontSize=7.5, textColor=C5, leading=10)), Paragraph(customer["address"], F("_v", fontSize=8.5, textColor=C4, leading=11))])
    if customer.get("phone"):
        cinfo.append([Paragraph("Phone", F("_l", fontSize=7.5, textColor=C5, leading=10)), Paragraph(customer["phone"], F("_v", fontSize=8.5, textColor=C4, leading=11))])
    ct = Table(cinfo, colWidths=[50, W - 50])
    ct.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    els.append(ct)

    # ── 3. SUMMARY CARDS ─────────────────────────────────────────────────────────
    els.append(Spacer(1, 3 * mm))
    sdata = [[
        Paragraph(f"<b>Total Invoiced</b><br/><font size=10 color='#1a3a5c'>AED {total_dr:,.2f}</font>", F("_s1", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Total Paid</b><br/><font size=10 color='#1a7d1a'>AED {total_cr:,.2f}</font>", F("_s2", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Outstanding</b><br/><font size=10 color='#c62828'>AED {closing if closing > 0 else 0:,.2f}</font>", F("_s3", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Transactions</b><br/><font size=10>{len(entries)}</font>", F("_s4", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
    ]]
    st = Table(sdata, colWidths=[W / 4, W / 4, W / 4, W / 4])
    st.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, C3), ("INNERGRID", (0, 0), (-1, -1), 0.3, C3),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 0), (-1, -1), BG),
    ]))
    els.append(st)
    els.append(Spacer(1, 3 * mm))

    # ── 4. PERIOD FILTER (if any) ────────────────────────────────────────────────
    if from_date or to_date:
        rng = f"Period: {from_date or '\u2026'} to {to_date or '\u2026'}"
        els.append(Paragraph(f"<font size=7 color='#6b7280'>{rng}</font>", F("_pr", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=9)))
        els.append(Spacer(1, 2 * mm))

    # ── 5. TRANSACTION TABLE ─────────────────────────────────────────────────────
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

    # Opening balance row
    rws.append([
        Paragraph("", F("_o", fontSize=7, leading=10)),
        Paragraph("", F("_o")),
        Paragraph("", F("_o")),
        Paragraph("Opening Balance", F("_ol", fontSize=7, textColor=C5, leading=10)),
        Paragraph("", F("_o")),
        Paragraph("", F("_o")),
        Paragraph("<b>0.00</b>", F("_ob", fontSize=7, fontName="Helvetica-Bold", textColor=C4, alignment=TA_RIGHT, leading=10)),
    ])

    # Transaction rows
    for e in entries:
        d = str(e.get("d", ""))
        month = d[:7] if d and len(d) >= 7 else ""
        bal_val = e.get("bal", 0) or 0
        bal_display = "0.00" if bal_val <= 0 else f"{bal_val:,.2f}"
        bal_color = "#c62828" if bal_val > 0 else "#1a7d1a"
        entry_type = e.get("type", "")
        type_color = "#1a56db" if entry_type == "Invoice" else "#e65100" if entry_type == "Credit Note" else "#c62828" if entry_type == "Unallocated Payment" else "#1a7d1a"
        rws.append([
            Paragraph(d, F("_d", fontSize=7, leading=10)),
            Paragraph(f"<font color='{C5}'>{month}</font>" if month else "", F("_m", fontSize=6.5, textColor=C5, leading=10)),
            Paragraph(str(e.get("ref", "\u2014")), F("_r", fontSize=7, fontName="Helvetica-Bold", textColor=C4, leading=10)),
            Paragraph(f"<font color=\"{type_color}\">{entry_type}</font>", F("_t", fontSize=7, alignment=TA_CENTER, leading=10)),
            Paragraph(f"<b>{e.get('dr', 0) or 0:,.2f}</b>" if e.get("dr") else '<font color="#cccccc">\u2014</font>', F("_dr", fontSize=7, textColor="#c62828" if e.get("dr") else C5, alignment=TA_RIGHT, leading=10)),
            Paragraph(f"<b>{e.get('cr', 0) or 0:,.2f}</b>" if e.get("cr") else '<font color="#cccccc">\u2014</font>', F("_cr", fontSize=7, textColor="#1a7d1a" if e.get("cr") else C5, alignment=TA_RIGHT, leading=10)),
            Paragraph(f"<b>{bal_display}</b>", F("_bl", fontSize=7, fontName="Helvetica-Bold", textColor=bal_color, alignment=TA_RIGHT, leading=10)),
        ])

    # Closing row
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
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), TH), ("TEXTCOLOR", (0, 0), (-1, 0), WH),
        ("BOX", (0, 0), (-1, -1), 0.5, C3), ("INNERGRID", (0, 0), (-1, -1), 0.3, C3),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, -1), (-1, -1), TH), ("TEXTCOLOR", (0, -1), (-1, -1), WH),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-2, -2), [WH, BG]),
    ]))
    els.append(it)

    # ── 6. SIGNATURES ────────────────────────────────────────────────────────────
    els.append(Spacer(1, 8 * mm))
    s_sg = ParagraphStyle("SSG", fontSize=9, alignment=TA_CENTER, leading=14)
    s_auth_cells = []
    s_auth_cells.append(Paragraph("_________________________", s_sg))
    s_auth_cells.append(Paragraph("<b>Authorized Signatory</b>", s_sg))
    s_auth_cell = Table([[c] for c in s_auth_cells], colWidths=[W * 0.35])
    s_auth_cell.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    soa_sig = Table([[
        s_auth_cell,
        C("", fontSize=4),
        Paragraph("", s_sg),
    ]], colWidths=[W * 0.35, W * 0.30, W * 0.35])
    soa_sig.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (0, 0), 0.5, C5), ("LINEABOVE", (2, 0), (2, 0), 0.5, C5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(soa_sig)

    # ── 7. FOOTER ────────────────────────────────────────────────────────────────
    els.append(Spacer(1, 8 * mm))
    fh = Table([[""]], colWidths=[W], rowHeights=[0.5])
    fh.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TH), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    els.append(fh)
    els.append(Spacer(1, 2 * mm))
    ft_txt = "This is a computer-generated Statement of Account."
    if from_date or to_date:
        rng = f"Period: {from_date or '\u2026'} to {to_date or '\u2026'}"
        ft_txt += f" | {rng}"
    els.append(Paragraph(ft_txt, F("_ft", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=9)))

    # ── Build ────────────────────────────────────────────────────────────────────
    doc.build(els)
    pdf_data = buf.getvalue()
    buf.close()

    with open(output_path, "wb") as f:
        f.write(pdf_data)
    return str(output_path)
