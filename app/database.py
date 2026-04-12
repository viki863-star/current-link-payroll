import sqlite3
from pathlib import Path

from flask import Flask, current_app, g


SCHEMA = """
CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    phone_number TEXT,
    vehicle_no TEXT NOT NULL,
    shift TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,
    basic_salary REAL NOT NULL,
    ot_rate REAL NOT NULL DEFAULT 0,
    duty_start TEXT,
    photo_name TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    remarks TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS driver_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    txn_type TEXT NOT NULL,
    source TEXT NOT NULL,
    given_by TEXT,
    amount REAL NOT NULL,
    details TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
);

CREATE TABLE IF NOT EXISTS driver_timesheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    work_hours REAL NOT NULL DEFAULT 0,
    remarks TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(driver_id, entry_date),
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
);

CREATE TABLE IF NOT EXISTS salary_store (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    salary_month TEXT NOT NULL,
    basic_salary REAL NOT NULL,
    ot_hours REAL NOT NULL DEFAULT 0,
    ot_rate REAL NOT NULL DEFAULT 0,
    ot_amount REAL NOT NULL DEFAULT 0,
    personal_vehicle REAL NOT NULL DEFAULT 0,
    net_salary REAL NOT NULL,
    remarks TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(driver_id, salary_month),
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
);

CREATE TABLE IF NOT EXISTS salary_slips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id TEXT NOT NULL,
    salary_store_id INTEGER NOT NULL,
    salary_month TEXT NOT NULL,
    source_filter TEXT,
    total_deductions REAL NOT NULL DEFAULT 0,
    available_advance REAL NOT NULL DEFAULT 0,
    remaining_advance REAL NOT NULL DEFAULT 0,
    payment_source TEXT,
    paid_by TEXT,
    net_payable REAL NOT NULL,
    pdf_path TEXT NOT NULL,
    generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id),
    FOREIGN KEY(salary_store_id) REFERENCES salary_store(id)
);

CREATE TABLE IF NOT EXISTS owner_fund_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_name TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    amount REAL NOT NULL,
    received_by TEXT,
    payment_method TEXT DEFAULT 'Cash',
    details TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


REQUIRED_COLUMNS = {
    "drivers": {
        "phone_number": "TEXT",
    },
    "driver_transactions": {
        "given_by": "TEXT",
    },
    "salary_slips": {
        "available_advance": "REAL NOT NULL DEFAULT 0",
        "remaining_advance": "REAL NOT NULL DEFAULT 0",
        "payment_source": "TEXT",
        "paid_by": "TEXT",
    },
}


def init_db(app: Flask) -> None:
    database_path = Path(app.root_path).parent / app.config["DATABASE"]
    app.config["DATABASE_PATH"] = database_path

    with sqlite3.connect(database_path) as connection:
        connection.executescript(SCHEMA)
        _ensure_columns(connection)

    app.teardown_appcontext(close_db)


def open_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(exception=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _ensure_columns(connection: sqlite3.Connection) -> None:
    for table_name, columns in REQUIRED_COLUMNS.items():
        existing_columns = {
            row[1]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, column_type in columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
            )
