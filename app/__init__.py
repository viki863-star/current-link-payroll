import os
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
    generated_root = project_root / "generated"

    app.config.update(
        DATABASE=os.getenv("DATABASE_FILE", "payroll.db"),
        DATABASE_URL=os.getenv("DATABASE_URL", "").strip(),
        SECRET_KEY=os.getenv("SECRET_KEY", ""),
        ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD", ""),
        OWNER_PASSWORD=os.getenv("OWNER_PASSWORD", ""),
        COMPANY_NAME="Current Link",
        COMPANY_SUBTITLE="Transport and General Contracting LLC SPC",
        CURRENTLINK_FILE=str(Path.home() / "Downloads" / "Currentlink.xlsm"),
        DRIVER_PDF_FILE=str(Path.home() / "Downloads" / "Driver.pdf"),
        GENERATED_DIR=str(generated_root),
        DRIVER_FILES_DIR=str(generated_root / "drivers"),
        STATIC_ASSETS_DIR=str(project_root / "app" / "static"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower() == "true",
        WTF_CSRF_TIME_LIMIT=3600,
    )

    if test_config:
        app.config.update(test_config)

    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY is missing. Set it in .env or the environment before starting the app.")
    if not app.config.get("TESTING"):
        if not app.config["ADMIN_PASSWORD"]:
            raise RuntimeError("ADMIN_PASSWORD is missing. Set it in .env or the environment.")
        if not app.config["OWNER_PASSWORD"]:
            raise RuntimeError("OWNER_PASSWORD is missing. Set it in .env or the environment.")

    Path(app.config["DRIVER_FILES_DIR"]).mkdir(parents=True, exist_ok=True)

    csrf.init_app(app)
    init_db(app)
    register_routes(app)

    return app
