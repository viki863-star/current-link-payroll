import os
import sqlite3
from pathlib import Path

from flask import Flask, current_app, g


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    phone_number TEXT,
    pin_hash TEXT,
    vehicle_no TEXT NOT NULL,
    shift TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,
    basic_salary REAL NOT NULL,
    ot_rate REAL NOT NULL DEFAULT 0,
    duty_start TEXT,
    photo_name TEXT,
    photo_data TEXT,
    photo_content_type TEXT,
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
    ot_month TEXT,
    salary_mode TEXT NOT NULL DEFAULT 'full',
    prorata_start_date TEXT,
    salary_days REAL NOT NULL DEFAULT 30,
    daily_rate REAL NOT NULL DEFAULT 0,
    monthly_basic_salary REAL NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS parties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    party_code TEXT NOT NULL UNIQUE,
    party_name TEXT NOT NULL,
    party_kind TEXT NOT NULL DEFAULT 'Company',
    party_roles TEXT NOT NULL,
    contact_person TEXT,
    phone_number TEXT,
    email TEXT,
    trn_no TEXT,
    trade_license_no TEXT,
    address TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    file_name TEXT NOT NULL,
    imported_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_role TEXT,
    actor_name TEXT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    status TEXT NOT NULL DEFAULT 'success',
    details TEXT,
    ip_address TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_rate_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    identifier TEXT NOT NULL,
    failures INTEGER NOT NULL DEFAULT 0,
    blocked_until TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role, identifier)
);
"""


POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS drivers (
    id BIGSERIAL PRIMARY KEY,
    driver_id TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    phone_number TEXT,
    pin_hash TEXT,
    vehicle_no TEXT NOT NULL,
    shift TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,
    basic_salary DOUBLE PRECISION NOT NULL,
    ot_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    duty_start TEXT,
    photo_name TEXT,
    photo_data TEXT,
    photo_content_type TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS driver_transactions (
    id BIGSERIAL PRIMARY KEY,
    driver_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    txn_type TEXT NOT NULL,
    source TEXT NOT NULL,
    given_by TEXT,
    amount DOUBLE PRECISION NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
);

CREATE TABLE IF NOT EXISTS driver_timesheets (
    id BIGSERIAL PRIMARY KEY,
    driver_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    work_hours DOUBLE PRECISION NOT NULL DEFAULT 0,
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(driver_id, entry_date),
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
);

CREATE TABLE IF NOT EXISTS salary_store (
    id BIGSERIAL PRIMARY KEY,
    driver_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    salary_month TEXT NOT NULL,
    ot_month TEXT,
    salary_mode TEXT NOT NULL DEFAULT 'full',
    prorata_start_date TEXT,
    salary_days DOUBLE PRECISION NOT NULL DEFAULT 30,
    daily_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    monthly_basic_salary DOUBLE PRECISION NOT NULL DEFAULT 0,
    basic_salary DOUBLE PRECISION NOT NULL,
    ot_hours DOUBLE PRECISION NOT NULL DEFAULT 0,
    ot_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    ot_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    personal_vehicle DOUBLE PRECISION NOT NULL DEFAULT 0,
    net_salary DOUBLE PRECISION NOT NULL,
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(driver_id, salary_month),
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
);

CREATE TABLE IF NOT EXISTS salary_slips (
    id BIGSERIAL PRIMARY KEY,
    driver_id TEXT NOT NULL,
    salary_store_id BIGINT NOT NULL,
    salary_month TEXT NOT NULL,
    source_filter TEXT,
    total_deductions DOUBLE PRECISION NOT NULL DEFAULT 0,
    available_advance DOUBLE PRECISION NOT NULL DEFAULT 0,
    remaining_advance DOUBLE PRECISION NOT NULL DEFAULT 0,
    payment_source TEXT,
    paid_by TEXT,
    net_payable DOUBLE PRECISION NOT NULL,
    pdf_path TEXT NOT NULL,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id),
    FOREIGN KEY(salary_store_id) REFERENCES salary_store(id)
);

CREATE TABLE IF NOT EXISTS owner_fund_entries (
    id BIGSERIAL PRIMARY KEY,
    owner_name TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    received_by TEXT,
    payment_method TEXT DEFAULT 'Cash',
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parties (
    id BIGSERIAL PRIMARY KEY,
    party_code TEXT NOT NULL UNIQUE,
    party_name TEXT NOT NULL,
    party_kind TEXT NOT NULL DEFAULT 'Company',
    party_roles TEXT NOT NULL,
    contact_person TEXT,
    phone_number TEXT,
    email TEXT,
    trn_no TEXT,
    trade_license_no TEXT,
    address TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_history (
    id BIGSERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    file_name TEXT NOT NULL,
    imported_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    actor_role TEXT,
    actor_name TEXT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    status TEXT NOT NULL DEFAULT 'success',
    details TEXT,
    ip_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_rate_limits (
    id BIGSERIAL PRIMARY KEY,
    role TEXT NOT NULL,
    identifier TEXT NOT NULL,
    failures INTEGER NOT NULL DEFAULT 0,
    blocked_until TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role, identifier)
);
"""


