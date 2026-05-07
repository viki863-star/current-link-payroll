import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from app import create_app


@pytest.fixture
def app():
    runtime_root = Path.cwd() / "generated" / "test-runs" / f"current-link-tests-{uuid4().hex}"
    runtime_root.mkdir(parents=True, exist_ok=True)
    database_path = runtime_root / "test_payroll.db"
    generated_dir = runtime_root / "generated"
    driver_files_dir = generated_dir / "drivers"

    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DATABASE": str(database_path),
            "SECRET_KEY": "test-secret-key",
            "ADMIN_PASSWORD": "admin-pass",
            "OWNER_PASSWORD": "owner-pass",
            "GENERATED_DIR": str(generated_dir),
            "GENERATED_BACKUP_DIR": "",
            "DRIVER_FILES_DIR": str(driver_files_dir),
        }
    )
    Path(app.config["DRIVER_FILES_DIR"]).mkdir(parents=True, exist_ok=True)
    try:
        yield app
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


@pytest.fixture
def client(app):
    return app.test_client()
