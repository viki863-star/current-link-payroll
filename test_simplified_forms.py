#!/usr/bin/env python3
"""
Regression checks for the simplified supplier registration flows.
"""

from app import create_app


def _build_app():
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test-secret-key",
            "ADMIN_PASSWORD": "admin-pass",
            "OWNER_PASSWORD": "owner-pass",
        }
    )
    app.config["SERVER_NAME"] = "localhost"
    return app


def _login_admin(client):
    with client.session_transaction() as session:
        session["role"] = "admin"
        session["display_name"] = "Test Admin"


def test_managed_supplier_form_is_simplified():
    app = _build_app()
    client = app.test_client()
    _login_admin(client)

    response = client.get("/suppliers/managed")
    assert response.status_code == 200

    html = response.data.decode("utf-8")
    assert "Managed Supplier Desk" in html
    assert "Managed Supplier Cards" in html
    assert "Create Managed Supplier Card" in html
    assert "Portal Login Email" not in html
    assert "TRN / VAT" not in html
    assert "Trade License" not in html
    assert "Additional Tags" not in html


def test_partnership_supplier_form_keeps_partnership_fields():
    app = _build_app()
    client = app.test_client()
    _login_admin(client)

    response = client.get("/suppliers/partnership")
    assert response.status_code == 200

    html = response.data.decode("utf-8")
    assert "Partnership Supplier Desk" in html
    assert "Partnership Supplier Cards" in html
    assert "Create Partnership Supplier Card" in html
    assert "Partner Party" in html
    assert "Partner Name" in html
    assert "Company Share %" in html
    assert "Partner Share %" in html
    assert "Portal Login Email" not in html
    assert "TRN / VAT" not in html
    assert "Trade License" not in html


def test_online_supplier_form_keeps_portal_fields():
    app = _build_app()
    client = app.test_client()
    _login_admin(client)

    response = client.get("/suppliers/admin/register?mode=Normal")
    assert response.status_code == 200

    html = response.data.decode("utf-8")
    assert "Online Supplier Desk" in html
    assert "Online Supplier Cards" in html
    assert "Create Online Supplier Card" in html
    assert "Portal Login Email" in html
    assert "Enable supplier portal" in html
