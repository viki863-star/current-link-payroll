import re
import shutil
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader
from werkzeug.security import generate_password_hash

from app.database import open_db
from app.pdf_service import generate_kata_pdf, generate_owner_fund_pdf


def admin_session(client):
    with client.session_transaction() as session:
        session["role"] = "admin"
        session["display_name"] = "Admin"


def driver_session(client, driver_id="DRV-T1"):
    with client.session_transaction() as session:
        session["role"] = "driver"
        session["driver_id"] = driver_id
        session["display_name"] = "Driver"


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


def create_supplier_record(
    client,
    *,
    party_code,
    party_name,
    party_kind="Company",
    portal_enabled=False,
    portal_login_email="",
):
    return client.post(
        "/suppliers/admin/register?mode=Normal",
        data={
            "original_party_code": "",
            "party_code": party_code,
            "party_name": party_name,
            "party_kind": party_kind,
            "party_roles": ["Supplier"],
            "contact_person": party_name,
            "phone_number": "0500000001",
            "email": portal_login_email or f"{party_code.lower()}@example.com",
            "portal_login_email": portal_login_email,
            "portal_enabled": "1" if portal_enabled else "",
            "trn_no": f"TRN-{party_code}",
            "trade_license_no": f"LIC-{party_code}",
            "address": "Mussafah",
            "notes": "supplier",
            "status": "Active",
        },
        follow_redirects=True,
    )


def create_customer_record(client, *, party_code, party_name, party_kind="Company"):
    return client.post(
        "/customers",
        data={
            "original_party_code": "",
            "party_code": party_code,
            "party_name": party_name,
            "party_kind": party_kind,
            "contact_person": party_name,
            "phone_number": "0500000002",
            "email": f"{party_code.lower()}@example.com",
            "trn_no": f"TRN-{party_code}",
            "trade_license_no": f"LIC-{party_code}",
            "address": "Abu Dhabi",
            "notes": "customer",
            "status": "Active",
        },
        follow_redirects=True,
    )


def set_supplier_password(client, *, user_id, email, password="secret12"):
    return client.post(
        "/supplier-forgot-password",
        data={
            "user_id": user_id,
            "email": email,
            "password": password,
            "confirm_password": password,
        },
        follow_redirects=True,
    )


def create_supplier_lpo(app, *, lpo_no, party_code, amount=1050.0, description="Portal LPO", status="Approved"):
    with app.app_context():
        db = open_db()
        db.execute(
            """
            INSERT INTO lpos (
                lpo_no, party_code, quotation_no, agreement_no, issue_date, valid_until,
                amount, tax_percent, description, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (lpo_no, party_code, None, None, "2026-04-01", "2026-04-30", amount, 5.0, description, status),
        )
        db.commit()


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
            "prorata_end_date": "2026-04-29",
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
        assert float(row["salary_days"]) == 21.0
        assert float(row["daily_rate"]) == 100.0
        assert float(row["monthly_basic_salary"]) == 3000.0
        assert float(row["basic_salary"]) == 2100.0
        assert float(row["net_salary"]) == 2100.0


def test_salary_store_prorata_uses_selected_duty_range(app, client):
    create_driver_record(app, basic_salary=3000.0, duty_start="2026-04-01")
    admin_session(client)

    response = client.post(
        "/drivers/DRV-T1/salary-store",
        data={
            "entry_date": "2026-04-30",
            "salary_month": "2026-04",
            "salary_mode": "prorata",
            "prorata_start_date": "2026-04-09",
            "prorata_end_date": "2026-04-29",
            "ot_hours": "0",
            "personal_vehicle": "0",
            "remarks": "9 to 29 duty",
            "action": "calculate",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"21.00" in response.data
    assert b"2026-04-09 to 2026-04-29" in response.data


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
            SELECT salary_month, total_deductions, remaining_advance, net_payable,
                   salary_after_deduction, actual_paid_amount, company_balance_due
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
        assert float(slips[0]["salary_after_deduction"]) == 2900.0
        assert float(slips[0]["actual_paid_amount"]) == 2900.0
        assert float(slips[0]["company_balance_due"]) == 0.0
        assert float(slips[0]["net_payable"]) == 2900.0
        assert slips[1]["salary_month"] == "2026-05"
        assert float(slips[1]["total_deductions"]) == 200.0
        assert float(slips[1]["remaining_advance"]) == 200.0
        assert float(slips[1]["salary_after_deduction"]) == 2800.0
        assert float(slips[1]["actual_paid_amount"]) == 2800.0
        assert float(slips[1]["company_balance_due"]) == 0.0
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
    assert b"monthly statement refreshed" in first_slip.data

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
    assert b"monthly statement refreshed" in updated_slip.data

    with app.app_context():
        db = open_db()
        slips = db.execute(
            """
            SELECT salary_month, total_deductions, remaining_advance, net_payable,
                   salary_after_deduction, actual_paid_amount, company_balance_due,
                   payment_source, paid_by
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
        assert float(slips[0]["salary_after_deduction"]) == 2800.0
        assert float(slips[0]["actual_paid_amount"]) == 2800.0
        assert float(slips[0]["company_balance_due"]) == 0.0
        assert float(slips[0]["net_payable"]) == 2800.0
        assert slips[0]["payment_source"] == "Office"
        assert slips[0]["paid_by"] == "Admin"


def test_salary_slip_supports_custom_actual_paid_and_company_balance(app, client):
    create_driver_record(app, basic_salary=5000.0)
    admin_session(client)

    client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-04-10",
            "txn_type": "Advance",
            "source": "Owner Fund",
            "given_by": "Office",
            "amount": "1424",
            "details": "Advance before salary",
        },
        follow_redirects=True,
    )

    stored = client.post(
        "/drivers/DRV-T1/salary-store",
        data={
            "entry_date": "2026-04-30",
            "salary_month": "2026-04",
            "ot_hours": "0",
            "personal_vehicle": "300",
            "personal_vehicle_note": "Recovery trip",
            "remarks": "April salary",
            "action": "save",
        },
        follow_redirects=True,
    )
    assert b"Salary stored successfully." in stored.data
    assert b"5300.00" in stored.data
    assert b"Recovery trip" in stored.data

    slip = client.post(
        "/drivers/DRV-T1/salary-slip",
        data={
            "salary_store_id": "1",
            "deduction_amount": "1424",
            "actual_paid_amount": "3500",
            "payment_source": "Owner Fund",
            "paid_by": "Waqar",
        },
        follow_redirects=True,
    )

    assert b"monthly statement refreshed" in slip.data
    assert b"Salary After Deduction" in slip.data
    assert b"AED 3876.00" in slip.data
    assert b"Actual Paid" in slip.data
    assert b"AED 3500.00" in slip.data
    assert b"Company Balance" in slip.data
    assert b"AED 376.00" in slip.data
    assert b"Personal / Vehicle Note" in slip.data
    assert b"Recovery trip" in slip.data

    with app.app_context():
        db = open_db()
        slip_row = db.execute(
            """
            SELECT total_deductions, remaining_advance, salary_after_deduction,
                   actual_paid_amount, company_balance_due, net_payable
            FROM salary_slips
            WHERE driver_id = ? AND salary_month = ?
            """,
            ("DRV-T1", "2026-04"),
        ).fetchone()
        assert slip_row is not None
        assert float(slip_row["total_deductions"]) == 1424.0
        assert float(slip_row["remaining_advance"]) == 0.0
        assert float(slip_row["salary_after_deduction"]) == 3876.0
        assert float(slip_row["actual_paid_amount"]) == 3500.0
        assert float(slip_row["company_balance_due"]) == 376.0
        assert float(slip_row["net_payable"]) == 3500.0

    action_page = client.get("/drivers/DRV-T1?kata_month=2026-04")
    assert action_page.status_code == 200
    assert b"Salary" in action_page.data
    assert b"Remaining Salary" in action_page.data
    assert b"Previous Balance" in action_page.data
    assert b"Total Salary" in action_page.data
    assert b"Received Not Yet Deducted" in action_page.data
    assert b"Recovery trip" in action_page.data
    assert b"No unrecovered cash entries for this month." in action_page.data
    assert b"AED 5300.00" in action_page.data


