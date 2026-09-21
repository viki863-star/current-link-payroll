"""
PDF Design System - Base Module
===============================
Colors, fonts, and reusable helper functions for all PDF templates.

Usage:
    from base_design import *
    pdf = canvas.Canvas("output.pdf", pagesize=A4)
    _draw_header(pdf, company_profile=company)
"""

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

# ── Color Palette ──────────────────────────────────────────────────────────────
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
WHITE = colors.white


# ── Utility Functions ──────────────────────────────────────────────────────────

def format_currency(value: float) -> str:
    """Format number with commas and 2 decimal places."""
    return f"{value:,.2f}"


def format_month_label(value: str) -> str:
    """Convert '2026-08' to 'Aug 2026'."""
    if not value or value == "-":
        return value
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%b %Y")
    except ValueError:
        return value


def format_date_label(value) -> str:
    """Convert date string or object to '01-Aug-2026' format."""
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


def previous_month_value(value: str) -> str:
    """Get previous month string from '2026-08' -> '2026-07'."""
    if not value or value == "-":
        return value
    try:
        month_date = datetime.strptime(f"{value}-01", "%Y-%m-%d")
    except ValueError:
        return value
    if month_date.month == 1:
        return f"{month_date.year - 1}-12"
    return f"{month_date.year}-{month_date.month - 1:02d}"


# ── Text Fitting ───────────────────────────────────────────────────────────────

def _fit_text(pdf: canvas.Canvas, text: str, font_name: str, font_size: float,
              max_width: float, min_size: float = 6.4):
    """Fit text to max_width by reducing font size or clipping with '...'."""
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


def _wrap_text_lines(pdf: canvas.Canvas, text: str, font_name: str, font_size: float,
                     max_width: float, *, max_lines: int = 2, min_size: float = 6.0):
    """Wrap text into multiple lines fitting max_width."""
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


# ── Drawing Helpers ────────────────────────────────────────────────────────────

def _draw_header(pdf: canvas.Canvas, assets_dir: str = "", company_profile: dict | None = None) -> None:
    """Draw standard company header card with logo, name, address, TRN."""
    company = company_profile or {}
    header_x = 15 * mm
    header_y = PAGE_HEIGHT - 50 * mm
    header_w = 180 * mm
    header_h = 44 * mm

    logo_data = company.get("logo_data")
    logo_type = company.get("logo_type")

    pdf.setFillColor(WHITE)
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
            pdf.drawImage(logo_img, header_x + 3 * mm, header_y + (header_h - target) / 2,
                          width=target, height=target, preserveAspectRatio=True, mask="auto")
            text_x = header_x + 42 * mm
            text_area_w = header_w - 48 * mm
        except Exception:
            pass

    cy = header_y + header_h / 2

    c_name = company.get("company_name", "COMPANY NAME")
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
    """Draw centered document title below header."""
    pdf.setFillColor(BLUE_DARK)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 62 * mm, title)
    if subtitle:
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 7.5)
        pdf.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 67 * mm, subtitle)


def _draw_label_value_row(pdf: canvas.Canvas, x: float, y: float,
                         label_width: float, value_width: float,
                         label: str, value: str) -> None:
    """Draw a label-value pair (label in muted, value in bold)."""
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.8)
    pdf.drawString(x, y, label)
    pdf.setFillColor(TEXT)
    text, size = _fit_text(pdf, str(value or "-"), "Helvetica-Bold", 8.2, value_width)
    pdf.setFont("Helvetica-Bold", size)
    pdf.drawString(x + label_width, y, text)


def _draw_small_meta_row(pdf: canvas.Canvas, x: float, y: float,
                         label: str, value: str, value_width: float) -> None:
    """Draw compact label: value pair for metadata rows."""
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.9)
    label_text = f"{label}:"
    pdf.drawString(x, y, label_text)
    pdf.setFillColor(TEXT)
    text, size = _fit_text(pdf, str(value or "-"), "Helvetica-Bold", 7.1, value_width)
    pdf.setFont("Helvetica-Bold", size)
    label_width = pdf.stringWidth(label_text, "Helvetica", 6.9) + (2 * mm)
    pdf.drawRightString(x + label_width + value_width, y, text)


def _draw_stat_box(pdf: canvas.Canvas, x: float, y: float, w: float, h: float,
                   label: str, value: str, *,
                   fill_color=colors.white, text_color=TEXT, border_color=LINE) -> None:
    """Draw a stat box with label on top and value below."""
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


