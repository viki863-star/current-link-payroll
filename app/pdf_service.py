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
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except Exception:
    arabic_reshaper = None
    get_display = lambda s: s


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


def generate_lpo_pdf(company, party, lpo: dict, assets_dir: str, output_dir: str, company_profile: dict | None = None) -> str:
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
    _draw_header(pdf, assets_dir, company_profile)
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
                   f"{company.get('company_name', 'CURRENT LINK TRANSPORT AND GENERAL CONTRACTING')}  |  "
                   f"TRN: {company.get('trn_no') or '-'}")
    _draw_footer_banner(pdf, assets_dir, True, company_profile)

    pdf.showPage()
    pdf.save()
    return str(output_path)

def generate_salary_slip_pdf(driver, salary_row, slip_payload, output_dir: str, assets_dir: str, generated_dir: str, payment_rows=None, company_profile: dict | None = None) -> str:
    output_path = Path(output_dir) / f"{driver['driver_id']}_{salary_row['salary_month']}_salary-slip.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    _draw_header(pdf, assets_dir, company_profile)
    _draw_title(
        pdf,
        f"Salary Slip {format_month_label(salary_row['salary_month'])}",
        f"Payslip  |  {format_month_label(salary_row['salary_month'])}",
    )
    try:
        _draw_salary_summary(pdf, driver, salary_row, slip_payload)
    except Exception:
        pass
    try:
        _draw_salary_breakdown(pdf, salary_row, slip_payload)
    except Exception:
        pass
    try:
        _draw_salary_footer(pdf, driver, slip_payload, assets_dir, generated_dir, payment_rows or [], company_profile)
    except Exception:
        pass
    pdf.showPage()
    pdf.save()
    return str(output_path)


