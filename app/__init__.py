import os
from datetime import timedelta
from pathlib import Path

from flask import Flask
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv

from .database import init_db
from .routes import register_routes

csrf = CSRFProtect()


CURRENT_LINK_STORAGE_FOLDERS = [
    "Database",
    "Generated",
    "Generated/Drivers",
    "Generated/Suppliers",
    "Generated/Suppliers/Online",
    "Generated/Suppliers/Cash",
    "Generated/Suppliers/Managed",
    "Generated/Suppliers/Partnership",
    "Generated/Customers",
    "Generated/Customers/Invoices",
    "Generated/Customers/Statements",
    "Generated/Customers/Contracts",
    "Generated/Accounts",
    "Generated/Accounts/Owner_Fund",
    "Generated/Accounts/Tax",
    "Generated/Accounts/Reports",
    "Generated/Accounts/Audit_Logs",
    "Generated/Field_Staff",
    "Generated/Field_Staff/Staff_Advances",
    "Generated/Field_Staff/Workshop_Expenses",
    "Generated/Field_Staff/Fuel_Expenses",
    "Generated/Field_Staff/General_Expenses",
    "Backups",
    "Backups/Daily",
    "Backups/Weekly",
    "Backups/Monthly",
]


def _default_local_data_root(project_root: Path) -> Path:
    if os.name == "nt":
        return Path("D:/CurrentLinkData")
    return project_root / "local_data"


def _safe_mkdir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def _ensure_storage_layout(root: Path) -> bool:
    if not _safe_mkdir(root):
        return False
    for folder in CURRENT_LINK_STORAGE_FOLDERS:
        if not _safe_mkdir(root / folder):
            return False
    return True

