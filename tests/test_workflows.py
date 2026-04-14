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


def test_company_setup_supports_profile_branch_currency_and_financial_year(app, client):
    admin_session(client)

    profile = client.post(
        "/company-setup",
        data={
            "action": "save_company_profile",
            "company_name": "Current Link GC",
            "legal_name": "Current Link Transport and General Contracting LLC SPC",
            "trade_license_no": "CN-12345",
            "trade_license_expiry": "2027-04-14",
            "trn_no": "100123456700003",
            "vat_status": "Registered",
            "address": "Mussafah M17, Abu Dhabi",
            "phone_number": "0552885561",
            "email": "info@currentlinkgc.com",
            "bank_name": "ADCB",
            "bank_account_name": "Current Link",
            "bank_account_number": "1234567890",
            "iban": "AE070331234567890",
            "swift_code": "ADCBAEAAXXX",
            "invoice_terms": "30 Days",
            "base_currency": "AED",
            "financial_year_label": "FY 2026",
            "financial_year_start": "2026-01-01",
            "financial_year_end": "2026-12-31",
        },
        follow_redirects=True,
    )
    assert profile.status_code == 200

    branch = client.post(
        "/company-setup",
        data={
            "action": "save_branch",
            "original_branch_code": "",
            "branch_code": "BR-0001",
            "branch_name": "Mussafah Yard",
            "address": "M17 Abu Dhabi",
            "contact_person": "Waqar",
            "phone_number": "0501224963",
            "email": "yard@currentlinkgc.com",
            "status": "Active",
        },
        follow_redirects=True,
    )
    assert branch.status_code == 200

    currency_base = client.post(
        "/company-setup",
        data={
            "action": "save_currency",
            "original_currency_code": "",
            "currency_code": "AED",
            "currency_name": "UAE Dirham",
            "symbol": "AED",
            "exchange_rate": "1",
            "is_base": "1",
            "status": "Active",
        },
        follow_redirects=True,
    )
    assert currency_base.status_code == 200

    currency_second = client.post(
        "/company-setup",
        data={
            "action": "save_currency",
            "original_currency_code": "",
            "currency_code": "USD",
            "currency_name": "US Dollar",
            "symbol": "$",
            "exchange_rate": "3.6725",
            "status": "Active",
        },
        follow_redirects=True,
    )
    assert currency_second.status_code == 200

    financial_year = client.post(
        "/company-setup",
        data={
            "action": "save_financial_year",
            "original_year_code": "",
            "year_code": "FY-2026",
            "year_label": "FY 2026",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "is_current": "1",
            "status": "Open",
        },
        follow_redirects=True,
    )
    assert financial_year.status_code == 200

    branch_update = client.post(
        "/company-setup",
        data={
            "action": "save_branch",
            "original_branch_code": "BR-0001",
            "branch_code": "BR-0001",
            "branch_name": "Mussafah Main Yard",
            "address": "M17 Abu Dhabi",
            "contact_person": "Waqar Hussain",
            "phone_number": "0501224963",
            "email": "mainyard@currentlinkgc.com",
            "status": "Active",
        },
        follow_redirects=True,
    )
    assert branch_update.status_code == 200

    settings_page = client.get("/company-setup", follow_redirects=True)
    assert settings_page.status_code == 200
    assert b"Company Setup" in settings_page.data
    assert b"Mussafah Main Yard" in settings_page.data
    assert b"FY 2026" in settings_page.data

    with app.app_context():
        db = open_db()
        profile_row = db.execute(
            "SELECT company_name, trn_no, base_currency, financial_year_label FROM company_profile ORDER BY id ASC LIMIT 1"
        ).fetchone()
        branch_row = db.execute(
            "SELECT branch_name, contact_person FROM branches WHERE branch_code = ?",
            ("BR-0001",),
        ).fetchone()
        aed_row = db.execute(
            "SELECT currency_name, is_base FROM company_currencies WHERE currency_code = ?",
            ("AED",),
        ).fetchone()
        usd_row = db.execute(
            "SELECT exchange_rate, is_base FROM company_currencies WHERE currency_code = ?",
            ("USD",),
        ).fetchone()
        year_row = db.execute(
            "SELECT year_label, is_current, status FROM financial_years WHERE year_code = ?",
            ("FY-2026",),
        ).fetchone()
        assert profile_row["company_name"] == "Current Link GC"
        assert profile_row["trn_no"] == "100123456700003"
        assert profile_row["base_currency"] == "AED"
        assert profile_row["financial_year_label"] == "FY 2026"
        assert branch_row["branch_name"] == "Mussafah Main Yard"
        assert branch_row["contact_person"] == "Waqar Hussain"
        assert aed_row["currency_name"] == "UAE Dirham"
        assert int(aed_row["is_base"]) == 1
        assert float(usd_row["exchange_rate"]) == 3.6725
        assert int(usd_row["is_base"]) == 0
        assert year_row["year_label"] == "FY 2026"
        assert int(year_row["is_current"]) == 1
        assert year_row["status"] == "Open"


