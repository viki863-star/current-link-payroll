"""
Salary Slip PDF Template
=========================
Standalone template for generating professional driver salary slip documents.

Usage:
    from salary_slip_design import generate_salary_slip_pdf
    generate_salary_slip_pdf(company, driver, salary_row, slip_payload, output_path)
"""

from base_design import *


def generate_salary_slip_pdf(
    company: dict,
    driver: dict,
    salary_row: dict,
    slip_payload: dict,
    output_path: str,
) -> str:
    """Generate a standalone Salary Slip PDF.

    Args:
        company:      Company profile dict (company_name, trn_no, address, etc.)
        driver:       Driver dict with keys:
                        full_name, driver_id, vehicle_no, phone_number,
                        shift, duty_start
        salary_row:   Salary data dict with keys:
                        salary_month, basic_salary, ot_hours, ot_amount,
                        personal_vehicle, net_salary, ot_type, ot_trips
        slip_payload: Computed slip dict with keys:
                        deduction_amount, available_advance, remaining_advance,
                        salary_after_deduction, actual_paid_amount,
                        company_balance_due, _vehicle_no
        output_path:  Absolute path for the output PDF file.

    Returns:
        Absolute path to the generated PDF.
    """
    company = company or {}
    driver = driver or {}
    salary_row = salary_row or {}
    slip_payload = slip_payload or {}

    pdf = canvas.Canvas(str(output_path), pagesize=A4)

    # ── 1. Header card (logo, company name, address, TRN) ────────────────────────
    _draw_header(pdf, company_profile=company)

    # ── 2. Title ─────────────────────────────────────────────────────────────────
    _draw_title(
        pdf,
        f"Salary Slip {format_month_label(salary_row.get('salary_month', ''))}",
        f"Payslip  |  {format_month_label(salary_row.get('salary_month', ''))}",
    )

    # ── 3. Driver summary card ───────────────────────────────────────────────────
    _draw_driver_summary(pdf, driver, salary_row, slip_payload)

    # ── 4. Salary breakdown (earnings & deductions) ──────────────────────────────
    _draw_salary_breakdown(pdf, salary_row, slip_payload)

    # ── 5. Footer ────────────────────────────────────────────────────────────────
    _draw_footer_banner(pdf, company_profile=company)

    pdf.showPage()
    pdf.save()
    return str(output_path)


