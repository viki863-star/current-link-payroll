from datetime import datetime
from pathlib import Path

from werkzeug.security import generate_password_hash

from app.database import open_db
from app.pdf_service import generate_kata_pdf


def admin_session(client):
    with client.session_transaction() as session:
        session["role"] = "admin"
        session["display_name"] = "Admin"


def create_driver_record(app, **overrides):
    payload = {
        "driver_id": "DRV-T1",
        "full_name": "Test Driver",
        "phone_number": "0556701482",
        "pin_hash": generate_password_hash("1234"),
        "vehicle_no": "5224",
        "shift": "Day",
        "vehicle_type": "Water Tanker",
        "basic_salary": 3300.0,
        "ot_rate": 10.0,
        "duty_start": "2026-01-13",
        "photo_name": "",
        "photo_data": "",
        "photo_content_type": "",
        "status": "Active",
        "remarks": "",
    }
    payload.update(overrides)

    with app.app_context():
        db = open_db()
        db.execute(
            """
            INSERT INTO drivers (
                driver_id, full_name, phone_number, pin_hash, vehicle_no, shift, vehicle_type,
                basic_salary, ot_rate, duty_start, photo_name, photo_data, photo_content_type, status, remarks
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["driver_id"],
                payload["full_name"],
                payload["phone_number"],
                payload["pin_hash"],
                payload["vehicle_no"],
                payload["shift"],
                payload["vehicle_type"],
                payload["basic_salary"],
                payload["ot_rate"],
                payload["duty_start"],
                payload["photo_name"],
                payload["photo_data"],
                payload["photo_content_type"],
                payload["status"],
                payload["remarks"],
            ),
        )
        db.commit()

    return payload


def test_driver_login_requires_phone_and_pin(app, client):
    create_driver_record(app)

    response = client.post(
        "/login",
        data={"role": "driver", "phone_number": "0556701482", "driver_pin": "1234"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/portal/driver" in response.headers["Location"]
    client.get("/logout", follow_redirects=False)

    failed = client.post(
        "/login",
        data={"role": "driver", "phone_number": "0556701482", "driver_pin": "9999"},
        follow_redirects=True,
    )
    assert b"Driver PIN is not correct." in failed.data


def test_admin_login_supports_hash_and_rate_limit(app, client):
    app.config["ADMIN_PASSWORD"] = ""
    app.config["ADMIN_PASSWORD_HASH"] = generate_password_hash("admin-pass")
    app.config["LOGIN_MAX_ATTEMPTS"] = 2
    app.config["LOGIN_LOCK_MINUTES"] = 1

    first = client.post(
        "/login",
        data={"role": "admin", "password": "wrong-pass"},
        follow_redirects=True,
    )
    assert b"Admin password is not correct." in first.data

    second = client.post(
        "/login",
        data={"role": "admin", "password": "wrong-pass"},
        follow_redirects=True,
    )
    assert b"Too many login attempts." in second.data

    blocked = client.post(
        "/login",
        data={"role": "admin", "password": "admin-pass"},
        follow_redirects=True,
    )
    assert b"Too many login attempts." in blocked.data


def test_salary_store_updates_existing_month(app, client):
    create_driver_record(app)
    admin_session(client)

    first = client.post(
        "/drivers/DRV-T1/salary-store",
        data={
            "entry_date": "2026-04-01",
            "salary_month": "2026-04",
            "ot_hours": "5",
            "personal_vehicle": "0",
            "remarks": "first",
            "action": "save",
        },
        follow_redirects=True,
    )
    assert b"Salary stored successfully." in first.data

    second = client.post(
        "/drivers/DRV-T1/salary-store",
        data={
            "entry_date": "2026-04-02",
            "salary_month": "2026-04",
            "ot_hours": "7",
            "personal_vehicle": "100",
            "remarks": "updated",
            "action": "save",
        },
        follow_redirects=True,
    )
    assert b"Existing salary record was updated." in second.data

    with app.app_context():
        db = open_db()
        rows = db.execute("SELECT salary_month, ot_month, ot_hours, personal_vehicle, net_salary FROM salary_store WHERE driver_id = ?", ("DRV-T1",)).fetchall()
        assert len(rows) == 1
        assert rows[0]["salary_month"] == "2026-04"
        assert float(rows[0]["ot_hours"]) == 7.0
        assert float(rows[0]["personal_vehicle"]) == 100.0
        assert float(rows[0]["net_salary"]) == 3470.0
        assert rows[0]["ot_month"] == "2026-03"


def test_salary_store_supports_prorata_from_duty_start(app, client):
    create_driver_record(app, basic_salary=3000.0, duty_start="2026-04-09")
    admin_session(client)

    response = client.post(
        "/drivers/DRV-T1/salary-store",
        data={
            "entry_date": "2026-04-30",
            "salary_month": "2026-04",
            "salary_mode": "prorata",
            "prorata_start_date": "2026-04-09",
            "ot_hours": "0",
            "personal_vehicle": "0",
            "remarks": "Joined mid month",
            "action": "save",
        },
        follow_redirects=True,
    )

    assert b"Salary stored successfully." in response.data
    assert b"Prorata mode is active." in response.data

    with app.app_context():
        db = open_db()
        row = db.execute(
            """
            SELECT salary_mode, prorata_start_date, salary_days, daily_rate,
                   monthly_basic_salary, basic_salary, net_salary
            FROM salary_store
            WHERE driver_id = ? AND salary_month = ?
            """,
            ("DRV-T1", "2026-04"),
        ).fetchone()
        assert row is not None
        assert row["salary_mode"] == "prorata"
        assert row["prorata_start_date"] == "2026-04-09"
        assert float(row["salary_days"]) == 22.0
        assert float(row["daily_rate"]) == 100.0
        assert float(row["monthly_basic_salary"]) == 3000.0
        assert float(row["basic_salary"]) == 2200.0
        assert float(row["net_salary"]) == 2200.0


def test_transaction_rejects_invalid_amount(app, client):
    create_driver_record(app)
    admin_session(client)

    response = client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-04-12",
            "txn_type": "Advance",
            "source": "Owner Fund",
            "given_by": "Office",
            "amount": "abc",
            "details": "bad amount",
        },
        follow_redirects=True,
    )

    assert b"Amount must be a valid number." in response.data

    with app.app_context():
        db = open_db()
        count = db.execute("SELECT COUNT(*) FROM driver_transactions WHERE driver_id = ?", ("DRV-T1",)).fetchone()[0]
        assert count == 0


def test_partial_advance_deduction_carries_remaining_balance(app, client):
    create_driver_record(app, basic_salary=3000.0)
    admin_session(client)

    first_txn = client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-04-12",
            "txn_type": "Advance",
            "source": "Owner Fund",
            "given_by": "Office",
            "amount": "500",
            "details": "seed advance",
        },
        follow_redirects=True,
    )
    assert b"Transaction saved" in first_txn.data

    april_salary = client.post(
        "/drivers/DRV-T1/salary-store",
        data={
            "entry_date": "2026-04-30",
            "salary_month": "2026-04",
            "ot_hours": "0",
            "personal_vehicle": "0",
            "remarks": "April salary",
            "action": "save",
        },
        follow_redirects=True,
    )
    assert b"Salary stored successfully." in april_salary.data

    april_slip = client.post(
        "/drivers/DRV-T1/salary-slip",
        data={
            "salary_store_id": "1",
            "deduction_amount": "100",
            "payment_source": "Owner Fund",
            "paid_by": "Waqar",
        },
        follow_redirects=True,
    )
    assert b"Salary slip PDF generated" in april_slip.data

    may_salary = client.post(
        "/drivers/DRV-T1/salary-store",
        data={
            "entry_date": "2026-05-31",
            "salary_month": "2026-05",
            "ot_hours": "0",
            "personal_vehicle": "0",
            "remarks": "May salary",
            "action": "save",
        },
        follow_redirects=True,
    )
    assert b"Salary stored successfully." in may_salary.data

    may_slip = client.post(
        "/drivers/DRV-T1/salary-slip",
        data={
            "salary_store_id": "2",
            "deduction_amount": "200",
            "payment_source": "Owner Fund",
            "paid_by": "Waqar",
        },
        follow_redirects=True,
    )
    assert b"Salary slip PDF generated" in may_slip.data

    with app.app_context():
        db = open_db()
        slips = db.execute(
            """
            SELECT salary_month, total_deductions, remaining_advance, net_payable
            FROM salary_slips
            WHERE driver_id = ?
            ORDER BY salary_month ASC
            """,
            ("DRV-T1",),
        ).fetchall()
        assert len(slips) == 2
        assert slips[0]["salary_month"] == "2026-04"
        assert float(slips[0]["total_deductions"]) == 100.0
        assert float(slips[0]["remaining_advance"]) == 400.0
        assert float(slips[0]["net_payable"]) == 2900.0
        assert slips[1]["salary_month"] == "2026-05"
        assert float(slips[1]["total_deductions"]) == 200.0
        assert float(slips[1]["remaining_advance"]) == 200.0
        assert float(slips[1]["net_payable"]) == 2800.0

    kata_response = client.get("/drivers/DRV-T1/kata-pdf", follow_redirects=False)
    assert kata_response.status_code == 302
    assert "/generated/" in kata_response.headers["Location"]


def test_existing_paid_salary_slip_can_be_updated(app, client):
    create_driver_record(app, basic_salary=3000.0)
    admin_session(client)

    client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-04-12",
            "txn_type": "Advance",
            "source": "Owner Fund",
            "given_by": "Office",
            "amount": "500",
            "details": "advance",
        },
        follow_redirects=True,
    )

    client.post(
        "/drivers/DRV-T1/salary-store",
        data={
            "entry_date": "2026-04-30",
            "salary_month": "2026-04",
            "ot_hours": "0",
            "personal_vehicle": "0",
            "remarks": "April salary",
            "action": "save",
        },
        follow_redirects=True,
    )

    first_slip = client.post(
        "/drivers/DRV-T1/salary-slip",
        data={
            "salary_store_id": "1",
            "deduction_amount": "100",
            "payment_source": "Owner Fund",
            "paid_by": "Waqar",
        },
        follow_redirects=True,
    )
    assert b"Salary slip PDF generated" in first_slip.data

    updated_slip = client.post(
        "/drivers/DRV-T1/salary-slip",
        data={
            "salary_store_id": "1",
            "deduction_amount": "200",
            "payment_source": "Office",
            "paid_by": "Admin",
        },
        follow_redirects=True,
    )
    assert b"Salary slip updated" in updated_slip.data

    with app.app_context():
        db = open_db()
        slips = db.execute(
            """
            SELECT salary_month, total_deductions, remaining_advance, net_payable, payment_source, paid_by
            FROM salary_slips
            WHERE driver_id = ?
            ORDER BY id ASC
            """,
            ("DRV-T1",),
        ).fetchall()
        assert len(slips) == 1
        assert slips[0]["salary_month"] == "2026-04"
        assert float(slips[0]["total_deductions"]) == 200.0
        assert float(slips[0]["remaining_advance"]) == 300.0
        assert float(slips[0]["net_payable"]) == 2800.0
        assert slips[0]["payment_source"] == "Office"
        assert slips[0]["paid_by"] == "Admin"


def test_kata_pdf_accepts_postgres_datetime_generated_at(app, tmp_path):
    driver = create_driver_record(app)

    output_path = generate_kata_pdf(
        driver,
        [
            {
                "entry_date": "2026-04-30",
                "salary_month": "2026-04",
                "net_salary": 3000.0,
            }
        ],
        [
            {
                "entry_date": "2026-04-12",
                "txn_type": "Advance",
                "source": "Owner Fund",
                "given_by": "Office",
                "amount": 500.0,
            }
        ],
        [
            {
                "generated_at": datetime(2026, 4, 30, 10, 30, 0),
                "salary_month": "2026-04",
                "total_deductions": 100.0,
                "net_payable": 2900.0,
                "payment_source": "Owner Fund",
                "paid_by": "Waqar",
            }
        ],
        str(tmp_path),
        str(Path(app.root_path).parent / "app" / "static"),
    )

    assert Path(output_path).exists()


def test_delete_driver_removes_related_records(app, client):
    create_driver_record(app)
    admin_session(client)

    with app.app_context():
        db = open_db()
        db.execute(
            "INSERT INTO driver_transactions (driver_id, entry_date, txn_type, source, given_by, amount, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("DRV-T1", "2026-04-12", "Advance", "Owner Fund", "Office", 500.0, "seed"),
        )
        db.execute(
            "INSERT INTO salary_store (driver_id, entry_date, salary_month, basic_salary, ot_hours, ot_rate, ot_amount, personal_vehicle, net_salary, remarks) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("DRV-T1", "2026-04-12", "2026-04", 3300.0, 0.0, 10.0, 0.0, 0.0, 3300.0, ""),
        )
        db.execute(
            "INSERT INTO driver_timesheets (driver_id, entry_date, work_hours, remarks) VALUES (?, ?, ?, ?)",
            ("DRV-T1", "2026-04-12", 8.0, ""),
        )
        db.commit()

    response = client.post("/drivers/DRV-T1/delete", data={}, follow_redirects=True)
    assert b"deleted successfully" in response.data

    with app.app_context():
        db = open_db()
        assert db.execute("SELECT COUNT(*) FROM drivers WHERE driver_id = ?", ("DRV-T1",)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM driver_transactions WHERE driver_id = ?", ("DRV-T1",)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM driver_timesheets WHERE driver_id = ?", ("DRV-T1",)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM salary_store WHERE driver_id = ?", ("DRV-T1",)).fetchone()[0] == 0


def test_owner_fund_can_edit_and_delete(app, client):
    admin_session(client)

    created = client.post(
        "/owner-fund",
        data={
            "entry_id": "",
            "owner_name": "Nasrullah",
            "entry_date": "2026-04-12",
            "amount": "50000",
            "received_by": "Waqar",
            "payment_method": "Cash",
            "details": "seed entry",
        },
        follow_redirects=True,
    )
    assert b"Owner fund entry saved." in created.data

    with app.app_context():
        db = open_db()
        entry = db.execute("SELECT id, amount, details FROM owner_fund_entries ORDER BY id DESC LIMIT 1").fetchone()
        entry_id = entry["id"]
        assert float(entry["amount"]) == 50000.0

    updated = client.post(
        "/owner-fund",
        data={
            "entry_id": str(entry_id),
            "owner_name": "Nasrullah",
            "entry_date": "2026-04-12",
            "amount": "45000",
            "received_by": "Waqar",
            "payment_method": "Bank",
            "details": "updated entry",
        },
        follow_redirects=True,
    )
    assert b"Owner fund entry updated." in updated.data

    with app.app_context():
        db = open_db()
        entry = db.execute("SELECT amount, payment_method, details FROM owner_fund_entries WHERE id = ?", (entry_id,)).fetchone()
        assert float(entry["amount"]) == 45000.0
        assert entry["payment_method"] == "Bank"
        assert entry["details"] == "updated entry"

    deleted = client.post(f"/owner-fund/{entry_id}/delete", data={}, follow_redirects=True)
    assert b"Owner fund entry deleted." in deleted.data

    with app.app_context():
        db = open_db()
        assert db.execute("SELECT COUNT(*) FROM owner_fund_entries WHERE id = ?", (entry_id,)).fetchone()[0] == 0


def test_party_master_create_auto_code_and_keep_driver_data_safe(app, client):
    create_driver_record(app)
    admin_session(client)

    response = client.post(
        "/parties/new",
        data={
            "party_code": "",
            "party_name": "Al Jaber Transport",
            "party_kind": "Company",
            "party_roles": ["Supplier", "Customer"],
            "contact_person": "Waqar",
            "phone_number": "0501224963",
            "email": "ops@aljaber.example",
            "trn_no": "TRN-4455",
            "trade_license_no": "LIC-2201",
            "address": "Mussafah",
            "notes": "First party",
            "status": "Active",
        },
        follow_redirects=True,
    )

    assert b"Party saved successfully." in response.data
    assert b"Al Jaber Transport" in response.data

    with app.app_context():
        db = open_db()
        party = db.execute(
            "SELECT party_code, party_roles FROM parties WHERE party_name = ?",
            ("Al Jaber Transport",),
        ).fetchone()
        assert party is not None
        assert party["party_code"].startswith("PTY-")
        assert "Supplier" in party["party_roles"]
        assert "Customer" in party["party_roles"]
        assert db.execute("SELECT COUNT(*) FROM drivers WHERE driver_id = ?", ("DRV-T1",)).fetchone()[0] == 1


def test_party_status_can_be_updated(app, client):
    admin_session(client)

    with app.app_context():
        db = open_db()
        db.execute(
            """
            INSERT INTO parties (
                party_code, party_name, party_kind, party_roles, contact_person,
                phone_number, email, trn_no, trade_license_no, address, notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "PTY-0001",
                "Norul",
                "Individual",
                "Borrower, Partner",
                "Norul",
                "0501082900",
                "",
                "",
                "",
                "",
                "",
                "Active",
            ),
        )
        db.commit()

    response = client.post(
        "/parties/PTY-0001/status",
        data={"status": "Inactive"},
        follow_redirects=True,
    )

    assert b"marked as Inactive" in response.data

    with app.app_context():
        db = open_db()
        status = db.execute("SELECT status FROM parties WHERE party_code = ?", ("PTY-0001",)).fetchone()["status"]
        assert status == "Inactive"


