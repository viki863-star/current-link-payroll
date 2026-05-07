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
        "policy": {
            "daily": "Daily DB only, last 7",
            "weekly": "Weekly full ZIP, last 4",
            "monthly": "Monthly full ZIP, last 12",
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
        return Path(configured)
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
        # Walk through all files in generated directory
        for source_path in generated_dir.rglob("*"):
            if not source_path.is_file():
                continue
            
            try:
                relative_path = source_path.relative_to(generated_dir)
                backup_target = backup_root / relative_path
                
                # Skip if target already exists and is newer or same age
                if backup_target.exists():
                    source_mtime = source_path.stat().st_mtime
                    target_mtime = backup_target.stat().st_mtime
                    if target_mtime >= source_mtime:
                        skipped_count += 1
                        continue
                
                # Create parent directory and copy file
                backup_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, backup_target)
                copied_count += 1
                
            except Exception as e:
                app.logger.warning(f"Failed to sync {source_path}: {e}")
                error_count += 1
        
        message = f"Synced {copied_count} files, skipped {skipped_count} (already up-to-date), {error_count} errors"
        return _success_result(backup_root, message)
        
    except Exception as e:
        return _error_result(f"Sync failed: {e}")


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
