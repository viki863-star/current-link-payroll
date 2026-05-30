import argparse
import os
import sqlite3
import sys
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import POSTGRES_SCHEMA


TABLE_ORDER = [
    "drivers",
    "parties",
    "owner_fund_entries",
    "import_history",
    "audit_logs",
    "auth_rate_limits",
    "driver_transactions",
    "driver_timesheets",
    "salary_store",
    "salary_slips",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely copy local SQLite payroll data into a Postgres database."
    )
    parser.add_argument(
        "--sqlite",
        default="payroll.db",
        help="Path to the source SQLite database. Defaults to payroll.db",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "").strip(),
        help="Target Postgres DATABASE_URL. Falls back to env DATABASE_URL if omitted.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete target rows before import. Use only when you are sure the target DB is disposable.",
    )
    return parser.parse_args()


def normalize_database_url(value: str) -> str:
    if value.startswith("postgres://"):
        return "postgresql://" + value[len("postgres://") :]
    return value


def sqlite_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def existing_columns_sqlite(connection: sqlite3.Connection, table_name: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row["name"] for row in rows]


def existing_columns_postgres(connection: psycopg.Connection, table_name: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_name,),
        )
        return [row[0] for row in cursor.fetchall()]


def create_schema(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        for statement in [part.strip() for part in POSTGRES_SCHEMA.split(";") if part.strip()]:
            cursor.execute(statement)
    connection.commit()


def truncate_tables(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "TRUNCATE TABLE salary_slips, salary_store, driver_timesheets, driver_transactions, "
            "auth_rate_limits, audit_logs, import_history, owner_fund_entries, parties, drivers "
            "RESTART IDENTITY CASCADE"
        )
    connection.commit()


def copy_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn: psycopg.Connection,
    table_name: str,
) -> int:
    source_columns = existing_columns_sqlite(sqlite_conn, table_name)
    target_columns = existing_columns_postgres(pg_conn, table_name)
    common_columns = [column for column in source_columns if column in target_columns]
    if not common_columns:
        return 0

    rows = sqlite_conn.execute(f"SELECT {', '.join(common_columns)} FROM {table_name}").fetchall()
    if not rows:
        return 0

    placeholders = ", ".join(["%s"] * len(common_columns))
    assignments = ", ".join(
        [f"{column} = EXCLUDED.{column}" for column in common_columns if column != "id"]
    )
    query = (
        f"INSERT INTO {table_name} ({', '.join(common_columns)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO UPDATE SET {assignments}"
    )

    values = [tuple(row[column] for column in common_columns) for row in rows]
    with pg_conn.cursor() as cursor:
        cursor.executemany(query, values)
    pg_conn.commit()
    return len(values)


def sync_sequence(connection: psycopg.Connection, table_name: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), true)"
        )
    connection.commit()


def main() -> int:
    args = parse_args()
    sqlite_path = Path(args.sqlite).expanduser().resolve()
    database_url = normalize_database_url(args.database_url)

    if not sqlite_path.exists():
        raise SystemExit(f"SQLite file not found: {sqlite_path}")
    if not database_url:
        raise SystemExit("DATABASE_URL is missing. Pass --database-url or set env DATABASE_URL.")

    print(f"Source SQLite: {sqlite_path}")
    print("Target Postgres: configured")
    print("Mode:", "truncate-and-import" if args.truncate else "safe-upsert")

    sqlite_conn = sqlite_connection(sqlite_path)
    pg_conn = psycopg.connect(database_url)

    try:
        create_schema(pg_conn)
        if args.truncate:
            truncate_tables(pg_conn)

        for table_name in TABLE_ORDER:
            copied = copy_table(sqlite_conn, pg_conn, table_name)
            sync_sequence(pg_conn, table_name)
            print(f"{table_name}: {copied} row(s) synced")
    finally:
        sqlite_conn.close()
        pg_conn.close()

    print("Migration finished successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