def test_accounting_stack_flow_keeps_driver_core_safe(app, client):
    create_driver_record(app)
    admin_session(client)

    with app.app_context():
        db = open_db()
        db.execute(
            """
            INSERT INTO parties (
                party_code, party_name, party_kind, party_roles, contact_person,
                phone_number, email, trn_no, trade_license_no, address, notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "PTY-SUP-01",
                "Al Jaber Supplier",
                "Company",
                "Supplier",
                "Ops",
                "0501224963",
                "supplier@example.com",
                "TRN-SUP",
                "LIC-SUP",
                "Abu Dhabi",
                "Supplier master",
                "Active",
            ),
        )
        db.execute(
            """
            INSERT INTO parties (
                party_code, party_name, party_kind, party_roles, contact_person,
                phone_number, email, trn_no, trade_license_no, address, notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "PTY-CUS-01",
                "Norul Customer",
                "Company",
                "Customer, Borrower, Vehicle Holder",
                "Waqar",
                "0501082900",
                "customer@example.com",
                "TRN-CUS",
                "LIC-CUS",
                "Mussafah",
                "Customer master",
                "Active",
            ),
        )
        db.commit()

    agreement_customer = client.post(
        "/agreements-lpos",
        data={
            "action": "save_agreement",
            "agreement_no": "AGR-C-001",
            "party_code": "PTY-CUS-01",
            "agreement_kind": "Customer",
            "rate_type": "Monthly",
            "start_date": "2026-04-01",
            "end_date": "2026-12-31",
            "amount": "18000",
            "tax_percent": "5",
            "scope": "Monthly tanker rental",
            "notes": "Customer agreement",
        },
        follow_redirects=True,
    )
    assert b"Agreement saved successfully." in agreement_customer.data

    agreement_supplier = client.post(
        "/agreements-lpos",
        data={
            "action": "save_agreement",
            "agreement_no": "AGR-S-001",
            "party_code": "PTY-SUP-01",
            "agreement_kind": "Supplier",
            "rate_type": "Daily",
            "start_date": "2026-04-01",
            "end_date": "2026-12-31",
            "amount": "450",
            "tax_percent": "5",
            "scope": "Trailer hire",
            "notes": "Supplier agreement",
        },
        follow_redirects=True,
    )
    assert b"Agreement saved successfully." in agreement_supplier.data

    lpo_response = client.post(
        "/agreements-lpos",
        data={
            "action": "save_lpo",
            "lpo_no": "LPO-C-001",
            "party_code": "PTY-CUS-01",
            "agreement_no": "AGR-C-001",
            "issue_date": "2026-04-02",
            "valid_until": "2026-04-30",
            "amount": "18000",
            "tax_percent": "5",
            "description": "April work order",
        },
        follow_redirects=True,
    )
    assert b"LPO saved successfully." in lpo_response.data

    hire_customer = client.post(
        "/agreements-lpos",
        data={
            "action": "save_hire",
            "hire_no": "HIR-C-001",
            "direction": "Customer Rental",
            "party_code": "PTY-CUS-01",
            "agreement_no": "AGR-C-001",
            "lpo_no": "LPO-C-001",
            "entry_date": "2026-04-10",
            "asset_name": "Tanker 52",
            "asset_type": "Tanker",
            "unit_type": "Months",
            "quantity": "1",
            "rate": "18000",
            "tax_percent": "5",
            "notes": "Customer monthly billing",
        },
        follow_redirects=True,
    )
    assert b"Hire register row saved successfully." in hire_customer.data

    hire_supplier = client.post(
        "/agreements-lpos",
        data={
            "action": "save_hire",
            "hire_no": "HIR-S-001",
            "direction": "Supplier Hire",
            "party_code": "PTY-SUP-01",
            "agreement_no": "AGR-S-001",
            "lpo_no": "",
            "entry_date": "2026-04-11",
            "asset_name": "Trailer 14",
            "asset_type": "Trailer",
            "unit_type": "Days",
            "quantity": "10",
            "rate": "450",
            "tax_percent": "5",
            "notes": "Supplier daily hire",
        },
        follow_redirects=True,
    )
    assert b"Hire register row saved successfully." in hire_supplier.data

    sales_invoice = client.post(
        "/invoices",
        data={
            "action": "save_invoice",
            "invoice_no": "INV-S-001",
            "invoice_kind": "Sales",
            "party_code": "PTY-CUS-01",
            "agreement_no": "AGR-C-001",
            "lpo_no": "LPO-C-001",
            "hire_no": "HIR-C-001",
            "issue_date": "2026-04-12",
            "due_date": "2026-04-30",
            "subtotal": "18000",
            "tax_percent": "5",
            "notes": "Customer April invoice",
        },
        follow_redirects=True,
    )
    assert b"Invoice created successfully." in sales_invoice.data

    purchase_invoice = client.post(
        "/invoices",
        data={
            "action": "save_invoice",
            "invoice_no": "INV-P-001",
            "invoice_kind": "Purchase",
            "party_code": "PTY-SUP-01",
            "agreement_no": "AGR-S-001",
            "lpo_no": "",
            "hire_no": "HIR-S-001",
            "issue_date": "2026-04-13",
            "due_date": "2026-04-30",
            "subtotal": "4500",
            "tax_percent": "5",
            "notes": "Supplier April bill",
        },
        follow_redirects=True,
    )
    assert b"Invoice created successfully." in purchase_invoice.data

    receipt = client.post(
        "/invoices",
        data={
            "action": "save_payment",
            "voucher_no": "PAY-R-001",
            "invoice_no": "INV-S-001",
            "entry_date": "2026-04-14",
            "payment_method": "Bank",
            "amount": "5000",
            "reference": "RCPT-1",
            "notes": "Partial customer receipt",
        },
        follow_redirects=True,
    )
    assert b"Payment saved and invoice balance updated." in receipt.data

    payment_supplier = client.post(
        "/invoices",
        data={
            "action": "save_payment",
            "voucher_no": "PAY-P-001",
            "invoice_no": "INV-P-001",
            "entry_date": "2026-04-15",
            "payment_method": "Owner Fund",
            "amount": "1000",
            "reference": "PMT-1",
            "notes": "Advance to supplier",
        },
        follow_redirects=True,
    )
    assert b"Payment saved and invoice balance updated." in payment_supplier.data

    loan_response = client.post(
        "/loans",
        data={
            "loan_no": "LOAN-001",
            "party_code": "PTY-CUS-01",
            "entry_date": "2026-04-16",
            "loan_type": "Given",
            "amount": "2000",
            "payment_method": "Cash",
            "reference": "Loan note",
            "notes": "Recover later",
        },
        follow_redirects=True,
    )
    assert b"Loan entry saved successfully." in loan_response.data

    fee_response = client.post(
        "/annual-fees",
        data={
            "fee_no": "FEE-001",
            "party_code": "PTY-CUS-01",
            "fee_type": "Vehicle",
            "description": "Vehicle sponsorship annual fee",
            "vehicle_no": "AUH-54221",
            "due_date": "2026-12-31",
            "annual_amount": "3600",
            "received_amount": "1200",
            "notes": "Annual collection",
        },
        follow_redirects=True,
    )
    assert b"Annual fee row saved successfully." in fee_response.data

    assert client.get("/suppliers").status_code == 200
    assert client.get("/customers").status_code == 200
    assert client.get("/agreements-lpos").status_code == 200
    assert client.get("/invoices").status_code == 200
    assert client.get("/loans").status_code == 200
    assert client.get("/annual-fees").status_code == 200

    supplier_statement = client.get("/suppliers/PTY-SUP-01/statement")
    assert supplier_statement.status_code == 200
    assert b"Supplier Statement" in supplier_statement.data

    customer_statement = client.get("/customers/PTY-CUS-01/statement")
    assert customer_statement.status_code == 200
    assert b"Customer Statement" in customer_statement.data

    tax_page = client.get("/tax")
    assert tax_page.status_code == 200
    assert b"AED 900.00" in tax_page.data
    assert b"AED 225.00" in tax_page.data
    assert b"AED 675.00" in tax_page.data

    reports_page = client.get("/reports")
    assert reports_page.status_code == 200
    assert b"Management Reporting Deck" in reports_page.data
    assert b"AED 13900.00" in reports_page.data
    assert b"AED 3725.00" in reports_page.data

    with app.app_context():
        db = open_db()
        assert db.execute("SELECT COUNT(*) FROM drivers WHERE driver_id = ?", ("DRV-T1",)).fetchone()[0] == 1
        sales = db.execute(
            "SELECT balance_amount, status FROM account_invoices WHERE invoice_no = ?",
            ("INV-S-001",),
        ).fetchone()
        purchase = db.execute(
            "SELECT balance_amount, status FROM account_invoices WHERE invoice_no = ?",
            ("INV-P-001",),
        ).fetchone()
        assert float(sales["balance_amount"]) == 13900.0
        assert sales["status"] == "Partially Paid"
        assert float(purchase["balance_amount"]) == 3725.0
        assert purchase["status"] == "Partially Paid"


