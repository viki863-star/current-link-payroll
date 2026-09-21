"""
Customer Tax Invoice - LIVE FORMAT
==================================
Exact copy of the invoice design currently working in the system.
Uses ReportLab Platypus (SimpleDocTemplate) for layout.

Usage:
    from customer_invoice_live import generate_customer_invoice_pdf
    pdf_path = generate_customer_invoice_pdf(company, customer, invoice, items, output_dir)
"""

from __future__ import annotations
import base64
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.platypus.flowables import TopPadder
from reportlab.pdfbase.pdfmetrics import stringWidth

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None


def generate_customer_invoice_pdf(
    company: dict,
    customer: dict,
    invoice: dict,
    items: list[dict],
    output_dir: str,
    logo_path: str | None = None,
    stamp_path: str | None = None,
    sign_path: str | None = None,
) -> str:
    """
    Generate a customer tax invoice PDF (live format).

    Args:
        company: dict with keys: company_name, address, phone_number, email, trn_no,
                 theme_color, logo_data, bank_name, bank_account_name, bank_account_number,
                 iban, swift_code, invoice_terms, base_currency
        customer: dict with keys: customer_name, trn, phone, email, address
        invoice: dict with keys: invoice_no, invoice_date, amount, vat_percent,
                 vat_amount, total_amount, notes, so_no, lpo_no, lpo_date, project_no, ref_no
        items: list of dicts with keys: description, quantity, rate, amount, unit,
               vat_percent_item, vat_amount_item, total_incl_vat, vehicle_no
        output_dir: directory to write the PDF
        logo_path: optional path to logo image file
        stamp_path: optional path to stamp image
        sign_path: optional path to signature image
    Returns:
        Absolute path to generated PDF.
    """
    _logo_tmp_files = []
    output_path = Path(output_dir) / f"{invoice['invoice_no'].replace('/', '-')}_invoice.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    buf = BytesIO()
    LM, RM, TM, BM = 14 * mm, 14 * mm, 10 * mm, 8 * mm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM

    tc = company.get("theme_color") or "#1a3a5c"
    try:
        TH = colors.HexColor(tc)
    except Exception:
        TH = colors.HexColor("#1a3a5c")
    WH = colors.white
    BG = colors.HexColor("#f8fafc")
    C3 = colors.HexColor("#e2e8f0")
    C4 = colors.HexColor("#0f172a")
    C5 = colors.HexColor("#64738b")
    C6 = colors.HexColor("#dc2626")
    DH = colors.HexColor("#1e293b")

    cn = company.get("company_name") or "COMPANY NAME"
    c_addr = company.get("address") or ""
    c_ph = company.get("phone_number") or ""
    c_em = company.get("email") or ""
    c_trn = company.get("trn_no") or "—"

    inv_no = invoice.get("invoice_no") or "—"
    inv_dt = invoice.get("invoice_date") or "—"

    def S(name, **kw):
        kw.setdefault("fontSize", 8)
        kw.setdefault("leading", 12)
        return ParagraphStyle(name, **kw)

    safe = lambda v, d="—": str(v) if v else d
    els = []

    # ── 1. HEADER — Logo + Company Name + TAX INVOICE ──────────────────────
    logo = None
    LW = 0
    if logo_path:
        try:
            logo = Image(logo_path, width=60, height=60)
            LW = 60
        except Exception:
            pass
    elif company.get("logo_data"):
        try:
            lb = base64.b64decode(company["logo_data"])
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            f.write(lb)
            f.close()
            _logo_tmp_files.append(f.name)
            if PILImage:
                with PILImage.open(f.name) as img:
                    ow, oh = img.size
                ratio = 22 * mm / oh
                logo_w = int(ow * ratio)
                logo_h = int(22 * mm)
                logo = Image(f.name, width=logo_w, height=logo_h)
                LW = logo_w
            else:
                logo = Image(f.name, width=60, height=60)
                LW = 60
        except Exception:
            pass

    ci_lines = []
    c_contact = []
    if c_ph:
        c_contact.append(f"Phone: {c_ph}")
    if c_em:
        c_contact.append(f"Email: {c_em}")
    if c_contact:
        ci_lines.append('<font size=7 color="#64748b">' + ' &middot; '.join(c_contact) + '</font>')
    ci_lines.append(f"<font size=7 color='#64748b'><b>TRN: {c_trn}</b></font>")
    ci_html = f"<font size=14><b>{cn}</b></font><br/>" + "<br/>".join(ci_lines)
    co_p = Paragraph(ci_html, S("CO", fontSize=14, fontName="Helvetica-Bold", textColor=TH, leading=17))

    if logo:
        lh = Table([[logo, Spacer(1, 6 * mm), co_p]], colWidths=[LW, 6 * mm, W * 0.65 - LW - 6 * mm])
        lh.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
    else:
        lh = co_p

    rh = Paragraph(
        f"<b>TAX INVOICE</b><br/>"
        f"<font size=8 color='#64748b'># {inv_no}<br/>{inv_dt}</font>",
        S("TI", fontSize=16, fontName="Helvetica-Bold", textColor=TH, leading=20, alignment=TA_RIGHT),
    )

    ht = Table([[lh, rh]], colWidths=[W * 0.65, W * 0.35])
    ht.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(ht)

    # Blue separator line
    bl = Table([[""]], colWidths=[W], rowHeights=[2])
    bl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TH),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(bl)
    els.append(Spacer(1, 5 * mm))

    # ── 2. BILL TO / INVOICE INFO CARDS ─────────────────────────────────────
    def card(title, pairs):
        cw = W * 0.50
        r = [[
            Paragraph(f"<b>{title}</b>", S("_ch", fontSize=7, fontName="Helvetica-Bold", textColor=C5, leading=9)),
            Paragraph("", S("_cs", fontSize=2, leading=2)),
        ]]
        for a, b in pairs:
            r.append([
                Paragraph(a, S("_cl", fontSize=7, textColor=C5, leading=9.5)),
                Paragraph(f"{b}", S("_cv", fontSize=7.5, fontName="Helvetica-Bold", textColor=C4, leading=10)),
            ])
        t = Table(r, colWidths=[cw * 0.25, cw * 0.75])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 0.5, C3),
        ]))
        return t

    bd = [("Customer", safe(customer.get("customer_name"))), ("TRN", safe(customer.get("trn")))]
    if customer.get("phone"):
        bd.append(("Phone", customer["phone"]))
    if customer.get("email"):
        bd.append(("Email", customer["email"]))
    if customer.get("address"):
        addr_display = customer["address"].replace(" , Po Box", "<br/>Po Box").replace(", Po Box", "<br/>Po Box")
        bd.append(("Address", addr_display))

    id_ = [("Invoice #", inv_no), ("Date", inv_dt)]
    if invoice.get("so_no"):
        id_.append(("SO No.", invoice["so_no"]))
    if invoice.get("lpo_no"):
        id_.append(("LPO No.", invoice["lpo_no"]))
    if invoice.get("lpo_date"):
        id_.append(("LPO Date", invoice["lpo_date"]))
    if invoice.get("project_no"):
        id_.append(("Project No.", invoice["project_no"]))
    if invoice.get("ref_no"):
        id_.append(("Ref No.", invoice["ref_no"]))

    iw = Table([[card("BILL TO", bd), Spacer(1, 3 * mm), card("INVOICE INFO", id_)]], colWidths=[W * 0.50, 3 * mm, W * 0.50])
    iw.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(iw)
    els.append(Spacer(1, 5 * mm))

    # ── 3. ITEMS TABLE ──────────────────────────────────────────────────────
    sub = float(invoice.get("amount") or 0)
    vat = float(invoice.get("vat_amount") or 0)
    tot = float(invoice.get("total_amount") or 0)
    vp = float(invoice.get("vat_percent") or 0)

    num_rows = len(items) + 1
    fs = 7.0
    if num_rows > 0:
        avail_pt = A4[1] - TM - BM - 140 * mm
        target = avail_pt / max(num_rows, 1)
        fs = max(5.0, min(8.0, target / 3.0))
    ldr = fs * 1.2
    pad_t = max(1.0, fs * 0.3)
    pad_b = max(1.0, fs * 0.3)

    def _pc(t, **kw):
        kw.setdefault("fontSize", fs)
        kw.setdefault("leading", ldr)
        return Paragraph(str(t), S("_pc", **kw))

    cw = [9 * mm, 40 * mm, 20 * mm, 12 * mm, 16 * mm, 20 * mm, 13 * mm, 19 * mm, 19 * mm]
    hdr = [
        Paragraph("<b>#</b>", S("_h0", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=ldr)),
        Paragraph("<b>Description</b>", S("_h1", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, leading=ldr)),
        Paragraph("<b>Qty</b>", S("_h2", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=ldr)),
        Paragraph("<b>Unit</b>", S("_hu", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=ldr)),
        Paragraph("<b>Unit Price</b>", S("_h3", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=ldr)),
        Paragraph("<b>Taxable<br/>Amount</b>", S("_h4", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=ldr)),
        Paragraph("<b>VAT %</b>", S("_h5", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=ldr)),
        Paragraph("<b>VAT Amount</b>", S("_h6", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=ldr)),
        Paragraph("<b>Total<br/>(incl. VAT)</b>", S("_h7", fontSize=fs, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=ldr)),
    ]
    rws = [hdr]

    for idx, it in enumerate(items):
        vp_item = float(it.get("vat_percent_item") or invoice.get("vat_percent") or 5)
        amt = float(it.get("amount") or 0)
        va_item = float(it.get("vat_amount_item") or (amt * vp_item / 100))
        ti_item = float(it.get("total_incl_vat") or (amt + va_item))

        desc_html = it.get("description") or "—"
        if it.get("vehicle_no"):
            desc_html += f" <b>| Vehicle:</b> {it['vehicle_no']}"

        rws.append([
            _pc(str(idx + 1), alignment=TA_CENTER, fontName="Helvetica-Bold"),
            _pc(desc_html, fontSize=fs, leading=ldr * 0.9),
            _pc(f"{float(it.get('quantity') or 0):,.4f}", alignment=TA_CENTER),
            _pc((it.get('unit') or 'mo'), alignment=TA_CENTER),
            _pc(f"{float(it.get('rate') or 0):,.4f}", alignment=TA_RIGHT),
            _pc(f"{amt:,.2f}", alignment=TA_RIGHT),
            _pc(f"{vp_item:.2f}%", alignment=TA_CENTER),
            _pc(f"{va_item:,.2f}", alignment=TA_RIGHT, textColor=C6),
            Paragraph(f"<b>{ti_item:,.2f}</b>", S("_b", fontSize=fs, fontName="Helvetica-Bold", alignment=TA_RIGHT, leading=ldr)),
        ])

    itt = Table(rws, colWidths=cw, repeatRows=1)
    itt.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), DH),
        ("TEXTCOLOR", (0, 0), (-1, 0), WH),
        ("BOX", (0, 0), (-1, -1), 0.5, C3),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C3),
        ("TOPPADDING", (0, 0), (-1, -1), pad_t),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad_b),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WH, BG]),
    ]))
    els.append(itt)

    # ── 4. TOTALS ───────────────────────────────────────────────────────────
    tw = 90 * mm
    trows = [
        [Paragraph("Sub Total", S("_st", fontSize=9, textColor=C5, leading=12)),
         Paragraph(f"<b>AED {sub:,.2f}</b>", S("_stv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=12, alignment=TA_RIGHT))],
        [Paragraph(f"VAT @ {vp:.0f}%", S("_vt", fontSize=9, textColor=C5, leading=12)),
         Paragraph(f"<b>AED {vat:,.2f}</b>", S("_vtv", fontSize=9, fontName="Helvetica-Bold", textColor=C6, leading=12, alignment=TA_RIGHT))],
        [Paragraph("<b>Total Due</b>", S("_td", fontSize=12, fontName="Helvetica-Bold", textColor=C4, leading=15)),
         Paragraph(f"<b>AED {tot:,.2f}</b>", S("_tdv", fontSize=13, fontName="Helvetica-Bold", textColor=TH, leading=16, alignment=TA_RIGHT))],
    ]
    tt = Table(trows, colWidths=[tw * 0.40, tw * 0.60])
    tt.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.5, C3),
        ("LINEABOVE", (0, 2), (-1, 2), 1.5, TH),
    ]))

    ft = Table([["", tt]], colWidths=[W - tw, tw])
    ft.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(Spacer(1, 2 * mm))
    els.append(ft)

    # ── 5. AMOUNT IN WORDS ──────────────────────────────────────────────────
    def n2w(n):
        if n == 0:
            return "Zero"
        o = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
             "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
        t = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
        sc = ["", "Thousand", "Million", "Billion"]

        def h(num):
            r = ""
            if num >= 100:
                r += o[num // 100] + " Hundred"
                num %= 100
            if num and r:
                r += " "
            if num >= 20:
                r += t[num // 10]
                num %= 10
            if num and r:
                r += " "
            if num > 0:
                r += o[num]
            return r.strip()

        ip = int(n)
        dp = min(int(round((n - ip) * 100)), 99)
        if ip == 0:
            w = "Zero"
        else:
            w = ""
            i = 0
            while ip > 0:
                ck = ip % 1000
                if ck:
                    cw = h(ck)
                    if sc[i]:
                        cw += " " + sc[i]
                    w = cw + (" " + w if w else "")
                ip //= 1000
                i += 1
        if dp:
            w += f" and {dp:02d}/100"
        return "AED " + w + " Only"

    els.append(Spacer(1, 4 * mm))
    ab = Table([[Paragraph(f"<b>Amount in Words:</b> {n2w(tot)}", S("AW", fontSize=9, textColor=C4, leading=14))]], colWidths=[W])
    ab.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    els.append(ab)

    # Notes
    display_notes = invoice.get("notes") or ""
    if display_notes:
        els.append(Spacer(1, 3 * mm))
        nb = Table([[Paragraph(f"<b>Notes:</b> {display_notes}", S("NW", fontSize=7.5, textColor=C4, leading=10))]], colWidths=[W])
        nb.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BG),
            ("BOX", (0, 0), (-1, -1), 0.5, C3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        els.append(nb)

    # ── 6. BANK DETAILS ─────────────────────────────────────────────────────
    if company.get("bank_name") or company.get("bank_account_name") or company.get("iban"):
        bk_items = []
        if company.get("bank_name"):
            bk_items.append(("Bank", company["bank_name"]))
        if company.get("bank_account_name"):
            bk_items.append(("Account", company["bank_account_name"]))
        if company.get("bank_account_number"):
            bk_items.append(("A/C No.", company["bank_account_number"]))
        if company.get("iban"):
            bk_items.append(("IBAN", company["iban"]))
        if company.get("swift_code"):
            bk_items.append(("Swift", company["swift_code"]))
        if bk_items:
            els.append(Spacer(1, 3 * mm))
            els.append(Paragraph("<b>BANK DETAILS</b>", S("BD", fontSize=7, fontName="Helvetica-Bold", textColor=C5, leading=9, spaceAfter=2)))
            bk_rows = [[
                Paragraph(f"<font color='#64748b'>{lbl}:</font>", S("_bkl", fontSize=7, textColor=C5, leading=9)),
                Paragraph(f"<b>{val}</b>", S("_bkv", fontSize=7, fontName="Helvetica-Bold", textColor=C4, leading=9)),
            ] for lbl, val in bk_items]
            bkt = Table(bk_rows, colWidths=[20 * mm, W - 20 * mm])
            bkt.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]))
            els.append(bkt)

    # ── 7. SIGNATURES ───────────────────────────────────────────────────────
    els.append(Spacer(1, 4 * mm))
    sg = ParagraphStyle("SG", fontSize=8, alignment=TA_CENTER, leading=11)

    stamp_img = Image(stamp_path, width=60, height=60) if stamp_path else None
    sign_img = Image(sign_path, width=60, height=60) if sign_path else None

    auth_img = []
    if stamp_img:
        auth_img.append(stamp_img)
    if sign_img:
        auth_img.append(sign_img)

    if auth_img:
        auth_imgs = Table([auth_img], colWidths=[60] * len(auth_img))
        auth_imgs.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]))
    else:
        auth_imgs = Paragraph("", sg)

    auth_cell = Table([
        [Paragraph("_________________________", sg)],
        [auth_imgs],
        [Paragraph("<b>Authorized Signatory</b>", sg)],
    ], colWidths=[W * 0.38])
    auth_cell.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    sgt = Table([[
        auth_cell,
        Paragraph("", sg),
    ]], colWidths=[W * 0.50, W * 0.50])
    sgt.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (0, 0), 0.5, C5),
        ("LINEABOVE", (1, 0), (1, 0), 0.5, C5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(sgt)

    # ── 8. FOOTER ───────────────────────────────────────────────────────────
    ftr_rows = []
    if c_addr:
        addr_parts = [p.strip() for p in c_addr.split(",")]
        addr_display = ", ".join(addr_parts[:2]) + "<br/>" + ", ".join(addr_parts[2:]) if len(addr_parts) > 2 else c_addr
        ftr_rows.append(Paragraph(f"<font size=6.5 color='#64748b'>{addr_display}</font>", S("_ad", fontSize=6.5, textColor=C5, alignment=TA_CENTER, leading=8)))
        ftr_rows.append(Spacer(1, 2 * mm))

    bar = Table([[""]], colWidths=[W], rowHeights=[1.2])
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TH),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    ftr_rows.append(bar)
    ftr_rows.append(Spacer(1, 2 * mm))
    ftr_rows.append(Paragraph(
        "This is a computer-generated Tax Invoice. Valid without signature.",
        S("FN", fontSize=6.5, textColor=C5, alignment=TA_CENTER, leading=8),
    ))

    ftr_table = Table([[r] for r in ftr_rows], colWidths=[W])
    ftr_table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(TopPadder(ftr_table))

    # ── BUILD ───────────────────────────────────────────────────────────────
    doc.build(els)
    for f in _logo_tmp_files:
        try:
            import os
            os.remove(f)
        except Exception:
            pass

    pdf_data = buf.getvalue()
    buf.close()
    with open(output_path, "wb") as out:
        out.write(pdf_data)
    return str(output_path)
