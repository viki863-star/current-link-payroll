from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


PAGE_WIDTH, PAGE_HEIGHT = A4
BLUE = colors.HexColor("#1C568B")
BLUE_DARK = colors.HexColor("#15335D")
BLUE_SOFT = colors.HexColor("#EAF2FB")
ORANGE = colors.HexColor("#E6871F")
GREEN = colors.HexColor("#2CB15C")
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
    _draw_title(pdf, f"Salary Slip {format_month_label(salary_row['salary_month'])}")
    _draw_salary_summary(pdf, driver, salary_row, slip_payload)
    _draw_salary_breakdown(pdf, salary_row, slip_payload)
    _draw_salary_footer(pdf, driver, assets_dir, generated_dir)
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
    _draw_title(pdf, "Driver KATA Statement")

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
    _draw_title(pdf, "Owner Fund Kata")

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


def _draw_header(pdf: canvas.Canvas, assets_dir: str) -> None:
    banner = Path(assets_dir) / "current-link-header.png"
    if banner.exists():
        pdf.drawImage(
            str(banner),
            15 * mm,
            PAGE_HEIGHT - 34 * mm,
            width=180 * mm,
            height=22 * mm,
            preserveAspectRatio=True,
            mask="auto",
        )
    pdf.setFillColor(BLUE)
    pdf.rect(15 * mm, PAGE_HEIGHT - 39 * mm, 180 * mm, 1.8 * mm, fill=1, stroke=0)


def _draw_title(pdf: canvas.Canvas, title: str) -> None:
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 49 * mm, title)


