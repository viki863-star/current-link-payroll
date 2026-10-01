"""Merged PDF (and ZIP of per-driver PDFs) for Driving License + Emirates ID.

Images live as base64 columns on ``employees`` — the additive columns added by
``hr.routes.ensure_employees_table`` (nothing existing is touched).

Both sides of a document are drawn **side by side** so front + back land on the
same printable page: one employee -> one readable PDF, and "Download all"
returns a ZIP holding one such PDF per driver / operator.
"""

import base64
import io
import re
import zipfile
from datetime import date

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = A4
MARGIN = 36
TOP = PAGE_H - 40
BOTTOM = 46
CONTENT_W = PAGE_W - 2 * MARGIN

BOX_GAP = 14
BOX_H = 168          # front/back boxes are drawn side by side at this height
IMAGE_MAX_PX = 1600  # downscale before embedding so the PDF stays small
JPEG_QUALITY = 85

ACCENT = HexColor("#1a3a5c")
MUTED = HexColor("#64748b")
LINE = HexColor("#cbd5e1")
DASH = HexColor("#94a3b8")
SOFT = HexColor("#f1f5f9")

SECTIONS = (
    {
        "title": "Driving License",
        "no_label": "License No.",
        "no_field": "driving_license_no",
        "expiry_field": "driving_license_expiry",
        "front": "driving_license_front",
        "back": "driving_license_back",
    },
    {
        "title": "Emirates ID",
        "no_label": "EID No.",
        "no_field": "emirates_id_no",
        "expiry_field": None,
        "front": "emirates_id_front",
        "back": "emirates_id_back",
    },
)

IMAGE_FIELDS = tuple(f for s in SECTIONS for f in (s["front"], s["back"]))


def employee_has_ids(emp) -> bool:
    """True when at least one side of either document has been uploaded."""
    for field in IMAGE_FIELDS:
        value = emp.get(field) if hasattr(emp, "get") else None
        if value and str(value).strip():
            return True
    return False


def _image_reader(b64data):
    """base64 image -> reportlab ImageReader, normalized (EXIF, RGB, <=1600px)."""
    if not b64data:
        return None
    try:
        from PIL import Image, ImageOps

        raw = base64.b64decode(b64data)
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        if max(img.size) > IMAGE_MAX_PX:
            img.thumbnail((IMAGE_MAX_PX, IMAGE_MAX_PX))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=JPEG_QUALITY)
        out.seek(0)
        return ImageReader(out)
    except Exception:
        return None


def _draw_fit_string(pdf, text, x, y, max_width, max_size=12.0, min_size=7.0, font="Helvetica-Bold"):
    text = str(text or "")
    size = max_size
    while size > min_size and pdf.stringWidth(text, font, size) > max_width:
        size -= 0.5
    pdf.setFont(font, size)
    pdf.drawString(x, y, text)