def test_supplier_workspace_flow_tracks_balance_and_keeps_driver_data_safe(app, client):
    create_driver_record(app)
    admin_session(client)

    supplier_response = client.post(
        "/suppliers",
        data={
            "original_party_code": "",
            "party_code": "",
            "party_name": "Hussain Trailer Supply",
            "party_kind": "Company",
            "party_roles": ["Partner"],
            "contact_person": "Hussain",
            "phone_number": "0501224963",
            "email": "hussain@example.com",
            "trn_no": "TRN-HUS",
            "trade_license_no": "LIC-HUS",
            "address": "Mussafah",
            "notes": "Supplier master",
            "status": "Active",
        },
        follow_redirects=True,
    )
    assert b"Supplier registered successfully." in supplier_response.data

    with app.app_context():
        db = open_db()
        supplier = db.execute("SELECT party_code FROM parties WHERE party_name = ?", ("Hussain Trailer Supply",)).fetchone()
        party_code = supplier["party_code"]

    asset_response = client.post(
        f"/suppliers/{party_code}",
        data={
            "action": "save_asset",
            "original_asset_code": "",
            "asset_code": "",
            "asset_name": "Trailer Fleet 01",
            "asset_type": "Trailer",
            "vehicle_no": "TRL-1001",
            "rate_basis": "Hours",
            "default_rate": "80",
            "capacity": "40ft",
            "status": "Active",
            "notes": "Main fleet unit",
        },
        follow_redirects=True,
    )
    assert b"Supplier vehicle saved successfully." in asset_response.data

    with app.app_context():
        db = open_db()
        asset_code = db.execute(
            "SELECT asset_code FROM supplier_assets WHERE party_code = ? ORDER BY id DESC LIMIT 1",
            (party_code,),
        ).fetchone()["asset_code"]

    first_timesheet = client.post(
        f"/suppliers/{party_code}",
        data={
            "action": "save_timesheet",
            "original_timesheet_no": "",
            "timesheet_no": "",
            "asset_code": asset_code,
            "period_month": "2026-04",
            "entry_date": "2026-04-29",
            "billing_basis": "Hours",
            "billable_qty": "120",
            "timesheet_hours": "120",
            "rate": "80",
            "status": "Open",
            "notes": "April hours batch 1",
        },
        follow_redirects=True,
    )
    assert b"Supplier timesheet saved successfully." in first_timesheet.data

    second_timesheet = client.post(
        f"/suppliers/{party_code}",
        data={
            "action": "save_timesheet",
            "original_timesheet_no": "",
            "timesheet_no": "",
            "asset_code": asset_code,
            "period_month": "2026-04",
            "entry_date": "2026-04-30",
            "billing_basis": "Hours",
            "billable_qty": "40",
            "timesheet_hours": "40",
            "rate": "80",
            "status": "Open",
            "notes": "April hours batch 2",
        },
        follow_redirects=True,
    )
    assert b"Supplier timesheet saved successfully." in second_timesheet.data

    voucher_response = client.post(
        f"/suppliers/{party_code}",
        data={
            "action": "save_voucher",
            "original_voucher_no": "",
            "voucher_no": "SPV-HUS-001",
            "period_month": "2026-04",
            "issue_date": "2026-04-30",
            "tax_percent": "5",
            "status": "Open",
            "notes": "April supplier voucher",
        },
        follow_redirects=True,
    )
    assert b"Supplier voucher created from open timesheets." in voucher_response.data

    payment_response = client.post(
        f"/suppliers/{party_code}",
        data={
            "action": "save_payment",
            "original_payment_no": "",
            "payment_no": "SPP-HUS-001",
            "voucher_no": "SPV-HUS-001",
            "entry_date": "2026-05-02",
            "amount": "8000",
            "payment_method": "Bank",
            "reference": "BANK-001",
            "notes": "Part payment",
        },
        follow_redirects=True,
    )
    assert b"Supplier payment saved successfully." in payment_response.data

    pdf_response = client.get("/supplier-payments/SPP-HUS-001/voucher", follow_redirects=False)
    assert pdf_response.status_code == 302
    assert "/generated/" in pdf_response.headers["Location"]

    with app.app_context():
        db = open_db()
        voucher = db.execute(
            """
            SELECT subtotal, total_amount, paid_amount, balance_amount, status
            FROM supplier_vouchers
            WHERE voucher_no = ?
            """,
            ("SPV-HUS-001",),
        ).fetchone()
        linked_rows = db.execute(
            "SELECT COUNT(*) FROM supplier_timesheets WHERE voucher_no = ?",
            ("SPV-HUS-001",),
        ).fetchone()[0]
        assert voucher is not None
        assert float(voucher["subtotal"]) == 12800.0
        assert float(voucher["total_amount"]) == 13440.0
        assert float(voucher["paid_amount"]) == 8000.0
        assert float(voucher["balance_amount"]) == 5440.0
        assert voucher["status"] == "Partially Paid"
        assert linked_rows == 2
        assert db.execute("SELECT COUNT(*) FROM drivers WHERE driver_id = ?", ("DRV-T1",)).fetchone()[0] == 1


