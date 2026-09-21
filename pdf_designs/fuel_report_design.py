"""
Fuel Report PDF Template
=========================
Standalone template for generating vehicle fuel consumption reports.

Usage:
    from fuel_report_design import generate_fuel_report_pdf
    generate_fuel_report_pdf(company, entries, output_path, month_label, vehicle_filter)
"""

from base_design import *

from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from io import BytesIO
from collections import Counter


def generate_fuel_report_pdf(
    company: dict,
    entries: list,
    output_path: str,
    month_label: str = "All Periods",
    vehicle_filter: str = "",
) -> str:
    """Generate a standalone Fuel Report PDF.

    Args:
        company:         Company profile dict (company_name, trn_no, address, etc.)
        entries:         List of fuel entry dicts, each with keys:
                           entry_date, vehicle_plate, gallons, rate_per_gallon,
                           total_amount, supplier_name
        output_path:     Absolute path for the output PDF file.
        month_label:     Display label for the period (e.g. "Aug 2026").
        vehicle_filter:  Vehicle plate filter text (optional).

    Returns:
        Absolute path to the generated PDF.
    """
    company = company or {}
    entries = list(entries or [])

    # ── Compute totals ───────────────────────────────────────────────────────────
    total_gallons = sum(float(r.get("gallons", 0) or 0) for r in entries)
    total_amount = sum(float(r.get("total_amount", 0) or 0) for r in entries)
    subtitle = month_label + (f" | Vehicle: {vehicle_filter}" if vehicle_filter else "")

    veh_totals = Counter()
    for r in entries:
        plate = r.get("vehicle_plate") or "Unknown"
        veh_totals[plate] += float(r.get("gallons", 0) or 0)
    top_vehicles = veh_totals.most_common(10)

    # ── Color palette ────────────────────────────────────────────────────────────
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
    RD = colors.HexColor("#c62828")

    # ── Build document ───────────────────────────────────────────────────────────
    buf = BytesIO()
    LM, RM, TM, BM = 12 * mm, 12 * mm, 15 * mm, 15 * mm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM
    els = []

    cn = company.get("company_name", "COMPANY NAME")
    trn = company.get("trn_no") or "\u2014"

    # ── 1. HEADER ────────────────────────────────────────────────────────────────
    addr = company.get("address") or ""
    ph = company.get("phone_number") or ""
    em = company.get("email") or ""
    parts = [x for x in [addr] if x]
    cparts = [x for x in [ph, em] if x]
    info = ""
    if parts or cparts:
        info = " &middot; ".join(parts + cparts)

    cl = [f"<font size=10><b>{cn}</b></font>"]
    if info:
        cl.append(f'<font size=6 color="#6b7280">{info}</font>')
    if trn and trn != "\u2014":
        cl.append(f'<font size=6 color="#6b7280">TRN: {trn}</font>')

    co_p = Paragraph(
        "<br/>".join(cl),
        ParagraphStyle("CO", fontSize=10, fontName="Helvetica-Bold", textColor=TH, leading=12),
    )

    rh = Paragraph(
        f"<b>FUEL CONSUMPTION<br/>REPORT</b><br/><font size=6.5 color='#6b7280'>{subtitle}</font>",
        ParagraphStyle("TI", fontSize=13, fontName="Helvetica-Bold", textColor=TH, leading=16, alignment=TA_RIGHT),
    )

    ht = Table([[co_p, rh]], colWidths=[W * 0.65, W * 0.35])
    ht.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    els.append(ht)
    els.append(Spacer(1, 2 * mm))

    # Accent line
    hr = Table([[""]], colWidths=[W], rowHeights=[1.5])
    hr.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TH), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    els.append(hr)
    els.append(Spacer(1, 4 * mm))

    # ── 2. PERIOD BADGE ──────────────────────────────────────────────────────────
    badge = Table([[Paragraph(f"<b>{subtitle}</b>", ParagraphStyle("b", fontSize=7, fontName="Helvetica-Bold", textColor=TH, alignment=TA_CENTER, leading=9))]], colWidths=[160])
    badge.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, TH),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    els.append(badge)
    els.append(Spacer(1, 4 * mm))

    # ── 3. SUMMARY CARDS ─────────────────────────────────────────────────────────
    sdata = [[
        Paragraph(f"<b>Total Gallons (GLN)</b><br/><font size=10 color='#1a3a5c'>{total_gallons:,.2f}</font>", ParagraphStyle("_s1", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Total Amount (AED)</b><br/><font size=10 color='#c62828'>AED {total_amount:,.2f}</font>", ParagraphStyle("_s2", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Total Entries</b><br/><font size=10 color='#1a3a5c'>{len(entries)}</font>", ParagraphStyle("_s3", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
    ]]
    st = Table(sdata, colWidths=[W / 3, W / 3, W / 3])
    st.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, C3), ("INNERGRID", (0, 0), (-1, -1), 0.3, C3),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 0), (-1, -1), BG),
    ]))
    els.append(st)
    els.append(Spacer(1, 5 * mm))

    # ── 4. DATA TABLE ────────────────────────────────────────────────────────────
    cw_d = int(W * 0.12)
    cw_v = int(W * 0.10)
    cw_g = int(W * 0.10)
    cw_r = int(W * 0.12)
    cw_a = int(W * 0.16)
    cw_s = W - cw_d - cw_v - cw_g - cw_r - cw_a

    def supp_p(t):
        return Paragraph(str(t or "\u2014"), ParagraphStyle("s", fontSize=6, textColor=C5, leading=7.5, alignment=TA_LEFT))

    hdr = [
        Paragraph("<b>Date</b>", ParagraphStyle("h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph("<b>Vehicle</b>", ParagraphStyle("h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph("<b>GLN</b>", ParagraphStyle("h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
        Paragraph("<b>Rate/GLN</b>", ParagraphStyle("h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
        Paragraph("<b>Total AED</b>", ParagraphStyle("h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
        Paragraph("<b>Supplier</b>", ParagraphStyle("h", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_LEFT, leading=9)),
    ]

    rws = [hdr]
    for r in entries:
        rws.append([
            str(r.get("entry_date") or "\u2014"),
            str(r.get("vehicle_plate") or "\u2014"),
            f"{float(r.get('gallons') or 0):,.2f}",
            f"{float(r.get('rate_per_gallon') or 0):,.3f}",
            f"{float(r.get('total_amount') or 0):,.2f}",
            supp_p(r.get("supplier_name")),
        ])

    # Totals row
    rws.append([
        Paragraph("<b>Total</b>", ParagraphStyle("t", fontSize=8, fontName="Helvetica-Bold", textColor=WH, leading=10, alignment=TA_CENTER)),
        "",
        Paragraph(f"<b>{total_gallons:,.2f}</b>", ParagraphStyle("t", fontSize=8, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        "",
        Paragraph(f"<b>{total_amount:,.2f}</b>", ParagraphStyle("t", fontSize=8, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        Paragraph("<b>\u2014</b>", ParagraphStyle("t", fontSize=8, fontName="Helvetica-Bold", textColor=WH, leading=10)),
    ])

    it = Table(rws, colWidths=[cw_d, cw_v, cw_g, cw_r, cw_a, cw_s], repeatRows=1)
    it.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), TH), ("TEXTCOLOR", (0, 0), (-1, 0), WH),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("ALIGN", (2, 1), (2, -2), "RIGHT"),
        ("ALIGN", (3, 1), (3, -2), "RIGHT"),
        ("ALIGN", (4, 1), (4, -2), "RIGHT"),
        ("ALIGN", (5, 1), (5, -2), "LEFT"),
        ("FONTSIZE", (0, 1), (4, -2), 6),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (4, 1), (4, -2), RD),
        ("FONTNAME", (4, 1), (4, -2), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("BACKGROUND", (0, -1), (-1, -1), TH), ("TEXTCOLOR", (0, -1), (-1, -1), WH),
        ("BOX", (0, 0), (-1, -1), 0.5, C3), ("INNERGRID", (0, 0), (-1, -1), 0.3, C3),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, TH),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, TH),
        ("ROWBACKGROUNDS", (0, 1), (-2, -2), [WH, BG]),
    ]))
    els.append(it)
    els.append(Spacer(1, 5 * mm))

    # ── 5. TOP VEHICLES BAR CHART ────────────────────────────────────────────────
    if top_vehicles:
        from reportlab.graphics.shapes import Drawing, Rect, String, Line
        from reportlab.graphics import renderPDF

        CH = 155
        d = Drawing(W, CH)
        LM_CHART = 70
        RM_CHART = 50
        TM_CHART = 22
        BM_CHART = 18
        PW = W - LM_CHART - RM_CHART
        PH = CH - TM_CHART - BM_CHART
        max_val = max(v for _, v in top_vehicles)
        n = len(top_vehicles)

        # Chart title
        d.add(String(W / 2, CH - 4, "Top Vehicles by Fuel Consumption",
                     textAnchor="middle", fontSize=9, fontName="Helvetica-Bold", fillColor=TH))

        # Grid lines
        for i in range(6):
            x = LM_CHART + PW * i / 5
            d.add(Line(x, BM_CHART, x, BM_CHART + PH, strokeColor=colors.Color(0.88, 0.88, 0.88), strokeWidth=0.4))

        # X-axis line
        d.add(Line(LM_CHART, BM_CHART, LM_CHART + PW, BM_CHART, strokeColor=colors.Color(0.7, 0.7, 0.7), strokeWidth=0.5))

        # Grid labels
        for i in range(6):
            v = max_val * i / 5
            x = LM_CHART + PW * i / 5
            d.add(String(x, BM_CHART - 3, f"{v:,.0f}", textAnchor="middle", fontSize=5.5, fillColor=C5))

        # Bars
        bars = top_vehicles[:10]
        bs = PH / (n + 0.5)
        bh = bs * 0.6

        for i, (plate, gal) in enumerate(bars):
            y = BM_CHART + bs * (n - 1 - i) + (bs - bh) / 2
            bw = (gal / max_val) * PW if max_val > 0 else 0

            # Vehicle label (y-axis)
            d.add(String(LM_CHART - 6, y + bh / 2, plate,
                         textAnchor="end", fontSize=6, fontName="Helvetica", fillColor=C4))

            # Bar
            d.add(Rect(LM_CHART, y, max(bw, 1), bh, fillColor=colors.HexColor("#1C568B"), strokeColor=None))

            # GLN value at end of bar
            d.add(String(LM_CHART + max(bw, 0) + 3, y + bh / 2, f"{gal:,.0f}",
                         textAnchor="start", fontSize=6.5, fontName="Helvetica-Bold", fillColor=C4))

        # X-axis label
        d.add(String(LM_CHART + PW / 2, 2, "Fuel Consumption (GLN)",
                     textAnchor="middle", fontSize=7, fontName="Helvetica", fillColor=C5))

        els.append(Spacer(1, 2 * mm))
        els.append(d)
        els.append(Spacer(1, 4 * mm))

    # ── 6. FOOTER ────────────────────────────────────────────────────────────────
    els.append(Paragraph(
        f'<font size=6.5 color="#6b7280">Generated on {datetime.now().strftime("%d-%b-%Y %I:%M %p")}</font>',
        ParagraphStyle("_ft", fontSize=6.5, textColor=C5, alignment=TA_CENTER, leading=9),
    ))

    # ── Build ────────────────────────────────────────────────────────────────────
    doc.build(els)
    pdf_data = buf.getvalue()
    buf.close()

    with open(output_path, "wb") as f:
        f.write(pdf_data)
    return str(output_path)