def _draw_driver_summary(pdf, driver, salary_row, slip_payload):
    """Draw the driver info card and actual paid metric."""
    summary_x = 16 * mm
    summary_y = PAGE_HEIGHT - 181 * mm + 34 * mm  # position below header+title
    summary_y = PAGE_HEIGHT - 147 * mm
    summary_w = 116 * mm
    summary_h = 47 * mm
    _v = slip_payload.get("_vehicle_no") or ""

    # Card background
    pdf.setFillColor(WHITE)
    pdf.roundRect(summary_x, summary_y, summary_w, summary_h, 5 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(summary_x, summary_y, summary_w, summary_h, 5 * mm, fill=0, stroke=1)

    # Card header
    pdf.setFillColor(BLUE_SOFT)
    pdf.roundRect(summary_x, summary_y + summary_h - 10 * mm, summary_w, 10 * mm, 5 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(summary_x + 5 * mm, summary_y + summary_h - 6.2 * mm, "DRIVER SUMMARY")

    # Left column
    left_rows = [
        ("Driver Name", driver.get("full_name", "-")),
        ("Driver ID", driver.get("driver_id", "-")),
        ("Vehicle Number", driver.get("vehicle_no") or driver.get("_vehicle_no_fb") or _v or "-"),
        ("Join Date", format_date_label(driver.get("duty_start"))),
    ]
    # Right column
    right_rows = [
        ("Phone Number", driver.get("phone_number", "-")),
        ("Pay Period", format_month_label(salary_row.get("salary_month", ""))),
        ("OT Month", format_month_label(
            salary_row.get("ot_month") or previous_month_value(salary_row.get("salary_month", ""))
        )),
        ("Shift", driver.get("shift", "-")),
        ("Basic Salary", f"AED {format_currency(float(salary_row.get('basic_salary', 0)))}"),
    ]

    row_y = summary_y + summary_h - 15.5 * mm
    for label, value in left_rows:
        _draw_label_value_row(pdf, summary_x + 5 * mm, row_y, 24 * mm, 25 * mm, label, value)
        row_y -= 5.8 * mm

    row_y = summary_y + summary_h - 15.5 * mm
    for label, value in right_rows:
        _draw_label_value_row(pdf, summary_x + 63 * mm, row_y, 19 * mm, 28 * mm, label, value)
        row_y -= 5.8 * mm

    # Actual Paid metric box (top right)
    metric_x = 138 * mm
    metric_y = summary_y + 24 * mm
    metric_w = 56 * mm
    metric_h = 23 * mm
    pdf.setFillColor(BLUE)
    pdf.roundRect(metric_x, metric_y, metric_w, metric_h, 5 * mm, fill=1, stroke=0)
    pdf.setFillColor(WHITE)
    pdf.setFont("Helvetica-Bold", 8.2)
    pdf.drawCentredString(metric_x + metric_w / 2, metric_y + 16 * mm, "ACTUAL PAID")
    pdf.setFont("Helvetica-Bold", 13.2)
    pdf.drawCentredString(
        metric_x + metric_w / 2, metric_y + 9.2 * mm,
        f"{format_currency(float(slip_payload.get('actual_paid_amount', 0)))} AED",
    )
    pdf.setFont("Helvetica", 7.2)
    pdf.drawCentredString(
        metric_x + metric_w / 2, metric_y + 3.2 * mm,
        format_month_label(salary_row.get("salary_month", "")),
    )


def _draw_salary_breakdown(pdf, salary_row, slip_payload):
    """Draw the earnings & deductions table."""
    ot_month = salary_row.get("ot_month") or previous_month_value(salary_row.get("salary_month", ""))
    gross = float(salary_row.get("net_salary", 0))
    deduction_amount = float(slip_payload.get("deduction_amount", 0))
    available_advance = float(slip_payload.get("available_advance", 0))
    remaining_advance = float(slip_payload.get("remaining_advance", 0))
    salary_after_deduction = float(slip_payload.get("salary_after_deduction", 0))
    actual_paid_amount = float(slip_payload.get("actual_paid_amount", 0))
    company_balance_due = float(slip_payload.get("company_balance_due", 0))
    personal_vehicle_note = (salary_row.get("personal_vehicle_note") or "").strip()

    x = 16 * mm
    y = 103 * mm
    w = 179 * mm
    h = 66 * mm

    # Section title
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(x, y + h + 6.5 * mm, "SALARY DETAILS")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.4)
    pdf.drawString(x + 38 * mm, y + h + 6.5 * mm, "Earnings & Deductions")

    # Card background
    pdf.setFillColor(WHITE)
    pdf.roundRect(x, y, w, h, 5 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(x, y, w, h, 5 * mm, fill=0, stroke=1)

    # Orange header bar
    pdf.setFillColor(ORANGE)
    pdf.rect(x, y + h - 10 * mm, w, 10 * mm, fill=1, stroke=0)
    pdf.setFillColor(WHITE)
    pdf.setFont("Helvetica-Bold", 8.9)
    pdf.drawString(x + 6 * mm, y + h - 6.2 * mm, "EARNINGS")
    pdf.drawString(x + 63 * mm, y + h - 6.2 * mm, "AMOUNT")
    pdf.drawString(x + 95 * mm, y + h - 6.2 * mm, "DEDUCTIONS")
    pdf.drawString(x + 152 * mm, y + h - 6.2 * mm, "AMOUNT")

    # Vertical divider
    pdf.setStrokeColor(LINE)
    pdf.line(x + 89.5 * mm, y + 5 * mm, x + 89.5 * mm, y + h - 5 * mm)

    # Build earnings/deductions arrays
    personal_vehicle_label = "Personal / Vehicle"
    if personal_vehicle_note:
        personal_vehicle_label = f"Personal / Vehicle - {personal_vehicle_note}"
    ot_type = salary_row.get("ot_type") or "hours"
    ot_qty_label = "OT Extra Trips" if ot_type == "trips" else f"OT Hours ({format_month_label(ot_month)})"
    ot_qty = float(salary_row.get("ot_trips", 0)) if ot_type == "trips" else float(salary_row.get("ot_hours", 0))

    earnings = [
        ("Basic Salary", float(salary_row.get("basic_salary", 0))),
        (ot_qty_label, ot_qty),
        ("OT Amount", float(salary_row.get("ot_amount", 0))),
        (personal_vehicle_label, float(salary_row.get("personal_vehicle", 0))),
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

    # Bottom stat boxes
    metrics_y = 84 * mm
    _draw_stat_box(pdf, 16 * mm, metrics_y, 56 * mm, 14 * mm, "STORED SALARY", format_currency(gross))
    _draw_stat_box(pdf, 77.5 * mm, metrics_y, 56 * mm, 14 * mm, "ACTUAL PAID", format_currency(actual_paid_amount))
    _draw_stat_box(
        pdf, 139 * mm, metrics_y, 56 * mm, 14 * mm,
        "COMPANY BALANCE", f"{format_currency(company_balance_due)} AED",
        fill_color=BLUE, text_color=WHITE, border_color=BLUE,
    )
