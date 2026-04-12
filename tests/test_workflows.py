from werkzeug.security import generate_password_hash

from app.database import open_db


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