def test_salary_slip_rejects_actual_paid_over_salary_after_deduction(app, client):
    create_driver_record(app, basic_salary=3000.0)
    admin_session(client)

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

    response = client.post(
        "/drivers/DRV-T1/salary-slip",
        data={
            "salary_store_id": "1",
            "deduction_amount": "100",
            "actual_paid_amount": "5000",
            "payment_source": "Office",
            "paid_by": "Admin",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'name="actual_paid_amount"' in response.data
    assert b'value="5000"' in response.data

    with app.app_context():
        db = open_db()
        count = db.execute("SELECT COUNT(*) FROM salary_slips WHERE driver_id = ?", ("DRV-T1",)).fetchone()[0]
        assert count == 0


def test_driver_transactions_page_shows_full_history_and_salary_paid_rows(app, client):
    create_driver_record(app, basic_salary=3000.0)
    admin_session(client)

    client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-02-10",
            "txn_type": "Advance",
            "source": "Owner Fund",
            "given_by": "Office",
            "amount": "200",
            "details": "Old visa",
        },
        follow_redirects=True,
    )
    client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-04-11",
            "txn_type": "Petty Cash",
            "source": "Office",
            "given_by": "Nasrullah",
            "amount": "300",
            "details": "Fuel for April",
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
    client.post(
        "/drivers/DRV-T1/salary-slip",
        data={
            "salary_store_id": "1",
            "deduction_amount": "100",
            "payment_source": "Bank",
            "paid_by": "Waqar",
        },
        follow_redirects=True,
    )

    response = client.get("/drivers/DRV-T1/transactions", follow_redirects=True)

    assert response.status_code == 200
    assert b"Show All Transactions" in response.data
    assert b"All Transactions" in response.data
    assert b"Old visa" in response.data
    assert b"Fuel for April" in response.data
    assert b"Salary Paid" in response.data
    assert b"April salary" in response.data
    assert b"Bank" in response.data
    assert b"Edit Slip" in response.data
    assert b"Delete Slip" in response.data


def test_salary_paid_entry_can_be_deleted_from_transaction_history(app, client):
    create_driver_record(app, basic_salary=3000.0)
    admin_session(client)

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
    client.post(
        "/drivers/DRV-T1/salary-slip",
        data={
            "salary_store_id": "1",
            "deduction_amount": "100",
            "payment_source": "Office",
            "paid_by": "Admin",
        },
        follow_redirects=True,
    )

    response = client.post("/drivers/DRV-T1/salary-slip/1/delete", data={}, follow_redirects=True)

    assert response.status_code == 200

    with app.app_context():
        db = open_db()
        count = db.execute("SELECT COUNT(*) FROM salary_slips WHERE driver_id = ?", ("DRV-T1",)).fetchone()[0]
        assert count == 0