class _IdsPdf:
    """Small canvas wrapper that keeps the header + page breaks in one place."""

    def __init__(self, company_name, emp):
        self.emp = emp
        self.company_name = company_name or "Current Link"
        self.buf = io.BytesIO()
        self.pdf = canvas.Canvas(self.buf, pagesize=A4)
        self.pdf.setTitle(f"{emp.get('employee_id') or 'Employee'} - License and Emirates ID")
        self.pages = 0
        self.y = 0.0
        self._new_page()

    def _new_page(self, continued=False):
        if self.pages:
            self.pdf.showPage()
        self.pages += 1
        pdf = self.pdf
        y = TOP

        pdf.setFillColor(ACCENT)
        pdf.setFont("Helvetica-Bold", 15)
        pdf.drawString(MARGIN, y - 14, self.company_name.strip()[:70])
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 8.5)
        title = "Driving License & Emirates ID"
        if continued:
            title += " (continued)"
        pdf.drawRightString(PAGE_W - MARGIN, y - 14, title)
        pdf.drawString(MARGIN, y - 27, f"Generated on {date.today().isoformat()}")

        y -= 44
        pdf.setFillColor(black)
        _draw_fit_string(
            pdf,
            f"{self.emp.get('full_name') or ''}  ({self.emp.get('employee_id') or ''})",
            MARGIN,
            y,
            CONTENT_W,
        )
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 9)
        meta = "  ·  ".join(
            str(self.emp.get(k) or "")
            for k in ("employee_type", "department", "status")
            if self.emp.get(k)
        )
        pdf.drawString(MARGIN, y - 14, meta)

        pdf.setStrokeColor(LINE)
        pdf.setLineWidth(1)
        pdf.line(MARGIN, y - 24, PAGE_W - MARGIN, y - 24)
        self.y = y - 24 - 16

    def _ensure(self, height):
        if self.y - height < BOTTOM:
            self._new_page(continued=True)

    def add_section(self, title, meta_pairs, front_b64, back_b64):
        block_h = 27 + 14 + BOX_H + 26
        self._ensure(block_h)
        pdf = self.pdf
        y = self.y

        pdf.setFillColor(SOFT)
        pdf.roundRect(MARGIN, y - 17, CONTENT_W, 17, 3, stroke=0, fill=1)
        pdf.setFillColor(ACCENT)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(MARGIN + 8, y - 12.5, title.upper())
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 8.5)
        meta_text = "     ".join(f"{label}: {value}" for label, value in meta_pairs if value)
        if meta_text:
            pdf.drawRightString(PAGE_W - MARGIN - 8, y - 12.5, meta_text[:90])
        y -= 17 + 12

        box_w = (CONTENT_W - BOX_GAP) / 2
        self._box(MARGIN, y, box_w, front_b64, "Front side")
        self._box(MARGIN + box_w + BOX_GAP, y, box_w, back_b64, "Back side")
        self.y = y - BOX_H - 26

    def _box(self, x, y_top, w, b64, caption):
        pdf = self.pdf
        bottom = y_top - BOX_H

        pdf.saveState()
        pdf.setStrokeColor(DASH)
        pdf.setLineWidth(1)
        pdf.setDash(4, 3)
        pdf.setFillColor(white)
        pdf.rect(x, bottom, w, BOX_H, stroke=1, fill=1)
        pdf.setDash()

        reader = _image_reader(b64) if b64 else None
        if reader is None:
            pdf.setFillColor(DASH if not b64 else HexColor("#dc2626"))
            pdf.setFont("Helvetica-Oblique", 9)
            pdf.drawCentredString(
                x + w / 2,
                bottom + BOX_H / 2 - 3,
                "Not uploaded" if not b64 else "Preview unavailable",
            )
        else:
            try:
                iw, ih = reader.getSize()
            except Exception:
                iw = ih = 0
            if iw and ih:
                scale = min((w - 12) / iw, (BOX_H - 12) / ih)
                dw, dh = iw * scale, ih * scale
                pdf.drawImage(
                    reader,
                    x + (w - dw) / 2,
                    bottom + (BOX_H - dh) / 2,
                    width=dw,
                    height=dh,
                )

        pdf.setStrokeColor(DASH)
        pdf.setLineWidth(0.7)
        pdf.setDash(3, 2)
        pdf.rect(x, bottom, w, BOX_H, stroke=1, fill=0)
        pdf.setDash()
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 8)
        pdf.drawCentredString(x + w / 2, bottom - 13, caption)
        pdf.restoreState()

    def save(self):
        self.pdf.save()
        return self.buf.getvalue()


def build_employee_ids_pdf(company_name, emp) -> bytes:
    """One employee -> one PDF carrying DL front/back + Emirates ID front/back."""
    emp = dict(emp)
    builder = _IdsPdf(company_name, emp)
    for section in SECTIONS:
        meta = []
        no_label, no_value = section["no_label"], emp.get(section["no_field"])
        if no_value:
            meta.append((no_label, str(no_value).strip()))
        if section["expiry_field"]:
            expiry = emp.get(section["expiry_field"])
            if expiry:
                meta.append(("Expiry", str(expiry).strip()))
        builder.add_section(
            section["title"],
            meta,
            emp.get(section["front"]) or "",
            emp.get(section["back"]) or "",
        )
    return builder.save()


def _safe_pdf_name(emp, used: set) -> str:
    base = f"{emp.get('employee_id') or 'EMP'}_{emp.get('full_name') or 'employee'}"
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", base).strip("_") or "employee"
    name = f"{base}.pdf"
    counter = 2
    while name in used:
        name = f"{base}_{counter}.pdf"
        counter += 1
    used.add(name)
    return name


def write_ids_zip(company_name, employees, out) -> int:
    """Write one merged PDF per employee into ``out`` (seekable file object).

    Only employees that actually have an image are included; returns the count.
    """
    written = 0
    used: set = set()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for emp in employees:
            emp = dict(emp)
            if not employee_has_ids(emp):
                continue
            zf.writestr(_safe_pdf_name(emp, used), build_employee_ids_pdf(company_name, emp))
            written += 1
    return written
