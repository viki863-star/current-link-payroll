import os
from datetime import timedelta
from pathlib import Path

from flask import Flask
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv

from .database import init_db
from .routes import register_routes

csrf = CSRFProtect()

def create_app(test_config: dict | None = None) -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env", override=False)

    app = Flask(__name__)
    project_root = Path(app.root_path).parent
    generated_root = Path(os.getenv("GENERATED_DIR", str(project_root / "generated"))).expanduser()
    driver_files_root = Path(
        os.getenv("DRIVER_FILES_DIR", str(generated_root / "drivers"))
    ).expanduser()
    default_backup_root = "F:/Current Link Backup/generated" if os.name == "nt" else ""
    generated_backup_root = Path(
        os.getenv("GENERATED_BACKUP_DIR", default_backup_root)
    ).expanduser() if os.getenv("GENERATED_BACKUP_DIR", default_backup_root).strip() else None

    app.config.update(
        DATABASE=os.getenv("DATABASE_FILE", "payroll.db"),
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
        GENERATED_DIR=str(generated_root),
        GENERATED_BACKUP_DIR=str(generated_backup_root) if generated_backup_root else "",
        DRIVER_FILES_DIR=str(driver_files_root),
        STATIC_ASSETS_DIR=str(project_root / "app" / "static"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower() == "true",
        WTF_CSRF_TIME_LIMIT=3600,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )

    if test_config:
        app.config.update(test_config)

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
        except OSError:
            app.config["GENERATED_BACKUP_DIR"] = ""

    csrf.init_app(app)
    init_db(app)
    register_routes(app)

    return app