REQUIRED_COLUMNS = {
    "drivers": {
        "phone_number": "TEXT",
        "pin_hash": "TEXT",
        "photo_data": "TEXT",
        "photo_content_type": "TEXT",
    },
    "driver_transactions": {
        "given_by": "TEXT",
    },
    "salary_slips": {
        "available_advance": "DOUBLE PRECISION NOT NULL DEFAULT 0",
        "remaining_advance": "DOUBLE PRECISION NOT NULL DEFAULT 0",
        "payment_source": "TEXT",
        "paid_by": "TEXT",
    },
    "salary_store": {
        "ot_month": "TEXT",
        "salary_mode": "TEXT NOT NULL DEFAULT 'full'",
        "prorata_start_date": "TEXT",
        "salary_days": "DOUBLE PRECISION NOT NULL DEFAULT 30",
        "daily_rate": "DOUBLE PRECISION NOT NULL DEFAULT 0",
        "monthly_basic_salary": "DOUBLE PRECISION NOT NULL DEFAULT 0",
    },
}


class Record(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class QueryResult:
    def __init__(self, cursor, backend: str):
        self.cursor = cursor
        self.backend = backend

    def fetchone(self):
        row = self.cursor.fetchone()
        return _to_record(row, self.cursor.description)

    def fetchall(self):
        return [_to_record(row, self.cursor.description) for row in self.cursor.fetchall()]


class DatabaseAdapter:
    def __init__(self, connection, backend: str):
        self.connection = connection
        self.backend = backend

    def execute(self, query: str, params=()):
        cursor = self.connection.cursor()
        cursor.execute(_prepare_query(query, self.backend), params or ())
        return QueryResult(cursor, self.backend)

    def executemany(self, query: str, params_seq):
        cursor = self.connection.cursor()
        cursor.executemany(_prepare_query(query, self.backend), params_seq)
        return QueryResult(cursor, self.backend)

    def executescript(self, script: str):
        if self.backend == "sqlite":
            self.connection.executescript(script)
            return
        cursor = self.connection.cursor()
        for statement in [part.strip() for part in script.split(";") if part.strip()]:
            cursor.execute(statement)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def init_db(app: Flask) -> None:
    database_url = (app.config.get("DATABASE_URL") or "").strip()
    database_file = app.config.get("DATABASE", "payroll.db")

    if database_url:
        app.config["DATABASE_BACKEND"] = "postgres"
        app.config["DATABASE_URL"] = _normalize_database_url(database_url)
        app.config["DATABASE_PATH"] = None
        db = DatabaseAdapter(_connect_postgres(app.config["DATABASE_URL"]), "postgres")
        try:
            db.executescript(POSTGRES_SCHEMA)
            _ensure_columns(db)
            db.commit()
        finally:
            db.close()
    else:
        database_path = Path(database_file)
        if not database_path.is_absolute():
            database_path = Path(app.root_path).parent / database_path
        app.config["DATABASE_BACKEND"] = "sqlite"
        app.config["DATABASE_PATH"] = database_path
        db = DatabaseAdapter(_connect_sqlite(database_path), "sqlite")
        try:
            db.executescript(SQLITE_SCHEMA)
            _ensure_columns(db)
            db.commit()
        finally:
            db.close()

    app.teardown_appcontext(close_db)


def open_db():
    if "db" not in g:
        backend = current_app.config.get("DATABASE_BACKEND", "sqlite")
        if backend == "postgres":
            connection = _connect_postgres(current_app.config["DATABASE_URL"])
        else:
            connection = _connect_sqlite(current_app.config["DATABASE_PATH"])
        g.db = DatabaseAdapter(connection, backend)
    return g.db


def close_db(exception=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _connect_sqlite(database_path: Path):
    connection = sqlite3.connect(database_path)
    connection.row_factory = _sqlite_row_factory
    return connection


def _connect_postgres(database_url: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            'Postgres mode requires psycopg. Install it with pip install "psycopg[binary]".'
        ) from exc

    return psycopg.connect(database_url)


def _sqlite_row_factory(cursor, row):
    return Record((column[0], row[index]) for index, column in enumerate(cursor.description))


def _to_record(row, description):
    if row is None:
        return None
    if isinstance(row, Record):
        return row
    if hasattr(row, "keys"):
        return Record((key, row[key]) for key in row.keys())
    return Record((column[0], row[index]) for index, column in enumerate(description or []))


def _prepare_query(query: str, backend: str) -> str:
    if backend == "postgres":
        return query.replace("?", "%s")
    return query


def _normalize_database_url(value: str) -> str:
    if value.startswith("postgres://"):
        return "postgresql://" + value[len("postgres://") :]
    return value


def _ensure_columns(db: DatabaseAdapter) -> None:
    for table_name, columns in REQUIRED_COLUMNS.items():
        existing_columns = _existing_columns(db, table_name)
        for column_name, column_type in columns.items():
            if column_name in existing_columns:
                continue
            db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _existing_columns(db: DatabaseAdapter, table_name: str) -> set[str]:
    if db.backend == "sqlite":
        rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row["name"] for row in rows}

    rows = db.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ?
        """,
        (table_name,),
    ).fetchall()
    return {row["column_name"] for row in rows}
