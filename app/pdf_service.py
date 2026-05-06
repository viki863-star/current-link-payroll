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

def generate_salary_slip_pdf(driver, salary_row, slip_payload, output_dir: str, assets_dir: str, generated_dir: str, payment_rows=None) -> str:
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
    _draw_salary_footer(pdf, driver, slip_payload, assets_dir, generated_dir, payment_rows or [])
    pdf.showPage()
    pdf.save()
    return str(output_path)


def generate_kata_pdf(driver, salary_rows, transactions, salary_slips, salary_payments=None, output_dir: str = "", assets_dir: str = "", month_value: str | None = None) -> str:
    if isinstance(salary_payments, (str, Path)) and output_dir and not assets_dir:
        assets_dir = output_dir
        output_dir = str(salary_payments)
        salary_payments = None
    normalized_month = format_month_label(month_value) if month_value else ""
    file_suffix = f"kata-{month_value}" if month_value else "kata-statement"
    output_path = Path(output_dir) / f"{driver['driver_id']}_{file_suffix}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    selected_month = month_value or ""

    def _salary_for_month(value):
        return not selected_month or (_pdf_row_value(value, "salary_month") or "") == selected_month

    def _txn_for_month(value):
        txn_month = (_pdf_row_value(value, "salary_month") or "").strip() or str(_pdf_row_value(value, "entry_date") or "")[:7]
        return not selected_month or txn_month == selected_month

    def _slip_for_month(value):
        return not selected_month or (_pdf_row_value(value, "salary_month") or "") == selected_month

    salary_payments = list(salary_payments or [])

    def _previous_month_before(target_month: str) -> str:
        candidates = []
        for row in salary_rows:
            month_text = (_pdf_row_value(row, "salary_month") or "").strip()
            if month_text and month_text < target_month:
                candidates.append(month_text)
        for row in salary_slips:
            month_text = (_pdf_row_value(row, "salary_month") or "").strip()
            if month_text and month_text < target_month:
                candidates.append(month_text)
        for row in salary_payments:
            month_text = (_pdf_row_value(row, "salary_month") or "").strip()
            if month_text and month_text < target_month:
                candidates.append(month_text)
        for row in transactions:
            month_text = ((_pdf_row_value(row, "salary_month") or "").strip() or str(_pdf_row_value(row, "entry_date") or "")[:7])
            if month_text and month_text < target_month:
                candidates.append(month_text)
        return max(candidates) if candidates else ""

    def _month_statement_core(target_month: str):
        previous_month = _previous_month_before(target_month)
        opening = 0.0
        if previous_month:
            previous_slips = [item for item in salary_slips if (_pdf_row_value(item, "salary_month") or "") == previous_month]
            if previous_slips:
                opening = _pdf_slip_amounts(previous_slips[-1])["company_balance_due"]
        opening = max(opening, 0.0)

        month_salary_rows = [row for row in salary_rows if (_pdf_row_value(row, "salary_month") or "") == target_month]
        month_transactions = [
            row for row in transactions
            if (((_pdf_row_value(row, "salary_month") or "").strip()) or str(_pdf_row_value(row, "entry_date") or "")[:7]) == target_month
        ]
        month_salary_slips = [row for row in salary_slips if (_pdf_row_value(row, "salary_month") or "") == target_month]
        month_salary_payments = [row for row in salary_payments if (_pdf_row_value(row, "salary_month") or "") == target_month]

        entries = []
        running = opening
        entries.append(
            {
                "date": f"{target_month}-01",
                "amount": opening,
                "paid_by": "Previous Month",
                "reason": "Opening balance",
                "balance_after": opening,
                "sort_group": -1,
            }
        )
        for salary in month_salary_rows:
            running += float(salary["net_salary"])
            entries.append(
                {
                    "date": _iso_date_value(salary["entry_date"]),
                    "amount": float(salary["net_salary"]),
                    "paid_by": "Current Link",
                    "reason": _pdf_salary_reason(salary),
                    "balance_after": max(running, 0.0),
                    "sort_group": 0,
                }
            )
        for txn in month_transactions:
            entries.append(
                {
                    "date": _iso_date_value(txn["entry_date"]),
                    "amount": float(txn["amount"]),
                    "paid_by": (_pdf_row_value(txn, "source") or _pdf_row_value(txn, "given_by") or "-").strip(),
                    "reason": (_pdf_row_value(txn, "details") or _pdf_row_value(txn, "given_by") or txn["txn_type"] or "-").strip(),
                    "balance_after": max(running, 0.0),
                    "sort_group": 1,
                }
            )
        total_deduction = sum(float(item["total_deductions"] or 0.0) for item in month_salary_slips)
        if total_deduction > 0:
            running = max(running - total_deduction, 0.0)
            entries.append(
                {
                    "date": f"{target_month}-28",
                    "amount": total_deduction,
                    "paid_by": "Current Link",
                    "reason": "Advance deduction applied",
                    "balance_after": running,
                    "sort_group": 2,
                }
            )
        if not month_salary_payments and month_salary_slips:
            for slip in month_salary_slips:
                slip_amounts = _pdf_slip_amounts(slip)
                if slip_amounts["actual_paid_amount"] > 0:
                    month_salary_payments.append(
                        {
                            "payment_date": _iso_date_value(_pdf_row_value(slip, "generated_at")),
                            "salary_month": _pdf_row_value(slip, "salary_month"),
                            "amount": slip_amounts["actual_paid_amount"],
                            "payment_source": _pdf_row_value(slip, "payment_source") or "",
                            "paid_by": _pdf_row_value(slip, "paid_by") or "",
                            "notes": "Legacy salary payment",
                        }
                    )
        for payment in month_salary_payments:
            payment_amount = float(_pdf_row_value(payment, "amount", 0.0) or 0.0)
            if payment_amount > 0:
                running = max(running - payment_amount, 0.0)
                entries.append(
                    {
                        "date": _iso_date_value(_pdf_row_value(payment, "payment_date")),
                        "amount": payment_amount,
                        "paid_by": (_pdf_row_value(payment, "payment_source") or _pdf_row_value(payment, "paid_by") or "-").strip(),
                        "reason": (_pdf_row_value(payment, "notes") or "Actual salary paid").strip(),
                        "balance_after": running,
                        "sort_group": 3,
                    }
                )
        total_company_balance = sum(_pdf_slip_amounts(item)["company_balance_due"] for item in month_salary_slips)
        if total_company_balance > 0:
            entries.append(
                {
                    "date": f"{target_month}-30",
                    "amount": total_company_balance,
                    "paid_by": "Current Link",
                    "reason": "Company balance due",
                    "balance_after": running,
                    "sort_group": 4,
                }
            )
        entries.sort(key=lambda item: (item["date"], item["sort_group"]))

        total_salary = sum(float(row["net_salary"]) for row in month_salary_rows)
        total_extra = sum(
            float(_pdf_row_value(row, "ot_amount", 0.0) or 0.0) + float(_pdf_row_value(row, "personal_vehicle", 0.0) or 0.0)
            for row in month_salary_rows
        )
        base_salary_total = max(total_salary - total_extra, 0.0)
        total_net_paid = sum(float(_pdf_row_value(item, "amount", 0.0) or 0.0) for item in month_salary_payments)
        return {
            "month": target_month,
            "previous_month": previous_month,
            "opening_balance": opening,
            "entries": entries,
            "earning_entries": [item for item in entries if item["sort_group"] == 0],
            "detail_entries": [item for item in entries if item["sort_group"] in (1, 2, 3)],
            "salary_rows": month_salary_rows,
            "transactions": month_transactions,
            "salary_slips": month_salary_slips,
            "payments": month_salary_payments,
            "total_salary": total_salary,
            "total_extra": total_extra,
            "base_salary_total": base_salary_total,
            "total_deducted": total_deduction,
            "total_paid": total_net_paid,
            "total_company_balance": total_company_balance,
            "closing_balance": max(running, 0.0),
        }

    def _undeducted_received_rows(entries, deduction_amount: float):
        remaining_deduction = max(float(deduction_amount or 0.0), 0.0)
        rows = []
        for item in entries:
            if item.get("sort_group") != 1:
                continue
            amount = float(item["amount"])
            recovered = min(amount, remaining_deduction)
            outstanding = max(amount - recovered, 0.0)
            remaining_deduction = max(remaining_deduction - recovered, 0.0)
            if outstanding <= 0.001:
                continue
            row = dict(item)
            row["amount"] = round(outstanding, 2)
            rows.append(row)
        return rows

    if selected_month:
        current_month_data = _month_statement_core(selected_month)
        entries = _undeducted_received_rows(current_month_data["entries"], current_month_data["total_deducted"])
        opening_balance = current_month_data["opening_balance"]
        total_salary = current_month_data["total_salary"]
        total_extra = current_month_data["total_extra"]
        base_salary_total = current_month_data["base_salary_total"]
        total_advance = sum(float(item["amount"]) for item in current_month_data["transactions"])
        total_deducted = current_month_data["total_deducted"]
        total_net_paid = current_month_data["total_paid"]
        total_company_balance = current_month_data["total_company_balance"]
        closing_balance = current_month_data["closing_balance"]
        salary_entries = list(current_month_data["earning_entries"])
        total_salary_with_balance = opening_balance + total_salary
        received_not_deducted_total = round(sum(float(item["amount"]) for item in entries), 2)
        remaining_salary = round(max(total_salary_with_balance - received_not_deducted_total, 0.0), 2)
    else:
        entries = []
        salary_entries = []
        opening_balance = 0.0
        total_salary = sum(float(row["net_salary"]) for row in salary_rows)
        total_extra = sum(
            float(_pdf_row_value(row, "ot_amount", 0.0) or 0.0) + float(_pdf_row_value(row, "personal_vehicle", 0.0) or 0.0)
            for row in salary_rows
        )
        base_salary_total = max(total_salary - total_extra, 0.0)
        total_advance = sum(float(item["amount"]) for item in transactions)
        for salary in salary_rows:
            entries.append(
                {
                    "date": _iso_date_value(salary["entry_date"]),
                    "amount": float(salary["net_salary"]),
                    "paid_by": "Current Link",
                    "reason": _pdf_salary_reason(salary),
                    "balance_after": 0.0,
                    "sort_group": 0,
                }
            )
            salary_entries.append(entries[-1])
        for txn in transactions:
            entries.append(
                {
                    "date": _iso_date_value(txn["entry_date"]),
                    "amount": float(txn["amount"]),
                    "paid_by": (_pdf_row_value(txn, "source") or _pdf_row_value(txn, "given_by") or "-").strip(),
                    "reason": (_pdf_row_value(txn, "details") or _pdf_row_value(txn, "given_by") or txn["txn_type"] or "-").strip(),
                    "balance_after": 0.0,
                    "sort_group": 1,
                }
            )
        total_deducted = sum(float(item["total_deductions"] or 0.0) for item in salary_slips)
        total_net_paid = sum(float(_pdf_row_value(item, "amount", 0.0) or 0.0) for item in salary_payments)
        total_company_balance = sum(_pdf_slip_amounts(item)["company_balance_due"] for item in salary_slips)
        closing_balance = total_company_balance
        entries.sort(key=lambda item: (item["date"], item["sort_group"]))
        total_salary_with_balance = total_salary
        received_not_deducted_total = total_advance
        remaining_salary = round(max(total_salary_with_balance - received_not_deducted_total, 0.0), 2)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    rows_per_page = 16 if selected_month else 20
    pages = [entries[index:index + rows_per_page] for index in range(0, len(entries), rows_per_page)] or [[]]

    for page_number, page_rows in enumerate(pages, start=1):
        _draw_header(pdf, assets_dir)
        _draw_title(
            pdf,
            "Driver Full KATA" if not selected_month else f"Driver Monthly Statement {normalized_month}",
            "Complete history" if not selected_month else "Current month salary and received detail",
        )
        _draw_kata_driver_summary(pdf, driver)
        if selected_month:
            _draw_kata_paper_summary(
                pdf,
                {
                    "previous_balance": format_currency(opening_balance),
                    "salary": format_currency(base_salary_total),
                    "extra": format_currency(total_extra),
                    "total_salary": format_currency(total_salary_with_balance),
                    "received_total": format_currency(received_not_deducted_total),
                    "remaining_salary": format_currency(remaining_salary),
                    "earning_rows": [
                        {
                            "date": item["date"],
                            "reason": item["reason"],
                            "amount": format_currency(float(item["amount"] or 0.0)),
                        }
                        for item in salary_entries[:4]
                    ],
                    "received_rows": [
                        {
                            "date": item["date"],
                            "reason": item["reason"],
                            "paid_by": item["paid_by"],
                            "amount": format_currency(float(item["amount"] or 0.0)),
                        }
                        for item in entries[:4]
                    ],
                },
                month_label=normalized_month,
                driver_id=driver["driver_id"],
            )
        else:
            _draw_kata_stat_row(
                pdf,
                [
                    ("Opening", format_currency(opening_balance if selected_month else 0.0)),
                    ("Salary", format_currency(total_salary)),
                    ("Transactions", format_currency(total_advance)),
                    ("Deducted", format_currency(total_deducted)),
                    ("Closing", format_currency(closing_balance)),
                ],
            )
            _draw_kata_stat_row(
                pdf,
                [
                    ("Paid", format_currency(total_net_paid)),
                    ("Balance", format_currency(total_company_balance)),
                    ("Period", normalized_month or "Start to End"),
                    ("Entries", str(len(entries))),
                    ("Page", f"{page_number}/{len(pages)}"),
                ],
                start_y=PAGE_HEIGHT - 157 * mm,
            )
        table_top = PAGE_HEIGHT - 254 * mm if selected_month else None
        _draw_kata_statement_table(pdf, page_rows, top=table_top)
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