def _draw_salary_summary(pdf: canvas.Canvas, driver, salary_row, slip_payload) -> None:
    left_x = 16 * mm
    top_y = PAGE_HEIGHT - 57 * mm

    pdf.setFillColor(colors.white)
    pdf.roundRect(left_x, top_y - 55 * mm, 118 * mm, 51 * mm, 5 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(left_x, top_y - 55 * mm, 118 * mm, 51 * mm, 5 * mm, fill=0, stroke=1)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left_x + 5 * mm, top_y - 8 * mm, "DRIVER SUMMARY")

    rows = [
        ("Driver Name", driver["full_name"]),
        ("Driver ID", driver["driver_id"]),
        ("Phone Number", driver["phone_number"] if "phone_number" in driver.keys() else "-"),
        ("Pay Period", format_month_label(salary_row["salary_month"])),
        ("Vehicle Number", driver["vehicle_no"]),
        ("Shift", driver["shift"]),
        ("Join Date", format_date_label(driver["duty_start"])),
    ]

    y = top_y - 14 * mm
    for label, value in rows:
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 8.0)
        pdf.drawString(left_x + 5 * mm, y, label)
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica-Bold", 8.2)
        pdf.drawString(left_x + 39 * mm, y, str(value or "-"))
        y -= 5.1 * mm

    box_x = 140 * mm
    box_y = top_y - 34 * mm
    pdf.setFillColor(BLUE)
    pdf.roundRect(box_x, box_y, 43 * mm, 26 * mm, 5 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawCentredString(box_x + 21.5 * mm, box_y + 15 * mm, f"{format_currency(float(slip_payload['net_payable']))} AED")
    pdf.setFont("Helvetica", 7.5)
    pdf.drawCentredString(box_x + 21.5 * mm, box_y + 6 * mm, "Total Net Pay")

    info_x = 140 * mm
    info_y = top_y - 56 * mm
    pdf.setFillColor(BLUE_SOFT)
    pdf.roundRect(info_x, info_y, 43 * mm, 20 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawString(info_x + 4 * mm, info_y + 14 * mm, f"Driver ID: {driver['driver_id']}")
    pdf.drawString(info_x + 4 * mm, info_y + 9 * mm, f"Source: {slip_payload['payment_source']}")
    paid_by = slip_payload.get("paid_by") or "-"
    pdf.setFont("Helvetica", 7.3)
    pdf.drawString(info_x + 4 * mm, info_y + 4 * mm, f"Paid By: {paid_by[:24]}")


def _draw_salary_breakdown(pdf: canvas.Canvas, salary_row, slip_payload) -> None:
    gross = float(salary_row["net_salary"])
    deduction_amount = float(slip_payload["deduction_amount"])
    available_advance = float(slip_payload["available_advance"])
    remaining_advance = float(slip_payload["remaining_advance"])
    net_payable = float(slip_payload["net_payable"])

    x = 16 * mm
    y = PAGE_HEIGHT - 138 * mm
    w = 179 * mm
    h = 63 * mm

    pdf.setFillColor(colors.white)
    pdf.roundRect(x, y, w, h, 5 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(x, y, w, h, 5 * mm, fill=0, stroke=1)

    pdf.setFillColor(ORANGE)
    pdf.rect(x, y + h - 9 * mm, w, 9 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 8.7)
    pdf.drawString(x + 4 * mm, y + h - 5.7 * mm, "EARNINGS")
    pdf.drawString(x + 60 * mm, y + h - 5.7 * mm, "AMOUNT")
    pdf.drawString(x + 95 * mm, y + h - 5.7 * mm, "DEDUCTIONS")
    pdf.drawString(x + 149 * mm, y + h - 5.7 * mm, "AMOUNT")

    pdf.setStrokeColor(LINE)
    pdf.line(x + 88 * mm, y + 4 * mm, x + 88 * mm, y + h - 4 * mm)

    earnings = [
        ("Basic Salary", float(salary_row["basic_salary"])),
        ("OT Hours", float(salary_row["ot_hours"])),
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

    row_y = y + h - 16 * mm
    for index in range(5):
        left_label, left_value = earnings[index]
        right_label, right_value = deductions[index]
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 8.2)
        pdf.drawString(x + 4 * mm, row_y, left_label)
        pdf.drawString(x + 92 * mm, row_y, right_label)
        pdf.setFillColor(TEXT)
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.drawRightString(x + 83 * mm, row_y, format_currency(left_value))
        pdf.drawRightString(x + 173 * mm, row_y, format_currency(right_value))
        row_y -= 7.6 * mm

    total_y = y - 13 * mm
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(x + 1 * mm, total_y, "TOTAL NET PAYABLE")
    pdf.setFillColor(BLUE_DARK)
    pdf.drawRightString(x + w - 3 * mm, total_y, format_currency(net_payable))


def _draw_salary_footer(pdf: canvas.Canvas, driver, assets_dir: str, generated_dir: str) -> None:
    card_x = 16 * mm
    card_y = 34 * mm
    card_w = 58 * mm
    card_h = 34 * mm
    pdf.setFillColor(SOFT)
    pdf.roundRect(card_x, card_y, card_w, card_h, 4 * mm, fill=1, stroke=0)

    if not _draw_driver_photo(pdf, driver, generated_dir, card_x + 2.5 * mm, card_y + 2.5 * mm, card_w - 5 * mm, card_h - 5 * mm):
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawCentredString(card_x + card_w / 2, card_y + card_h / 2, "NO PHOTO")

    note_x = 82 * mm
    note_y = 39 * mm
    pdf.setFillColor(BLUE_SOFT)
    pdf.roundRect(note_x, note_y, 52 * mm, 24 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(note_x + 4 * mm, note_y + 16 * mm, "Payment Status")
    pdf.setFillColor(GREEN)
    pdf.setFont("Helvetica-BoldOblique", 17)
    pdf.drawString(note_x + 4 * mm, note_y + 6 * mm, "PAID")

    sign_x = 146 * mm
    sign_y = 46 * mm
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(sign_x, sign_y + 8 * mm, "Driver Sign")
    pdf.line(sign_x + 22 * mm, sign_y + 8.5 * mm, sign_x + 46 * mm, sign_y + 8.5 * mm)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.4)
    pdf.drawString(82 * mm, 31 * mm, "This is a system-generated salary slip.")
    _draw_footer_banner(pdf, assets_dir)


def _draw_driver_photo(pdf: canvas.Canvas, driver, generated_dir: str, x: float, y: float, w: float, h: float) -> bool:
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
        pdf.drawImage(
            str(footer),
            18 * mm,
            12 * mm,
            width=174 * mm,
            height=18 * mm,
            preserveAspectRatio=True,
            mask="auto",
        )


def format_currency(value: float) -> str:
    return f"{value:,.2f}"


def format_month_label(value: str) -> str:
    if not value or value == "-":
        return value
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%b %Y")
    except ValueError:
        return value


def format_date_label(value: str | None) -> str:
    if not value:
        return "-"
    for pattern in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(value, pattern).strftime("%d-%b-%Y")
        except ValueError:
            continue
    return value
