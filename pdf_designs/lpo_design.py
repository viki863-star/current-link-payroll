"""
Local Purchase Order (LPO) PDF Template
========================================
Standalone template for generating professional LPO documents.

Usage:
    from lpo_design import generate_lpo_pdf
    generate_lpo_pdf(company, party, lpo, output_path)
"""

from base_design import *


# ── Standard LPO Terms ──────────────────────────────────────────────────────────
LPO_STANDARD_TERMS = [
    "1. This order is subject to the supplier's acceptance in writing within the stated validity period.",
    "2. Prices are inclusive of all applicable taxes unless explicitly stated otherwise.",
    "3. Goods/services must comply with the specifications and delivery schedule noted above.",
    "4. Any variation from this order requires written approval from the buyer.",
    "5. Payment will be processed upon satisfactory delivery and receipt of valid invoice.",
]


def generate_lpo_pdf(
    company: dict,
    party: dict,
    lpo: dict,
    output_path: str,
    company_profile: dict | None = None,
) -> str:
    """Generate a standalone Local Purchase Order PDF.

    Args:
        company:         Company profile dict (company_name, trn_no, address, etc.)
        party:           Supplier/party dict (party_name, party_code, contact_person, etc.)
        lpo:             LPO data dict with keys:
                           lpo_no, issue_date, valid_until, quotation_no,
                           job_title, description, amount, tax_percent,
                           tax_amount, total_amount, payment_terms,
                           delivery_terms, additional_terms, notes
        output_path:     Absolute path for the output PDF file.
        company_profile: Alias for company (used for header rendering).

    Returns:
        Absolute path to the generated PDF.
    """
    cp = company or company_profile or {}
    currency = cp.get("base_currency") or "AED"

    amount = float(lpo.get("amount") or 0.0)
    tax_percent = float(lpo.get("tax_percent") or 0.0)
    tax_amount = float(lpo.get("tax_amount") or round(amount * tax_percent / 100.0, 2))
    total_amount = float(lpo.get("total_amount") or round(amount + tax_amount, 2))

    pdf = canvas.Canvas(str(output_path), pagesize=A4)

    # ── 1. Header card (logo, company name, address, TRN) ────────────────────────
    _draw_header(pdf, company_profile=cp)

    # ── 2. Title row ─────────────────────────────────────────────────────────────
    _draw_title(
        pdf,
        "Local Purchase Order",
        f"LPO {lpo.get('lpo_no', '-')}  |  Issued {format_date_label(lpo.get('issue_date'))}",
    )

    # ── 3. LPO metadata strip ────────────────────────────────────────────────────
    meta_y = PAGE_HEIGHT - 76 * mm
    meta_h = 11 * mm
    pdf.setFillColor(BLUE_SOFT)
    pdf.roundRect(15 * mm, meta_y, 180 * mm, meta_h, 3 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(15 * mm, meta_y, 180 * mm, meta_h, 3 * mm, fill=0, stroke=1)

    meta_pairs = [
        ("LPO No", lpo.get("lpo_no") or "-"),
        ("Issue Date", format_date_label(lpo.get("issue_date"))),
        ("Valid Until", format_date_label(lpo.get("valid_until")) if lpo.get("valid_until") else "Open"),
        ("Quotation Ref", lpo.get("quotation_no") or "-"),
        ("Status", "Issued"),
    ]
    col_w = 180 * mm / len(meta_pairs)
    for idx, (label, value) in enumerate(meta_pairs):
        cx = 15 * mm + idx * col_w + col_w / 2
        pdf.setFillColor(BLUE_DARK)
        pdf.setFont("Helvetica-Bold", 6.2)
        pdf.drawCentredString(cx, meta_y + 7.2 * mm, label.upper())
        pdf.setFillColor(TEXT)
        val_text, val_size = _fit_text(pdf, str(value), "Helvetica-Bold", 7.5, col_w - 4 * mm, min_size=6.0)
        pdf.setFont("Helvetica-Bold", val_size)
        pdf.drawCentredString(cx, meta_y + 2.4 * mm, val_text)

    # ── 4. Supplier details card ─────────────────────────────────────────────────
    card_y = PAGE_HEIGHT - 110 * mm
    card_h = 28 * mm
    card_w = 180 * mm
    pdf.setFillColor(WHITE)
    pdf.roundRect(15 * mm, card_y, card_w, card_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(15 * mm, card_y, card_w, card_h, 4 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.roundRect(15 * mm, card_y + card_h - 8 * mm, card_w, 8 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(WHITE)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(20 * mm, card_y + card_h - 5.2 * mm, "SUPPLIER DETAILS")

    supplier_rows = [
        ("Supplier Name", (party or {}).get("party_name") or "-"),
        ("Supplier Code", (party or {}).get("party_code") or "-"),
        ("Contact", (party or {}).get("contact_person") or "-"),
        ("Phone", (party or {}).get("phone_number") or "-"),
        ("TRN", (party or {}).get("trn_no") or "-"),
        ("Email", (party or {}).get("email") or "-"),
    ]
    row_y = card_y + card_h - 13 * mm
    for idx, (label, value) in enumerate(supplier_rows):
        col = idx % 3
        if idx and col == 0:
            row_y -= 6 * mm
        x = 20 * mm + col * 60 * mm
        _draw_label_value_row(pdf, x, row_y, 20 * mm, 36 * mm, label, value)

    # ── 5. Work description / scope of work ──────────────────────────────────────
    desc_y = PAGE_HEIGHT - 146 * mm
    desc_h = 30 * mm
    pdf.setFillColor(SOFT)
    pdf.roundRect(15 * mm, desc_y, 180 * mm, desc_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(15 * mm, desc_y, 180 * mm, desc_h, 4 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(20 * mm, desc_y + desc_h - 5.5 * mm, "SCOPE OF WORK / DESCRIPTION")

    job_title = (lpo.get("job_title") or "").strip()
    description = (lpo.get("description") or "").strip()
    combined_desc = (
        f"{job_title}  —  {description}"
        if job_title and description
        else (job_title or description or "As per agreed quotation.")
    )
    desc_lines = _wrap_text_lines(pdf, combined_desc, "Helvetica", 8.0, 168 * mm, max_lines=3, min_size=6.5)
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica", 8.0)
    for idx, line in enumerate(desc_lines):
        pdf.drawString(20 * mm, desc_y + desc_h - 13 * mm - idx * 5.5 * mm, line)

    # ── 6. Amount summary boxes ──────────────────────────────────────────────────
    amt_y = PAGE_HEIGHT - 164 * mm
    _draw_stat_box(
        pdf, 15 * mm, amt_y, 55 * mm, 13 * mm, "SUBTOTAL",
        f"{currency} {format_currency(amount)}",
    )
    _draw_stat_box(
        pdf, 74 * mm, amt_y, 55 * mm, 13 * mm, f"VAT ({tax_percent:.1f}%)",
        f"{currency} {format_currency(tax_amount)}", fill_color=SOFT,
    )
    _draw_stat_box(
        pdf, 133 * mm, amt_y, 62 * mm, 13 * mm, "TOTAL AMOUNT",
        f"{currency} {format_currency(total_amount)}",
        fill_color=BLUE, text_color=WHITE, border_color=BLUE,
    )

    # ── 7. Payment & delivery terms row ──────────────────────────────────────────
    terms_y = PAGE_HEIGHT - 184 * mm
    terms_h = 14 * mm
    pdf.setFillColor(WHITE)
    pdf.roundRect(15 * mm, terms_y, 180 * mm, terms_h, 3 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(15 * mm, terms_y, 180 * mm, terms_h, 3 * mm, fill=0, stroke=1)
    _draw_small_meta_row(
        pdf, 20 * mm, terms_y + 8.5 * mm, "Payment Terms",
        lpo.get("payment_terms") or "As per company standard terms", 85 * mm,
    )
    _draw_small_meta_row(
        pdf, 98 * mm, terms_y + 8.5 * mm, "Delivery / Completion",
        lpo.get("delivery_terms") or "As agreed", 80 * mm,
    )
    _draw_small_meta_row(
        pdf, 20 * mm, terms_y + 3.2 * mm, "Notes",
        lpo.get("notes") or "-", 160 * mm,
    )

    # ── 8. Standard terms & conditions ───────────────────────────────────────────
    tc_y = PAGE_HEIGHT - 212 * mm
    tc_h = 24 * mm
    pdf.setFillColor(WHITE)
    pdf.roundRect(15 * mm, tc_y, 180 * mm, tc_h, 3 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(15 * mm, tc_y, 180 * mm, tc_h, 3 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(20 * mm, tc_y + tc_h - 5 * mm, "STANDARD TERMS & CONDITIONS")
    pdf.setFillColor(MUTED)
    tc_line_y = tc_y + tc_h - 9.5 * mm
    for term in LPO_STANDARD_TERMS[:4]:
        term_text, term_size = _fit_text(pdf, term, "Helvetica", 6.2, 168 * mm, min_size=5.5)
        pdf.setFont("Helvetica", term_size)
        pdf.drawString(20 * mm, tc_line_y, term_text)
        tc_line_y -= 4.0 * mm
        if tc_line_y < tc_y + 1 * mm:
            break

    # ── 9. Custom / additional terms ─────────────────────────────────────────────
    extra = (lpo.get("additional_terms") or "").strip()
    if extra:
        extra_y = tc_y - 14 * mm
        extra_h = 11 * mm
        pdf.setFillColor(colors.HexColor("#FFF9EE"))
        pdf.roundRect(15 * mm, extra_y, 180 * mm, extra_h, 3 * mm, fill=1, stroke=0)
        pdf.setStrokeColor(ORANGE)
        pdf.roundRect(15 * mm, extra_y, 180 * mm, extra_h, 3 * mm, fill=0, stroke=1)
        pdf.setFillColor(ORANGE)
        pdf.setFont("Helvetica-Bold", 7.5)
        pdf.drawString(20 * mm, extra_y + extra_h - 5 * mm, "ADDITIONAL / SPECIAL TERMS")
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica", 7.0)
        extra_lines = _wrap_text_lines(pdf, extra, "Helvetica", 7.0, 168 * mm, max_lines=2, min_size=6.0)
        for idx, line in enumerate(extra_lines):
            pdf.drawString(20 * mm, extra_y + extra_h - 9.5 * mm - idx * 4.5 * mm, line)

    # ── 10. Signature / authorisation row ────────────────────────────────────────
    sig_y = 26 * mm
    sig_h = 18 * mm
    for sig_x, sig_label in [
        (15 * mm, "Authorised Signatory — Company"),
        (112 * mm, "Acknowledged — Supplier"),
    ]:
        pdf.setFillColor(SOFT)
        pdf.roundRect(sig_x, sig_y, 83 * mm, sig_h, 3 * mm, fill=1, stroke=0)
        pdf.setStrokeColor(LINE)
        pdf.roundRect(sig_x, sig_y, 83 * mm, sig_h, 3 * mm, fill=0, stroke=1)
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 6.5)
        pdf.drawString(sig_x + 3 * mm, sig_y + sig_h - 5 * mm, sig_label)
        pdf.setStrokeColor(LINE)
        pdf.line(sig_x + 3 * mm, sig_y + 5 * mm, sig_x + 80 * mm, sig_y + 5 * mm)
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 6.0)
        pdf.drawString(sig_x + 3 * mm, sig_y + 1.5 * mm, "Name & Stamp")

    # ── 11. Footer ───────────────────────────────────────────────────────────────
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.8)
    pdf.drawString(
        15 * mm, 20 * mm,
        f"Generated on {datetime.now().strftime('%d-%b-%Y %I:%M %p')}  |  "
        f"{cp.get('company_name', 'COMPANY')}  |  TRN: {cp.get('trn_no') or '-'}",
    )
    _draw_footer_banner(pdf, company_profile=cp)

    pdf.showPage()
    pdf.save()
    return str(output_path)