def test_accounting_records_support_edit_delete_and_invoice_resync(app, client):
    admin_session(client)

    with app.app_context():
        db = open_db()
        db.execute(
            """
            INSERT INTO parties (
                party_code, party_name, party_kind, party_roles, contact_person,
                phone_number, email, trn_no, trade_license_no, address, notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "PTY-CUS-02",
                "Edit Customer",
                "Company",
                "Customer, Borrower, Vehicle Holder",
                "Ops",
                "0500000001",
                "edit@example.com",
                "",
                "",
                "Abu Dhabi",
                "",
                "Active",
            ),
        )
        db.commit()

    agreement = client.post(
        "/agreements-lpos",
        data={
            "action": "save_agreement",
            "agreement_no": "AGR-E-001",
            "party_code": "PTY-CUS-02",
            "agreement_kind": "Customer",
            "rate_type": "Monthly",
            "start_date": "2026-05-01",
            "end_date": "2026-12-31",
            "amount": "20000",
            "tax_percent": "5",
            "scope": "Original scope",
            "notes": "Original agreement",
        },
        follow_redirects=True,
    )
    assert b"Agreement saved successfully." in agreement.data

    agreement_update = client.post(
        "/agreements-lpos",
        data={
            "action": "save_agreement",
            "original_agreement_no": "AGR-E-001",
            "agreement_no": "AGR-E-001",
            "party_code": "PTY-CUS-02",
            "agreement_kind": "Customer",
            "rate_type": "Monthly",
            "start_date": "2026-05-01",
            "end_date": "2026-12-31",
            "amount": "21000",
            "tax_percent": "5",
            "scope": "Updated scope",
            "notes": "Updated agreement",
        },
        follow_redirects=True,
    )
    assert b"Agreement updated successfully." in agreement_update.data

    invoice = client.post(
        "/invoices",
        data={
            "action": "save_invoice",
            "invoice_no": "INV-E-001",
            "invoice_kind": "Sales",
            "party_code": "PTY-CUS-02",
            "agreement_no": "AGR-E-001",
            "lpo_no": "",
            "hire_no": "",
            "issue_date": "2026-05-10",
            "due_date": "2026-05-31",
            "subtotal": "1000",
            "tax_percent": "5",
            "notes": "Editable invoice",
        },
        follow_redirects=True,
    )
    assert b"Invoice created successfully." in invoice.data

    payment = client.post(
        "/invoices",
        data={
            "action": "save_payment",
            "voucher_no": "PAY-E-001",
            "invoice_no": "INV-E-001",
            "entry_date": "2026-05-11",
            "payment_method": "Bank",
            "amount": "300",
            "reference": "R-1",
            "notes": "Original payment",
        },
        follow_redirects=True,
    )
    assert b"Payment saved and invoice balance updated." in payment.data

    payment_update = client.post(
        "/invoices",
        data={
            "action": "save_payment",
            "original_voucher_no": "PAY-E-001",
            "voucher_no": "PAY-E-001",
            "invoice_no": "INV-E-001",
            "entry_date": "2026-05-11",
            "payment_method": "Bank",
            "amount": "500",
            "reference": "R-2",
            "notes": "Updated payment",
        },
        follow_redirects=True,
    )
    assert b"Payment updated successfully." in payment_update.data

    with app.app_context():
        db = open_db()
        invoice_row = db.execute(
            "SELECT paid_amount, balance_amount, status FROM account_invoices WHERE invoice_no = ?",
            ("INV-E-001",),
        ).fetchone()
        agreement_row = db.execute(
            "SELECT amount, scope, notes FROM agreements WHERE agreement_no = ?",
            ("AGR-E-001",),
        ).fetchone()
        assert float(invoice_row["paid_amount"]) == 500.0
        assert float(invoice_row["balance_amount"]) == 550.0
        assert invoice_row["status"] == "Partially Paid"
        assert float(agreement_row["amount"]) == 21000.0
        assert agreement_row["scope"] == "Updated scope"

    deleted_payment = client.post("/payments/PAY-E-001/delete", data={}, follow_redirects=True)
    assert b"Payment deleted successfully." in deleted_payment.data

    with app.app_context():
        db = open_db()
        invoice_row = db.execute(
            "SELECT paid_amount, balance_amount, status FROM account_invoices WHERE invoice_no = ?",
            ("INV-E-001",),
        ).fetchone()
        assert float(invoice_row["paid_amount"]) == 0.0
        assert float(invoice_row["balance_amount"]) == 1050.0
        assert invoice_row["status"] == "Open"

    loan = client.post(
        "/loans",
        data={
            "loan_no": "LOAN-E-001",
            "party_code": "PTY-CUS-02",
            "entry_date": "2026-05-12",
            "loan_type": "Given",
            "amount": "2000",
            "payment_method": "Cash",
            "reference": "Loan",
            "notes": "Original loan",
        },
        follow_redirects=True,
    )
    assert b"Loan entry saved successfully." in loan.data

    loan_update = client.post(
        "/loans",
        data={
            "original_loan_no": "LOAN-E-001",
            "loan_no": "LOAN-E-001",
            "party_code": "PTY-CUS-02",
            "entry_date": "2026-05-12",
            "loan_type": "Given",
            "amount": "2500",
            "payment_method": "Cash",
            "reference": "Loan-2",
            "notes": "Updated loan",
        },
        follow_redirects=True,
    )
    assert b"Loan entry updated successfully." in loan_update.data

    fee = client.post(
        "/annual-fees",
        data={
            "fee_no": "FEE-E-001",
            "party_code": "PTY-CUS-02",
            "fee_type": "Vehicle",
            "description": "Vehicle fee",
            "vehicle_no": "AUH-100",
            "due_date": "2026-12-31",
            "annual_amount": "3000",
            "received_amount": "1000",
            "notes": "Original fee",
        },
        follow_redirects=True,
    )
    assert b"Annual fee row saved successfully." in fee.data

    fee_update = client.post(
        "/annual-fees",
        data={
            "original_fee_no": "FEE-E-001",
            "fee_no": "FEE-E-001",
            "party_code": "PTY-CUS-02",
            "fee_type": "Vehicle",
            "description": "Vehicle fee updated",
            "vehicle_no": "AUH-100",
            "due_date": "2026-12-31",
            "annual_amount": "4000",
            "received_amount": "1500",
            "notes": "Updated fee",
        },
        follow_redirects=True,
    )
    assert b"Annual fee row updated successfully." in fee_update.data

    deleted_invoice = client.post("/invoices/INV-E-001/delete", data={}, follow_redirects=True)
    assert b"Invoice deleted successfully." in deleted_invoice.data

    deleted_fee = client.post("/annual-fees/FEE-E-001/delete", data={}, follow_redirects=True)
    assert b"Annual fee row deleted successfully." in deleted_fee.data

    deleted_loan = client.post("/loans/LOAN-E-001/delete", data={}, follow_redirects=True)
    assert b"Loan entry deleted successfully." in deleted_loan.data

    deleted_agreement = client.post("/agreements/AGR-E-001/delete", data={}, follow_redirects=True)
    assert b"Agreement deleted successfully." in deleted_agreement.data

    with app.app_context():
        db = open_db()
        assert db.execute("SELECT COUNT(*) FROM account_invoices WHERE invoice_no = ?", ("INV-E-001",)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM annual_fee_entries WHERE fee_no = ?", ("FEE-E-001",)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM loan_entries WHERE loan_no = ?", ("LOAN-E-001",)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM agreements WHERE agreement_no = ?", ("AGR-E-001",)).fetchone()[0] == 0
