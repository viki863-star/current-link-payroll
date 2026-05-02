#!/usr/bin/env python3
"""
Regression checks for the redesigned managed supplier workspace.
"""

import re
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from app import create_app


class TestManagedSupplierDesk(unittest.TestCase):
    def setUp(self):
        self.runtime_root = Path.cwd() / "generated" / "test-runs" / f"managed-desk-tests-{uuid4().hex}"
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.app = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SECRET_KEY": "test-secret-key",
                "ADMIN_PASSWORD": "admin-pass",
                "OWNER_PASSWORD": "owner-pass",
                "DATABASE": str(self.runtime_root / "managed-desk.db"),
                "GENERATED_DIR": str(self.runtime_root / "generated"),
                "GENERATED_BACKUP_DIR": "",
                "DRIVER_FILES_DIR": str(self.runtime_root / "generated" / "drivers"),
            }
        )
        self.client = self.app.test_client()

        with self.client.session_transaction() as session:
            session["role"] = "admin"
            session["display_name"] = "Test Admin"

    def tearDown(self):
        shutil.rmtree(self.runtime_root, ignore_errors=True)

    def _create_managed_supplier(self, party_code="PTY-MNG-01", party_name="Managed Supplier One"):
        response = self.client.post(
            "/suppliers/managed",
            data={
                "original_party_code": "",
                "party_code": party_code,
                "party_name": party_name,
                "party_kind": "Company",
                "party_roles": ["Supplier"],
                "contact_person": "Ops Lead",
                "phone_number": "0500000001",
                "email": "managed@example.com",
                "trn_no": "",
                "trade_license_no": "",
                "address": "Mussafah",
                "notes": "managed supplier seed",
                "status": "Active",
                "supplier_mode": "Managed",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Supplier registered successfully.", response.data)

    def test_managed_supplier_registration_page_matches_new_flow(self):
        response = self.client.get("/suppliers/managed")
        self.assertEqual(response.status_code, 200)

        html = response.data.decode("utf-8")
        self.assertIn("Managed Supplier Desk", html)
        self.assertIn("Managed Supplier Cards", html)
        self.assertIn("Create Managed Supplier Card", html)
        self.assertNotIn("Managed Quotations", html)
        self.assertNotIn("Managed Invoices", html)
        self.assertNotIn("Quotation Review", html)
        self.assertNotIn("LPO Workspace", html)

    def test_managed_supplier_cards_page_uses_card_directory_labels(self):
        self._create_managed_supplier()
        response = self.client.get("/suppliers/managed/cards")
        self.assertEqual(response.status_code, 200)

        html = response.data.decode("utf-8")
        self.assertIn("Register Managed Supplier", html)
        self.assertIn("Managed Supplier Cards", html)
        self.assertIn("Search Managed Suppliers", html)
        self.assertIn("Open Portal", html)
        self.assertNotIn("Managed Quotations", html)
        self.assertNotIn("Managed Invoices", html)
        self.assertNotIn("Statement", html)

    def test_supplier_screen_options_match_dedicated_portal_flow(self):
        from app.routes import _supplier_screen_options

        normal_keys = [option["key"] for option in _supplier_screen_options("Normal")]
        managed_keys = [option["key"] for option in _supplier_screen_options("Managed")]
        cash_keys = [option["key"] for option in _supplier_screen_options("Cash")]
        partnership_keys = [option["key"] for option in _supplier_screen_options("Partnership")]

        self.assertEqual(normal_keys, ["portal", "statement"])
        self.assertEqual(managed_keys, ["portal", "statement"])
        self.assertEqual(cash_keys, ["portal", "kata"])
        self.assertIn("vehicles", partnership_keys)
        self.assertIn("timesheets", partnership_keys)
        self.assertIn("billing", partnership_keys)
        self.assertIn("statement", partnership_keys)
        self.assertIn("partnership", partnership_keys)

    def test_supplier_default_screen_is_portal_for_every_desk(self):
        from app.routes import _default_supplier_screen

        self.assertEqual(_default_supplier_screen("Normal"), "portal")
        self.assertEqual(_default_supplier_screen("Managed"), "portal")
        self.assertEqual(_default_supplier_screen("Cash"), "portal")
        self.assertEqual(_default_supplier_screen("Loan"), "portal")

    def test_managed_supplier_cards_use_portal_card_layout(self):
        self._create_managed_supplier()
        response = self.client.get("/suppliers/managed/cards")
        self.assertEqual(response.status_code, 200)

        html = response.data.decode("utf-8")
        self.assertIn("supplier-card-grid", html)
        self.assertIn("supplier-card-metrics", html)
        self.assertIn("supplier-card-actions", html)
        self.assertIn("Balance Due", html)
        self.assertIn("Open Work", html)
        self.assertIn("Vouchers", html)
        self.assertIn("Paid", html)
        self.assertNotIn("supplier-stats-grid", html)

    def test_managed_supplier_navigation_removes_registrations_and_quotations(self):
        response = self.client.get("/suppliers/managed")
        self.assertEqual(response.status_code, 200)

        html = response.data.decode("utf-8")
        self.assertIn("Managed Supplier Desk", html)

        registrations_pattern = r'<a[^>]*href="[^"]*supplier_registrations[^"]*"[^>]*>Registrations</a>'
        quotations_pattern = r'<a[^>]*href="[^"]*admin_supplier_quotations[^"]*"[^>]*>Quotations</a>'

        self.assertEqual(re.findall(registrations_pattern, html, re.IGNORECASE), [])
        self.assertEqual(re.findall(quotations_pattern, html, re.IGNORECASE), [])
        self.assertIn("Dashboard", html)

    def test_partnership_supplier_navigation_keeps_registrations_and_quotations(self):
        response = self.client.get("/suppliers/partnership")
        self.assertEqual(response.status_code, 200)

        html = response.data.decode("utf-8")
        self.assertIn("Partnership Supplier Desk", html)
        self.assertIn("Registrations", html)
        self.assertIn("Quotations", html)
        self.assertIn("Dashboard", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