def test_kata_pdf_accepts_postgres_datetime_generated_at(app):
    driver = create_driver_record(app)
    output_dir = Path.cwd() / "generated" / "test-runs" / f"kata-pdf-{uuid4().hex}"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
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
            str(output_dir),
            str(Path(app.root_path).parent / "app" / "static"),
        )

        assert Path(output_path).exists()
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_monthly_kata_pdf_uses_paper_style_summary_labels(app):
    driver = create_driver_record(app)
    output_dir = Path.cwd() / "generated" / "test-runs" / f"monthly-paper-kata-{uuid4().hex}"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        output_path = generate_kata_pdf(
            driver,
            [
                {
                    "entry_date": "2026-03-31",
                    "salary_month": "2026-03",
                    "basic_salary": 4500.0,
                    "ot_amount": 0.0,
                    "personal_vehicle": 800.0,
                    "net_salary": 5300.0,
                    "remarks": "March salary",
                    "personal_vehicle_note": "Recovery trip",
                },
                {
                    "entry_date": "2026-04-30",
                    "salary_month": "2026-04",
                    "basic_salary": 4500.0,
                    "ot_amount": 300.0,
                    "personal_vehicle": 500.0,
                    "net_salary": 5300.0,
                    "remarks": "April salary",
                    "personal_vehicle_note": "Recovery trip",
                }
            ],
            [
                {
                    "entry_date": "2026-03-10",
                    "txn_type": "Advance",
                    "source": "Owner Fund",
                    "given_by": "Office",
                    "amount": 1424.0,
                    "details": "March advance",
                },
                {
                    "entry_date": "2026-04-10",
                    "txn_type": "Advance",
                    "source": "Owner Fund",
                    "given_by": "Office",
                    "amount": 1424.0,
                    "details": "Advance before salary",
                }
            ],
            [
                {
                    "generated_at": "2026-03-31 10:30:00",
                    "salary_month": "2026-03",
                    "total_deductions": 1424.0,
                    "salary_after_deduction": 3876.0,
                    "actual_paid_amount": 3500.0,
                    "company_balance_due": 376.0,
                    "net_payable": 3500.0,
                    "payment_source": "Owner Fund",
                    "paid_by": "Waqar",
                },
                {
                    "generated_at": "2026-04-30 10:30:00",
                    "salary_month": "2026-04",
                    "total_deductions": 1424.0,
                    "salary_after_deduction": 3876.0,
                    "actual_paid_amount": 3500.0,
                    "company_balance_due": 376.0,
                    "net_payable": 3500.0,
                    "payment_source": "Owner Fund",
                    "paid_by": "Waqar",
                }
            ],
            [],
            str(output_dir),
            str(Path(app.root_path).parent / "app" / "static"),
            month_value="2026-04",
        )

        extracted_text = "\n".join(page.extract_text() or "" for page in PdfReader(output_path).pages)
        assert "HISAAB SUMMARY" in extracted_text
        assert "Closed Previous Hisaab" in extracted_text
        assert "Previous Balance" in extracted_text
        assert "Total Salary" in extracted_text
        assert "Received Not Yet" in extracted_text
        assert "Deducted" in extracted_text
        assert "REMAINING SALARY" in extracted_text
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_full_kata_pdf_keeps_all_history_rows_across_pages(app):
    driver = create_driver_record(app)
    output_dir = Path.cwd() / "generated" / "test-runs" / f"full-kata-{uuid4().hex}"
    output_dir.mkdir(parents=True, exist_ok=True)

    transactions = []
    for index in range(1, 27):
        transactions.append(
            {
                "entry_date": f"2026-04-{((index - 1) % 28) + 1:02d}",
                "txn_type": "Petty Cash",
                "source": "Owner Direct",
                "given_by": f"Owner {index}",
                "amount": 100.0 + index,
                "details": f"History row {index}",
            }
        )

    try:
        output_path = generate_kata_pdf(
            driver,
            [],
            transactions,
            [],
            str(output_dir),
            str(Path(app.root_path).parent / "app" / "static"),
            month_value=None,
        )

        reader = PdfReader(output_path)
        extracted_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        assert len(reader.pages) >= 2
        assert "History row 1" in extracted_text
        assert "History row 26" in extracted_text
        assert "Start to End" in extracted_text
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_driver_portal_shows_only_selected_month_kata_entries(app, client):
    create_driver_record(app, basic_salary=3000.0)
    admin_session(client)

    client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-02-10",
            "txn_type": "Advance",
            "source": "Owner Fund",
            "given_by": "Owner",
            "amount": "200",
            "details": "Old visa",
        },
        follow_redirects=True,
    )
    client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-03-11",
            "txn_type": "Petty Cash",
            "source": "Office",
            "given_by": "Office",
            "amount": "300",
            "details": "Fuel for March",
        },
        follow_redirects=True,
    )
    client.post(
        "/drivers/DRV-T1/salary-store",
        data={
            "entry_date": "2026-03-31",
            "salary_month": "2026-03",
            "ot_hours": "0",
            "personal_vehicle": "0",
            "remarks": "March salary",
            "action": "save",
        },
        follow_redirects=True,
    )
    client.post(
        "/drivers/DRV-T1/salary-slip",
        data={
            "salary_store_id": "1",
            "deduction_amount": "100",
            "payment_source": "Office",
            "paid_by": "Waqar",
        },
        follow_redirects=True,
    )

    driver_session(client)
    response = client.get("/portal/driver?month=2026-03")

    assert response.status_code == 200
    assert b"Monthly Statement" in response.data
    assert b"Previous Balance" in response.data
    assert b"Total Salary" in response.data
    assert b"Given By" in response.data
    assert b"Details" in response.data
    assert b"Fuel for March" in response.data
    assert b"Office" in response.data
    assert b"March salary" in response.data
    assert b"Old visa" not in response.data
    assert b"2026-02-10" not in response.data
    assert b"Received Not Yet Deducted" in response.data
    assert b"AED 200.00" in response.data
    assert b"Remaining Salary" in response.data
    assert b"AED 2800.00" in response.data


def test_driver_monthly_kata_pdf_route_uses_selected_month_filename(app, client):
    create_driver_record(app, basic_salary=3000.0)
    admin_session(client)

    client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-03-11",
            "txn_type": "Petty Cash",
            "source": "Owner Direct",
            "given_by": "Owner",
            "amount": "300",
            "details": "Visa expense",
        },
        follow_redirects=True,
    )

    response = client.get("/drivers/DRV-T1/kata-pdf?month=2026-03", follow_redirects=False)

    assert response.status_code == 302
    assert "kata-2026-03" in response.headers["Location"]


def test_driver_action_page_keeps_selected_kata_month(app, client):
    create_driver_record(app, basic_salary=3000.0)
    admin_session(client)

    client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-02-10",
            "txn_type": "Advance",
            "source": "Owner Fund",
            "given_by": "Owner",
            "amount": "200",
            "details": "Old visa",
        },
        follow_redirects=True,
    )
    client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-03-11",
            "txn_type": "Petty Cash",
            "source": "Office",
            "given_by": "Office",
            "amount": "300",
            "details": "Fuel for March",
        },
        follow_redirects=True,
    )
    client.post(
        "/drivers/DRV-T1/salary-store",
        data={
            "entry_date": "2026-03-31",
            "salary_month": "2026-03",
            "ot_hours": "0",
            "personal_vehicle": "0",
            "remarks": "March salary",
            "action": "save",
        },
        follow_redirects=True,
    )
    client.post(
        "/drivers/DRV-T1/salary-slip",
        data={
            "salary_store_id": "1",
            "deduction_amount": "100",
            "payment_source": "Office",
            "paid_by": "Waqar",
        },
        follow_redirects=True,
    )

    response = client.get("/drivers/DRV-T1?kata_month=2026-03")

    assert response.status_code == 200
    assert b'input type="month" name="kata_month" value="2026-03"' in response.data
    assert b"Statement Month" in response.data
    assert b"Driver Statement Desk" in response.data
    assert b"Deductions" in response.data
    assert b"Salary" in response.data
    assert b"Given By" in response.data
    assert b"Details" in response.data
    assert b"Previous Balance" in response.data
    assert b"Total Salary" in response.data
    assert b"Fuel for March" in response.data
    assert b"March salary" in response.data
    assert b"Old visa" not in response.data
    assert b"2026-03" in response.data
    assert b"/drivers/DRV-T1/kata-pdf?month=2026-03" in response.data
    assert b"Received Not Yet Deducted" in response.data
    assert b"AED 200.00" in response.data
    assert b"Remaining Salary" in response.data
    assert b"AED 2800.00" in response.data


