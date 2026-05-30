from __future__ import annotations

import sqlite3
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET


MAIN_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@dataclass
class DriverRecord:
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



def import_drivers_from_workbook(database_path: str, workbook_path: str) -> int:
    workbook = Path(workbook_path)
    if not workbook.exists():
        raise FileNotFoundError(f"Workbook not found: {workbook}")

    records = _load_driver_records(workbook)
    if not records:
        return 0

    with sqlite3.connect(database_path) as connection:
        upsert_driver_records(connection, records)

    return len(records)


def load_driver_records(workbook_path: str) -> list[DriverRecord]:
    workbook = Path(workbook_path)
    if not workbook.exists():
        raise FileNotFoundError(f"Workbook not found: {workbook}")
    return _load_driver_records(workbook)


def upsert_driver_records(db, records: Sequence[DriverRecord]) -> int:
    rows = [
        (
            record.driver_id,
            record.full_name,
            record.phone_number,
            record.vehicle_no,
            record.shift,
            record.vehicle_type,
            record.basic_salary,
            record.ot_rate,
            record.duty_start,
            record.photo_name,
            record.status,
            record.remarks,
        )
        for record in records
    ]
    if not rows:
        return 0

    db.executemany(
        """
        INSERT INTO drivers (
            driver_id,
            full_name,
            phone_number,
            vehicle_no,
            shift,
            vehicle_type,
            basic_salary,
            ot_rate,
            duty_start,
            photo_name,
            status,
            remarks
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(driver_id) DO UPDATE SET
            full_name=excluded.full_name,
            phone_number=excluded.phone_number,
            vehicle_no=excluded.vehicle_no,
            shift=excluded.shift,
            vehicle_type=excluded.vehicle_type,
            basic_salary=excluded.basic_salary,
            ot_rate=excluded.ot_rate,
            duty_start=excluded.duty_start,
            photo_name=excluded.photo_name,
            status=excluded.status,
            remarks=excluded.remarks
        """,
        rows,
    )
    return len(rows)



def _load_driver_records(workbook_path: Path) -> list[DriverRecord]:
    with zipfile.ZipFile(workbook_path) as archive:
        shared_strings = _parse_shared_strings(archive)
        sheet_path = _sheet_path_by_name(archive, "Drivers_Master")
        sheet_root = ET.fromstring(archive.read(sheet_path))

        records: list[DriverRecord] = []
        for row in sheet_root.findall(".//m:sheetData/m:row", MAIN_NS):
            row_number = int(row.attrib["r"])
            if row_number == 1:
                continue

            values: dict[str, str] = {}
            for cell in row.findall("m:c", MAIN_NS):
                reference = cell.attrib.get("r", "")
                column = "".join(character for character in reference if character.isalpha())
                values[column] = _cell_value(cell, shared_strings).strip()

            driver_id = values.get("A", "")
            if not driver_id:
                continue

            records.append(
                DriverRecord(
                    driver_id=driver_id,
                    full_name=values.get("B", ""),
                    phone_number="",
                    vehicle_no=values.get("C", ""),
                    shift=values.get("D", ""),
                    vehicle_type=values.get("E", ""),
                    basic_salary=_to_float(values.get("F", "0")),
                    ot_rate=_to_float(values.get("G", "0")),
                    duty_start=_excel_date_to_text(values.get("H", "")),
                    photo_name=values.get("J", values.get("I", "")),
                    status=values.get("K", "Active") or "Active",
                    remarks=values.get("L", ""),
                )
            )

        return records



def _parse_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("m:si", MAIN_NS):
        strings.append("".join(text_node.text or "" for text_node in item.iterfind(".//m:t", MAIN_NS)))
    return strings



def _sheet_path_by_name(archive: zipfile.ZipFile, target_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    workbook_rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in workbook_rels}

    for sheet in workbook.find("m:sheets", MAIN_NS):
        if sheet.attrib["name"] != target_name:
            continue
        relation_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        return "xl/" + relmap[relation_id]

    raise ValueError(f"Sheet not found: {target_name}")



def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value = cell.find("m:v", MAIN_NS)
    if value is None:
        inline = cell.find("m:is", MAIN_NS)
        if inline is None:
            return ""
        return "".join(text_node.text or "" for text_node in inline.iterfind(".//m:t", MAIN_NS))

    raw = value.text or ""
    if cell_type == "s":
        return shared_strings[int(raw)]
    return raw



def _to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0



def _excel_date_to_text(value: str) -> str:
    if not value:
        return ""
    try:
        serial = float(value)
        date_value = datetime(1899, 12, 30) + timedelta(days=serial)
        return date_value.strftime("%Y-%m-%d")
    except ValueError:
        return value

