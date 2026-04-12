from pathlib import Path

import pytest
from app import create_app


@pytest.fixture
def app(tmp_path):
    database_path = tmp_path / "test_payroll.db"
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DATABASE": str(database_path),
            "SECRET_KEY": "test-secret-key",
            "ADMIN_PASSWORD": "admin-pass",
            "OWNER_PASSWORD": "owner-pass",
            "GENERATED_DIR": str(tmp_path / "generated"),
            "DRIVER_FILES_DIR": str(tmp_path / "generated" / "drivers"),
        }
    )
    Path(app.config["DRIVER_FILES_DIR"]).mkdir(parents=True, exist_ok=True)
    yield app


@pytest.fixture
def client(app):
    return app.test_client()