def test_supplier_workspace_flow_keeps_driver_core_safe(app, client):
    create_driver_record(app)
    admin_session(client)

    supplier_create = client.post(
        "/suppliers",
        data={
            "party_code": "PTY-SUP-01",
            "party_name": "Hussain Logistics",
            "party_kind": "Individual",
            "party_roles": ["Supplier", "Vehicle Holder"],
            "contact_person": "Hussain",
            "phone_number": "0501224963",
            "email": "hussain@example.com",
            "trn_no": "TRN-HUS",
            "trade_license_no": "LIC-HUS",
            "address": "Mussafah, Abu Dhabi",
            "notes": "Provides 50 trailers every month",
            "status": "Active",
        },
        follow_redirects=True,
    )
    assert supplier_create.status_code == 200

    with app.app_context():
        db = open_db()
        supplier_row = db.execute(
            "SELECT party_code, party_name, party_roles FROM parties WHERE party_code = ?",
            ("PTY-SUP-01",),
        ).fetchone()
        assert supplier_row is not None
        assert supplier_row["party_name"] == "Hussain Logistics"
        assert "Supplier" in supplier_row["party_roles"]

    supplier_page = client.get("/suppliers", follow_redirects=True)
    assert supplier_page.status_code == 200
    assert b"Hussain Logistics" in supplier_page.data

    asset_one = client.post(
        "/suppliers/PTY-SUP-01",
        data={
            "action": "save_asset",
            "original_asset_code": "",
            "asset_code": "AST-HUS-01",
            "asset_name": "Trailer 01",
            "asset_type": "Trailer",
            "vehicle_no": "TR-001",
            "rate_basis": "Hours",
            "default_rate": "120",
            "capacity": "40 FT",
            "status": "Active",
            "notes": "Primary fleet unit",
        },
        follow_redirects=True,
    )
    assert asset_one.status_code == 200

    asset_two = client.post(
        "/suppliers/PTY-SUP-01",
        data={
            "action": "save_asset",
            "original_asset_code": "",
            "asset_code": "AST-HUS-02",
            "asset_name": "Trailer 02",
            "asset_type": "Trailer",
            "vehicle_no": "TR-002",
            "rate_basis": "Hours",
            "default_rate": "115",
            "capacity": "40 FT",
            "status": "Active",
            "notes": "Secondary fleet unit",
        },
        follow_redirects=True,
    )
    assert asset_two.status_code == 200

    timesheet_one = client.post(
        "/suppliers/PTY-SUP-01",
        data={
            "action": "save_timesheet",
            "original_timesheet_no": "",
            "timesheet_no": "TSH-HUS-01",
            "asset_code": "AST-HUS-01",
            "period_month": "2026-04",
            "entry_date": "2026-04-29",
            "billing_basis": "Hours",
            "billable_qty": "120",
            "timesheet_hours": "120",
            "rate": "120",
            "status": "Open",
            "notes": "April month-end hours",
        },
        follow_redirects=True,
    )
    assert timesheet_one.status_code == 200

    timesheet_two = client.post(
        "/suppliers/PTY-SUP-01",
        data={
            "action": "save_timesheet",
            "original_timesheet_no": "",
            "timesheet_no": "TSH-HUS-02",
            "asset_code": "AST-HUS-02",
            "period_month": "2026-04",
            "entry_date": "2026-04-30",
            "billing_basis": "Hours",
            "billable_qty": "100",
            "timesheet_hours": "100",
            "rate": "115",
            "status": "Open",
            "notes": "Second trailer April hours",
        },
        follow_redirects=True,
    )
    assert timesheet_two.status_code == 200

    voucher = client.post(
        "/suppliers/PTY-SUP-01",
        data={
            "action": "save_voucher",
            "original_voucher_no": "",
            "voucher_no": "SPV-HUS-01",
            "period_month": "2026-04",
            "issue_date": "2026-04-30",
            "tax_percent": "5",
            "status": "Open",
            "notes": "April supplier payable voucher",
        },
        follow_redirects=True,
    )
    assert voucher.status_code == 200

    payment = client.post(
        "/suppliers/PTY-SUP-01",
        data={
            "action": "save_payment",
            "original_payment_no": "",
            "payment_no": "SPP-HUS-01",
            "voucher_no": "SPV-HUS-01",
            "entry_date": "2026-05-02",
            "amount": "10000",
            "payment_method": "Bank",
            "reference": "PV-100",
            "notes": "Part payment to Hussain",
        },
        follow_redirects=True,
    )
    assert payment.status_code == 200

    supplier_detail = client.get("/suppliers/PTY-SUP-01", follow_redirects=True)
    assert supplier_detail.status_code == 200
    assert b"Hussain Logistics" in supplier_detail.data
    assert b"SPV-HUS-01" in supplier_detail.data
    assert b"SPP-HUS-01" in supplier_detail.data
    assert b"Outstanding" in supplier_detail.data

    payment_voucher = client.get("/supplier-payments/SPP-HUS-01/voucher", follow_redirects=False)
    assert payment_voucher.status_code == 302
    assert "/generated/" in payment_voucher.headers["Location"]

    with app.app_context():
        db = open_db()
        assert db.execute("SELECT COUNT(*) FROM drivers WHERE driver_id = ?", ("DRV-T1",)).fetchone()[0] == 1
        voucher_row = db.execute(
            """
            SELECT subtotal, tax_amount, total_amount, paid_amount, balance_amount, status
            FROM supplier_vouchers
            WHERE voucher_no = ?
            """,
            ("SPV-HUS-01",),
        ).fetchone()
        assert voucher_row is not None
        assert float(voucher_row["subtotal"]) == 25900.0
        assert float(voucher_row["tax_amount"]) == 1295.0
        assert float(voucher_row["total_amount"]) == 27195.0
        assert float(voucher_row["paid_amount"]) == 10000.0
        assert float(voucher_row["balance_amount"]) == 17195.0
        assert voucher_row["status"] == "Partially Paid"
        linked = db.execute(
            "SELECT COUNT(*) FROM supplier_timesheets WHERE voucher_no = ?",
            ("SPV-HUS-01",),
        ).fetchone()[0]
        assert linked == 2


