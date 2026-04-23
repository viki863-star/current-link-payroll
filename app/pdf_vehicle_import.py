from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


STATUS_OPTIONS = {"ACTIVE", "INACTIVE"}


@dataclass
class VehiclePdfRecord:
    vehicle_no: str
    vehicle_type: str
    status: str


def load_vehicle_records_from_pdf(pdf_path: str) -> list[VehiclePdfRecord]:
    source = Path(pdf_path)
    if not source.exists():
        raise FileNotFoundError(f"PDF not found: {source}")
    reader = PdfReader(str(source))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return _parse_vehicle_pdf_text(text)


def load_vehicle_records_from_pdf_bytes(pdf_bytes: bytes) -> list[VehiclePdfRecord]:
    if not pdf_bytes:
        return []
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return _parse_vehicle_pdf_text(text)


def _parse_vehicle_pdf_text(text: str) -> list[VehiclePdfRecord]:
    prepared: dict[str, VehiclePdfRecord] = {}
    for raw_line in text.splitlines():
        line = " ".join((raw_line or "").split())
        if not line:
            continue
        if line.lower().startswith("vehicle no"):
            continue
        record = _parse_vehicle_line(line)
        if record is None:
            continue
        existing = prepared.get(record.vehicle_no)
        if existing is None:
            prepared[record.vehicle_no] = record
            continue
        vehicle_type = record.vehicle_type if len(record.vehicle_type) > len(existing.vehicle_type) else existing.vehicle_type
        status = record.status if record.status != "Active" or existing.status == "Active" else existing.status
        prepared[record.vehicle_no] = VehiclePdfRecord(
            vehicle_no=record.vehicle_no,
            vehicle_type=vehicle_type,
            status=status,
        )
    return list(prepared.values())


def _parse_vehicle_line(line: str) -> VehiclePdfRecord | None:
    tokens = line.split()
    if not tokens:
        return None
    vehicle_no = tokens[0].strip().upper()
    if not any(character.isdigit() for character in vehicle_no):
        return None

    tail = tokens[1:]
    if not tail:
        return VehiclePdfRecord(vehicle_no=vehicle_no, vehicle_type="General", status="Active")

    status = "Active"
    if tail and tail[-1].upper() in STATUS_OPTIONS:
        status = tail.pop().title()

    vehicle_type = " ".join(tail).strip()
    vehicle_type = " ".join(vehicle_type.split())
    if not vehicle_type:
        vehicle_type = "General"
    vehicle_type = vehicle_type.replace("TonActive", "Ton Active").replace("Standy", "Standby").strip()
    if vehicle_type.endswith(" Active"):
        vehicle_type = vehicle_type[: -len(" Active")].strip()
        status = "Active"

    return VehiclePdfRecord(
        vehicle_no=vehicle_no,
        vehicle_type=vehicle_type or "General",
        status=status,
    )
