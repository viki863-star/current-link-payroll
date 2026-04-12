from pathlib import Path

from flask import Flask

from .database import init_db
from .routes import register_routes


def create_app() -> Flask:
    app = Flask(__name__)
    project_root = Path(app.root_path).parent
    generated_root = project_root / "generated"

    app.config["DATABASE"] = "payroll.db"
    app.config["SECRET_KEY"] = "dev-secret-key"
    app.config["ADMIN_PASSWORD"] = "current2324"
    app.config["OWNER_PASSWORD"] = "current2324"
    app.config["COMPANY_NAME"] = "Current Link"
    app.config["COMPANY_SUBTITLE"] = "Transport and General Contracting LLC SPC"
    app.config["CURRENTLINK_FILE"] = str(Path.home() / "Downloads" / "Currentlink.xlsm")
    app.config["GENERATED_DIR"] = str(generated_root)
    app.config["DRIVER_FILES_DIR"] = str(generated_root / "drivers")
    app.config["STATIC_ASSETS_DIR"] = str(project_root / "app" / "static")

    Path(app.config["DRIVER_FILES_DIR"]).mkdir(parents=True, exist_ok=True)

    init_db(app)
    register_routes(app)

    return app