def test_supplier_workspace_records_support_edit_delete_and_balance_resync(app, client):
    admin_session(client)

    client.post(
        "/suppliers",
        data={
            "party_code": "PTY-SUP-02",
            "party_name": "Edit Supplier",
            "party_kind": "Company",
            "party_roles": ["Supplier"],
            "contact_person": "Ops",
            "phone_number": "0500000001",
            "email": "edit.supplier@example.com",
            "trn_no": "",
            "trade_license_no": "",
            "address": "Abu Dhabi",
            "notes": "",
            "status": "Active",
        },
        follow_redirects=True,
    )

    client.post(
        "/suppliers/PTY-SUP-02",
        data={
            "action": "save_asset",
            "original_asset_code": "",
            "asset_code": "AST-EDIT-01",
            "asset_name": "Trailer Alpha",
            "asset_type": "Trailer",
            "vehicle_no": "EA-100",
            "rate_basis": "Days",
            "default_rate": "450",
            "capacity": "Flatbed",
            "status": "Active",
            "notes": "Original asset",
        },
        follow_redirects=True,
    )

    asset_update = client.post(
        "/suppliers/PTY-SUP-02",
        data={
            "action": "save_asset",
            "original_asset_code": "AST-EDIT-01",
            "asset_code": "AST-EDIT-01",
            "asset_name": "Trailer Alpha Updated",
            "asset_type": "Trailer",
            "vehicle_no": "EA-101",
            "rate_basis": "Days",
            "default_rate": "500",
            "capacity": "Flatbed",
            "status": "Active",
            "notes": "Updated asset",
        },
        follow_redirects=True,
    )
    assert asset_update.status_code == 200

    with app.app_context():
        db = open_db()
        asset_row = db.execute(
            "SELECT asset_name, vehicle_no, default_rate FROM supplier_assets WHERE asset_code = ?",
            ("AST-EDIT-01",),
        ).fetchone()
        assert asset_row is not None
        assert asset_row["asset_name"] == "Trailer Alpha Updated"
        assert asset_row["vehicle_no"] == "EA-101"
        assert float(asset_row["default_rate"]) == 500.0

    client.post(
        "/suppliers/PTY-SUP-02",
        data={
            "action": "save_timesheet",
            "original_timesheet_no": "",
            "timesheet_no": "TSH-EDIT-01",
            "asset_code": "AST-EDIT-01",
            "period_month": "2026-05",
            "entry_date": "2026-05-30",
            "billing_basis": "Days",
            "billable_qty": "10",
            "timesheet_hours": "0",
            "rate": "500",
            "status": "Open",
            "notes": "Original timesheet",
        },
        follow_redirects=True,
    )

    timesheet_update = client.post(
        "/suppliers/PTY-SUP-02",
        data={
            "action": "save_timesheet",
            "original_timesheet_no": "TSH-EDIT-01",
            "timesheet_no": "TSH-EDIT-01",
            "asset_code": "AST-EDIT-01",
            "period_month": "2026-05",
            "entry_date": "2026-05-31",
            "billing_basis": "Days",
            "billable_qty": "12",
            "timesheet_hours": "0",
            "rate": "500",
            "status": "Open",
            "notes": "Updated timesheet",
        },
        follow_redirects=True,
    )
    assert timesheet_update.status_code == 200

    with app.app_context():
        db = open_db()
        timesheet_row = db.execute(
            "SELECT billable_qty, subtotal, notes FROM supplier_timesheets WHERE timesheet_no = ?",
            ("TSH-EDIT-01",),
        ).fetchone()
        assert timesheet_row is not None
        assert float(timesheet_row["billable_qty"]) == 12.0
        assert float(timesheet_row["subtotal"]) == 6000.0
        assert timesheet_row["notes"] == "Updated timesheet"

    client.post(
        "/suppliers/PTY-SUP-02",
        data={
            "action": "save_voucher",
            "original_voucher_no": "",
            "voucher_no": "SPV-EDIT-01",
            "period_month": "2026-05",
            "issue_date": "2026-05-31",
            "tax_percent": "5",
            "status": "Open",
            "notes": "Original voucher",
        },
        follow_redirects=True,
    )

    voucher_update = client.post(
        "/suppliers/PTY-SUP-02",
        data={
            "action": "save_voucher",
            "original_voucher_no": "SPV-EDIT-01",
            "voucher_no": "SPV-EDIT-01",
            "period_month": "2026-05",
            "issue_date": "2026-05-31",
            "tax_percent": "10",
            "status": "Open",
            "notes": "Updated voucher tax",
        },
        follow_redirects=True,
    )
    assert voucher_update.status_code == 200

    with app.app_context():
        db = open_db()
        voucher_row = db.execute(
            "SELECT tax_percent, total_amount, balance_amount FROM supplier_vouchers WHERE voucher_no = ?",
            ("SPV-EDIT-01",),
        ).fetchone()
        assert voucher_row is not None
        assert float(voucher_row["tax_percent"]) == 10.0
        assert float(voucher_row["total_amount"]) == 6600.0
        assert float(voucher_row["balance_amount"]) == 6600.0

    client.post(
        "/suppliers/PTY-SUP-02",
        data={
            "action": "save_payment",
            "original_payment_no": "",
            "payment_no": "SPP-EDIT-01",
            "voucher_no": "SPV-EDIT-01",
            "entry_date": "2026-06-01",
            "amount": "2000",
            "payment_method": "Cash",
            "reference": "PV-1",
            "notes": "Original payment",
        },
        follow_redirects=True,
    )

    payment_update = client.post(
        "/suppliers/PTY-SUP-02",
        data={
            "action": "save_payment",
            "original_payment_no": "SPP-EDIT-01",
            "payment_no": "SPP-EDIT-01",
            "voucher_no": "SPV-EDIT-01",
            "entry_date": "2026-06-02",
            "amount": "2500",
            "payment_method": "Bank",
            "reference": "PV-2",
            "notes": "Updated payment",
        },
        follow_redirects=True,
    )
    assert payment_update.status_code == 200

    with app.app_context():
        db = open_db()
        payment_row = db.execute(
            "SELECT amount, payment_method, reference FROM supplier_payments WHERE payment_no = ?",
            ("SPP-EDIT-01",),
        ).fetchone()
        voucher_row = db.execute(
            "SELECT paid_amount, balance_amount, status FROM supplier_vouchers WHERE voucher_no = ?",
            ("SPV-EDIT-01",),
        ).fetchone()
        assert payment_row is not None
        assert float(payment_row["amount"]) == 2500.0
        assert payment_row["payment_method"] == "Bank"
        assert payment_row["reference"] == "PV-2"
        assert float(voucher_row["paid_amount"]) == 2500.0
        assert float(voucher_row["balance_amount"]) == 4100.0
        assert voucher_row["status"] == "Partially Paid"

    payment_voucher = client.get("/supplier-payments/SPP-EDIT-01/voucher", follow_redirects=False)
    assert payment_voucher.status_code == 302
    assert "/generated/" in payment_voucher.headers["Location"]

    blocked_delete = client.post("/supplier-vouchers/SPV-EDIT-01/delete", data={}, follow_redirects=True)
    assert blocked_delete.status_code == 200

    with app.app_context():
        db = open_db()
        assert db.execute(
            "SELECT COUNT(*) FROM supplier_vouchers WHERE voucher_no = ?",
            ("SPV-EDIT-01",),
        ).fetchone()[0] == 1

    deleted_payment = client.post("/supplier-payments/SPP-EDIT-01/delete", data={}, follow_redirects=True)
    assert deleted_payment.status_code == 200

    deleted_voucher = client.post("/supplier-vouchers/SPV-EDIT-01/delete", data={}, follow_redirects=True)
    assert deleted_voucher.status_code == 200

    deleted_timesheet = client.post("/supplier-timesheets/TSH-EDIT-01/delete", data={}, follow_redirects=True)
    assert deleted_timesheet.status_code == 200

    deleted_asset = client.post("/supplier-assets/AST-EDIT-01/delete", data={}, follow_redirects=True)
    assert deleted_asset.status_code == 200

    with app.app_context():
        db = open_db()
        asset_row = db.execute(
            "SELECT COUNT(*) FROM supplier_assets WHERE asset_code = ?",
            ("AST-EDIT-01",),
        ).fetchone()[0]
        timesheet_row = db.execute(
            "SELECT COUNT(*) FROM supplier_timesheets WHERE timesheet_no = ?",
            ("TSH-EDIT-01",),
        ).fetchone()[0]
        voucher_row = db.execute(
            "SELECT COUNT(*) FROM supplier_vouchers WHERE voucher_no = ?",
            ("SPV-EDIT-01",),
        ).fetchone()[0]
        payment_row = db.execute(
            "SELECT COUNT(*) FROM supplier_payments WHERE payment_no = ?",
            ("SPP-EDIT-01",),
        ).fetchone()[0]
        assert asset_row == 0
        assert timesheet_row == 0
        assert voucher_row == 0
        assert payment_row == 0


