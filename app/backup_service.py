from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import zipfile


BACKUP_LIMITS = {
    "daily": 7,
    "weekly": 4,
    "monthly": 12,
}


def create_daily_backup(app=None):
    app = _resolve_app(app)
    database_path = _database_path(app)
    if not database_path.exists():
        return _error_result(f"Database file was not found at {database_path}")

    backup_dir = _backup_dir(app, "daily")
    filename = f"current_link_daily_db_{_timestamp()}.db"
    target = backup_dir / filename
    shutil.copy2(database_path, target)
    cleanup_old_backups(app)
    return _success_result(target, f"Daily database backup created at {target}")


def create_weekly_backup(app=None):
    app = _resolve_app(app)
    database_path = _database_path(app)
    if not database_path.exists():
        return _error_result(f"Database file was not found at {database_path}")

    generated_dir = Path(app.config["GENERATED_DIR"])
    backup_dir = _backup_dir(app, "weekly")
    archive_path = backup_dir / f"current_link_weekly_full_{_timestamp()}.zip"
    _write_full_archive(archive_path, database_path, generated_dir, include_metadata=False)
    cleanup_old_backups(app)
    return _success_result(archive_path, f"Weekly full backup created at {archive_path}")


def create_monthly_backup(app=None):
    app = _resolve_app(app)
    database_path = _database_path(app)
    if not database_path.exists():
        return _error_result(f"Database file was not found at {database_path}")

    generated_dir = Path(app.config["GENERATED_DIR"])
    backup_dir = _backup_dir(app, "monthly")
    archive_path = backup_dir / f"current_link_monthly_full_{_timestamp()}.zip"
    _write_full_archive(archive_path, database_path, generated_dir, include_metadata=True)
    cleanup_old_backups(app)
    return _success_result(archive_path, f"Monthly full backup created at {archive_path}")


def create_backup_now(kind: str = "weekly", app=None):
    normalized = (kind or "weekly").strip().lower()
    if normalized == "daily":
        return create_daily_backup(app)
    if normalized == "weekly":
        return create_weekly_backup(app)
    if normalized == "monthly":
        return create_monthly_backup(app)
    return _error_result(f"Unsupported backup kind: {kind}")