def _draw_invoice_header(pdf, company_profile, title_text='', logo_size=14*mm):
    """Draw invoice-style header with company info and title on right."""
    company = company_profile or {}
    c_name = company.get('company_name', 'COMPANY NAME')
    c_addr = company.get('address', '')
    c_ph = company.get('phone_number', '')
    c_em = company.get('email', '')
    c_trn = company.get('trn_no', '')

    left_x = 16 * mm
    top_y = PAGE_HEIGHT - 38 * mm
    logo_data = company.get('logo_data')

    logo_x = left_x
    if logo_data:
        try:
            lb = base64.b64decode(logo_data)
            logo_img = ImageReader(BytesIO(lb))
            pdf.drawImage(logo_img, left_x, top_y - logo_size, width=logo_size, height=logo_size,
                          preserveAspectRatio=True, mask='auto')
            logo_x = left_x + logo_size + 4 * mm
        except Exception:
            pass

    pdf.setFillColor(BLUE_DARK)
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(logo_x, top_y, c_name)

    pdf.setFillColor(MUTED)
    pdf.setFont('Helvetica', 7)
    ci_y = top_y - 5 * mm
    if c_addr:
        pdf.drawString(logo_x, ci_y, c_addr)
        ci_y -= 4 * mm

    contact_parts = []
    if c_ph: contact_parts.append(f'Phone: {c_ph}')
    if c_em: contact_parts.append(f'Email: {c_em}')
    if contact_parts:
        pdf.drawString(logo_x, ci_y, ' &middot; '.join(contact_parts))
        ci_y -= 4 * mm
    else:
        ci_y -= 2 * mm

    if c_trn:
        pdf.setFillColor(BLUE_DARK)
        pdf.setFont('Helvetica-Bold', 7)
        pdf.drawString(logo_x, ci_y, f'TRN: {c_trn}')

    if title_text:
        pdf.setFillColor(BLUE_DARK)
        pdf.setFont('Helvetica-Bold', 14)
        pdf.drawRightString(PAGE_WIDTH - 16 * mm, top_y, title_text)

    hr_y = top_y - 28 * mm
    pdf.setFillColor(BLUE)
    pdf.rect(16 * mm, hr_y, PAGE_WIDTH - 32 * mm, 1.5 * mm, fill=1, stroke=0)


def _draw_invoice_party_box(pdf: canvas.Canvas, x: float, y: float, w: float, h: float,
                            heading: str, title: str, secondary: str, address: str,
                            trn_no: str, contact: str) -> None:
    """Draw a party info box (used for buyer/seller in invoices)."""
    pdf.setFillColor(WHITE)
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


def _draw_footer_banner(pdf: canvas.Canvas, assets_dir: str = "",
                        show_top_rule: bool = True, company_profile: dict | None = None) -> None:
    """Draw standard footer banner with company name and contact."""
    company = company_profile or {}
    footer_w = 180 * mm

    if show_top_rule:
        pdf.setFillColor(ORANGE)
        pdf.rect(15 * mm, 30 * mm, footer_w, 1.2 * mm, fill=1, stroke=0)

    pdf.setFillColor(WHITE)
    pdf.roundRect(15 * mm, 8 * mm, footer_w, 22 * mm, 4 * mm, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(15 * mm, 8 * mm, footer_w, 22 * mm, 4 * mm, fill=0, stroke=1)

    c_name = (company.get("company_name", "COMPANY NAME")).upper()
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


def _draw_table_header(pdf: canvas.Canvas, top: float, headers: list, x_positions: list) -> None:
    """Draw table header row with blue background."""
    pdf.setFillColor(BLUE)
    pdf.rect(15 * mm, top - 5 * mm, 180 * mm, 7 * mm, fill=1, stroke=0)
    pdf.setFillColor(WHITE)
    pdf.setFont("Helvetica-Bold", 7)
    for header, x in zip(headers, x_positions):
        pdf.drawString(x, top - 3 * mm, header)


def _draw_paid_stamp(pdf: canvas.Canvas, x: float, y: float) -> None:
    """Draw a rotated 'PAID' stamp."""
    pdf.saveState()
    pdf.translate(x, y)
    pdf.rotate(-16)
    pdf.setStrokeColor(RED)
    pdf.setFillColor(WHITE)
    pdf.roundRect(-12 * mm, -4 * mm, 24 * mm, 8 * mm, 3 * mm, fill=1, stroke=1)
    pdf.setFillColor(RED)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawCentredString(0, -0.4 * mm, "PAID")
    pdf.restoreState()