def create_app(test_config: dict | None = None) -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env", override=False)

    app = Flask(__name__)
    project_root = Path(app.root_path).parent
    default_data_root = _default_local_data_root(project_root)
    fallback_data_root = project_root / "generated" / "local_data"
    data_root = Path(os.getenv("CURRENT_LINK_DATA_ROOT", str(default_data_root))).expanduser()
    if not _ensure_storage_layout(data_root):
        data_root = fallback_data_root
        _ensure_storage_layout(data_root)

    fallback_generated_root = project_root / "generated"
    default_database_file = data_root / "Database" / "payroll.db"
    default_generated_root = data_root / "Generated"
    default_backup_root = data_root / "Backups"

    configured_database_file = os.getenv("DATABASE_FILE", str(default_database_file)).strip()
    configured_generated_dir = os.getenv("GENERATED_DIR", str(default_generated_root)).strip()
    configured_backup_dir = os.getenv("GENERATED_BACKUP_DIR", str(default_backup_root)).strip()
    configured_driver_files_dir = os.getenv("DRIVER_FILES_DIR", str(default_generated_root / "Drivers")).strip()
    configured_pc_mirror_root = os.getenv("PC_MIRROR_ROOT", "").strip()
    configured_pc_mirror_log_dir = os.getenv("PC_MIRROR_LOG_DIR", "").strip()

    database_file = Path(configured_database_file).expanduser()
    generated_root = Path(configured_generated_dir).expanduser()
    generated_backup_root = Path(configured_backup_dir).expanduser() if configured_backup_dir else None

    if not _safe_mkdir(generated_root):
        generated_root = fallback_generated_root
        _safe_mkdir(generated_root)

    if not _safe_mkdir(database_file.parent):
        database_file = (project_root / "payroll.db").resolve()
        _safe_mkdir(database_file.parent)

    driver_files_root = Path(
        configured_driver_files_dir or str(generated_root / "Drivers")
    ).expanduser()
    if not _safe_mkdir(driver_files_root):
        driver_files_root = generated_root / "drivers"
        _safe_mkdir(driver_files_root)

    pc_mirror_log_root = (
        Path(configured_pc_mirror_log_dir).expanduser()
        if configured_pc_mirror_log_dir
        else ((generated_backup_root or default_backup_root) / "PC_Mirror_Logs")
    )
    if not _safe_mkdir(pc_mirror_log_root):
        pc_mirror_log_root = generated_root / "pc_mirror_logs"
        _safe_mkdir(pc_mirror_log_root)

    if generated_backup_root and not _safe_mkdir(generated_backup_root):
        generated_backup_root = None

    for extra_dir in (
        generated_root / "Drivers",
        generated_root / "Suppliers",
        generated_root / "Customers",
        generated_root / "Accounts",
        generated_root / "Field_Staff",
        generated_root / "maintenance",
        generated_root / "invoices",
        generated_root / "owner_fund",
        generated_root / "fleet_vehicle_imports",
    ):
        _safe_mkdir(extra_dir)

    app.config.update(
        DATABASE=str(database_file),
        DATABASE_URL=os.getenv("DATABASE_URL", "").strip(),
        REQUIRE_DATABASE_URL=os.getenv("REQUIRE_DATABASE_URL", "false").strip().lower() == "true",
        SECRET_KEY=os.getenv("SECRET_KEY", ""),
        ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD", ""),
        ADMIN_PASSWORD_HASH=os.getenv("ADMIN_PASSWORD_HASH", ""),
        OWNER_PASSWORD=os.getenv("OWNER_PASSWORD", ""),
        OWNER_PASSWORD_HASH=os.getenv("OWNER_PASSWORD_HASH", ""),
        LOGIN_MAX_ATTEMPTS=int(os.getenv("LOGIN_MAX_ATTEMPTS", "5")),
        LOGIN_LOCK_MINUTES=int(os.getenv("LOGIN_LOCK_MINUTES", "15")),
        COMPANY_NAME="Current Link",
        COMPANY_SUBTITLE="Transport and General Contracting LLC SPC",
        CURRENTLINK_FILE=str(Path.home() / "Downloads" / "Currentlink.xlsm"),
        DRIVER_PDF_FILE=str(Path.home() / "Downloads" / "Driver.pdf"),
        LOCAL_DATA_ROOT=str(data_root),
        GENERATED_DIR=str(generated_root),
        GENERATED_BACKUP_DIR=str(generated_backup_root) if generated_backup_root else "",
        DRIVER_FILES_DIR=str(driver_files_root),
        PC_MIRROR_ROOT=configured_pc_mirror_root,
        PC_MIRROR_LOG_DIR=str(pc_mirror_log_root),
        BACKUP_ROOT_DIR=str(generated_backup_root or (data_root / "Backups")),
        BACKUP_DAILY_DIR=str((generated_backup_root or (data_root / "Backups")) / "Daily"),
        BACKUP_WEEKLY_DIR=str((generated_backup_root or (data_root / "Backups")) / "Weekly"),
        BACKUP_MONTHLY_DIR=str((generated_backup_root or (data_root / "Backups")) / "Monthly"),
        STATIC_ASSETS_DIR=str(project_root / "app" / "static"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower() == "true",
        WTF_CSRF_TIME_LIMIT=3600,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )

    if test_config:
        app.config.update(test_config)
        if "DRIVER_FILES_DIR" not in test_config:
            app.config["DRIVER_FILES_DIR"] = str(Path(app.config["GENERATED_DIR"]) / "drivers")
        if "BACKUP_ROOT_DIR" not in test_config:
            backup_root = app.config.get("GENERATED_BACKUP_DIR") or ""
            app.config["BACKUP_ROOT_DIR"] = backup_root
            app.config["BACKUP_DAILY_DIR"] = str(Path(backup_root) / "Daily") if backup_root else ""
            app.config["BACKUP_WEEKLY_DIR"] = str(Path(backup_root) / "Weekly") if backup_root else ""
            app.config["BACKUP_MONTHLY_DIR"] = str(Path(backup_root) / "Monthly") if backup_root else ""

    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY is missing. Set it in .env or the environment before starting the app.")
    if not app.config.get("TESTING"):
        if app.config["REQUIRE_DATABASE_URL"] and not app.config["DATABASE_URL"]:
            raise RuntimeError("DATABASE_URL is required for this deployment.")
        if not (app.config["ADMIN_PASSWORD"] or app.config["ADMIN_PASSWORD_HASH"]):
            raise RuntimeError("ADMIN_PASSWORD or ADMIN_PASSWORD_HASH is missing. Set it in .env or the environment.")
        if not (app.config["OWNER_PASSWORD"] or app.config["OWNER_PASSWORD_HASH"]):
            raise RuntimeError("OWNER_PASSWORD or OWNER_PASSWORD_HASH is missing. Set it in .env or the environment.")

    Path(app.config["DRIVER_FILES_DIR"]).mkdir(parents=True, exist_ok=True)
    if app.config["GENERATED_BACKUP_DIR"]:
        try:
            Path(app.config["GENERATED_BACKUP_DIR"]).mkdir(parents=True, exist_ok=True)
            Path(app.config["BACKUP_DAILY_DIR"]).mkdir(parents=True, exist_ok=True)
            Path(app.config["BACKUP_WEEKLY_DIR"]).mkdir(parents=True, exist_ok=True)
            Path(app.config["BACKUP_MONTHLY_DIR"]).mkdir(parents=True, exist_ok=True)
        except OSError:
            app.config["GENERATED_BACKUP_DIR"] = ""
            app.config["BACKUP_ROOT_DIR"] = ""
            app.config["BACKUP_DAILY_DIR"] = ""
            app.config["BACKUP_WEEKLY_DIR"] = ""
            app.config["BACKUP_MONTHLY_DIR"] = ""

    csrf.init_app(app)
    init_db(app)
    from .hr import hr_bp
    app.register_blueprint(hr_bp)
    from .fleet import fleet_bp
    app.register_blueprint(fleet_bp)
    from .supplier import supplier_bp
    app.register_blueprint(supplier_bp)
    from .customer import customer_bp
    app.register_blueprint(customer_bp)
    if not app.config.get("TESTING"):
        try:
            from .backup_service import ensure_daily_backup_for_today

            ensure_daily_backup_for_today(app)
        except Exception:
            app.logger.warning("Automatic daily backup skipped.", exc_info=True)
    register_routes(app)

    return app