def cleanup_old_backups(app=None):
    app = _resolve_app(app)
    for kind, keep_count in BACKUP_LIMITS.items():
        backup_dir = _backup_dir(app, kind)
        pattern = {
            "daily": "current_link_daily_db_*.db",
            "weekly": "current_link_weekly_full_*.zip",
            "monthly": "current_link_monthly_full_*.zip",
        }[kind]
        files = sorted(
            backup_dir.glob(pattern),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for old_file in files[keep_count:]:
            try:
                old_file.unlink()
            except OSError:
                app.logger.warning("Could not delete old backup %s", old_file, exc_info=True)
    return {"ok": True, "message": "Old backups cleaned up."}


def ensure_daily_backup_for_today(app=None):
    app = _resolve_app(app)
    if (app.config.get("DATABASE_BACKEND") or "sqlite") != "sqlite":
        return _error_result("Automatic daily DB backup is only available for local SQLite mode.")

    backup_dir = _backup_dir(app, "daily")
    today_prefix = f"current_link_daily_db_{datetime.now().strftime('%Y-%m-%d')}_"
    if any(backup_dir.glob(f"{today_prefix}*.db")):
        latest = latest_backup_file("daily", app)
        return _success_result(latest, "Today's daily backup already exists.")
    return create_daily_backup(app)


def latest_backup_file(kind: str, app=None) -> Path | None:
    app = _resolve_app(app)
    normalized = (kind or "").strip().lower()
    if normalized not in BACKUP_LIMITS:
        return None
    backup_dir = _backup_dir(app, normalized)
    pattern = {
        "daily": "current_link_daily_db_*.db",
        "weekly": "current_link_weekly_full_*.zip",
        "monthly": "current_link_monthly_full_*.zip",
    }[normalized]
    files = sorted(
        backup_dir.glob(pattern),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def backup_status_summary(app=None):
    app = _resolve_app(app)
    configured_root = (app.config.get("BACKUP_ROOT_DIR") or "").strip()
    backup_root = Path(configured_root) if configured_root else _default_backup_root(app)
    generated_dir = Path(app.config["GENERATED_DIR"])
    database_path = _database_path(app)
    pc_mirror_root = _pc_mirror_root(app)
    latest_pc_sync = _latest_pc_mirror_sync_log(app)
    disk_target = backup_root if backup_root.exists() else generated_dir
    try:
        disk_usage = shutil.disk_usage(disk_target)
        free_disk = _format_bytes(disk_usage.free)
    except OSError:
        free_disk = "Unavailable"
    return {
        "database_path": str(database_path),
        "generated_dir": str(generated_dir),
        "backup_root": str(backup_root),
        "daily_dir": str(_backup_dir(app, "daily")),
        "weekly_dir": str(_backup_dir(app, "weekly")),
        "monthly_dir": str(_backup_dir(app, "monthly")),
        "latest_daily": latest_backup_file("daily", app),
        "latest_weekly": latest_backup_file("weekly", app),
        "latest_monthly": latest_backup_file("monthly", app),
        "free_disk_space": free_disk,
        "pc_mirror_root": str(pc_mirror_root) if pc_mirror_root else "",
        "pc_mirror_enabled": bool(pc_mirror_root),
        "pc_mirror_available": bool(pc_mirror_root and pc_mirror_root.exists()),
        "pc_mirror_log_dir": str(_pc_mirror_log_dir(app)),
        "latest_pc_sync": latest_pc_sync,
        "policy": {
            "daily": "Daily DB only, last 7",
            "weekly": "Weekly full ZIP, last 4",
            "monthly": "Monthly full ZIP, last 12",
            "pc_mirror": "Nightly end-of-day PC copy with fresh DB snapshot",
        },
    }


def _write_full_archive(archive_path: Path, database_path: Path, generated_dir: Path, *, include_metadata: bool):
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(database_path, arcname=f"database/{database_path.name}")
        if generated_dir.exists():
            for item in generated_dir.rglob("*"):
                if item.is_file():
                    archive.write(item, arcname=Path("generated") / item.relative_to(generated_dir))
        if include_metadata:
            archive.writestr("meta/backup-info.txt", _metadata_text(database_path, generated_dir))


def _metadata_text(database_path: Path, generated_dir: Path) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        "Current Link ERP Monthly Backup\n"
        f"Created: {timestamp}\n"
        f"Database: {database_path}\n"
        f"Generated: {generated_dir}\n"
        "Contents: payroll.db + full Generated folder + this metadata file\n"
    )


def _backup_dir(app, kind: str) -> Path:
    mapping = {
        "daily": app.config.get("BACKUP_DAILY_DIR") or "",
        "weekly": app.config.get("BACKUP_WEEKLY_DIR") or "",
        "monthly": app.config.get("BACKUP_MONTHLY_DIR") or "",
    }
    configured = (mapping[kind] or "").strip()
    if configured:
        path = Path(configured)
    else:
        path = _default_backup_root(app) / kind.title()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _database_path(app) -> Path:
    configured = app.config.get("DATABASE_PATH")
    if configured:
        path = Path(configured)
        if path.exists():
            return path
    
    # Try DATABASE_FILE from environment
    configured_file = app.config.get("DATABASE_FILE")
    if configured_file:
        path = Path(configured_file)
        if path.exists():
            return path
    
    # Try default locations
    default_paths = [
        Path("payroll.db"),
        Path(app.root_path) / "payroll.db",
        Path(app.root_path).parent / "payroll.db",
        Path(app.config.get("DATABASE", "payroll.db")),
    ]
    
    for path in default_paths:
        if path.exists():
            return path
    
    # Return the first default path even if it doesn't exist (for error message)
    return Path(app.config.get("DATABASE", "payroll.db"))


def _default_backup_root(app) -> Path:
    generated_dir = Path(app.config["GENERATED_DIR"])
    return generated_dir.parent / "backups"


def _resolve_app(app):
    if app is not None:
        return app
    from flask import current_app

    return current_app._get_current_object()


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def _success_result(path: Path | None, message: str):
    return {"ok": True, "path": str(path) if path else "", "message": message}


def _error_result(message: str):
    return {"ok": False, "path": "", "message": message}


def _pc_mirror_root(app):
    configured = (app.config.get("PC_MIRROR_ROOT") or "").strip()
    if not configured:
        return None
    return Path(configured).expanduser()


def _pc_mirror_log_dir(app):
    configured = (app.config.get("PC_MIRROR_LOG_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return (_default_backup_root(app) / "PC_Mirror_Logs").resolve()


def _latest_pc_mirror_sync_log(app):
    log_dir = _pc_mirror_log_dir(app)
    if not log_dir.exists():
        return None
    logs = sorted(log_dir.glob("pc_mirror_sync_*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _copy_if_newer(source_path: Path, target_path: Path, *, app=None, counts: dict | None = None):
    counts = counts or {"copied": 0, "skipped": 0, "errors": 0}
    try:
        if target_path.exists() and target_path.stat().st_mtime >= source_path.stat().st_mtime:
            counts["skipped"] += 1
            return counts
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        counts["copied"] += 1
        return counts
    except Exception as exc:
        if app is not None:
            app.logger.warning("Failed to sync %s to %s: %s", source_path, target_path, exc)
        counts["errors"] += 1
        return counts


def _sync_tree(source_root: Path, target_root: Path, *, app=None, counts: dict | None = None):
    counts = counts or {"copied": 0, "skipped": 0, "errors": 0}
    for source_path in source_root.rglob("*"):
        if not source_path.is_file():
            continue
        target_path = target_root / source_path.relative_to(source_root)
        _copy_if_newer(source_path, target_path, app=app, counts=counts)
    return counts


def sync_all_generated_files(app=None):
    """Copy all existing generated files from server to local backup directory."""
    app = _resolve_app(app)
    generated_dir = Path(app.config["GENERATED_DIR"])
    backup_root = _generated_backup_root(app)
    
    if backup_root is None:
        return _error_result("Backup directory not configured (GENERATED_BACKUP_DIR)")
    
    if not generated_dir.exists():
        return _error_result(f"Generated directory not found: {generated_dir}")
    
    copied_count = 0
    skipped_count = 0
    error_count = 0
    
    try:
        sync_counts = _sync_tree(generated_dir, backup_root, app=app)
        copied_count = sync_counts["copied"]
        skipped_count = sync_counts["skipped"]
        error_count = sync_counts["errors"]
        
        message = f"Synced {copied_count} files, skipped {skipped_count} (already up-to-date), {error_count} errors"
        return _success_result(backup_root, message)
        
    except Exception as e:
        return _error_result(f"Sync failed: {e}")


def sync_pc_mirror_copy(app=None):
    """Create a fresh DB snapshot and sync generated/backup outputs to the configured PC mirror root."""
    app = _resolve_app(app)
    mirror_root = _pc_mirror_root(app)
    if mirror_root is None:
        return {"ok": False, "path": "", "message": "PC mirror root is not configured (PC_MIRROR_ROOT)."}

    log_dir = _pc_mirror_log_dir(app)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"pc_mirror_sync_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.log"
    log_lines = [
        "Current Link ERP PC Mirror Sync",
        f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Mirror root: {mirror_root}",
    ]

    try:
        if not mirror_root.exists():
            raise FileNotFoundError(f"PC mirror root is not available: {mirror_root}")

        generated_dir = Path(app.config["GENERATED_DIR"])
        if not generated_dir.exists():
            raise FileNotFoundError(f"Generated directory not found: {generated_dir}")

        backup_result = create_daily_backup(app)
        if not backup_result["ok"]:
            raise RuntimeError(backup_result["message"])

        backup_root = Path(app.config.get("BACKUP_ROOT_DIR") or _default_backup_root(app))
        latest_daily = Path(backup_result["path"]) if backup_result.get("path") else latest_backup_file("daily", app)
        if latest_daily is None or not latest_daily.exists():
            raise FileNotFoundError("Fresh daily backup snapshot was not created.")

        counts = {"copied": 0, "skipped": 0, "errors": 0}
        _sync_tree(generated_dir, mirror_root / "Generated", app=app, counts=counts)
        if backup_root.exists():
            _sync_tree(backup_root, mirror_root / "Backups", app=app, counts=counts)

        snapshot_target = mirror_root / "Database" / "payroll_snapshot_latest.db"
        _copy_if_newer(latest_daily, snapshot_target, app=app, counts=counts)

        log_lines.extend(
            [
                f"Generated source: {generated_dir}",
                f"Backup source: {backup_root}",
                f"Daily snapshot source: {latest_daily}",
                f"Snapshot target: {snapshot_target}",
                f"Copied: {counts['copied']}",
                f"Skipped: {counts['skipped']}",
                f"Errors: {counts['errors']}",
            ]
        )
        message = (
            "Full PC copy synced: "
            f"{counts['copied']} copied, {counts['skipped']} skipped, {counts['errors']} errors. "
            f"Target: {mirror_root}"
        )
        return {
            "ok": True,
            "path": str(mirror_root),
            "message": message,
            "log_path": str(log_path),
            "copied": counts["copied"],
            "skipped": counts["skipped"],
            "errors": counts["errors"],
        }
    except Exception as exc:
        log_lines.append(f"Failed: {exc}")
        return {
            "ok": False,
            "path": "",
            "message": f"PC mirror sync failed: {exc}",
            "log_path": str(log_path),
        }
    finally:
        try:
            log_lines.append(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        except OSError:
            app.logger.warning("Could not write PC mirror sync log %s", log_path, exc_info=True)


def _generated_backup_root(app):
    """Get the backup root path for generated files."""
    backup_root = (app.config.get("GENERATED_BACKUP_DIR") or "").strip()
    if not backup_root:
        return None
    return Path(backup_root)


def _format_bytes(size: int) -> str:
    value = float(size)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def create_supplier_data_backup(app=None):
    """
    Create a comprehensive backup of all supplier data including:
    - Cash suppliers
    - Online suppliers
    - Managed suppliers
    - Partnership suppliers
    - All payment records and vouchers
    """
    app = _resolve_app(app)
    
    try:
        import sqlite3
        import json
        import csv
        from datetime import datetime
        
        database_path = _database_path(app)
        if not database_path.exists():
            return _error_result(f"Database file was not found at {database_path}")
        
        # Create backup directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(app.config.get("GENERATED_BACKUP_DIR") or app.config["GENERATED_DIR"]) / "supplier_backups" / f"supplier_backup_{timestamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Connect to database
        conn = sqlite3.connect(str(database_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # List of supplier-related tables
        supplier_tables = [
            "parties",
            "supplier_profile",
            "supplier_portal_accounts",
            "supplier_assets",
            "supplier_timesheets",
            "supplier_vouchers",
            "supplier_payments",
            "supplier_invoice_submissions",
            "supplier_partnership_entries",
            "supplier_registration_requests",
            "supplier_quotation_submissions",
            "cash_supplier_trips",
            "cash_supplier_debits",
            "cash_supplier_payments",
            "agreements",
            "lpos",
            "hire_records",
            "account_invoices",
            "account_payments",
            "supplier_inquiries",
        ]
        
        backup_info = {
            "backup_timestamp": datetime.now().isoformat(),
            "database": str(database_path),
            "tables_backed_up": [],
            "total_records": 0
        }
        
        # Backup each table to JSON and CSV
        for table in supplier_tables:
            try:
                cursor.execute(f"SELECT * FROM {table}")
                rows = cursor.fetchall()
                
                if not rows:
                    continue
                
                # Save as JSON
                json_data = []
                for row in rows:
                    json_data.append(dict(row))
                
                json_path = backup_dir / f"{table}.json"
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(json_data, f, indent=2, default=str)
                
                # Save as CSV
                csv_path = backup_dir / f"{table}.csv"
                if rows:
                    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        # Write header
                        writer.writerow([col[0] for col in cursor.description])
                        # Write rows
                        for row in rows:
                            writer.writerow([str(cell) if cell is not None else '' for cell in row])
                
                backup_info["tables_backed_up"].append({
                    "table": table,
                    "records": len(rows),
                    "json_file": f"{table}.json",
                    "csv_file": f"{table}.csv"
                })
                backup_info["total_records"] += len(rows)
                
            except Exception as e:
                # Log error but continue with other tables
                error_file = backup_dir / f"{table}_error.txt"
                with open(error_file, 'w') as f:
                    f.write(f"Error backing up table {table}: {str(e)}")
        
        # Save backup info
        info_path = backup_dir / "backup_info.json"
        with open(info_path, 'w', encoding='utf-8') as f:
            json.dump(backup_info, f, indent=2)
        
        # Create ZIP archive
        zip_path = backup_dir.parent / f"supplier_backup_{timestamp}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in backup_dir.rglob('*'):
                if file.is_file():
                    zipf.write(file, file.relative_to(backup_dir.parent))
        
        conn.close()
        
        # Mirror to local backup directory if configured
        _mirror_generated_file(app, zip_path)
        
        message = f"Supplier data backup created: {len(backup_info['tables_backed_up'])} tables, {backup_info['total_records']} records"
        return _success_result(zip_path, message)
        
    except Exception as e:
        return _error_result(f"Supplier data backup failed: {str(e)}")


def auto_generate_supplier_statement_pdf(app=None, party_code: str = "") -> dict:
    """Automatically generate supplier statement PDF after any action.
    
    This function should be called after any supplier action (save_asset, save_timesheet,
    save_voucher, save_debit, save_trip, etc.) to automatically generate and save
    the latest statement PDF to the local backup directory.
    
    Args:
        app: Flask application instance
        party_code: Supplier party code
        
    Returns:
        dict with success/error result
    """
    app = _resolve_app(app)
    
    try:
        from .database import open_db
        from .pdf_service import (
            generate_plain_supplier_statement_pdf,
            generate_partnership_supplier_statement_pdf,
            generate_cash_supplier_kata_pdf,
        )
        from .routes import (
            _fetch_supplier_party,
            _supplier_mode_for_party,
            _supplier_statement_data,
            _cash_supplier_kata,
            _filter_cash_supplier_kata_rows,
            _cash_supplier_kata_summary,
            _supplier_partnership_asset_rows,
            _normalize_month,
            _current_month_value,
        )
        from datetime import datetime
        
        db = open_db()
        party = _fetch_supplier_party(db, party_code)
        if party is None:
            return _error_result(f"Supplier {party_code} was not found.")
        
        supplier_mode = _supplier_mode_for_party(db, party_code)
        output_dir = Path(app.config["GENERATED_DIR"]) / "suppliers" / party_code / "statements"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if supplier_mode in ("Cash", "Loan"):
            # Generate cash supplier kata PDF
            kata_rows, kata_summary = _cash_supplier_kata(db, party_code)
            pdf_path = generate_cash_supplier_kata_pdf(
                party,
                kata_rows,
                kata_summary,
                str(output_dir),
                app.config["STATIC_ASSETS_DIR"],
                title="Cash Supplier Kata" if supplier_mode == "Cash" else "Loan Supplier Kata",
                filter_caption="Auto-generated after action",
            )
        elif supplier_mode == "Partnership":
            # Generate partnership statement PDF
            partnership_month = _normalize_month(_current_month_value())
            statement_rows, statement_summary = _supplier_statement_data(db, party_code, supplier_mode=supplier_mode)
            asset_rows = _supplier_partnership_asset_rows(db, party_code, partnership_month)
            pdf_path = generate_partnership_supplier_statement_pdf(
                party,
                partnership_month,
                asset_rows,
                statement_summary,
                str(output_dir),
            )
        else:
            # Generate plain supplier statement PDF
            statement_rows, statement_summary = _supplier_statement_data(db, party_code, supplier_mode=supplier_mode)
            pdf_path = generate_plain_supplier_statement_pdf(
                party,
                statement_rows,
                statement_summary,
                str(output_dir),
                title="Supplier Statement of Account",
            )
        
        # Mirror to local backup directory
        _mirror_generated_file(app, pdf_path)
        
        # Also archive the statement record
        from .routes import _archive_supplier_statement_pdf_record
        _archive_supplier_statement_pdf_record(app, party, pdf_path, "auto_generated_after_action")
        
        return _success_result(pdf_path, f"Supplier statement PDF auto-generated for {party_code}")
        
    except Exception as e:
        return _error_result(f"Failed to auto-generate supplier statement PDF: {str(e)}")
