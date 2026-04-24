from __future__ import annotations

import base64
from datetime import date as date_cls
from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


PAGE_WIDTH, PAGE_HEIGHT = A4
BLUE = colors.HexColor("#1C568B")
BLUE_DARK = colors.HexColor("#15335D")
BLUE_SOFT = colors.HexColor("#EAF2FB")
ORANGE = colors.HexColor("#E6871F")
GREEN = colors.HexColor("#2CB15C")
RED = colors.HexColor("#D44A3A")
SLATE = colors.HexColor("#40556E")
TEXT = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#667A95")
LINE = colors.HexColor("#D7E2EF")
SOFT = colors.HexColor("#F6F9FD")


# ── Standard LPO terms that appear on every issued LPO ────────────────────────
LPO_STANDARD_TERMS = [
    "1. This LPO is valid solely for the scope, period and amount stated above.",
    "2. All services or supplies must strictly conform to specifications agreed with the company.",
    "3. Every invoice submitted must quote this LPO number or it will not be processed.",
    "4. No variation in scope, quantity or price is authorised without a written amendment.",
    "5. Payment will be settled as per the agreed payment terms stated on this document.",
    "6. The supplier must comply with all applicable UAE laws, regulations and company policies.",
    "7. The company reserves the right to inspect work prior to approval of the invoice.",
]


