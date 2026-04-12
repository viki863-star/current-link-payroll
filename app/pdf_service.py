from __future__ import annotations

import base64
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


def generate_kata_pdf(driver, salary_rows, transactions, output_dir: str, assets_dir: str) -> str:
    output_path = Path(output_dir) / f"{driver['driver_id']}_kata-statement.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    entries = []
    for salary in salary_rows:
        entries.append(
            {
                "date": salary["entry_date"],
                "month": salary["salary_month"],
                "credit": float(salary["net_salary"]),
                "debit": 0.0,
                "details": "Salary Stored",
            }
        )
    for txn in transactions:
        entries.append(
            {
                "date": txn["entry_date"],
                "month": "-",
                "credit": 0.0,
                "debit": float(txn["amount"]),
                "details": f"{txn['txn_type']} / {txn['source']}",
            }
        )
    entries.sort(key=lambda item: item["date"])

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    _draw_header(pdf, assets_dir)
    _draw_title(pdf, "Driver KATA Statement", "Running salary and transaction movement for this driver")

    pdf.setFillColor(SOFT)
    pdf.roundRect(16 * mm, PAGE_HEIGHT - 110 * mm, 178 * mm, 20 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(22 * mm, PAGE_HEIGHT - 98 * mm, driver["full_name"])
    pdf.setFont("Helvetica", 9)
    pdf.drawString(22 * mm, PAGE_HEIGHT - 104 * mm, f"Driver ID: {driver['driver_id']}")
    pdf.drawString(78 * mm, PAGE_HEIGHT - 104 * mm, f"Vehicle: {driver['vehicle_no']}")
    pdf.drawString(132 * mm, PAGE_HEIGHT - 104 * mm, f"Shift: {driver['shift']}")

    top = PAGE_HEIGHT - 122 * mm
    _draw_table_header(
        pdf,
        top,
        ["Date", "Month", "Salary Added", "Paid / Received", "Details", "Balance"],
        [18, 44, 74, 106, 136, 184],
    )

    balance = 0.0
    y = top - 7 * mm
    pdf.setFont("Helvetica", 8.5)
    for item in entries[:24]:
        balance += item["credit"] - item["debit"]
        pdf.setFillColor(colors.black)
        pdf.drawString(18 * mm, y, format_date_label(item["date"]))
        pdf.drawString(44 * mm, y, format_month_label(item["month"]) if item["month"] != "-" else "-")
        pdf.drawRightString(100 * mm, y, format_currency(item["credit"]) if item["credit"] else "0.00")
        pdf.drawRightString(132 * mm, y, format_currency(item["debit"]) if item["debit"] else "0.00")
        pdf.drawString(136 * mm, y, item["details"][:22])
        pdf.drawRightString(190 * mm, y, format_currency(balance))
        y -= 6.5 * mm
        if y < 54 * mm:
            break

    total_salary = sum(float(row["net_salary"]) for row in salary_rows)
    total_paid = sum(float(item["amount"]) for item in transactions)
    _draw_kata_summary(pdf, total_salary, total_paid, balance)
    _draw_footer_banner(pdf, assets_dir)

    pdf.showPage()
    pdf.save()
    return str(output_path)


def generate_owner_fund_pdf(statement_rows, totals, output_dir: str, assets_dir: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(output_dir) / f"owner-fund-kata_{timestamp}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    _draw_header(pdf, assets_dir)
    _draw_title(pdf, "Owner Fund Kata", "Incoming owner funds, outgoing usage and running balance")

    pdf.setFillColor(SOFT)
    pdf.roundRect(16 * mm, PAGE_HEIGHT - 104 * mm, 178 * mm, 18 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(22 * mm, PAGE_HEIGHT - 94 * mm, f"Incoming: AED {format_currency(float(totals['incoming']))}")
    pdf.drawString(84 * mm, PAGE_HEIGHT - 94 * mm, f"Used: AED {format_currency(float(totals['outgoing']))}")
    pdf.drawString(138 * mm, PAGE_HEIGHT - 94 * mm, f"Balance: AED {format_currency(float(totals['balance']))}")

    top = PAGE_HEIGHT - 118 * mm
    _draw_table_header(
        pdf,
        top,
        ["Date", "Reference", "Details", "Incoming", "Outgoing", "Balance"],
        [18, 42, 96, 146, 170, 190],
    )

    y = top - 7 * mm
    pdf.setFont("Helvetica", 8.2)
    for row in statement_rows[:24]:
        pdf.setFillColor(TEXT)
        pdf.drawString(18 * mm, y, format_date_label(row["entry_date"]))
        pdf.drawString(42 * mm, y, str(row["reference"])[:24])
        details = f"{row['party']} | {row['details']}" if row["party"] else str(row["details"])
        pdf.drawString(96 * mm, y, details[:28])
        pdf.drawRightString(163 * mm, y, format_currency(float(row["incoming"])))
        pdf.drawRightString(184 * mm, y, format_currency(float(row["outgoing"])))
        pdf.drawRightString(193 * mm, y, format_currency(float(row["balance"])))
        y -= 6.3 * mm
        if y < 44 * mm:
            break

    _draw_footer_banner(pdf, assets_dir)
    pdf.showPage()
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


def _draw_kata_summary(pdf: canvas.Canvas, total_salary: float, total_paid: float, balance: float) -> None:
    left = 16 * mm
    top = 44 * mm
    pdf.setFillColor(SOFT)
    pdf.roundRect(left, top, 64 * mm, 24 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left + 4 * mm, top + 17 * mm, "SUMMARY")
    pdf.setFont("Helvetica", 8.5)
    rows = [
        ("Total Salary Added", total_salary),
        ("Total Paid / Received", total_paid),
        ("Balance", balance),
    ]
    y = top + 11 * mm
    for label, value in rows:
        pdf.drawString(left + 4 * mm, y, label)
        pdf.drawRightString(left + 58 * mm, y, format_currency(value))
        y -= 6 * mm


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
    pdf.drawString(x, y, f"{label}:")
    pdf.setFillColor(TEXT)
    text, size = _fit_text(pdf, str(value or "-"), "Helvetica-Bold", 7.1, value_width)
    pdf.setFont("Helvetica-Bold", size)
    pdf.drawRightString(x + 46 * mm, y, text)


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
    for pattern in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(value, pattern).strftime("%d-%b-%Y")
        except ValueError:
            continue
    return value
