"""
Driver Statement (Kata) PDF Template
======================================
Standalone template for generating driver kata/statement documents.

Usage:
    from kata_design import generate_kata_pdf
    generate_kata_pdf(company, driver, entries, summary, output_path)
"""

from base_design import *


def generate_kata_pdf(
    company: dict,
    driver: dict,
    entries: list,
    summary: dict,
    output_path: str,
    month_label: str = "",
) -> str:
    """Generate a standalone Driver Statement (Kata) PDF.

    Args:
        company:      Company profile dict (company_name, trn_no, address, etc.)
        driver:       Driver dict with keys:
                        full_name, driver_id, vehicle_no, shift, phone_number
        entries:      List of statement entry dicts, each with keys:
                        date, amount, paid_by, reason, balance_after, sort_group
        summary:      Summary dict with keys:
                        previous_balance, salary, received_total, remaining_salary
        output_path:  Absolute path for the output PDF file.
        month_label:  Display label for the month (e.g. "Aug 2026").

    Returns:
        Absolute path to the generated PDF.
    """
    company = company or {}
    driver = driver or {}
    entries = list(entries or [])
    summary = summary or {}

    pdf = canvas.Canvas(str(output_path), pagesize=A4)

    # ── 1. Header card ───────────────────────────────────────────────────────────
    _draw_header(pdf, company_profile=company)

    # ── 2. Title ─────────────────────────────────────────────────────────────────
    _draw_title(
        pdf,
        f"Driver Statement {month_label}",
        f"Kata / Hisaab  |  {driver.get('full_name', '-')}  |  {month_label}",
    )

    # ── 3. Driver info card ──────────────────────────────────────────────────────
    box_x = 16 * mm
    box_y = PAGE_HEIGHT - 112 * mm
    box_w = 178 * mm
    box_h = 19 * mm

    pdf.setFillColor(SOFT)
    pdf.roundRect(box_x, box_y, box_w, box_h, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(box_x + 6 * mm, box_y + 12.2 * mm, driver.get("full_name", "-"))
    pdf.setFont("Helvetica", 8.8)
    pdf.drawString(box_x + 6 * mm, box_y + 6 * mm, f"Driver ID: {driver.get('driver_id', '-')}")
    pdf.drawString(box_x + 48 * mm, box_y + 6 * mm, f"Vehicle: {driver.get('vehicle_no', '-')}")
    pdf.drawString(box_x + 96 * mm, box_y + 6 * mm, f"Shift: {driver.get('shift', '-')}")
    pdf.drawString(box_x + 132 * mm, box_y + 6 * mm, f"Phone: {driver.get('phone_number', '-')}")

    # ── 4. Paper summary stat boxes ──────────────────────────────────────────────
    _draw_paper_summary(pdf, summary, month_label)

    # ── 5. Transaction table ─────────────────────────────────────────────────────
    _draw_transaction_table(pdf, entries)

    # ── 6. Footer ────────────────────────────────────────────────────────────────
    _draw_footer_banner(pdf, company_profile=company)

    pdf.showPage()
    pdf.save()
    return str(output_path)


def _draw_paper_summary(pdf, summary, month_label):
    """Draw the 4 summary stat boxes."""
    start_x = 16 * mm
    y = PAGE_HEIGHT - 164 * mm
    gap = 4 * mm
    box_w = (178 * mm - gap * 3) / 4
    box_h = 18 * mm

    _draw_stat_box(
        pdf, start_x, y, box_w, box_h, "PREVIOUS BALANCE",
        f"AED {summary.get('previous_balance', 0)}",
        fill_color=WHITE, text_color=BLUE, border_color=LINE,
    )
    _draw_stat_box(
        pdf, start_x + (box_w + gap), y, box_w, box_h, "SALARY + OT",
        f"AED {summary.get('salary', 0)}",
        fill_color=WHITE, text_color=GREEN, border_color=LINE,
    )
    _draw_stat_box(
        pdf, start_x + 2 * (box_w + gap), y, box_w, box_h, "RECEIVED",
        f"AED {summary.get('received_total', 0)}",
        fill_color=WHITE, text_color=ORANGE, border_color=LINE,
    )
    _draw_stat_box(
        pdf, start_x + 3 * (box_w + gap), y, box_w, box_h, "REMAINING SALARY",
        f"AED {summary.get('remaining_salary', 0)}",
        fill_color=BLUE, text_color=WHITE, border_color=BLUE,
    )


def _draw_transaction_table(pdf, entries, top=None):
    """Draw the statement transaction table with In/Out/Balance columns."""
    top = top if top is not None else PAGE_HEIGHT - 180 * mm

    _draw_table_header(
        pdf, top,
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
        pdf.drawString(18 * mm, y, format_date_label(item.get("date")))

        etype = _entry_type(item.get("sort_group", 1))
        pdf.setFont("Helvetica", 7.6)
        pdf.drawString(30 * mm, y, etype)

        ref_text, ref_size = _fit_text(
            pdf, str(item.get("paid_by", "-")), "Helvetica", 7.4, 22 * mm, min_size=6.4,
        )
        pdf.setFont("Helvetica", ref_size)
        pdf.drawString(44 * mm, y, ref_text)

        detail_text, detail_size = _fit_text(
            pdf, str(item.get("reason", "-")), "Helvetica", 7.8, 44 * mm, min_size=6.6,
        )
        pdf.setFont("Helvetica", detail_size)
        pdf.drawString(70 * mm, y, detail_text)

        amount = float(item.get("amount", 0.0))
        sg = item.get("sort_group", 1)
        is_incoming = sg == 0
        incoming = amount if is_incoming else 0.0
        outgoing = amount if not is_incoming and sg >= 1 else 0.0

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

    # ── Totals row ───────────────────────────────────────────────────────────────
    if entries:
        pdf.setStrokeColor(LINE)
        pdf.line(16 * mm, y + 2 * mm, 194 * mm, y + 2 * mm)
        total_in = sum(float(item.get("amount", 0)) for item in entries if item.get("sort_group") == 0)
        total_out = sum(float(item.get("amount", 0)) for item in entries if item.get("sort_group", 1) >= 1)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.setFillColor(BLUE_DARK)
        pdf.drawString(18 * mm, y - 3 * mm, "Totals")
        pdf.setFillColor(GREEN)
        pdf.drawRightString(140 * mm, y - 3 * mm, format_currency(total_in))
        pdf.setFillColor(ORANGE)
        pdf.drawRightString(162 * mm, y - 3 * mm, format_currency(total_out))
        pdf.setFillColor(BLUE_DARK)
        pdf.drawRightString(194 * mm, y - 3 * mm, format_currency(max(total_in - total_out, 0.0)))