def generate_lpo_pdf(company, party, lpo: dict, assets_dir: str, output_dir: str) -> str:
    """Generate a professional A4 LPO PDF.

    Args:
        company: company_profile DB row (may be None).
        party:   supplier party DB row.
        lpo:     dict with keys: lpo_no, issue_date, valid_until, quotation_no,
                 job_title, description, amount, tax_percent, tax_amount,
                 total_amount, payment_terms, delivery_terms, additional_terms, notes.
        assets_dir: path to STATIC_ASSETS_DIR (for the header banner).
        output_dir: directory to write the PDF into.
    Returns:
        Absolute string path to the generated PDF.
    """
    safe_no = str(lpo["lpo_no"]).replace("/", "-")
    output_path = Path(output_dir) / f"{safe_no}_lpo.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    company = company or {}
    currency = company.get("base_currency") or "AED"

    amount      = float(lpo.get("amount") or 0.0)
    tax_percent = float(lpo.get("tax_percent") or 0.0)
    tax_amount  = float(lpo.get("tax_amount") or round(amount * tax_percent / 100.0, 2))
    total_amount = float(lpo.get("total_amount") or round(amount + tax_amount, 2))

    pdf = canvas.Canvas(str(output_path), pagesize=A4)

    # ── Header & title ────────────────────────────────────────────────────────
    _draw_header(pdf, assets_dir)
    _draw_title(
        pdf,
        "Local Purchase Order",
        f"LPO {lpo['lpo_no']}  |  Issued {format_date_label(lpo.get('issue_date'))}",
    )

    # ── LPO metadata strip ────────────────────────────────────────────────────
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
        pdf.setFont("Helvetica-Bold", 7.5)
        val_text, val_size = _fit_text(pdf, str(value), "Helvetica-Bold", 7.5, col_w - 4 * mm, min_size=6.0)
        pdf.setFont("Helvetica-Bold", val_size)
        pdf.drawCentredString(cx, meta_y + 2.4 * mm, val_text)

    # ── Supplier details card ─────────────────────────────────────────────────
    card_y = PAGE_HEIGHT - 110 * mm
    card_h = 28 * mm
    card_w = 180 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(15 * mm, card_y, card_w, card_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(15 * mm, card_y, card_w, card_h, 4 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.roundRect(15 * mm, card_y + card_h - 8 * mm, card_w, 8 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
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

    # ── Work description ──────────────────────────────────────────────────────
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
    combined_desc = f"{job_title}  —  {description}" if job_title and description else (job_title or description or "As per agreed quotation.")
    desc_lines = _wrap_text_lines(pdf, combined_desc, "Helvetica", 8.0, 168 * mm, max_lines=3, min_size=6.5)
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica", 8.0)
    for idx, line in enumerate(desc_lines):
        pdf.drawString(20 * mm, desc_y + desc_h - 13 * mm - idx * 5.5 * mm, line)

    # ── Amount summary ────────────────────────────────────────────────────────
    amt_y = PAGE_HEIGHT - 164 * mm
    _draw_stat_box(pdf, 15 * mm,   amt_y, 55 * mm, 13 * mm, "SUBTOTAL",
                   f"{currency} {format_currency(amount)}")
    _draw_stat_box(pdf, 74 * mm,   amt_y, 55 * mm, 13 * mm, f"VAT ({tax_percent:.1f}%)",
                   f"{currency} {format_currency(tax_amount)}", fill_color=SOFT)
    _draw_stat_box(pdf, 133 * mm,  amt_y, 62 * mm, 13 * mm, "TOTAL AMOUNT",
                   f"{currency} {format_currency(total_amount)}",
                   fill_color=BLUE, text_color=colors.white, border_color=BLUE)

    # ── Payment & delivery terms ──────────────────────────────────────────────
    terms_y = PAGE_HEIGHT - 184 * mm
    terms_h = 14 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(15 * mm, terms_y, 180 * mm, terms_h, 3 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(15 * mm, terms_y, 180 * mm, terms_h, 3 * mm, fill=0, stroke=1)
    _draw_small_meta_row(pdf, 20 * mm, terms_y + 8.5 * mm, "Payment Terms",
                         lpo.get("payment_terms") or "As per company standard terms", 85 * mm)
    _draw_small_meta_row(pdf, 98 * mm, terms_y + 8.5 * mm, "Delivery / Completion",
                         lpo.get("delivery_terms") or "As agreed", 80 * mm)
    _draw_small_meta_row(pdf, 20 * mm, terms_y + 3.2 * mm, "Notes",
                         lpo.get("notes") or "-", 160 * mm)

    # ── Standard terms & conditions ───────────────────────────────────────────
    tc_y = PAGE_HEIGHT - 212 * mm
    tc_h = 24 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(15 * mm, tc_y, 180 * mm, tc_h, 3 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(15 * mm, tc_y, 180 * mm, tc_h, 3 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(20 * mm, tc_y + tc_h - 5 * mm, "STANDARD TERMS & CONDITIONS")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.2)
    tc_line_y = tc_y + tc_h - 9.5 * mm
    for term in LPO_STANDARD_TERMS[:4]:
        term_text, term_size = _fit_text(pdf, term, "Helvetica", 6.2, 168 * mm, min_size=5.5)
        pdf.setFont("Helvetica", term_size)
        pdf.drawString(20 * mm, tc_line_y, term_text)
        tc_line_y -= 4.0 * mm
        if tc_line_y < tc_y + 1 * mm:
            break

    # ── Custom / additional terms ─────────────────────────────────────────────
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

    # ── Signature / authorisation row ─────────────────────────────────────────
    sig_y = 26 * mm
    sig_h = 18 * mm
    for sig_x, sig_label in [(15 * mm, "Authorised Signatory — Company"), (112 * mm, "Acknowledged — Supplier")]:
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

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.8)
    pdf.drawString(15 * mm, 20 * mm,
                   f"Generated on {datetime.now().strftime('%d-%b-%Y %I:%M %p')}  |  "
                   f"{company.get('company_name') or 'Current Link'}  |  "
                   f"TRN: {company.get('trn_no') or '-'}")
    _draw_footer_banner(pdf, assets_dir)

    pdf.showPage()
    pdf.save()
    return str(output_path)

def generate_salary_slip_pdf(driver, salary_row, slip_payload, output_dir: str, assets_dir: str, generated_dir: str) -> str:
    output_path = Path(output_dir) / f"{driver['driver_id']}_{salary_row['salary_month']}_salary-slip.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    _draw_header(pdf, assets_dir)
    _draw_title(
        pdf,
        f"Salary Slip {format_month_label(salary_row['salary_month'])}",
        "Payroll summary with earnings, deductions and payment details",
    )
    _draw_salary_summary(pdf, driver, salary_row, slip_payload)
    _draw_salary_breakdown(pdf, salary_row, slip_payload)
    _draw_salary_footer(pdf, driver, slip_payload, assets_dir, generated_dir)
    pdf.showPage()
    pdf.save()
    return str(output_path)


def generate_kata_pdf(driver, salary_rows, transactions, salary_slips, output_dir: str, assets_dir: str) -> str:
    output_path = Path(output_dir) / f"{driver['driver_id']}_kata-statement.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    entries = []
    for salary in salary_rows:
        entries.append(
            {
                "date": _iso_date_value(salary["entry_date"]),
                "reference": f"Salary {format_month_label(salary['salary_month'])}",
                "salary_added": float(salary["net_salary"]),
                "advance_taken": 0.0,
                "deducted": 0.0,
                "net_paid": 0.0,
                "details": "Salary stored",
            }
        )
    for txn in transactions:
        entries.append(
            {
                "date": _iso_date_value(txn["entry_date"]),
                "reference": txn["txn_type"],
                "salary_added": 0.0,
                "advance_taken": float(txn["amount"]),
                "deducted": 0.0,
                "net_paid": 0.0,
                "details": f"{txn['source']} / {txn.get('given_by', '') or '-'}",
            }
        )
    for slip in salary_slips:
        entries.append(
            {
                "date": _iso_date_value(slip["generated_at"]),
                "reference": f"Slip {format_month_label(slip['salary_month'])}",
                "salary_added": 0.0,
                "advance_taken": 0.0,
                "deducted": float(slip["total_deductions"]),
                "net_paid": float(slip["net_payable"]),
                "details": f"{slip['payment_source'] or '-'} / {slip['paid_by'] or '-'}",
            }
        )
    entries.sort(key=lambda item: item["date"])

    total_salary = sum(float(row["net_salary"]) for row in salary_rows)
    total_advance = sum(float(item["amount"]) for item in transactions)
    total_deducted = sum(float(item["total_deductions"]) for item in salary_slips)
    total_net_paid = sum(float(item["net_payable"]) for item in salary_slips)
    advance_balance = 0.0
    for item in entries:
        advance_balance += item["advance_taken"]
        advance_balance -= item["deducted"]
        item["advance_balance"] = max(advance_balance, 0.0)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    _draw_header(pdf, assets_dir)
    _draw_title(pdf, "Driver KATA Statement", "Advance taken, deducted amount and remaining balance")
    _draw_kata_driver_summary(pdf, driver)
    _draw_kata_stat_row(
        pdf,
        [
            ("Salary", format_currency(total_salary)),
            ("Advance", format_currency(total_advance)),
            ("Deducted", format_currency(total_deducted)),
            ("Left", format_currency(max(total_advance - total_deducted, 0.0))),
            ("Net Paid", format_currency(total_net_paid)),
        ],
    )
    _draw_kata_statement_table(pdf, entries)
    _draw_footer_banner(pdf, assets_dir)

    pdf.showPage()
    pdf.save()
    return str(output_path)


def generate_owner_fund_pdf(statement_rows, totals, output_dir: str, assets_dir: str, filters=None) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(output_dir) / f"owner-fund-kata_{timestamp}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    filters = filters or {}

    table_left = 16 * mm
    table_width = 178 * mm
    table_top = PAGE_HEIGHT - 122 * mm
    row_height = 6.1 * mm
    bottom_limit = 42 * mm
    rows_per_page = max(1, int((table_top - bottom_limit - (8 * mm)) // row_height))

    def _active_filter_text():
        parts = []
        if filters.get("month"):
            parts.append(f"Month {format_month_label(filters['month'])}")
        if filters.get("movement") and filters["movement"] != "All":
            parts.append(filters["movement"])
        if filters.get("search"):
            parts.append(f"Search {filters['search']}")
        return " | ".join(parts)

    filter_text = _active_filter_text()
    table_rows = list(statement_rows) if statement_rows else [
        {
            "entry_date": "-",
            "movement": "-",
            "reference": "No matching rows",
            "party": "-",
            "details": "No owner fund movement matched the current filter.",
            "incoming": 0.0,
            "outgoing": 0.0,
            "balance": float(totals.get("closing_balance", totals.get("balance", 0.0))),
        }
    ]
    pages = [table_rows[index : index + rows_per_page] for index in range(0, len(table_rows), rows_per_page)] or [table_rows]
    total_pages = len(pages)

    def _draw_filter_bar():
        if not filter_text:
            return
        bar_x = 16 * mm
        bar_y = PAGE_HEIGHT - 78 * mm
        bar_w = 178 * mm
        bar_h = 8.6 * mm
        pdf.setFillColor(BLUE_SOFT)
        pdf.roundRect(bar_x, bar_y, bar_w, bar_h, 3 * mm, fill=1, stroke=0)
        pdf.setStrokeColor(LINE)
        pdf.roundRect(bar_x, bar_y, bar_w, bar_h, 3 * mm, fill=0, stroke=1)
        pdf.setFillColor(BLUE_DARK)
        text, size = _fit_text(pdf, f"Filtered View: {filter_text}", "Helvetica-Bold", 7.4, bar_w - 8 * mm, min_size=6.2)
        pdf.setFont("Helvetica-Bold", size)
        pdf.drawString(bar_x + 4 * mm, bar_y + 2.7 * mm, text)

    def _draw_summary(page_number: int):
        stat_y = PAGE_HEIGHT - 104 * mm
        _draw_stat_box(pdf, 16 * mm, stat_y, 41 * mm, 14 * mm, "VIEW IN", f"AED {format_currency(float(totals['incoming']))}")
        _draw_stat_box(pdf, 61 * mm, stat_y, 41 * mm, 14 * mm, "VIEW OUT", f"AED {format_currency(float(totals['outgoing']))}", fill_color=SOFT)
        _draw_stat_box(pdf, 106 * mm, stat_y, 41 * mm, 14 * mm, "VIEW NET", f"AED {format_currency(float(totals['balance']))}", fill_color=SOFT)
        _draw_stat_box(
            pdf,
            151 * mm,
            stat_y,
            43 * mm,
            14 * mm,
            "CLOSING",
            f"AED {format_currency(float(totals.get('closing_balance', totals['balance'])))}",
            fill_color=colors.HexColor("#FFF4E8"),
            text_color=ORANGE,
            border_color=ORANGE,
        )

        overall_incoming = totals.get("overall_incoming")
        overall_outgoing = totals.get("overall_outgoing")
        overall_balance = totals.get("overall_balance")
        if overall_incoming is not None and overall_outgoing is not None and overall_balance is not None:
            note = (
                f"Overall In AED {format_currency(float(overall_incoming))}   "
                f"Out AED {format_currency(float(overall_outgoing))}   "
                f"Balance AED {format_currency(float(overall_balance))}"
            )
        else:
            note = "Running balance follows the filtered owner fund view."
        note_text, note_size = _fit_text(pdf, note, "Helvetica", 7.0, 150 * mm, min_size=6.0)
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", note_size)
        pdf.drawString(16 * mm, PAGE_HEIGHT - 113 * mm, note_text)
        pdf.drawRightString(194 * mm, PAGE_HEIGHT - 113 * mm, f"Page {page_number} / {total_pages}")

    def _draw_table(page_rows, page_number: int):
        _draw_header(pdf, assets_dir)
        _draw_title(pdf, "Owner Fund Kata", "Incoming owner funds, outgoing usage and running balance")
        _draw_filter_bar()
        _draw_summary(page_number)
        _draw_table_header(
            pdf,
            table_top,
            ["Date", "Type", "Reference", "Details", "In", "Out", "Balance"],
            [18, 36, 53, 91, 146, 165, 182],
        )

        y = table_top - 6.4 * mm
        for index, row in enumerate(page_rows):
            if index % 2 == 0:
                pdf.setFillColor(SOFT)
                pdf.roundRect(table_left, y - 2.2 * mm, table_width, 5.7 * mm, 1.8 * mm, fill=1, stroke=0)

            pdf.setFillColor(TEXT)
            pdf.setFont("Helvetica", 7.2)
            pdf.drawString(18 * mm, y, format_date_label(row["entry_date"]))

            movement_text, movement_size = _fit_text(pdf, row.get("movement") or "-", "Helvetica-Bold", 7.1, 15 * mm, min_size=6.2)
            pdf.setFont("Helvetica-Bold", movement_size)
            pdf.drawString(36 * mm, y, movement_text)

            ref_text, ref_size = _fit_text(pdf, str(row["reference"]), "Helvetica-Bold", 7.0, 34 * mm, min_size=6.0)
            pdf.setFont("Helvetica-Bold", ref_size)
            pdf.drawString(53 * mm, y, ref_text)

            details_value = str(row["details"] or "-")
            if row.get("party") and row["party"] != "-":
                details_value = f"{row['party']} | {details_value}"
            detail_text, detail_size = _fit_text(pdf, details_value, "Helvetica", 6.8, 52 * mm, min_size=5.8)
            pdf.setFont("Helvetica", detail_size)
            pdf.drawString(91 * mm, y, detail_text)

            pdf.setFont("Helvetica-Bold", 7.2)
            pdf.drawRightString(160 * mm, y, format_currency(float(row["incoming"])))
            pdf.drawRightString(177 * mm, y, format_currency(float(row["outgoing"])))
            pdf.drawRightString(194 * mm, y, format_currency(float(row["balance"])))
            y -= row_height

        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 7.0)
        footer_text = "Amounts are shown in AED. Large statements continue automatically to the next page."
        footer_line, footer_size = _fit_text(pdf, footer_text, "Helvetica", 7.0, 120 * mm, min_size=6.0)
        pdf.setFont("Helvetica", footer_size)
        pdf.drawString(16 * mm, 33 * mm, footer_line)
        _draw_footer_banner(pdf, assets_dir)
        pdf.showPage()

    for page_number, page_rows in enumerate(pages, start=1):
        _draw_table(page_rows, page_number)

    pdf.save()
    return str(output_path)


def generate_timesheet_pdf(driver, month_value: str, calendar_days, summary, output_dir: str, assets_dir: str, generated_dir: str) -> str:
    output_path = Path(output_dir) / f"{driver['driver_id']}_{month_value}_timesheet.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    _draw_header(pdf, assets_dir)
    _draw_title(pdf, f"Driver Timesheet {format_month_label(month_value)}", "Daily attendance, working hours and missing-day review")

    top_x = 16 * mm
    top_y = 181 * mm
    top_w = 118 * mm
    top_h = 43 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(top_x, top_y, top_w, top_h, 5 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(top_x, top_y, top_w, top_h, 5 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_SOFT)
    pdf.roundRect(top_x, top_y + top_h - 10 * mm, top_w, 10 * mm, 5 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(top_x + 5 * mm, top_y + top_h - 6.1 * mm, "DRIVER DETAILS")

    summary_rows = [
        ("Driver Name", driver["full_name"]),
        ("Driver ID", driver["driver_id"]),
        ("Vehicle No", driver["vehicle_no"]),
        ("Shift", driver["shift"]),
        ("Phone", driver["phone_number"] if "phone_number" in driver.keys() else "-"),
        ("Month", format_month_label(month_value)),
    ]
    row_y = top_y + top_h - 15.5 * mm
    for index, (label, value) in enumerate(summary_rows):
        column_x = top_x + (5 * mm if index % 2 == 0 else 63 * mm)
        if index and index % 2 == 0:
            row_y -= 7.2 * mm
        _draw_label_value_row(pdf, column_x, row_y, 23 * mm, 28 * mm, label, value)

    metric_labels = [
        ("Entered Days", str(summary["entered_days"])),
        ("Missing Days", str(summary["missing_days"])),
        ("Total Hours", format_currency(summary["total_hours"])),
    ]
    for index, (label, value) in enumerate(metric_labels):
        _draw_stat_box(pdf, (138 + index * 0) * mm, (208 - index * 13.5) * mm, 56 * mm, 11 * mm, label, value)

    _draw_timesheet_table(pdf, calendar_days)
    _draw_timesheet_footer(pdf, driver, summary, assets_dir, generated_dir)
    pdf.showPage()
    pdf.save()
    return str(output_path)


def generate_supplier_payment_voucher_pdf(party, voucher, payment, output_dir: str, assets_dir: str) -> str:
    output_path = Path(output_dir) / f"{payment['payment_no']}_payment-voucher.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    _draw_header(pdf, assets_dir)
    _draw_title(pdf, "Supplier Payment Voucher", "Month-end payable settlement summary")

    card_x = 16 * mm
    card_y = PAGE_HEIGHT - 118 * mm
    card_w = 178 * mm
    card_h = 34 * mm

    pdf.setFillColor(colors.white)
    pdf.roundRect(card_x, card_y, card_w, card_h, 5 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(card_x, card_y, card_w, card_h, 5 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_SOFT)
    pdf.roundRect(card_x, card_y + card_h - 10 * mm, card_w, 10 * mm, 5 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(card_x + 5 * mm, card_y + card_h - 6.1 * mm, "SUPPLIER DETAILS")

    _draw_label_value_row(pdf, card_x + 5 * mm, card_y + 18 * mm, 22 * mm, 55 * mm, "Supplier", party["party_name"])
    _draw_label_value_row(pdf, card_x + 92 * mm, card_y + 18 * mm, 20 * mm, 45 * mm, "Code", party["party_code"])
    _draw_label_value_row(pdf, card_x + 5 * mm, card_y + 10 * mm, 22 * mm, 55 * mm, "Contact", party.get("contact_person") or "-")
    _draw_label_value_row(pdf, card_x + 92 * mm, card_y + 10 * mm, 20 * mm, 45 * mm, "Phone", party.get("phone_number") or "-")

    summary_top = PAGE_HEIGHT - 160 * mm
    _draw_stat_box(pdf, 16 * mm, summary_top, 42 * mm, 15 * mm, "Payment", f"AED {format_currency(float(payment['amount']))}", fill_color=BLUE_SOFT, text_color=BLUE_DARK, border_color=BLUE)
    _draw_stat_box(pdf, 61 * mm, summary_top, 42 * mm, 15 * mm, "Voucher Total", f"AED {format_currency(float(voucher['total_amount']))}", fill_color=SOFT, text_color=TEXT, border_color=LINE)
    _draw_stat_box(pdf, 106 * mm, summary_top, 42 * mm, 15 * mm, "Paid To Date", f"AED {format_currency(float(voucher['paid_amount']))}", fill_color=SOFT, text_color=TEXT, border_color=LINE)
    _draw_stat_box(pdf, 151 * mm, summary_top, 42 * mm, 15 * mm, "Outstanding", f"AED {format_currency(float(voucher['balance_amount']))}", fill_color=colors.HexColor("#FFF4E8"), text_color=ORANGE, border_color=ORANGE)

    table_x = 16 * mm
    table_top = PAGE_HEIGHT - 188 * mm
    table_w = 178 * mm
    row_h = 10 * mm

    pdf.setFillColor(BLUE_DARK)
    pdf.roundRect(table_x, table_top, table_w, row_h, 3 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 8.5)
    headers = [("Payment No", 6), ("Voucher No", 44), ("Date", 82), ("Method", 110), ("Reference", 138)]
    for label, offset in headers:
        pdf.drawString((table_x + offset * mm), table_top + 3.8 * mm, label)

    data_y = table_top - 10 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(table_x, data_y, table_w, 24 * mm, 3 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(table_x, data_y, table_w, 24 * mm, 3 * mm, fill=0, stroke=1)
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(table_x + 6 * mm, data_y + 16 * mm, payment["payment_no"])
    pdf.drawString(table_x + 44 * mm, data_y + 16 * mm, voucher["voucher_no"])
    pdf.drawString(table_x + 82 * mm, data_y + 16 * mm, format_date_label(payment["entry_date"]))
    pdf.drawString(table_x + 110 * mm, data_y + 16 * mm, payment.get("payment_method") or "-")
    pdf.drawString(table_x + 138 * mm, data_y + 16 * mm, (payment.get("reference") or "-")[:22])

    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(MUTED)
    pdf.drawString(table_x + 6 * mm, data_y + 8 * mm, f"Period: {format_month_label(voucher['period_month'])}")
    pdf.drawString(table_x + 56 * mm, data_y + 8 * mm, f"Voucher Date: {format_date_label(voucher['issue_date'])}")
    pdf.drawString(table_x + 114 * mm, data_y + 8 * mm, f"Status: {voucher['status']}")

    notes_y = PAGE_HEIGHT - 228 * mm
    pdf.setFillColor(SOFT)
    pdf.roundRect(16 * mm, notes_y, 178 * mm, 26 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(16 * mm, notes_y, 178 * mm, 26 * mm, 4 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(21 * mm, notes_y + 19 * mm, "Voucher Notes")
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(21 * mm, notes_y + 11 * mm, (voucher.get("notes") or payment.get("notes") or "No notes entered.")[:110])

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.6)
    pdf.drawString(16 * mm, 36 * mm, f"Generated on {datetime.now().strftime('%d-%b-%Y %I:%M %p')}")
    _draw_footer_banner(pdf, assets_dir)
    pdf.showPage()
    pdf.save()
    return str(output_path)


def generate_plain_supplier_statement_pdf(party, statement_rows, summary, output_dir: str, title: str = "Supplier Statement") -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_code = str(party["party_code"]).replace("/", "-")
    output_path = Path(output_dir) / f"{safe_code}_statement_{timestamp}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    rows = list(statement_rows or [])
    if not rows:
        rows = [{"invoice_date": "-", "external_invoice_no": "No invoice", "submission_no": "-", "total_amount": 0.0, "paid_amount_display": 0.0, "balance_amount_display": 0.0, "display_status": "No Data"}]

    table_top = PAGE_HEIGHT - 92 * mm
    row_height = 7.2 * mm
    bottom_limit = 26 * mm
    rows_per_page = max(1, int((table_top - bottom_limit) // row_height) - 1)
    pages = [rows[index:index + rows_per_page] for index in range(0, len(rows), rows_per_page)] or [rows]

    for page_number, page_rows in enumerate(pages, start=1):
        pdf.setFillColor(colors.white)
        pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
        _draw_title(pdf, title, f"{party['party_name']} | {party['party_code']}")
        stats_y = PAGE_HEIGHT - 68 * mm
        _draw_stat_box(pdf, 16 * mm, stats_y, 42 * mm, 14 * mm, "All Submitted", f"AED {format_currency(float(summary.get('all_submitted', 0.0)))}")
        _draw_stat_box(pdf, 61 * mm, stats_y, 42 * mm, 14 * mm, "Approved", f"AED {format_currency(float(summary.get('approved_total', 0.0)))}", fill_color=SOFT)
        _draw_stat_box(pdf, 106 * mm, stats_y, 42 * mm, 14 * mm, "Paid", f"AED {format_currency(float(summary.get('total_paid', 0.0)))}", fill_color=SOFT)
        _draw_stat_box(pdf, 151 * mm, stats_y, 43 * mm, 14 * mm, "Pending", f"AED {format_currency(float(summary.get('pending_submitted', 0.0)))}", fill_color=colors.HexColor("#FFF4E8"), text_color=ORANGE, border_color=ORANGE)
        _draw_stat_box(pdf, 16 * mm, PAGE_HEIGHT - 86 * mm, 178 * mm, 12 * mm, "Outstanding", f"AED {format_currency(float(summary.get('approved_outstanding', 0.0)))}", fill_color=colors.HexColor("#EEF6FF"), text_color=BLUE_DARK, border_color=BLUE)

        header_top = table_top - 28 * mm
        _draw_table_header(pdf, header_top, ["Date", "Invoice", "Total", "Paid", "Balance", "Status"], [18, 46, 118, 144, 168, 184])
        y = header_top - 6.2 * mm
        for index, row in enumerate(page_rows):
            if index % 2 == 0:
                pdf.setFillColor(SOFT)
                pdf.roundRect(16 * mm, y - 2.2 * mm, 178 * mm, 6.2 * mm, 1.6 * mm, fill=1, stroke=0)
            pdf.setFillColor(TEXT)
            pdf.setFont("Helvetica", 7.2)
            pdf.drawString(18 * mm, y, format_date_label(row.get("invoice_date")))
            invoice_text, invoice_size = _fit_text(pdf, str(row.get("external_invoice_no") or "-"), "Helvetica-Bold", 7.2, 28 * mm, min_size=6.0)
            pdf.setFont("Helvetica-Bold", invoice_size)
            pdf.drawString(46 * mm, y, invoice_text)
            pdf.setFont("Helvetica", 7.2)
            pdf.drawRightString(138 * mm, y, format_currency(float(row.get("total_amount") or 0.0)))
            pdf.drawRightString(160 * mm, y, format_currency(float(row.get("paid_amount_display") or 0.0)))
            pdf.drawRightString(182 * mm, y, format_currency(float(row.get("balance_amount_display") or 0.0)))
            status_text, status_size = _fit_text(pdf, str(row.get("display_status") or "-"), "Helvetica-Bold", 7.0, 10 * mm, min_size=6.0)
            pdf.setFont("Helvetica-Bold", status_size)
            pdf.drawRightString(194 * mm, y, status_text)
            y -= row_height

        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 7.0)
        pdf.drawString(16 * mm, 14 * mm, f"Generated on {datetime.now().strftime('%d-%b-%Y %I:%M %p')}")
        pdf.drawRightString(194 * mm, 14 * mm, f"Page {page_number} / {len(pages)}")
        pdf.showPage()

    pdf.save()
    return str(output_path)


def generate_partnership_supplier_statement_pdf(party, period_month: str, asset_rows, summary, output_dir: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_code = str(party["party_code"]).replace("/", "-")
    output_path = Path(output_dir) / f"{safe_code}_partnership_{period_month}_{timestamp}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    rows = list(asset_rows or [])
    if not rows:
        rows = [{"asset_name": "No vehicle", "vehicle_no": "-", "double_shift_mode": "-", "work_total": 0.0, "total_salary_cost": 0.0, "total_maintenance_cost": 0.0, "net_profit": 0.0, "company_should_receive": 0.0, "partner_should_receive": 0.0}]

    table_top = PAGE_HEIGHT - 96 * mm
    row_height = 8.0 * mm
    bottom_limit = 26 * mm
    rows_per_page = max(1, int((table_top - bottom_limit) // row_height) - 1)
    pages = [rows[index:index + rows_per_page] for index in range(0, len(rows), rows_per_page)] or [rows]

    for page_number, page_rows in enumerate(pages, start=1):
        pdf.setFillColor(colors.white)
        pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
        _draw_title(pdf, "Partnership Profit Statement", f"{party['party_name']} | {format_month_label(period_month)}")
        _draw_stat_box(pdf, 16 * mm, PAGE_HEIGHT - 58 * mm, 42 * mm, 14 * mm, "Work", f"AED {format_currency(float(summary.get('work_total', 0.0)))}")
        _draw_stat_box(pdf, 61 * mm, PAGE_HEIGHT - 58 * mm, 42 * mm, 14 * mm, "Salary", f"AED {format_currency(float(summary.get('total_salary_cost', 0.0)))}", fill_color=SOFT)
        _draw_stat_box(pdf, 106 * mm, PAGE_HEIGHT - 58 * mm, 42 * mm, 14 * mm, "Maintenance", f"AED {format_currency(float(summary.get('total_maintenance_cost', 0.0)))}", fill_color=SOFT)
        _draw_stat_box(pdf, 151 * mm, PAGE_HEIGHT - 58 * mm, 43 * mm, 14 * mm, "Net Profit", f"AED {format_currency(float(summary.get('net_profit', 0.0)))}", fill_color=colors.HexColor("#FFF4E8"), text_color=ORANGE, border_color=ORANGE)

        _draw_table_header(pdf, table_top, ["Vehicle", "Mode", "Work", "Salary", "Maint.", "Net", "Company", "Partner"], [18, 58, 78, 102, 126, 148, 172, 192])
        y = table_top - 6.2 * mm
        for index, row in enumerate(page_rows):
            if index % 2 == 0:
                pdf.setFillColor(SOFT)
                pdf.roundRect(16 * mm, y - 2.4 * mm, 178 * mm, 6.8 * mm, 1.6 * mm, fill=1, stroke=0)
            pdf.setFillColor(TEXT)
            vehicle_text, vehicle_size = _fit_text(pdf, f"{row.get('asset_name') or '-'} / {row.get('vehicle_no') or '-'}", "Helvetica-Bold", 6.9, 36 * mm, min_size=5.8)
            pdf.setFont("Helvetica-Bold", vehicle_size)
            pdf.drawString(18 * mm, y, vehicle_text)
            pdf.setFont("Helvetica", 6.8)
            pdf.drawString(58 * mm, y, str(row.get("double_shift_mode") or "-"))
            pdf.drawRightString(100 * mm, y, format_currency(float(row.get("work_total") or 0.0)))
            pdf.drawRightString(124 * mm, y, format_currency(float(row.get("total_salary_cost") or 0.0)))
            pdf.drawRightString(146 * mm, y, format_currency(float(row.get("total_maintenance_cost") or 0.0)))
            pdf.drawRightString(168 * mm, y, format_currency(float(row.get("net_profit") or 0.0)))
            pdf.drawRightString(188 * mm, y, format_currency(float(row.get("company_should_receive") or 0.0)))
            pdf.drawRightString(194 * mm, y, format_currency(float(row.get("partner_should_receive") or 0.0)))
            y -= row_height

        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 7.0)
        pdf.drawString(16 * mm, 14 * mm, f"Generated on {datetime.now().strftime('%d-%b-%Y %I:%M %p')}")
        pdf.drawRightString(194 * mm, 14 * mm, f"Page {page_number} / {len(pages)}")
        pdf.showPage()

    pdf.save()
    return str(output_path)


def generate_cash_supplier_kata_pdf(
    party,
    rows,
    summary,
    output_dir: str,
    assets_dir: str,
    title: str = "Cash Supplier Kata",
    filter_caption: str = "",
) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_code = str(party["party_code"]).replace("/", "-")
    output_path = Path(output_dir) / f"{safe_code}_kata_{timestamp}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    party_keys = set(party.keys()) if hasattr(party, "keys") else set()

    def _party_value(key: str, default: str = "-"):
        if hasattr(party, "get"):
            return party.get(key, default)
        if key in party_keys:
            return party[key]
        return default

    table_rows = list(rows or [])
    if not table_rows:
        table_rows = [
            {
                "entry_date": "-",
                "period_month_display": "-",
                "reference": "No entry",
                "entry_type": "-",
                "earning_basis": "",
                "description": "No cash supplier entries available.",
                "earned": 0.0,
                "debit": 0.0,
                "paid": 0.0,
                "running_balance": 0.0,
            }
        ]

    def _draw_page_frame(pdf_obj: canvas.Canvas, page_number: int, page_count: int) -> tuple[float, float]:
        pdf_obj.setFillColor(colors.white)
        pdf_obj.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
        _draw_header(pdf_obj, assets_dir)

        title_text, title_size = _fit_text(pdf_obj, title, "Helvetica-Bold", 15.5, 120 * mm, min_size=11.5)
        pdf_obj.setFillColor(BLUE_DARK)
        pdf_obj.setFont("Helvetica-Bold", title_size)
        pdf_obj.drawString(16 * mm, PAGE_HEIGHT - 58 * mm, title_text)

        supplier_name, supplier_size = _fit_text(
            pdf_obj,
            str(_party_value("party_name") or "-"),
            "Helvetica-Bold",
            11.0,
            126 * mm,
            min_size=8.4,
        )
        pdf_obj.setFillColor(TEXT)
        pdf_obj.setFont("Helvetica-Bold", supplier_size)
        pdf_obj.drawString(16 * mm, PAGE_HEIGHT - 65.5 * mm, supplier_name)

        meta_parts = [str(_party_value("party_code") or "-")]
        if _party_value("phone_number", ""):
            meta_parts.append(str(_party_value("phone_number", "")))
        if _party_value("contact_person", ""):
            meta_parts.append(str(_party_value("contact_person", "")))
        meta_line = " | ".join(part for part in meta_parts if part)
        meta_text, meta_size = _fit_text(pdf_obj, meta_line, "Helvetica", 7.6, 126 * mm, min_size=6.4)
        pdf_obj.setFillColor(MUTED)
        pdf_obj.setFont("Helvetica", meta_size)
        pdf_obj.drawString(16 * mm, PAGE_HEIGHT - 71 * mm, meta_text)

        if filter_caption:
            filter_text, filter_size = _fit_text(
                pdf_obj,
                f"Filtered View: {filter_caption}",
                "Helvetica",
                7.2,
                126 * mm,
                min_size=6.0,
            )
            pdf_obj.setFont("Helvetica", filter_size)
            pdf_obj.drawString(16 * mm, PAGE_HEIGHT - 76 * mm, filter_text)

        stats_y = PAGE_HEIGHT - 86 * mm
        box_gap = 3 * mm
        box_width = (178 * mm - (box_gap * 3)) / 4
        stat_boxes = [
            ("Earned", f"AED {format_currency(float(summary.get('total_earned', 0.0)))}", colors.white, TEXT, LINE),
            ("Debits", f"AED {format_currency(float(summary.get('total_debits', 0.0)))}", SOFT, TEXT, LINE),
            ("Paid", f"AED {format_currency(float(summary.get('total_paid', 0.0)))}", colors.HexColor("#EDF5FF"), BLUE_DARK, colors.HexColor("#C8DBF4")),
            ("Balance", f"AED {format_currency(float(summary.get('balance', 0.0)))}", colors.HexColor("#EEF6FF"), BLUE_DARK, BLUE),
        ]
        for index, (label, value, fill, text_color, border) in enumerate(stat_boxes):
            _draw_stat_box(
                pdf_obj,
                16 * mm + index * (box_width + box_gap),
                stats_y,
                box_width,
                14 * mm,
                label,
                value,
                fill_color=fill,
                text_color=text_color,
                border_color=border,
            )

        table_header_top = PAGE_HEIGHT - 106 * mm
        _draw_table_header(
            pdf_obj,
            table_header_top,
            ["Date", "Month", "Ref", "Type", "Description", "Earned", "Debit", "Paid", "Balance"],
            [18, 35, 54, 72, 94, 148, 164, 178, 189],
        )
        return table_header_top - 4.6 * mm, 24 * mm

    row_height = 10.0 * mm
    working_rows = []
    pages = []
    current_y = PAGE_HEIGHT - 110.6 * mm
    bottom_limit = 24 * mm
    for row in table_rows:
        if current_y - row_height < bottom_limit:
            pages.append(working_rows)
            working_rows = []
            current_y = PAGE_HEIGHT - 110.6 * mm
        working_rows.append(row)
        current_y -= row_height
    if working_rows or not pages:
        pages.append(working_rows)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    for page_number, page_rows in enumerate(pages, start=1):
        start_y, bottom_limit = _draw_page_frame(pdf, page_number, len(pages))
        current_y = start_y
        for index, row in enumerate(page_rows):
            card_y = current_y - 5.0 * mm
            if index % 2 == 0:
                pdf.setFillColor(SOFT)
                pdf.roundRect(16 * mm, card_y, 178 * mm, 8.5 * mm, 1.8 * mm, fill=1, stroke=0)

            type_text = str(row.get("entry_type") or "-")
            if row.get("earning_basis"):
                type_text = f"{type_text} / {row.get('earning_basis')}"
            type_lines = _wrap_text_lines(pdf, type_text, "Helvetica", 6.0, 19 * mm, max_lines=2, min_size=5.4)
            desc_lines = _wrap_text_lines(pdf, str(row.get("description") or "-"), "Helvetica", 6.1, 50 * mm, max_lines=2, min_size=5.4)

            top_line_y = current_y + 1.4 * mm
            second_line_y = current_y - 2.4 * mm

            pdf.setFillColor(TEXT)
            pdf.setFont("Helvetica", 6.3)
            pdf.drawString(18 * mm, top_line_y, format_date_label(row.get("entry_date")))
            month_text, month_size = _fit_text(pdf, str(row.get("period_month_display") or "-"), "Helvetica", 6.1, 15 * mm, min_size=5.4)
            pdf.setFont("Helvetica", month_size)
            pdf.drawString(35 * mm, top_line_y, month_text)
            ref_text, ref_size = _fit_text(pdf, str(row.get("reference") or "-"), "Helvetica-Bold", 6.3, 16 * mm, min_size=5.5)
            pdf.setFont("Helvetica-Bold", ref_size)
            pdf.drawString(54 * mm, top_line_y, ref_text)

            pdf.setFillColor(TEXT)
            pdf.setFont("Helvetica", 5.9)
            for line_index, line in enumerate(type_lines[:2]):
                pdf.drawString(72 * mm, top_line_y - line_index * 3.8 * mm, line)
            for line_index, line in enumerate(desc_lines[:2]):
                pdf.drawString(94 * mm, top_line_y - line_index * 3.8 * mm, line)

            pdf.setFont("Helvetica-Bold", 6.2)
            pdf.drawRightString(162 * mm, second_line_y, format_currency(float(row.get("earned") or 0.0)))
            pdf.drawRightString(176 * mm, second_line_y, format_currency(float(row.get("debit") or 0.0)))
            pdf.drawRightString(188 * mm, second_line_y, format_currency(float(row.get("paid") or 0.0)))
            pdf.drawRightString(194 * mm, second_line_y, format_currency(float(row.get("running_balance") or 0.0)))
            current_y -= row_height

        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 7.0)
        pdf.drawString(16 * mm, 14 * mm, f"Generated on {datetime.now().strftime('%d-%b-%Y %I:%M %p')}")
        pdf.drawRightString(194 * mm, 14 * mm, f"Page {page_number} / {len(pages)}")
        _draw_footer_banner(pdf, assets_dir)
        pdf.showPage()

    pdf.save()
    return str(output_path)


def generate_tax_invoice_pdf(company_profile, party, invoice, line_items, output_dir: str, assets_dir: str) -> str:
    safe_invoice_no = str(invoice["invoice_no"]).replace("/", "-")
    output_path = Path(output_dir) / f"{safe_invoice_no}_tax-invoice.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    subtotal = float(invoice["subtotal"] or 0.0)
    tax_percent = float(invoice["tax_percent"] or 0.0)
    tax_amount = float(invoice["tax_amount"] or 0.0)
    total_amount = float(invoice["total_amount"] or 0.0)
    currency = company_profile.get("base_currency") or "AED"
    title = invoice.get("document_type") or ("Tax Invoice" if (invoice.get("invoice_kind") or "Sales") == "Sales" else "Supplier Bill")

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    _draw_header(pdf, assets_dir)
    _draw_title(pdf, title, "Commercial invoice with seller, bill-to, line items and VAT")

    seller_x = 16 * mm
    seller_y = PAGE_HEIGHT - 116 * mm
    seller_w = 86 * mm
    seller_h = 42 * mm
    buyer_x = 108 * mm
    buyer_y = seller_y
    buyer_w = 86 * mm
    buyer_h = seller_h

    seller_contact = " | ".join(item for item in [company_profile.get("phone_number"), company_profile.get("email")] if item) or "-"
    buyer_contact = " | ".join(item for item in [party.get("phone_number"), party.get("email")] if item) or "-"

    _draw_invoice_party_box(
        pdf,
        seller_x,
        seller_y,
        seller_w,
        seller_h,
        "SELLER",
        company_profile.get("company_name") or "Current Link",
        company_profile.get("legal_name") or company_profile.get("company_name") or "-",
        company_profile.get("address") or "-",
        company_profile.get("trn_no") or "-",
        seller_contact,
    )
    _draw_invoice_party_box(
        pdf,
        buyer_x,
        buyer_y,
        buyer_w,
        buyer_h,
        "BILL TO",
        party.get("party_name") or "-",
        party.get("contact_person") or party.get("party_kind") or "-",
        party.get("address") or "-",
        party.get("trn_no") or "-",
        buyer_contact,
    )

    table_top = PAGE_HEIGHT - 163 * mm
    _draw_table_header(
        pdf,
        table_top,
        ["#", "Description", "Unit", "Qty", "Rate", "Amount"],
        [18, 28, 124, 145, 162, 190],
    )

    y = table_top - 7 * mm
    row_height = 7.2 * mm
    pdf.setFont("Helvetica", 8)
    for index, line in enumerate(line_items[:8], start=1):
        if (index - 1) % 2 == 0:
            pdf.setFillColor(SOFT)
            pdf.roundRect(16 * mm, y - 2.4 * mm, 178 * mm, 6.1 * mm, 1.8 * mm, fill=1, stroke=0)
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(18 * mm, y, str(index))
        description, desc_size = _fit_text(pdf, line.get("description") or "-", "Helvetica-Bold", 7.8, 90 * mm, min_size=6.2)
        pdf.setFont("Helvetica-Bold", desc_size)
        pdf.drawString(28 * mm, y, description)
        pdf.setFont("Helvetica", 7.8)
        pdf.drawString(124 * mm, y, (line.get("unit_label") or "-")[:10])
        pdf.drawRightString(156 * mm, y, format_currency(float(line.get("quantity") or 0)))
        pdf.drawRightString(179 * mm, y, format_currency(float(line.get("rate") or 0)))
        pdf.drawRightString(193 * mm, y, format_currency(float(line.get("subtotal") or 0)))
        y -= row_height

    min_rows = 9
    filler_index = len(line_items)
    while filler_index < min_rows and y >= 67 * mm:
        if filler_index % 2 == 0:
            pdf.setFillColor(colors.white)
            pdf.roundRect(16 * mm, y - 2.4 * mm, 178 * mm, 6.1 * mm, 1.8 * mm, fill=1, stroke=0)
        pdf.setStrokeColor(LINE)
        pdf.line(16 * mm, y - 2.2 * mm, 194 * mm, y - 2.2 * mm)
        y -= row_height
        filler_index += 1

    summary_y = 43 * mm
    _draw_stat_box(pdf, 118 * mm, summary_y + 30 * mm, 76 * mm, 12 * mm, "SUBTOTAL", f"{currency} {format_currency(subtotal)}")
    _draw_stat_box(pdf, 118 * mm, summary_y + 15 * mm, 76 * mm, 12 * mm, "VAT", f"{tax_percent:.2f}% / {currency} {format_currency(tax_amount)}", fill_color=SOFT)
    _draw_stat_box(pdf, 118 * mm, summary_y, 76 * mm, 12 * mm, "TOTAL AMOUNT", f"{currency} {format_currency(total_amount)}", fill_color=BLUE, text_color=colors.white, border_color=BLUE)

    notes_y = 38 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(16 * mm, notes_y, 96 * mm, 24 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(16 * mm, notes_y, 96 * mm, 24 * mm, 4 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8.2)
    pdf.drawString(20 * mm, notes_y + 17 * mm, "NOTES")
    note_lines = _wrap_text_lines(
        pdf,
        invoice.get("notes") or company_profile.get("invoice_terms") or "No notes entered.",
        "Helvetica",
        7.1,
        86 * mm,
        max_lines=2,
        min_size=6.0,
    )
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica", 7.1)
    for index, note_line in enumerate(note_lines):
        pdf.drawString(20 * mm, notes_y + 11.5 * mm - (index * 4.2 * mm), note_line)

    _draw_small_meta_row(pdf, 20 * mm, notes_y + 3.4 * mm, "Terms", company_profile.get("invoice_terms") or "-", 50 * mm)
    _draw_small_meta_row(pdf, 118 * mm, notes_y - 4.8 * mm, "Generated", datetime.now().strftime("%d-%b-%Y %I:%M %p"), 54 * mm)

    _draw_footer_banner(pdf, assets_dir)
    pdf.showPage()
    pdf.save()
    return str(output_path)


def _draw_header(pdf: canvas.Canvas, assets_dir: str) -> None:
    premium_banner = Path(assets_dir) / "current-link-header-premium.png"
    banner = premium_banner if premium_banner.exists() else Path(assets_dir) / "current-link-header.png"
    if banner.exists():
        image = ImageReader(str(banner))
        image_width, image_height = image.getSize()
        target_width = 180 * mm
        target_height = target_width * (image_height / image_width)
        banner_x = 15 * mm
        banner_y = PAGE_HEIGHT - 44 * mm

        pdf.setFillColor(colors.white)
        pdf.roundRect(15 * mm, PAGE_HEIGHT - 45 * mm, 180 * mm, 39 * mm, 4 * mm, fill=1, stroke=0)
        pdf.drawImage(
            image,
            banner_x,
            banner_y,
            width=target_width,
            height=target_height,
            preserveAspectRatio=False,
            mask="auto",
        )
    pdf.setFillColor(BLUE)
    pdf.rect(15 * mm, PAGE_HEIGHT - 46 * mm, 180 * mm, 1.7 * mm, fill=1, stroke=0)


def _draw_title(pdf: canvas.Canvas, title: str, subtitle: str = "") -> None:
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 17)
    pdf.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 60 * mm, title)
    if subtitle:
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 8)
        pdf.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 65.5 * mm, subtitle)


def _draw_salary_summary(pdf: canvas.Canvas, driver, salary_row, slip_payload) -> None:
    ot_month = salary_row["ot_month"] if "ot_month" in salary_row.keys() and salary_row["ot_month"] else previous_month_value(salary_row["salary_month"])
    summary_x = 16 * mm
    summary_y = 181 * mm
    summary_w = 116 * mm
    summary_h = 47 * mm

    pdf.setFillColor(colors.white)
    pdf.roundRect(summary_x, summary_y, summary_w, summary_h, 5 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(summary_x, summary_y, summary_w, summary_h, 5 * mm, fill=0, stroke=1)

    pdf.setFillColor(BLUE_SOFT)
    pdf.roundRect(summary_x, summary_y + summary_h - 10 * mm, summary_w, 10 * mm, 5 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(summary_x + 5 * mm, summary_y + summary_h - 6.2 * mm, "DRIVER SUMMARY")

    left_rows = [
        ("Driver Name", driver["full_name"]),
        ("Driver ID", driver["driver_id"]),
        ("Vehicle Number", driver["vehicle_no"]),
        ("Join Date", format_date_label(driver["duty_start"])),
    ]
    right_rows = [
        ("Phone Number", driver["phone_number"] if "phone_number" in driver.keys() else "-"),
        ("Pay Period", format_month_label(salary_row["salary_month"])),
        ("OT Month", format_month_label(ot_month)),
        ("Shift", driver["shift"]),
        ("Basic Salary", f"AED {format_currency(float(salary_row['basic_salary']))}"),
    ]

    row_y = summary_y + summary_h - 15.5 * mm
    for label, value in left_rows:
        _draw_label_value_row(pdf, summary_x + 5 * mm, row_y, 24 * mm, 25 * mm, label, value)
        row_y -= 5.8 * mm

    row_y = summary_y + summary_h - 15.5 * mm
    for label, value in right_rows:
        _draw_label_value_row(pdf, summary_x + 63 * mm, row_y, 19 * mm, 28 * mm, label, value)
        row_y -= 5.8 * mm

    metric_x = 138 * mm
    metric_y = 205 * mm
    metric_w = 56 * mm
    metric_h = 23 * mm
    pdf.setFillColor(BLUE)
    pdf.roundRect(metric_x, metric_y, metric_w, metric_h, 5 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 8.2)
    pdf.drawCentredString(metric_x + metric_w / 2, metric_y + 16 * mm, "NET PAYABLE")
    pdf.setFont("Helvetica-Bold", 13.2)
    pdf.drawCentredString(metric_x + metric_w / 2, metric_y + 9.2 * mm, f"{format_currency(float(slip_payload['net_payable']))} AED")
    pdf.setFont("Helvetica", 7.2)
    pdf.drawCentredString(metric_x + metric_w / 2, metric_y + 3.2 * mm, format_month_label(salary_row["salary_month"]))

    info_y = 181 * mm
    info_h = 20 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(metric_x, info_y, metric_w, info_h, 5 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(metric_x, info_y, metric_w, info_h, 5 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(metric_x + 4 * mm, info_y + 14.3 * mm, "PAYMENT DETAILS")
    _draw_small_meta_row(pdf, metric_x + 4 * mm, info_y + 9.2 * mm, "Source", slip_payload["payment_source"], 33 * mm)
    _draw_small_meta_row(pdf, metric_x + 4 * mm, info_y + 5.1 * mm, "Paid By", slip_payload.get("paid_by") or "-", 33 * mm)
    _draw_small_meta_row(pdf, metric_x + 4 * mm, info_y + 1.1 * mm, "Advance Left", f"AED {format_currency(float(slip_payload['remaining_advance']))}", 29 * mm)


def _draw_salary_breakdown(pdf: canvas.Canvas, salary_row, slip_payload) -> None:
    ot_month = salary_row["ot_month"] if "ot_month" in salary_row.keys() and salary_row["ot_month"] else previous_month_value(salary_row["salary_month"])
    gross = float(salary_row["net_salary"])
    deduction_amount = float(slip_payload["deduction_amount"])
    available_advance = float(slip_payload["available_advance"])
    remaining_advance = float(slip_payload["remaining_advance"])
    net_payable = float(slip_payload["net_payable"])

    x = 16 * mm
    y = 103 * mm
    w = 179 * mm
    h = 66 * mm

    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(x, y + h + 6.5 * mm, "SALARY DETAILS")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.4)
    pdf.drawString(x + 38 * mm, y + h + 6.5 * mm, "Separate earnings and deductions layout for clean printing")

    pdf.setFillColor(colors.white)
    pdf.roundRect(x, y, w, h, 5 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(x, y, w, h, 5 * mm, fill=0, stroke=1)

    pdf.setFillColor(ORANGE)
    pdf.rect(x, y + h - 10 * mm, w, 10 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 8.9)
    pdf.drawString(x + 6 * mm, y + h - 6.2 * mm, "EARNINGS")
    pdf.drawString(x + 63 * mm, y + h - 6.2 * mm, "AMOUNT")
    pdf.drawString(x + 95 * mm, y + h - 6.2 * mm, "DEDUCTIONS")
    pdf.drawString(x + 152 * mm, y + h - 6.2 * mm, "AMOUNT")

    pdf.setStrokeColor(LINE)
    pdf.line(x + 89.5 * mm, y + 5 * mm, x + 89.5 * mm, y + h - 5 * mm)

    earnings = [
        ("Basic Salary", float(salary_row["basic_salary"])),
        (f"OT Hours ({format_month_label(ot_month)})", float(salary_row["ot_hours"])),
        ("OT Amount", float(salary_row["ot_amount"])),
        ("Personal / Vehicle", float(salary_row["personal_vehicle"])),
        ("Gross Earnings", gross),
    ]
    deductions = [
        ("Available Advance", available_advance),
        ("Deduct This Slip", deduction_amount),
        ("Advance Remaining", remaining_advance),
        ("Other Deductions", 0.0),
        ("Total Deductions", deduction_amount),
    ]

    row_y = y + h - 18.5 * mm
    for index in range(5):
        if index % 2 == 0:
            pdf.setFillColor(SOFT)
            pdf.roundRect(x + 3 * mm, row_y - 3.4 * mm, 82 * mm, 6.4 * mm, 1.8 * mm, fill=1, stroke=0)
            pdf.roundRect(x + 92 * mm, row_y - 3.4 * mm, 82 * mm, 6.4 * mm, 1.8 * mm, fill=1, stroke=0)
        left_label, left_value = earnings[index]
        right_label, right_value = deductions[index]
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 8.3)
        pdf.drawString(x + 6 * mm, row_y, left_label)
        pdf.drawString(x + 95 * mm, row_y, right_label)
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica-Bold", 8.7)
        pdf.drawRightString(x + 82 * mm, row_y, format_currency(left_value))
        pdf.drawRightString(x + 172 * mm, row_y, format_currency(right_value))
        row_y -= 8.1 * mm

    metrics_y = 84 * mm
    _draw_stat_box(pdf, 16 * mm, metrics_y, 56 * mm, 14 * mm, "GROSS EARNINGS", format_currency(gross))
    _draw_stat_box(pdf, 77.5 * mm, metrics_y, 56 * mm, 14 * mm, "TOTAL DEDUCTIONS", format_currency(deduction_amount))
    _draw_stat_box(pdf, 139 * mm, metrics_y, 56 * mm, 14 * mm, "FINAL NET PAY", f"{format_currency(net_payable)} AED", fill_color=BLUE, text_color=colors.white, border_color=BLUE)


def _draw_salary_footer(pdf: canvas.Canvas, driver, slip_payload, assets_dir: str, generated_dir: str) -> None:
    card_x = 16 * mm
    card_y = 38 * mm
    card_w = 44 * mm
    card_h = 33 * mm
    pdf.setFillColor(SOFT)
    pdf.roundRect(card_x, card_y, card_w, card_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(card_x, card_y, card_w, card_h, 4 * mm, fill=0, stroke=1)

    if not _draw_driver_photo(pdf, driver, generated_dir, card_x + 2.5 * mm, card_y + 2.5 * mm, card_w - 5 * mm, card_h - 5 * mm):
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawCentredString(card_x + card_w / 2, card_y + card_h / 2, "NO PHOTO")

    status_x = 66 * mm
    status_y = 38 * mm
    status_w = 60 * mm
    status_h = 33 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(status_x, status_y, status_w, status_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(status_x, status_y, status_w, status_h, 4 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8.4)
    pdf.drawString(status_x + 4 * mm, status_y + 25 * mm, "PAYMENT STATUS")
    pdf.setFillColor(GREEN)
    pdf.setFont("Helvetica-Bold", 13.5)
    pdf.drawString(status_x + 4 * mm, status_y + 17 * mm, "PAID")
    _draw_small_meta_row(pdf, status_x + 4 * mm, status_y + 11.2 * mm, "Source", slip_payload["payment_source"], 34 * mm)
    _draw_small_meta_row(pdf, status_x + 4 * mm, status_y + 6.7 * mm, "Paid By", slip_payload.get("paid_by") or "-", 34 * mm)
    _draw_small_meta_row(pdf, status_x + 4 * mm, status_y + 2.2 * mm, "Remaining", f"AED {format_currency(float(slip_payload['remaining_advance']))}", 30 * mm)

    sign_x = 132 * mm
    sign_y = 38 * mm
    sign_w = 63 * mm
    sign_h = 33 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(sign_x, sign_y, sign_w, sign_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(sign_x, sign_y, sign_w, sign_h, 4 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8.4)
    pdf.drawString(sign_x + 4 * mm, sign_y + 25 * mm, "DRIVER ACKNOWLEDGMENT")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.4)
    pdf.drawString(sign_x + 4 * mm, sign_y + 18.8 * mm, f"Driver ID: {driver['driver_id']}")
    pdf.drawString(sign_x + 4 * mm, sign_y + 14.2 * mm, "Signature")
    pdf.setStrokeColor(BLUE_DARK)
    pdf.line(sign_x + 22 * mm, sign_y + 14.6 * mm, sign_x + 54 * mm, sign_y + 14.6 * mm)
    _draw_paid_stamp(pdf, sign_x + 40 * mm, sign_y + 7.5 * mm)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.1)
    pdf.drawString(16 * mm, 33 * mm, "This is a system-generated salary slip for internal payroll records.")
    _draw_footer_banner(pdf, assets_dir)


def _draw_timesheet_table(pdf: canvas.Canvas, calendar_days) -> None:
    x = 16 * mm
    y = 86 * mm
    w = 179 * mm
    h = 88 * mm

    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(x, y + h + 6.5 * mm, "MONTHLY TIMESHEET")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.4)
    pdf.drawString(x + 38 * mm, y + h + 6.5 * mm, "Missing entries are highlighted for quick review")

    pdf.setFillColor(colors.white)
    pdf.roundRect(x, y, w, h, 5 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(x, y, w, h, 5 * mm, fill=0, stroke=1)

    half = 89.5 * mm
    _draw_timesheet_table_header(pdf, x, y + h - 10 * mm, half - 2 * mm)
    _draw_timesheet_table_header(pdf, x + half, y + h - 10 * mm, half - 2 * mm)

    left_rows = calendar_days[:16]
    right_rows = calendar_days[16:]
    row_height = 4.7 * mm
    start_y = y + h - 15 * mm
    _draw_timesheet_rows(pdf, x + 3 * mm, start_y, left_rows, row_height, 82 * mm)
    _draw_timesheet_rows(pdf, x + half + 3 * mm, start_y, right_rows, row_height, 82 * mm)
    pdf.setStrokeColor(LINE)
    pdf.line(x + half, y + 4 * mm, x + half, y + h - 4 * mm)


def _draw_timesheet_table_header(pdf: canvas.Canvas, x: float, y: float, width: float) -> None:
    pdf.setFillColor(ORANGE)
    pdf.roundRect(x, y, width, 8 * mm, 2 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 7.3)
    pdf.drawString(x + 3 * mm, y + 2.5 * mm, "DAY")
    pdf.drawString(x + 15 * mm, y + 2.5 * mm, "STATUS")
    pdf.drawString(x + 37 * mm, y + 2.5 * mm, "HOURS")
    pdf.drawString(x + 54 * mm, y + 2.5 * mm, "REMARKS")


def _draw_timesheet_rows(pdf: canvas.Canvas, x: float, y: float, rows, row_height: float, width: float) -> None:
    current_y = y
    for index, row in enumerate(rows):
        if index % 2 == 0:
            pdf.setFillColor(SOFT)
            pdf.roundRect(x - 1.2 * mm, current_y - 2.6 * mm, width, row_height, 1.4 * mm, fill=1, stroke=0)
        status_label = "Entered" if row["entered"] else "Missing"
        status_color = GREEN if row["entered"] else RED
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica-Bold", 7.2)
        pdf.drawString(x, current_y, f"{row['day']:02d}")
        pdf.setFillColor(status_color)
        pdf.setFont("Helvetica-Bold", 7.2)
        pdf.drawString(x + 12 * mm, current_y, status_label)
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica-Bold", 7.2)
        pdf.drawRightString(x + 34 * mm, current_y, format_currency(row["work_hours"]) if row["entered"] else "0.00")
        pdf.setFillColor(MUTED if row["entered"] else RED)
        text, size = _fit_text(pdf, row["remarks"] or ("No entry" if not row["entered"] else "-"), "Helvetica", 6.6, 29 * mm)
        pdf.setFont("Helvetica", size)
        pdf.drawString(x + 40 * mm, current_y, text)
        current_y -= row_height


def _draw_timesheet_footer(pdf: canvas.Canvas, driver, summary, assets_dir: str, generated_dir: str) -> None:
    photo_x = 16 * mm
    photo_y = 38 * mm
    photo_w = 36 * mm
    photo_h = 30 * mm
    pdf.setFillColor(SOFT)
    pdf.roundRect(photo_x, photo_y, photo_w, photo_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(photo_x, photo_y, photo_w, photo_h, 4 * mm, fill=0, stroke=1)
    if not _draw_driver_photo(pdf, driver, generated_dir, photo_x + 2 * mm, photo_y + 2 * mm, photo_w - 4 * mm, photo_h - 4 * mm):
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawCentredString(photo_x + photo_w / 2, photo_y + photo_h / 2, "NO PHOTO")

    note_x = 58 * mm
    note_y = 38 * mm
    note_w = 68 * mm
    note_h = 30 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(note_x, note_y, note_w, note_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(note_x, note_y, note_w, note_h, 4 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8.1)
    pdf.drawString(note_x + 4 * mm, note_y + 22 * mm, "TIMESHEET STATUS")
    _draw_small_meta_row(pdf, note_x + 4 * mm, note_y + 15.2 * mm, "Entered", str(summary["entered_days"]), 24 * mm)
    _draw_small_meta_row(pdf, note_x + 4 * mm, note_y + 10.4 * mm, "Missing", str(summary["missing_days"]), 24 * mm)
    _draw_small_meta_row(pdf, note_x + 4 * mm, note_y + 5.6 * mm, "Hours", format_currency(summary["total_hours"]), 24 * mm)

    sign_x = 132 * mm
    sign_y = 38 * mm
    sign_w = 63 * mm
    sign_h = 30 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(sign_x, sign_y, sign_w, sign_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(sign_x, sign_y, sign_w, sign_h, 4 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8.2)
    pdf.drawString(sign_x + 4 * mm, sign_y + 22 * mm, "SUPERVISOR REVIEW")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.2)
    pdf.drawString(sign_x + 4 * mm, sign_y + 15.5 * mm, "Check missing days before payroll close.")
    pdf.drawString(sign_x + 4 * mm, sign_y + 10.5 * mm, "Sign")
    pdf.setStrokeColor(BLUE_DARK)
    pdf.line(sign_x + 16 * mm, sign_y + 11 * mm, sign_x + 52 * mm, sign_y + 11 * mm)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7)
    pdf.drawString(16 * mm, 33 * mm, "This monthly timesheet is system-generated for operational review.")
    _draw_footer_banner(pdf, assets_dir)


def _draw_driver_photo(pdf: canvas.Canvas, driver, generated_dir: str, x: float, y: float, w: float, h: float) -> bool:
    photo_data = driver["photo_data"] if "photo_data" in driver.keys() and driver["photo_data"] else ""
    if photo_data:
        try:
            image = ImageReader(BytesIO(base64.b64decode(photo_data)))
            pdf.drawImage(image, x, y, width=w, height=h, preserveAspectRatio=True, mask="auto")
            return True
        except Exception:
            pass

    photo_name = driver["photo_name"] or ""
    if not photo_name:
        return False

    photo_path = Path(generated_dir) / photo_name
    if not photo_path.exists():
        return False

    pdf.drawImage(str(photo_path), x, y, width=w, height=h, preserveAspectRatio=True, mask="auto")
    return True


def _draw_table_header(pdf: canvas.Canvas, top: float, headers, x_positions) -> None:
    pdf.setFillColor(BLUE)
    pdf.roundRect(16 * mm, top, 178 * mm, 8 * mm, 2 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 8.2)
    for header, x in zip(headers, x_positions):
        pdf.drawString(x * mm, top + 2.5 * mm, header)


def _draw_kata_driver_summary(pdf: canvas.Canvas, driver) -> None:
    box_x = 16 * mm
    box_y = PAGE_HEIGHT - 112 * mm
    box_w = 178 * mm
    box_h = 19 * mm

    pdf.setFillColor(SOFT)
    pdf.roundRect(box_x, box_y, box_w, box_h, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(box_x + 6 * mm, box_y + 12.2 * mm, driver["full_name"])
    pdf.setFont("Helvetica", 8.8)
    pdf.drawString(box_x + 6 * mm, box_y + 6 * mm, f"Driver ID: {driver['driver_id']}")
    pdf.drawString(box_x + 48 * mm, box_y + 6 * mm, f"Vehicle: {driver['vehicle_no']}")
    pdf.drawString(box_x + 96 * mm, box_y + 6 * mm, f"Shift: {driver['shift']}")
    pdf.drawString(box_x + 132 * mm, box_y + 6 * mm, f"Phone: {driver['phone_number'] if 'phone_number' in driver.keys() else '-'}")


def _draw_kata_stat_row(pdf: canvas.Canvas, items) -> None:
    start_x = 16 * mm
    start_y = PAGE_HEIGHT - 137 * mm
    gap = 4 * mm
    box_w = (178 * mm - (gap * 4)) / 5
    box_h = 16 * mm

    for index, (label, value) in enumerate(items):
        x = start_x + index * (box_w + gap)
        fill = colors.white if index < 4 else BLUE
        text_color = TEXT if index < 4 else colors.white
        border = LINE if index < 4 else BLUE
        _draw_stat_box(pdf, x, start_y, box_w, box_h, label.upper(), value, fill_color=fill, text_color=text_color, border_color=border)


def _draw_kata_statement_table(pdf: canvas.Canvas, entries) -> None:
    top = PAGE_HEIGHT - 160 * mm
    _draw_table_header(
        pdf,
        top,
        ["Date", "Reference", "Salary", "Advance", "Deducted", "Net Paid", "Adv Left"],
        [18, 39, 84, 109, 133, 156, 180],
    )

    y = top - 7 * mm
    row_height = 6.5 * mm
    for index, item in enumerate(entries[:24]):
        if index % 2 == 0:
            pdf.setFillColor(SOFT)
            pdf.roundRect(16 * mm, y - 2.3 * mm, 178 * mm, 5.8 * mm, 1.8 * mm, fill=1, stroke=0)
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica", 8)
        pdf.drawString(18 * mm, y, format_date_label(item["date"]))

        reference, ref_size = _fit_text(
            pdf,
            f"{item['reference']} | {item['details']}",
            "Helvetica-Bold",
            7.7,
            40 * mm,
            min_size=6.1,
        )
        pdf.setFont("Helvetica-Bold", ref_size)
        pdf.drawString(39 * mm, y, reference)

        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawRightString(104 * mm, y, format_currency(item["salary_added"]))
        pdf.drawRightString(129 * mm, y, format_currency(item["advance_taken"]))
        pdf.drawRightString(154 * mm, y, format_currency(item["deducted"]))
        pdf.drawRightString(178 * mm, y, format_currency(item["net_paid"]))
        pdf.drawRightString(193 * mm, y, format_currency(item["advance_balance"]))
        y -= row_height
        if y < 44 * mm:
            break


def _draw_footer_banner(pdf: canvas.Canvas, assets_dir: str) -> None:
    footer = Path(assets_dir) / "current-link-footer.png"
    pdf.setFillColor(ORANGE)
    pdf.rect(15 * mm, 30 * mm, 180 * mm, 1.2 * mm, fill=1, stroke=0)
    if footer.exists():
        image = ImageReader(str(footer))
        image_width, image_height = image.getSize()
        target_width = 180 * mm
        target_height = target_width * (image_height / image_width)
        footer_x = 15 * mm
        footer_y = 9 * mm

        pdf.setFillColor(colors.white)
        pdf.roundRect(15 * mm, 8 * mm, 180 * mm, 21 * mm, 4 * mm, fill=1, stroke=0)
        pdf.drawImage(
            image,
            footer_x,
            footer_y,
            width=target_width,
            height=target_height,
            preserveAspectRatio=False,
            mask="auto",
        )


def _draw_label_value_row(pdf: canvas.Canvas, x: float, y: float, label_width: float, value_width: float, label: str, value: str) -> None:
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.8)
    pdf.drawString(x, y, label)
    pdf.setFillColor(TEXT)
    text, size = _fit_text(pdf, str(value or "-"), "Helvetica-Bold", 8.2, value_width)
    pdf.setFont("Helvetica-Bold", size)
    pdf.drawString(x + label_width, y, text)


def _draw_small_meta_row(pdf: canvas.Canvas, x: float, y: float, label: str, value: str, value_width: float) -> None:
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.9)
    label_text = f"{label}:"
    pdf.drawString(x, y, label_text)
    pdf.setFillColor(TEXT)
    text, size = _fit_text(pdf, str(value or "-"), "Helvetica-Bold", 7.1, value_width)
    pdf.setFont("Helvetica-Bold", size)
    label_width = pdf.stringWidth(label_text, "Helvetica", 6.9) + (2 * mm)
    pdf.drawRightString(x + label_width + value_width, y, text)


def _draw_invoice_party_box(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    heading: str,
    title: str,
    secondary: str,
    address: str,
    trn_no: str,
    contact: str,
) -> None:
    pdf.setFillColor(colors.white)
    pdf.roundRect(x, y, w, h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(x, y, w, h, 4 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_SOFT)
    pdf.roundRect(x, y + h - 8 * mm, w, 8 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(x + 4 * mm, y + h - 5.2 * mm, heading)

    safe_title, title_size = _fit_text(pdf, title or "-", "Helvetica-Bold", 9.6, w - 8 * mm, min_size=7.8)
    safe_secondary, secondary_size = _fit_text(pdf, secondary or "-", "Helvetica", 7.4, w - 8 * mm, min_size=6.5)
    address_lines = _wrap_text_lines(pdf, address or "-", "Helvetica", 7.0, w - 8 * mm, max_lines=2, min_size=6.0)
    contact_line, contact_size = _fit_text(pdf, contact or "-", "Helvetica", 6.7, w - 8 * mm, min_size=6.0)

    top_y = y + h - 12.8 * mm
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica-Bold", title_size)
    pdf.drawString(x + 4 * mm, top_y, safe_title)
    pdf.setFont("Helvetica", secondary_size)
    pdf.drawString(x + 4 * mm, top_y - 4.6 * mm, safe_secondary)

    pdf.setFont("Helvetica", 7.0)
    for index, line in enumerate(address_lines):
        pdf.drawString(x + 4 * mm, top_y - 9.2 * mm - (index * 3.8 * mm), line)

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.8)
    pdf.drawString(x + 4 * mm, y + 7.1 * mm, f"TRN: {trn_no or '-'}")
    pdf.drawString(x + 4 * mm, y + 3.1 * mm, contact_line)


def _wrap_text_lines(
    pdf: canvas.Canvas,
    text: str,
    font_name: str,
    font_size: float,
    max_width: float,
    *,
    max_lines: int = 2,
    min_size: float = 6.0,
):
    value = " ".join(str(text or "-").split()) or "-"
    if max_lines <= 1:
        return [_fit_text(pdf, value, font_name, font_size, max_width, min_size=min_size)[0]]

    words = value.split(" ")
    lines = []
    index = 0

    while index < len(words) and len(lines) < max_lines:
        if len(lines) == max_lines - 1:
            remainder = " ".join(words[index:]).strip()
            lines.append(_fit_text(pdf, remainder, font_name, font_size, max_width, min_size=min_size)[0])
            break

        current = words[index]
        index += 1
        while index < len(words):
            candidate = f"{current} {words[index]}".strip()
            if pdf.stringWidth(candidate, font_name, font_size) <= max_width:
                current = candidate
                index += 1
            else:
                break
        lines.append(_fit_text(pdf, current, font_name, font_size, max_width, min_size=min_size)[0])

    return lines[:max_lines] or ["-"]


def _draw_stat_box(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    value: str,
    *,
    fill_color=colors.white,
    text_color=TEXT,
    border_color=LINE,
) -> None:
    pdf.setFillColor(fill_color)
    pdf.roundRect(x, y, w, h, 3.5 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(border_color)
    pdf.roundRect(x, y, w, h, 3.5 * mm, fill=0, stroke=1)
    pdf.setFillColor(text_color)
    pdf.setFont("Helvetica-Bold", 7.1)
    pdf.drawString(x + 4 * mm, y + 9.2 * mm, label)
    text, size = _fit_text(pdf, value, "Helvetica-Bold", 9.6, w - 8 * mm)
    pdf.setFont("Helvetica-Bold", size)
    pdf.drawString(x + 4 * mm, y + 4.1 * mm, text)


def _draw_paid_stamp(pdf: canvas.Canvas, x: float, y: float) -> None:
    pdf.saveState()
    pdf.translate(x, y)
    pdf.rotate(-16)
    pdf.setStrokeColor(RED)
    pdf.setFillColor(colors.white)
    pdf.roundRect(-12 * mm, -4 * mm, 24 * mm, 8 * mm, 3 * mm, fill=1, stroke=1)
    pdf.setFillColor(RED)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawCentredString(0, -0.4 * mm, "PAID")
    pdf.restoreState()


def _fit_text(pdf: canvas.Canvas, text: str, font_name: str, font_size: float, max_width: float, min_size: float = 6.4):
    value = text or "-"
    size = font_size
    while size > min_size and pdf.stringWidth(value, font_name, size) > max_width:
        size -= 0.2
    if pdf.stringWidth(value, font_name, size) <= max_width:
        return value, size

    clipped = value
    while clipped and pdf.stringWidth(f"{clipped}...", font_name, size) > max_width:
        clipped = clipped[:-1]
    return (f"{clipped}..." if clipped else "..."), size


def format_currency(value: float) -> str:
    return f"{value:,.2f}"


def format_month_label(value: str) -> str:
    if not value or value == "-":
        return value
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%b %Y")
    except ValueError:
        return value


def previous_month_value(value: str) -> str:
    if not value or value == "-":
        return value
    try:
        month_date = datetime.strptime(f"{value}-01", "%Y-%m-%d")
    except ValueError:
        return value
    if month_date.month == 1:
        return f"{month_date.year - 1}-12"
    return f"{month_date.year}-{month_date.month - 1:02d}"


def format_date_label(value: str | None) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d-%b-%Y")
    if isinstance(value, date_cls):
        return value.strftime("%d-%b-%Y")
    for pattern in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(str(value), pattern).strftime("%d-%b-%Y")
        except ValueError:
            continue
    return str(value)


def _iso_date_value(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date_cls):
        return value.strftime("%Y-%m-%d")
    text = str(value or "")
    if len(text) >= 10:
        return text[:10]
    return text or "-"