def generate_kata_pdf(driver, salary_rows, transactions, salary_slips, salary_payments=None, output_dir: str = "", assets_dir: str = "", month_value: str | None = None, company_profile: dict | None = None) -> str:
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

    from reportlab.platypus import SimpleDocTemplate, Paragraph as PlParagraph, Spacer, Table as PlTable, TableStyle as PlTableStyle, Image as PlImage
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    import os, tempfile

    LM, RM, TM, BM = 18*mm, 18*mm, 15*mm, 15*mm
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM

    cp = dict(company_profile) if company_profile else {}
    tc = cp.get("theme_color") or "#1a3a5c"
    try:
        TH = colors.HexColor(tc)
    except:
        TH = colors.HexColor("#1a3a5c")
    BG = colors.HexColor("#f4f6f9")
    WH = colors.white
    C3 = colors.HexColor("#d1d5db")
    C4 = colors.HexColor("#111827")
    C5 = colors.HexColor("#6b7280")

    def F(name, **kw):
        kw.setdefault("fontSize", 8)
        kw.setdefault("leading", 12)
        return ParagraphStyle(name, **kw)

    def C(t, **kw):
        kw.setdefault("alignment", TA_CENTER)
        return PlParagraph(str(t), F("_C", **kw))

    def R(t, **kw):
        kw.setdefault("alignment", TA_RIGHT)
        return PlParagraph(str(t), F("_R", **kw))

    els = []
    cn = cp.get("company_name", "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING")
    trn = cp.get("trn_no") or "—"

    # ═══ HEADER ═══
    logo = None
    LW = 0
    if cp.get("logo_data"):
        try:
            lb = base64.b64decode(cp["logo_data"])
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            f.write(lb)
            f.close()
            logo = PlImage(f.name, width=50, height=50)
            LW = 50
        except Exception:
            pass

    cl = [f"<font size=11><b>{cn}</b></font>"]
    addr = cp.get("address") or ""
    ph = cp.get("phone_number") or ""
    em = cp.get("email") or ""
    parts_l = [x for x in [addr] if x]
    cparts = [x for x in [ph, em, f"TRN: {trn}"] if x and x != "TRN: —"]
    if parts_l or cparts:
        info = " &middot; ".join(parts_l + cparts)
        cl.append(f"<font size=6.5 color='#6b7280'>{info}</font>")
    co_p = PlParagraph("<br/>".join(cl), F("CO", fontSize=11, fontName="Helvetica-Bold", textColor=TH, leading=13))
    if logo:
        lh = PlTable([[logo, Spacer(1, 3*mm), co_p]], colWidths=[LW, 3*mm, W*0.65 - LW - 3*mm])
        lh.setStyle(PlTableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    else:
        lh = co_p
    rh = PlParagraph("<b>STATEMENT<br/>OF ACCOUNT</b>", F("TI", fontSize=14, fontName="Helvetica-Bold", textColor=TH, leading=18, alignment=TA_RIGHT))
    ht = PlTable([[lh, rh]], colWidths=[W*0.65, W*0.35])
    ht.setStyle(PlTableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ht)
    els.append(Spacer(1, 2*mm))
    hr = PlTable([[""]], colWidths=[W], rowHeights=[2])
    hr.setStyle(PlTableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(hr)
    els.append(Spacer(1, 4*mm))

    # ═══ FUND INFO ═══
    month_display = f" — {normalized_month}" if normalized_month else ""
    finfo = [
        [PlParagraph("<b>Fund</b>", F("_fl", fontSize=8, fontName="Helvetica-Bold", textColor=C4, leading=11)),
         PlParagraph(f"<b>Driver Statement{month_display}</b>", F("_fv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=12))],
        [PlParagraph("Driver", F("_l", fontSize=7.5, textColor=C5, leading=10)),
         PlParagraph(f"{driver['full_name']} ({driver['driver_id']})", F("_v", fontSize=8.5, textColor=C4, leading=11))],
    ]
    if driver.get("vehicle_no"):
        finfo.append([PlParagraph("Vehicle", F("_l", fontSize=7.5, textColor=C5, leading=10)),
                      PlParagraph(driver["vehicle_no"], F("_v", fontSize=8.5, textColor=C4, leading=11))])
    ft = PlTable(finfo, colWidths=[50, W - 50])
    ft.setStyle(PlTableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ft)

    # ═══ SUMMARY CARDS ═══
    els.append(Spacer(1, 3*mm))
    if selected_month:
        sdata = [[
            PlParagraph(f"<b>Opening Balance</b><br/><font size=10 color='#1a3a5c'>AED {format_currency(opening_balance)}</font>", F("_s1", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
            PlParagraph(f"<b>Salary</b><br/><font size=10 color='#1a7d1a'>AED {format_currency(total_salary)}</font>", F("_s2", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
            PlParagraph(f"<b>Received</b><br/><font size=10 color='#c62828'>AED {format_currency(received_not_deducted_total)}</font>", F("_s3", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
            PlParagraph(f"<b>Remaining</b><br/><font size=10 color='#e65100'>AED {format_currency(remaining_salary)}</font>", F("_s4", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        ]]
    else:
        sdata = [[
            PlParagraph(f"<b>Total Salary</b><br/><font size=10 color='#1a7d1a'>AED {format_currency(total_salary)}</font>", F("_s1", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
            PlParagraph(f"<b>Transactions</b><br/><font size=10 color='#c62828'>AED {format_currency(total_advance)}</font>", F("_s2", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
            PlParagraph(f"<b>Deducted</b><br/><font size=10 color='#e65100'>AED {format_currency(total_deducted)}</font>", F("_s3", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
            PlParagraph(f"<b>Paid</b><br/><font size=10 color='#1a3a5c'>AED {format_currency(total_net_paid)}</font>", F("_s4", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        ]]
    st = PlTable(sdata, colWidths=[W/4, W/4, W/4, W/4])
    st.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5),
        ("BACKGROUND",(0,0),(-1,-1),BG),
    ]))
    els.append(st)
    els.append(Spacer(1, 3*mm))

    # ═══ STATEMENT TABLE ═══
    colw = [55, 40, 50, 50, W - 55 - 40 - 50 - 50 - 42 - 42 - 50, 42, 42, 50]
    hdr = [
        PlParagraph("<b>Date</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        PlParagraph("<b>Month</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        PlParagraph("<b>Reference</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        PlParagraph("<b>Type</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        PlParagraph("<b>Details</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        PlParagraph("<b>In (AED)</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
        PlParagraph("<b>Out (AED)</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
        PlParagraph("<b>Balance (AED)</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
    ]
    rws = [hdr]

    if selected_month:
        rws.append([
            PlParagraph("", F("_o", fontSize=6.5, leading=9)), PlParagraph("", F("_o")),
            PlParagraph("", F("_o")), PlParagraph("Opening Balance", F("_ol", fontSize=6.5, textColor=C5, leading=9)),
            PlParagraph("", F("_o")), PlParagraph("", F("_o")), PlParagraph("", F("_o")),
            PlParagraph(f"<b>{format_currency(opening_balance)}</b>", F("_ob", fontSize=6.5, fontName="Helvetica-Bold", textColor=C4, alignment=TA_RIGHT, leading=9)),
        ])

    total_in = 0.0
    total_out = 0.0
    for item in entries:
        d = item["date"]
        month = d[:7] if d else ""
        sg = item.get("sort_group", 1)
        etype = {0: "Salary", 1: "Advance", 2: "Deduction", 3: "Payment", 4: "Closing"}.get(sg, "")
        ref = str(item.get("paid_by", "-"))
        det = str(item.get("reason", "-"))
        amount = float(item.get("amount", 0.0))
        bal = float(item.get("balance_after", 0.0))
        is_incoming = sg == 0
        inv = amount if is_incoming else 0.0
        outv = amount if not is_incoming and sg >= 1 else 0.0
        total_in += inv
        total_out += outv
        bal_c = "#c62828" if bal > 0 else "#1a7d1a" if bal < 0 else "#111827"

        rws.append([
            PlParagraph(d, F("_d", fontSize=6.5, leading=9)),
            PlParagraph(f"<font color='#6b7280'>{month}</font>", F("_m", fontSize=6, textColor=C5, leading=9)),
            PlParagraph(ref, F("_r", fontSize=6.5, fontName="Helvetica-Bold", textColor=C4, leading=9)),
            PlParagraph(f"<font color=\"{'#1a56db' if is_incoming else '#c62828' if sg >= 1 else '#e65100'}\">{etype}</font>", F("_t", fontSize=6.5, alignment=TA_CENTER, leading=9)),
            PlParagraph(det, F("_det", fontSize=6.2, textColor=C5, leading=9)),
            PlParagraph(f"<b>{inv:,.2f}</b>" if inv else '<font color="#cccccc">—</font>', F("_dr", fontSize=6.5, textColor="#1a7d1a" if inv else C5, alignment=TA_RIGHT, leading=9)),
            PlParagraph(f"<b>{outv:,.2f}</b>" if outv else '<font color="#cccccc">—</font>', F("_cr", fontSize=6.5, textColor="#c62828" if outv else C5, alignment=TA_RIGHT, leading=9)),
            PlParagraph(f"<b>{format_currency(bal)}</b>", F("_bl", fontSize=6.5, fontName="Helvetica-Bold", textColor=bal_c, alignment=TA_RIGHT, leading=9)),
        ])

    closing_val = closing_balance if selected_month else total_company_balance
    rws.append([
        PlParagraph("<b>Closing Balance</b>", F("_cb", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, leading=10)),
        PlParagraph("", F("_x")), PlParagraph("", F("_x")), PlParagraph("", F("_x")), PlParagraph("", F("_x")),
        PlParagraph(f"<b>{format_currency(total_in)}</b>", F("_ct", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        PlParagraph(f"<b>{format_currency(total_out)}</b>", F("_ct", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        PlParagraph(f"<b>{format_currency(closing_val)}</b>", F("_ccl", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
    ])

    it = PlTable(rws, colWidths=colw, repeatRows=1)
    it.setStyle(PlTableStyle([
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

    # ═══ SIGNATURES ═══
    els.append(Spacer(1, 8*mm))
    s_sg = ParagraphStyle("SSG", fontSize=9, alignment=TA_CENTER, leading=14)
    s_stamp_path = os.path.join(assets_dir, 'Stamp.png')
    s_sign_path = os.path.join(assets_dir, 'Sign (1).png')
    s_auth_cells = []
    s_auth_cells.append(PlParagraph("_________________________", s_sg))
    if os.path.exists(s_stamp_path):
        s_auth_cells.append(PlImage(s_stamp_path, width=40, height=40))
    if os.path.exists(s_sign_path):
        s_auth_cells.append(PlImage(s_sign_path, width=40, height=40))
    s_auth_cells.append(PlParagraph("<b>Authorized Signatory</b>", s_sg))
    s_auth_cell = PlTable([[c] for c in s_auth_cells], colWidths=[W*0.35])
    s_auth_cell.setStyle(PlTableStyle([
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),0),
        ("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))
    soa_sig = PlTable([[
        s_auth_cell,
        C("", fontSize=4),
        PlParagraph("", s_sg),
    ]], colWidths=[W*0.35, W*0.30, W*0.35])
    soa_sig.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LINEABOVE",(0,0),(0,0),0.5,C5), ("LINEABOVE",(2,0),(2,0),0.5,C5),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
    ]))
    els.append(soa_sig)

    # ═══ FOOTER ═══
    els.append(Spacer(1, 8*mm))
    fh = PlTable([[""]], colWidths=[W], rowHeights=[0.5])
    fh.setStyle(PlTableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(fh)
    els.append(Spacer(1, 2*mm))
    ft_txt = "This is a computer-generated Statement of Account."
    els.append(PlParagraph(ft_txt, F("_ft", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=9)))

    doc.build(els)
    return str(output_path)


def generate_simple_kata_pdf(driver, salary_row, unpaid_salary_rows, advances, prev_remaining, this_deduction, remaining, month_value, output_dir: str, assets_dir: str, company_profile: dict | None = None) -> str:
    from reportlab.platypus import SimpleDocTemplate, Paragraph as PlParagraph, Spacer, Table as PlTable, TableStyle as PlTableStyle, Image as PlImage
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    import os, tempfile

    _URDU_FONT = "NotoNaskhArabic"
    if _URDU_FONT not in pdfmetrics.getRegisteredFontNames():
        try:
            _urdu_font_path = os.path.join(assets_dir or "", "fonts", "NotoNaskhArabic-Regular.ttf")
            if os.path.exists(_urdu_font_path):
                pdfmetrics.registerFont(TTFont(_URDU_FONT, _urdu_font_path))
        except Exception:
            pass

    def _urdu(text):
        try:
            return get_display(arabic_reshaper.reshape(str(text)))
        except Exception:
            return str(text)

    def _UP(text, **kw):
        kw.setdefault("fontSize", 8)
        kw.setdefault("alignment", TA_CENTER)
        return PlParagraph(_urdu(text), ParagraphStyle("UP", fontName=_URDU_FONT, **kw))

    normalized_month = format_month_label(month_value) if month_value else ""
    file_suffix = f"kata-{month_value}" if month_value else "kata-statement"
    output_path = Path(output_dir) / f"{driver['driver_id']}_{file_suffix}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    LM, RM, TM, BM = 18*mm, 18*mm, 15*mm, 15*mm
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM

    cp = dict(company_profile) if company_profile else {}
    tc = cp.get("theme_color") or "#1a3a5c"
    try: TH = colors.HexColor(tc)
    except: TH = colors.HexColor("#1a3a5c")
    BG = colors.HexColor("#f4f6f9"); WH = colors.white
    C3 = colors.HexColor("#d1d5db"); C4 = colors.HexColor("#111827")
    C5 = colors.HexColor("#6b7280")

    def F(name, **kw):
        kw.setdefault("fontSize", 8); kw.setdefault("leading", 12)
        return ParagraphStyle(name, **kw)
    def C(t, **kw):
        kw.setdefault("alignment", TA_CENTER)
        return PlParagraph(str(t), F("_C", **kw))
    def R(t, **kw):
        kw.setdefault("alignment", TA_RIGHT)
        return PlParagraph(str(t), F("_R", **kw))

    els = []
    cn = cp.get("company_name", "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING")
    trn = cp.get("trn_no") or "—"

    # ═══ HEADER ═══
    logo = None; LW = 0
    if cp.get("logo_data"):
        try:
            lb = base64.b64decode(cp["logo_data"])
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            f.write(lb); f.close()
            logo = PlImage(f.name, width=50, height=50)
            LW = 50
        except: pass

    cl = [f"<font size=11><b>{cn}</b></font>"]
    addr = cp.get("address") or ""; ph = cp.get("phone_number") or ""; em = cp.get("email") or ""
    parts_l = [x for x in [addr] if x]
    cparts = [x for x in [ph, em, f"TRN: {trn}"] if x and x != "TRN: —"]
    if parts_l or cparts:
        info = " &middot; ".join(parts_l + cparts)
        cl.append(f"<font size=6.5 color='#6b7280'>{info}</font>")
    co_p = PlParagraph("<br/>".join(cl), F("CO", fontSize=11, fontName="Helvetica-Bold", textColor=TH, leading=13))
    if logo:
        lh = PlTable([[logo, Spacer(1, 3*mm), co_p]], colWidths=[LW, 3*mm, W*0.65 - LW - 3*mm])
        lh.setStyle(PlTableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    else:
        lh = co_p
    rh = PlParagraph("<b>STATEMENT<br/>OF ACCOUNT</b>", F("TI", fontSize=14, fontName="Helvetica-Bold", textColor=TH, leading=18, alignment=TA_RIGHT))
    ht = PlTable([[lh, rh]], colWidths=[W*0.65, W*0.35])
    ht.setStyle(PlTableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ht)
    els.append(Spacer(1, 2*mm))
    hr = PlTable([[""]], colWidths=[W], rowHeights=[2])
    hr.setStyle(PlTableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(hr)
    els.append(Spacer(1, 4*mm))

    # ═══ FUND INFO ═══
    net_sal = float(salary_row.get("net_salary")) if salary_row else 0.0
    finfo = [
        [PlParagraph("<b>Fund</b>", F("_fl", fontSize=8, fontName="Helvetica-Bold", textColor=C4, leading=11)),
         PlParagraph(f"<b>Employee Statement — {normalized_month}</b>", F("_fv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=12))],
        [PlParagraph("Employee", F("_l", fontSize=7.5, textColor=C5, leading=10)),
         PlParagraph(f"{driver.get('full_name','-')} ({driver.get('driver_id','-')})", F("_v", fontSize=8.5, textColor=C4, leading=11))],
    ]
    ft = PlTable(finfo, colWidths=[50, W - 50])
    ft.setStyle(PlTableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ft)

    # ═══ SUMMARY CARDS ═══
    els.append(Spacer(1, 3*mm))
    unpaid_sal_total = sum(float(r.get("net_salary") or 0) for r in (unpaid_salary_rows or []))
    txn_total_all = sum(float(a.get("amount", 0)) for a in advances)
    salary_after_deduct = max(unpaid_sal_total - txn_total_all, 0.0)
    def _summary_card(en_label, ur_label, amount_html, style_name, fs=10, highlight=False):
        hl_bg = colors.HexColor("#e8f5e9") if highlight else WH
        hl_line = colors.HexColor("#2e7d32") if highlight else TH
        inner = [
            [PlParagraph(f"<b>{en_label}</b>", F(style_name, fontSize=6, fontName="Helvetica-Bold", textColor=C5, alignment=TA_CENTER, leading=8)),
             _UP(f"<b>{ur_label}</b>")],
            [PlParagraph(amount_html, F(style_name, fontSize=fs, textColor=C5, alignment=TA_CENTER, leading=fs + 4))],
        ]
        t = PlTable(inner, colWidths=[W/4])
        t.setStyle(PlTableStyle([
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("ALIGN",(0,0),(-1,-1),"CENTER"),
            ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
            ("LEFTPADDING",(0,0),(-1,-1),1), ("RIGHTPADDING",(0,0),(-1,-1),1),
            ("BACKGROUND",(0,0),(-1,-1),hl_bg),
            ("LINEABOVE",(0,0),(-1,-1),0.8,hl_line),
        ]))
        return t

    sdata = [[
        _summary_card("TOTAL ADVANCES", "کل ایڈوانسز", f"<font color='#c62828'><b>{format_currency(txn_total_all)}</b></font>", "_s1", fs=10),
        _summary_card("STORE SALARY", "اسٹور تنخواہ", f"<font color='#1a7d1a'><b>{format_currency(unpaid_sal_total)}</b></font>", "_s2", fs=10),
        _summary_card("DEDUCTED", "کٹوتی", f"<font color='#1a3a5c'><b>{format_currency(this_deduction)}</b></font>", "_s3", fs=10),
        _summary_card("NET PAYABLE", "کٹوتی کے بعد تنخواہ", f"<font color='#2e7d32'><b>{format_currency(salary_after_deduct)}</b></font>", "_s4", fs=11, highlight=True),
    ]]
    st = PlTable(sdata, colWidths=[W/4, W/4, W/4, W/4])
    st.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5),
        ("BACKGROUND",(0,0),(-1,-1),BG),
    ]))
    els.append(st)
    els.append(Spacer(1, 3*mm))

    # ═══ TWO-COLUMN LAYOUT: TRANSACTIONS (LEFT) + SALARY (RIGHT) ═══
    left_w = W * 0.55
    right_w = W * 0.45
    gap = 4*mm
    col_w = [left_w, gap, right_w]

    # ── LEFT: ADVANCES / TRANSACTIONS TABLE ──
    left_title = [
        PlParagraph("<b>Transactions (Advances Received)</b>", F("_ltitle", fontSize=7.5, fontName="Helvetica-Bold", textColor=TH, leading=10)),
        _UP("<b>لین دین (موصول شدہ پیشگی)</b>"),
    ]
    
    txn_colw = [42, left_w - 42 - 42, 42]
    txn_hdr = [
        PlParagraph("<b>Date</b>", F("_th", fontSize=5.8, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=8)),
        PlParagraph("<b>Details</b>", F("_th", fontSize=5.8, fontName="Helvetica-Bold", textColor=WH, leading=8)),
        PlParagraph("<b>Amount</b>", F("_th", fontSize=5.8, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=8)),
    ]
    txn_rows = [txn_hdr]
    txn_total = 0.0
    for a in advances:
        amt = float(a.get("amount", 0))
        txn_total += amt
        txn_rows.append([
            PlParagraph(str(a.get("entry_date", ""))[:10], F("_td", fontSize=6, leading=8)),
            PlParagraph(str(a.get("details", "-"))[:40], F("_tDet", fontSize=5.8, textColor=C5, leading=8)),
            PlParagraph(f"<b>{format_currency(amt)}</b>", F("_ta", fontSize=6, fontName="Helvetica-Bold", textColor=C4, alignment=TA_RIGHT, leading=8)),
        ])
    # Total row
    txn_rows.append([
        PlParagraph("<b>Total</b>", F("_ttb", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        PlParagraph("", F("_tx")),
        PlParagraph(f"<b>{format_currency(txn_total)}</b>", F("_ttt", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
    ])
    txn_tbl = PlTable(txn_rows, colWidths=txn_colw, repeatRows=1)
    txn_tbl.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BACKGROUND",(0,0),(-1,0),TH), ("TEXTCOLOR",(0,0),(-1,0),WH),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),1.5), ("BOTTOMPADDING",(0,0),(-1,-1),1.5),
        ("LEFTPADDING",(0,0),(-1,-1),2), ("RIGHTPADDING",(0,0),(-1,-1),2),
        ("BACKGROUND",(0,-1),(-1,-1),TH), ("TEXTCOLOR",(0,-1),(-1,-1),WH),
        ("ROWBACKGROUNDS",(0,1),(-2,-2),[WH, BG]),
    ]))

    # ── RIGHT: ALL UNPAID SALARY STORE ROWS ──
    right_title = [
        PlParagraph("<b>Store Salary (Not Yet Run)</b>", F("_rtitle", fontSize=7.5, fontName="Helvetica-Bold", textColor=TH, leading=10)),
        _UP("<b>اسٹور تنخواہ (ابھی اجرا نہیں ہوئی)</b>"),
    ]
    
    sal_colw = [right_w * 0.55, right_w * 0.45]
    sal_hdr = [
        PlParagraph("<b>Month</b>", F("_sh2", fontSize=5.8, fontName="Helvetica-Bold", textColor=WH, leading=8)),
        PlParagraph("<b>Amount</b>", F("_sh2", fontSize=5.8, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=8)),
    ]
    sal_rows = [sal_hdr]
    sal_grand_total = 0.0
    if unpaid_salary_rows:
        for sr in unpaid_salary_rows:
            month = str(sr.get("salary_month", ""))
            net = float(sr.get("net_salary") or 0)
            sal_rows.append([
                PlParagraph(f"<b>{month}</b>", F("_smh", fontSize=6, fontName="Helvetica-Bold", textColor=C4, leading=8)),
                PlParagraph(f"<b>{format_currency(net)}</b>", F("_sa2", fontSize=6, fontName="Helvetica-Bold", textColor=C4, alignment=TA_RIGHT, leading=8)),
            ])
            sal_grand_total += net
    else:
        sal_rows.append([
            PlParagraph("—", F("_sd2", fontSize=6, textColor=C5, leading=8)),
            PlParagraph("", F("_sd2", fontSize=6, leading=8)),
        ])

    # Grand total row
    sal_rows.append([
        PlParagraph("<b>Total Store Salary</b>", F("_st2", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        PlParagraph(f"<b>{format_currency(sal_grand_total)}</b>", F("_stv2", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
    ])

    sal_tbl = PlTable(sal_rows, colWidths=sal_colw, repeatRows=1)
    sal_tbl.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BACKGROUND",(0,0),(-1,0),TH), ("TEXTCOLOR",(0,0),(-1,0),WH),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),1.5), ("BOTTOMPADDING",(0,0),(-1,-1),1.5),
        ("LEFTPADDING",(0,0),(-1,-1),2), ("RIGHTPADDING",(0,0),(-1,-1),2),
        ("BACKGROUND",(0,-1),(-1,-1),TH), ("TEXTCOLOR",(0,-1),(-1,-1),WH),
        ("ROWBACKGROUNDS",(0,1),(-2,-2),[WH, BG]),
    ]))

    # Combine both sides into two-column layout
    left_content = left_title + [Spacer(1, 1.5*mm), txn_tbl]
    right_content = right_title + [Spacer(1, 1.5*mm), sal_tbl]
    
    # Build left side table
    left_table = PlTable([[c] for c in left_content], colWidths=[left_w])
    left_table.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),0), ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))
    right_table = PlTable([[c] for c in right_content], colWidths=[right_w])
    right_table.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),0), ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))

    two_col = PlTable([[left_table, Spacer(1, gap), right_table]], colWidths=col_w)
    two_col.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),0), ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))
    els.append(two_col)

    # ═══ SIGNATURES ═══
    els.append(Spacer(1, 8*mm))
    s_sg = ParagraphStyle("SSG", fontSize=9, alignment=TA_CENTER, leading=14)
    s_stamp_path = os.path.join(assets_dir, 'Stamp.png')
    s_sign_path = os.path.join(assets_dir, 'Sign (1).png')
    s_auth_cells = []
    s_auth_cells.append(PlParagraph("_________________________", s_sg))
    if os.path.exists(s_stamp_path):
        s_auth_cells.append(PlImage(s_stamp_path, width=40, height=40))
    if os.path.exists(s_sign_path):
        s_auth_cells.append(PlImage(s_sign_path, width=40, height=40))
    s_auth_cells.append(PlParagraph("<b>Authorized Signatory</b>", s_sg))
    s_auth_cell = PlTable([[c] for c in s_auth_cells], colWidths=[W*0.35])
    s_auth_cell.setStyle(PlTableStyle([
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),0),
        ("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))
    soa_sig = PlTable([[
        s_auth_cell,
        C("", fontSize=4),
        PlParagraph("", s_sg),
    ]], colWidths=[W*0.35, W*0.30, W*0.35])
    soa_sig.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LINEABOVE",(0,0),(0,0),0.5,C5), ("LINEABOVE",(2,0),(2,0),0.5,C5),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
    ]))
    els.append(soa_sig)

    # ═══ FOOTER ═══
    els.append(Spacer(1, 8*mm))
    fh = PlTable([[""]], colWidths=[W], rowHeights=[0.5])
    fh.setStyle(PlTableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(fh)
    els.append(Spacer(1, 2*mm))
    ft_txt = "This is a computer-generated Employee Statement."
    els.append(PlParagraph(ft_txt, F("_ft", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=9)))

    doc.build(els)
    return str(output_path)


def generate_transactions_kata_pdf(driver, advances, month_value, output_dir: str, assets_dir: str, company_profile: dict | None = None) -> str:
    from reportlab.platypus import SimpleDocTemplate, Paragraph as PlParagraph, Spacer, Table as PlTable, TableStyle as PlTableStyle, Image as PlImage
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    import os, tempfile

    normalized_month = format_month_label(month_value) if month_value else ""
    file_suffix = f"transactions-{month_value}" if month_value else "transactions"
    output_path = Path(output_dir) / f"{driver['driver_id']}_{file_suffix}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    LM, RM, TM, BM = 18*mm, 18*mm, 15*mm, 15*mm
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM

    cp = dict(company_profile) if company_profile else {}
    tc = cp.get("theme_color") or "#1a3a5c"
    try: TH = colors.HexColor(tc)
    except: TH = colors.HexColor("#1a3a5c")
    BG = colors.HexColor("#f4f6f9"); WH = colors.white
    C3 = colors.HexColor("#d1d5db"); C4 = colors.HexColor("#111827")
    C5 = colors.HexColor("#6b7280")

    def F(name, **kw):
        kw.setdefault("fontSize", 8); kw.setdefault("leading", 12)
        return ParagraphStyle(name, **kw)
    def C(t, **kw):
        kw.setdefault("alignment", TA_CENTER)
        return PlParagraph(str(t), F("_C", **kw))
    def R(t, **kw):
        kw.setdefault("alignment", TA_RIGHT)
        return PlParagraph(str(t), F("_R", **kw))

    els = []
    cn = cp.get("company_name", "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING")
    trn = cp.get("trn_no") or "—"

    # ═══ HEADER ═══
    logo = None; LW = 0
    if cp.get("logo_data"):
        try:
            lb = base64.b64decode(cp["logo_data"])
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            f.write(lb); f.close()
            logo = PlImage(f.name, width=50, height=50)
            LW = 50
        except: pass

    cl = [f"<font size=11><b>{cn}</b></font>"]
    addr = cp.get("address") or ""; ph = cp.get("phone_number") or ""; em = cp.get("email") or ""
    parts_l = [x for x in [addr] if x]
    cparts = [x for x in [ph, em, f"TRN: {trn}"] if x and x != "TRN: —"]
    if parts_l or cparts:
        info = " &middot; ".join(parts_l + cparts)
        cl.append(f"<font size=6.5 color='#6b7280'>{info}</font>")
    co_p = PlParagraph("<br/>".join(cl), F("CO", fontSize=11, fontName="Helvetica-Bold", textColor=TH, leading=13))
    if logo:
        lh = PlTable([[logo, Spacer(1, 3*mm), co_p]], colWidths=[LW, 3*mm, W*0.65 - LW - 3*mm])
        lh.setStyle(PlTableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    else:
        lh = co_p
    rh = PlParagraph("<b>STATEMENT<br/>OF ACCOUNT</b>", F("TI", fontSize=14, fontName="Helvetica-Bold", textColor=TH, leading=18, alignment=TA_RIGHT))
    ht = PlTable([[lh, rh]], colWidths=[W*0.65, W*0.35])
    ht.setStyle(PlTableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ht)
    els.append(Spacer(1, 2*mm))
    hr = PlTable([[""]], colWidths=[W], rowHeights=[2])
    hr.setStyle(PlTableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(hr)
    els.append(Spacer(1, 4*mm))

    # ═══ FUND INFO ═══
    finfo = [
        [PlParagraph("<b>Fund</b>", F("_fl", fontSize=8, fontName="Helvetica-Bold", textColor=C4, leading=11)),
         PlParagraph(f"<b>Outstanding Advances — {normalized_month}</b>", F("_fv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=12))],
        [PlParagraph("Employee", F("_l", fontSize=7.5, textColor=C5, leading=10)),
         PlParagraph(f"{driver.get('full_name','-')} ({driver.get('driver_id','-')})", F("_v", fontSize=8.5, textColor=C4, leading=11))],
    ]
    ft = PlTable(finfo, colWidths=[50, W - 50])
    ft.setStyle(PlTableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ft)

    # ═══ SUMMARY CARDS ═══
    els.append(Spacer(1, 3*mm))
    total_amt = sum(float(a.get("amount", 0)) for a in advances)
    total_ded = sum(float(a.get("deducted", 0)) for a in advances)
    total_out = total_amt - total_ded
    cleared_count = sum(1 for a in advances if float(a.get("deducted", 0)) >= float(a.get("amount", 0)))
    uncleared_count = len(advances) - cleared_count
    sdata = [[
        PlParagraph(f"<b>Total Transactions</b><br/><font size=10 color='#1a3a5c'>{len(advances)}</font>", F("_s1", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        PlParagraph(f"<b>Total Advances</b><br/><font size=10 color='#1a7d1a'>AED {format_currency(total_amt)}</font>", F("_s2", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        PlParagraph(f"<b>Total Deducted</b><br/><font size=10 color='#c62828'>AED {format_currency(total_ded)}</font>", F("_s3", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        PlParagraph(f"<b>Outstanding</b><br/><font size=10 color='#e65100'>AED {format_currency(total_out)}</font>", F("_s4", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
    ]]
    st = PlTable(sdata, colWidths=[W/4, W/4, W/4, W/4])
    st.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5),
        ("BACKGROUND",(0,0),(-1,-1),BG),
    ]))
    els.append(st)
    els.append(Spacer(1, 3*mm))

    # ═══ ADVANCES TABLE ═══
    els.append(PlParagraph("<b>Advance / Transaction Details</b>", F("_atitle", fontSize=8, fontName="Helvetica-Bold", textColor=TH, leading=10)))
    els.append(Spacer(1, 2*mm))

    adv_colw = [50, 42, 50, W - 50 - 42 - 50 - 50 - 50, 50, 50]
    adv_hdr = [
        PlParagraph("<b>Date</b>", F("_ah", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        PlParagraph("<b>Amount</b>", F("_ah", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
        PlParagraph("<b>Given By</b>", F("_ah", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        PlParagraph("<b>Details</b>", F("_ah", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        PlParagraph("<b>Deducted</b>", F("_ah", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
        PlParagraph("<b>Remaining</b>", F("_ah", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
    ]
    adv_rows = [adv_hdr]
    t_amt = 0.0; t_ded = 0.0; t_rem = 0.0
    for a in advances:
        amt = float(a.get("amount", 0))
        ded = float(a.get("deducted", 0))
        rem = amt - ded
        t_amt += amt; t_ded += ded; t_rem += rem
        adv_rows.append([
            PlParagraph(str(a.get("entry_date",""))[:10], F("_ad", fontSize=6.5, leading=9)),
            PlParagraph(f"<b>{format_currency(amt)}</b>", F("_aa", fontSize=6.5, fontName="Helvetica-Bold", textColor=C4, alignment=TA_RIGHT, leading=9)),
            PlParagraph(str(a.get("given_by","-")), F("_ag", fontSize=6.5, textColor=C5, leading=9)),
            PlParagraph(str(a.get("details","-")), F("_aDet", fontSize=6.2, textColor=C5, leading=9)),
            PlParagraph(f"<b>{format_currency(ded)}</b>" if ded > 0 else '<font color="#cccccc">—</font>', F("_adr", fontSize=6.5, textColor="#c62828" if ded > 0 else C5, alignment=TA_RIGHT, leading=9)),
            PlParagraph(f"<b>{format_currency(rem)}</b>" if rem > 0 else '<font color="#cccccc">—</font>', F("_arm", fontSize=6.5, textColor="#e65100" if rem > 0 else C5, alignment=TA_RIGHT, leading=9)),
        ])
    # Totals row
    adv_rows.append([
        PlParagraph("<b>Totals</b>", F("_atb", fontSize=7, fontName="Helvetica-Bold", textColor=WH, leading=10)),
        PlParagraph(f"<b>{format_currency(t_amt)}</b>", F("_att", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        PlParagraph("", F("_ax")),
        PlParagraph(f"Cleared: {cleared_count} / Out: {uncleared_count}", F("_ax", fontSize=6.2, textColor=WH, leading=9)),
        PlParagraph(f"<b>{format_currency(t_ded)}</b>", F("_att", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        PlParagraph(f"<b>{format_currency(t_rem)}</b>", F("_att", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
    ])
    atbl = PlTable(adv_rows, colWidths=adv_colw, repeatRows=1)
    atbl.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BACKGROUND",(0,0),(-1,0),TH), ("TEXTCOLOR",(0,0),(-1,0),WH),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),2), ("BOTTOMPADDING",(0,0),(-1,-1),2),
        ("LEFTPADDING",(0,0),(-1,-1),3), ("RIGHTPADDING",(0,0),(-1,-1),3),
        ("BACKGROUND",(0,-1),(-1,-1),TH), ("TEXTCOLOR",(0,-1),(-1,-1),WH),
        ("ROWBACKGROUNDS",(0,1),(-2,-2),[WH, BG]),
    ]))
    els.append(atbl)

    # ═══ SIGNATURES ═══
    els.append(Spacer(1, 8*mm))
    s_sg = ParagraphStyle("SSG", fontSize=9, alignment=TA_CENTER, leading=14)
    s_stamp_path = os.path.join(assets_dir, 'Stamp.png')
    s_sign_path = os.path.join(assets_dir, 'Sign (1).png')
    s_auth_cells = []
    s_auth_cells.append(PlParagraph("_________________________", s_sg))
    if os.path.exists(s_stamp_path):
        s_auth_cells.append(PlImage(s_stamp_path, width=40, height=40))
    if os.path.exists(s_sign_path):
        s_auth_cells.append(PlImage(s_sign_path, width=40, height=40))
    s_auth_cells.append(PlParagraph("<b>Authorized Signatory</b>", s_sg))
    s_auth_cell = PlTable([[c] for c in s_auth_cells], colWidths=[W*0.35])
    s_auth_cell.setStyle(PlTableStyle([
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),0),
        ("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))
    soa_sig = PlTable([[
        s_auth_cell,
        C("", fontSize=4),
        PlParagraph("", s_sg),
    ]], colWidths=[W*0.35, W*0.30, W*0.35])
    soa_sig.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LINEABOVE",(0,0),(0,0),0.5,C5), ("LINEABOVE",(2,0),(2,0),0.5,C5),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
    ]))
    els.append(soa_sig)

    # ═══ FOOTER ═══
    els.append(Spacer(1, 8*mm))
    fh = PlTable([[""]], colWidths=[W], rowHeights=[0.5])
    fh.setStyle(PlTableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(fh)
    els.append(Spacer(1, 2*mm))
    ft_txt = "This is a computer-generated Outstanding Advances Statement."
    els.append(PlParagraph(ft_txt, F("_ft", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=9)))

    doc.build(els)
    return str(output_path)


def generate_owner_fund_pdf(statement_rows, totals, output_dir: str, assets_dir: str, filters=None, company_profile: dict | None = None) -> str:
    import os, tempfile
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors as rl_colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(output_dir) / f"owner-fund-kata_{timestamp}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    filters = filters or {}
    cp = dict(company_profile) if company_profile else {}

    def _active_filter_text():
        parts = []
        if filters.get("date_from") and filters.get("date_to"):
            parts.append(f"Period: {filters['date_from']} to {filters['date_to']}")
        elif filters.get("month"):
            parts.append(f"Period: {filters['month']}")
        if filters.get("movement") and filters["movement"] != "All":
            parts.append(f"Type: {filters['movement']}")
        if filters.get("search"):
            parts.append(f"Search: {filters['search']}")
        return " | ".join(parts)

    filter_text = _active_filter_text()
    table_rows = list(statement_rows) if statement_rows else []

    closing_bal = float(totals.get("closing_balance", totals.get("balance", 0.0)))
    opening_bal = closing_bal - float(totals.get("incoming", 0)) + float(totals.get("outgoing", 0))
    total_in = float(totals["incoming"])
    total_out = float(totals["outgoing"])

    LM, RM, TM, BM = 18*mm, 18*mm, 15*mm, 15*mm
    buf = BytesIO()
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM

    tc = cp.get("theme_color") or "#1a3a5c"
    try: TH = rl_colors.HexColor(tc)
    except: TH = rl_colors.HexColor("#1a3a5c")
    BG = rl_colors.HexColor("#f4f6f9"); WH = rl_colors.white
    C3 = rl_colors.HexColor("#d1d5db"); C4 = rl_colors.HexColor("#111827")
    C5 = rl_colors.HexColor("#6b7280"); CG = rl_colors.HexColor("#1a7d1a")
    CR = rl_colors.HexColor("#c62828"); CO = rl_colors.HexColor("#e65100")

    def F(name, **kw):
        kw.setdefault("fontSize", 8); kw.setdefault("leading", 12)
        return ParagraphStyle(name, **kw)

    def C(t, **kw):
        kw.setdefault("alignment", TA_CENTER)
        return Paragraph(str(t), F("_C", **kw))
    def R(t, **kw):
        kw.setdefault("alignment", TA_RIGHT)
        return Paragraph(str(t), F("_R", **kw))

    els = []
    cn = cp.get("company_name", "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING")
    trn = cp.get("trn_no") or "—"

    # ═══ HEADER (matches customer SOA style) ═══
    logo = None; LW = 0
    if cp.get("logo_data"):
        try:
            lb = base64.b64decode(cp["logo_data"])
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            f.write(lb); f.close()
            logo = Image(f.name, width=50, height=50)
            LW = 50
        except: pass

    cl = [f"<font size=11><b>{cn}</b></font>"]
    addr = cp.get("address") or ""; ph = cp.get("phone_number") or ""; em = cp.get("email") or ""
    parts_l = [x for x in [addr] if x]
    cparts = [x for x in [ph, em, f"TRN: {trn}"] if x and x != "TRN: —"]
    if parts_l or cparts:
        info = " &middot; ".join(parts_l + cparts)
        cl.append(f"<font size=6.5 color='#6b7280'>{info}</font>")
    co_p = Paragraph("<br/>".join(cl), F("CO", fontSize=11, fontName="Helvetica-Bold", textColor=TH, leading=13))
    if logo:
        lh = Table([[logo, Spacer(1, 3*mm), co_p]], colWidths=[LW, 3*mm, W*0.65 - LW - 3*mm])
        lh.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    else:
        lh = co_p
    rh = Paragraph(
        "<b>OWNER FUND<br/>STATEMENT</b>",
        F("TI", fontSize=14, fontName="Helvetica-Bold", textColor=TH, leading=18, alignment=TA_RIGHT))
    ht = Table([[lh, rh]], colWidths=[W*0.65, W*0.35])
    ht.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ht)
    els.append(Spacer(1, 2*mm))
    hr = Table([[""]], colWidths=[W], rowHeights=[2])
    hr.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(hr)
    els.append(Spacer(1, 4*mm))

    # ═══ FUND INFO ═══
    finfo = [
        [Paragraph("<b>Account</b>", F("_fl", fontSize=8, fontName="Helvetica-Bold", textColor=C4, leading=11)),
         Paragraph("<b>Owner Fund</b>", F("_fv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=12))],
    ]
    if filter_text:
        finfo.append([Paragraph("Filter", F("_l", fontSize=7.5, textColor=C5, leading=10)), Paragraph(filter_text, F("_v", fontSize=8.5, textColor=C4, leading=11))])
    ft = Table(finfo, colWidths=[50, W - 50])
    ft.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ft)

    # ═══ SUMMARY CARDS ═══
    els.append(Spacer(1, 3*mm))
    sdata = [[
        Paragraph(f"<b>Opening Balance</b><br/><font size=10 color='#1a3a5c'>AED {opening_bal:,.2f}</font>", F("_s1", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Total Incoming</b><br/><font size=10 color='#1a7d1a'>AED {total_in:,.2f}</font>", F("_s2", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Total Outgoing</b><br/><font size=10 color='#c62828'>AED {total_out:,.2f}</font>", F("_s3", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Closing Balance</b><br/><font size=10 color='#e65100'>AED {closing_bal:,.2f}</font>", F("_s4", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
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

    # ═══ STATEMENT TABLE ═══
    colw = [55, 38, 55, 50, W - 55 - 38 - 55 - 50 - 55 - 55 - 65, 55, 55, 65]
    hdr = [
        Paragraph("<b>Date</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph("<b>Month</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph("<b>Reference</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        Paragraph("<b>Type</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph("<b>Details</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        Paragraph("<b>In (AED)</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
        Paragraph("<b>Out (AED)</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
        Paragraph("<b>Balance (AED)</b>", F("_h", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
    ]
    rws = [hdr]
    # Opening balance row
    rws.append([
        Paragraph("", F("_o", fontSize=6.5, leading=9)), Paragraph("", F("_o")),
        Paragraph("", F("_o")), Paragraph("Opening Balance", F("_ol", fontSize=6.5, textColor=C5, leading=9)),
        Paragraph("", F("_o")), Paragraph("", F("_o")), Paragraph("", F("_o")),
        Paragraph(f"<b>{opening_bal:,.2f}</b>", F("_ob", fontSize=6.5, fontName="Helvetica-Bold", textColor=C4, alignment=TA_RIGHT, leading=9)),
    ])
    for row in table_rows:
        d = str(row.get("entry_date", ""))
        month = d[:7] if d and len(d) >= 7 else ""
        movement = row.get("movement") or "-"
        ref = str(row.get("reference", "")) or "-"
        det = str(row.get("details", "")) or "-"
        inv = float(row.get("incoming", 0))
        outv = float(row.get("outgoing", 0))
        bal_v = float(row.get("balance", 0))
        bal_disp = f"{bal_v:,.2f}"
        bal_c = "#c62828" if bal_v > 0 else "#1a7d1a" if bal_v < 0 else C4

        rws.append([
            Paragraph(d, F("_d", fontSize=6.5, leading=9)),
            Paragraph(f"<font color='{C5}'>{month}</font>" if month else "", F("_m", fontSize=6, textColor=C5, leading=9)),
            Paragraph(ref, F("_r", fontSize=6.5, fontName="Helvetica-Bold", textColor=C4, leading=9)),
            Paragraph(f"<font color=\"{'#1a56db' if movement in ('IN','Incoming') else '#c62828' if movement in ('OUT','Outgoing') else '#e65100'}\">{movement}</font>", F("_t", fontSize=6.5, alignment=TA_CENTER, leading=9)),
            Paragraph(det, F("_det", fontSize=6.2, textColor=C5, leading=9)),
            Paragraph(f"<b>{inv:,.2f}</b>" if inv else '<font color="#cccccc">—</font>', F("_dr", fontSize=6.5, textColor="#1a7d1a" if inv else C5, alignment=TA_RIGHT, leading=9)),
            Paragraph(f"<b>{outv:,.2f}</b>" if outv else '<font color="#cccccc">—</font>', F("_cr", fontSize=6.5, textColor="#c62828" if outv else C5, alignment=TA_RIGHT, leading=9)),
            Paragraph(f"<b>{bal_disp}</b>", F("_bl", fontSize=6.5, fontName="Helvetica-Bold", textColor=bal_c, alignment=TA_RIGHT, leading=9)),
        ])

    # Closing row
    rws.append([
        Paragraph("<b>Closing Balance</b>", F("_cb", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, leading=10)),
        Paragraph("", F("_x", fontSize=6.5, leading=9)),
        Paragraph("", F("_x")),
        Paragraph("", F("_x")),
        Paragraph("", F("_x")),
        Paragraph(f"<b>{total_in:,.2f}</b>" if total_in else '<font color="rgba(255,255,255,0.35)">—</font>', F("_ct", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        Paragraph(f"<b>{total_out:,.2f}</b>" if total_out else '<font color="rgba(255,255,255,0.35)">—</font>', F("_ct", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        Paragraph(f"<b>{closing_bal:,.2f}</b>", F("_ccl", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
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

    # ═══ SIGNATURES ═══
    els.append(Spacer(1, 8*mm))
    s_sg = ParagraphStyle("SSG", fontSize=9, alignment=TA_CENTER, leading=14)
    s_stamp_path = os.path.join(assets_dir, 'Stamp.png')
    s_sign_path = os.path.join(assets_dir, 'Sign (1).png')
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

    # ═══ FOOTER ═══
    els.append(Spacer(1, 8*mm))
    fh = Table([[""]], colWidths=[W], rowHeights=[0.5])
    fh.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(fh)
    els.append(Spacer(1, 2*mm))
    ft_txt = "This is a computer-generated Statement of Account."
    if filter_text:
        ft_txt += f" | {filter_text}"
    els.append(Paragraph(ft_txt, F("_ft", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=9)))

    doc.build(els)
    return str(output_path)


def generate_timesheet_pdf(driver, month_value: str, calendar_days, summary, output_dir: str, assets_dir: str, generated_dir: str, company_profile: dict | None = None) -> str:
    output_path = Path(output_dir) / f"{driver['driver_id']}_{month_value}_timesheet.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    _draw_header(pdf, assets_dir, company_profile)
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
    _draw_timesheet_footer(pdf, driver, summary, assets_dir, generated_dir, company_profile)
    pdf.showPage()
    pdf.save()
    return str(output_path)


def generate_supplier_payment_voucher_pdf(party, voucher, payment, output_dir: str, assets_dir: str, company_profile: dict | None = None) -> str:
    output_path = Path(output_dir) / f"{payment['payment_no']}_payment-voucher.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    _draw_header(pdf, assets_dir, company_profile)
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
    _draw_footer_banner(pdf, assets_dir, True, company_profile)
    pdf.showPage()
    pdf.save()
    return str(output_path)


def generate_cash_supplier_payment_voucher_pdf(party, payment, summary, output_dir: str, assets_dir: str, company_profile: dict | None = None) -> str:
    output_path = Path(output_dir) / f"{payment['payment_no']}_payment-voucher.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    _draw_header(pdf, assets_dir, company_profile)
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
    _draw_footer_banner(pdf, assets_dir, True, company_profile)
    pdf.showPage()
    pdf.save()
    return str(output_path)


def generate_plain_supplier_statement_pdf(party, statement_rows, summary, output_dir: str, title: str = "Supplier Statement", assets_dir: str = "", company_profile: dict | None = None) -> str:
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
        _draw_header(pdf, assets_dir, company_profile)
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
        _draw_footer_banner(pdf, assets_dir, True, company_profile)
        pdf.showPage()

    pdf.save()
    return str(output_path)


def generate_partnership_supplier_statement_pdf(party, period_month: str, asset_rows, summary, output_dir: str, assets_dir: str = "", company_profile: dict | None = None) -> str:
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
        _draw_header(pdf, assets_dir, company_profile)
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
        _draw_footer_banner(pdf, assets_dir, True, company_profile)
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
    company_profile: dict | None = None,
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
        _draw_header(pdf_obj, assets_dir, company_profile)

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
        _draw_footer_banner(pdf, assets_dir, False, company_profile)
        pdf.showPage()

    pdf.save()
    return str(output_path)


def generate_cash_supplier_manual_pdf(sections, output_dir: str, assets_dir: str, company_profile: dict | None = None) -> str:
    output_path = Path(output_dir) / "cash-supplier-desk-guide.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    page_number = 1

    def start_page() -> float:
        _draw_header(pdf, assets_dir, company_profile)
        _draw_title(pdf, "Cash Supplier Desk Guide", "Roman Urdu SOP for portal, kata workflow, aur backup routine")
        pdf.setFillColor(BLUE_SOFT)
        pdf.roundRect(15 * mm, PAGE_HEIGHT - 82 * mm, 180 * mm, 12 * mm, 3 * mm, fill=1, stroke=0)
        pdf.setFillColor(BLUE_DARK)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(20 * mm, PAGE_HEIGHT - 75 * mm, "Is guide ko portal training, month-end review, aur backup checks ke liye use karein.")
        return PAGE_HEIGHT - 92 * mm

    y = start_page()
    for section in sections:
        required_height = 16 * mm + max(1, len(section.get("items", []))) * 10 * mm
        if y - required_height < 18 * mm:
            pdf.setFillColor(MUTED)
            pdf.setFont("Helvetica", 7.2)
            pdf.drawString(16 * mm, 14 * mm, f"Generated on {datetime.now().strftime('%d-%b-%Y %I:%M %p')}")
            pdf.drawRightString(194 * mm, 14 * mm, f"Page {page_number}")
            _draw_footer_banner(pdf, assets_dir, False, company_profile)
            pdf.showPage()
            page_number += 1
            y = start_page()

        pdf.setFillColor(colors.white)
        pdf.roundRect(15 * mm, y - 6 * mm, 180 * mm, 11 * mm, 3 * mm, fill=1, stroke=0)
        pdf.setStrokeColor(LINE)
        pdf.roundRect(15 * mm, y - 6 * mm, 180 * mm, 11 * mm, 3 * mm, fill=0, stroke=1)
        pdf.setFillColor(BLUE_DARK)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(20 * mm, y, section.get("title", "Guide Section"))
        y -= 10 * mm

        for idx, item in enumerate(section.get("items", []), start=1):
            bullet = f"{idx}. "
            wrapped_lines = _wrap_text_lines(pdf, item, "Helvetica", 8.2, 164 * mm, max_lines=4, min_size=7.0)
            line_count = len(wrapped_lines) or 1
            block_height = max(9 * mm, line_count * 4.8 * mm + 3 * mm)
            if y - block_height < 18 * mm:
                pdf.setFillColor(MUTED)
                pdf.setFont("Helvetica", 7.2)
                pdf.drawString(16 * mm, 14 * mm, f"Generated on {datetime.now().strftime('%d-%b-%Y %I:%M %p')}")
                pdf.drawRightString(194 * mm, 14 * mm, f"Page {page_number}")
                _draw_footer_banner(pdf, assets_dir, False, company_profile)
                pdf.showPage()
                page_number += 1
                y = start_page()

            pdf.setFillColor(SOFT)
            pdf.roundRect(19 * mm, y - block_height + 2 * mm, 172 * mm, block_height, 2.5 * mm, fill=1, stroke=0)
            pdf.setFillColor(BLUE)
            pdf.setFont("Helvetica-Bold", 8.4)
            pdf.drawString(24 * mm, y - 3 * mm, bullet)
            pdf.setFillColor(TEXT)
            pdf.setFont("Helvetica", 8.2)
            text_y = y - 3 * mm
            for line in wrapped_lines:
                pdf.drawString(31 * mm, text_y, line)
                text_y -= 4.6 * mm
            y -= block_height + 2.5 * mm
        y -= 2 * mm

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.2)
    pdf.drawString(16 * mm, 14 * mm, f"Generated on {datetime.now().strftime('%d-%b-%Y %I:%M %p')}")
    pdf.drawRightString(194 * mm, 14 * mm, f"Page {page_number}")
    _draw_footer_banner(pdf, assets_dir, False, company_profile)
    pdf.save()
    return str(output_path)


def generate_field_staff_vehicle_report_pdf(vehicle_meta, report_rows, summary, output_dir: str, assets_dir: str, company_profile: dict | None = None) -> str:
    vehicle_no = (vehicle_meta.get("vehicle_no") or vehicle_meta.get("vehicle_id") or "general").strip() or "general"
    safe_vehicle = str(vehicle_no).replace("/", "-").replace(" ", "_")
    output_path = Path(output_dir) / f"{safe_vehicle}_vehicle_report.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    page_number = 1
    rows_per_page = 18
    title = "Partnership Vehicle Expense Report" if vehicle_meta.get("is_partnership") else "Vehicle Expense Report"
    subtitle = f"{vehicle_meta.get('vehicle_no') or '-'} | {vehicle_meta.get('vehicle_id') or '-'} | Full vehicle history"
    table_columns = [
        ("Date", 16, 18, "left"),
        ("Paper No", 34, 23, "left"),
        ("Workshop", 57, 43, "left"),
        ("Work Type", 100, 26, "left"),
        ("Field Staff", 126, 29, "left"),
        ("Amount", 155, 18, "right"),
        ("Status", 173, 21, "right"),
    ]

    def draw_vehicle_header(top: float) -> None:
        pdf.setFillColor(BLUE)
        pdf.roundRect(16 * mm, top, 178 * mm, 8 * mm, 2 * mm, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 8.0)
        for header, x_mm, width_mm, align in table_columns:
            cell_x = x_mm * mm
            cell_w = width_mm * mm
            if align == "right":
                header_text, header_size = _fit_text(pdf, header, "Helvetica-Bold", 8.0, cell_w - 5 * mm, min_size=6.8)
                pdf.setFont("Helvetica-Bold", header_size)
                pdf.drawRightString(cell_x + cell_w - (2.5 * mm), top + 2.45 * mm, header_text)
            else:
                header_text, header_size = _fit_text(pdf, header, "Helvetica-Bold", 8.0, cell_w - 5 * mm, min_size=6.8)
                pdf.setFont("Helvetica-Bold", header_size)
                pdf.drawString(cell_x + 2.5 * mm, top + 2.45 * mm, header_text)

    def draw_vehicle_row(row_y: float, row, *, striped: bool) -> None:
        if striped:
            pdf.setFillColor(SOFT)
            pdf.roundRect(16 * mm, row_y - 2.6 * mm, 178 * mm, 6.6 * mm, 1.8 * mm, fill=1, stroke=0)
        values = [
            format_date_label(row.get("paper_date")),
            row.get("paper_no") or "-",
            row.get("workshop_name") or "-",
            row.get("work_type") or "-",
            row.get("technician_name") or "-",
            format_currency(float(row.get("total_amount") or 0.0)),
            f"{row.get('review_status') or '-'} / {row.get('payment_status') or '-'}",
        ]
        fonts = [
            ("Helvetica", 7.4, 6.2),
            ("Helvetica-Bold", 7.3, 6.1),
            ("Helvetica", 7.0, 5.8),
            ("Helvetica", 7.0, 5.8),
            ("Helvetica", 7.0, 5.8),
            ("Helvetica-Bold", 7.4, 6.1),
            ("Helvetica", 6.7, 5.6),
        ]
        pdf.setFillColor(TEXT)
        for (value, (font_name, font_size, min_size), (_, x_mm, width_mm, align)) in zip(values, fonts, table_columns):
            cell_x = x_mm * mm
            cell_w = width_mm * mm
            text, size = _fit_text(pdf, str(value or "-"), font_name, font_size, cell_w - 5 * mm, min_size=min_size)
            pdf.setFont(font_name, size)
            if align == "right":
                pdf.drawRightString(cell_x + cell_w - (2.5 * mm), row_y, text)
            else:
                pdf.drawString(cell_x + 2.5 * mm, row_y, text)

    def draw_page(page_rows, page_no: int, total_pages: int):
        _draw_header(pdf, assets_dir, company_profile)
        _draw_title(pdf, title, subtitle)

        summary_x = 15 * mm
        summary_y = PAGE_HEIGHT - 104 * mm
        summary_w = 180 * mm
        summary_h = 24 * mm
        pdf.setFillColor(colors.white)
        pdf.roundRect(summary_x, summary_y, summary_w, summary_h, 4 * mm, fill=1, stroke=0)
        pdf.setStrokeColor(LINE)
        pdf.roundRect(summary_x, summary_y, summary_w, summary_h, 4 * mm, fill=0, stroke=1)
        pdf.setFillColor(BLUE_SOFT)
        pdf.roundRect(summary_x, summary_y + summary_h - 8 * mm, summary_w, 8 * mm, 4 * mm, fill=1, stroke=0)
        pdf.setFillColor(BLUE_DARK)
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.drawString(summary_x + 5 * mm, summary_y + summary_h - 5.2 * mm, "VEHICLE SUMMARY")

        _draw_label_value_row(pdf, summary_x + 5 * mm, summary_y + 10.5 * mm, 22 * mm, 32 * mm, "Vehicle No", vehicle_meta.get("vehicle_no") or "-")
        _draw_label_value_row(pdf, summary_x + 65 * mm, summary_y + 10.5 * mm, 20 * mm, 32 * mm, "Vehicle ID", vehicle_meta.get("vehicle_id") or "-")
        _draw_label_value_row(pdf, summary_x + 120 * mm, summary_y + 10.5 * mm, 22 * mm, 32 * mm, "Mode", vehicle_meta.get("ownership_mode") or "Standard")

        metrics_y = PAGE_HEIGHT - 136 * mm
        _draw_stat_box(pdf, 15 * mm, metrics_y, 42 * mm, 14 * mm, "TOTAL PAPERS", str(int(summary.get("paper_count") or 0)))
        _draw_stat_box(pdf, 61 * mm, metrics_y, 42 * mm, 14 * mm, "TOTAL AMOUNT", f"AED {format_currency(float(summary.get('total_amount') or 0.0))}")
        _draw_stat_box(pdf, 107 * mm, metrics_y, 42 * mm, 14 * mm, "APPROVED", f"AED {format_currency(float(summary.get('approved_amount') or 0.0))}", fill_color=SOFT)
        _draw_stat_box(pdf, 153 * mm, metrics_y, 42 * mm, 14 * mm, "PAID", f"AED {format_currency(float(summary.get('paid_amount') or 0.0))}", fill_color=BLUE, text_color=colors.white, border_color=BLUE)
        _draw_compact_meta_row(pdf, 16 * mm, metrics_y - 4.5 * mm, 74 * mm, "Balance Due", f"AED {format_currency(float(summary.get('balance_due') or 0.0))}")
        if vehicle_meta.get("is_partnership"):
            _draw_compact_meta_row(
                pdf,
                104 * mm,
                metrics_y - 4.5 * mm,
                90 * mm,
                "Split",
                f"Company AED {format_currency(float(summary.get('company_share_amount') or 0.0))} / Partner AED {format_currency(float(summary.get('partner_share_amount') or 0.0))}",
            )

        table_top = PAGE_HEIGHT - 158 * mm
        draw_vehicle_header(table_top)

        y = table_top - 7 * mm
        row_height = 8 * mm
        for index, row in enumerate(page_rows):
            draw_vehicle_row(y, row, striped=index % 2 == 0)
            y -= row_height

        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 7.0)
        pdf.drawString(16 * mm, 14 * mm, f"Generated on {datetime.now().strftime('%d-%b-%Y %I:%M %p')}")
        pdf.drawRightString(194 * mm, 14 * mm, f"Page {page_no} / {total_pages}")
        _draw_footer_banner(pdf, assets_dir, False, company_profile)
        pdf.showPage()

    pages = [report_rows[i : i + rows_per_page] for i in range(0, len(report_rows), rows_per_page)] or [[]]
    total_pages = len(pages)
    for index, page_rows in enumerate(pages, start=1):
        draw_page(page_rows, index, total_pages)
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
    _draw_header(pdf, assets_dir, company_profile)
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
        company_profile.get("company_name", "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING"),
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


def _draw_invoice_header(pdf, company_profile, title_text='', logo_size=14*mm):
    company = company_profile or {}
    c_name = company.get('company_name', 'CURRENT LINK TRANSPORT AND GENERAL CONTRACTING')
    c_addr = company.get('address', '')
    c_ph = company.get('phone_number', '')
    c_em = company.get('email', '')
    c_trn = company.get('trn_no', '')

    left_x = 16 * mm
    top_y = PAGE_HEIGHT - 38 * mm
    logo_data = company.get('logo_data')

    # Logo
    logo_x = left_x
    if logo_data:
        try:
            lb = base64.b64decode(logo_data)
            logo_img = ImageReader(BytesIO(lb))
            pdf.drawImage(logo_img, left_x, top_y - logo_size, width=logo_size, height=logo_size, preserveAspectRatio=True, mask='auto')
            logo_x = left_x + logo_size + 4 * mm
        except Exception:
            pass

    # Company name
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(logo_x, top_y, c_name)

    # Address
    pdf.setFillColor(MUTED)
    pdf.setFont('Helvetica', 7)
    ci_y = top_y - 5 * mm
    if c_addr:
        pdf.drawString(logo_x, ci_y, c_addr)
        ci_y -= 4 * mm

    # Phone + Email
    contact_parts = []
    if c_ph: contact_parts.append('Phone: {}'.format(c_ph))
    if c_em: contact_parts.append('Email: {}'.format(c_em))
    if contact_parts:
        pdf.drawString(logo_x, ci_y, ' &middot; '.join(contact_parts))
        ci_y -= 4 * mm
    else:
        ci_y -= 2 * mm

    # TRN
    if c_trn:
        pdf.setFillColor(BLUE_DARK)
        pdf.setFont('Helvetica-Bold', 7)
        pdf.drawString(logo_x, ci_y, 'TRN: {}'.format(c_trn))

    # Right side title
    if title_text:
        pdf.setFillColor(BLUE_DARK)
        pdf.setFont('Helvetica-Bold', 14)
        pdf.drawRightString(PAGE_WIDTH - 16 * mm, top_y, title_text)

    # Theme hr below
    hr_y = top_y - 28 * mm
    pdf.setFillColor(BLUE)
    pdf.rect(16 * mm, hr_y, PAGE_WIDTH - 32 * mm, 1.5 * mm, fill=1, stroke=0)


def _draw_header(pdf: canvas.Canvas, assets_dir: str = "", company_profile: dict | None = None) -> None:
    company = company_profile or {}

    header_x = 15 * mm
    header_y = PAGE_HEIGHT - 50 * mm
    header_w = 180 * mm
    header_h = 44 * mm

    logo_data = company.get("logo_data")
    logo_type = company.get("logo_type")

    pdf.setFillColor(colors.white)
    pdf.roundRect(header_x, header_y, header_w, header_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(header_x, header_y, header_w, header_h, 4 * mm, fill=0, stroke=1)

    text_x = header_x + 5 * mm
    text_area_w = header_w - 10 * mm
    if logo_data and logo_type:
        try:
            logo_binary = base64.b64decode(logo_data)
            logo_img = ImageReader(BytesIO(logo_binary))
            target = 34 * mm
            pdf.drawImage(
                logo_img,
                header_x + 3 * mm,
                header_y + (header_h - target) / 2,
                width=target, height=target,
                preserveAspectRatio=True, mask="auto",
            )
            text_x = header_x + 42 * mm
            text_area_w = header_w - 48 * mm
        except Exception:
            pass

    cy = header_y + header_h / 2

    c_name = company.get("company_name", "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING")
    pdf.setFillColor(BLUE_DARK)
    cname_text, cname_size = _fit_text(pdf, c_name, "Helvetica-Bold", 13, text_area_w, min_size=9)
    pdf.setFont("Helvetica-Bold", cname_size)
    pdf.drawString(text_x, cy + 10 * mm, cname_text)

    addr = company.get("address") or ""
    if addr:
        pdf.setFillColor(MUTED)
        addr_text, addr_size = _fit_text(pdf, addr, "Helvetica", 7.5, text_area_w, min_size=5.5)
        pdf.setFont("Helvetica", addr_size)
        pdf.drawString(text_x, cy + 1 * mm, addr_text)

    trn = company.get("trn_no") or ""
    phone = company.get("phone_number") or ""
    email = company.get("email") or ""
    left_parts = [f"TRN: {trn}"] if trn else []
    right_parts = [p for p in [phone, email] if p]
    if left_parts:
        pdf.setFillColor(BLUE_DARK)
        ltext, lsize = _fit_text(pdf, left_parts[0], "Helvetica-Bold", 7.5, text_area_w * 0.4, min_size=5.5)
        pdf.setFont("Helvetica-Bold", lsize)
        pdf.drawString(text_x, cy - 8 * mm, ltext)
        offset = pdf.stringWidth(ltext, "Helvetica-Bold", lsize) + 6 * mm
    else:
        offset = 0
    if right_parts:
        pdf.setFillColor(BLUE_DARK)
        contact_str = " | ".join(right_parts)
        ctext, csize = _fit_text(pdf, contact_str, "Helvetica", 7.5, text_area_w * 0.5 - offset, min_size=5.5)
        pdf.setFont("Helvetica", csize)
        pdf.drawString(text_x + offset, cy - 8 * mm, ctext)

    pdf.setFillColor(BLUE)
    pdf.rect(header_x + 4 * mm, header_y + 4 * mm, header_w - 8 * mm, 1.5 * mm, fill=1, stroke=0)


def _draw_title(pdf: canvas.Canvas, title: str, subtitle: str = "") -> None:
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 62 * mm, title)
    if subtitle:
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 7.5)
        pdf.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 67 * mm, subtitle)


def _draw_salary_summary(pdf: canvas.Canvas, driver, salary_row, slip_payload) -> None:
    ot_month = salary_row["ot_month"] if "ot_month" in salary_row.keys() and salary_row["ot_month"] else previous_month_value(salary_row["salary_month"])
    summary_x = 16 * mm
    summary_y = 181 * mm
    summary_w = 116 * mm
    summary_h = 47 * mm
    _v = slip_payload.get("_vehicle_no") or ""

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
        ("Vehicle Number", driver.get("vehicle_no") or driver.get("_vehicle_no_fb") or _v or "-"),
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
    pdf.drawString(x + 38 * mm, y + h + 6.5 * mm, "Earnings & Deductions")

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
    ot_type = salary_row.get("ot_type") or "hours"
    ot_qty_label = f"OT Extra Trips" if ot_type == "trips" else f"OT Hours ({format_month_label(ot_month)})"
    ot_qty = float(salary_row.get("ot_trips") or 0) if ot_type == "trips" else float(salary_row["ot_hours"])
    earnings = [
        ("Basic Salary", float(salary_row["basic_salary"])),
        (ot_qty_label, ot_qty),
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


def _draw_salary_footer(pdf: canvas.Canvas, driver, slip_payload, assets_dir: str, generated_dir: str, payment_rows, company_profile: dict | None = None) -> None:
    # ═══ PHOTO CARD ═══
    card_x = 16 * mm
    card_y = 38 * mm
    card_w = 44 * mm
    card_h = 33 * mm
    pdf.setFillColor(SOFT)
    pdf.roundRect(card_x, card_y, card_w, card_h, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(card_x, card_y, card_w, card_h, 4 * mm, fill=0, stroke=1)
    _dl = {"photo_data": slip_payload.get("_photo_data") or "", "photo_name": slip_payload.get("_photo_name") or ""}
    if not _draw_driver_photo(pdf, driver, generated_dir, card_x + 2.5 * mm, card_y + 2.5 * mm, card_w - 5 * mm, card_h - 5 * mm, _dl):
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawCentredString(card_x + card_w / 2, card_y + card_h / 2, "NO PHOTO")

    # ═══ ACKNOWLEDGMENT CARD ═══
    sign_x = 66 * mm
    sign_y = 38 * mm
    sign_w = 129 * mm
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
    pdf.line(sign_x + 22 * mm, sign_y + 14.6 * mm, sign_x + 100 * mm, sign_y + 14.6 * mm)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.5)
    pdf.drawString(sign_x + 4 * mm, sign_y + 2.5 * mm, f"System Generated on {datetime.now().strftime('%d-%b-%Y %I:%M %p')}")
    _draw_paid_stamp(pdf, sign_x + 80 * mm, sign_y + 7.5 * mm)

    # ═══ DISCLAIMER ═══
    _draw_footer_banner(pdf, assets_dir, True, company_profile)


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


def _draw_timesheet_footer(pdf: canvas.Canvas, driver, summary, assets_dir: str, generated_dir: str, company_profile: dict | None = None) -> None:
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
    _draw_footer_banner(pdf, assets_dir, True, company_profile)


def _draw_driver_photo(pdf: canvas.Canvas, driver, generated_dir: str, x: float, y: float, w: float, h: float, _dl: dict | None = None) -> bool:
    _dl = _dl or {}
    raw = driver.get("photo_data") or _dl.get("photo_data") or ""
    if raw:
        try:
            image = ImageReader(BytesIO(base64.b64decode(raw)))
            pdf.drawImage(image, x, y, width=w, height=h, preserveAspectRatio=True, mask="auto")
            return True
        except Exception:
            pass

    raw = driver.get("photo_name") or _dl.get("photo_name") or ""
    if raw:
        photo_path = Path(generated_dir) / raw
        if photo_path.exists():
            try:
                pdf.drawImage(str(photo_path), x, y, width=w, height=h, preserveAspectRatio=True, mask="auto")
                return True
            except Exception:
                pass
    return False


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
    start_x = 16 * mm
    y = PAGE_HEIGHT - 164 * mm
    gap = 4 * mm
    box_w = (178 * mm - gap * 3) / 4
    box_h = 18 * mm

    _draw_stat_box(pdf, start_x, y, box_w, box_h, "PREVIOUS BALANCE", f"AED {summary['previous_balance']}",
                    fill_color=colors.white, text_color=BLUE, border_color=LINE)
    _draw_stat_box(pdf, start_x + (box_w + gap), y, box_w, box_h, "SALARY + OT", f"AED {summary['salary']}",
                    fill_color=colors.white, text_color=GREEN, border_color=LINE)
    _draw_stat_box(pdf, start_x + 2 * (box_w + gap), y, box_w, box_h, "RECEIVED", f"AED {summary['received_total']}",
                    fill_color=colors.white, text_color=ORANGE, border_color=LINE)
    _draw_stat_box(pdf, start_x + 3 * (box_w + gap), y, box_w, box_h, "REMAINING SALARY", f"AED {summary['remaining_salary']}",
                    fill_color=BLUE, text_color=colors.white, border_color=BLUE)


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
        ["Date", "Type", "Reference", "Details", "Incoming", "Outgoing", "Balance"],
        [18, 30, 44, 70, 118, 140, 162],
    )

    def _entry_type(sg):
        return {0: "Salary", 1: "Advance", 2: "Deduction", 3: "Payment", 4: "Closing"}.get(sg, "")

    y = top - 7 * mm
    row_height = 7.8 * mm
    running = 0.0
    for index, item in enumerate(entries[:20]):
        if index % 2 == 0:
            pdf.setFillColor(SOFT)
            pdf.roundRect(16 * mm, y - 3.1 * mm, 178 * mm, 7.2 * mm, 1.8 * mm, fill=1, stroke=0)
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica", 8.4)
        pdf.drawString(18 * mm, y, format_date_label(item["date"]))

        etype = _entry_type(item.get("sort_group", 1))
        pdf.setFont("Helvetica", 7.6)
        pdf.drawString(30 * mm, y, etype)

        ref_text, ref_size = _fit_text(pdf, str(item.get("paid_by", "-")), "Helvetica", 7.4, 22 * mm, min_size=6.4)
        pdf.setFont("Helvetica", ref_size)
        pdf.drawString(44 * mm, y, ref_text)

        detail_text, detail_size = _fit_text(pdf, str(item.get("reason", "-")), "Helvetica", 7.8, 44 * mm, min_size=6.6)
        pdf.setFont("Helvetica", detail_size)
        pdf.drawString(70 * mm, y, detail_text)

        amount = float(item.get("amount", 0.0))
        sg = item.get("sort_group", 1)
        is_incoming = sg == 0
        incoming = amount if is_incoming else 0.0
        outgoing = amount if not is_incoming and sg >= 1 else 0.0
        running = max(running + incoming - outgoing, 0.0) if sg >= 0 else running + incoming

        pdf.setFont("Helvetica-Bold", 8.4)
        if incoming > 0:
            pdf.setFillColor(GREEN)
            pdf.drawRightString(140 * mm, y, format_currency(incoming))
        else:
            pdf.setFillColor(ORANGE)
            pdf.drawRightString(162 * mm, y, format_currency(outgoing))

        pdf.setFillColor(BLUE_DARK)
        pdf.drawRightString(194 * mm, y, format_currency(item.get("balance_after", running)))
        y -= row_height
        if y < 44 * mm:
            break
    if entries:
        pdf.setStrokeColor(LINE)
        pdf.line(16 * mm, y + 2 * mm, 194 * mm, y + 2 * mm)
        total_in = sum(float(item["amount"]) for item in entries if item.get("sort_group") == 0)
        total_out = sum(float(item["amount"]) for item in entries if item.get("sort_group", 1) >= 1)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.setFillColor(BLUE_DARK)
        pdf.drawString(18 * mm, y - 3 * mm, "Totals")
        pdf.setFillColor(GREEN)
        pdf.drawRightString(140 * mm, y - 3 * mm, format_currency(total_in))
        pdf.setFillColor(ORANGE)
        pdf.drawRightString(162 * mm, y - 3 * mm, format_currency(total_out))
        pdf.setFillColor(BLUE_DARK)
        pdf.drawRightString(194 * mm, y - 3 * mm, format_currency(max(total_in - total_out, 0.0)))


def _draw_footer_banner(pdf: canvas.Canvas, assets_dir: str = "", show_top_rule: bool = True, company_profile: dict | None = None) -> None:
    company = company_profile or {}
    footer_w = 180 * mm

    if show_top_rule:
        pdf.setFillColor(ORANGE)
        pdf.rect(15 * mm, 30 * mm, footer_w, 1.2 * mm, fill=1, stroke=0)

    pdf.setFillColor(colors.white)
    pdf.roundRect(15 * mm, 8 * mm, footer_w, 22 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(15 * mm, 8 * mm, footer_w, 22 * mm, 4 * mm, fill=0, stroke=1)

    c_name = (company.get("company_name", "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING")).upper()
    cname_text, cname_size = _fit_text(pdf, c_name, "Helvetica-Bold", 8, footer_w - 10 * mm, min_size=6)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", cname_size)
    pdf.drawCentredString(PAGE_WIDTH / 2, 22.5 * mm, cname_text)

    addr = company.get("address") or ""
    if addr:
        addr_text, addr_size = _fit_text(pdf, addr, "Helvetica", 6.5, footer_w - 10 * mm, min_size=5)
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", addr_size)
        pdf.drawCentredString(PAGE_WIDTH / 2, 16.5 * mm, addr_text)

    parts = [p for p in [company.get("phone_number"), company.get("email")] if p]
    contact_str = "  |  ".join(parts) if parts else ""
    if contact_str:
        contact_text, contact_size = _fit_text(pdf, contact_str, "Helvetica", 6.5, footer_w - 10 * mm, min_size=5)
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", contact_size)
        pdf.drawCentredString(PAGE_WIDTH / 2, 11.5 * mm, contact_text)


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


def _draw_compact_meta_row(pdf: canvas.Canvas, x: float, y: float, total_width: float, label: str, value: str) -> None:
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.9)
    label_text = f"{label}:"
    pdf.drawString(x, y, label_text)
    label_width = pdf.stringWidth(label_text, "Helvetica", 6.9)
    available_width = max(total_width - label_width - (2.6 * mm), 14 * mm)
    pdf.setFillColor(TEXT)
    text, size = _fit_text(pdf, str(value or "-"), "Helvetica-Bold", 7.0, available_width, min_size=5.8)
    pdf.setFont("Helvetica-Bold", size)
    pdf.drawRightString(x + total_width, y, text)


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


def generate_field_staff_advances_pdf(staff, advances, jobs_data, papers_data, total, filter_month, date_from, date_to, output_dir, assets_dir, company_profile=None, base_url=""):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors as rl_colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    import os, tempfile

    os.makedirs(output_dir, exist_ok=True)
    period_tag = filter_month or (f"{date_from} to {date_to}" if date_from and date_to else date_from or date_to or "all")
    filename = f"staff_advances_{staff['staff_id']}_{period_tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path = os.path.join(output_dir, filename)

    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)
    W = A4[0] - 30*mm
    els = []
    WH = rl_colors.white
    TH = rl_colors.HexColor("#1C568B")
    C4 = rl_colors.HexColor("#1F2937")
    C5 = rl_colors.HexColor("#667A95")
    BG = rl_colors.HexColor("#F6F9FD")

    def F(name, fontSize=8, fontName="Helvetica", textColor=C4, alignment=TA_LEFT, leading=None):
        return ParagraphStyle(name, fontSize=fontSize, fontName=fontName, textColor=textColor, alignment=alignment, leading=leading or fontSize*1.3)

    cp = dict(company_profile) if company_profile else {}
    logo = None; LW = 0
    if cp.get("logo_data"):
        try:
            lb = base64.b64decode(cp["logo_data"])
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            f.write(lb); f.close()
            logo = Image(f.name, width=50, height=50)
            LW = 50
        except Exception:
            pass
    cn = cp.get("company_name") or staff["full_name"] if staff else "Field Staff"
    trn = f"TRN: {cp['trn_no']}" if cp.get("trn_no") else ""
    addr = cp.get("address") or ""
    ph = cp.get("phone_number") or ""

    co_p = Paragraph(
        f"<b>{cn}</b><br/>"
        f"<font size=7 color='#667A95'>{addr}<br/>{ph}{' | '+trn if trn else ''}</font>",
        F("_co", fontSize=8.5, fontName="Helvetica-Bold", textColor=C4, leading=10)
    )
    lh = Table([[logo, Spacer(1, 3*mm), co_p]], colWidths=[LW, 3*mm, W*0.65 - LW - 3*mm]) if logo else Table([[co_p]], colWidths=[W*0.65])
    lh.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))

    period_label = filter_month or (f"{date_from} to {date_to}" if date_from and date_to else date_from or date_to or "All Time")
    title = f"Cash Given Statement" + (f" — {period_label}" if period_label != "All Time" else "")
    rh = Paragraph(f"<b>{title}</b><br/><font size=7 color='#667A95'>Staff: {staff['full_name']} ({staff['staff_id']})</font>", F("_rh", fontSize=10, fontName="Helvetica-Bold", textColor=TH, alignment=TA_RIGHT, leading=12))
    ht = Table([[lh, rh]], colWidths=[W*0.65, W*0.35])
    ht.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ht)
    els.append(Spacer(1, 2*mm))
    hr = Table([[""]], colWidths=[W], rowHeights=[0.5])
    hr.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(hr)
    els.append(Spacer(1, 4*mm))

    # Summary
    total_given = sum(a["amount"] for a in advances) if advances else 0
    sdata = [[
        Paragraph(f"<b>Total Entries</b><br/><font size=10 color='#1a3a5c'>{len(advances)}</font>", F("_s1", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Total Given</b><br/><font size=10 color='#16a34a'>AED {total_given:,.2f}</font>", F("_s2", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Period</b><br/><font size=10 color='#1a3a5c'>{period_label}</font>", F("_s3", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
    ]]
    st = Table(sdata, colWidths=[W/3, W/3, W/3])
    st.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BOX",(0,0),(-1,-1),0.5, rl_colors.HexColor("#D7E2EF")),
        ("INNERGRID",(0,0),(-1,-1),0.3, rl_colors.HexColor("#D7E2EF")),
        ("TOPPADDING",(0,0),(-1,-1),8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("BACKGROUND",(0,0),(-1,-1), rl_colors.HexColor("#F6F9FD")),
    ]))
    els.append(st)
    els.append(Spacer(1, 4*mm))

    # Table header
    colw = [40, 60, 45, 40, W - 40 - 60 - 45 - 40 - 55, 55]
    hdr = [
        Paragraph("<b>Date</b>", F("_h", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph("<b>Reference</b>", F("_h", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        Paragraph("<b>Source</b>", F("_h", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph("<b>Given By</b>", F("_h", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph("<b>Notes</b>", F("_h", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        Paragraph("<b>Amount</b>", F("_h", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
    ]
    rws = [hdr]
    for a in advances:
        d = str(a.get("entry_date", ""))
        ref = a.get("advance_no", "")
        src = a.get("funding_source", "")
        gb = a.get("reference", "")
        nt = a.get("notes", "")
        amt = float(a.get("amount", 0))
        rws.append([
            Paragraph(d, F("_d", fontSize=6.5, leading=9)),
            Paragraph(ref, F("_r", fontSize=6.5, fontName="Helvetica-Bold", textColor=C4, leading=9)),
            Paragraph(src, F("_s", fontSize=6.5, alignment=TA_CENTER, leading=9)),
            Paragraph(gb, F("_g", fontSize=6.5, textColor=C5, leading=9)),
            Paragraph(nt[:60] if nt else "-", F("_n", fontSize=6.2, textColor=C5, leading=9)),
            Paragraph(f"<b>{amt:,.2f}</b>", F("_a", fontSize=6.5, textColor=rl_colors.HexColor("#16a34a"), alignment=TA_RIGHT, leading=9)),
        ])
    # Total row
    rws.append([
        Paragraph("<b>Total</b>", F("_tb", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, leading=10)),
        Paragraph("", F("_x")), Paragraph("", F("_x")), Paragraph("", F("_x")), Paragraph("", F("_x")),
        Paragraph(f"<b>{total_given:,.2f}</b>", F("_tt", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
    ])
    it = Table(rws, colWidths=colw, repeatRows=1)
    it.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BACKGROUND",(0,0),(-1,0),TH), ("TEXTCOLOR",(0,0),(-1,0),WH),
        ("BOX",(0,0),(-1,-1),0.5, rl_colors.HexColor("#D7E2EF")),
        ("INNERGRID",(0,0),(-1,-1),0.3, rl_colors.HexColor("#D7E2EF")),
        ("TOPPADDING",(0,0),(-1,-1),2), ("BOTTOMPADDING",(0,0),(-1,-1),2),
        ("LEFTPADDING",(0,0),(-1,-1),3), ("RIGHTPADDING",(0,0),(-1,-1),3),
        ("BACKGROUND",(0,-1),(-1,-1),TH), ("TEXTCOLOR",(0,-1),(-1,-1),WH),
        ("ROWBACKGROUNDS",(0,1),(-2,-2),[WH, BG]),
    ]))
    els.append(it)

    # Footer
    els.append(Spacer(1, 10*mm))
    s_sg = ParagraphStyle("SSG", fontSize=9, alignment=TA_CENTER, leading=14)
    s_stamp_path = os.path.join(assets_dir, 'Stamp.png')
    s_sign_path = os.path.join(assets_dir, 'Sign (1).png')
    s_auth_cells = []
    s_auth_cells.append(Paragraph("_________________________", s_sg))
    if os.path.exists(s_stamp_path):
        try:
            s_auth_cells.append(Image(s_stamp_path, width=40, height=40))
        except Exception:
            s_auth_cells.append(Paragraph("<br/>", s_sg))
    else:
        s_auth_cells.append(Paragraph("<br/>", s_sg))
    s_auth_cells.append(Paragraph("<b>Authorised Signatory</b>", s_sg))
    s_auth_cells.append(Paragraph(f"<font size=6 color='#667A95'>Generated: {datetime.now().strftime('%d-%b-%Y %H:%M')}</font>",
                                  ParagraphStyle("SSG2", fontSize=6, alignment=TA_CENTER, leading=8)))
    s_auth_cell = Table([[c] for c in s_auth_cells], colWidths=[W*0.35])
    s_auth_cell.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                                     ("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1)]))
    if os.path.exists(s_sign_path):
        try:
            els.append(Table([[
                Paragraph(f"<font size=7 color='#667A95'>Prepared by: {os.getlogin()}</font>",
                          ParagraphStyle("PREP", fontSize=7, alignment=TA_LEFT, leading=9)),
                s_auth_cell,
                Image(s_sign_path, width=55, height=20),
            ]], colWidths=[W*0.35, W*0.30, W*0.35]))
        except Exception:
            els.append(s_auth_cell)
    else:
        els.append(s_auth_cell)

    doc.build(els)
    return path


def _generate_employee_list_pdf(employees, output_dir: str, company_profile: dict | None = None) -> str:
    from datetime import date
    output_path = Path(output_dir) / f"employees_{date.today().isoformat()}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    company = company_profile or {}
    cn = company.get("company_name", "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING")

    doc = SimpleDocTemplate(
        str(output_path), pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=20*mm, bottomMargin=15*mm,
    )

    W = 180*mm
    styles = getSampleStyleSheet()
    styleN = styles["Normal"]

    els = []

    els.append(Paragraph(
        f"<font size=14><b>{cn}</b></font>",
        ParagraphStyle("Title", fontSize=14, alignment=TA_CENTER, spaceAfter=2*mm),
    ))
    els.append(Paragraph(
        "<font size=10>Employee Directory</font>",
        ParagraphStyle("Sub", fontSize=10, alignment=TA_CENTER, spaceAfter=5*mm),
    ))
    els.append(Paragraph(
        f"<font size=8 color='#666'>Generated on: {date.today().isoformat()} &mdash; Total: {len(employees)} employees</font>",
        ParagraphStyle("Meta", fontSize=8, alignment=TA_CENTER, spaceAfter=8*mm),
    ))

    data = [["#", "ID", "Name", "Phone", "Type", "Dept", "Designation", "Join Date", "Salary", "Status"]]
    for i, emp in enumerate(employees, 1):
        data.append([
            str(i),
            emp["employee_id"],
            emp["full_name"],
            emp["phone_number"] or "-",
            emp["employee_type"],
            emp["department"],
            emp["designation"],
            emp["join_date"],
            f'{emp["basic_salary"] or 0:,.0f}',
            emp["status"] or "",
        ])

    col_w = [8*mm, 22*mm, 36*mm, 24*mm, 18*mm, 20*mm, 22*mm, 18*mm, 18*mm, 16*mm]
    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), Color(0.1, 0.23, 0.36)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (8, 0), (8, -1), "RIGHT"),
        ("ALIGN", (7, 0), (7, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, Color(0.85, 0.88, 0.92)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, Color(0.96, 0.97, 0.99)]),
        ("TOPPADDING", (0, 0), (-1, -1), 3*mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3*mm),
    ]))
    els.append(t)

    doc.build(els)
    return str(output_path)

def generate_field_staff_jobs_pdf(staff, jobs, total_amount, filter_month, date_from, date_to, output_dir, assets_dir, company_profile=None, base_url=""):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors as rl_colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, Flowable
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    import os, tempfile

    ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
    def _embed_attachment_image(b64data, att_type, tmp_root):
        try:
            raw = base64.b64decode(b64data or "")
            if not raw:
                return None
            ext = ext_map.get((att_type or "").lower(), ".png")
            tmp_img = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=tmp_root)
            tmp_img.write(raw)
            tmp_img.close()
            return tmp_img.name
        except Exception:
            return None

    class _LinkImage(Flowable):
        def __init__(self, path, url, width=22, height=22):
            super().__init__()
            self.path, self.url = path, url
            self.width, self.height = width, height
        def draw(self):
            from reportlab.lib.utils import ImageReader
            try:
                self.canv.drawImage(self.path, 0, 0, width=self.width, height=self.height,
                                    preserveAspectRatio=True, anchor='c', mask='auto')
            except Exception:
                pass
            self.canv.linkURL(self.url, (0, 0, self.width, self.height), relative=1, thickness=0)

    os.makedirs(output_dir, exist_ok=True)
    period_tag = filter_month or (f"{date_from}_to_{date_to}" if date_from and date_to else date_from or date_to or "all")
    filename = f"staff_jobs_{staff['staff_id']}_{period_tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path = os.path.join(output_dir, filename)

    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)
    W = A4[0] - 30*mm
    els = []
    WH = rl_colors.white
    TH = rl_colors.HexColor("#1C568B")
    C4 = rl_colors.HexColor("#1F2937")
    C5 = rl_colors.HexColor("#667A95")
    BG = rl_colors.HexColor("#F6F9FD")

    def F(name, fontSize=8, fontName="Helvetica", textColor=C4, alignment=TA_LEFT, leading=None):
        return ParagraphStyle(name, fontSize=fontSize, fontName=fontName, textColor=textColor, alignment=alignment, leading=leading or fontSize*1.3)

    cp = dict(company_profile) if company_profile else {}
    logo = None; LW = 0
    if cp.get("logo_data"):
        try:
            lb = base64.b64decode(cp["logo_data"])
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            f.write(lb); f.close()
            logo = Image(f.name, width=50, height=50)
            LW = 50
        except Exception:
            pass
    cn = cp.get("company_name") or staff["full_name"] if staff else "Field Staff"
    trn = f"TRN: {cp['trn_no']}" if cp.get("trn_no") else ""
    addr = cp.get("address") or ""
    ph = cp.get("phone_number") or ""

    co_p = Paragraph(
        f"<b>{cn}</b><br/>"
        f"<font size=7 color='#667A95'>{addr}<br/>{ph}{' | '+trn if trn else ''}</font>",
        F("_co", fontSize=8.5, fontName="Helvetica-Bold", textColor=C4, leading=10)
    )
    lh = Table([[logo, Spacer(1, 3*mm), co_p]], colWidths=[LW, 3*mm, W*0.65 - LW - 3*mm]) if logo else Table([[co_p]], colWidths=[W*0.65])
    lh.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))

    period_label = filter_month or (f"{date_from} to {date_to}" if date_from and date_to else date_from or date_to or "All Time")
    title = f"Job Entries Statement" + (f" — {period_label}" if period_label != "All Time" else "")
    rh = Paragraph(f"<b>{title}</b><br/><font size=7 color='#667A95'>Staff: {staff['full_name']} ({staff['staff_id']})</font>", F("_rh", fontSize=10, fontName="Helvetica-Bold", textColor=TH, alignment=TA_RIGHT, leading=12))
    ht = Table([[lh, rh]], colWidths=[W*0.65, W*0.35])
    ht.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ht)
    els.append(Spacer(1, 2*mm))
    hr = Table([[""]], colWidths=[W], rowHeights=[0.5])
    hr.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(hr)
    els.append(Spacer(1, 4*mm))

    # Summary
    sdata = [[
        Paragraph(f"<b>Total Jobs</b><br/><font size=10 color='#1a3a5c'>{len(jobs)}</font>", F("_s1", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Total Amount</b><br/><font size=10 color='#e65100'>AED {total_amount:,.2f}</font>", F("_s2", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph(f"<b>Period</b><br/><font size=10 color='#1a3a5c'>{period_label}</font>", F("_s3", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
    ]]
    st = Table(sdata, colWidths=[W/3, W/3, W/3])
    st.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BOX",(0,0),(-1,-1),0.5, rl_colors.HexColor("#D7E2EF")),
        ("INNERGRID",(0,0),(-1,-1),0.3, rl_colors.HexColor("#D7E2EF")),
        ("TOPPADDING",(0,0),(-1,-1),8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("BACKGROUND",(0,0),(-1,-1), rl_colors.HexColor("#F6F9FD")),
    ]))
    els.append(st)
    els.append(Spacer(1, 4*mm))

    # Table
    colw = [50, 55, 45, 40, W - 50 - 55 - 45 - 40 - 50, 50]
    hdr = [
        Paragraph("<b>Date</b>", F("_h", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph("<b>Vehicle</b>", F("_h", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        Paragraph("<b>Amount</b>", F("_h", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
        Paragraph("<b>Category</b>", F("_h", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph("<b>Description</b>", F("_h", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        Paragraph("<b>Attachment</b>", F("_h", fontSize=6.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
    ]
    rws = [hdr]
    _tmp_imgs = []
    for j in jobs:
            d = str(j.get("created_at", ""))[:10]
            veh = j.get("vehicle_id", "")
            cat = j.get("category", "")
            desc = j.get("description", "") or "-"
            amt = float(j.get("amount", 0))
            has_att = bool(j.get("attachment_data"))
            if has_att:
                att_url = f"{base_url}/fleet/attachment/{j['id']}"
                att_type = (j.get("attachment_type") or "").lower()
                if att_type.startswith("image/"):
                    thumb_f = _embed_attachment_image(j.get("attachment_data"), att_type, tempfile.gettempdir())
                    if thumb_f:
                        _tmp_imgs.append(thumb_f)
                        att_link = _LinkImage(thumb_f, att_url, width=20, height=20)
                    else:
                        att_link = f'<a href="{att_url}" color="#1C568B">See</a>'
                else:
                    att_link = f'<a href="{att_url}" color="#1C568B">Open</a>'
            else:
                att_link = '<font color="#cccccc">—</font>'
            rws.append([
                Paragraph(d, F("_d", fontSize=6.5, leading=9)),
                Paragraph(veh, F("_v", fontSize=6.5, fontName="Helvetica-Bold", textColor=C4, leading=9)),
                Paragraph(f"<b>{amt:,.2f}</b>", F("_a", fontSize=6.5, textColor=rl_colors.HexColor("#e65100"), alignment=TA_RIGHT, leading=9)),
                Paragraph(cat, F("_c", fontSize=6.5, alignment=TA_CENTER, leading=9)),
                Paragraph(desc, F("_det", fontSize=6.2, textColor=C5, leading=9)),
                (att_link if isinstance(att_link, Flowable) else Paragraph(att_link, F("_at", fontSize=6.5, textColor=rl_colors.HexColor("#1C568B"), alignment=TA_CENTER, leading=9))),
            ])
    # Total row
    rws.append([
        Paragraph("<b>Total</b>", F("_tb", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, leading=10)),
        Paragraph("", F("_x")),
        Paragraph(f"<b>{total_amount:,.2f}</b>", F("_tt", fontSize=7.5, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
        Paragraph("", F("_x")), Paragraph("", F("_x")), Paragraph("", F("_x")),
    ])
    it = Table(rws, colWidths=colw, repeatRows=1)
    it.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BACKGROUND",(0,0),(-1,0),TH), ("TEXTCOLOR",(0,0),(-1,0),WH),
        ("BOX",(0,0),(-1,-1),0.5, rl_colors.HexColor("#D7E2EF")),
        ("INNERGRID",(0,0),(-1,-1),0.3, rl_colors.HexColor("#D7E2EF")),
        ("TOPPADDING",(0,0),(-1,-1),2), ("BOTTOMPADDING",(0,0),(-1,-1),2),
        ("LEFTPADDING",(0,0),(-1,-1),3), ("RIGHTPADDING",(0,0),(-1,-1),3),
        ("BACKGROUND",(0,-1),(-1,-1),TH), ("TEXTCOLOR",(0,-1),(-1,-1),WH),
        ("ROWBACKGROUNDS",(0,1),(-2,-2),[WH, BG]),
    ]))
    els.append(it)

    # Footer
    els.append(Spacer(1, 10*mm))
    s_sg = ParagraphStyle("SSG", fontSize=9, alignment=TA_CENTER, leading=14)
    s_stamp_path = os.path.join(assets_dir, 'Stamp.png')
    s_sign_path = os.path.join(assets_dir, 'Sign (1).png')
    s_auth_cells = []
    s_auth_cells.append(Paragraph("_________________________", s_sg))
    if os.path.exists(s_stamp_path):
        try:
            s_auth_cells.append(Image(s_stamp_path, width=40, height=40))
        except Exception:
            s_auth_cells.append(Paragraph("<br/>", s_sg))
    else:
        s_auth_cells.append(Paragraph("<br/>", s_sg))
    s_auth_cells.append(Paragraph("<b>Authorised Signatory</b>", s_sg))
    s_auth_cells.append(Paragraph(f"<font size=6 color='#667A95'>Generated: {datetime.now().strftime('%d-%b-%Y %H:%M')}</font>",
                                  ParagraphStyle("SSG2", fontSize=6, alignment=TA_CENTER, leading=8)))
    s_auth_cell = Table([[c] for c in s_auth_cells], colWidths=[W*0.35])
    s_auth_cell.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                                     ("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1)]))
    if os.path.exists(s_sign_path):
        try:
            els.append(Table([[
                Paragraph(f"<font size=7 color='#667A95'>Prepared by: Admin</font>",
                          ParagraphStyle("PREP", fontSize=7, alignment=TA_LEFT, leading=9)),
                s_auth_cell,
                Image(s_sign_path, width=55, height=20),
            ]], colWidths=[W*0.35, W*0.30, W*0.35]))
        except Exception:
            els.append(s_auth_cell)
    else:
        els.append(s_auth_cell)

    doc.build(els)
    for f in _tmp_imgs:
        try:
            os.remove(f)
        except OSError:
            pass
    return path


def generate_deduction_statement_pdf(driver, salary_store_row, slip_row, deducted_transactions, output_dir: str, assets_dir: str, company_profile: dict | None = None) -> str:
    from reportlab.platypus import SimpleDocTemplate, Paragraph as PlParagraph, Spacer, Table as PlTable, TableStyle as PlTableStyle, Image as PlImage
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    import os, tempfile

    month_value = str(slip_row.get("salary_month", ""))
    output_path = Path(output_dir) / f"{driver['driver_id']}_deduction_{month_value}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    LM, RM, TM, BM = 18*mm, 18*mm, 15*mm, 15*mm
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM

    cp = dict(company_profile) if company_profile else {}
    tc = cp.get("theme_color") or "#1a3a5c"
    try: TH = colors.HexColor(tc)
    except: TH = colors.HexColor("#1a3a5c")
    BG = colors.HexColor("#f4f6f9"); WH = colors.white
    C3 = colors.HexColor("#d1d5db"); C4 = colors.HexColor("#111827"); C5 = colors.HexColor("#6b7280")

    def F(name, **kw):
        kw.setdefault("fontSize", 8); kw.setdefault("leading", 12)
        return ParagraphStyle(name, **kw)

    els = []
    cn = cp.get("company_name", "CURRENT LINK TRANSPORT AND GENERAL CONTRACTING")
    trn = cp.get("trn_no") or "—"

    logo = None; LW = 0
    if cp.get("logo_data"):
        try:
            lb = base64.b64decode(cp["logo_data"])
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            f.write(lb); f.close()
            logo = PlImage(f.name, width=50, height=50)
            LW = 50
        except: pass

    cl = [f"<font size=11><b>{cn}</b></font>"]
    addr = cp.get("address") or ""; ph = cp.get("phone_number") or ""; em = cp.get("email") or ""
    parts_l = [x for x in [addr] if x]
    cparts = [x for x in [ph, em, f"TRN: {trn}"] if x and x != "TRN: —"]
    if parts_l or cparts:
        info = " &middot; ".join(parts_l + cparts)
        cl.append(f"<font size=6.5 color='#6b7280'>{info}</font>")
    co_p = PlParagraph("<br/>".join(cl), F("CO", fontSize=11, fontName="Helvetica-Bold", textColor=TH, leading=13))
    if logo:
        lh = PlTable([[logo, Spacer(1, 3*mm), co_p]], colWidths=[LW, 3*mm, W*0.65 - LW - 3*mm])
        lh.setStyle(PlTableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    else:
        lh = co_p
    rh = PlParagraph("<b>DEDUCTION<br/>STATEMENT</b>", F("TI", fontSize=14, fontName="Helvetica-Bold", textColor=TH, leading=18, alignment=TA_RIGHT))
    ht = PlTable([[lh, rh]], colWidths=[W*0.65, W*0.35])
    ht.setStyle(PlTableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ht)
    els.append(Spacer(1, 2*mm))
    hr = PlTable([[""]], colWidths=[W], rowHeights=[2])
    hr.setStyle(PlTableStyle([("BACKGROUND",(0,0),(-1,-1),TH),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(hr)
    els.append(Spacer(1, 4*mm))

    finfo = [
        [PlParagraph("<b>Driver</b>", F("_fl", fontSize=8, fontName="Helvetica-Bold", textColor=C4, leading=11)),
         PlParagraph(f"<b>{driver.get('full_name','-')} ({driver.get('driver_id','-')})</b>", F("_fv", fontSize=9, fontName="Helvetica-Bold", textColor=C4, leading=12))],
        [PlParagraph("Month", F("_l", fontSize=7.5, textColor=C5, leading=10)),
         PlParagraph(format_month_label(month_value), F("_v", fontSize=8.5, textColor=C4, leading=11))],
    ]
    ft = PlTable(finfo, colWidths=[50, W - 50])
    ft.setStyle(PlTableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    els.append(ft)
    els.append(Spacer(1, 4*mm))

    total_ded = float(slip_row.get("total_deductions") or 0)
    salary_after = float(slip_row.get("salary_after_deduction") or 0)
    net_sal = float(salary_store_row.get("net_salary") or 0) if salary_store_row else 0
    sdata = [[
        PlParagraph(f"<b>Net Salary</b><br/><font size=10 color='#1a3a5c'>AED {format_currency(net_sal)}</font>", F("_s1", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        PlParagraph(f"<b>Total Deducted</b><br/><font size=10 color='#c62828'>AED {format_currency(total_ded)}</font>", F("_s2", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        PlParagraph(f"<b>Net Received</b><br/><font size=10 color='#1a7d1a'>AED {format_currency(salary_after)}</font>", F("_s3", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        PlParagraph(f"<b>Transactions</b><br/><font size=10>{len(deducted_transactions)}</font>", F("_s4", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
    ]]
    st = PlTable(sdata, colWidths=[W/4, W/4, W/4, W/4])
    st.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5),
        ("BACKGROUND",(0,0),(-1,-1),BG),
    ]))
    els.append(st)
    els.append(Spacer(1, 4*mm))

    els.append(PlParagraph("<b>Deducted Transactions</b>", F("_ttitle", fontSize=8, fontName="Helvetica-Bold", textColor=TH, leading=10)))
    els.append(Spacer(1, 2*mm))
    dcolw = [42, 42, W - 42 - 42 - 50, 50]
    dhdr = [
        PlParagraph("<b>Date</b>", F("_dh", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_CENTER, leading=9)),
        PlParagraph("<b>Amount</b>", F("_dh", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
        PlParagraph("<b>Details</b>", F("_dh", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, leading=9)),
        PlParagraph("<b>Deducted</b>", F("_dh", fontSize=6.2, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=9)),
    ]
    drows = [dhdr]
    total_txn_amt = 0.0
    for dt in deducted_transactions:
        amt = float(dt.get("amount", 0))
        ded = float(dt.get("amount_deducted", amt))
        total_txn_amt += ded
        drows.append([
            PlParagraph(str(dt.get("entry_date", ""))[:10], F("_dd", fontSize=6.5, leading=9)),
            PlParagraph(f"<b>{format_currency(amt)}</b>", F("_da", fontSize=6.5, fontName="Helvetica-Bold", textColor=C4, alignment=TA_RIGHT, leading=9)),
            PlParagraph(str(dt.get("details", "-")), F("_dDet", fontSize=6.2, textColor=C5, leading=9)),
            PlParagraph(f"<b>{format_currency(ded)}</b>", F("_ddr", fontSize=6.5, fontName="Helvetica-Bold", textColor="#c62828", alignment=TA_RIGHT, leading=9)),
        ])
    drows.append([
        PlParagraph("<b>Total</b>", F("_dtb", fontSize=7, fontName="Helvetica-Bold", textColor=WH, leading=10)),
        PlParagraph("", F("_dx")),
        PlParagraph("", F("_dx")),
        PlParagraph(f"<b>{format_currency(total_txn_amt)}</b>", F("_dtt", fontSize=7, fontName="Helvetica-Bold", textColor=WH, alignment=TA_RIGHT, leading=10)),
    ])
    dtbl = PlTable(drows, colWidths=dcolw, repeatRows=1)
    dtbl.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BACKGROUND",(0,0),(-1,0),TH), ("TEXTCOLOR",(0,0),(-1,0),WH),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),2), ("BOTTOMPADDING",(0,0),(-1,-1),2),
        ("LEFTPADDING",(0,0),(-1,-1),3), ("RIGHTPADDING",(0,0),(-1,-1),3),
        ("BACKGROUND",(0,-1),(-1,-1),TH), ("TEXTCOLOR",(0,-1),(-1,-1),WH),
        ("ROWBACKGROUNDS",(0,1),(-2,-2),[WH, BG]),
    ]))
    els.append(dtbl)
    els.append(Spacer(1, 4*mm))

    calc = [
        [PlParagraph("Net Salary", F("_cl", fontSize=7.5, leading=10)), PlParagraph(f"AED {format_currency(net_sal)}", F("_cr", fontSize=7.5, alignment=TA_RIGHT, leading=10))],
        [PlParagraph("Total Deducted", F("_cl", fontSize=7.5, textColor="#c62828", leading=10)), PlParagraph(f"-AED {format_currency(total_ded)}", F("_cr", fontSize=7.5, textColor="#c62828", alignment=TA_RIGHT, leading=10))],
        [PlParagraph("<b>Net Received by Driver</b>", F("_cl", fontSize=8, fontName="Helvetica-Bold", textColor="#1a7d1a", leading=11)), PlParagraph(f"<b>AED {format_currency(salary_after)}</b>", F("_cr", fontSize=8, fontName="Helvetica-Bold", textColor="#1a7d1a", alignment=TA_RIGHT, leading=11))],
    ]
    ct = PlTable(calc, colWidths=[W*0.6, W*0.4])
    ct.setStyle(PlTableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BOX",(0,0),(-1,-1),0.5,C3), ("INNERGRID",(0,0),(-1,-1),0.3,C3),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
        ("BACKGROUND",(2,0),(2,0),BG),
    ]))
    els.append(ct)

    els.append(Spacer(1, 8*mm))
    s_sg = ParagraphStyle("SSG", fontSize=9, alignment=TA_CENTER, leading=14)
    s_auth_cells = []
    s_auth_cells.append(PlParagraph("_________________________", s_sg))
    s_stamp_path = os.path.join(assets_dir, 'Stamp.png')
    s_sign_path = os.path.join(assets_dir, 'Sign (1).png')
    if os.path.exists(s_stamp_path):
        s_auth_cells.append(PlImage(s_stamp_path, width=40, height=40))
    if os.path.exists(s_sign_path):
        s_auth_cells.append(PlImage(s_sign_path, width=40, height=40))
    s_auth_cells.append(PlParagraph("<b>Authorized Signatory</b>", s_sg))
    s_auth_cell = PlTable([[c] for c in s_auth_cells], colWidths=[W*0.35])
    s_auth_cell.setStyle(PlTableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),2)]))
    els.append(s_auth_cell)

    els.append(Spacer(1, 6*mm))
    els.append(PlParagraph("This is a computer-generated Deduction Statement.", F("_ft", fontSize=7, textColor=C5, alignment=TA_CENTER, leading=9)))

    doc.build(els)
    return str(output_path)


def generate_fuel_report_pdf(entries, vehicle_filter, month_filter, output_dir, assets_dir='', company_profile=None):
    import tempfile
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from collections import Counter
    from io import BytesIO

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = Path(output_dir) / 'fuel_report_{}_{}.pdf'.format(month_filter or 'all', timestamp)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    buf = BytesIO()
    LM, RM, TM, BM = 12*mm, 12*mm, 15*mm, 15*mm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM
    rows = list(entries or [])
    total_gallons = sum(float(r.get('gallons', 0) or 0) for r in rows)
    total_amount = sum(float(r.get('total_amount', 0) or 0) for r in rows)
    month_label = format_month_label(month_filter) if month_filter else 'All Periods'

    veh_totals = Counter()
    for r in rows:
        plate = r.get('vehicle_plate') or 'Unknown'
        veh_totals[plate] += float(r.get('gallons', 0) or 0)
    top_vehicles = veh_totals.most_common(10)

    _logo_tmp_files = []
    cp = company_profile or {}
    tc = cp.get('theme_color') or '#1a3a5c'
    try: TH = colors.HexColor(tc)
    except: TH = colors.HexColor('#1a3a5c')
    BG = colors.HexColor('#f4f6f9'); WH = colors.white; C3 = colors.HexColor('#d1d5db')
    C4 = colors.HexColor('#111827'); C5 = colors.HexColor('#6b7280'); RD = colors.HexColor('#c62828')
    els = []
    cn = cp.get('company_name', 'CURRENT LINK TRANSPORT AND GENERAL CONTRACTING')
    trn = cp.get('trn_no') or '—'

    # ═══════════════════════════════════════
    # 1. HEADER
    # ═══════════════════════════════════════
    logo = None; LW = 0
    if cp.get('logo_data'):
        try:
            lb = base64.b64decode(cp['logo_data'])
            f = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            f.write(lb); f.close()
            logo = Image(f.name, width=40, height=40)
            LW = 40
            _logo_tmp_files.append(f.name)
        except: pass

    addr = cp.get('address') or ''; ph = cp.get('phone_number') or ''; em = cp.get('email') or ''
    parts = [x for x in [addr] if x]
    cparts = [x for x in [ph, em] if x]
    info = ''
    if parts or cparts:
        info = ' &middot; '.join(parts + cparts)

    cl = ['<font size=10><b>{}</b></font>'.format(cn)]
    if info:
        cl.append('<font size=6 color="#6b7280">{}</font>'.format(info))
    if trn and trn != '—':
        cl.append('<font size=6 color="#6b7280">TRN: {}</font>'.format(trn))
    co_p = Paragraph('<br/>'.join(cl), ParagraphStyle('CO', fontSize=10, fontName='Helvetica-Bold', textColor=TH, leading=12))

    lh = co_p
    if logo:
        lh = Table([[logo, Spacer(1, 2*mm), co_p]], colWidths=[LW, 2*mm, W*0.65 - LW - 2*mm])
        lh.setStyle(TableStyle([('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))

    subtitle = month_label + (' | Vehicle: {}'.format(vehicle_filter) if vehicle_filter else '')
    rh = Paragraph(
        '<b>FUEL CONSUMPTION<br/>REPORT</b><br/><font size=6.5 color="#6b7280">{}</font>'.format(subtitle),
        ParagraphStyle('TI', fontSize=13, fontName='Helvetica-Bold', textColor=TH, leading=16, alignment=TA_RIGHT))

    ht = Table([[lh, rh]], colWidths=[W*0.65, W*0.35])
    ht.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    els.append(ht)
    els.append(Spacer(1, 2*mm))
    hr = Table([['']], colWidths=[W], rowHeights=[1.5])
    hr.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),TH),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    els.append(hr)
    els.append(Spacer(1, 4*mm))

    # ═══════════════════════════════════════
    # 2. PERIOD BADGE
    # ═══════════════════════════════════════
    badge = Table([[Paragraph('<b>{}</b>'.format(subtitle), ParagraphStyle('b', fontSize=7, fontName='Helvetica-Bold', textColor=TH, alignment=TA_CENTER, leading=9))]], colWidths=[160])
    badge.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),0.5,TH), ('TOPPADDING',(0,0),(-1,-1),3), ('BOTTOMPADDING',(0,0),(-1,-1),3),
        ('LEFTPADDING',(0,0),(-1,-1),8), ('RIGHTPADDING',(0,0),(-1,-1),8), ('ALIGN',(0,0),(-1,-1),'CENTER'),
    ]))
    els.append(badge)
    els.append(Spacer(1, 4*mm))

    # ═══════════════════════════════════════
    # 3. SUMMARY CARDS
    # ═══════════════════════════════════════
    sdata = [[
        Paragraph('<b>Total Gallons (GLN)</b><br/><font size=10 color="#1a3a5c">{:,.2f}</font>'.format(total_gallons), ParagraphStyle('_s1', fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph('<b>Total Amount (AED)</b><br/><font size=10 color="#c62828">AED {:,.2f}</font>'.format(total_amount), ParagraphStyle('_s2', fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph('<b>Total Entries</b><br/><font size=10 color="#1a3a5c">{}</font>'.format(len(rows)), ParagraphStyle('_s3', fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
    ]]
    st = Table(sdata, colWidths=[W/3, W/3, W/3])
    st.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('BOX',(0,0),(-1,-1),0.5,C3), ('INNERGRID',(0,0),(-1,-1),0.3,C3),
        ('TOPPADDING',(0,0),(-1,-1),8), ('BOTTOMPADDING',(0,0),(-1,-1),8),
        ('LEFTPADDING',(0,0),(-1,-1),5), ('RIGHTPADDING',(0,0),(-1,-1),5),
        ('BACKGROUND',(0,0),(-1,-1),BG),
    ]))
    els.append(st)
    els.append(Spacer(1, 5*mm))

    # ═══════════════════════════════════════
    # 4. DATA TABLE
    # ═══════════════════════════════════════
    # Proportions: Date 12%, Vehicle 10%, GLN 10%, Rate/GLN 12%, Total AED 16%, Supplier 40%
    cw_d = int(W * 0.12)
    cw_v = int(W * 0.10)
    cw_g = int(W * 0.10)
    cw_r = int(W * 0.12)
    cw_a = int(W * 0.16)
    cw_s = W - cw_d - cw_v - cw_g - cw_r - cw_a

    def supp_p(t):
        return Paragraph(str(t or '—'), ParagraphStyle('s', fontSize=6, textColor=C5, leading=7.5, alignment=TA_LEFT))

    hdr = [
        Paragraph('<b>Date</b>', ParagraphStyle('h', fontSize=7, fontName='Helvetica-Bold', textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph('<b>Vehicle</b>', ParagraphStyle('h', fontSize=7, fontName='Helvetica-Bold', textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph('<b>GLN</b>', ParagraphStyle('h', fontSize=7, fontName='Helvetica-Bold', textColor=WH, alignment=TA_RIGHT, leading=9)),
        Paragraph('<b>Rate/GLN</b>', ParagraphStyle('h', fontSize=7, fontName='Helvetica-Bold', textColor=WH, alignment=TA_RIGHT, leading=9)),
        Paragraph('<b>Total AED</b>', ParagraphStyle('h', fontSize=7, fontName='Helvetica-Bold', textColor=WH, alignment=TA_RIGHT, leading=9)),
        Paragraph('<b>Supplier</b>', ParagraphStyle('h', fontSize=7, fontName='Helvetica-Bold', textColor=WH, alignment=TA_LEFT, leading=9)),
    ]

    rws = [hdr]
    for r in rows:
        rws.append([
            str(r.get('entry_date') or '—'),
            str(r.get('vehicle_plate') or '—'),
            '{:,.2f}'.format(float(r.get('gallons') or 0)),
            '{:,.3f}'.format(float(r.get('rate_per_gallon') or 0)),
            '{:,.2f}'.format(float(r.get('total_amount') or 0)),
            supp_p(r.get('supplier_name')),
        ])

    rws.append([
        Paragraph('<b>Total</b>', ParagraphStyle('t', fontSize=8, fontName='Helvetica-Bold', textColor=WH, leading=10, alignment=TA_CENTER)),
        '',
        Paragraph('<b>{:,.2f}</b>'.format(total_gallons), ParagraphStyle('t', fontSize=8, fontName='Helvetica-Bold', textColor=WH, alignment=TA_RIGHT, leading=10)),
        '',
        Paragraph('<b>{:,.2f}</b>'.format(total_amount), ParagraphStyle('t', fontSize=8, fontName='Helvetica-Bold', textColor=WH, alignment=TA_RIGHT, leading=10)),
        Paragraph('<b>—</b>', ParagraphStyle('t', fontSize=8, fontName='Helvetica-Bold', textColor=WH, leading=10)),
    ])

    it = Table(rws, colWidths=[cw_d, cw_v, cw_g, cw_r, cw_a, cw_s], repeatRows=1)
    it.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('BACKGROUND',(0,0),(-1,0),TH), ('TEXTCOLOR',(0,0),(-1,0),WH),
        ('ALIGN',(0,1),(0,-1),'CENTER'),
        ('ALIGN',(1,1),(1,-1),'CENTER'),
        ('ALIGN',(2,1),(2,-2),'RIGHT'),
        ('ALIGN',(3,1),(3,-2),'RIGHT'),
        ('ALIGN',(4,1),(4,-2),'RIGHT'),
        ('ALIGN',(5,1),(5,-2),'LEFT'),
        ('FONTSIZE',(0,1),(4,-2),6),
        ('FONTNAME',(0,-1),(-1,-1),'Helvetica-Bold'),
        ('TEXTCOLOR',(4,1),(4,-2),RD),
        ('FONTNAME',(4,1),(4,-2),'Helvetica-Bold'),
        ('TOPPADDING',(0,0),(-1,-1),1.5), ('BOTTOMPADDING',(0,0),(-1,-1),1.5),
        ('LEFTPADDING',(0,0),(-1,-1),2), ('RIGHTPADDING',(0,0),(-1,-1),2),
        ('BACKGROUND',(0,-1),(-1,-1),TH), ('TEXTCOLOR',(0,-1),(-1,-1),WH),
        ('BOX',(0,0),(-1,-1),0.5,C3), ('INNERGRID',(0,0),(-1,-1),0.3,C3),
        ('LINEBELOW',(0,0),(-1,0),0.6,TH),
        ('LINEABOVE',(0,-1),(-1,-1),0.6,TH),
        ('ROWBACKGROUNDS',(0,1),(-2,-2),[WH, BG]),
    ]))
    els.append(it)
    els.append(Spacer(1, 5*mm))

    # ═══════════════════════════════════════
    # 5. TOP VEHICLES BAR CHART (REAL GRAPHICAL CHART)
    # ═══════════════════════════════════════
    if top_vehicles:
        from reportlab.graphics.shapes import Drawing, Rect, String, Line
        from reportlab.graphics import renderPDF
        CH = 155
        d = Drawing(W, CH)
        LM = 70; RM = 50; TM = 22; BM = 18
        PW = W - LM - RM
        PH = CH - TM - BM
        max_val = max(v for _, v in top_vehicles)
        n = len(top_vehicles)

        # Title
        d.add(String(W / 2, CH - 4, 'Top Vehicles by Fuel Consumption',
               textAnchor='middle', fontSize=9, fontName='Helvetica-Bold', fillColor=TH))

        # Grid lines (light vertical)
        for i in range(6):
            x = LM + PW * i / 5
            d.add(Line(x, BM, x, BM + PH, strokeColor=colors.Color(0.88, 0.88, 0.88), strokeWidth=0.4))

        # X-axis line
        d.add(Line(LM, BM, LM + PW, BM, strokeColor=colors.Color(0.7, 0.7, 0.7), strokeWidth=0.5))
        # Grid labels
        for i in range(6):
            v = max_val * i / 5
            x = LM + PW * i / 5
            d.add(String(x, BM - 3, '{:,.0f}'.format(v), textAnchor='middle', fontSize=5.5, fillColor=C5))

        bars = top_vehicles[:10]
        bs = PH / (n + 0.5)
        bh = bs * 0.6

        for i, (plate, gal) in enumerate(bars):
            y = BM + bs * (n - 1 - i) + (bs - bh) / 2
            bw = (gal / max_val) * PW if max_val > 0 else 0

            # Vehicle label (y-axis)
            d.add(String(LM - 6, y + bh / 2, plate,
                   textAnchor='end', fontSize=6, fontName='Helvetica', fillColor=C4))

            # Bar
            d.add(Rect(LM, y, max(bw, 1), bh, fillColor=colors.HexColor('#1C568B'), strokeColor=None))

            # GLN value at end of bar
            d.add(String(LM + max(bw, 0) + 3, y + bh / 2, '{:,.0f}'.format(gal),
                   textAnchor='start', fontSize=6.5, fontName='Helvetica-Bold', fillColor=C4))

        # X-axis label
        d.add(String(LM + PW / 2, 2, 'Fuel Consumption (GLN)',
               textAnchor='middle', fontSize=7, fontName='Helvetica', fillColor=C5))

        els.append(Spacer(1, 2*mm))
        els.append(d)
        els.append(Spacer(1, 4*mm))

    # ═══════════════════════════════════════
    # 6. FOOTER
    # ═══════════════════════════════════════
    els.append(Paragraph(
        '<font size=6.5 color="#6b7280">Generated on {}</font>'.format(datetime.now().strftime('%d-%b-%Y %I:%M %p')),
        ParagraphStyle('_ft', fontSize=6.5, textColor=C5, alignment=TA_CENTER, leading=9)))

    doc.build(els)
    with open(str(output_path), 'wb') as f:
        f.write(buf.getvalue())
    for tmp in _logo_tmp_files:
        try: os.unlink(tmp)
        except: pass
    return str(output_path)


def generate_atm_report_pdf(entries, month, year, output_dir, assets_dir='', company_profile=None):
    import tempfile
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from io import BytesIO

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = Path(output_dir) / 'atm_report_{}_{}_{}.pdf'.format(year or 'all', month or 'all', timestamp)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = list(entries or [])
    total_amount = sum(float(r.get('amount', 0) or 0) for r in rows)
    month_label = format_month_label('{}-{}'.format(year, month)) if month and year else 'All Periods'

    _logo_tmp_files = []
    buf = BytesIO()
    LM, RM, TM, BM = 12*mm, 12*mm, 15*mm, 15*mm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    W = A4[0] - LM - RM

    cp = company_profile or {}
    tc = cp.get('theme_color') or '#1a3a5c'
    try: TH = colors.HexColor(tc)
    except: TH = colors.HexColor('#1a3a5c')
    BG = colors.HexColor('#f4f6f9'); WH = colors.white; C3 = colors.HexColor('#d1d5db')
    C4 = colors.HexColor('#111827'); C5 = colors.HexColor('#6b7280'); RD = colors.HexColor('#c62828')

    cn = cp.get('company_name', 'CURRENT LINK TRANSPORT AND GENERAL CONTRACTING')
    trn = cp.get('trn_no') or '—'
    els = []

    # ═══════════════════════════════════════
    # 1. HEADER
    # ═══════════════════════════════════════
    logo = None; LW = 0
    if cp.get('logo_data'):
        try:
            lb = base64.b64decode(cp['logo_data'])
            f = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            f.write(lb); f.close()
            logo = Image(f.name, width=40, height=40)
            LW = 40
            _logo_tmp_files.append(f.name)
        except: pass

    addr = cp.get('address') or ''; ph = cp.get('phone_number') or ''; em = cp.get('email') or ''
    parts = [x for x in [addr] if x]
    cparts = [x for x in [ph, em] if x]
    info = ''
    if parts or cparts:
        info = ' &middot; '.join(parts + cparts)

    cl = ['<font size=10><b>{}</b></font>'.format(cn)]
    if info:
        cl.append('<font size=6 color="#6b7280">{}</font>'.format(info))
    if trn and trn != '—':
        cl.append('<font size=6 color="#6b7280">TRN: {}</font>'.format(trn))
    co_p = Paragraph('<br/>'.join(cl), ParagraphStyle('CO', fontSize=10, fontName='Helvetica-Bold', textColor=TH, leading=12))

    lh = co_p
    if logo:
        lh = Table([[logo, Spacer(1, 2*mm), co_p]], colWidths=[LW, 2*mm, W*0.65 - LW - 2*mm])
        lh.setStyle(TableStyle([('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))

    month_display = month_label.replace('-', ' ') if month_label != 'All Periods' else 'All Periods'
    rh = Paragraph(
        '<b>ATM WITHDRAWAL<br/>REPORT</b><br/><font size=6.5 color="#6b7280">{}</font>'.format(month_display),
        ParagraphStyle('TI', fontSize=13, fontName='Helvetica-Bold', textColor=TH, leading=16, alignment=TA_RIGHT))

    ht = Table([[lh, rh]], colWidths=[W*0.65, W*0.35])
    ht.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    els.append(ht)
    els.append(Spacer(1, 2*mm))
    hr = Table([['']], colWidths=[W], rowHeights=[1.5])
    hr.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),TH),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    els.append(hr)
    els.append(Spacer(1, 4*mm))

    # ═══════════════════════════════════════
    # 2. PERIOD BADGE
    # ═══════════════════════════════════════
    badge_text = month_display
    badge = Table([[Paragraph('<b>{}</b>'.format(badge_text), ParagraphStyle('b', fontSize=7, fontName='Helvetica-Bold', textColor=TH, alignment=TA_CENTER, leading=9))]], colWidths=[80])
    badge.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),0.5,TH), ('TOPPADDING',(0,0),(-1,-1),3), ('BOTTOMPADDING',(0,0),(-1,-1),3),
        ('LEFTPADDING',(0,0),(-1,-1),8), ('RIGHTPADDING',(0,0),(-1,-1),8), ('ALIGN',(0,0),(-1,-1),'CENTER'),
    ]))
    els.append(badge)
    els.append(Spacer(1, 4*mm))

    # ═══════════════════════════════════════
    # 3. SUMMARY CARDS
    # ═══════════════════════════════════════
    avg = total_amount / len(rows) if rows else 0
    sdata = [[
        Paragraph('<b>Total Withdrawals</b><br/><font size=10 color="#1a3a5c">{}</font>'.format(len(rows)), ParagraphStyle('_s1', fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph('<b>Total Amount</b><br/><font size=10 color="#c62828">AED {:,.2f}</font>'.format(total_amount), ParagraphStyle('_s2', fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
        Paragraph('<b>Average</b><br/><font size=10 color="#1a3a5c">AED {:,.2f}</font>'.format(avg), ParagraphStyle('_s3', fontSize=7, textColor=C5, alignment=TA_CENTER, leading=10)),
    ]]
    st = Table(sdata, colWidths=[W/3, W/3, W/3])
    st.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('BOX',(0,0),(-1,-1),0.5,C3), ('INNERGRID',(0,0),(-1,-1),0.3,C3),
        ('TOPPADDING',(0,0),(-1,-1),8), ('BOTTOMPADDING',(0,0),(-1,-1),8),
        ('LEFTPADDING',(0,0),(-1,-1),5), ('RIGHTPADDING',(0,0),(-1,-1),5),
        ('BACKGROUND',(0,0),(-1,-1),BG),
    ]))
    els.append(st)
    els.append(Spacer(1, 5*mm))

    # ═══════════════════════════════════════
    # 4. DATA TABLE
    # ═══════════════════════════════════════
    # Column proportions: Date 12%, Payee 28%, Amount 15%, Description 45%
    cw_d = int(W * 0.12)
    cw_p = int(W * 0.28)
    cw_a = int(W * 0.15)
    cw_desc = W - cw_d - cw_p - cw_a

    hdr = [
        Paragraph('<b>Date</b>', ParagraphStyle('h', fontSize=7, fontName='Helvetica-Bold', textColor=WH, alignment=TA_CENTER, leading=9)),
        Paragraph('<b>Payee</b>', ParagraphStyle('h', fontSize=7, fontName='Helvetica-Bold', textColor=WH, alignment=TA_LEFT, leading=9)),
        Paragraph('<b>Amount (AED)</b>', ParagraphStyle('h', fontSize=7, fontName='Helvetica-Bold', textColor=WH, alignment=TA_RIGHT, leading=9)),
        Paragraph('<b>Description</b>', ParagraphStyle('h', fontSize=7, fontName='Helvetica-Bold', textColor=WH, alignment=TA_LEFT, leading=9)),
    ]

    def desc_p(t):
        return Paragraph(str(t or '—'), ParagraphStyle('d', fontSize=6, textColor=C5, leading=7.5, alignment=TA_LEFT))

    rws = [hdr]
    for r in rows:
        rws.append([
            str(r.get('entry_date') or '—'),
            str(r.get('payee') or '—'),
            '{:,.2f}'.format(float(r.get('amount') or 0)),
            desc_p(r.get('description')),
        ])

    rws.append(['Total', '', '{:,.2f}'.format(total_amount), Paragraph('<b>—</b>', ParagraphStyle('t', fontSize=6, fontName='Helvetica-Bold', textColor=WH, leading=7.5))])

    it = Table(rws, colWidths=[cw_d, cw_p, cw_a, cw_desc], repeatRows=1)
    it.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('BACKGROUND',(0,0),(-1,0),TH), ('TEXTCOLOR',(0,0),(-1,0),WH),
        ('ALIGN',(0,1),(0,-1),'CENTER'),
        ('ALIGN',(1,1),(1,-1),'LEFT'),
        ('ALIGN',(2,1),(2,-1),'RIGHT'),
        ('ALIGN',(3,1),(3,-1),'LEFT'),
        ('FONTSIZE',(0,1),(2,-2),6),
        ('FONTNAME',(1,1),(1,-2),'Helvetica-Bold'),
        ('FONTNAME',(2,1),(2,-2),'Helvetica-Bold'),
        ('TEXTCOLOR',(2,1),(2,-2),RD),
        ('TOPPADDING',(0,0),(-1,-1),1.5), ('BOTTOMPADDING',(0,0),(-1,-1),1.5),
        ('LEFTPADDING',(0,0),(-1,-1),2), ('RIGHTPADDING',(0,0),(-1,-1),2),
        ('FONTNAME',(0,-1),(-1,-1),'Helvetica-Bold'),
        ('FONTSIZE',(0,-1),(-1,-1),8),
        ('BACKGROUND',(0,-1),(-1,-1),TH), ('TEXTCOLOR',(0,-1),(-1,-1),WH),
        ('BOX',(0,0),(-1,-1),0.5,C3), ('INNERGRID',(0,0),(-1,-1),0.3,C3),
        ('LINEBELOW',(0,0),(-1,0),0.6,TH),
        ('ROWBACKGROUNDS',(0,1),(-2,-2),[WH, BG]),
        ('LINEABOVE',(0,-1),(-1,-1),0.6,TH),
    ]))
    els.append(it)
    els.append(Spacer(1, 5*mm))

    # ═══════════════════════════════════════
    # 5. FOOTER
    # ═══════════════════════════════════════
    els.append(Paragraph(
        '<font size=6.5 color="#6b7280">Generated on {}</font>'.format(datetime.now().strftime('%d-%b-%Y %I:%M %p')),
        ParagraphStyle('_ft', fontSize=6.5, textColor=C5, alignment=TA_CENTER, leading=9)))

    doc.build(els)
    with open(str(output_path), 'wb') as f:
        f.write(buf.getvalue())
    for tmp in _logo_tmp_files:
        try: os.unlink(tmp)
        except: pass
    return str(output_path)