def test_driver_statement_carries_previous_month_balance_into_next_month(app, client):
    create_driver_record(app, basic_salary=4500.0)
    admin_session(client)

    client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-03-10",
            "txn_type": "Advance",
            "source": "Owner Fund",
            "given_by": "Office",
            "amount": "1424",
            "details": "March advance",
        },
        follow_redirects=True,
    )
    client.post(
        "/drivers/DRV-T1/salary-store",
        data={
            "entry_date": "2026-03-31",
            "salary_month": "2026-03",
            "ot_hours": "0",
            "personal_vehicle": "800",
            "remarks": "March salary",
            "personal_vehicle_note": "Recovery trip",
            "action": "save",
        },
        follow_redirects=True,
    )
    client.post(
        "/drivers/DRV-T1/salary-slip",
        data={
            "salary_store_id": "1",
            "deduction_amount": "1424",
            "actual_paid_amount": "3500",
            "payment_source": "Owner Direct",
            "paid_by": "Waqar",
        },
        follow_redirects=True,
    )
    client.post(
        "/drivers/DRV-T1/transactions",
        data={
            "entry_date": "2026-04-05",
            "txn_type": "Advance",
            "source": "Owner Fund",
            "given_by": "Owner",
            "amount": "69",
            "details": "Eid kharcha",
        },
        follow_redirects=True,
    )
    client.post(
        "/drivers/DRV-T1/salary-store",
        data={
            "entry_date": "2026-04-30",
            "salary_month": "2026-04",
            "ot_hours": "0",
            "personal_vehicle": "630",
            "remarks": "April salary",
            "personal_vehicle_note": "Petrol",
            "action": "save",
        },
        follow_redirects=True,
    )
    client.post(
        "/drivers/DRV-T1/salary-slip",
        data={
            "salary_store_id": "2",
            "deduction_amount": "69",
            "actual_paid_amount": "3500",
            "payment_source": "Owner Direct",
            "paid_by": "Waqar",
        },
        follow_redirects=True,
    )

    response = client.get("/drivers/DRV-T1?kata_month=2026-04")

    assert response.status_code == 200
    assert b"Closed Previous Hisaab" in response.data
    assert b"March advance" in response.data
    assert b"March salary" not in response.data
    assert b"Previous Balance" in response.data
    assert b"AED 376.00" in response.data
    assert b"April salary" in response.data
    assert b"Eid kharcha" not in response.data
    assert b"Earning | Apr 2026" in response.data
    assert b"Received Not Yet Deducted" in response.data
    assert b"Remaining Salary" in response.data
    assert b"AED 5506.00" in response.data


def test_owner_fund_pdf_supports_filtered_multi_page_output(app):
    rows = []
    running_balance = 0.0
    for index in range(1, 43):
        incoming = 50000.0 if index == 1 else (2500.0 if index % 9 == 0 else 0.0)
        outgoing = 3100.0 if index % 3 == 0 else 650.0
        running_balance += incoming - outgoing
        rows.append(
            {
                "entry_date": f"2026-04-{((index - 1) % 28) + 1:02d}",
                "movement": "Incoming" if incoming else "Outgoing",
                "reference": f"Owner Flow / REF-{index:03d}",
                "party": "Waqar" if index % 2 else "Driver Desk",
                "details": f"Owner fund movement row {index} with 50000 tracking details",
                "incoming": incoming,
                "outgoing": outgoing,
                "balance": running_balance,
            }
        )

    output_dir = Path.cwd() / "generated" / "test-runs" / f"owner-fund-pdf-{uuid4().hex}"
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        output_path = generate_owner_fund_pdf(
            rows,
            {
                "incoming": sum(float(row["incoming"]) for row in rows),
                "outgoing": sum(float(row["outgoing"]) for row in rows),
                "balance": sum(float(row["incoming"]) for row in rows) - sum(float(row["outgoing"]) for row in rows),
                "closing_balance": running_balance,
                "overall_balance": running_balance,
                "overall_incoming": sum(float(row["incoming"]) for row in rows),
                "overall_outgoing": sum(float(row["outgoing"]) for row in rows),
            },
            str(output_dir),
            str(Path(app.root_path).parent / "app" / "static"),
            filters={"month": "2026-04", "movement": "Outgoing", "search": "50000"},
        )

        pdf_file = Path(output_path)
        assert pdf_file.exists()
        raw_bytes = pdf_file.read_bytes()
        assert len(re.findall(rb"/Type /Page\b", raw_bytes)) >= 2
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


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


