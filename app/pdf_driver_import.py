from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


SHIFT_TOKENS = {"single", "day", "night"}
STATUS_TOKENS = {"Active", "Inactive"}
DATE_PATTERNS = ("%m/%d/%y", "%m/%d/%Y", "%m/%-d/%Y", "%m/%-d/%y")


@dataclass
class DriverPdfRecord:
    driver_id: str
    full_name: str
    phone_number: str
    vehicle_no: str
    shift: str
    vehicle_type: str
    basic_salary: float
    ot_rate: float
    duty_start: str
    photo_name: str
    status: str
    remarks: str


def load_driver_records_from_pdf(pdf_path: str) -> list[DriverPdfRecord]:
    source = Path(pdf_path)
    if not source.exists():
        raise FileNotFoundError(f"PDF not found: {source}")

    reader = PdfReader(str(source))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return _parse_driver_pdf_text(text)


def load_driver_records_from_pdf_bytes(pdf_bytes: bytes) -> list[DriverPdfRecord]:
    if not pdf_bytes:
        return []
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return _parse_driver_pdf_text(text)


def _parse_driver_pdf_text(text: str) -> list[DriverPdfRecord]:
    rows: list[DriverPdfRecord] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line or not line.startswith("DRV-"):
            continue
        record = _parse_driver_line(line)
        if record is not None:
            rows.append(record)
    return rows


def _parse_driver_line(line: str) -> DriverPdfRecord | None:
    tokens = line.split()
    if len(tokens) < 3:
        return None

    driver_id = tokens[0]
    try:
        status_index = next(index for index, token in enumerate(tokens) if token in STATUS_TOKENS)
        status = tokens[status_index]
        trailing_tokens = tokens[status_index + 1 :]
    except StopIteration:
        status_index = len(tokens)
        status = "Active"
        trailing_tokens = []

    try:
        shift_index = next(
            index for index in range(1, status_index) if tokens[index].lower() in SHIFT_TOKENS
        )
    except StopIteration:
        return None

    if shift_index < 2:
        return None

    vehicle_no = tokens[shift_index - 1]
    full_name = " ".join(tokens[1 : shift_index - 1]).strip()
    shift = _normalize_shift(tokens[shift_index])
    remarks = " ".join(trailing_tokens).strip()
    phone_number = _extract_phone(remarks)
    if phone_number:
        remarks = remarks.replace(phone_number, "").strip()

    detail_tokens = tokens[shift_index + 1 : status_index]
    duty_start = ""
    if detail_tokens and _looks_like_date(detail_tokens[-1]):
        duty_start = _normalize_date(detail_tokens.pop())

    numeric_tail: list[str] = []
    while detail_tokens and _looks_numeric(detail_tokens[-1]):
        numeric_tail.insert(0, detail_tokens.pop())

    vehicle_type_tokens = detail_tokens[:]
    basic_salary = 0.0
    ot_rate = 0.0

    if numeric_tail:
        if vehicle_type_tokens:
            if len(numeric_tail) >= 2:
                basic_salary = _to_float(numeric_tail[0])
                ot_rate = _to_float(numeric_tail[1])
            else:
                basic_salary = _to_float(numeric_tail[0])
        else:
            basic_salary = _to_float(numeric_tail[-1])
            vehicle_type_tokens = numeric_tail[:-1]

    vehicle_type = " ".join(vehicle_type_tokens).strip() or "General"

    return DriverPdfRecord(
        driver_id=driver_id,
        full_name=full_name or driver_id,
        phone_number=_normalize_phone(phone_number),
        vehicle_no=vehicle_no,
        shift=shift,
        vehicle_type=vehicle_type,
        basic_salary=basic_salary,
        ot_rate=ot_rate,
        duty_start=duty_start,
        photo_name="",
        status=status,
        remarks=remarks,
    )


def _looks_numeric(value: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", value))


def _looks_like_date(value: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", value))


def _normalize_date(value: str) -> str:
    clean = value.strip()
    patterns = [("%m/%d/%y", False), ("%m/%d/%Y", False)]
    for pattern, _ in patterns:
        try:
            return datetime.strptime(clean, pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    parts = clean.split("/")
    if len(parts) == 3:
        month, day, year = parts
        if len(year) == 2:
            year = f"20{year}"
        try:
            return datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d")
        except ValueError:
            return clean
    return clean


def _extract_phone(text: str) -> str:
    match = re.search(r"(\+?\d[\d\s-]{7,}\d)", text)
    return match.group(1).strip() if match else ""


def _normalize_phone(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _normalize_shift(value: str) -> str:
    lowered = value.lower()
    if lowered == "day":
        return "Day"
    if lowered == "night":
        return "Night"
    return "Single"


def _to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