def test_invoice_center_generates_tax_invoice_pdf_with_line_items(app, client):
    admin_session(client)

    with app.app_context():
        db = open_db()
        db.execute(
            """
            INSERT INTO company_profile (
                company_name, legal_name, trade_license_no, trn_no, vat_status, address,
                phone_number, email, invoice_terms, base_currency
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Current Link",
                "Current Link Transport and General Contracting LLC SPC",
                "CN-12345",
                "100123456700003",
                "Registered",
                "Mussafah M17, Abu Dhabi",
                "0501224963",
                "info@currentlinkgc.com",
                "30 Days",
                "AED",
            ),
        )
        db.execute(
            """
            INSERT INTO parties (
                party_code, party_name, party_kind, party_roles, contact_person, phone_number,
                email, trn_no, address, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "PTY-CUST-01",
                "Al Noor Projects",
                "Company",
                "Customer",
                "Naeem",
                "0501002003",
                "accounts@alnoor.example.com",
                "100987654300003",
                "Dubai Industrial City",
                "Active",
            ),
        )
        db.commit()

    response = client.post(
        "/invoices",
        data={
            "action": "save_invoice",
            "original_invoice_no": "",
            "invoice_no": "INV-CUST-01",
            "invoice_kind": "Sales",
            "document_type": "Tax Invoice",
            "party_code": "PTY-CUST-01",
            "agreement_no": "",
            "lpo_no": "",
            "hire_no": "",
            "issue_date": "2026-05-01",
            "due_date": "2026-05-31",
            "subtotal": "",
            "tax_percent": "5",
            "notes": "April transport and trailer support",
            "line_description_1": "Trailer monthly deployment",
            "line_unit_1": "Month",
            "line_quantity_1": "1",
            "line_rate_1": "12000",
            "line_subtotal_1": "",
            "line_description_2": "Extra standby trips",
            "line_unit_2": "Trips",
            "line_quantity_2": "4",
            "line_rate_2": "250",
            "line_subtotal_2": "",
            "line_description_3": "",
            "line_unit_3": "",
            "line_quantity_3": "",
            "line_rate_3": "",
            "line_subtotal_3": "",
            "line_description_4": "",
            "line_unit_4": "",
            "line_quantity_4": "",
            "line_rate_4": "",
            "line_subtotal_4": "",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Invoice created successfully." in response.data

    pdf_response = client.get("/invoices/INV-CUST-01/pdf", follow_redirects=False)
    assert pdf_response.status_code == 302
    assert "/generated/" in pdf_response.headers["Location"]

    with app.app_context():
        db = open_db()
        invoice_row = db.execute(
            """
            SELECT document_type, subtotal, tax_amount, total_amount, pdf_path
            FROM account_invoices
            WHERE invoice_no = ?
            """,
            ("INV-CUST-01",),
        ).fetchone()
        line_count = db.execute(
            "SELECT COUNT(*) FROM account_invoice_lines WHERE invoice_no = ?",
            ("INV-CUST-01",),
        ).fetchone()[0]

        assert invoice_row is not None
        assert invoice_row["document_type"] == "Tax Invoice"
        assert float(invoice_row["subtotal"]) == 13000.0
        assert float(invoice_row["tax_amount"]) == 650.0
        assert float(invoice_row["total_amount"]) == 13650.0
        assert line_count == 2
        assert invoice_row["pdf_path"].startswith("invoices/")
        assert (Path(app.config["GENERATED_DIR"]) / invoice_row["pdf_path"]).exists()