def test_owner_fund_filters_scope_statement_and_pdf_link(app, client):
    admin_session(client)
    create_driver_record(app)

    with app.app_context():
        db = open_db()
        db.execute(
            """
            INSERT INTO owner_fund_entries (owner_name, entry_date, amount, received_by, payment_method, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Nasrullah", "2026-04-12", 50000.0, "Waqar", "Cash", "capital"),
        )
        db.execute(
            """
            INSERT INTO owner_fund_entries (owner_name, entry_date, amount, received_by, payment_method, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Nasrullah", "2026-05-03", 9000.0, "Waqar", "Cash", "future capital"),
        )
        db.execute(
            """
            INSERT INTO driver_transactions (driver_id, entry_date, txn_type, source, given_by, amount, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("DRV-T1", "2026-04-14", "Advance", "Owner Fund", "Office", 1200.0, "50000 allocation"),
        )
        db.execute(
            """
            INSERT INTO salary_slips (driver_id, salary_store_id, salary_month, generated_at, total_deductions, net_payable, remaining_advance, payment_source, paid_by, pdf_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("DRV-T1", 0, "2026-04", "2026-04-15 10:30:00", 0.0, 3000.0, 0.0, "Owner Fund", "Waqar", ""),
        )
        db.commit()

    response = client.get("/owner-fund?month=2026-04&movement=Outgoing&search=50000")

    assert response.status_code == 200
    assert b"View Used" in response.data
    assert b"Driver Txn / Test Driver" in response.data
    assert b"month=2026-04&amp;movement=Outgoing&amp;search=50000" in response.data

    driver_name_response = client.get("/owner-fund?month=2026-04&movement=Outgoing&search=Test")
    assert driver_name_response.status_code == 200
    assert b"Driver Txn / Test Driver" in driver_name_response.data
    assert b"Salary Slip / Test Driver" in driver_name_response.data


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
        "/suppliers/admin/register?mode=Normal",
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
        "/suppliers/admin/register?mode=Normal",
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

    supplier_detail = client.get("/suppliers/PTY-SUP-01?screen=billing", follow_redirects=True)
    assert supplier_detail.status_code == 200
    assert b"Hussain Logistics" in supplier_detail.data
    assert b"SPV-HUS-01" in supplier_detail.data
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
        "/suppliers/admin/register?mode=Normal",
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


def test_individual_supplier_cannot_activate_portal(app, client):
    admin_session(client)
    response = create_supplier_record(
        client,
        party_code="PTY-IND-01",
        party_name="Individual Supplier",
        party_kind="Individual",
        portal_enabled=True,
        portal_login_email="individual@example.com",
    )
    assert b"Supplier registered successfully." in response.data

    client.get("/logout", follow_redirects=False)
    password_setup = set_supplier_password(
        client,
        user_id="pty-ind-01",
        email="individual@example.com",
    )
    assert b"Supplier portal account was not found." in password_setup.data


def test_company_supplier_portal_can_activate_login_submit_and_convert(app, client):
    admin_session(client)
    response = create_supplier_record(
        client,
        party_code="PTY-COMP-01",
        party_name="Portal Supplier LLC",
        party_kind="Company",
        portal_enabled=True,
        portal_login_email="portal@example.com",
    )
    assert b"Supplier registered successfully." in response.data

    client.get("/logout", follow_redirects=False)
    password_setup = set_supplier_password(
        client,
        user_id="pty-comp-01",
        email="portal@example.com",
    )
    assert b"Password updated. You can sign in now." in password_setup.data

    login = client.post(
        "/supplier-login",
        data={"user_id": "pty-comp-01", "password": "secret12"},
        follow_redirects=False,
    )
    assert login.status_code == 302
    assert "/portal/supplier" in login.headers["Location"]

    create_supplier_lpo(app, lpo_no="LPO-PORT-01", party_code="PTY-COMP-01")

    submit = client.post(
        "/portal/supplier",
        data={
            "action": "submit_invoice",
            "submission_no": "SIN-PORT-01",
            "lpo_no": "LPO-PORT-01",
            "external_invoice_no": "INV-PORT-01",
            "invoice_date": "2026-04-15",
            "period_month": "2026-04",
            "subtotal": "1000",
            "vat_amount": "50",
            "total_amount": "1050",
            "notes": "portal invoice",
            "invoice_attachment": (BytesIO(b"invoice"), "invoice.pdf"),
            "timesheet_attachment": (BytesIO(b"timesheet"), "timesheet.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Invoice submitted successfully." in submit.data

    client.get("/logout", follow_redirects=False)
    admin_session(client)

    approve = client.post(
        "/suppliers/PTY-COMP-01",
        data={
            "action": "approve_submission",
            "submission_no": "SIN-PORT-01",
        },
        follow_redirects=True,
    )
    assert b"Supplier invoice approved" in approve.data

    convert = client.post(
        "/suppliers/PTY-COMP-01",
        data={
            "action": "convert_submission",
            "submission_no": "SIN-PORT-01",
        },
        follow_redirects=True,
    )
    assert b"Supplier invoice converted into payable voucher." in convert.data

    with app.app_context():
        db = open_db()
        submission = db.execute(
            """
            SELECT review_status, linked_voucher_no, invoice_attachment_path, timesheet_attachment_path
            FROM supplier_invoice_submissions
            WHERE submission_no = ?
            """,
            ("SIN-PORT-01",),
        ).fetchone()
        voucher = db.execute(
            """
            SELECT source_type, source_reference, total_amount, balance_amount, paid_amount
            FROM supplier_vouchers
            WHERE voucher_no = ?
            """,
            (submission["linked_voucher_no"],),
        ).fetchone()
        assert submission["review_status"] == "Converted"
        assert submission["linked_voucher_no"]
        assert submission["invoice_attachment_path"].startswith("suppliers/PTY-COMP-01/")
        assert submission["timesheet_attachment_path"].startswith("suppliers/PTY-COMP-01/")
        assert voucher["source_type"] == "Submission"
        assert voucher["source_reference"] == "SIN-PORT-01"
        assert float(voucher["total_amount"]) == 1050.0
        assert float(voucher["balance_amount"]) == 1050.0
        assert float(voucher["paid_amount"]) == 0.0


def test_admin_by_hand_supplier_submission_defaults_to_approved_ready(app, client):
    admin_session(client)
    response = create_supplier_record(
        client,
        party_code="PTY-HAND-01",
        party_name="Manual Supplier LLC",
        party_kind="Company",
    )
    assert b"Supplier registered successfully." in response.data

    saved = client.post(
        "/suppliers/PTY-HAND-01",
        data={
            "action": "save_submission",
            "submission_no": "SIN-HAND-01",
            "external_invoice_no": "INV-HAND-01",
            "invoice_date": "2026-04-16",
            "period_month": "2026-04",
            "subtotal": "2000",
            "vat_amount": "100",
            "total_amount": "2100",
            "notes": "manual paper checked",
        },
        follow_redirects=True,
    )
    assert b"By-hand supplier invoice saved" in saved.data

    statement_page = client.get("/suppliers/PTY-HAND-01?screen=statement", follow_redirects=True)
    assert b"INV-HAND-01" in statement_page.data
    assert b"Outstanding" in statement_page.data
    assert b"Approved" in statement_page.data

    with app.app_context():
        db = open_db()
        submission = db.execute(
            """
            SELECT review_status, review_note, linked_voucher_no, total_amount
            FROM supplier_invoice_submissions
            WHERE submission_no = ?
            """,
            ("SIN-HAND-01",),
        ).fetchone()
        assert submission["review_status"] == "Approved"
        assert submission["review_note"] == "Ready for Voucher"
        assert submission["linked_voucher_no"] is None
        assert float(submission["total_amount"]) == 2100.0


def test_supplier_portal_statement_hides_rejected_rows_but_allows_resubmit(app, client):
    admin_session(client)
    create_supplier_record(
        client,
        party_code="PTY-REJ-01",
        party_name="Rejected Portal Supplier",
        party_kind="Company",
        portal_enabled=True,
        portal_login_email="reject@example.com",
    )
    client.get("/logout", follow_redirects=False)
    client.post(
        "/supplier-forgot-password",
        data={
            "user_id": "pty-rej-01",
            "email": "reject@example.com",
            "password": "secret12",
            "confirm_password": "secret12",
        },
        follow_redirects=True,
    )
    client.post("/supplier-login", data={"user_id": "pty-rej-01", "password": "secret12"}, follow_redirects=True)

    with app.app_context():
        db = open_db()
        db.execute(
            """
            INSERT INTO supplier_invoice_submissions (
                submission_no, party_code, source_channel, external_invoice_no, period_month,
                invoice_date, subtotal, vat_amount, total_amount, review_status, review_note,
                created_by_role, created_by_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "SIN-REJ-01",
                "PTY-REJ-01",
                "Portal",
                "INV-REJ-01",
                "2026-04",
                "2026-04-01",
                1000.0,
                50.0,
                1050.0,
                "Rejected",
                "Wrong invoice",
                "supplier",
                "Rejected Portal Supplier",
            ),
        )
        db.commit()

    portal_page = client.get("/portal/supplier", follow_redirects=True)
    assert b"INV-REJ-01" in portal_page.data
    assert b"Resubmit" in portal_page.data
    assert b"Rejected" in portal_page.data
    assert b"Wrong invoice" in portal_page.data
    assert b"Statement of account" in portal_page.data
    statement_slice = portal_page.data.split(b"Statement of account", 1)[1]
    assert b"INV-REJ-01" not in statement_slice

    resubmit = client.get("/portal/supplier?resubmit_submission=SIN-REJ-01", follow_redirects=True)
    assert b"You can resubmit this invoice with corrected files or amounts." in resubmit.data
    assert b"INV-REJ-01" in resubmit.data


def test_supplier_partnership_and_double_shift_flow_tracks_monthly_split(app, client):
    create_driver_record(app, driver_id="DRV-PART-1", full_name="Core Driver Safe")
    admin_session(client)

    client.post(
        "/suppliers/partnership",
        data={
            "party_code": "PTY-PART-01",
            "party_name": "Hussain Partner Fleet",
            "party_kind": "Company",
            "party_roles": ["Supplier", "Partner"],
            "supplier_mode": "Partnership",
            "partner_name": "Hussain",
            "default_company_share_percent": "50",
            "default_partner_share_percent": "50",
            "contact_person": "Hussain",
            "phone_number": "0502003004",
            "email": "hussain.partner@example.com",
            "trn_no": "TRN-PART-1",
            "trade_license_no": "LIC-PART-1",
            "address": "Mussafah",
            "notes": "50/50 tanker partnership",
            "status": "Active",
        },
        follow_redirects=True,
    )

    asset_response = client.post(
        "/suppliers/PTY-PART-01",
        data={
            "action": "save_asset",
            "original_asset_code": "",
            "asset_code": "AST-PART-01",
            "asset_name": "Tanker 50-50",
            "asset_type": "Tanker",
            "vehicle_no": "TNK-501",
            "rate_basis": "Hours",
            "default_rate": "150",
            "double_shift_mode": "Double Shift",
            "partnership_mode": "Partnership",
            "partner_name": "Hussain",
            "company_share_percent": "50",
            "partner_share_percent": "50",
            "day_shift_paid_by": "Company",
            "night_shift_paid_by": "Partner",
            "capacity": "5000 Gallon",
            "status": "Active",
            "notes": "Shared tanker with double shift",
        },
        follow_redirects=True,
    )
    assert asset_response.status_code == 200

    client.post(
        "/suppliers/PTY-PART-01",
        data={
            "action": "save_timesheet",
            "original_timesheet_no": "",
            "timesheet_no": "TSH-PART-01",
            "asset_code": "AST-PART-01",
            "period_month": "2026-04",
            "entry_date": "2026-04-30",
            "billing_basis": "Hours",
            "billable_qty": "100",
            "timesheet_hours": "100",
            "rate": "150",
            "status": "Open",
            "notes": "April partnership work",
        },
        follow_redirects=True,
    )

    client.post(
        "/suppliers/PTY-PART-01",
        data={
            "action": "save_partnership_entry",
            "original_entry_no": "",
            "entry_no": "PEN-0001",
            "asset_code": "AST-PART-01",
            "period_month": "2026-04",
            "entry_date": "2026-04-30",
            "entry_kind": "Vehicle Expense",
            "expense_head": "Fuel",
            "shift_label": "General",
            "driver_name": "",
            "paid_by": "Partner",
            "amount": "2000",
            "notes": "Fuel paid by partner",
        },
        follow_redirects=True,
    )

    client.post(
        "/suppliers/PTY-PART-01",
        data={
            "action": "save_partnership_entry",
            "original_entry_no": "",
            "entry_no": "PEN-0002",
            "asset_code": "AST-PART-01",
            "period_month": "2026-04",
            "entry_date": "2026-04-30",
            "entry_kind": "Driver Salary",
            "expense_head": "Day shift salary",
            "shift_label": "Day",
            "driver_name": "Company Driver",
            "paid_by": "Company",
            "amount": "2500",
            "notes": "Day shift paid by company",
        },
        follow_redirects=True,
    )

    client.post(
        "/suppliers/PTY-PART-01",
        data={
            "action": "save_partnership_entry",
            "original_entry_no": "",
            "entry_no": "PEN-0003",
            "asset_code": "AST-PART-01",
            "period_month": "2026-04",
            "entry_date": "2026-04-30",
            "entry_kind": "Driver Salary",
            "expense_head": "Night shift salary",
            "shift_label": "Night",
            "driver_name": "Partner Driver",
            "paid_by": "Partner",
            "amount": "2400",
            "notes": "Night shift paid by partner",
        },
        follow_redirects=True,
    )

    detail = client.get("/suppliers/PTY-PART-01?screen=partnership&partnership_month=2026-04", follow_redirects=True)
    assert detail.status_code == 200
    assert b"Double Shift" in detail.data
    assert b"Vehicle Profit Result" in detail.data
    assert b"Hussain" in detail.data
    assert b"Company Should Receive" in detail.data
    assert b"Partner Should Receive" in detail.data

    with app.app_context():
        db = open_db()
        asset_row = db.execute(
            """
            SELECT double_shift_mode, partnership_mode, partner_name,
                   company_share_percent, partner_share_percent,
                   day_shift_paid_by, night_shift_paid_by
            FROM supplier_assets
            WHERE asset_code = ?
            """,
            ("AST-PART-01",),
        ).fetchone()
        entry_count = db.execute(
            "SELECT COUNT(*) FROM supplier_partnership_entries WHERE asset_code = ?",
            ("AST-PART-01",),
        ).fetchone()[0]

        assert asset_row is not None
        assert asset_row["double_shift_mode"] == "Double Shift"
        assert asset_row["partnership_mode"] == "Partnership"
        assert asset_row["partner_name"] == "Hussain"
        assert float(asset_row["company_share_percent"]) == 50.0
        assert float(asset_row["partner_share_percent"]) == 50.0
        assert asset_row["day_shift_paid_by"] == "Company"
        assert asset_row["night_shift_paid_by"] == "Partner"
        assert entry_count == 3
        assert db.execute("SELECT COUNT(*) FROM drivers WHERE driver_id = ?", ("DRV-PART-1",)).fetchone()[0] == 1


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
        pdf_path = Path(app.config["GENERATED_DIR"]) / invoice_row["pdf_path"]
        assert pdf_path.exists()

    extracted_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)
    assert "Tax Invoice" in extracted_text
    assert "SELLER" in extracted_text
    assert "BILL TO" in extracted_text
    assert "SUBTOTAL" in extracted_text
    assert "VAT" in extracted_text
    assert "TOTAL AMOUNT" in extracted_text
    assert "INVOICE NO" not in extracted_text
    assert "ISSUE DATE" not in extracted_text
    assert "DUE DATE" not in extracted_text
    assert "STATUS" not in extracted_text
    assert "KIND" not in extracted_text
    assert "AGREEMENT" not in extracted_text
    assert "LPO" not in extracted_text
    assert "HIRE" not in extracted_text
    assert "PAID" not in extracted_text
    assert "BALANCE" not in extracted_text


def test_fleet_maintenance_tracks_advance_workshop_credit_and_partnership_split(app, client):
    admin_session(client)

    with app.app_context():
        db = open_db()
        db.execute(
            """
            INSERT INTO parties (
                party_code, party_name, party_kind, party_roles, contact_person,
                phone_number, email, trn_no, address, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "PTY-WS-01",
                "Zaraki Auto Shop",
                "Company",
                "Supplier",
                "Workshop",
                "0501000001",
                "shop@example.com",
                "",
                "Mussafah",
                "Active",
            ),
        )
        db.execute(
            """
            INSERT INTO parties (
                party_code, party_name, party_kind, party_roles, contact_person,
                phone_number, email, trn_no, address, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "PTY-PART-02",
                "Hussain Partnership",
                "Company",
                "Partner",
                "Hussain",
                "0502000002",
                "partner@example.com",
                "",
                "Abu Dhabi",
                "Active",
            ),
        )
        db.commit()

    vehicle_standard = client.post(
        "/fleet-maintenance",
        data={
            "action": "save_vehicle",
            "original_vehicle_id": "",
            "vehicle_id": "VEH-0001",
            "vehicle_no": "TNK-101",
            "vehicle_type": "Water Tanker",
            "make_model": "Hino 5000",
            "status": "Active",
            "shift_mode": "Single Shift",
            "ownership_mode": "Standard",
            "partner_party_code": "",
            "partner_name": "",
            "company_share_percent": "100",
            "partner_share_percent": "0",
            "notes": "Own tanker",
        },
        follow_redirects=True,
    )
    assert b"Vehicle saved successfully." in vehicle_standard.data

    vehicle_partnership = client.post(
        "/fleet-maintenance",
        data={
            "action": "save_vehicle",
            "original_vehicle_id": "",
            "vehicle_id": "VEH-0002",
            "vehicle_no": "TRL-202",
            "vehicle_type": "Trailer",
            "make_model": "Partnership Trailer",
            "status": "Active",
            "shift_mode": "Double Shift",
            "ownership_mode": "Partnership",
            "partner_party_code": "PTY-PART-02",
            "partner_name": "",
            "company_share_percent": "50",
            "partner_share_percent": "50",
            "notes": "50/50 unit",
        },
        follow_redirects=True,
    )
    assert b"Vehicle saved successfully." in vehicle_partnership.data

    technician = client.post(
        "/fleet-maintenance",
        data={
            "action": "save_staff",
            "original_staff_code": "",
            "staff_code": "TEC-0001",
            "staff_name": "Amjad",
            "phone_number": "0505556667",
            "status": "Active",
            "notes": "Lead technician",
        },
        follow_redirects=True,
    )
    assert b"Technician saved successfully." in technician.data

    advance = client.post(
        "/fleet-maintenance",
        data={
            "action": "save_advance",
            "original_advance_no": "",
            "advance_no": "ADV-0001",
            "staff_code": "TEC-0001",
            "entry_date": "2026-04-01",
            "funding_source": "Owner Fund",
            "amount": "3000",
            "reference": "Owner issue",
            "notes": "April advance",
        },
        follow_redirects=True,
    )
    assert b"Field staff payment saved successfully." in advance.data

    paper_one = client.post(
        "/fleet-maintenance",
        data={
            "action": "save_paper",
            "paper_no": "MTP-0001",
            "paper_date": "2026-04-15",
            "vehicle_id": "VEH-0001",
            "workshop_party_code": "",
            "staff_code": "TEC-0001",
            "advance_no": "ADV-0001",
            "tax_mode": "Without Tax",
            "supplier_bill_no": "BILL-001",
            "work_summary": "Oil seal and labour",
            "funding_source": "Technician Advance",
            "paid_by": "Company",
            "tax_amount": "0",
            "notes": "Settled from Amjad advance",
            "line_description_1": "Oil seal replacement",
            "line_quantity_1": "1",
            "line_rate_1": "500",
            "line_amount_1": "",
            "line_description_2": "",
            "line_quantity_2": "",
            "line_rate_2": "",
            "line_amount_2": "",
            "line_description_3": "",
            "line_quantity_3": "",
            "line_rate_3": "",
            "line_amount_3": "",
            "line_description_4": "",
            "line_quantity_4": "",
            "line_rate_4": "",
            "line_amount_4": "",
            "attachment": (BytesIO(b"paper-one"), "paper-one.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Maintenance paper saved successfully." in paper_one.data

    paper_two = client.post(
        "/fleet-maintenance",
        data={
            "action": "save_paper",
            "paper_no": "MTP-0002",
            "paper_date": "2026-04-20",
            "vehicle_id": "VEH-0002",
            "workshop_party_code": "PTY-WS-01",
            "staff_code": "",
            "advance_no": "",
            "tax_mode": "Tax Invoice",
            "supplier_bill_no": "VAT-2002",
            "work_summary": "Brake and welding paper",
            "funding_source": "Workshop Credit",
            "paid_by": "Partner",
            "tax_amount": "50",
            "notes": "Workshop monthly bill",
            "line_description_1": "Brake overhaul and welding",
            "line_quantity_1": "1",
            "line_rate_1": "1000",
            "line_amount_1": "",
            "line_description_2": "",
            "line_quantity_2": "",
            "line_rate_2": "",
            "line_amount_2": "",
            "line_description_3": "",
            "line_quantity_3": "",
            "line_rate_3": "",
            "line_amount_3": "",
            "line_description_4": "",
            "line_quantity_4": "",
            "line_rate_4": "",
            "line_amount_4": "",
            "attachment": (BytesIO(b"paper-two"), "paper-two.jpg"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Maintenance paper saved successfully." in paper_two.data

    filtered = client.get("/fleet-maintenance?month=2026-04&search=Brake", follow_redirects=True)
    assert filtered.status_code == 200
    assert b"Vehicle Master" in filtered.data
    assert b"Brake and welding paper" in filtered.data
    assert b"Zaraki Auto Shop" in filtered.data

    with app.app_context():
        db = open_db()
        assert db.execute("SELECT COUNT(*) FROM vehicle_master").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM maintenance_staff").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM maintenance_paper_lines WHERE paper_no = ?", ("MTP-0001",)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM maintenance_paper_lines WHERE paper_no = ?", ("MTP-0002",)).fetchone()[0] == 1

        advance_row = db.execute(
            """
            SELECT amount, settled_amount, balance_amount
            FROM maintenance_staff_advances
            WHERE advance_no = ?
            """,
            ("ADV-0001",),
        ).fetchone()
        first_paper = db.execute(
            """
            SELECT total_amount, company_share_amount, partner_share_amount, company_paid_amount, partner_paid_amount, attachment_path
            FROM maintenance_papers
            WHERE paper_no = ?
            """,
            ("MTP-0001",),
        ).fetchone()
        second_paper = db.execute(
            """
            SELECT total_amount, tax_amount, company_share_amount, partner_share_amount, company_paid_amount, partner_paid_amount
            FROM maintenance_papers
            WHERE paper_no = ?
            """,
            ("MTP-0002",),
        ).fetchone()
        technician_settlement = db.execute(
            """
            SELECT settlement_type, amount, status
            FROM maintenance_settlements
            WHERE paper_no = ?
            """,
            ("MTP-0001",),
        ).fetchone()
        workshop_settlement = db.execute(
            """
            SELECT settlement_type, party_code, amount, status
            FROM maintenance_settlements
            WHERE paper_no = ?
            """,
            ("MTP-0002",),
        ).fetchone()

        assert advance_row is not None
        assert float(advance_row["amount"]) == 3000.0
        assert float(advance_row["settled_amount"]) == 500.0
        assert float(advance_row["balance_amount"]) == 2500.0

        assert first_paper is not None
        assert float(first_paper["total_amount"]) == 500.0
        assert float(first_paper["company_share_amount"]) == 500.0
        assert float(first_paper["partner_share_amount"]) == 0.0
        assert float(first_paper["company_paid_amount"]) == 500.0
        assert float(first_paper["partner_paid_amount"]) == 0.0
        assert first_paper["attachment_path"].startswith("maintenance/mtp-0001/")
        assert (Path(app.config["GENERATED_DIR"]) / first_paper["attachment_path"]).exists()

        assert second_paper is not None
        assert float(second_paper["total_amount"]) == 1050.0
        assert float(second_paper["tax_amount"]) == 50.0
        assert float(second_paper["company_share_amount"]) == 525.0
        assert float(second_paper["partner_share_amount"]) == 525.0
        assert float(second_paper["company_paid_amount"]) == 0.0
        assert float(second_paper["partner_paid_amount"]) == 0.0

        assert technician_settlement is not None
        assert technician_settlement["settlement_type"] == "Technician Advance"
        assert float(technician_settlement["amount"]) == 500.0
        assert technician_settlement["status"] == "Settled"

        assert workshop_settlement is not None
        assert workshop_settlement["settlement_type"] == "Workshop Credit"
        assert workshop_settlement["party_code"] == "PTY-WS-01"
        assert float(workshop_settlement["amount"]) == 1050.0
        assert workshop_settlement["status"] == "Open"


def test_supplier_edit_flow_accepts_portal_toggle_without_500(app, client):
    admin_session(client)
    created = create_supplier_record(
        client,
        party_code="PTY-EDIT-PORTAL",
        party_name="Edit Portal Supplier",
        party_kind="Company",
        portal_enabled=False,
    )
    assert b"Supplier registered successfully." in created.data

    updated = client.post(
        "/suppliers/admin/register?mode=Normal",
        data={
            "original_party_code": "PTY-EDIT-PORTAL",
            "party_code": "PTY-EDIT-PORTAL",
            "party_name": "Edit Portal Supplier",
            "party_kind": "Company",
            "party_roles": ["Supplier"],
            "contact_person": "Ops",
            "phone_number": "0500000001",
            "email": "edit.portal@example.com",
            "portal_login_email": "edit.portal@example.com",
            "portal_enabled": "1",
            "trn_no": "TRN-PTY-EDIT-PORTAL",
            "trade_license_no": "LIC-PTY-EDIT-PORTAL",
            "address": "Mussafah",
            "notes": "updated",
            "status": "Active",
            "supplier_mode": "Normal",
        },
        follow_redirects=True,
    )
    assert b"Supplier updated successfully." in updated.data

    with app.app_context():
        db = open_db()
        account = db.execute(
            "SELECT login_email, portal_enabled FROM supplier_portal_accounts WHERE party_code = ?",
            ("PTY-EDIT-PORTAL",),
        ).fetchone()
        assert account is not None
        assert account["login_email"] == "edit.portal@example.com"
        assert int(account["portal_enabled"]) == 1


def test_customer_desk_can_add_and_archive_customer(app, client):
    admin_session(client)
    created = create_customer_record(client, party_code="PTY-CUST-01", party_name="Delta Customer")
    assert b"Customer saved successfully." in created.data

    archive = client.post("/customers/PTY-CUST-01/archive", data={}, follow_redirects=True)
    assert archive.status_code == 200
    assert b"marked as Inactive" in archive.data

    desk = client.get("/customers", follow_redirects=True)
    assert b"Delta Customer" not in desk.data

    with app.app_context():
        db = open_db()
        row = db.execute("SELECT status FROM parties WHERE party_code = ?", ("PTY-CUST-01",)).fetchone()
        assert row["status"] == "Inactive"


def test_supplier_portal_and_partnership_statement_pdfs_download(app, client):
    admin_session(client)
    create_supplier_record(
        client,
        party_code="PTY-COMP-02",
        party_name="PDF Supplier LLC",
        party_kind="Company",
        portal_enabled=True,
        portal_login_email="pdf.portal@example.com",
    )
    client.get("/logout", follow_redirects=False)
    client.post(
        "/supplier-forgot-password",
        data={
            "user_id": "pty-comp-02",
            "email": "pdf.portal@example.com",
            "password": "secret12",
            "confirm_password": "secret12",
        },
        follow_redirects=True,
    )
    client.post("/supplier-login", data={"user_id": "pty-comp-02", "password": "secret12"}, follow_redirects=True)
    portal_pdf = client.get("/portal/supplier/statement-pdf", follow_redirects=False)
    assert portal_pdf.status_code == 302
    assert "/generated/" in portal_pdf.headers["Location"]

    client.get("/logout", follow_redirects=False)
    admin_session(client)
    client.post(
        "/suppliers/partnership",
        data={
            "party_code": "PTY-PDF-PART",
            "party_name": "Partnership PDF Supplier",
            "party_kind": "Company",
            "party_roles": ["Supplier", "Partner"],
            "contact_person": "Ops",
            "phone_number": "0500000003",
            "email": "partnership@example.com",
            "trn_no": "",
            "trade_license_no": "",
            "address": "Mussafah",
            "notes": "partnership",
            "status": "Active",
            "supplier_mode": "Partnership",
            "partner_name": "Partner",
            "default_company_share_percent": "50",
            "default_partner_share_percent": "50",
        },
        follow_redirects=True,
    )
    partnership_pdf = client.get("/suppliers/PTY-PDF-PART/statement-pdf?month=2026-04", follow_redirects=False)
    assert partnership_pdf.status_code == 302
    assert "/generated/" in partnership_pdf.headers["Location"]