def generate_cash_supplier_payment_voucher_pdf(party, payment, summary, output_dir: str, assets_dir: str) -> str:
    output_path = Path(output_dir) / f"{payment['payment_no']}_payment-voucher.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    _draw_header(pdf, assets_dir)
    _draw_title(pdf, "Supplier Payment Voucher", "Cash supplier payment acknowledgement and running balance summary")

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
    _draw_stat_box(pdf, 61 * mm, summary_top, 42 * mm, 15 * mm, "Total Earned", f"AED {format_currency(float(summary.get('total_earned', 0.0)))}", fill_color=SOFT, text_color=TEXT, border_color=LINE)
    _draw_stat_box(pdf, 106 * mm, summary_top, 42 * mm, 15 * mm, "Total Paid", f"AED {format_currency(float(summary.get('total_paid', 0.0)))}", fill_color=SOFT, text_color=TEXT, border_color=LINE)
    _draw_stat_box(pdf, 151 * mm, summary_top, 42 * mm, 15 * mm, "Running Balance", f"AED {format_currency(float(summary.get('balance', 0.0)))}", fill_color=colors.HexColor("#FFF4E8"), text_color=ORANGE, border_color=ORANGE)

    table_x = 16 * mm
    table_top = PAGE_HEIGHT - 188 * mm
    table_w = 178 * mm
    row_h = 10 * mm

    pdf.setFillColor(BLUE_DARK)
    pdf.roundRect(table_x, table_top, table_w, row_h, 3 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 8.5)
    headers = [("Payment No", 6), ("Date", 48), ("Method", 82), ("Reference", 122), ("Created By", 154)]
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
    pdf.drawString(table_x + 48 * mm, data_y + 16 * mm, format_date_label(payment["entry_date"]))
    pdf.drawString(table_x + 82 * mm, data_y + 16 * mm, payment.get("payment_method") or "-")
    pdf.drawString(table_x + 122 * mm, data_y + 16 * mm, (payment.get("reference") or "-")[:16])
    pdf.drawString(table_x + 154 * mm, data_y + 16 * mm, (payment.get("created_by") or "Admin")[:18])

    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(MUTED)
    pdf.drawString(table_x + 6 * mm, data_y + 8 * mm, f"Supplier Mode: {party.get('supplier_mode') or 'Cash'}")
    pdf.drawString(table_x + 56 * mm, data_y + 8 * mm, f"Debits / Loans: AED {format_currency(float(summary.get('total_debits', 0.0)))}")
    pdf.drawString(table_x + 126 * mm, data_y + 8 * mm, f"Status: {'Advance' if float(summary.get('balance', 0.0)) < 0 else 'Running'}")

    notes_y = PAGE_HEIGHT - 228 * mm
    pdf.setFillColor(SOFT)
    pdf.roundRect(16 * mm, notes_y, 178 * mm, 26 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(16 * mm, notes_y, 178 * mm, 26 * mm, 4 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(21 * mm, notes_y + 19 * mm, "Payment Notes")
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(21 * mm, notes_y + 11 * mm, (payment.get("notes") or "No notes entered.")[:110])

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
    summary = summary or {}
    total_work_done = float(summary.get("total_earned") or summary.get("earned") or 0.0)
    total_paid = float(summary.get("total_paid") or summary.get("paid") or 0.0)
    closing_balance = float(summary.get("balance") or 0.0)
    if not total_work_done:
        total_work_done = round(
            sum(float(item.get("total_amount") or item.get("earned") or 0.0) for item in rows or []),
            2,
        )
    if not total_paid:
        total_paid = round(
            sum(float(item.get("paid") or item.get("pdf_paid_amount") or 0.0) for item in rows or []),
            2,
        )

    def _party_value(key: str, default: str = "-"):
        if hasattr(party, "get"):
            return party.get(key, default)
        if key in party_keys:
            return party[key]
        return default

    raw_rows = list(rows or [])
    if not raw_rows:
        raw_rows = [
            {
                "pdf_date": "",
                "pdf_vehicle_no": "",
                "pdf_month_label": "",
                "pdf_qty_or_note": "No statement entries available.",
                "pdf_rate": "",
                "pdf_total_amount": "",
                "pdf_paid_amount": "",
                "pdf_balance": "0.00",
                "pdf_row_kind": "note",
                "running_balance": 0.0,
            }
        ]

    table_x = 16 * mm
    table_width = 178 * mm
    col_widths_mm = [22, 18, 19, 41, 18, 24, 18, 18]
    col_labels = ["Date", "Veh No", "Month", "Total Hour or Trips", "Rate", "Total Amount", "Paid", "Balance"]
    col_lefts = [table_x]
    for width_mm in col_widths_mm[:-1]:
        col_lefts.append(col_lefts[-1] + width_mm * mm)
    col_rights = [left + width_mm * mm for left, width_mm in zip(col_lefts, col_widths_mm)]
    row_fill_alt = colors.HexColor("#F6F9FD")
    row_fill_payment = colors.HexColor("#EEF8F0")
    row_fill_payment_band = colors.HexColor("#D9F0DF")
    grid_color = colors.HexColor("#6E7B8B")
    header_height = 9 * mm
    page_bottom_limit = 26 * mm
    table_top_base = PAGE_HEIGHT - (98 * mm if filter_caption else 92 * mm)
    body_top = table_top_base - header_height - (2 * mm)
    table_inner_pad = 1.6 * mm
    measure_pdf = canvas.Canvas(BytesIO(), pagesize=A4)

    def _prepare_display_row(source_row: dict):
        row_kind = str(source_row.get("pdf_row_kind") or "note")
        detail_text = str(source_row.get("pdf_qty_or_note") or "")
        if row_kind == "earning":
            detail_lines = [_fit_text(measure_pdf, detail_text, "Times-Roman", 8.3, (41 * mm) - (2 * table_inner_pad), min_size=7.8)[0]]
        else:
            detail_lines = _wrap_text_lines(
                measure_pdf,
                detail_text,
                "Times-Roman",
                8.1,
                (41 * mm) - (2 * table_inner_pad),
                max_lines=2,
                min_size=7.4,
            )
        visible_lines = [line for line in detail_lines if line]
        line_count = max(1, len(visible_lines))
        row_height = (10.5 * mm) if line_count == 1 else (14.5 * mm)
        return {
            "kind": row_kind,
            "date_text": _fit_text(measure_pdf, str(source_row.get("pdf_date") or ""), "Times-Roman", 8.4, (22 * mm) - (2 * table_inner_pad), min_size=7.6)[0],
            "vehicle_text": _fit_text(measure_pdf, str(source_row.get("pdf_vehicle_no") or ""), "Times-Roman", 8.4, (18 * mm) - (2 * table_inner_pad), min_size=7.6)[0],
            "month_text": _fit_text(measure_pdf, str(source_row.get("pdf_month_label") or ""), "Times-Roman", 8.4, (19 * mm) - (2 * table_inner_pad), min_size=7.6)[0],
            "detail_lines": visible_lines or [""],
            "rate_text": _fit_text(measure_pdf, str(source_row.get("pdf_rate") or ""), "Times-Roman", 8.4, (18 * mm) - (2 * table_inner_pad), min_size=7.6)[0],
            "total_text": _fit_text(measure_pdf, str(source_row.get("pdf_total_amount") or ""), "Times-Roman", 8.5, (24 * mm) - (2 * table_inner_pad), min_size=7.6)[0],
            "paid_text": _fit_text(measure_pdf, str(source_row.get("pdf_paid_amount") or ""), "Times-Roman", 8.5, (18 * mm) - (2 * table_inner_pad), min_size=7.6)[0],
            "balance_text": _fit_text(measure_pdf, str(source_row.get("pdf_balance") or ""), "Times-Bold", 8.6, (18 * mm) - (2 * table_inner_pad), min_size=7.6)[0],
            "balance_value": float(source_row.get("running_balance") or 0.0),
            "row_height": row_height,
        }

    display_rows = [_prepare_display_row(row) for row in raw_rows]

    pages = []
    current_page_rows = []
    used_height = 0.0
    available_height = body_top - page_bottom_limit
    for row in display_rows:
        if current_page_rows and used_height + row["row_height"] > available_height:
            pages.append(current_page_rows)
            current_page_rows = []
            used_height = 0.0
        current_page_rows.append(row)
        used_height += row["row_height"]
    if current_page_rows or not pages:
        pages.append(current_page_rows)

    def _draw_page_frame(pdf_obj: canvas.Canvas, page_number: int, page_count: int) -> float:
        pdf_obj.setFillColor(colors.white)
        pdf_obj.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
        _draw_header(pdf_obj, assets_dir)

        pdf_obj.setFillColor(BLUE_DARK)
        title_text, title_size = _fit_text(pdf_obj, title, "Times-Bold", 14.5, 88 * mm, min_size=12.0)
        pdf_obj.setFont("Times-Bold", title_size)
        pdf_obj.drawString(16 * mm, PAGE_HEIGHT - 57 * mm, title_text)

        pdf_obj.setFillColor(MUTED)
        pdf_obj.setFont("Helvetica-Bold", 7.4)
        pdf_obj.drawString(16 * mm, PAGE_HEIGHT - 62.2 * mm, "Statement of Account (SOA)")

        supplier_name, supplier_name_size = _fit_text(pdf_obj, str(_party_value("party_name") or "-"), "Times-Bold", 11.5, 120 * mm, min_size=9.5)
        pdf_obj.setFillColor(TEXT)
        pdf_obj.setFont("Times-Bold", supplier_name_size)
        pdf_obj.drawString(16 * mm, PAGE_HEIGHT - 67.8 * mm, supplier_name)

        supplier_code_text = f"Supplier Code: {_party_value('party_code') or '-'}"
        code_text, code_size = _fit_text(pdf_obj, supplier_code_text, "Times-Roman", 8.6, 120 * mm, min_size=7.6)
        pdf_obj.setFillColor(MUTED)
        pdf_obj.setFont("Times-Roman", code_size)
        pdf_obj.drawString(16 * mm, PAGE_HEIGHT - 73.2 * mm, code_text)

        report_x = 108 * mm
        report_y = PAGE_HEIGHT - 79 * mm
        report_w = 87 * mm
        report_h = 21 * mm
        pdf_obj.setFillColor(colors.white)
        pdf_obj.setStrokeColor(BLUE)
        pdf_obj.setLineWidth(0.8)
        pdf_obj.roundRect(report_x, report_y, report_w, report_h, 3.5 * mm, fill=1, stroke=1)
        pdf_obj.setFillColor(BLUE_SOFT)
        pdf_obj.roundRect(report_x, report_y + report_h - 6.2 * mm, report_w, 6.2 * mm, 3.5 * mm, fill=1, stroke=0)
        pdf_obj.setFillColor(BLUE_DARK)
        pdf_obj.setFont("Helvetica-Bold", 7.2)
        pdf_obj.drawString(report_x + 3.2 * mm, report_y + report_h - 4.3 * mm, "OVERALL REPORT")
        pdf_obj.setStrokeColor(LINE)
        pdf_obj.setLineWidth(0.5)
        metric_w = report_w / 3
        for idx in range(1, 3):
            divider_x = report_x + idx * metric_w
            pdf_obj.line(divider_x, report_y + 2.2 * mm, divider_x, report_y + report_h - 7.3 * mm)

        metric_specs = [
            ("TOTAL WORK", total_work_done, GREEN),
            ("TOTAL PAID", total_paid, BLUE_DARK),
            ("BALANCE", closing_balance, BLUE_DARK if closing_balance >= 0 else RED),
        ]
        for idx, (label, value, color) in enumerate(metric_specs):
            left_x = report_x + idx * metric_w
            center_x = left_x + (metric_w / 2)
            pdf_obj.setFillColor(MUTED)
            pdf_obj.setFont("Helvetica-Bold", 5.8)
            pdf_obj.drawCentredString(center_x, report_y + 8.2 * mm, label)
            value_text, value_size = _fit_text(
                pdf_obj,
                format_currency(value),
                "Helvetica-Bold",
                8.9,
                metric_w - (4 * mm),
                min_size=6.8,
            )
            pdf_obj.setFillColor(color)
            pdf_obj.setFont("Helvetica-Bold", value_size)
            pdf_obj.drawCentredString(center_x, report_y + 3.4 * mm, value_text)

        if filter_caption:
            filter_box_y = PAGE_HEIGHT - 84.5 * mm
            pdf_obj.setFillColor(SOFT)
            pdf_obj.setStrokeColor(LINE)
            pdf_obj.setLineWidth(0.45)
            pdf_obj.roundRect(16 * mm, filter_box_y - 2.0 * mm, 178 * mm, 5.8 * mm, 2.0 * mm, fill=1, stroke=1)
            filter_text, filter_size = _fit_text(
                pdf_obj,
                f"Filtered View: {filter_caption}",
                "Helvetica",
                7.2,
                172 * mm,
                min_size=6.6,
            )
            pdf_obj.setFillColor(MUTED)
            pdf_obj.setFont("Helvetica", filter_size)
            pdf_obj.drawString(18 * mm, filter_box_y, filter_text)

        pdf_obj.setFillColor(BLUE)
        pdf_obj.setStrokeColor(BLUE)
        pdf_obj.setLineWidth(0.6)
        pdf_obj.rect(table_x, table_top_base, table_width, header_height, fill=1, stroke=1)
        pdf_obj.setFillColor(colors.white)
        pdf_obj.setFont("Times-Bold", 9.0)
        for label, left_x, right_x in zip(col_labels, col_lefts, col_rights):
            pdf_obj.drawCentredString((left_x + right_x) / 2, table_top_base + 2.7 * mm, label)
        pdf_obj.setStrokeColor(colors.white)
        pdf_obj.setLineWidth(0.5)
        for x in col_rights[:-1]:
            pdf_obj.line(x, table_top_base, x, table_top_base + header_height)
        return body_top

    def _draw_cell_center(pdf_obj: canvas.Canvas, text: str, left_x: float, right_x: float, mid_y: float, font_name: str, font_size: float, *, min_size: float = 7.6, text_color=TEXT):
        cell_text, size = _fit_text(pdf_obj, text, font_name, font_size, (right_x - left_x) - (2 * table_inner_pad), min_size=min_size)
        pdf_obj.setFillColor(text_color)
        pdf_obj.setFont(font_name, size)
        pdf_obj.drawCentredString((left_x + right_x) / 2, mid_y - (size * 0.2), cell_text)

    def _draw_cell_right(pdf_obj: canvas.Canvas, text: str, left_x: float, right_x: float, mid_y: float, font_name: str, font_size: float, *, min_size: float = 7.6, text_color=TEXT):
        cell_text, size = _fit_text(pdf_obj, text, font_name, font_size, (right_x - left_x) - (2 * table_inner_pad), min_size=min_size)
        pdf_obj.setFillColor(text_color)
        pdf_obj.setFont(font_name, size)
        pdf_obj.drawRightString(right_x - table_inner_pad, mid_y - (size * 0.2), cell_text)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    for page_number, page_rows in enumerate(pages, start=1):
        current_top = _draw_page_frame(pdf, page_number, len(pages))
        for row_index, row in enumerate(page_rows):
            row_height = row["row_height"]
            row_bottom = current_top - row_height
            if row["kind"] == "payment":
                fill_color = row_fill_payment
            else:
                fill_color = row_fill_alt if row_index % 2 == 0 else colors.white
            pdf.setFillColor(fill_color)
            pdf.setStrokeColor(grid_color)
            pdf.setLineWidth(0.45)
            pdf.rect(table_x, row_bottom, table_width, row_height, fill=1, stroke=1)
            if row["kind"] == "payment":
                pdf.setFillColor(row_fill_payment_band)
                pdf.rect(table_x, row_bottom + row_height - (2.2 * mm), table_width, 2.2 * mm, fill=1, stroke=0)
                pdf.setStrokeColor(grid_color)
            for x in col_rights[:-1]:
                pdf.line(x, row_bottom, x, row_bottom + row_height)

            middle_y = row_bottom + (row_height / 2)
            _draw_cell_center(pdf, row["date_text"], col_lefts[0], col_rights[0], middle_y, "Times-Roman", 8.4)
            _draw_cell_center(pdf, row["vehicle_text"], col_lefts[1], col_rights[1], middle_y, "Times-Roman", 8.4)
            _draw_cell_center(pdf, row["month_text"], col_lefts[2], col_rights[2], middle_y, "Times-Roman", 8.4)

            if row["kind"] == "earning":
                _draw_cell_center(pdf, row["detail_lines"][0], col_lefts[3], col_rights[3], middle_y, "Times-Roman", 8.4)
            else:
                detail_x = col_lefts[3] + table_inner_pad
                if len(row["detail_lines"]) == 1:
                    detail_text, detail_size = _fit_text(pdf, row["detail_lines"][0], "Times-Roman", 8.2, (col_rights[3] - col_lefts[3]) - (2 * table_inner_pad), min_size=7.4)
                    pdf.setFillColor(TEXT)
                    pdf.setFont("Times-Roman", detail_size)
                    pdf.drawString(detail_x, middle_y - (detail_size * 0.2), detail_text)
                else:
                    first_y = row_bottom + row_height - (4.3 * mm)
                    second_y = row_bottom + row_height - (8.8 * mm)
                    pdf.setFillColor(TEXT)
                    pdf.setFont("Times-Roman", 8.0)
                    pdf.drawString(detail_x, first_y, row["detail_lines"][0])
                    pdf.drawString(detail_x, second_y, row["detail_lines"][1])

            _draw_cell_right(pdf, row["rate_text"], col_lefts[4], col_rights[4], middle_y, "Times-Roman", 8.4)
            total_color = RED if row["kind"] == "debit" and row["total_text"] else TEXT
            total_text = f"-{row['total_text']}" if row["kind"] == "debit" and row["total_text"] else row["total_text"]
            _draw_cell_right(pdf, total_text, col_lefts[5], col_rights[5], middle_y, "Times-Roman", 8.5, text_color=total_color)
            paid_color = BLUE_DARK if row["kind"] == "payment" and row["paid_text"] else TEXT
            paid_font = "Times-Bold" if row["kind"] == "payment" and row["paid_text"] else "Times-Roman"
            _draw_cell_right(pdf, row["paid_text"], col_lefts[6], col_rights[6], middle_y, paid_font, 8.5, text_color=paid_color)
            balance_color = TEXT if row["balance_value"] >= 0 else RED
            _draw_cell_right(pdf, row["balance_text"], col_lefts[7], col_rights[7], middle_y, "Times-Bold", 8.6, text_color=balance_color)
            current_top = row_bottom

        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 7.0)
        pdf.drawString(16 * mm, 14 * mm, f"Generated on {datetime.now().strftime('%d-%b-%Y %I:%M %p')}")
        pdf.drawRightString(194 * mm, 14 * mm, f"Page {page_number} / {len(pages)}")
        _draw_footer_banner(pdf, assets_dir, show_top_rule=False)
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
    header_x = 15 * mm
    header_y = PAGE_HEIGHT - 45 * mm
    header_w = 180 * mm
    header_h = 39 * mm

    pdf.setFillColor(colors.white)
    pdf.roundRect(header_x, header_y, header_w, header_h, 4 * mm, fill=1, stroke=0)

    if banner.exists():
        image = ImageReader(str(banner))
        image_width, image_height = image.getSize()
        target_width = 180 * mm
        target_height = target_width * (image_height / image_width)
        banner_x = 15 * mm
        banner_y = PAGE_HEIGHT - 44 * mm

        pdf.drawImage(
            image,
            banner_x,
            banner_y,
            width=target_width,
            height=target_height,
            preserveAspectRatio=False,
            mask="auto",
        )
    else:
        pdf.setFillColor(BLUE_DARK)
        pdf.roundRect(header_x, header_y, header_w, header_h, 4 * mm, fill=1, stroke=0)

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
    pdf.drawCentredString(metric_x + metric_w / 2, metric_y + 16 * mm, "ACTUAL PAID")
    pdf.setFont("Helvetica-Bold", 13.2)
    pdf.drawCentredString(metric_x + metric_w / 2, metric_y + 9.2 * mm, f"{format_currency(float(slip_payload['actual_paid_amount']))} AED")
    pdf.setFont("Helvetica", 7.2)
    pdf.drawCentredString(metric_x + metric_w / 2, metric_y + 3.2 * mm, format_month_label(salary_row["salary_month"]))

def _draw_salary_breakdown(pdf: canvas.Canvas, salary_row, slip_payload) -> None:
    ot_month = salary_row["ot_month"] if "ot_month" in salary_row.keys() and salary_row["ot_month"] else previous_month_value(salary_row["salary_month"])
    gross = float(salary_row["net_salary"])
    deduction_amount = float(slip_payload["deduction_amount"])
    available_advance = float(slip_payload["available_advance"])
    remaining_advance = float(slip_payload["remaining_advance"])
    salary_after_deduction = float(slip_payload["salary_after_deduction"])
    actual_paid_amount = float(slip_payload["actual_paid_amount"])
    company_balance_due = float(slip_payload["company_balance_due"])
    personal_vehicle_note = (salary_row["personal_vehicle_note"] or "").strip() if "personal_vehicle_note" in salary_row.keys() else ""

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

    personal_vehicle_label = "Personal / Vehicle"
    if personal_vehicle_note:
        personal_vehicle_label = f"Personal / Vehicle - {personal_vehicle_note}"
    earnings = [
        ("Basic Salary", float(salary_row["basic_salary"])),
        (f"OT Hours ({format_month_label(ot_month)})", float(salary_row["ot_hours"])),
        ("OT Amount", float(salary_row["ot_amount"])),
        (personal_vehicle_label, float(salary_row["personal_vehicle"])),
        ("Stored Salary", gross),
    ]
    deductions = [
        ("Available Advance", available_advance),
        ("Advance Deduction", deduction_amount),
        ("Advance Remaining", remaining_advance),
        ("Salary After Deduction", salary_after_deduction),
        ("Company Balance", company_balance_due),
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
        left_text, left_size = _fit_text(pdf, left_label, "Helvetica", 8.3, 52 * mm, min_size=6.2)
        right_text, right_size = _fit_text(pdf, right_label, "Helvetica", 8.3, 52 * mm, min_size=6.2)
        pdf.setFont("Helvetica", left_size)
        pdf.drawString(x + 6 * mm, row_y, left_text)
        pdf.setFont("Helvetica", right_size)
        pdf.drawString(x + 95 * mm, row_y, right_text)
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica-Bold", 8.7)
        pdf.drawRightString(x + 82 * mm, row_y, format_currency(left_value))
        pdf.drawRightString(x + 172 * mm, row_y, format_currency(right_value))
        row_y -= 8.1 * mm

    metrics_y = 84 * mm
    _draw_stat_box(pdf, 16 * mm, metrics_y, 56 * mm, 14 * mm, "STORED SALARY", format_currency(gross))
    _draw_stat_box(pdf, 77.5 * mm, metrics_y, 56 * mm, 14 * mm, "ACTUAL PAID", format_currency(actual_paid_amount))
    _draw_stat_box(pdf, 139 * mm, metrics_y, 56 * mm, 14 * mm, "COMPANY BALANCE", f"{format_currency(company_balance_due)} AED", fill_color=BLUE, text_color=colors.white, border_color=BLUE)


def _draw_salary_footer(pdf: canvas.Canvas, driver, slip_payload, assets_dir: str, generated_dir: str, payment_rows) -> None:
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
    status_label = "PAID" if float(slip_payload["company_balance_due"]) <= 0.001 else "PARTIAL"
    status_color = GREEN if status_label == "PAID" else ORANGE
    pdf.setFillColor(status_color)
    pdf.setFont("Helvetica-Bold", 13.5)
    pdf.drawString(status_x + 4 * mm, status_y + 17 * mm, status_label)
    _draw_small_meta_row(pdf, status_x + 4 * mm, status_y + 11.2 * mm, "Paid", f"AED {format_currency(float(slip_payload['actual_paid_amount']))}", 34 * mm)
    _draw_small_meta_row(pdf, status_x + 4 * mm, status_y + 6.7 * mm, "Balance", f"AED {format_currency(float(slip_payload['company_balance_due']))}", 34 * mm)
    _draw_small_meta_row(pdf, status_x + 4 * mm, status_y + 2.2 * mm, "Advance Left", f"AED {format_currency(float(slip_payload['remaining_advance']))}", 28 * mm)

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
    pdf.drawString(16 * mm, 30 * mm, "This is a system-generated salary slip for internal payroll records.")
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


def _draw_kata_paper_summary(pdf: canvas.Canvas, summary, month_label: str, driver_id: str) -> None:
    box_x = 16 * mm
    box_y = PAGE_HEIGHT - 170 * mm
    box_w = 178 * mm
    box_h = 62 * mm
    left_w = 72 * mm
    center_w = 54 * mm

    pdf.setFillColor(colors.white)
    pdf.roundRect(box_x, box_y, box_w, box_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(box_x, box_y, box_w, box_h, 4 * mm, fill=0, stroke=1)

    pdf.setFillColor(BLUE_SOFT)
    pdf.roundRect(box_x, box_y + box_h - 9 * mm, box_w, 9 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8.8)
    pdf.drawString(box_x + 4 * mm, box_y + box_h - 5.8 * mm, f"MONTHLY STATEMENT | {month_label}")
    pdf.drawRightString(box_x + box_w - 4 * mm, box_y + box_h - 5.8 * mm, f"Driver ID {driver_id}")

    pdf.setFont("Helvetica-Bold", 6.9)
    pdf.setFillColor(MUTED)
    pdf.drawString(box_x + 4 * mm, box_y + box_h - 11.4 * mm, "SALARY SUMMARY")
    pdf.drawString(box_x + left_w + 4 * mm, box_y + box_h - 11.4 * mm, "REMAINING SALARY")
    right_heading_x = box_x + left_w + center_w + 4 * mm
    pdf.drawString(right_heading_x, box_y + box_h - 11.4 * mm, "RECEIVED NOT YET")
    pdf.drawString(right_heading_x, box_y + box_h - 14.8 * mm, "DEDUCTED")

    pdf.setStrokeColor(LINE)
    pdf.line(box_x + left_w, box_y + 4 * mm, box_x + left_w, box_y + box_h - 11 * mm)
    pdf.line(box_x + left_w + center_w, box_y + 4 * mm, box_x + left_w + center_w, box_y + box_h - 11 * mm)

    row_y = box_y + box_h - 17 * mm
    left_rows = [
        ("Previous Balance", summary["previous_balance"]),
        ("Salary", summary["salary"]),
        ("Extra / OT", summary["extra"]),
        ("Total Salary", summary["total_salary"]),
    ]
    for label, value in left_rows:
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica-Bold", 7.8)
        pdf.drawString(box_x + 4 * mm, row_y, label)
        pdf.setFont("Helvetica-Bold", 8.2)
        pdf.drawRightString(box_x + left_w - 4 * mm, row_y, f"AED {value}")
        row_y -= 6 * mm

    center_x = box_x + left_w + 3 * mm
    center_y = box_y + 24 * mm
    inner_w = center_w - 6 * mm
    inner_h = 20 * mm
    pdf.setFillColor(BLUE)
    pdf.roundRect(center_x, center_y, inner_w, inner_h, 3 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 7.2)
    pdf.drawCentredString(center_x + inner_w / 2, center_y + inner_h - 5.8 * mm, "REMAINING SALARY")
    pdf.setFont("Helvetica-Bold", 12.4)
    pdf.drawCentredString(center_x + inner_w / 2, center_y + inner_h - 12.5 * mm, f"AED {summary['remaining_salary']}")

    meta_y = box_y + 14 * mm
    meta_left = box_x + left_w + 5 * mm
    meta_right = meta_left + center_w - 10 * mm
    for label, value in [
        ("Total Salary", summary["total_salary"]),
        ("Not Yet Deducted", summary["received_total"]),
    ]:
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica-Bold", 6.8)
        pdf.drawString(meta_left, meta_y, label)
        pdf.drawRightString(meta_right, meta_y, f"AED {value}")
        meta_y -= 5 * mm

    right_x = box_x + left_w + center_w + 4 * mm
    right_y = box_y + box_h - 17.5 * mm
    for detail in summary.get("received_rows", [])[:3]:
        pdf.setFillColor(TEXT)
        line = f"{format_date_label(detail['date'])} | {detail['reason']}"
        fitted, size = _fit_text(pdf, line, "Helvetica-Bold", 6.1, box_x + box_w - right_x - 4 * mm, min_size=5.5)
        pdf.setFont("Helvetica-Bold", size)
        pdf.drawString(right_x, right_y, fitted)
        pdf.drawRightString(box_x + box_w - 4 * mm, right_y, f"AED {detail['amount']}")
        detail_text, detail_size = _fit_text(pdf, detail["paid_by"], "Helvetica", 5.9, box_x + box_w - right_x - 4 * mm, min_size=5.3)
        pdf.setFont("Helvetica", detail_size)
        pdf.setFillColor(MUTED)
        pdf.drawString(right_x, right_y - 3.2 * mm, detail_text)
        right_y -= 7.4 * mm
    pdf.setStrokeColor(LINE)
    pdf.line(right_x, box_y + 10 * mm, box_x + box_w - 4 * mm, box_y + 10 * mm)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 7.0)
    pdf.drawString(right_x, box_y + 6 * mm, "Total Received")
    pdf.drawRightString(box_x + box_w - 4 * mm, box_y + 6 * mm, f"AED {summary['received_total']}")


def _draw_kata_closed_rows(pdf: canvas.Canvas, entries, month_label: str) -> None:
    box_x = 16 * mm
    box_y = PAGE_HEIGHT - 214 * mm
    box_w = 178 * mm
    box_h = 22 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(box_x, box_y, box_w, box_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(box_x, box_y, box_w, box_h, 4 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_SOFT)
    pdf.roundRect(box_x, box_y + box_h - 7.5 * mm, box_w, 7.5 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 7.6)
    pdf.drawString(box_x + 4 * mm, box_y + box_h - 4.9 * mm, f"Closed Previous Hisaab | {month_label}")

    row_y = box_y + box_h - 11.5 * mm
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.7)
    for item in entries[-3:]:
        text = f"{item['date']} | {item['reason']} | AED {format_currency(float(item['amount']))}"
        fitted, size = _fit_text(pdf, text, "Helvetica", 6.7, box_w - 10 * mm, min_size=6.0)
        pdf.setFont("Helvetica", size)
        pdf.drawString(box_x + 4 * mm, row_y, fitted)
        text_width = pdf.stringWidth(fitted, "Helvetica", size)
        pdf.setStrokeColor(MUTED)
        pdf.setLineWidth(0.7)
        pdf.line(box_x + 4 * mm, row_y + 1.2 * mm, box_x + 4 * mm + text_width, row_y + 1.2 * mm)
        row_y -= 4.2 * mm


def _draw_kata_stat_row(pdf: canvas.Canvas, items, start_y=None) -> None:
    start_x = 16 * mm
    start_y = start_y if start_y is not None else PAGE_HEIGHT - 137 * mm
    gap = 4 * mm
    box_w = (178 * mm - (gap * 4)) / 5
    box_h = 16 * mm

    for index, (label, value) in enumerate(items):
        x = start_x + index * (box_w + gap)
        fill = colors.white if index < 4 else BLUE
        text_color = TEXT if index < 4 else colors.white
        border = LINE if index < 4 else BLUE
        _draw_stat_box(pdf, x, start_y, box_w, box_h, label.upper(), value, fill_color=fill, text_color=text_color, border_color=border)


def _draw_kata_statement_table(pdf: canvas.Canvas, entries, top=None) -> None:
    top = top if top is not None else PAGE_HEIGHT - 180 * mm
    _draw_table_header(
        pdf,
        top,
        ["Date", "Amount", "Given By", "Details"],
        [18, 50, 88, 130],
    )

    y = top - 7 * mm
    row_height = 7.8 * mm
    for index, item in enumerate(entries[:20]):
        if index % 2 == 0:
            pdf.setFillColor(SOFT)
            pdf.roundRect(16 * mm, y - 3.1 * mm, 178 * mm, 7.2 * mm, 1.8 * mm, fill=1, stroke=0)
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica", 8.4)
        pdf.drawString(18 * mm, y, format_date_label(item["date"]))

        pdf.setFont("Helvetica-Bold", 8.4)
        pdf.drawRightString(75 * mm, y, format_currency(item["amount"]))

        who_text, who_size = _fit_text(pdf, item["paid_by"], "Helvetica-Bold", 8.2, 36 * mm, min_size=6.8)
        pdf.setFont("Helvetica-Bold", who_size)
        pdf.drawString(88 * mm, y, who_text)

        purpose_text, purpose_size = _fit_text(pdf, item["reason"], "Helvetica-Bold", 8.2, 58 * mm, min_size=6.8)
        pdf.setFont("Helvetica-Bold", purpose_size)
        pdf.drawString(130 * mm, y, purpose_text)
        y -= row_height
        if y < 44 * mm:
            break
    if entries:
        pdf.setStrokeColor(LINE)
        pdf.line(16 * mm, y + 2 * mm, 194 * mm, y + 2 * mm)
        pdf.setFont("Helvetica-Bold", 8.4)
        pdf.setFillColor(BLUE_DARK)
        pdf.drawString(18 * mm, y - 3 * mm, "Total")
        pdf.drawRightString(75 * mm, y - 3 * mm, format_currency(sum(float(item["amount"]) for item in entries)))


def _draw_footer_banner(pdf: canvas.Canvas, assets_dir: str, show_top_rule: bool = True) -> None:
    footer = Path(assets_dir) / "current-link-footer.png"
    if show_top_rule:
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


def _pdf_row_value(row, key, default=""):
    if isinstance(row, dict):
        return row.get(key, default)
    if hasattr(row, "keys") and key in row.keys():
        return row[key]
    return default


def _pdf_salary_reason(row) -> str:
    remarks = (_pdf_row_value(row, "remarks") or "").strip()
    personal_note = (_pdf_row_value(row, "personal_vehicle_note") or "").strip()
    personal_amount = float(_pdf_row_value(row, "personal_vehicle", 0.0) or 0.0)
    parts = []
    if remarks:
        parts.append(remarks)
    if personal_amount > 0 and personal_note:
        parts.append(f"Personal / Vehicle: {personal_note}")
    return " | ".join(parts) if parts else "Monthly salary"


def _pdf_slip_amounts(row) -> dict[str, float]:
    net_payable = float(_pdf_row_value(row, "net_payable", 0.0) or 0.0)
    salary_after_deduction = float(_pdf_row_value(row, "salary_after_deduction", 0.0) or 0.0)
    actual_paid_amount = float(_pdf_row_value(row, "actual_paid_amount", 0.0) or 0.0)
    company_balance_due = float(_pdf_row_value(row, "company_balance_due", 0.0) or 0.0)

    if salary_after_deduction <= 0 and net_payable > 0:
        salary_after_deduction = net_payable
    if actual_paid_amount <= 0 and net_payable > 0 and salary_after_deduction == net_payable and company_balance_due <= 0:
        actual_paid_amount = net_payable
    if company_balance_due <= 0 and salary_after_deduction >= actual_paid_amount:
        company_balance_due = max(salary_after_deduction - actual_paid_amount, 0.0)

    return {
        "salary_after_deduction": salary_after_deduction,
        "actual_paid_amount": actual_paid_amount,
        "company_balance_due": company_balance_due,
    }


def _iso_date_value(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date_cls):
        return value.strftime("%Y-%m-%d")
    text = str(value or "")
    if len(text) >= 10:
        return text[:10]
    return text or "-"
