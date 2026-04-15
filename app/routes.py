import base64
import shutil
from calendar import monthrange
from datetime import date, datetime, timedelta
from functools import wraps
from io import BytesIO
from pathlib import Path

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from flask_wtf.csrf import CSRFError

from .database import open_db
from .excel_import import load_driver_records, upsert_driver_records
from .pdf_driver_import import load_driver_records_from_pdf, load_driver_records_from_pdf_bytes
from .pdf_service import (
    format_month_label,
    generate_kata_pdf,
    generate_owner_fund_pdf,
    generate_salary_slip_pdf,
    generate_supplier_payment_voucher_pdf,
    generate_tax_invoice_pdf,
    generate_timesheet_pdf,
)


TRANSACTION_TYPES = ["Petty Cash", "Advance", "Fine", "Fuel", "Other"]
PAYMENT_SOURCES = ["Owner Fund", "Owner Direct", "Current Link", "Office", "Cash", "Bank", "Other"]
PARTY_KIND_OPTIONS = ["Company", "Individual"]
PARTY_ROLE_OPTIONS = [
    "Supplier",
    "Customer",
    "Borrower",
    "Visa Holder",
    "Vehicle Holder",
    "Partner",
]
VAT_STATUS_OPTIONS = ["Registered", "Not Registered", "Exempt"]
SALARY_MODE_OPTIONS = [("full", "Full Salary (30-Day Basis)"), ("prorata", "Prorata From Duty Start")]
AGREEMENT_KIND_OPTIONS = ["Customer", "Supplier", "Mixed"]
RATE_TYPE_OPTIONS = ["Monthly", "Daily", "Trip", "Hourly", "Fixed"]
HIRE_DIRECTION_OPTIONS = ["Supplier Hire", "Customer Rental"]
UNIT_TYPE_OPTIONS = ["Days", "Trips", "Hours", "Months", "Units"]
INVOICE_KIND_OPTIONS = ["Sales", "Purchase"]
INVOICE_DOCUMENT_OPTIONS = ["Tax Invoice", "Simplified Tax Invoice", "Credit Note", "Debit Note", "Supplier Bill"]
PAYMENT_KIND_OPTIONS = ["Received", "Paid"]
PAYMENT_METHOD_OPTIONS = ["Bank", "Cash", "Owner Fund", "Cheque", "Transfer", "Other"]
LOAN_TYPE_OPTIONS = ["Given", "Recovered"]
FEE_TYPE_OPTIONS = ["Visa", "Vehicle"]
SUPPLIER_RATE_BASIS_OPTIONS = ["Hours", "Days", "Trips", "Monthly", "Fixed"]
SUPPLIER_VOUCHER_STATUS_OPTIONS = ["Open", "Partially Paid", "Paid"]
BRANCH_STATUS_OPTIONS = ["Active", "Inactive"]
FINANCIAL_YEAR_STATUS_OPTIONS = ["Open", "Closed", "Archived"]
INVOICE_LINE_SLOTS = 4
ADMIN_WORKSPACE_ORDER = ["universal", "drivers", "suppliers", "customers", "accounts"]
ADMIN_WORKSPACE_META = {
    "universal": {
        "label": "Universal",
        "eyebrow": "Dashboard",
        "title": "Main Dashboard",
        "summary": "Pick a desk.",
    },
    "drivers": {
        "label": "Drivers",
        "eyebrow": "Driver Desk",
        "title": "Driver Desk",
        "summary": "Driver control.",
    },
    "suppliers": {
        "label": "Suppliers",
        "eyebrow": "Supplier Desk",
        "title": "Supplier Desk",
        "summary": "Fleet and payments.",
    },
    "customers": {
        "label": "Customers",
        "eyebrow": "Customer Desk",
        "title": "Customer Desk",
        "summary": "Invoices and statements.",
    },
    "accounts": {
        "label": "Accounts",
        "eyebrow": "Accounts Desk",
        "title": "Accounts Desk",
        "summary": "Fund, tax, reports.",
    },
}


class ValidationError(ValueError):
    pass


def register_routes(app: Flask) -> None:
    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        flash("Your session form expired or the request was not secure. Please try again.", "error")
        return redirect(request.referrer or url_for(_role_home_endpoint()))

    @app.context_processor
    def inject_auth_context():
        current_role = _current_role()
        current_workspace = _current_admin_workspace() if current_role == "admin" else ""
        workspace_home_endpoint = _workspace_home_endpoint(current_workspace) if current_role == "admin" else ""
        return {
            "current_role": current_role,
            "current_driver_id": session.get("driver_id"),
            "current_user_name": session.get("display_name", ""),
            "is_admin": current_role == "admin",
            "is_driver": current_role == "driver",
            "is_owner": current_role == "owner",
            "current_admin_workspace": current_workspace,
            "current_workspace_meta": _current_workspace_meta(),
            "admin_workspace_links": _admin_workspace_links() if current_role == "admin" else [],
            "admin_module_links": _admin_module_links(current_workspace) if current_role == "admin" else [],
            "admin_workspace_home_endpoint": workspace_home_endpoint,
            "admin_workspace_home_url": url_for(workspace_home_endpoint) if workspace_home_endpoint else "",
            "admin_workspace_home_label": f"{ADMIN_WORKSPACE_META[current_workspace]['title']}" if current_role == "admin" and current_workspace in ADMIN_WORKSPACE_META and current_workspace != "universal" else "",
        }

    @app.route("/")
    def home():
        if _current_role():
            return redirect(url_for(_role_home_endpoint()))
        return render_template("landing.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if _current_role():
            return redirect(url_for(_role_home_endpoint()))

        selected_role = "admin"
        if request.method == "POST":
            role = request.form.get("role", "").strip().lower()
            password = request.form.get("password", "").strip()
            phone_number = request.form.get("phone_number", "").strip()
            driver_pin = request.form.get("driver_pin", "").strip()
            selected_role = role or "admin"
            db = open_db()
            identifier = _auth_identifier(role, phone_number)

            if role in {"admin", "owner", "driver"}:
                lock_info = _get_login_lock(db, role, identifier)
                if lock_info["locked"]:
                    flash(lock_info["message"], "error")
                    _audit_log(
                        db,
                        "login_blocked",
                        entity_type="auth",
                        entity_id=role,
                        status="blocked",
                        details=lock_info["message"],
                    )
                    db.commit()
                    return render_template("login.html", selected_role=selected_role)

            if role == "admin":
                if not password:
                    flash("Admin password is required.", "error")
                elif _verify_env_secret(app.config["ADMIN_PASSWORD"], app.config.get("ADMIN_PASSWORD_HASH", ""), password):
                    _clear_failed_login(db, "admin", identifier)
                    _audit_log(db, "login_success", entity_type="auth", entity_id="admin", details="Admin login")
                    db.commit()
                    _set_session("admin", display_name="Admin")
                    flash("Admin login successful.", "success")
                    return redirect(url_for("dashboard"))
                else:
                    _record_failed_login(db, "admin", identifier)
                    _audit_log(db, "login_failed", entity_type="auth", entity_id="admin", status="failed", details="Admin password mismatch")
                    db.commit()
                    flash(_latest_login_error(db, "admin", identifier, "Admin password is not correct."), "error")
            elif role == "owner":
                if not password:
                    flash("Owner access code is required.", "error")
                elif _verify_env_secret(app.config["OWNER_PASSWORD"], app.config.get("OWNER_PASSWORD_HASH", ""), password):
                    _clear_failed_login(db, "owner", identifier)
                    _audit_log(db, "login_success", entity_type="auth", entity_id="owner", details="Owner login")
                    db.commit()
                    _set_session("owner", display_name="Owner")
                    flash("Owner login successful.", "success")
                    return redirect(url_for("owner_fund"))
                else:
                    _record_failed_login(db, "owner", identifier)
                    _audit_log(db, "login_failed", entity_type="auth", entity_id="owner", status="failed", details="Owner password mismatch")
                    db.commit()
                    flash(_latest_login_error(db, "owner", identifier, "Owner access code is not correct."), "error")
            elif role == "driver":
                normalized_phone = _normalize_phone(phone_number)
                driver = _find_driver_by_phone(db, normalized_phone)
                if driver is None:
                    if normalized_phone:
                        _record_failed_login(db, "driver", identifier)
                        _audit_log(db, "login_failed", entity_type="auth", entity_id="driver", status="failed", details="Unknown driver phone")
                        db.commit()
                    flash("Driver phone number was not found. Add phone number in driver master first.", "error")
                elif not driver["pin_hash"]:
                    flash("Driver PIN is not set yet. Ask admin to update the driver profile.", "error")
                elif not driver_pin:
                    flash("Driver PIN is required.", "error")
                elif not check_password_hash(driver["pin_hash"], driver_pin):
                    _record_failed_login(db, "driver", identifier)
                    _audit_log(db, "login_failed", entity_type="auth", entity_id=driver["driver_id"], status="failed", details="Driver PIN mismatch")
                    db.commit()
                    flash(_latest_login_error(db, "driver", identifier, "Driver PIN is not correct."), "error")
                else:
                    _clear_failed_login(db, "driver", identifier)
                    _audit_log(db, "login_success", entity_type="auth", entity_id=driver["driver_id"], details="Driver login")
                    db.commit()
                    _set_session("driver", driver_id=driver["driver_id"], display_name=driver["full_name"])
                    flash(f"Welcome {driver['full_name']}.", "success")
                    return redirect(url_for("driver_portal"))
            else:
                flash("Select a valid login type.", "error")

        return render_template("login.html", selected_role=selected_role)

    @app.get("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "success")
        return redirect(url_for("login"))

    @app.get("/services")
    def services():
        return render_template("services.html")

    @app.get("/workspace/<workspace_key>")
    @_login_required("admin")
    def switch_workspace(workspace_key: str):
        selected_workspace = _set_admin_workspace(workspace_key)
        return redirect(url_for(_workspace_home_endpoint(selected_workspace)))

    @app.route("/dashboard")
    @_login_required("admin")
    def dashboard():
        _touch_admin_workspace("universal")
        db = open_db()
        query = request.args.get("q", "").strip()
        status_filter = request.args.get("status", "").strip()
        shift_filter = request.args.get("shift", "").strip()
        vehicle_filter = request.args.get("vehicle_type", "").strip()
        where_sql, params = _driver_filter_clause(query, status_filter, shift_filter, vehicle_filter)
        current_month = _current_month_value()

        drivers = db.execute(
            f"""
            SELECT
                driver_id,
                full_name,
                phone_number,
                vehicle_no,
                shift,
                vehicle_type,
                basic_salary,
                ot_rate,
                duty_start,
                photo_name,
                status,
                (
                    SELECT salary_month
                    FROM salary_store
                    WHERE salary_store.driver_id = drivers.driver_id
                    ORDER BY salary_month DESC
                    LIMIT 1
                ) AS latest_salary_month
            FROM drivers
            {where_sql}
            ORDER BY CASE WHEN status = 'Active' THEN 0 ELSE 1 END, full_name ASC
            """,
            params,
        ).fetchall()

        total_payroll = sum(driver["basic_salary"] for driver in drivers)
        active_drivers = sum(1 for driver in drivers if (driver["status"] or "").lower() == "active")
        stored_this_month = db.execute(
            "SELECT COUNT(*) FROM salary_store WHERE salary_month = ?",
            (current_month,),
        ).fetchone()[0]
        owner_fund_incoming, owner_fund_outgoing, owner_fund_balance = _owner_fund_totals(db)
        supplier_summary = _supplier_summary(db)
        supplier_hub_summary = _supplier_hub_summary(db)
        top_suppliers = _supplier_directory_rows(db, limit=6)
        customer_summary = _customer_summary(db)
        invoice_summary = _invoice_center_summary(db)
        loan_summary = _loan_summary(db)
        annual_fee_summary = _annual_fee_summary(db)
        import_history = db.execute(
            """
            SELECT source_type, file_name, imported_count, notes, created_at
            FROM import_history
            ORDER BY created_at DESC, id DESC
            LIMIT 8
            """
        ).fetchall()
        filter_options = _driver_filter_options(db)
        shift_chart = _chart_rows(
            db.execute(
                """
                SELECT shift AS label, COUNT(*) AS value
                FROM drivers
                GROUP BY shift
                ORDER BY COUNT(*) DESC, shift ASC
                """
            ).fetchall()
        )
        vehicle_chart = _chart_rows(
            db.execute(
                """
                SELECT vehicle_type AS label, COUNT(*) AS value
                FROM drivers
                GROUP BY vehicle_type
                ORDER BY COUNT(*) DESC, vehicle_type ASC
                LIMIT 6
                """
            ).fetchall()
        )
        import_chart = _chart_rows(
            db.execute(
                """
                SELECT source_type AS label, COUNT(*) AS value
                FROM import_history
                GROUP BY source_type
                ORDER BY COUNT(*) DESC, source_type ASC
                """
            ).fetchall()
        )

        return render_template(
            "dashboard.html",
            drivers=drivers,
            total_drivers=len(drivers),
            active_drivers=active_drivers,
            total_payroll=total_payroll,
            stored_this_month=stored_this_month,
            current_month_label=format_month_label(current_month),
            query=query,
            status_filter=status_filter,
            shift_filter=shift_filter,
            vehicle_filter=vehicle_filter,
            owner_fund_incoming=owner_fund_incoming,
            owner_fund_outgoing=owner_fund_outgoing,
            owner_fund_balance=owner_fund_balance,
            supplier_summary=supplier_summary,
            supplier_hub_summary=supplier_hub_summary,
            top_suppliers=top_suppliers,
            customer_summary=customer_summary,
            invoice_summary=invoice_summary,
            loan_summary=loan_summary,
            annual_fee_summary=annual_fee_summary,
            import_history=import_history,
            shifts=filter_options["shifts"],
            vehicle_types=filter_options["vehicle_types"],
            shift_chart=shift_chart,
            vehicle_chart=vehicle_chart,
            import_chart=import_chart,
        )

    @app.route("/company-setup", methods=["GET", "POST"])
    @_login_required("admin")
    def company_setup():
        _touch_admin_workspace("accounts")
        db = open_db()
        profile_values = _company_profile_values(db)
        branch_values = _default_branch_form(db)
        currency_values = _default_currency_form(db)
        year_values = _default_financial_year_form(db)

        edit_branch_code = request.args.get("edit_branch", "").strip().upper()
        edit_currency_code = request.args.get("edit_currency", "").strip().upper()
        edit_year_code = request.args.get("edit_year", "").strip().upper()

        if edit_branch_code:
            row = db.execute("SELECT * FROM branches WHERE branch_code = ?", (edit_branch_code,)).fetchone()
            if row is not None:
                branch_values = _branch_form_from_row(row)
        if edit_currency_code:
            row = db.execute("SELECT * FROM company_currencies WHERE currency_code = ?", (edit_currency_code,)).fetchone()
            if row is not None:
                currency_values = _currency_form_from_row(row)
        if edit_year_code:
            row = db.execute("SELECT * FROM financial_years WHERE year_code = ?", (edit_year_code,)).fetchone()
            if row is not None:
                year_values = _financial_year_form_from_row(row)

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            try:
                if action == "save_company_profile":
                    profile_values = _company_profile_form_data(request)
                    payload = _prepare_company_profile_payload(profile_values)
                    existing = db.execute("SELECT id FROM company_profile ORDER BY id ASC LIMIT 1").fetchone()
                    if existing is None:
                        db.execute(
                            """
                            INSERT INTO company_profile (
                                company_name, legal_name, trade_license_no, trade_license_expiry, trn_no,
                                vat_status, address, phone_number, email, bank_name, bank_account_name,
                                bank_account_number, iban, swift_code, invoice_terms, base_currency,
                                financial_year_label, financial_year_start, financial_year_end
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        _audit_log(db, "company_profile_created", entity_type="company_profile", entity_id="MAIN", details=profile_values["company_name"])
                        message = "Company setup saved successfully."
                    else:
                        db.execute(
                            """
                            UPDATE company_profile
                            SET company_name = ?, legal_name = ?, trade_license_no = ?, trade_license_expiry = ?,
                                trn_no = ?, vat_status = ?, address = ?, phone_number = ?, email = ?,
                                bank_name = ?, bank_account_name = ?, bank_account_number = ?, iban = ?,
                                swift_code = ?, invoice_terms = ?, base_currency = ?, financial_year_label = ?,
                                financial_year_start = ?, financial_year_end = ?
                            WHERE id = ?
                            """,
                            payload + (existing["id"],),
                        )
                        _audit_log(db, "company_profile_updated", entity_type="company_profile", entity_id="MAIN", details=profile_values["company_name"])
                        message = "Company setup updated successfully."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("company_setup"))

                if action == "save_branch":
                    branch_values = _branch_form_data(request)
                    payload = _prepare_branch_payload(db, branch_values)
                    _ensure_reference_available(db, "branches", "branch_code", branch_values["branch_code"], branch_values["original_branch_code"], "Branch code")
                    if branch_values["original_branch_code"]:
                        db.execute(
                            """
                            UPDATE branches
                            SET branch_code = ?, branch_name = ?, address = ?, contact_person = ?,
                                phone_number = ?, email = ?, status = ?
                            WHERE branch_code = ?
                            """,
                            payload + (branch_values["original_branch_code"],),
                        )
                        _audit_log(db, "branch_updated", entity_type="branch", entity_id=branch_values["branch_code"], details=branch_values["branch_name"])
                        message = "Branch updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO branches (
                                branch_code, branch_name, address, contact_person, phone_number, email, status
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        _audit_log(db, "branch_created", entity_type="branch", entity_id=branch_values["branch_code"], details=branch_values["branch_name"])
                        message = "Branch saved successfully."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("company_setup"))

                if action == "save_currency":
                    currency_values = _currency_form_data(request)
                    payload = _prepare_currency_payload(db, currency_values)
                    _ensure_reference_available(db, "company_currencies", "currency_code", currency_values["currency_code"], currency_values["original_currency_code"], "Currency code")
                    if payload[4]:
                        db.execute("UPDATE company_currencies SET is_base = 0")
                    if currency_values["original_currency_code"]:
                        db.execute(
                            """
                            UPDATE company_currencies
                            SET currency_code = ?, currency_name = ?, symbol = ?, exchange_rate = ?, is_base = ?, status = ?
                            WHERE currency_code = ?
                            """,
                            payload + (currency_values["original_currency_code"],),
                        )
                        _audit_log(db, "currency_updated", entity_type="currency", entity_id=currency_values["currency_code"], details=currency_values["currency_name"])
                        message = "Currency updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO company_currencies (
                                currency_code, currency_name, symbol, exchange_rate, is_base, status
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        _audit_log(db, "currency_created", entity_type="currency", entity_id=currency_values["currency_code"], details=currency_values["currency_name"])
                        message = "Currency saved successfully."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("company_setup"))

                if action == "save_financial_year":
                    year_values = _financial_year_form_data(request)
                    payload = _prepare_financial_year_payload(db, year_values)
                    _ensure_reference_available(db, "financial_years", "year_code", year_values["year_code"], year_values["original_year_code"], "Financial year code")
                    if payload[4]:
                        db.execute("UPDATE financial_years SET is_current = 0")
                    if year_values["original_year_code"]:
                        db.execute(
                            """
                            UPDATE financial_years
                            SET year_code = ?, year_label = ?, start_date = ?, end_date = ?, is_current = ?, status = ?
                            WHERE year_code = ?
                            """,
                            payload + (year_values["original_year_code"],),
                        )
                        _audit_log(db, "financial_year_updated", entity_type="financial_year", entity_id=year_values["year_code"], details=year_values["year_label"])
                        message = "Financial year updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO financial_years (
                                year_code, year_label, start_date, end_date, is_current, status
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        _audit_log(db, "financial_year_created", entity_type="financial_year", entity_id=year_values["year_code"], details=year_values["year_label"])
                        message = "Financial year saved successfully."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("company_setup"))
            except ValidationError as exc:
                flash(str(exc), "error")

        return render_template(
            "company_setup.html",
            profile_values=profile_values,
            branch_values=branch_values,
            currency_values=currency_values,
            year_values=year_values,
            branches=_branch_rows(db),
            currencies=_currency_rows(db),
            financial_years=_financial_year_rows(db),
            summary=_company_setup_summary(db),
            vat_status_options=VAT_STATUS_OPTIONS,
            branch_status_options=BRANCH_STATUS_OPTIONS,
            financial_year_status_options=FINANCIAL_YEAR_STATUS_OPTIONS,
        )

    @app.route("/parties/list")
    @_login_required("admin")
    def party_list():
        db = open_db()
        query = request.args.get("q", "").strip()
        status_filter = request.args.get("status", "").strip()
        role_filter = request.args.get("role", "").strip()
        kind_filter = request.args.get("kind", "").strip()
        where_sql, params = _party_filter_clause(query, status_filter, role_filter, kind_filter)

        parties = db.execute(
            f"""
            SELECT
                party_code,
                party_name,
                party_kind,
                party_roles,
                contact_person,
                phone_number,
                email,
                trn_no,
                trade_license_no,
                status,
                created_at
            FROM parties
            {where_sql}
            ORDER BY CASE WHEN status = 'Active' THEN 0 ELSE 1 END, party_name ASC
            """,
            params,
        ).fetchall()

        return render_template(
            "party_list.html",
            parties=parties,
            query=query,
            status_filter=status_filter,
            role_filter=role_filter,
            kind_filter=kind_filter,
            role_options=PARTY_ROLE_OPTIONS,
            kind_options=PARTY_KIND_OPTIONS,
            party_count=len(parties),
            active_count=sum(1 for party in parties if (party["status"] or "").lower() == "active"),
            inactive_count=sum(1 for party in parties if (party["status"] or "").lower() != "active"),
        )

    @app.route("/parties/new", methods=["GET", "POST"])
    @_login_required("admin")
    def create_party():
        values = _default_party_form()

        if request.method == "POST":
            values = _party_form_data(request)
            db = open_db()

            try:
                values["party_roles"] = _normalize_party_roles(values["party_roles"])
                values["phone_number"] = _normalize_optional_phone(values["phone_number"])
                _validate_optional_email(values["email"])
                values["party_code"] = values["party_code"] or _next_party_code(db)
            except ValidationError as exc:
                flash(str(exc), "error")
                return render_template(
                    "party_form.html",
                    values=values,
                    page_title="Add Party",
                    submit_label="Save Party",
                    edit_mode=False,
                    role_options=PARTY_ROLE_OPTIONS,
                    kind_options=PARTY_KIND_OPTIONS,
                )

            try:
                db.execute(
                    """
                    INSERT INTO parties (
                        party_code, party_name, party_kind, party_roles, contact_person,
                        phone_number, email, trn_no, trade_license_no, address, notes, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        values["party_code"],
                        values["party_name"],
                        values["party_kind"],
                        _serialize_party_roles(values["party_roles"]),
                        values["contact_person"],
                        values["phone_number"],
                        values["email"],
                        values["trn_no"],
                        values["trade_license_no"],
                        values["address"],
                        values["notes"],
                        values["status"],
                    ),
                )
                _audit_log(
                    db,
                    "party_created",
                    entity_type="party",
                    entity_id=values["party_code"],
                    details=f"{values['party_name']} / {_serialize_party_roles(values['party_roles'])}",
                )
                db.commit()
            except Exception:
                flash("Party code must be unique.", "error")
                return render_template(
                    "party_form.html",
                    values=values,
                    page_title="Add Party",
                    submit_label="Save Party",
                    edit_mode=False,
                    role_options=PARTY_ROLE_OPTIONS,
                    kind_options=PARTY_KIND_OPTIONS,
                )

            flash("Party saved successfully.", "success")
            return redirect(url_for("party_list"))

        values["party_code"] = values["party_code"] or _preview_next_party_code()
        return render_template(
            "party_form.html",
            values=values,
            page_title="Add Party",
            submit_label="Save Party",
            edit_mode=False,
            role_options=PARTY_ROLE_OPTIONS,
            kind_options=PARTY_KIND_OPTIONS,
        )

    @app.route("/parties/<party_code>/edit", methods=["GET", "POST"])
    @_login_required("admin")
    def edit_party(party_code: str):
        db = open_db()
        party = _fetch_party(db, party_code)
        if party is None:
            flash("Party not found.", "error")
            return redirect(url_for("party_list"))

        if request.method == "POST":
            values = _party_form_data(request)
            values["party_code"] = party_code
            try:
                values["party_roles"] = _normalize_party_roles(values["party_roles"])
                values["phone_number"] = _normalize_optional_phone(values["phone_number"])
                _validate_optional_email(values["email"])
            except ValidationError as exc:
                flash(str(exc), "error")
                return render_template(
                    "party_form.html",
                    values=values,
                    page_title="Edit Party",
                    submit_label="Update Party",
                    edit_mode=True,
                    role_options=PARTY_ROLE_OPTIONS,
                    kind_options=PARTY_KIND_OPTIONS,
                )

            db.execute(
                """
                UPDATE parties
                SET party_name = ?, party_kind = ?, party_roles = ?, contact_person = ?,
                    phone_number = ?, email = ?, trn_no = ?, trade_license_no = ?,
                    address = ?, notes = ?, status = ?
                WHERE party_code = ?
                """,
                (
                    values["party_name"],
                    values["party_kind"],
                    _serialize_party_roles(values["party_roles"]),
                    values["contact_person"],
                    values["phone_number"],
                    values["email"],
                    values["trn_no"],
                    values["trade_license_no"],
                    values["address"],
                    values["notes"],
                    values["status"],
                    party_code,
                ),
            )
            _audit_log(
                db,
                "party_updated",
                entity_type="party",
                entity_id=party_code,
                details=f"{values['party_name']} / {_serialize_party_roles(values['party_roles'])}",
            )
            db.commit()
            flash("Party updated successfully.", "success")
            return redirect(url_for("party_list"))

        return render_template(
            "party_form.html",
            values=_party_values_from_record(party),
            page_title="Edit Party",
            submit_label="Update Party",
            edit_mode=True,
            role_options=PARTY_ROLE_OPTIONS,
            kind_options=PARTY_KIND_OPTIONS,
        )

    @app.post("/parties/<party_code>/status")
    @_login_required("admin")
    def update_party_status(party_code: str):
        db = open_db()
        party = _fetch_party(db, party_code)
        if party is None:
            flash("Party not found.", "error")
            return redirect(url_for("party_list"))
        next_status = request.form.get("status", "Active").strip() or "Active"
        db.execute("UPDATE parties SET status = ? WHERE party_code = ?", (next_status, party_code))
        _audit_log(
            db,
            "party_status_updated",
            entity_type="party",
            entity_id=party_code,
            details=f"{party['party_name']} / {next_status}",
        )
        db.commit()
        flash(f"{party['party_name']} marked as {next_status}.", "success")
        return redirect(url_for("party_list"))

    @app.route("/suppliers", methods=["GET", "POST"])
    @_login_required("admin")
    def suppliers():
        _touch_admin_workspace("suppliers")
        db = open_db()
        values = _default_supplier_form()
        query = request.args.get("q", "").strip()
        edit_party_code = request.args.get("edit", "").strip().upper()
        if edit_party_code:
            existing_party = _fetch_party(db, edit_party_code)
            if existing_party is not None and "Supplier" in _deserialize_party_roles(existing_party["party_roles"] or ""):
                values = _supplier_form_from_party(existing_party)

        if request.method == "POST":
            values = _supplier_form_data(request)
            try:
                payload = _prepare_supplier_party_payload(db, values)
                if values["original_party_code"]:
                    db.execute(
                        """
                        UPDATE parties
                        SET party_name = ?, party_kind = ?, party_roles = ?, contact_person = ?,
                            phone_number = ?, email = ?, trn_no = ?, trade_license_no = ?,
                            address = ?, notes = ?, status = ?
                        WHERE party_code = ?
                        """,
                        payload[1:] + (values["original_party_code"],),
                    )
                    _audit_log(
                        db,
                        "supplier_updated",
                        entity_type="supplier",
                        entity_id=payload[0],
                        details=f"{payload[1]} / {_serialize_party_roles(_deserialize_party_roles(payload[3]))}",
                    )
                    message = "Supplier updated successfully."
                else:
                    db.execute(
                        """
                        INSERT INTO parties (
                            party_code, party_name, party_kind, party_roles, contact_person,
                            phone_number, email, trn_no, trade_license_no, address, notes, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        payload,
                    )
                    _audit_log(
                        db,
                        "supplier_created",
                        entity_type="supplier",
                        entity_id=payload[0],
                        details=f"{payload[1]} / {_serialize_party_roles(_deserialize_party_roles(payload[3]))}",
                    )
                    message = "Supplier registered successfully."
                db.commit()
                flash(message, "success")
                return redirect(url_for("suppliers"))
            except ValidationError as exc:
                flash(str(exc), "error")

        return render_template(
            "suppliers.html",
            values=values,
            query=query,
            summary=_supplier_hub_summary(db),
            suppliers=_supplier_directory_rows(db, query=query),
            rate_basis_options=SUPPLIER_RATE_BASIS_OPTIONS,
            role_options=[item for item in PARTY_ROLE_OPTIONS if item != "Supplier"],
        )

    @app.route("/suppliers/<party_code>", methods=["GET", "POST"])
    @_login_required("admin")
    def supplier_detail(party_code: str):
        _touch_admin_workspace("suppliers")
        db = open_db()
        party = _fetch_supplier_party(db, party_code)
        if party is None:
            flash("Supplier was not found.", "error")
            return redirect(url_for("suppliers"))

        asset_values = _default_supplier_asset_form(db, party_code)
        timesheet_values = _default_supplier_timesheet_form(db, party_code)
        voucher_values = _default_supplier_voucher_form(db, party_code)
        payment_values = _default_supplier_payment_form(db, party_code)

        edit_asset_code = request.args.get("edit_asset", "").strip().upper()
        edit_timesheet_no = request.args.get("edit_timesheet", "").strip().upper()
        edit_voucher_no = request.args.get("edit_voucher", "").strip().upper()
        edit_payment_no = request.args.get("edit_payment", "").strip().upper()

        if edit_asset_code:
            row = db.execute("SELECT * FROM supplier_assets WHERE asset_code = ? AND party_code = ?", (edit_asset_code, party_code)).fetchone()
            if row is not None:
                asset_values = _supplier_asset_form_from_row(row)
        if edit_timesheet_no:
            row = db.execute("SELECT * FROM supplier_timesheets WHERE timesheet_no = ? AND party_code = ?", (edit_timesheet_no, party_code)).fetchone()
            if row is not None:
                timesheet_values = _supplier_timesheet_form_from_row(row)
        if edit_voucher_no:
            row = db.execute("SELECT * FROM supplier_vouchers WHERE voucher_no = ? AND party_code = ?", (edit_voucher_no, party_code)).fetchone()
            if row is not None:
                voucher_values = _supplier_voucher_form_from_row(row)
        if edit_payment_no:
            row = db.execute("SELECT * FROM supplier_payments WHERE payment_no = ? AND party_code = ?", (edit_payment_no, party_code)).fetchone()
            if row is not None:
                payment_values = _supplier_payment_form_from_row(row)

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            try:
                if action == "save_asset":
                    asset_values = _supplier_asset_form_data(request, party_code)
                    payload = _prepare_supplier_asset_payload(db, asset_values)
                    _ensure_reference_available(
                        db,
                        "supplier_assets",
                        "asset_code",
                        asset_values["asset_code"],
                        asset_values["original_asset_code"],
                        "Asset code",
                    )
                    if asset_values["original_asset_code"]:
                        db.execute(
                            """
                            UPDATE supplier_assets
                            SET asset_code = ?, party_code = ?, asset_name = ?, asset_type = ?, vehicle_no = ?,
                                rate_basis = ?, default_rate = ?, capacity = ?, status = ?, notes = ?
                            WHERE asset_code = ?
                            """,
                            payload + (asset_values["original_asset_code"],),
                        )
                        if asset_values["original_asset_code"] != asset_values["asset_code"]:
                            db.execute(
                                "UPDATE supplier_timesheets SET asset_code = ? WHERE asset_code = ?",
                                (asset_values["asset_code"], asset_values["original_asset_code"]),
                            )
                        _audit_log(
                            db,
                            "supplier_asset_updated",
                            entity_type="supplier_asset",
                            entity_id=asset_values["asset_code"],
                            details=f"{party_code} / {asset_values['asset_name']}",
                        )
                        message = "Supplier vehicle updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO supplier_assets (
                                asset_code, party_code, asset_name, asset_type, vehicle_no,
                                rate_basis, default_rate, capacity, status, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        _audit_log(
                            db,
                            "supplier_asset_created",
                            entity_type="supplier_asset",
                            entity_id=asset_values["asset_code"],
                            details=f"{party_code} / {asset_values['asset_name']}",
                        )
                        message = "Supplier vehicle saved successfully."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("supplier_detail", party_code=party_code))

                if action == "save_timesheet":
                    timesheet_values = _supplier_timesheet_form_data(request, party_code)
                    payload = _prepare_supplier_timesheet_payload(db, timesheet_values)
                    _ensure_reference_available(
                        db,
                        "supplier_timesheets",
                        "timesheet_no",
                        timesheet_values["timesheet_no"],
                        timesheet_values["original_timesheet_no"],
                        "Timesheet number",
                    )
                    if timesheet_values["original_timesheet_no"]:
                        existing_row = db.execute(
                            "SELECT voucher_no FROM supplier_timesheets WHERE timesheet_no = ? AND party_code = ?",
                            (timesheet_values["original_timesheet_no"], party_code),
                        ).fetchone()
                        if existing_row and existing_row["voucher_no"]:
                            raise ValidationError("Billed timesheets cannot be edited until their voucher is deleted.")
                        db.execute(
                            """
                            UPDATE supplier_timesheets
                            SET timesheet_no = ?, party_code = ?, asset_code = ?, period_month = ?, entry_date = ?,
                                billing_basis = ?, billable_qty = ?, timesheet_hours = ?, rate = ?, subtotal = ?,
                                status = ?, notes = ?
                            WHERE timesheet_no = ?
                            """,
                            payload + (timesheet_values["original_timesheet_no"],),
                        )
                        _audit_log(
                            db,
                            "supplier_timesheet_updated",
                            entity_type="supplier_timesheet",
                            entity_id=timesheet_values["timesheet_no"],
                            details=f"{party_code} / {timesheet_values['period_month']} / AED {timesheet_values['subtotal']}",
                        )
                        message = "Supplier timesheet updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO supplier_timesheets (
                                timesheet_no, party_code, asset_code, period_month, entry_date,
                                billing_basis, billable_qty, timesheet_hours, rate, subtotal,
                                status, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        _audit_log(
                            db,
                            "supplier_timesheet_created",
                            entity_type="supplier_timesheet",
                            entity_id=timesheet_values["timesheet_no"],
                            details=f"{party_code} / {timesheet_values['period_month']} / AED {timesheet_values['subtotal']}",
                        )
                        message = "Supplier timesheet saved successfully."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("supplier_detail", party_code=party_code))

                if action == "save_voucher":
                    voucher_values = _supplier_voucher_form_data(request, party_code)
                    if voucher_values["original_voucher_no"]:
                        payload = _prepare_existing_supplier_voucher_payload(db, voucher_values)
                        _ensure_reference_available(
                            db,
                            "supplier_vouchers",
                            "voucher_no",
                            voucher_values["voucher_no"],
                            voucher_values["original_voucher_no"],
                            "Voucher number",
                        )
                        db.execute(
                            """
                            UPDATE supplier_vouchers
                            SET voucher_no = ?, party_code = ?, period_month = ?, issue_date = ?, subtotal = ?,
                                tax_percent = ?, tax_amount = ?, total_amount = ?, paid_amount = ?, balance_amount = ?,
                                status = ?, notes = ?
                            WHERE voucher_no = ?
                            """,
                            payload + (voucher_values["original_voucher_no"],),
                        )
                        if voucher_values["voucher_no"] != voucher_values["original_voucher_no"]:
                            db.execute(
                                "UPDATE supplier_timesheets SET voucher_no = ? WHERE voucher_no = ?",
                                (voucher_values["voucher_no"], voucher_values["original_voucher_no"]),
                            )
                            db.execute(
                                "UPDATE supplier_payments SET voucher_no = ? WHERE voucher_no = ?",
                                (voucher_values["voucher_no"], voucher_values["original_voucher_no"]),
                            )
                        _supplier_sync_voucher_balance(db, voucher_values["voucher_no"])
                        _audit_log(
                            db,
                            "supplier_voucher_updated",
                            entity_type="supplier_voucher",
                            entity_id=voucher_values["voucher_no"],
                            details=f"{party_code} / {voucher_values['period_month']}",
                        )
                        message = "Supplier voucher updated successfully."
                    else:
                        payload, linked_timesheets = _prepare_new_supplier_voucher_payload(db, voucher_values)
                        db.execute(
                            """
                            INSERT INTO supplier_vouchers (
                                voucher_no, party_code, period_month, issue_date, subtotal,
                                tax_percent, tax_amount, total_amount, paid_amount, balance_amount, status, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        db.executemany(
                            """
                            UPDATE supplier_timesheets
                            SET voucher_no = ?, status = 'Billed'
                            WHERE timesheet_no = ?
                            """,
                            [(voucher_values["voucher_no"], item["timesheet_no"]) for item in linked_timesheets],
                        )
                        _audit_log(
                            db,
                            "supplier_voucher_created",
                            entity_type="supplier_voucher",
                            entity_id=voucher_values["voucher_no"],
                            details=f"{party_code} / {voucher_values['period_month']} / {len(linked_timesheets)} rows",
                        )
                        message = "Supplier voucher created from open timesheets."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("supplier_detail", party_code=party_code))

                if action == "save_payment":
                    payment_values = _supplier_payment_form_data(request, party_code)
                    payload = _prepare_supplier_payment_payload(db, payment_values)
                    _ensure_reference_available(
                        db,
                        "supplier_payments",
                        "payment_no",
                        payment_values["payment_no"],
                        payment_values["original_payment_no"],
                        "Payment number",
                    )
                    if payment_values["original_payment_no"]:
                        existing_payment = db.execute(
                            "SELECT voucher_no FROM supplier_payments WHERE payment_no = ? AND party_code = ?",
                            (payment_values["original_payment_no"], party_code),
                        ).fetchone()
                        if existing_payment is None:
                            raise ValidationError("Supplier payment was not found.")
                        db.execute(
                            """
                            UPDATE supplier_payments
                            SET payment_no = ?, voucher_no = ?, party_code = ?, entry_date = ?,
                                amount = ?, payment_method = ?, reference = ?, notes = ?
                            WHERE payment_no = ?
                            """,
                            payload + (payment_values["original_payment_no"],),
                        )
                        if existing_payment["voucher_no"] != payment_values["voucher_no"]:
                            _supplier_sync_voucher_balance(db, existing_payment["voucher_no"])
                        _supplier_sync_voucher_balance(db, payment_values["voucher_no"])
                        _audit_log(
                            db,
                            "supplier_payment_updated",
                            entity_type="supplier_payment",
                            entity_id=payment_values["payment_no"],
                            details=f"{payment_values['voucher_no']} / AED {payment_values['amount']}",
                        )
                        message = "Supplier payment updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO supplier_payments (
                                payment_no, voucher_no, party_code, entry_date,
                                amount, payment_method, reference, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        _supplier_sync_voucher_balance(db, payment_values["voucher_no"])
                        _audit_log(
                            db,
                            "supplier_payment_created",
                            entity_type="supplier_payment",
                            entity_id=payment_values["payment_no"],
                            details=f"{payment_values['voucher_no']} / AED {payment_values['amount']}",
                        )
                        message = "Supplier payment saved successfully."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("supplier_detail", party_code=party_code))
            except ValidationError as exc:
                flash(str(exc), "error")

        supplier_assets = _supplier_asset_rows(db, party_code)
        supplier_timesheets = _supplier_timesheet_rows(db, party_code)
        supplier_vouchers = _supplier_voucher_rows(db, party_code)
        supplier_payments = _supplier_payment_rows(db, party_code)
        statement_rows, statement_summary = _supplier_statement_data(db, party_code)

        return render_template(
            "supplier_detail.html",
            party=party,
            asset_values=asset_values,
            timesheet_values=timesheet_values,
            voucher_values=voucher_values,
            payment_values=payment_values,
            summary=_supplier_detail_summary(db, party_code),
            statement_rows=statement_rows,
            statement_summary=statement_summary,
            assets=supplier_assets,
            timesheets=supplier_timesheets,
            vouchers=supplier_vouchers,
            payments=supplier_payments,
            rate_basis_options=SUPPLIER_RATE_BASIS_OPTIONS,
            payment_method_options=PAYMENT_METHOD_OPTIONS,
            voucher_status_options=SUPPLIER_VOUCHER_STATUS_OPTIONS,
        )

    @app.get("/suppliers/<party_code>/statement")
    @_login_required("admin")
    def supplier_statement(party_code: str):
        return redirect(url_for("supplier_detail", party_code=party_code))

    @app.post("/supplier-assets/<asset_code>/delete")
    @_login_required("admin")
    def delete_supplier_asset(asset_code: str):
        db = open_db()
        asset = db.execute("SELECT asset_code, party_code, asset_name FROM supplier_assets WHERE asset_code = ?", (asset_code,)).fetchone()
        if asset is None:
            flash("Supplier vehicle was not found.", "error")
            return redirect(url_for("suppliers"))
        count = int(db.execute("SELECT COUNT(*) FROM supplier_timesheets WHERE asset_code = ?", (asset_code,)).fetchone()[0])
        if count:
            flash(f"Vehicle cannot be deleted because {count} timesheet row(s) are linked.", "error")
            return redirect(url_for("supplier_detail", party_code=asset["party_code"]))
        db.execute("DELETE FROM supplier_assets WHERE asset_code = ?", (asset_code,))
        _audit_log(db, "supplier_asset_deleted", entity_type="supplier_asset", entity_id=asset_code, details=asset["asset_name"])
        db.commit()
        flash("Supplier vehicle deleted successfully.", "success")
        return redirect(url_for("supplier_detail", party_code=asset["party_code"]))

    @app.post("/supplier-timesheets/<timesheet_no>/delete")
    @_login_required("admin")
    def delete_supplier_timesheet(timesheet_no: str):
        db = open_db()
        row = db.execute("SELECT timesheet_no, party_code, voucher_no FROM supplier_timesheets WHERE timesheet_no = ?", (timesheet_no,)).fetchone()
        if row is None:
            flash("Supplier timesheet was not found.", "error")
            return redirect(url_for("suppliers"))
        if row["voucher_no"]:
            flash("Billed timesheets cannot be deleted until their voucher is removed.", "error")
            return redirect(url_for("supplier_detail", party_code=row["party_code"]))
        db.execute("DELETE FROM supplier_timesheets WHERE timesheet_no = ?", (timesheet_no,))
        _audit_log(db, "supplier_timesheet_deleted", entity_type="supplier_timesheet", entity_id=timesheet_no, details=timesheet_no)
        db.commit()
        flash("Supplier timesheet deleted successfully.", "success")
        return redirect(url_for("supplier_detail", party_code=row["party_code"]))

    @app.post("/supplier-vouchers/<voucher_no>/delete")
    @_login_required("admin")
    def delete_supplier_voucher(voucher_no: str):
        db = open_db()
        voucher = db.execute("SELECT voucher_no, party_code FROM supplier_vouchers WHERE voucher_no = ?", (voucher_no,)).fetchone()
        if voucher is None:
            flash("Supplier voucher was not found.", "error")
            return redirect(url_for("suppliers"))
        count = int(db.execute("SELECT COUNT(*) FROM supplier_payments WHERE voucher_no = ?", (voucher_no,)).fetchone()[0])
        if count:
            flash(f"Voucher cannot be deleted because {count} payment row(s) are linked.", "error")
            return redirect(url_for("supplier_detail", party_code=voucher["party_code"]))
        db.execute("UPDATE supplier_timesheets SET voucher_no = NULL, status = 'Open' WHERE voucher_no = ?", (voucher_no,))
        db.execute("DELETE FROM supplier_vouchers WHERE voucher_no = ?", (voucher_no,))
        _audit_log(db, "supplier_voucher_deleted", entity_type="supplier_voucher", entity_id=voucher_no, details=voucher_no)
        db.commit()
        flash("Supplier voucher deleted and linked timesheets reopened.", "success")
        return redirect(url_for("supplier_detail", party_code=voucher["party_code"]))

    @app.post("/supplier-payments/<payment_no>/delete")
    @_login_required("admin")
    def delete_supplier_payment(payment_no: str):
        db = open_db()
        payment = db.execute("SELECT payment_no, voucher_no, party_code FROM supplier_payments WHERE payment_no = ?", (payment_no,)).fetchone()
        if payment is None:
            flash("Supplier payment was not found.", "error")
            return redirect(url_for("suppliers"))
        db.execute("DELETE FROM supplier_payments WHERE payment_no = ?", (payment_no,))
        _supplier_sync_voucher_balance(db, payment["voucher_no"])
        _audit_log(db, "supplier_payment_deleted", entity_type="supplier_payment", entity_id=payment_no, details=payment["voucher_no"])
        db.commit()
        flash("Supplier payment deleted successfully.", "success")
        return redirect(url_for("supplier_detail", party_code=payment["party_code"]))

    @app.get("/supplier-payments/<payment_no>/voucher")
    @_login_required("admin")
    def supplier_payment_voucher(payment_no: str):
        db = open_db()
        payment = _supplier_payment_with_context(db, payment_no)
        if payment is None:
            flash("Supplier payment voucher was not found.", "error")
            return redirect(url_for("suppliers"))
        output_dir = _supplier_output_dir(app, payment["party_code"]) / "payment_vouchers"
        pdf_path = generate_supplier_payment_voucher_pdf(
            payment,
            payment,
            payment,
            str(output_dir),
            app.config["STATIC_ASSETS_DIR"],
        )
        relative_path = Path(pdf_path).relative_to(app.config["GENERATED_DIR"]).as_posix()
        return redirect(url_for("generated_file", filename=relative_path))

    @app.get("/customers")
    @_login_required("admin")
    def customers():
        _touch_admin_workspace("customers")
        db = open_db()
        customer_parties = _parties_by_role(db, "Customer")
        summary = _customer_summary(db)
        top_receivables = _party_balance_rows(db, invoice_kind="Sales", limit=8)
        recent_hires = _hire_rows(db, direction="Customer Rental", limit=8)
        recent_invoices = _invoice_rows(db, invoice_kind="Sales", limit=8)
        return render_template(
            "customers.html",
            customer_parties=customer_parties,
            summary=summary,
            top_receivables=top_receivables,
            recent_hires=recent_hires,
            recent_invoices=recent_invoices,
        )

    @app.get("/customers/<party_code>/statement")
    @_login_required("admin")
    def customer_statement(party_code: str):
        _touch_admin_workspace("customers")
        db = open_db()
        party = _fetch_party(db, party_code)
        if party is None:
            flash("Customer was not found.", "error")
            return redirect(url_for("customers"))
        rows, summary = _party_statement(db, party_code, invoice_kind="Sales", hire_direction="Customer Rental")
        return render_template(
            "party_statement.html",
            page_title="Customer Statement",
            page_eyebrow="Receivables Ledger",
            party=party,
            rows=rows,
            summary=summary,
            back_endpoint="customers",
        )

    @app.route("/agreements-lpos", methods=["GET", "POST"])
    @_login_required("admin")
    def agreements_lpos():
        _touch_admin_workspace("customers")
        db = open_db()
        agreement_values = _default_agreement_form()
        lpo_values = _default_lpo_form()
        hire_values = _default_hire_form()

        edit_agreement_no = request.args.get("edit_agreement", "").strip().upper()
        edit_lpo_no = request.args.get("edit_lpo", "").strip().upper()
        edit_hire_no = request.args.get("edit_hire", "").strip().upper()

        if edit_agreement_no:
            agreement_row = db.execute("SELECT * FROM agreements WHERE agreement_no = ?", (edit_agreement_no,)).fetchone()
            if agreement_row is not None:
                agreement_values = _agreement_form_from_row(agreement_row)
        if edit_lpo_no:
            lpo_row = db.execute("SELECT * FROM lpos WHERE lpo_no = ?", (edit_lpo_no,)).fetchone()
            if lpo_row is not None:
                lpo_values = _lpo_form_from_row(lpo_row)
        if edit_hire_no:
            hire_row = db.execute("SELECT * FROM hire_records WHERE hire_no = ?", (edit_hire_no,)).fetchone()
            if hire_row is not None:
                hire_values = _hire_form_from_row(hire_row)

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            try:
                if action == "save_agreement":
                    agreement_values = _agreement_form_data(request)
                    payload = _prepare_agreement_payload(db, agreement_values)
                    _ensure_reference_available(
                        db,
                        "agreements",
                        "agreement_no",
                        agreement_values["agreement_no"],
                        agreement_values["original_agreement_no"],
                        "Agreement number",
                    )
                    if agreement_values["original_agreement_no"]:
                        db.execute(
                            """
                            UPDATE agreements
                            SET agreement_no = ?, party_code = ?, agreement_kind = ?, start_date = ?, end_date = ?,
                                rate_type = ?, amount = ?, tax_percent = ?, scope = ?, notes = ?, status = ?
                            WHERE agreement_no = ?
                            """,
                            payload + (agreement_values["original_agreement_no"],),
                        )
                        if agreement_values["agreement_no"] != agreement_values["original_agreement_no"]:
                            db.execute("UPDATE lpos SET agreement_no = ? WHERE agreement_no = ?", (agreement_values["agreement_no"], agreement_values["original_agreement_no"]))
                            db.execute("UPDATE hire_records SET agreement_no = ? WHERE agreement_no = ?", (agreement_values["agreement_no"], agreement_values["original_agreement_no"]))
                            db.execute("UPDATE account_invoices SET agreement_no = ? WHERE agreement_no = ?", (agreement_values["agreement_no"], agreement_values["original_agreement_no"]))
                        _audit_log(
                            db,
                            "agreement_updated",
                            entity_type="agreement",
                            entity_id=agreement_values["agreement_no"],
                            details=f"{agreement_values['party_code']} / AED {agreement_values['amount']}",
                        )
                        message = "Agreement updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO agreements (
                                agreement_no, party_code, agreement_kind, start_date, end_date,
                                rate_type, amount, tax_percent, scope, notes, status
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        _audit_log(
                            db,
                            "agreement_created",
                            entity_type="agreement",
                            entity_id=agreement_values["agreement_no"],
                            details=f"{agreement_values['party_code']} / AED {agreement_values['amount']}",
                        )
                        message = "Agreement saved successfully."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("agreements_lpos"))

                if action == "save_lpo":
                    lpo_values = _lpo_form_data(request)
                    payload = _prepare_lpo_payload(db, lpo_values)
                    _ensure_reference_available(db, "lpos", "lpo_no", lpo_values["lpo_no"], lpo_values["original_lpo_no"], "LPO number")
                    if lpo_values["original_lpo_no"]:
                        db.execute(
                            """
                            UPDATE lpos
                            SET lpo_no = ?, party_code = ?, agreement_no = ?, issue_date = ?, valid_until = ?,
                                amount = ?, tax_percent = ?, description = ?, status = ?
                            WHERE lpo_no = ?
                            """,
                            payload + (lpo_values["original_lpo_no"],),
                        )
                        if lpo_values["lpo_no"] != lpo_values["original_lpo_no"]:
                            db.execute("UPDATE hire_records SET lpo_no = ? WHERE lpo_no = ?", (lpo_values["lpo_no"], lpo_values["original_lpo_no"]))
                            db.execute("UPDATE account_invoices SET lpo_no = ? WHERE lpo_no = ?", (lpo_values["lpo_no"], lpo_values["original_lpo_no"]))
                        _audit_log(
                            db,
                            "lpo_updated",
                            entity_type="lpo",
                            entity_id=lpo_values["lpo_no"],
                            details=f"{lpo_values['party_code']} / AED {lpo_values['amount']}",
                        )
                        message = "LPO updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO lpos (
                                lpo_no, party_code, agreement_no, issue_date, valid_until,
                                amount, tax_percent, description, status
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        _audit_log(
                            db,
                            "lpo_created",
                            entity_type="lpo",
                            entity_id=lpo_values["lpo_no"],
                            details=f"{lpo_values['party_code']} / AED {lpo_values['amount']}",
                        )
                        message = "LPO saved successfully."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("agreements_lpos"))

                if action == "save_hire":
                    hire_values = _hire_form_data(request)
                    payload = _prepare_hire_payload(db, hire_values)
                    _ensure_reference_available(db, "hire_records", "hire_no", hire_values["hire_no"], hire_values["original_hire_no"], "Hire number")
                    if hire_values["original_hire_no"]:
                        db.execute(
                            """
                            UPDATE hire_records
                            SET hire_no = ?, party_code = ?, agreement_no = ?, lpo_no = ?, entry_date = ?, direction = ?,
                                asset_name = ?, asset_type = ?, unit_type = ?, quantity = ?, rate = ?, subtotal = ?,
                                tax_percent = ?, tax_amount = ?, total_amount = ?, status = ?, notes = ?
                            WHERE hire_no = ?
                            """,
                            payload + (hire_values["original_hire_no"],),
                        )
                        if hire_values["hire_no"] != hire_values["original_hire_no"]:
                            db.execute("UPDATE account_invoices SET hire_no = ? WHERE hire_no = ?", (hire_values["hire_no"], hire_values["original_hire_no"]))
                        _audit_log(
                            db,
                            "hire_record_updated",
                            entity_type="hire_record",
                            entity_id=hire_values["hire_no"],
                            details=f"{hire_values['direction']} / {hire_values['party_code']} / AED {hire_values['total_amount']}",
                        )
                        message = "Hire register row updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO hire_records (
                                hire_no, party_code, agreement_no, lpo_no, entry_date, direction,
                                asset_name, asset_type, unit_type, quantity, rate, subtotal,
                                tax_percent, tax_amount, total_amount, status, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        _audit_log(
                            db,
                            "hire_record_created",
                            entity_type="hire_record",
                            entity_id=hire_values["hire_no"],
                            details=f"{hire_values['direction']} / {hire_values['party_code']} / AED {hire_values['total_amount']}",
                        )
                        message = "Hire register row saved successfully."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("agreements_lpos"))
            except ValidationError as exc:
                flash(str(exc), "error")

        return render_template(
            "agreements_lpos.html",
            agreement_values=agreement_values,
            lpo_values=lpo_values,
            hire_values=hire_values,
            agreement_kind_options=AGREEMENT_KIND_OPTIONS,
            rate_type_options=RATE_TYPE_OPTIONS,
            hire_direction_options=HIRE_DIRECTION_OPTIONS,
            unit_type_options=UNIT_TYPE_OPTIONS,
            parties=_contract_parties(db),
            agreements=_agreement_rows(db),
            lpos=_lpo_rows(db),
            hires=_hire_rows(db, limit=12),
        )

    @app.post("/agreements/<agreement_no>/delete")
    @_login_required("admin")
    def delete_agreement(agreement_no: str):
        db = open_db()
        for table_name, field_name, label in [
            ("lpos", "agreement_no", "LPO"),
            ("hire_records", "agreement_no", "hire row"),
            ("account_invoices", "agreement_no", "invoice"),
        ]:
            count = int(db.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {field_name} = ?", (agreement_no,)).fetchone()[0])
            if count:
                flash(f"Agreement cannot be deleted because {count} {label} record(s) are linked.", "error")
                return redirect(url_for("agreements_lpos"))
        db.execute("DELETE FROM agreements WHERE agreement_no = ?", (agreement_no,))
        _audit_log(db, "agreement_deleted", entity_type="agreement", entity_id=agreement_no, details=agreement_no)
        db.commit()
        flash("Agreement deleted successfully.", "success")
        return redirect(url_for("agreements_lpos"))

    @app.post("/lpos/<lpo_no>/delete")
    @_login_required("admin")
    def delete_lpo(lpo_no: str):
        db = open_db()
        for table_name, field_name, label in [
            ("hire_records", "lpo_no", "hire row"),
            ("account_invoices", "lpo_no", "invoice"),
        ]:
            count = int(db.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {field_name} = ?", (lpo_no,)).fetchone()[0])
            if count:
                flash(f"LPO cannot be deleted because {count} {label} record(s) are linked.", "error")
                return redirect(url_for("agreements_lpos"))
        db.execute("DELETE FROM lpos WHERE lpo_no = ?", (lpo_no,))
        _audit_log(db, "lpo_deleted", entity_type="lpo", entity_id=lpo_no, details=lpo_no)
        db.commit()
        flash("LPO deleted successfully.", "success")
        return redirect(url_for("agreements_lpos"))

    @app.post("/hires/<hire_no>/delete")
    @_login_required("admin")
    def delete_hire(hire_no: str):
        db = open_db()
        count = int(db.execute("SELECT COUNT(*) FROM account_invoices WHERE hire_no = ?", (hire_no,)).fetchone()[0])
        if count:
            flash(f"Hire row cannot be deleted because {count} invoice record(s) are linked.", "error")
            return redirect(url_for("agreements_lpos"))
        db.execute("DELETE FROM hire_records WHERE hire_no = ?", (hire_no,))
        _audit_log(db, "hire_record_deleted", entity_type="hire_record", entity_id=hire_no, details=hire_no)
        db.commit()
        flash("Hire row deleted successfully.", "success")
        return redirect(url_for("agreements_lpos"))

    @app.route("/invoice-center", methods=["GET", "POST"])
    @app.route("/invoices", methods=["GET", "POST"])
    @_login_required("admin")
    def invoice_center():
        db = open_db()
        invoice_values = _default_invoice_form()
        payment_values = _default_payment_form()
        invoice_line_rows = _default_invoice_lines()

        edit_invoice_no = request.args.get("edit_invoice", "").strip().upper()
        edit_voucher_no = request.args.get("edit_payment", "").strip().upper()
        if edit_invoice_no:
            invoice_row = db.execute("SELECT * FROM account_invoices WHERE invoice_no = ?", (edit_invoice_no,)).fetchone()
            if invoice_row is not None:
                invoice_values = _invoice_form_from_row(invoice_row)
                invoice_line_rows = _invoice_line_rows_for_form(db, invoice_row["invoice_no"], invoice_values)
        if edit_voucher_no:
            payment_row = db.execute("SELECT * FROM account_payments WHERE voucher_no = ?", (edit_voucher_no,)).fetchone()
            if payment_row is not None:
                payment_values = _payment_form_from_row(payment_row)

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            try:
                if action == "save_invoice":
                    invoice_values = _invoice_form_data(request)
                    invoice_line_rows = _invoice_line_form_data(request)
                    payload, prepared_lines = _prepare_invoice_payload(db, invoice_values, invoice_line_rows)
                    _ensure_reference_available(
                        db,
                        "account_invoices",
                        "invoice_no",
                        invoice_values["invoice_no"],
                        invoice_values["original_invoice_no"],
                        "Invoice number",
                    )
                    if invoice_values["original_invoice_no"]:
                        already_paid = _invoice_paid_amount_excluding(db, invoice_values["original_invoice_no"])
                        if already_paid - float(invoice_values["total_amount"]) > 0.001:
                            raise ValidationError("Invoice total cannot be less than already posted payments.")
                        db.execute(
                            """
                            UPDATE account_invoices
                            SET invoice_no = ?, party_code = ?, agreement_no = ?, lpo_no = ?, hire_no = ?, invoice_kind = ?,
                                document_type = ?, issue_date = ?, due_date = ?, subtotal = ?, tax_percent = ?,
                                tax_amount = ?, total_amount = ?, pdf_path = ?, notes = ?
                            WHERE invoice_no = ?
                            """,
                            (
                                payload[0], payload[1], payload[2], payload[3], payload[4], payload[5],
                                payload[6], payload[7], payload[8], payload[9], payload[10], payload[11], payload[12], payload[16], payload[17],
                                invoice_values["original_invoice_no"],
                            ),
                        )
                        db.execute("DELETE FROM account_invoice_lines WHERE invoice_no = ?", (invoice_values["original_invoice_no"],))
                        _save_invoice_lines(db, invoice_values["invoice_no"], prepared_lines)
                        if invoice_values["invoice_no"] != invoice_values["original_invoice_no"]:
                            db.execute(
                                "UPDATE account_payments SET invoice_no = ? WHERE invoice_no = ?",
                                (invoice_values["invoice_no"], invoice_values["original_invoice_no"]),
                            )
                        _sync_invoice_balance(db, invoice_values["invoice_no"])
                        _audit_log(
                            db,
                            "account_invoice_updated",
                            entity_type="invoice",
                            entity_id=invoice_values["invoice_no"],
                            details=f"{invoice_values['invoice_kind']} / {invoice_values['party_code']} / AED {invoice_values['total_amount']}",
                        )
                        message = "Invoice updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO account_invoices (
                                invoice_no, party_code, agreement_no, lpo_no, hire_no, invoice_kind,
                                document_type, issue_date, due_date, subtotal, tax_percent, tax_amount,
                                total_amount, paid_amount, balance_amount, status, pdf_path, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        _save_invoice_lines(db, invoice_values["invoice_no"], prepared_lines)
                        _audit_log(
                            db,
                            "account_invoice_created",
                            entity_type="invoice",
                            entity_id=invoice_values["invoice_no"],
                            details=f"{invoice_values['invoice_kind']} / {invoice_values['party_code']} / AED {invoice_values['total_amount']}",
                        )
                        message = "Invoice created successfully."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("invoice_center"))

                if action == "save_payment":
                    payment_values = _payment_form_data(request)
                    original_voucher_no = payment_values["original_voucher_no"]
                    invoice = db.execute(
                        """
                        SELECT invoice_no, party_code, invoice_kind, total_amount, paid_amount, balance_amount
                        FROM account_invoices
                        WHERE invoice_no = ?
                        """,
                        (payment_values["invoice_no"],),
                    ).fetchone()
                    if invoice is None:
                        raise ValidationError("Select a valid invoice before saving payment.")
                    _ensure_reference_available(
                        db,
                        "account_payments",
                        "voucher_no",
                        payment_values["voucher_no"],
                        original_voucher_no,
                        "Voucher number",
                    )
                    entry_date = _validate_date_text(payment_values["entry_date"], "Payment date")
                    amount = _parse_decimal(payment_values["amount"], "Payment amount", required=True, minimum=0.01)
                    other_paid = _invoice_paid_amount_excluding(db, invoice["invoice_no"], original_voucher_no)
                    remaining_balance = float(invoice["total_amount"]) - other_paid
                    if amount - remaining_balance > 0.001:
                        raise ValidationError(f"Payment amount cannot be greater than invoice balance {remaining_balance:,.2f}.")
                    payment_kind = "Received" if (invoice["invoice_kind"] or "Sales") == "Sales" else "Paid"
                    payment_payload = (
                        payment_values["voucher_no"],
                        invoice["invoice_no"],
                        invoice["party_code"],
                        payment_kind,
                        entry_date,
                        amount,
                        payment_values["payment_method"],
                        payment_values["reference"],
                        payment_values["notes"],
                    )
                    if original_voucher_no:
                        existing_payment = db.execute("SELECT invoice_no FROM account_payments WHERE voucher_no = ?", (original_voucher_no,)).fetchone()
                        if existing_payment is None:
                            raise ValidationError("Payment voucher was not found.")
                        db.execute(
                            """
                            UPDATE account_payments
                            SET voucher_no = ?, invoice_no = ?, party_code = ?, payment_kind = ?, entry_date = ?,
                                amount = ?, payment_method = ?, reference = ?, notes = ?
                            WHERE voucher_no = ?
                            """,
                            payment_payload + (original_voucher_no,),
                        )
                        if existing_payment["invoice_no"] and existing_payment["invoice_no"] != invoice["invoice_no"]:
                            _sync_invoice_balance(db, existing_payment["invoice_no"])
                        _sync_invoice_balance(db, invoice["invoice_no"])
                        _audit_log(
                            db,
                            "account_payment_updated",
                            entity_type="payment",
                            entity_id=payment_values["voucher_no"],
                            details=f"{payment_kind} / {invoice['invoice_no']} / AED {amount}",
                        )
                        message = "Payment updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO account_payments (
                                voucher_no, invoice_no, party_code, payment_kind, entry_date,
                                amount, payment_method, reference, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payment_payload,
                        )
                        _sync_invoice_balance(db, invoice["invoice_no"])
                        _audit_log(
                            db,
                            "account_payment_created",
                            entity_type="payment",
                            entity_id=payment_values["voucher_no"],
                            details=f"{payment_kind} / {invoice['invoice_no']} / AED {amount}",
                        )
                        message = "Payment saved and invoice balance updated."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("invoice_center"))
            except ValidationError as exc:
                flash(str(exc), "error")

        return render_template(
            "invoice_center.html",
            invoice_values=invoice_values,
            invoice_line_rows=invoice_line_rows,
            payment_values=payment_values,
            invoice_kind_options=INVOICE_KIND_OPTIONS,
            invoice_document_options=INVOICE_DOCUMENT_OPTIONS,
            payment_method_options=PAYMENT_METHOD_OPTIONS,
            parties=_contract_parties(db),
            agreements=_agreement_rows(db, limit=40),
            lpos=_lpo_rows(db, limit=40),
            hires=_hire_rows(db, limit=40),
            open_invoices=_open_invoice_rows(db),
            invoices=_invoice_rows(db, limit=12),
            payments=_payment_rows(db, limit=12),
            summary=_invoice_center_summary(db),
        )

    @app.get("/invoices/<invoice_no>/pdf")
    @_login_required("admin")
    def invoice_pdf(invoice_no: str):
        db = open_db()
        pdf_path = _regenerate_invoice_pdf(app, db, invoice_no)
        if not pdf_path:
            flash("Invoice PDF could not be generated.", "error")
            return redirect(url_for("invoice_center"))
        relative_path = Path(pdf_path).relative_to(Path(app.config["GENERATED_DIR"])).as_posix()
        flash("Invoice PDF generated successfully.", "success")
        return redirect(url_for("generated_file", filename=relative_path))

    @app.post("/invoices/<invoice_no>/delete")
    @_login_required("admin")
    def delete_invoice(invoice_no: str):
        db = open_db()
        payment_count = int(db.execute("SELECT COUNT(*) FROM account_payments WHERE invoice_no = ?", (invoice_no,)).fetchone()[0])
        if payment_count:
            flash("Invoice cannot be deleted while payments are linked to it.", "error")
            return redirect(url_for("invoice_center"))
        db.execute("DELETE FROM account_invoice_lines WHERE invoice_no = ?", (invoice_no,))
        db.execute("DELETE FROM account_invoices WHERE invoice_no = ?", (invoice_no,))
        _audit_log(db, "account_invoice_deleted", entity_type="invoice", entity_id=invoice_no, details=invoice_no)
        db.commit()
        flash("Invoice deleted successfully.", "success")
        return redirect(url_for("invoice_center"))

    @app.post("/payments/<voucher_no>/delete")
    @_login_required("admin")
    def delete_payment(voucher_no: str):
        db = open_db()
        payment = db.execute("SELECT invoice_no FROM account_payments WHERE voucher_no = ?", (voucher_no,)).fetchone()
        if payment is None:
            flash("Payment voucher not found.", "error")
            return redirect(url_for("invoice_center"))
        db.execute("DELETE FROM account_payments WHERE voucher_no = ?", (voucher_no,))
        if payment["invoice_no"]:
            _sync_invoice_balance(db, payment["invoice_no"])
        _audit_log(db, "account_payment_deleted", entity_type="payment", entity_id=voucher_no, details=voucher_no)
        db.commit()
        flash("Payment deleted successfully.", "success")
        return redirect(url_for("invoice_center"))

    @app.route("/loans", methods=["GET", "POST"])
    @_login_required("admin")
    def loans_center():
        _touch_admin_workspace("accounts")
        db = open_db()
        values = _default_loan_form()
        edit_loan_no = request.args.get("edit_loan", "").strip().upper()
        if edit_loan_no:
            row = db.execute("SELECT * FROM loan_entries WHERE loan_no = ?", (edit_loan_no,)).fetchone()
            if row is not None:
                values = _loan_form_from_row(row)
        if request.method == "POST":
            values = _loan_form_data(request)
            try:
                payload = _prepare_loan_payload(db, values)
                _ensure_reference_available(db, "loan_entries", "loan_no", values["loan_no"], values["original_loan_no"], "Loan number")
                if values["original_loan_no"]:
                    db.execute(
                        """
                        UPDATE loan_entries
                        SET loan_no = ?, party_code = ?, entry_date = ?, loan_type = ?, amount = ?, payment_method = ?, reference = ?, notes = ?
                        WHERE loan_no = ?
                        """,
                        payload + (values["original_loan_no"],),
                    )
                    _audit_log(
                        db,
                        "loan_entry_updated",
                        entity_type="loan",
                        entity_id=values["loan_no"],
                        details=f"{values['loan_type']} / {values['party_code']} / AED {values['amount']}",
                    )
                    message = "Loan entry updated successfully."
                else:
                    db.execute(
                        """
                        INSERT INTO loan_entries (
                            loan_no, party_code, entry_date, loan_type, amount, payment_method, reference, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        payload,
                    )
                    _audit_log(
                        db,
                        "loan_entry_created",
                        entity_type="loan",
                        entity_id=values["loan_no"],
                        details=f"{values['loan_type']} / {values['party_code']} / AED {values['amount']}",
                    )
                    message = "Loan entry saved successfully."
                db.commit()
                flash(message, "success")
                return redirect(url_for("loans_center"))
            except ValidationError as exc:
                flash(str(exc), "error")

        return render_template(
            "loans.html",
            values=values,
            loan_type_options=LOAN_TYPE_OPTIONS,
            payment_method_options=PAYMENT_METHOD_OPTIONS,
            parties=_contract_parties(db),
            rows=_loan_rows(db),
            summary=_loan_summary(db),
        )

    @app.post("/loans/<loan_no>/delete")
    @_login_required("admin")
    def delete_loan_entry(loan_no: str):
        db = open_db()
        db.execute("DELETE FROM loan_entries WHERE loan_no = ?", (loan_no,))
        _audit_log(db, "loan_entry_deleted", entity_type="loan", entity_id=loan_no, details=loan_no)
        db.commit()
        flash("Loan entry deleted successfully.", "success")
        return redirect(url_for("loans_center"))

    @app.route("/annual-fees", methods=["GET", "POST"])
    @_login_required("admin")
    def annual_fees():
        _touch_admin_workspace("accounts")
        db = open_db()
        values = _default_fee_form()
        edit_fee_no = request.args.get("edit_fee", "").strip().upper()
        if edit_fee_no:
            row = db.execute("SELECT * FROM annual_fee_entries WHERE fee_no = ?", (edit_fee_no,)).fetchone()
            if row is not None:
                values = _fee_form_from_row(row)
        if request.method == "POST":
            values = _fee_form_data(request)
            try:
                payload = _prepare_fee_payload(db, values)
                _ensure_reference_available(db, "annual_fee_entries", "fee_no", values["fee_no"], values["original_fee_no"], "Fee number")
                if values["original_fee_no"]:
                    db.execute(
                        """
                        UPDATE annual_fee_entries
                        SET fee_no = ?, party_code = ?, fee_type = ?, description = ?, vehicle_no = ?, due_date = ?,
                            annual_amount = ?, received_amount = ?, balance_amount = ?, status = ?, notes = ?
                        WHERE fee_no = ?
                        """,
                        payload + (values["original_fee_no"],),
                    )
                    _audit_log(
                        db,
                        "annual_fee_updated",
                        entity_type="annual_fee",
                        entity_id=values["fee_no"],
                        details=f"{values['fee_type']} / {values['party_code']} / AED {values['annual_amount']}",
                    )
                    message = "Annual fee row updated successfully."
                else:
                    db.execute(
                        """
                        INSERT INTO annual_fee_entries (
                            fee_no, party_code, fee_type, description, vehicle_no, due_date,
                            annual_amount, received_amount, balance_amount, status, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        payload,
                    )
                    _audit_log(
                        db,
                        "annual_fee_created",
                        entity_type="annual_fee",
                        entity_id=values["fee_no"],
                        details=f"{values['fee_type']} / {values['party_code']} / AED {values['annual_amount']}",
                    )
                    message = "Annual fee row saved successfully."
                db.commit()
                flash(message, "success")
                return redirect(url_for("annual_fees"))
            except ValidationError as exc:
                flash(str(exc), "error")

        return render_template(
            "annual_fees.html",
            values=values,
            fee_type_options=FEE_TYPE_OPTIONS,
            parties=_contract_parties(db),
            rows=_annual_fee_rows(db),
            summary=_annual_fee_summary(db),
        )

    @app.post("/annual-fees/<fee_no>/delete")
    @_login_required("admin")
    def delete_annual_fee(fee_no: str):
        db = open_db()
        db.execute("DELETE FROM annual_fee_entries WHERE fee_no = ?", (fee_no,))
        _audit_log(db, "annual_fee_deleted", entity_type="annual_fee", entity_id=fee_no, details=fee_no)
        db.commit()
        flash("Annual fee row deleted successfully.", "success")
        return redirect(url_for("annual_fees"))

    @app.get("/tax")
    @_login_required("admin")
    def tax_center():
        _touch_admin_workspace("accounts")
        db = open_db()
        return render_template(
            "tax_center.html",
            summary=_tax_summary(db),
            invoices=_invoice_rows(db, limit=10),
        )

    @app.get("/reports")
    @_login_required("admin")
    def reports_center():
        _touch_admin_workspace("accounts")
        db = open_db()
        return render_template(
            "reports_center.html",
            supplier_summary=_supplier_summary(db),
            customer_summary=_customer_summary(db),
            invoice_summary=_invoice_center_summary(db),
            loan_summary=_loan_summary(db),
            annual_fee_summary=_annual_fee_summary(db),
            tax_summary=_tax_summary(db),
            top_receivables=_party_balance_rows(db, invoice_kind="Sales", limit=6),
            top_payables=_party_balance_rows(db, invoice_kind="Purchase", limit=6),
            due_fees=_annual_fee_rows(db, limit=6, due_only=True),
            recent_loans=_loan_rows(db, limit=6),
        )

    @app.route("/owner-fund", methods=["GET", "POST"])
    @_login_required("admin", "owner")
    def owner_fund():
        if _current_role() == "admin":
            _touch_admin_workspace("accounts")
        db = open_db()
        can_edit = _current_role() == "admin"
        edit_entry_id = request.args.get("edit", "").strip()
        values = {
            "entry_id": "",
            "owner_name": "",
            "entry_date": date.today().isoformat(),
            "amount": "",
            "received_by": "",
            "payment_method": "Cash",
            "details": "",
        }

        if edit_entry_id:
            existing_entry = db.execute(
                """
                SELECT id, owner_name, entry_date, amount, received_by, payment_method, details
                FROM owner_fund_entries
                WHERE id = ?
                """,
                (edit_entry_id,),
            ).fetchone()
            if existing_entry and can_edit:
                values = {
                    "entry_id": str(existing_entry["id"]),
                    "owner_name": existing_entry["owner_name"],
                    "entry_date": existing_entry["entry_date"],
                    "amount": f"{float(existing_entry['amount']):.2f}",
                    "received_by": existing_entry["received_by"] or "",
                    "payment_method": existing_entry["payment_method"] or "Cash",
                    "details": existing_entry["details"] or "",
                }

        if request.method == "POST":
            if not can_edit:
                flash("Owner view is read-only.", "error")
                return redirect(url_for("owner_fund"))

            values = {
                "entry_id": request.form.get("entry_id", "").strip(),
                "owner_name": request.form.get("owner_name", "").strip(),
                "entry_date": request.form.get("entry_date", date.today().isoformat()).strip() or date.today().isoformat(),
                "amount": request.form.get("amount", "").strip(),
                "received_by": request.form.get("received_by", "").strip(),
                "payment_method": request.form.get("payment_method", "Cash").strip() or "Cash",
                "details": request.form.get("details", "").strip(),
            }
            try:
                amount = _parse_decimal(values["amount"], "Amount", minimum=0.01)
            except ValidationError as exc:
                flash(str(exc), "error")
            else:
                if not values["owner_name"]:
                    flash("Owner name is required.", "error")
                else:
                    if values["entry_id"]:
                        db.execute(
                            """
                            UPDATE owner_fund_entries
                            SET owner_name = ?, entry_date = ?, amount = ?, received_by = ?, payment_method = ?, details = ?
                            WHERE id = ?
                            """,
                            (
                                values["owner_name"],
                                values["entry_date"],
                                amount,
                                values["received_by"],
                                values["payment_method"],
                                values["details"],
                                values["entry_id"],
                            ),
                        )
                        _audit_log(
                            db,
                            "owner_fund_updated",
                            entity_type="owner_fund",
                            entity_id=values["entry_id"],
                            details=f"{values['owner_name']} / AED {amount:.2f}",
                        )
                        message = "Owner fund entry updated."
                    else:
                        db.execute(
                            """
                            INSERT INTO owner_fund_entries (owner_name, entry_date, amount, received_by, payment_method, details)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                values["owner_name"],
                                values["entry_date"],
                                amount,
                                values["received_by"],
                                values["payment_method"],
                                values["details"],
                            ),
                        )
                        _audit_log(
                            db,
                            "owner_fund_created",
                            entity_type="owner_fund",
                            entity_id=values["owner_name"],
                            details=f"{values['owner_name']} / AED {amount:.2f}",
                        )
                        message = "Owner fund entry saved."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("owner_fund"))

        incoming, outgoing, balance = _owner_fund_totals(db)
        entries = db.execute(
            """
            SELECT id, owner_name, entry_date, amount, received_by, payment_method, details
            FROM owner_fund_entries
            ORDER BY entry_date DESC, id DESC
            LIMIT 20
            """
        ).fetchall()
        statement = _owner_fund_statement(db)
        pdf_files = _recent_generated_files(Path(app.config["GENERATED_DIR"]) / "owner_fund", "owner-fund-kata")

        return render_template(
            "owner_fund.html",
            values=values,
            incoming=incoming,
            outgoing=outgoing,
            balance=balance,
            entries=entries,
            statement=statement,
            can_edit=can_edit,
            pdf_files=pdf_files,
        )

    @app.post("/owner-fund/<int:entry_id>/delete")
    @_login_required("admin")
    def delete_owner_fund_entry(entry_id: int):
        db = open_db()
        entry = db.execute(
            """
            SELECT id, owner_name, amount
            FROM owner_fund_entries
            WHERE id = ?
            """,
            (entry_id,),
        ).fetchone()
        if entry is None:
            flash("Owner fund entry not found.", "error")
            return redirect(url_for("owner_fund"))
        db.execute("DELETE FROM owner_fund_entries WHERE id = ?", (entry_id,))
        _audit_log(
            db,
            "owner_fund_deleted",
            entity_type="owner_fund",
            entity_id=str(entry_id),
            details=f"{entry['owner_name']} / AED {float(entry['amount']):.2f}",
        )
        db.commit()
        flash("Owner fund entry deleted.", "success")
        return redirect(url_for("owner_fund"))

    @app.get("/owner-fund/pdf")
    @_login_required("admin", "owner")
    def owner_fund_pdf():
        db = open_db()
        incoming, outgoing, balance = _owner_fund_totals(db)
        statement = _owner_fund_statement(db, reverse=False)
        output_dir = Path(app.config["GENERATED_DIR"]) / "owner_fund"
        pdf_path = generate_owner_fund_pdf(
            statement,
            {"incoming": incoming, "outgoing": outgoing, "balance": balance},
            str(output_dir),
            app.config["STATIC_ASSETS_DIR"],
        )
        relative_path = Path(pdf_path).relative_to(app.config["GENERATED_DIR"]).as_posix()
        return redirect(url_for("generated_file", filename=relative_path))

    @app.route("/portal/driver", methods=["GET", "POST"])
    @_login_required("driver")
    def driver_portal():
        db = open_db()
        driver = _fetch_driver(db, _current_driver_id())
        if driver is None:
            session.clear()
            flash("Driver account was not found.", "error")
            return redirect(url_for("login"))

        selected_month = _normalize_month(
            request.args.get("month", "").strip()
            or request.form.get("selected_month", "").strip()
            or _current_month_value()
        )
        timesheet_values = {
            "entry_date": date.today().isoformat(),
            "work_hours": "",
            "remarks": "",
        }

        if request.method == "POST":
            timesheet_values = {
                "entry_date": request.form.get("entry_date", date.today().isoformat()).strip() or date.today().isoformat(),
                "work_hours": request.form.get("work_hours", "").strip(),
                "remarks": request.form.get("remarks", "").strip(),
            }
            try:
                work_hours = _parse_decimal(timesheet_values["work_hours"], "Hours", minimum=0.01, maximum=24)
            except ValidationError as exc:
                flash(str(exc), "error")
            else:
                db.execute(
                    """
                    INSERT INTO driver_timesheets (driver_id, entry_date, work_hours, remarks)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(driver_id, entry_date) DO UPDATE SET
                        work_hours = excluded.work_hours,
                        remarks = excluded.remarks
                    """,
                    (driver["driver_id"], timesheet_values["entry_date"], work_hours, timesheet_values["remarks"]),
                )
                db.commit()
                flash("Timesheet saved.", "success")
                return redirect(url_for("driver_portal", month=selected_month))

        recent_timesheets = db.execute(
            """
            SELECT entry_date, work_hours, remarks
            FROM driver_timesheets
            WHERE driver_id = ?
            ORDER BY entry_date DESC, id DESC
            LIMIT 12
            """,
            (driver["driver_id"],),
        ).fetchall()
        recent_transactions = db.execute(
            """
            SELECT entry_date, txn_type, source, amount, details
            FROM driver_transactions
            WHERE driver_id = ?
            ORDER BY entry_date DESC, id DESC
            LIMIT 12
            """,
            (driver["driver_id"],),
        ).fetchall()
        salary_slips = db.execute(
            """
            SELECT salary_month, net_payable, total_deductions, pdf_path, payment_source, generated_at
            FROM salary_slips
            WHERE driver_id = ?
            ORDER BY generated_at DESC, id DESC
            LIMIT 12
            """,
            (driver["driver_id"],),
        ).fetchall()
        month_hours = _timesheet_total_for_month(db, driver["driver_id"], selected_month)
        month_calendar = _driver_month_calendar(db, driver["driver_id"], selected_month)
        timesheet_summary = _timesheet_month_summary(month_calendar)

        return render_template(
            "driver_portal.html",
            driver=driver,
            photo_url=_driver_photo_url(app, driver),
            values=timesheet_values,
            recent_timesheets=recent_timesheets,
            recent_transactions=recent_transactions,
            salary_slips=salary_slips,
            month_hours=month_hours,
            outstanding_advance=_outstanding_advance(db, driver["driver_id"]),
            selected_month=selected_month,
            selected_month_label=format_month_label(selected_month),
            month_calendar=month_calendar,
            timesheet_summary=timesheet_summary,
        )

    @app.route("/drivers/list")
    @_login_required("admin")
    def driver_list():
        _touch_admin_workspace("drivers")
        db = open_db()
        query = request.args.get("q", "").strip()
        status_filter = request.args.get("status", "").strip()
        shift_filter = request.args.get("shift", "").strip()
        vehicle_filter = request.args.get("vehicle_type", "").strip()
        where_sql, params = _driver_filter_clause(query, status_filter, shift_filter, vehicle_filter)

        drivers = db.execute(
            f"""
            SELECT driver_id, full_name, phone_number, vehicle_no, shift, vehicle_type, basic_salary,
                   ot_rate, duty_start, photo_name, status, remarks
            FROM drivers
            {where_sql}
            ORDER BY CASE WHEN status = 'Active' THEN 0 ELSE 1 END, full_name ASC
            """,
            params,
        ).fetchall()
        filter_options = _driver_filter_options(db)
        return render_template(
            "driver_list.html",
            drivers=drivers,
            query=query,
            status_filter=status_filter,
            shift_filter=shift_filter,
            vehicle_filter=vehicle_filter,
            shifts=filter_options["shifts"],
            vehicle_types=filter_options["vehicle_types"],
            driver_count=len(drivers),
            active_count=sum(1 for driver in drivers if (driver["status"] or "").lower() == "active"),
            inactive_count=sum(1 for driver in drivers if (driver["status"] or "").lower() != "active"),
        )

    @app.route("/drivers/new", methods=["GET", "POST"])
    @_login_required("admin")
    def create_driver():
        _touch_admin_workspace("drivers")
        if request.method == "POST":
            form = _driver_form_data(request)
            missing_fields = [
                name
                for name, value in form.items()
                if name not in {"remarks", "photo_name", "duty_start", "driver_pin", "confirm_driver_pin"} and not value
            ]
            if missing_fields or not form["driver_pin"] or not form["confirm_driver_pin"]:
                flash("Please fill in all required driver fields.", "error")
                return render_template(
                    "driver_form.html",
                    values=form,
                    page_title="Add Driver",
                    submit_label="Save Driver",
                    edit_mode=False,
                    current_photo_url=None,
                )

            uploaded_photo = _save_driver_photo(app, form["driver_id"], form["full_name"], request.files.get("photo_file"))
            if uploaded_photo:
                form["photo_name"] = uploaded_photo["photo_name"]

            try:
                basic_salary = _parse_decimal(form["basic_salary"], "Basic salary", minimum=0.01)
                ot_rate = _parse_decimal(form["ot_rate"], "OT rate", minimum=0.0)
                normalized_phone = _normalize_required_phone(form["phone_number"])
                pin_hash = _driver_pin_hash_from_form(form, edit_mode=False)
            except ValidationError as exc:
                flash(str(exc), "error")
                return render_template(
                    "driver_form.html",
                    values=form,
                    page_title="Add Driver",
                    submit_label="Save Driver",
                    edit_mode=False,
                    current_photo_url=None,
                )

            form["phone_number"] = normalized_phone
            db = open_db()
            try:
                db.execute(
                    """
                    INSERT INTO drivers (
                        driver_id, full_name, phone_number, pin_hash, vehicle_no, shift, vehicle_type,
                        basic_salary, ot_rate, duty_start, photo_name, photo_data, photo_content_type, status, remarks
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _driver_insert_values(form, basic_salary, ot_rate, pin_hash, uploaded_photo),
                )
                _audit_log(
                    db,
                    "driver_created",
                    entity_type="driver",
                    entity_id=form["driver_id"],
                    details=f"{form['full_name']} / {form['vehicle_no']}",
                )
                db.commit()
            except Exception:
                flash("Driver ID must be unique.", "error")
                return render_template(
                    "driver_form.html",
                    values=form,
                    page_title="Add Driver",
                    submit_label="Save Driver",
                    edit_mode=False,
                    current_photo_url=_driver_photo_url(app, form),
                )

            flash("Driver saved. The new card is ready on the dashboard.", "success")
            return redirect(url_for("dashboard"))

        return render_template(
            "driver_form.html",
            values={},
            page_title="Add Driver",
            submit_label="Save Driver",
            edit_mode=False,
            current_photo_url=None,
        )

    @app.route("/drivers/<driver_id>/edit", methods=["GET", "POST"])
    @_login_required("admin")
    def edit_driver(driver_id: str):
        _touch_admin_workspace("drivers")
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for("driver_list"))

        if request.method == "POST":
            form = _driver_form_data(request)
            form["driver_id"] = driver_id
            uploaded_photo = _save_driver_photo(app, driver_id, form["full_name"], request.files.get("photo_file"))
            if uploaded_photo:
                form["photo_name"] = uploaded_photo["photo_name"]
            elif not form["photo_name"]:
                form["photo_name"] = driver["photo_name"] or ""

            try:
                basic_salary = _parse_decimal(form["basic_salary"], "Basic salary", minimum=0.01)
                ot_rate = _parse_decimal(form["ot_rate"], "OT rate", minimum=0.0)
                normalized_phone = _normalize_required_phone(form["phone_number"])
                pin_hash = _driver_pin_hash_from_form(form, edit_mode=True, existing_pin_hash=driver["pin_hash"] or "")
            except ValidationError as exc:
                flash(str(exc), "error")
                return render_template(
                    "driver_form.html",
                    values=form,
                    page_title="Edit Driver",
                    submit_label="Update Driver",
                    edit_mode=True,
                    current_photo_url=_driver_photo_url(app, driver),
                )

            db.execute(
                """
                UPDATE drivers
                SET full_name = ?, phone_number = ?, pin_hash = ?, vehicle_no = ?, shift = ?, vehicle_type = ?,
                    basic_salary = ?, ot_rate = ?, duty_start = ?, photo_name = ?,
                    photo_data = ?, photo_content_type = ?, status = ?, remarks = ?
                WHERE driver_id = ?
                """,
                (
                    form["full_name"],
                    normalized_phone,
                    pin_hash,
                    form["vehicle_no"],
                    form["shift"],
                    form["vehicle_type"],
                    basic_salary,
                    ot_rate,
                    form["duty_start"],
                    form["photo_name"],
                    uploaded_photo["photo_data"] if uploaded_photo else (driver["photo_data"] or ""),
                    uploaded_photo["photo_content_type"] if uploaded_photo else (driver["photo_content_type"] or ""),
                    form["status"],
                    form["remarks"],
                    driver_id,
                ),
            )
            _audit_log(
                db,
                "driver_updated",
                entity_type="driver",
                entity_id=driver_id,
                details=f"{form['full_name']} / {form['vehicle_no']}",
            )
            db.commit()
            flash("Driver updated successfully.", "success")
            return redirect(url_for("driver_list"))

        return render_template(
            "driver_form.html",
            values=dict(driver),
            page_title="Edit Driver",
            submit_label="Update Driver",
            edit_mode=True,
            current_photo_url=_driver_photo_url(app, driver),
        )

    @app.post("/drivers/<driver_id>/status")
    @_login_required("admin")
    def update_driver_status(driver_id: str):
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for("driver_list"))
        next_status = request.form.get("status", "Active").strip() or "Active"
        db.execute("UPDATE drivers SET status = ? WHERE driver_id = ?", (next_status, driver_id))
        db.commit()
        flash(f"{driver_id} marked as {next_status}.", "success")
        return redirect(url_for("driver_list"))

    @app.post("/drivers/<driver_id>/delete")
    @_login_required("admin")
    def delete_driver(driver_id: str):
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for("driver_list"))

        db.execute("DELETE FROM driver_timesheets WHERE driver_id = ?", (driver_id,))
        db.execute("DELETE FROM driver_transactions WHERE driver_id = ?", (driver_id,))
        db.execute("DELETE FROM salary_slips WHERE driver_id = ?", (driver_id,))
        db.execute("DELETE FROM salary_store WHERE driver_id = ?", (driver_id,))
        db.execute("DELETE FROM drivers WHERE driver_id = ?", (driver_id,))
        _audit_log(
            db,
            "driver_deleted",
            entity_type="driver",
            entity_id=driver_id,
            details=driver["full_name"],
        )
        db.commit()
        _remove_driver_generated_files(app, driver)
        flash(f"{driver['full_name']} deleted successfully.", "success")
        return redirect(url_for("driver_list"))

    @app.post("/drivers/import-currentlink")
    @_login_required("admin")
    def import_currentlink():
        try:
            records = load_driver_records(app.config["CURRENTLINK_FILE"])
            db = open_db()
            imported = upsert_driver_records(db, records)
            _log_import_history(db, "Currentlink Workbook", Path(app.config["CURRENTLINK_FILE"]).name, imported)
            db.commit()
        except FileNotFoundError:
            flash("Currentlink.xlsm was not found in Downloads.", "error")
            return redirect(url_for("dashboard"))
        except Exception as exc:
            flash(f"Import failed: {exc}", "error")
            return redirect(url_for("dashboard"))
        flash(f"Imported or updated {imported} drivers from Currentlink.xlsm.", "success")
        return redirect(url_for("dashboard"))

    @app.post("/drivers/import-driver-pdf")
    @_login_required("admin")
    def import_driver_pdf():
        try:
            uploaded_pdf = request.files.get("driver_pdf")
            if uploaded_pdf and uploaded_pdf.filename:
                file_name = uploaded_pdf.filename
                records = load_driver_records_from_pdf_bytes(uploaded_pdf.read())
            else:
                file_name = Path(app.config["DRIVER_PDF_FILE"]).name
                records = load_driver_records_from_pdf(app.config["DRIVER_PDF_FILE"])
            db = open_db()
            imported = upsert_driver_records(db, records)
            _log_import_history(db, "Driver PDF", file_name, imported)
            db.commit()
        except FileNotFoundError:
            flash("Driver.pdf was not found in Downloads.", "error")
            return redirect(url_for("dashboard"))
        except Exception as exc:
            flash(f"Driver PDF import failed: {exc}", "error")
            return redirect(url_for("dashboard"))

        flash(f"Imported or updated {imported} drivers from Driver PDF.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/drivers/<driver_id>")
    @_login_required("admin")
    def driver_action(driver_id: str):
        _touch_admin_workspace("drivers")
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for("driver_list"))

        current_month = _current_month_value()
        current_salary = db.execute(
            "SELECT * FROM salary_store WHERE driver_id = ? AND salary_month = ?",
            (driver_id, current_month),
        ).fetchone()
        latest_slip = db.execute(
            "SELECT * FROM salary_slips WHERE driver_id = ? ORDER BY generated_at DESC LIMIT 1",
            (driver_id,),
        ).fetchone()
        recent_transaction = db.execute(
            """
            SELECT entry_date, txn_type, amount
            FROM driver_transactions
            WHERE driver_id = ?
            ORDER BY entry_date DESC, id DESC
            LIMIT 1
            """,
            (driver_id,),
        ).fetchone()

        return render_template(
            "driver_action.html",
            driver=driver,
            photo_url=_driver_photo_url(app, driver),
            salary_status="Stored" if current_salary else "Not Stored",
            current_month_label=format_month_label(current_month),
            salary_due=_driver_balance(db, driver_id),
            advance_summary=_advance_summary(db, driver_id),
            outstanding_advance=_outstanding_advance(db, driver_id),
            transaction_count=db.execute(
                "SELECT COUNT(*) FROM driver_transactions WHERE driver_id = ?",
                (driver_id,),
            ).fetchone()[0],
            salary_count=db.execute(
                "SELECT COUNT(*) FROM salary_store WHERE driver_id = ?",
                (driver_id,),
            ).fetchone()[0],
            latest_slip=latest_slip,
            recent_transaction=recent_transaction,
        )

    @app.route("/drivers/<driver_id>/transactions", methods=["GET", "POST"])
    @_login_required("admin")
    def driver_transactions(driver_id: str):
        _touch_admin_workspace("drivers")
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for("driver_list"))

        edit_transaction_id = request.args.get("edit", "").strip()
        form = {
            "transaction_id": "",
            "entry_date": date.today().isoformat(),
            "txn_type": TRANSACTION_TYPES[0],
            "source": PAYMENT_SOURCES[0],
            "given_by": "",
            "amount": "",
            "details": "",
        }

        if edit_transaction_id:
            existing_transaction = db.execute(
                """
                SELECT id, entry_date, txn_type, source, given_by, amount, details
                FROM driver_transactions
                WHERE id = ? AND driver_id = ?
                """,
                (edit_transaction_id, driver_id),
            ).fetchone()
            if existing_transaction:
                form = {
                    "transaction_id": str(existing_transaction["id"]),
                    "entry_date": existing_transaction["entry_date"],
                    "txn_type": existing_transaction["txn_type"],
                    "source": existing_transaction["source"],
                    "given_by": existing_transaction["given_by"] or "",
                    "amount": f"{float(existing_transaction['amount']):.2f}",
                    "details": existing_transaction["details"] or "",
                }

        if request.method == "POST":
            form = {
                "transaction_id": request.form.get("transaction_id", "").strip(),
                "entry_date": request.form.get("entry_date", date.today().isoformat()).strip() or date.today().isoformat(),
                "txn_type": request.form.get("txn_type", TRANSACTION_TYPES[0]).strip() or TRANSACTION_TYPES[0],
                "source": request.form.get("source", PAYMENT_SOURCES[0]).strip() or PAYMENT_SOURCES[0],
                "given_by": request.form.get("given_by", "").strip(),
                "amount": request.form.get("amount", "").strip(),
                "details": request.form.get("details", "").strip(),
            }
            try:
                amount = _parse_decimal(form["amount"], "Amount", minimum=0.01)
            except ValidationError as exc:
                flash(str(exc), "error")
            else:
                if form["transaction_id"]:
                    db.execute(
                        """
                        UPDATE driver_transactions
                        SET entry_date = ?, txn_type = ?, source = ?, given_by = ?, amount = ?, details = ?
                        WHERE id = ? AND driver_id = ?
                        """,
                        (
                            form["entry_date"],
                            form["txn_type"],
                            form["source"],
                            form["given_by"],
                            amount,
                            form["details"],
                            form["transaction_id"],
                            driver_id,
                        ),
                    )
                    _audit_log(
                        db,
                        "transaction_updated",
                        entity_type="driver_transaction",
                        entity_id=form["transaction_id"],
                        details=f"{driver_id} / AED {amount:.2f}",
                    )
                    message = "Transaction updated and driver KATA PDF refreshed."
                else:
                    db.execute(
                        """
                        INSERT INTO driver_transactions (driver_id, entry_date, txn_type, source, given_by, amount, details)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            driver_id,
                            form["entry_date"],
                            form["txn_type"],
                            form["source"],
                            form["given_by"],
                            amount,
                            form["details"],
                        ),
                    )
                    _audit_log(
                        db,
                        "transaction_created",
                        entity_type="driver_transaction",
                        entity_id=driver_id,
                        details=f"{form['txn_type']} / AED {amount:.2f}",
                    )
                    message = "Transaction saved and driver KATA PDF updated."
                db.commit()
                _regenerate_kata_for_driver(app, db, driver)
                flash(message, "success")
                return redirect(url_for("driver_transactions", driver_id=driver_id))

        transactions = db.execute(
            """
            SELECT id, entry_date, txn_type, source, given_by, amount, details
            FROM driver_transactions
            WHERE driver_id = ?
            ORDER BY entry_date DESC, id DESC
            LIMIT 20
            """,
            (driver_id,),
        ).fetchall()
        return render_template(
            "driver_transactions.html",
            driver=driver,
            photo_url=_driver_photo_url(app, driver),
            values=form,
            transactions=transactions,
            transaction_types=TRANSACTION_TYPES,
            payment_sources=PAYMENT_SOURCES,
            salary_due=_driver_balance(db, driver_id),
            advance_summary=_advance_summary(db, driver_id),
        )

    @app.post("/drivers/<driver_id>/transactions/<int:transaction_id>/delete")
    @_login_required("admin")
    def delete_driver_transaction(driver_id: str, transaction_id: int):
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for("dashboard"))
        db.execute("DELETE FROM driver_transactions WHERE id = ? AND driver_id = ?", (transaction_id, driver_id))
        _audit_log(
            db,
            "transaction_deleted",
            entity_type="driver_transaction",
            entity_id=str(transaction_id),
            details=driver_id,
        )
        db.commit()
        _regenerate_kata_for_driver(app, db, driver)
        flash("Transaction deleted and driver KATA PDF refreshed.", "success")
        return redirect(url_for("driver_transactions", driver_id=driver_id))

    @app.route("/drivers/<driver_id>/salary-store", methods=["GET", "POST"])
    @_login_required("admin")
    def driver_salary_store(driver_id: str):
        _touch_admin_workspace("drivers")
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for("driver_list"))

        edit_salary_id = request.args.get("edit", "").strip()
        selected_month = request.args.get("month", "").strip() or _current_month_value()
        existing_row = None
        if edit_salary_id:
            existing_row = db.execute(
                "SELECT * FROM salary_store WHERE id = ? AND driver_id = ?",
                (edit_salary_id, driver_id),
            ).fetchone()
            if existing_row is not None:
                selected_month = existing_row["salary_month"]
        else:
            existing_row = db.execute(
                "SELECT * FROM salary_store WHERE driver_id = ? AND salary_month = ?",
                (driver_id, selected_month),
            ).fetchone()

        form = _default_salary_form(selected_month, driver.get("duty_start"))
        preview = _calculate_salary_preview(driver, form)
        if existing_row is not None:
            form = _salary_form_from_row(existing_row)
            preview = _salary_preview_from_row(existing_row)

        if request.method == "POST":
            form = {
                "entry_date": request.form.get("entry_date", date.today().isoformat()).strip() or date.today().isoformat(),
                "salary_month": _normalize_month(request.form.get("salary_month", selected_month).strip() or selected_month),
                "ot_month": "",
                "salary_mode": (request.form.get("salary_mode", "full").strip() or "full").lower(),
                "prorata_start_date": request.form.get("prorata_start_date", "").strip(),
                "ot_hours": request.form.get("ot_hours", "0").strip() or "0",
                "personal_vehicle": request.form.get("personal_vehicle", "0").strip() or "0",
                "remarks": request.form.get("remarks", "").strip(),
            }
            form["ot_month"] = _previous_month_value(form["salary_month"])
            existing_row = db.execute(
                "SELECT * FROM salary_store WHERE driver_id = ? AND salary_month = ?",
                (driver_id, form["salary_month"]),
            ).fetchone()
            try:
                preview = _calculate_salary_preview(driver, form)
            except ValidationError as exc:
                flash(str(exc), "error")
                return render_template(
                    "driver_salary_store.html",
                    driver=driver,
                    photo_url=_driver_photo_url(app, driver),
                    values=form,
                    preview=_calculate_salary_preview(driver, _default_salary_form(form["salary_month"], driver.get("duty_start"))),
                    salary_rows=db.execute(
                        """
                        SELECT id, entry_date, salary_month, ot_month, salary_mode, prorata_start_date,
                               salary_days, daily_rate, monthly_basic_salary, basic_salary, ot_hours,
                               ot_amount, personal_vehicle, net_salary, remarks
                        FROM salary_store
                        WHERE driver_id = ?
                        ORDER BY salary_month DESC
                        LIMIT 12
                        """,
                        (driver_id,),
                    ).fetchall(),
                    selected_month_label=format_month_label(form["salary_month"]),
                    existing_month=existing_row is not None,
                    timesheet_hours=_timesheet_total_for_month(db, driver_id, form["salary_month"]),
                    salary_mode_options=SALARY_MODE_OPTIONS,
                )
            action = request.form.get("action", "calculate")
            existing_month_row = db.execute(
                "SELECT id FROM salary_store WHERE driver_id = ? AND salary_month = ?",
                (driver_id, form["salary_month"]),
            ).fetchone()
            if action == "save":
                db.execute(
                    """
                    INSERT INTO salary_store (
                        driver_id, entry_date, salary_month, ot_month, salary_mode, prorata_start_date,
                        salary_days, daily_rate, monthly_basic_salary, basic_salary, ot_hours, ot_rate,
                        ot_amount, personal_vehicle, net_salary, remarks
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(driver_id, salary_month) DO UPDATE SET
                        entry_date = excluded.entry_date,
                        ot_month = excluded.ot_month,
                        salary_mode = excluded.salary_mode,
                        prorata_start_date = excluded.prorata_start_date,
                        salary_days = excluded.salary_days,
                        daily_rate = excluded.daily_rate,
                        monthly_basic_salary = excluded.monthly_basic_salary,
                        basic_salary = excluded.basic_salary,
                        ot_hours = excluded.ot_hours,
                        ot_rate = excluded.ot_rate,
                        ot_amount = excluded.ot_amount,
                        personal_vehicle = excluded.personal_vehicle,
                        net_salary = excluded.net_salary,
                        remarks = excluded.remarks
                    """,
                    (
                        driver_id,
                        form["entry_date"],
                        form["salary_month"],
                        preview["ot_month"],
                        preview["salary_mode"],
                        preview["prorata_start_date"] or None,
                        preview["salary_days"],
                        preview["daily_rate"],
                        preview["monthly_basic_salary"],
                        preview["basic_salary"],
                        preview["ot_hours"],
                        preview["ot_rate"],
                        preview["ot_amount"],
                        preview["personal_vehicle"],
                        preview["net_salary"],
                        form["remarks"],
                    ),
                )
                _audit_log(
                    db,
                    "salary_store_saved",
                    entity_type="salary_store",
                    entity_id=f"{driver_id}:{form['salary_month']}",
                    details=f"{preview['salary_mode_label']} / OT month {preview['ot_month']} / net AED {preview['net_salary']:.2f}",
                )
                db.commit()
                _regenerate_kata_for_driver(app, db, driver)
                if existing_month_row:
                    flash("This month already existed. Existing salary record was updated.", "success")
                else:
                    flash("Salary stored successfully.", "success")
                return redirect(url_for("driver_salary_store", driver_id=driver_id, month=form["salary_month"]))

        salary_rows = db.execute(
            """
            SELECT id, entry_date, salary_month, ot_month, salary_mode, prorata_start_date,
                   salary_days, daily_rate, monthly_basic_salary, basic_salary, ot_hours,
                   ot_amount, personal_vehicle, net_salary, remarks
            FROM salary_store
            WHERE driver_id = ?
            ORDER BY salary_month DESC
            LIMIT 12
            """,
            (driver_id,),
        ).fetchall()
        timesheet_hours = _timesheet_total_for_month(db, driver_id, form["salary_month"])

        return render_template(
            "driver_salary_store.html",
            driver=driver,
            photo_url=_driver_photo_url(app, driver),
            values=form,
            preview=preview,
            salary_rows=salary_rows,
            selected_month_label=format_month_label(form["salary_month"]),
            timesheet_hours=timesheet_hours,
            existing_month=existing_row,
            salary_mode_options=SALARY_MODE_OPTIONS,
        )

    @app.post("/drivers/<driver_id>/salary-store/<int:salary_id>/delete")
    @_login_required("admin")
    def delete_salary_store(driver_id: str, salary_id: int):
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for("dashboard"))
        db.execute("DELETE FROM salary_store WHERE id = ? AND driver_id = ?", (salary_id, driver_id))
        db.execute("DELETE FROM salary_slips WHERE salary_store_id = ? AND driver_id = ?", (salary_id, driver_id))
        _audit_log(
            db,
            "salary_store_deleted",
            entity_type="salary_store",
            entity_id=str(salary_id),
            details=driver_id,
        )
        db.commit()
        _regenerate_kata_for_driver(app, db, driver)
        flash("Salary row deleted.", "success")
        return redirect(url_for("driver_salary_store", driver_id=driver_id))

    @app.route("/drivers/<driver_id>/salary-slip", methods=["GET", "POST"])
    @_login_required("admin")
    def driver_salary_slip(driver_id: str):
        _touch_admin_workspace("drivers")
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for("driver_list"))

        salary_rows = db.execute(
            "SELECT * FROM salary_store WHERE driver_id = ? ORDER BY salary_month DESC",
            (driver_id,),
        ).fetchall()
        selected_salary_id = request.args.get("salary_store_id", "").strip()
        if not selected_salary_id and salary_rows:
            selected_salary_id = str(salary_rows[0]["id"])

        selected_salary = None
        existing_slip = None
        advance_summary = _advance_summary(db, driver_id)
        available_advance = advance_summary["remaining_advance"]
        values = {"deduction_amount": "0.00", "payment_source": PAYMENT_SOURCES[0], "paid_by": ""}

        if selected_salary_id:
            selected_salary = db.execute(
                "SELECT * FROM salary_store WHERE id = ? AND driver_id = ?",
                (selected_salary_id, driver_id),
            ).fetchone()
            if selected_salary is not None:
                existing_slip = db.execute(
                    """
                    SELECT * FROM salary_slips
                    WHERE salary_store_id = ? AND driver_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (selected_salary_id, driver_id),
                ).fetchone()
                available_advance = _advance_summary(
                    db,
                    driver_id,
                    exclude_salary_store_id=int(selected_salary_id),
                )["remaining_advance"]
                if existing_slip:
                    values = {
                        "deduction_amount": f"{float(existing_slip['total_deductions']):.2f}",
                        "payment_source": existing_slip["payment_source"] or PAYMENT_SOURCES[0],
                        "paid_by": existing_slip["paid_by"] or "",
                    }

        if request.method == "POST":
            selected_salary_id = request.form.get("salary_store_id", "").strip()
            values = {
                "deduction_amount": request.form.get("deduction_amount", "0").strip() or "0",
                "payment_source": request.form.get("payment_source", PAYMENT_SOURCES[0]).strip() or PAYMENT_SOURCES[0],
                "paid_by": request.form.get("paid_by", "").strip(),
            }
            if not selected_salary_id:
                flash("Select a stored salary month first.", "error")
            else:
                selected_salary = db.execute(
                    "SELECT * FROM salary_store WHERE id = ? AND driver_id = ?",
                    (selected_salary_id, driver_id),
                ).fetchone()
                existing_slip = db.execute(
                    """
                    SELECT * FROM salary_slips
                    WHERE salary_store_id = ? AND driver_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (selected_salary_id, driver_id),
                ).fetchone()
                available_advance = _advance_summary(
                    db,
                    driver_id,
                    exclude_salary_store_id=int(selected_salary_id),
                )["remaining_advance"]
                try:
                    deduction_amount = _parse_decimal(values["deduction_amount"], "Deduction amount", required=False, default=0.0, minimum=0.0)
                except ValidationError as exc:
                    flash(str(exc), "error")
                    deduction_amount = None
                if deduction_amount is None:
                    pass
                elif deduction_amount < 0 or deduction_amount > available_advance + 0.001:
                    flash(f"Deduction amount must be between 0 and {available_advance:,.2f}.", "error")
                elif selected_salary is None:
                    flash("Selected salary record was not found.", "error")
                else:
                    net_payable = float(selected_salary["net_salary"]) - deduction_amount
                    if net_payable < 0:
                        flash("Deduction cannot be greater than the salary amount.", "error")
                    else:
                        slip_payload = {
                            "available_advance": available_advance,
                            "deduction_amount": deduction_amount,
                            "remaining_advance": max(available_advance - deduction_amount, 0),
                            "payment_source": values["payment_source"],
                            "paid_by": values["paid_by"],
                            "net_payable": net_payable,
                        }
                        pdf_path = generate_salary_slip_pdf(
                            driver,
                            selected_salary,
                            slip_payload,
                            str(_driver_output_dir(app, driver_id, driver=driver) / "salary_slips"),
                            app.config["STATIC_ASSETS_DIR"],
                            app.config["GENERATED_DIR"],
                        )
                        relative_path = Path(pdf_path).relative_to(app.config["GENERATED_DIR"]).as_posix()
                        if existing_slip is not None:
                            db.execute(
                                """
                                UPDATE salary_slips
                                SET total_deductions = ?, available_advance = ?, remaining_advance = ?,
                                    payment_source = ?, paid_by = ?, net_payable = ?, pdf_path = ?,
                                    generated_at = CURRENT_TIMESTAMP
                                WHERE id = ? AND driver_id = ?
                                """,
                                (
                                    deduction_amount,
                                    available_advance,
                                    max(available_advance - deduction_amount, 0),
                                    values["payment_source"],
                                    values["paid_by"],
                                    net_payable,
                                    relative_path,
                                    existing_slip["id"],
                                    driver_id,
                                ),
                            )
                            _audit_log(
                                db,
                                "salary_slip_updated",
                                entity_type="salary_slip",
                                entity_id=str(existing_slip["id"]),
                                details=f"{driver_id}:{selected_salary['salary_month']} / net AED {net_payable:.2f}",
                            )
                            success_message = "Salary slip updated and KATA refreshed inside the driver folder."
                        else:
                            db.execute(
                                """
                                INSERT INTO salary_slips (
                                    driver_id, salary_store_id, salary_month, source_filter, total_deductions,
                                    available_advance, remaining_advance, payment_source, paid_by, net_payable, pdf_path
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    driver_id,
                                    selected_salary["id"],
                                    selected_salary["salary_month"],
                                    None,
                                    deduction_amount,
                                    available_advance,
                                    max(available_advance - deduction_amount, 0),
                                    values["payment_source"],
                                    values["paid_by"],
                                    net_payable,
                                    relative_path,
                                ),
                            )
                            _audit_log(
                                db,
                                "salary_slip_generated",
                                entity_type="salary_slip",
                                entity_id=f"{driver_id}:{selected_salary['salary_month']}",
                                details=f"OT month {selected_salary['ot_month'] or _previous_month_value(selected_salary['salary_month'])} / net AED {net_payable:.2f}",
                            )
                            success_message = "Salary slip PDF generated and KATA updated inside the driver folder."
                        db.commit()
                        _regenerate_kata_for_driver(app, db, driver)
                        flash(success_message, "success")
                        return redirect(
                            url_for(
                                "driver_salary_slip",
                                driver_id=driver_id,
                                salary_store_id=selected_salary["id"],
                            )
                        )

        slips = db.execute(
            """
            SELECT id, salary_store_id, salary_month, pdf_path, net_payable, total_deductions,
                   payment_source, paid_by, generated_at
            FROM salary_slips
            WHERE driver_id = ?
            ORDER BY generated_at DESC
            LIMIT 8
            """,
            (driver_id,),
        ).fetchall()
        preview = None
        if selected_salary is not None:
            try:
                deduction_amount = _parse_decimal(values["deduction_amount"], "Deduction amount", required=False, default=0.0, minimum=0.0)
            except ValidationError:
                deduction_amount = None
            if deduction_amount is not None:
                preview = {
                    "gross": float(selected_salary["net_salary"]),
                    "available_advance": available_advance,
                    "deduction_amount": deduction_amount,
                    "remaining_advance": max(available_advance - deduction_amount, 0),
                    "net_payable": float(selected_salary["net_salary"]) - deduction_amount,
                    "ot_month": selected_salary["ot_month"] or _previous_month_value(selected_salary["salary_month"]),
                }
        advance_summary = {
            **advance_summary,
            "remaining_advance": available_advance,
        }

        return render_template(
            "driver_salary_slip.html",
            driver=driver,
            photo_url=_driver_photo_url(app, driver),
            salary_rows=salary_rows,
            selected_salary=selected_salary,
            selected_salary_id=selected_salary_id,
            values=values,
            preview=preview,
            payment_sources=PAYMENT_SOURCES,
            slips=slips,
            existing_slip=existing_slip,
            advance_summary=advance_summary,
        )

    @app.get("/drivers/<driver_id>/kata-pdf")
    @_login_required("admin")
    def driver_kata_pdf(driver_id: str):
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for("dashboard"))
        pdf_path = _regenerate_kata_for_driver(app, db, driver)
        if pdf_path is None:
            flash("No salary or transaction data is available for this driver yet.", "error")
            return redirect(url_for("driver_action", driver_id=driver_id))
        relative_path = Path(pdf_path).relative_to(app.config["GENERATED_DIR"]).as_posix()
        return redirect(url_for("generated_file", filename=relative_path))

    @app.get("/drivers/<driver_id>/timesheet-pdf")
    @_login_required("admin", "driver")
    def driver_timesheet_pdf(driver_id: str):
        if _current_role() == "driver" and _current_driver_id() != driver_id:
            flash("You do not have access to that timesheet.", "error")
            return redirect(url_for("driver_portal"))

        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for(_role_home_endpoint()))

        month_value = _normalize_month(request.args.get("month", "").strip() or _current_month_value())
        month_calendar = _driver_month_calendar(db, driver_id, month_value)
        summary = _timesheet_month_summary(month_calendar)
        output_dir = _driver_output_dir(app, driver_id, driver=driver) / "timesheets"
        pdf_path = generate_timesheet_pdf(
            driver,
            month_value,
            month_calendar,
            summary,
            str(output_dir),
            app.config["STATIC_ASSETS_DIR"],
            app.config["GENERATED_DIR"],
        )
        relative_path = Path(pdf_path).relative_to(app.config["GENERATED_DIR"]).as_posix()
        return redirect(url_for("generated_file", filename=relative_path))

    @app.get("/drivers/<driver_id>/photo")
    @_login_required("admin", "driver")
    def driver_photo(driver_id: str):
        if _current_role() == "driver" and _current_driver_id() != driver_id:
            abort(403)
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            abort(404)

        photo_data = driver["photo_data"] or ""
        if photo_data:
            content_type = driver["photo_content_type"] or "image/jpeg"
            try:
                return send_file(BytesIO(base64.b64decode(photo_data)), mimetype=content_type)
            except Exception:
                pass

        photo_name = driver["photo_name"] or ""
        if photo_name:
            photo_path = Path(app.config["GENERATED_DIR"]) / photo_name
            if photo_path.exists():
                return send_file(photo_path, mimetype=driver["photo_content_type"] or None)
        abort(404)

    @app.get("/generated/<path:filename>")
    @_login_required("admin", "owner", "driver")
    def generated_file(filename: str):
        if not _can_access_generated_file(filename):
            flash("You do not have access to that file.", "error")
            return redirect(url_for(_role_home_endpoint()))
        target = Path(app.config["GENERATED_DIR"]) / filename
        if target.exists():
            return send_file(target, as_attachment=False)

        restored = _restore_generated_file(app, open_db(), filename)
        if restored and Path(restored).exists():
            return send_file(restored, as_attachment=False)

        flash("Requested file is no longer available.", "error")
        return redirect(url_for(_role_home_endpoint()))


def _login_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            role = _current_role()
            if not role:
                flash("Please sign in first.", "error")
                return redirect(url_for("login"))
            if roles and role not in roles:
                flash("You do not have access to that page.", "error")
                return redirect(url_for(_role_home_endpoint()))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def _client_ip() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded_for or request.remote_addr or "unknown"


def _auth_identifier(role: str, phone_number: str = "") -> str:
    if role == "driver":
        normalized_phone = _normalize_phone(phone_number)
        return normalized_phone or _client_ip()
    return _client_ip()


def _verify_env_secret(plain_value: str, hash_value: str, submitted_value: str) -> bool:
    if hash_value:
        return check_password_hash(hash_value, submitted_value)
    return bool(plain_value) and submitted_value == plain_value


def _auth_rate_limit_row(db, role: str, identifier: str):
    return db.execute(
        """
        SELECT role, identifier, failures, blocked_until
        FROM auth_rate_limits
        WHERE role = ? AND identifier = ?
        """,
        (role, identifier),
    ).fetchone()


def _get_login_lock(db, role: str, identifier: str):
    row = _auth_rate_limit_row(db, role, identifier)
    blocked_until = row["blocked_until"] if row and row["blocked_until"] else ""
    if not blocked_until:
        return {"locked": False, "message": ""}
    try:
        blocked_until_dt = datetime.fromisoformat(blocked_until)
    except ValueError:
        return {"locked": False, "message": ""}
    if blocked_until_dt <= datetime.now():
        db.execute(
            "UPDATE auth_rate_limits SET failures = 0, blocked_until = NULL, updated_at = ? WHERE role = ? AND identifier = ?",
            (datetime.now().isoformat(timespec="seconds"), role, identifier),
        )
        db.commit()
        return {"locked": False, "message": ""}
    remaining_minutes = max(1, int((blocked_until_dt - datetime.now()).total_seconds() // 60) + 1)
    return {"locked": True, "message": f"Too many login attempts. Try again in {remaining_minutes} minute(s)."}


def _record_failed_login(db, role: str, identifier: str) -> None:
    if not identifier:
        return
    row = _auth_rate_limit_row(db, role, identifier)
    failures = int(row["failures"]) + 1 if row else 1
    blocked_until = None
    if failures >= int(current_app.config.get("LOGIN_MAX_ATTEMPTS", 5)):
        blocked_until = (datetime.now() + timedelta(minutes=int(current_app.config.get("LOGIN_LOCK_MINUTES", 15)))).isoformat(timespec="seconds")
    if row is None:
        db.execute(
            """
            INSERT INTO auth_rate_limits (role, identifier, failures, blocked_until, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (role, identifier, failures, blocked_until, datetime.now().isoformat(timespec="seconds")),
        )
    else:
        db.execute(
            """
            UPDATE auth_rate_limits
            SET failures = ?, blocked_until = ?, updated_at = ?
            WHERE role = ? AND identifier = ?
            """,
            (failures, blocked_until, datetime.now().isoformat(timespec="seconds"), role, identifier),
        )


def _clear_failed_login(db, role: str, identifier: str) -> None:
    if not identifier:
        return
    db.execute(
        "DELETE FROM auth_rate_limits WHERE role = ? AND identifier = ?",
        (role, identifier),
    )


def _latest_login_error(db, role: str, identifier: str, default_message: str) -> str:
    lock_info = _get_login_lock(db, role, identifier)
    return lock_info["message"] if lock_info["locked"] else default_message


def _audit_log(db, action: str, *, entity_type: str = "", entity_id: str = "", status: str = "success", details: str = "") -> None:
    actor_role = _current_role() or "public"
    actor_name = session.get("display_name", "") or actor_role.title()
    db.execute(
        """
        INSERT INTO audit_logs (actor_role, actor_name, action, entity_type, entity_id, status, details, ip_address)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (actor_role, actor_name, action, entity_type, entity_id, status, details, _client_ip()),
    )


def _set_session(role: str, driver_id: str | None = None, display_name: str = "") -> None:
    session.clear()
    session.permanent = True
    session["role"] = role
    session["display_name"] = display_name
    if role == "admin":
        session["admin_workspace"] = "universal"
    if driver_id:
        session["driver_id"] = driver_id


def _current_role() -> str:
    return session.get("role", "")


def _current_driver_id() -> str:
    return session.get("driver_id", "")


def _role_home_endpoint() -> str:
    role = _current_role()
    if role == "admin":
        return _workspace_home_endpoint(_current_admin_workspace())
    if role == "owner":
        return "owner_fund"
    if role == "driver":
        return "driver_portal"
    return "login"


def _current_admin_workspace() -> str:
    if _current_role() != "admin":
        return ""
    workspace = (session.get("admin_workspace") or "universal").strip().lower()
    if workspace not in ADMIN_WORKSPACE_META:
        workspace = "universal"
    return workspace


def _set_admin_workspace(workspace: str) -> str:
    normalized = (workspace or "universal").strip().lower()
    if normalized not in ADMIN_WORKSPACE_META:
        normalized = "universal"
    session["admin_workspace"] = normalized
    return normalized


def _touch_admin_workspace(workspace: str) -> None:
    if _current_role() == "admin":
        _set_admin_workspace(workspace)


def _workspace_home_endpoint(workspace: str) -> str:
    return {
        "universal": "dashboard",
        "drivers": "driver_list",
        "suppliers": "suppliers",
        "customers": "customers",
        "accounts": "reports_center",
    }.get(workspace, "dashboard")


def _current_workspace_meta() -> dict[str, str]:
    role = _current_role()
    if role == "admin":
        workspace = _current_admin_workspace() or "universal"
        return {"key": workspace, **ADMIN_WORKSPACE_META[workspace]}
    if role == "owner":
        return {
            "key": "owner",
            "label": "Owner",
            "eyebrow": "Owner Workspace",
            "title": "Owner Fund Desk",
            "summary": "Track owner fund movement, support salary payouts and keep monthly backing visible.",
        }
    if role == "driver":
        return {
            "key": "driver",
            "label": "Driver",
            "eyebrow": "Driver Portal",
            "title": "Driver Self Service",
            "summary": "View salary, slips, transaction history, timesheet activity and assigned vehicle from one place.",
        }
    return {
        "key": "public",
        "label": "Portal",
        "eyebrow": "Current Link",
        "title": "Portal Access",
        "summary": "Open the right workspace and move fast without mixing payroll, supplier and customer operations.",
    }


def _admin_workspace_links():
    return [
        {
            "key": workspace,
            "label": ADMIN_WORKSPACE_META[workspace]["label"],
            "url": url_for("switch_workspace", workspace_key=workspace),
        }
        for workspace in ADMIN_WORKSPACE_ORDER
    ]


def _admin_module_links(workspace: str):
    workspace_key = workspace or "universal"
    module_map = {
        "universal": [],
        "drivers": [
            {"label": "Add Driver", "endpoint": "create_driver", "primary": True},
        ],
        "suppliers": [
            {"label": "Invoices", "endpoint": "invoice_center"},
        ],
        "customers": [
            {"label": "Invoices", "endpoint": "invoice_center", "primary": True},
        ],
        "accounts": [
            {"label": "Owner Fund", "endpoint": "owner_fund", "primary": True},
            {"label": "Tax", "endpoint": "tax_center"},
        ],
    }
    return [
        {
            **item,
            "url": url_for(item["endpoint"]),
        }
        for item in module_map.get(workspace_key, module_map["universal"])
    ]


def _find_driver_by_phone(db, phone_number: str):
    if not phone_number:
        return None
    drivers = db.execute(
        """
        SELECT driver_id, full_name, phone_number, pin_hash, status
        FROM drivers
        WHERE phone_number IS NOT NULL AND TRIM(phone_number) != ''
        ORDER BY full_name ASC
        """
    ).fetchall()
    for driver in drivers:
        if (driver["status"] or "").lower() != "active":
            continue
        if _normalize_phone(driver["phone_number"]) == phone_number:
            return driver
    return None


def _normalize_phone(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _fetch_driver(db, driver_id: str):
    return db.execute(
        """
        SELECT driver_id, full_name, phone_number, vehicle_no, shift, vehicle_type,
               basic_salary, ot_rate, duty_start, photo_name, photo_data, photo_content_type, pin_hash, status, remarks
        FROM drivers
        WHERE driver_id = ?
        """,
        (driver_id,),
    ).fetchone()


def _driver_filter_clause(query: str, status_filter: str = "", shift_filter: str = "", vehicle_filter: str = ""):
    filters = []
    params = []
    if query:
        needle = f"%{query}%"
        filters.append("(driver_id LIKE ? OR full_name LIKE ? OR vehicle_no LIKE ? OR phone_number LIKE ?)")
        params.extend([needle, needle, needle, needle])
    if status_filter:
        filters.append("status = ?")
        params.append(status_filter)
    if shift_filter:
        filters.append("shift = ?")
        params.append(shift_filter)
    if vehicle_filter:
        filters.append("vehicle_type = ?")
        params.append(vehicle_filter)
    if not filters:
        return "", []
    return "WHERE " + " AND ".join(filters), params


def _driver_filter_options(db):
    shifts = [
        row["shift"]
        for row in db.execute("SELECT DISTINCT shift FROM drivers WHERE TRIM(shift) != '' ORDER BY shift ASC").fetchall()
    ]
    vehicle_types = [
        row["vehicle_type"]
        for row in db.execute(
            "SELECT DISTINCT vehicle_type FROM drivers WHERE TRIM(vehicle_type) != '' ORDER BY vehicle_type ASC"
        ).fetchall()
    ]
    return {"shifts": shifts, "vehicle_types": vehicle_types}


def _party_filter_clause(query: str, status_filter: str = "", role_filter: str = "", kind_filter: str = ""):
    filters = []
    params = []
    if query:
        needle = f"%{query}%"
        filters.append(
            "(party_code LIKE ? OR party_name LIKE ? OR contact_person LIKE ? OR phone_number LIKE ? OR email LIKE ?)"
        )
        params.extend([needle, needle, needle, needle, needle])
    if status_filter:
        filters.append("status = ?")
        params.append(status_filter)
    if role_filter:
        filters.append("party_roles LIKE ?")
        params.append(f"%{role_filter}%")
    if kind_filter:
        filters.append("party_kind = ?")
        params.append(kind_filter)
    if not filters:
        return "", []
    return "WHERE " + " AND ".join(filters), params


def _default_party_form():
    return {
        "party_code": "",
        "party_name": "",
        "party_kind": "Company",
        "party_roles": [],
        "contact_person": "",
        "phone_number": "",
        "email": "",
        "trn_no": "",
        "trade_license_no": "",
        "address": "",
        "notes": "",
        "status": "Active",
    }


def _party_form_data(request):
    return {
        "party_code": request.form.get("party_code", "").strip().upper(),
        "party_name": request.form.get("party_name", "").strip(),
        "party_kind": request.form.get("party_kind", "Company").strip() or "Company",
        "party_roles": request.form.getlist("party_roles"),
        "contact_person": request.form.get("contact_person", "").strip(),
        "phone_number": request.form.get("phone_number", "").strip(),
        "email": request.form.get("email", "").strip(),
        "trn_no": request.form.get("trn_no", "").strip(),
        "trade_license_no": request.form.get("trade_license_no", "").strip(),
        "address": request.form.get("address", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "status": request.form.get("status", "Active").strip() or "Active",
    }


def _normalize_party_roles(values) -> list[str]:
    selected = []
    for role in PARTY_ROLE_OPTIONS:
        if role in values and role not in selected:
            selected.append(role)
    if not selected:
        raise ValidationError("Select at least one party role.")
    return selected


def _serialize_party_roles(values) -> str:
    return ", ".join(values)


def _deserialize_party_roles(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _normalize_optional_phone(value: str) -> str:
    if not (value or "").strip():
        return ""
    normalized = _normalize_phone(value)
    if len(normalized) < 7:
        raise ValidationError("Phone number must contain at least 7 digits.")
    return normalized


def _validate_optional_email(value: str) -> None:
    if value and "@" not in value:
        raise ValidationError("Email address must be valid.")


def _fetch_party(db, party_code: str):
    return db.execute(
        """
        SELECT
            party_code, party_name, party_kind, party_roles, contact_person,
            phone_number, email, trn_no, trade_license_no, address, notes, status, created_at
        FROM parties
        WHERE party_code = ?
        """,
        (party_code,),
    ).fetchone()


def _party_values_from_record(record):
    values = dict(record)
    values["party_roles"] = _deserialize_party_roles(record["party_roles"] or "")
    return values


def _next_party_code(db) -> str:
    rows = db.execute("SELECT party_code FROM parties WHERE party_code LIKE ? ORDER BY party_code ASC", ("PTY-%",)).fetchall()
    max_number = 0
    for row in rows:
        code = (row["party_code"] or "").strip().upper()
        if not code.startswith("PTY-"):
            continue
        try:
            max_number = max(max_number, int(code.split("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"PTY-{max_number + 1:04d}"


def _preview_next_party_code() -> str:
    try:
        return _next_party_code(open_db())
    except Exception:
        return "PTY-0001"



def _parties_by_role(db, role: str):
    return db.execute(
        """
        SELECT
            party_code, party_name, party_kind, party_roles, contact_person,
            phone_number, email, trn_no, trade_license_no, address, notes, status, created_at
        FROM parties
        WHERE party_roles LIKE ?
        ORDER BY CASE WHEN status = 'Active' THEN 0 ELSE 1 END, party_name ASC
        """,
        (f"%{role}%",),
    ).fetchall()


def _contract_parties(db):
    return db.execute(
        """
        SELECT
            party_code, party_name, party_kind, party_roles, contact_person,
            phone_number, email, trn_no, trade_license_no, address, notes, status, created_at
        FROM parties
        WHERE party_roles LIKE ? OR party_roles LIKE ?
        ORDER BY CASE WHEN status = 'Active' THEN 0 ELSE 1 END, party_name ASC
        """,
        ("%Supplier%", "%Customer%"),
    ).fetchall()


def _next_reference_code(db, table_name: str, field_name: str, prefix: str) -> str:
    rows = db.execute(f"SELECT {field_name} FROM {table_name} WHERE {field_name} LIKE ? ORDER BY {field_name} ASC", (f"{prefix}-%",)).fetchall()
    max_number = 0
    for row in rows:
        code = (row[field_name] or "").strip().upper()
        if not code.startswith(f"{prefix}-"):
            continue
        try:
            max_number = max(max_number, int(code.split("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefix}-{max_number + 1:04d}"


def _company_profile_row(db):
    return db.execute(
        """
        SELECT
            company_name, legal_name, trade_license_no, trade_license_expiry, trn_no,
            vat_status, address, phone_number, email, bank_name, bank_account_name,
            bank_account_number, iban, swift_code, invoice_terms, base_currency,
            financial_year_label, financial_year_start, financial_year_end
        FROM company_profile
        ORDER BY id ASC
        LIMIT 1
        """
    ).fetchone()


def _default_company_profile():
    return {
        "company_name": "",
        "legal_name": "",
        "trade_license_no": "",
        "trade_license_expiry": "",
        "trn_no": "",
        "vat_status": VAT_STATUS_OPTIONS[0],
        "address": "",
        "phone_number": "",
        "email": "",
        "bank_name": "",
        "bank_account_name": "",
        "bank_account_number": "",
        "iban": "",
        "swift_code": "",
        "invoice_terms": "30 Days",
        "base_currency": "AED",
        "financial_year_label": "",
        "financial_year_start": "",
        "financial_year_end": "",
    }


def _company_profile_values(db):
    row = _company_profile_row(db)
    if row is None:
        return _default_company_profile()
    values = _default_company_profile()
    values.update(dict(row))
    return values


def _company_profile_form_data(request):
    return {
        "company_name": request.form.get("company_name", "").strip(),
        "legal_name": request.form.get("legal_name", "").strip(),
        "trade_license_no": request.form.get("trade_license_no", "").strip(),
        "trade_license_expiry": request.form.get("trade_license_expiry", "").strip(),
        "trn_no": request.form.get("trn_no", "").strip(),
        "vat_status": request.form.get("vat_status", VAT_STATUS_OPTIONS[0]).strip() or VAT_STATUS_OPTIONS[0],
        "address": request.form.get("address", "").strip(),
        "phone_number": request.form.get("phone_number", "").strip(),
        "email": request.form.get("email", "").strip(),
        "bank_name": request.form.get("bank_name", "").strip(),
        "bank_account_name": request.form.get("bank_account_name", "").strip(),
        "bank_account_number": request.form.get("bank_account_number", "").strip(),
        "iban": request.form.get("iban", "").strip(),
        "swift_code": request.form.get("swift_code", "").strip(),
        "invoice_terms": request.form.get("invoice_terms", "").strip(),
        "base_currency": request.form.get("base_currency", "AED").strip().upper() or "AED",
        "financial_year_label": request.form.get("financial_year_label", "").strip(),
        "financial_year_start": request.form.get("financial_year_start", "").strip(),
        "financial_year_end": request.form.get("financial_year_end", "").strip(),
    }


def _prepare_company_profile_payload(values):
    if not values["company_name"]:
        raise ValidationError("Company name is required.")
    values["phone_number"] = _normalize_optional_phone(values["phone_number"])
    _validate_optional_email(values["email"])
    values["trade_license_expiry"] = _validate_date_text(values["trade_license_expiry"], "Trade license expiry", required=False)
    values["financial_year_start"] = _validate_date_text(values["financial_year_start"], "Financial year start", required=False)
    values["financial_year_end"] = _validate_date_text(values["financial_year_end"], "Financial year end", required=False)
    if values["financial_year_start"] and values["financial_year_end"] and values["financial_year_start"] > values["financial_year_end"]:
        raise ValidationError("Financial year end must be after the start date.")
    return (
        values["company_name"],
        values["legal_name"],
        values["trade_license_no"],
        values["trade_license_expiry"] or None,
        values["trn_no"],
        values["vat_status"],
        values["address"],
        values["phone_number"],
        values["email"],
        values["bank_name"],
        values["bank_account_name"],
        values["bank_account_number"],
        values["iban"],
        values["swift_code"],
        values["invoice_terms"],
        values["base_currency"],
        values["financial_year_label"],
        values["financial_year_start"] or None,
        values["financial_year_end"] or None,
    )


def _default_branch_form(db=None):
    db = db or open_db()
    return {
        "original_branch_code": "",
        "branch_code": _next_reference_code(db, "branches", "branch_code", "BR"),
        "branch_name": "",
        "address": "",
        "contact_person": "",
        "phone_number": "",
        "email": "",
        "status": BRANCH_STATUS_OPTIONS[0],
    }


def _branch_form_data(request):
    return {
        "original_branch_code": request.form.get("original_branch_code", "").strip().upper(),
        "branch_code": request.form.get("branch_code", "").strip().upper(),
        "branch_name": request.form.get("branch_name", "").strip(),
        "address": request.form.get("address", "").strip(),
        "contact_person": request.form.get("contact_person", "").strip(),
        "phone_number": request.form.get("phone_number", "").strip(),
        "email": request.form.get("email", "").strip(),
        "status": request.form.get("status", BRANCH_STATUS_OPTIONS[0]).strip() or BRANCH_STATUS_OPTIONS[0],
    }


def _branch_form_from_row(row):
    values = dict(row)
    values["original_branch_code"] = row["branch_code"]
    return values


def _prepare_branch_payload(db, values):
    if not values["branch_code"]:
        values["branch_code"] = _next_reference_code(db, "branches", "branch_code", "BR")
    if not values["branch_name"]:
        raise ValidationError("Branch name is required.")
    values["phone_number"] = _normalize_optional_phone(values["phone_number"])
    _validate_optional_email(values["email"])
    return (
        values["branch_code"],
        values["branch_name"],
        values["address"],
        values["contact_person"],
        values["phone_number"],
        values["email"],
        values["status"],
    )


def _default_currency_form(db=None):
    return {
        "original_currency_code": "",
        "currency_code": "",
        "currency_name": "",
        "symbol": "",
        "exchange_rate": "1",
        "is_base": True,
        "status": BRANCH_STATUS_OPTIONS[0],
    }


def _currency_form_data(request):
    return {
        "original_currency_code": request.form.get("original_currency_code", "").strip().upper(),
        "currency_code": request.form.get("currency_code", "").strip().upper(),
        "currency_name": request.form.get("currency_name", "").strip(),
        "symbol": request.form.get("symbol", "").strip(),
        "exchange_rate": request.form.get("exchange_rate", "").strip(),
        "is_base": request.form.get("is_base", "") == "1",
        "status": request.form.get("status", BRANCH_STATUS_OPTIONS[0]).strip() or BRANCH_STATUS_OPTIONS[0],
    }


def _currency_form_from_row(row):
    values = dict(row)
    values["original_currency_code"] = row["currency_code"]
    values["exchange_rate"] = str(row["exchange_rate"])
    values["is_base"] = bool(row["is_base"])
    return values


def _prepare_currency_payload(db, values):
    if not values["currency_code"]:
        raise ValidationError("Currency code is required.")
    if not values["currency_name"]:
        raise ValidationError("Currency name is required.")
    exchange_rate = _parse_decimal(values["exchange_rate"], "Exchange rate", required=False, default=1.0, minimum=0.000001)
    return (
        values["currency_code"],
        values["currency_name"],
        values["symbol"],
        exchange_rate,
        1 if values["is_base"] else 0,
        values["status"],
    )


def _default_financial_year_form(db=None):
    db = db or open_db()
    return {
        "original_year_code": "",
        "year_code": _next_reference_code(db, "financial_years", "year_code", "FY"),
        "year_label": "",
        "start_date": "",
        "end_date": "",
        "is_current": True,
        "status": FINANCIAL_YEAR_STATUS_OPTIONS[0],
    }


def _financial_year_form_data(request):
    return {
        "original_year_code": request.form.get("original_year_code", "").strip().upper(),
        "year_code": request.form.get("year_code", "").strip().upper(),
        "year_label": request.form.get("year_label", "").strip(),
        "start_date": request.form.get("start_date", "").strip(),
        "end_date": request.form.get("end_date", "").strip(),
        "is_current": request.form.get("is_current", "") == "1",
        "status": request.form.get("status", FINANCIAL_YEAR_STATUS_OPTIONS[0]).strip() or FINANCIAL_YEAR_STATUS_OPTIONS[0],
    }


def _financial_year_form_from_row(row):
    values = dict(row)
    values["original_year_code"] = row["year_code"]
    values["is_current"] = bool(row["is_current"])
    return values


def _prepare_financial_year_payload(db, values):
    if not values["year_code"]:
        values["year_code"] = _next_reference_code(db, "financial_years", "year_code", "FY")
    if not values["year_label"]:
        raise ValidationError("Financial year label is required.")
    start_date = _validate_date_text(values["start_date"], "Financial year start")
    end_date = _validate_date_text(values["end_date"], "Financial year end")
    if start_date > end_date:
        raise ValidationError("Financial year end must be after the start date.")
    return (
        values["year_code"],
        values["year_label"],
        start_date,
        end_date,
        1 if values["is_current"] else 0,
        values["status"],
    )


def _branch_rows(db):
    return db.execute(
        """
        SELECT branch_code, branch_name, address, contact_person, phone_number, email, status, created_at
        FROM branches
        ORDER BY CASE WHEN status = 'Active' THEN 0 ELSE 1 END, branch_name ASC
        """
    ).fetchall()


def _currency_rows(db):
    return db.execute(
        """
        SELECT currency_code, currency_name, symbol, exchange_rate, is_base, status, created_at
        FROM company_currencies
        ORDER BY is_base DESC, currency_code ASC
        """
    ).fetchall()


def _financial_year_rows(db):
    return db.execute(
        """
        SELECT year_code, year_label, start_date, end_date, is_current, status, created_at
        FROM financial_years
        ORDER BY is_current DESC, start_date DESC, year_label ASC
        """
    ).fetchall()


def _company_setup_summary(db):
    profile = _company_profile_row(db)
    return {
        "company_ready": 1 if profile is not None else 0,
        "branch_count": int(db.execute("SELECT COUNT(*) FROM branches").fetchone()[0]),
        "currency_count": int(db.execute("SELECT COUNT(*) FROM company_currencies").fetchone()[0]),
        "financial_year_count": int(db.execute("SELECT COUNT(*) FROM financial_years").fetchone()[0]),
    }


def _default_agreement_form(db=None):
    db = db or open_db()
    return {
        "original_agreement_no": "",
        "agreement_no": _next_reference_code(db, "agreements", "agreement_no", "AGR"),
        "party_code": "",
        "agreement_kind": AGREEMENT_KIND_OPTIONS[0],
        "start_date": date.today().isoformat(),
        "end_date": "",
        "rate_type": RATE_TYPE_OPTIONS[0],
        "amount": "",
        "tax_percent": "5",
        "scope": "",
        "notes": "",
        "status": "Active",
    }


def _default_lpo_form(db=None):
    db = db or open_db()
    return {
        "original_lpo_no": "",
        "lpo_no": _next_reference_code(db, "lpos", "lpo_no", "LPO"),
        "party_code": "",
        "agreement_no": "",
        "issue_date": date.today().isoformat(),
        "valid_until": "",
        "amount": "",
        "tax_percent": "5",
        "description": "",
        "status": "Open",
    }


def _default_hire_form(db=None):
    db = db or open_db()
    return {
        "original_hire_no": "",
        "hire_no": _next_reference_code(db, "hire_records", "hire_no", "HIR"),
        "party_code": "",
        "agreement_no": "",
        "lpo_no": "",
        "entry_date": date.today().isoformat(),
        "direction": HIRE_DIRECTION_OPTIONS[0],
        "asset_name": "",
        "asset_type": "",
        "unit_type": UNIT_TYPE_OPTIONS[0],
        "quantity": "1",
        "rate": "",
        "tax_percent": "5",
        "status": "Open",
        "notes": "",
    }


def _default_invoice_form(db=None):
    db = db or open_db()
    return {
        "original_invoice_no": "",
        "invoice_no": _next_reference_code(db, "account_invoices", "invoice_no", "INV"),
        "party_code": "",
        "agreement_no": "",
        "lpo_no": "",
        "hire_no": "",
        "invoice_kind": INVOICE_KIND_OPTIONS[0],
        "document_type": INVOICE_DOCUMENT_OPTIONS[0],
        "issue_date": date.today().isoformat(),
        "due_date": "",
        "subtotal": "",
        "tax_percent": "5",
        "notes": "",
    }


def _default_payment_form(db=None):
    db = db or open_db()
    return {
        "original_voucher_no": "",
        "voucher_no": _next_reference_code(db, "account_payments", "voucher_no", "PAY"),
        "invoice_no": "",
        "entry_date": date.today().isoformat(),
        "amount": "",
        "payment_method": PAYMENT_METHOD_OPTIONS[0],
        "reference": "",
        "notes": "",
    }


def _default_invoice_lines():
    return [
        {
            "line_no": index,
            "description": "",
            "quantity": "1" if index == 1 else "",
            "unit_label": "",
            "rate": "",
            "subtotal": "",
        }
        for index in range(1, INVOICE_LINE_SLOTS + 1)
    ]


def _default_loan_form(db=None):
    db = db or open_db()
    return {
        "original_loan_no": "",
        "loan_no": _next_reference_code(db, "loan_entries", "loan_no", "LOAN"),
        "party_code": "",
        "entry_date": date.today().isoformat(),
        "loan_type": LOAN_TYPE_OPTIONS[0],
        "amount": "",
        "payment_method": PAYMENT_METHOD_OPTIONS[1],
        "reference": "",
        "notes": "",
    }


def _default_fee_form(db=None):
    db = db or open_db()
    return {
        "original_fee_no": "",
        "fee_no": _next_reference_code(db, "annual_fee_entries", "fee_no", "FEE"),
        "party_code": "",
        "fee_type": FEE_TYPE_OPTIONS[0],
        "description": "",
        "vehicle_no": "",
        "due_date": date.today().isoformat(),
        "annual_amount": "",
        "received_amount": "0",
        "status": "Due",
        "notes": "",
    }


def _agreement_form_data(request):
    return {
        "original_agreement_no": request.form.get("original_agreement_no", "").strip().upper(),
        "agreement_no": request.form.get("agreement_no", "").strip().upper(),
        "party_code": request.form.get("party_code", "").strip().upper(),
        "agreement_kind": request.form.get("agreement_kind", AGREEMENT_KIND_OPTIONS[0]).strip() or AGREEMENT_KIND_OPTIONS[0],
        "start_date": request.form.get("start_date", "").strip(),
        "end_date": request.form.get("end_date", "").strip(),
        "rate_type": request.form.get("rate_type", RATE_TYPE_OPTIONS[0]).strip() or RATE_TYPE_OPTIONS[0],
        "amount": request.form.get("amount", "").strip(),
        "tax_percent": request.form.get("tax_percent", "0").strip() or "0",
        "scope": request.form.get("scope", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "status": request.form.get("status", "Active").strip() or "Active",
    }


def _lpo_form_data(request):
    return {
        "original_lpo_no": request.form.get("original_lpo_no", "").strip().upper(),
        "lpo_no": request.form.get("lpo_no", "").strip().upper(),
        "party_code": request.form.get("party_code", "").strip().upper(),
        "agreement_no": request.form.get("agreement_no", "").strip().upper(),
        "issue_date": request.form.get("issue_date", "").strip(),
        "valid_until": request.form.get("valid_until", "").strip(),
        "amount": request.form.get("amount", "").strip(),
        "tax_percent": request.form.get("tax_percent", "0").strip() or "0",
        "description": request.form.get("description", "").strip(),
        "status": request.form.get("status", "Open").strip() or "Open",
    }


def _hire_form_data(request):
    return {
        "original_hire_no": request.form.get("original_hire_no", "").strip().upper(),
        "hire_no": request.form.get("hire_no", "").strip().upper(),
        "party_code": request.form.get("party_code", "").strip().upper(),
        "agreement_no": request.form.get("agreement_no", "").strip().upper(),
        "lpo_no": request.form.get("lpo_no", "").strip().upper(),
        "entry_date": request.form.get("entry_date", "").strip(),
        "direction": request.form.get("direction", HIRE_DIRECTION_OPTIONS[0]).strip() or HIRE_DIRECTION_OPTIONS[0],
        "asset_name": request.form.get("asset_name", "").strip(),
        "asset_type": request.form.get("asset_type", "").strip(),
        "unit_type": request.form.get("unit_type", UNIT_TYPE_OPTIONS[0]).strip() or UNIT_TYPE_OPTIONS[0],
        "quantity": request.form.get("quantity", "1").strip() or "1",
        "rate": request.form.get("rate", "").strip(),
        "tax_percent": request.form.get("tax_percent", "0").strip() or "0",
        "status": request.form.get("status", "Open").strip() or "Open",
        "notes": request.form.get("notes", "").strip(),
    }


def _invoice_form_data(request):
    return {
        "original_invoice_no": request.form.get("original_invoice_no", "").strip().upper(),
        "invoice_no": request.form.get("invoice_no", "").strip().upper(),
        "party_code": request.form.get("party_code", "").strip().upper(),
        "agreement_no": request.form.get("agreement_no", "").strip().upper(),
        "lpo_no": request.form.get("lpo_no", "").strip().upper(),
        "hire_no": request.form.get("hire_no", "").strip().upper(),
        "invoice_kind": request.form.get("invoice_kind", INVOICE_KIND_OPTIONS[0]).strip() or INVOICE_KIND_OPTIONS[0],
        "document_type": request.form.get("document_type", INVOICE_DOCUMENT_OPTIONS[0]).strip() or INVOICE_DOCUMENT_OPTIONS[0],
        "issue_date": request.form.get("issue_date", "").strip(),
        "due_date": request.form.get("due_date", "").strip(),
        "subtotal": request.form.get("subtotal", "").strip(),
        "tax_percent": request.form.get("tax_percent", "0").strip() or "0",
        "notes": request.form.get("notes", "").strip(),
    }


def _invoice_line_form_data(request):
    rows = []
    for index in range(1, INVOICE_LINE_SLOTS + 1):
        quantity_raw = request.form.get(f"line_quantity_{index}", "").strip()
        rate_raw = request.form.get(f"line_rate_{index}", "").strip()
        subtotal_raw = request.form.get(f"line_subtotal_{index}", "").strip()
        rows.append(
            {
                "line_no": index,
                "description": request.form.get(f"line_description_{index}", "").strip(),
                "quantity": quantity_raw or ("1" if index == 1 else ""),
                "unit_label": request.form.get(f"line_unit_{index}", "").strip(),
                "rate": rate_raw,
                "subtotal": subtotal_raw,
            }
        )
    return rows


def _payment_form_data(request):
    return {
        "original_voucher_no": request.form.get("original_voucher_no", "").strip().upper(),
        "voucher_no": request.form.get("voucher_no", "").strip().upper(),
        "invoice_no": request.form.get("invoice_no", "").strip().upper(),
        "entry_date": request.form.get("entry_date", "").strip(),
        "amount": request.form.get("amount", "").strip(),
        "payment_method": request.form.get("payment_method", PAYMENT_METHOD_OPTIONS[0]).strip() or PAYMENT_METHOD_OPTIONS[0],
        "reference": request.form.get("reference", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }


def _loan_form_data(request):
    return {
        "original_loan_no": request.form.get("original_loan_no", "").strip().upper(),
        "loan_no": request.form.get("loan_no", "").strip().upper(),
        "party_code": request.form.get("party_code", "").strip().upper(),
        "entry_date": request.form.get("entry_date", "").strip(),
        "loan_type": request.form.get("loan_type", LOAN_TYPE_OPTIONS[0]).strip() or LOAN_TYPE_OPTIONS[0],
        "amount": request.form.get("amount", "").strip(),
        "payment_method": request.form.get("payment_method", PAYMENT_METHOD_OPTIONS[1]).strip() or PAYMENT_METHOD_OPTIONS[1],
        "reference": request.form.get("reference", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }


def _fee_form_data(request):
    return {
        "original_fee_no": request.form.get("original_fee_no", "").strip().upper(),
        "fee_no": request.form.get("fee_no", "").strip().upper(),
        "party_code": request.form.get("party_code", "").strip().upper(),
        "fee_type": request.form.get("fee_type", FEE_TYPE_OPTIONS[0]).strip() or FEE_TYPE_OPTIONS[0],
        "description": request.form.get("description", "").strip(),
        "vehicle_no": request.form.get("vehicle_no", "").strip(),
        "due_date": request.form.get("due_date", "").strip(),
        "annual_amount": request.form.get("annual_amount", "").strip(),
        "received_amount": request.form.get("received_amount", "0").strip() or "0",
        "status": request.form.get("status", "Due").strip() or "Due",
        "notes": request.form.get("notes", "").strip(),
    }


def _validate_date_text(value: str, field_name: str, *, required: bool = True) -> str:
    text = (value or "").strip()
    if not text:
        if required:
            raise ValidationError(f"{field_name} is required.")
        return ""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be a valid date.") from exc


def _validate_party_reference(db, party_code: str):
    if not party_code:
        raise ValidationError("Select a party first.")
    party = _fetch_party(db, party_code)
    if party is None:
        raise ValidationError("Selected party was not found.")
    return party


def _optional_reference_exists(db, table_name: str, field_name: str, value: str, label: str) -> str:
    code = (value or "").strip().upper()
    if not code:
        return ""
    row = db.execute(f"SELECT {field_name} FROM {table_name} WHERE {field_name} = ?", (code,)).fetchone()
    if row is None:
        raise ValidationError(f"{label} was not found.")
    return code


def _display_number(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _agreement_form_from_row(row):
    values = _default_agreement_form()
    values.update(
        {
            "original_agreement_no": row["agreement_no"],
            "agreement_no": row["agreement_no"],
            "party_code": row["party_code"] or "",
            "agreement_kind": row["agreement_kind"] or AGREEMENT_KIND_OPTIONS[0],
            "start_date": row["start_date"] or "",
            "end_date": row["end_date"] or "",
            "rate_type": row["rate_type"] or RATE_TYPE_OPTIONS[0],
            "amount": _display_number(row["amount"]),
            "tax_percent": _display_number(row["tax_percent"]),
            "scope": row["scope"] or "",
            "notes": row["notes"] or "",
            "status": row["status"] or "Active",
        }
    )
    return values


def _lpo_form_from_row(row):
    values = _default_lpo_form()
    values.update(
        {
            "original_lpo_no": row["lpo_no"],
            "lpo_no": row["lpo_no"],
            "party_code": row["party_code"] or "",
            "agreement_no": row["agreement_no"] or "",
            "issue_date": row["issue_date"] or "",
            "valid_until": row["valid_until"] or "",
            "amount": _display_number(row["amount"]),
            "tax_percent": _display_number(row["tax_percent"]),
            "description": row["description"] or "",
            "status": row["status"] or "Open",
        }
    )
    return values


def _hire_form_from_row(row):
    values = _default_hire_form()
    values.update(
        {
            "original_hire_no": row["hire_no"],
            "hire_no": row["hire_no"],
            "party_code": row["party_code"] or "",
            "agreement_no": row["agreement_no"] or "",
            "lpo_no": row["lpo_no"] or "",
            "entry_date": row["entry_date"] or "",
            "direction": row["direction"] or HIRE_DIRECTION_OPTIONS[0],
            "asset_name": row["asset_name"] or "",
            "asset_type": row["asset_type"] or "",
            "unit_type": row["unit_type"] or UNIT_TYPE_OPTIONS[0],
            "quantity": _display_number(row["quantity"]),
            "rate": _display_number(row["rate"]),
            "tax_percent": _display_number(row["tax_percent"]),
            "status": row["status"] or "Open",
            "notes": row["notes"] or "",
        }
    )
    return values


def _invoice_form_from_row(row):
    values = _default_invoice_form()
    values.update(
        {
            "original_invoice_no": row["invoice_no"],
            "invoice_no": row["invoice_no"],
            "party_code": row["party_code"] or "",
            "agreement_no": row["agreement_no"] or "",
            "lpo_no": row["lpo_no"] or "",
            "hire_no": row["hire_no"] or "",
            "invoice_kind": row["invoice_kind"] or INVOICE_KIND_OPTIONS[0],
            "document_type": row["document_type"] or (INVOICE_DOCUMENT_OPTIONS[0] if (row["invoice_kind"] or INVOICE_KIND_OPTIONS[0]) == "Sales" else "Supplier Bill"),
            "issue_date": row["issue_date"] or "",
            "due_date": row["due_date"] or "",
            "subtotal": _display_number(row["subtotal"]),
            "tax_percent": _display_number(row["tax_percent"]),
            "notes": row["notes"] or "",
        }
    )
    return values


def _invoice_line_rows_for_form(db, invoice_no: str, invoice_values=None):
    rows = db.execute(
        """
        SELECT line_no, description, quantity, unit_label, rate, subtotal
        FROM account_invoice_lines
        WHERE invoice_no = ?
        ORDER BY line_no ASC, id ASC
        """,
        (invoice_no,),
    ).fetchall()
    if rows:
        line_rows = []
        for index, row in enumerate(rows[:INVOICE_LINE_SLOTS], start=1):
            line_rows.append(
                {
                    "line_no": index,
                    "description": row["description"] or "",
                    "quantity": _display_number(row["quantity"]),
                    "unit_label": row["unit_label"] or "",
                    "rate": _display_number(row["rate"]),
                    "subtotal": _display_number(row["subtotal"]),
                }
            )
        while len(line_rows) < INVOICE_LINE_SLOTS:
            line_rows.append(_default_invoice_lines()[len(line_rows)])
        return line_rows

    invoice_values = invoice_values or {}
    hire_no = invoice_values.get("hire_no", "")
    if hire_no:
        hire_row = db.execute(
            """
            SELECT asset_name, unit_type, quantity, rate, subtotal
            FROM hire_records
            WHERE hire_no = ?
            """,
            (hire_no,),
        ).fetchone()
        if hire_row is not None:
            line_rows = _default_invoice_lines()
            line_rows[0].update(
                {
                    "description": hire_row["asset_name"] or "",
                    "quantity": _display_number(hire_row["quantity"]),
                    "unit_label": hire_row["unit_type"] or "",
                    "rate": _display_number(hire_row["rate"]),
                    "subtotal": _display_number(hire_row["subtotal"]),
                }
            )
            return line_rows

    return _default_invoice_lines()


def _payment_form_from_row(row):
    values = _default_payment_form()
    values.update(
        {
            "original_voucher_no": row["voucher_no"],
            "voucher_no": row["voucher_no"],
            "invoice_no": row["invoice_no"] or "",
            "entry_date": row["entry_date"] or "",
            "amount": _display_number(row["amount"]),
            "payment_method": row["payment_method"] or PAYMENT_METHOD_OPTIONS[0],
            "reference": row["reference"] or "",
            "notes": row["notes"] or "",
        }
    )
    return values


def _loan_form_from_row(row):
    values = _default_loan_form()
    values.update(
        {
            "original_loan_no": row["loan_no"],
            "loan_no": row["loan_no"],
            "party_code": row["party_code"] or "",
            "entry_date": row["entry_date"] or "",
            "loan_type": row["loan_type"] or LOAN_TYPE_OPTIONS[0],
            "amount": _display_number(row["amount"]),
            "payment_method": row["payment_method"] or PAYMENT_METHOD_OPTIONS[1],
            "reference": row["reference"] or "",
            "notes": row["notes"] or "",
        }
    )
    return values


def _fee_form_from_row(row):
    values = _default_fee_form()
    values.update(
        {
            "original_fee_no": row["fee_no"],
            "fee_no": row["fee_no"],
            "party_code": row["party_code"] or "",
            "fee_type": row["fee_type"] or FEE_TYPE_OPTIONS[0],
            "description": row["description"] or "",
            "vehicle_no": row["vehicle_no"] or "",
            "due_date": row["due_date"] or "",
            "annual_amount": _display_number(row["annual_amount"]),
            "received_amount": _display_number(row["received_amount"]),
            "status": row["status"] or "Due",
            "notes": row["notes"] or "",
        }
    )
    return values


def _ensure_reference_available(db, table_name: str, field_name: str, new_value: str, original_value: str, label: str):
    new_code = (new_value or "").strip().upper()
    original_code = (original_value or "").strip().upper()
    if not new_code or new_code == original_code:
        return
    existing = db.execute(f"SELECT {field_name} FROM {table_name} WHERE {field_name} = ?", (new_code,)).fetchone()
    if existing is not None:
        raise ValidationError(f"{label} already exists.")


def _invoice_paid_amount_excluding(db, invoice_no: str, exclude_voucher_no: str = "") -> float:
    if exclude_voucher_no:
        row = db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM account_payments WHERE invoice_no = ? AND voucher_no <> ?",
            (invoice_no, exclude_voucher_no),
        ).fetchone()
    else:
        row = db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM account_payments WHERE invoice_no = ?",
            (invoice_no,),
        ).fetchone()
    return float(row[0] or 0.0)


def _sync_invoice_balance(db, invoice_no: str):
    invoice = db.execute(
        "SELECT invoice_no, total_amount FROM account_invoices WHERE invoice_no = ?",
        (invoice_no,),
    ).fetchone()
    if invoice is None:
        return
    total_amount = float(invoice["total_amount"] or 0.0)
    paid_amount = _invoice_paid_amount_excluding(db, invoice_no)
    if paid_amount - total_amount > 0.001:
        raise ValidationError(f"Payments already posted are greater than invoice total for {invoice_no}.")
    balance_amount = max(round(total_amount - paid_amount, 2), 0.0)
    status = "Paid" if balance_amount <= 0.009 else ("Partially Paid" if paid_amount > 0 else "Open")
    db.execute(
        """
        UPDATE account_invoices
        SET paid_amount = ?, balance_amount = ?, status = ?
        WHERE invoice_no = ?
        """,
        (round(paid_amount, 2), balance_amount, status, invoice_no),
    )


def _fetch_supplier_party(db, party_code: str):
    party = _fetch_party(db, party_code)
    if party is None:
        return None
    if "Supplier" not in _deserialize_party_roles(party["party_roles"] or ""):
        return None
    return party


def _normalize_supplier_roles(values) -> list[str]:
    selected = ["Supplier"]
    for role in PARTY_ROLE_OPTIONS:
        if role == "Supplier":
            continue
        if role in values and role not in selected:
            selected.append(role)
    return selected


def _default_supplier_form():
    values = _default_party_form()
    values["original_party_code"] = ""
    values["party_roles"] = ["Supplier"]
    return values


def _supplier_form_data(request):
    return {
        "original_party_code": request.form.get("original_party_code", "").strip().upper(),
        "party_code": request.form.get("party_code", "").strip().upper(),
        "party_name": request.form.get("party_name", "").strip(),
        "party_kind": request.form.get("party_kind", "Company").strip() or "Company",
        "party_roles": ["Supplier"] + request.form.getlist("party_roles"),
        "contact_person": request.form.get("contact_person", "").strip(),
        "phone_number": request.form.get("phone_number", "").strip(),
        "email": request.form.get("email", "").strip(),
        "trn_no": request.form.get("trn_no", "").strip(),
        "trade_license_no": request.form.get("trade_license_no", "").strip(),
        "address": request.form.get("address", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "status": request.form.get("status", "Active").strip() or "Active",
    }


def _supplier_form_from_party(record):
    values = _party_values_from_record(record)
    values["original_party_code"] = record["party_code"]
    return values


def _prepare_supplier_party_payload(db, values):
    if not values["party_name"]:
        raise ValidationError("Supplier name is required.")
    values["party_roles"] = _normalize_supplier_roles(values["party_roles"])
    values["phone_number"] = _normalize_optional_phone(values["phone_number"])
    _validate_optional_email(values["email"])
    values["party_code"] = values["party_code"] or values["original_party_code"] or _next_party_code(db)
    return (
        values["party_code"],
        values["party_name"],
        values["party_kind"],
        _serialize_party_roles(values["party_roles"]),
        values["contact_person"],
        values["phone_number"],
        values["email"],
        values["trn_no"],
        values["trade_license_no"],
        values["address"],
        values["notes"],
        values["status"],
    )


def _default_supplier_asset_form(db=None, party_code: str = ""):
    db = db or open_db()
    return {
        "original_asset_code": "",
        "asset_code": _next_reference_code(db, "supplier_assets", "asset_code", "AST"),
        "party_code": party_code,
        "asset_name": "",
        "asset_type": "Trailer",
        "vehicle_no": "",
        "rate_basis": SUPPLIER_RATE_BASIS_OPTIONS[0],
        "default_rate": "",
        "capacity": "",
        "status": "Active",
        "notes": "",
    }


def _default_supplier_timesheet_form(db=None, party_code: str = ""):
    db = db or open_db()
    return {
        "original_timesheet_no": "",
        "timesheet_no": _next_reference_code(db, "supplier_timesheets", "timesheet_no", "TSH"),
        "party_code": party_code,
        "asset_code": "",
        "period_month": _current_month_value(),
        "entry_date": date.today().isoformat(),
        "billing_basis": SUPPLIER_RATE_BASIS_OPTIONS[0],
        "billable_qty": "",
        "timesheet_hours": "",
        "rate": "",
        "status": "Open",
        "notes": "",
    }


def _default_supplier_voucher_form(db=None, party_code: str = ""):
    db = db or open_db()
    return {
        "original_voucher_no": "",
        "voucher_no": _next_reference_code(db, "supplier_vouchers", "voucher_no", "SPV"),
        "party_code": party_code,
        "period_month": _current_month_value(),
        "issue_date": date.today().isoformat(),
        "tax_percent": "5",
        "status": SUPPLIER_VOUCHER_STATUS_OPTIONS[0],
        "notes": "",
    }


def _default_supplier_payment_form(db=None, party_code: str = ""):
    db = db or open_db()
    return {
        "original_payment_no": "",
        "payment_no": _next_reference_code(db, "supplier_payments", "payment_no", "SPP"),
        "party_code": party_code,
        "voucher_no": "",
        "entry_date": date.today().isoformat(),
        "amount": "",
        "payment_method": PAYMENT_METHOD_OPTIONS[0],
        "reference": "",
        "notes": "",
    }


def _supplier_asset_form_data(request, party_code: str):
    return {
        "original_asset_code": request.form.get("original_asset_code", "").strip().upper(),
        "asset_code": request.form.get("asset_code", "").strip().upper(),
        "party_code": party_code,
        "asset_name": request.form.get("asset_name", "").strip(),
        "asset_type": request.form.get("asset_type", "Trailer").strip() or "Trailer",
        "vehicle_no": request.form.get("vehicle_no", "").strip(),
        "rate_basis": request.form.get("rate_basis", SUPPLIER_RATE_BASIS_OPTIONS[0]).strip() or SUPPLIER_RATE_BASIS_OPTIONS[0],
        "default_rate": request.form.get("default_rate", "").strip(),
        "capacity": request.form.get("capacity", "").strip(),
        "status": request.form.get("status", "Active").strip() or "Active",
        "notes": request.form.get("notes", "").strip(),
    }


def _supplier_timesheet_form_data(request, party_code: str):
    return {
        "original_timesheet_no": request.form.get("original_timesheet_no", "").strip().upper(),
        "timesheet_no": request.form.get("timesheet_no", "").strip().upper(),
        "party_code": party_code,
        "asset_code": request.form.get("asset_code", "").strip().upper(),
        "period_month": _normalize_month(request.form.get("period_month", "").strip()),
        "entry_date": request.form.get("entry_date", date.today().isoformat()).strip() or date.today().isoformat(),
        "billing_basis": request.form.get("billing_basis", SUPPLIER_RATE_BASIS_OPTIONS[0]).strip() or SUPPLIER_RATE_BASIS_OPTIONS[0],
        "billable_qty": request.form.get("billable_qty", "").strip(),
        "timesheet_hours": request.form.get("timesheet_hours", "0").strip() or "0",
        "rate": request.form.get("rate", "").strip(),
        "status": request.form.get("status", "Open").strip() or "Open",
        "notes": request.form.get("notes", "").strip(),
    }


def _supplier_voucher_form_data(request, party_code: str):
    return {
        "original_voucher_no": request.form.get("original_voucher_no", "").strip().upper(),
        "voucher_no": request.form.get("voucher_no", "").strip().upper(),
        "party_code": party_code,
        "period_month": _normalize_month(request.form.get("period_month", "").strip()),
        "issue_date": request.form.get("issue_date", date.today().isoformat()).strip() or date.today().isoformat(),
        "tax_percent": request.form.get("tax_percent", "5").strip() or "5",
        "status": request.form.get("status", SUPPLIER_VOUCHER_STATUS_OPTIONS[0]).strip() or SUPPLIER_VOUCHER_STATUS_OPTIONS[0],
        "notes": request.form.get("notes", "").strip(),
    }


def _supplier_payment_form_data(request, party_code: str):
    return {
        "original_payment_no": request.form.get("original_payment_no", "").strip().upper(),
        "payment_no": request.form.get("payment_no", "").strip().upper(),
        "voucher_no": request.form.get("voucher_no", "").strip().upper(),
        "party_code": party_code,
        "entry_date": request.form.get("entry_date", date.today().isoformat()).strip() or date.today().isoformat(),
        "amount": request.form.get("amount", "").strip(),
        "payment_method": request.form.get("payment_method", PAYMENT_METHOD_OPTIONS[0]).strip() or PAYMENT_METHOD_OPTIONS[0],
        "reference": request.form.get("reference", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }


def _supplier_asset_form_from_row(row):
    values = _default_supplier_asset_form()
    values.update(
        {
            "original_asset_code": row["asset_code"],
            "asset_code": row["asset_code"],
            "party_code": row["party_code"],
            "asset_name": row["asset_name"] or "",
            "asset_type": row["asset_type"] or "Trailer",
            "vehicle_no": row["vehicle_no"] or "",
            "rate_basis": row["rate_basis"] or SUPPLIER_RATE_BASIS_OPTIONS[0],
            "default_rate": _display_number(row["default_rate"]),
            "capacity": row["capacity"] or "",
            "status": row["status"] or "Active",
            "notes": row["notes"] or "",
        }
    )
    return values


def _supplier_timesheet_form_from_row(row):
    values = _default_supplier_timesheet_form()
    values.update(
        {
            "original_timesheet_no": row["timesheet_no"],
            "timesheet_no": row["timesheet_no"],
            "party_code": row["party_code"],
            "asset_code": row["asset_code"] or "",
            "period_month": row["period_month"] or _current_month_value(),
            "entry_date": row["entry_date"] or date.today().isoformat(),
            "billing_basis": row["billing_basis"] or SUPPLIER_RATE_BASIS_OPTIONS[0],
            "billable_qty": _display_number(row["billable_qty"]),
            "timesheet_hours": _display_number(row["timesheet_hours"]),
            "rate": _display_number(row["rate"]),
            "status": row["status"] or "Open",
            "notes": row["notes"] or "",
        }
    )
    return values


def _supplier_voucher_form_from_row(row):
    values = _default_supplier_voucher_form()
    values.update(
        {
            "original_voucher_no": row["voucher_no"],
            "voucher_no": row["voucher_no"],
            "party_code": row["party_code"],
            "period_month": row["period_month"] or _current_month_value(),
            "issue_date": row["issue_date"] or date.today().isoformat(),
            "tax_percent": _display_number(row["tax_percent"]),
            "status": row["status"] or SUPPLIER_VOUCHER_STATUS_OPTIONS[0],
            "notes": row["notes"] or "",
        }
    )
    return values


def _supplier_payment_form_from_row(row):
    values = _default_supplier_payment_form()
    values.update(
        {
            "original_payment_no": row["payment_no"],
            "payment_no": row["payment_no"],
            "voucher_no": row["voucher_no"] or "",
            "party_code": row["party_code"],
            "entry_date": row["entry_date"] or date.today().isoformat(),
            "amount": _display_number(row["amount"]),
            "payment_method": row["payment_method"] or PAYMENT_METHOD_OPTIONS[0],
            "reference": row["reference"] or "",
            "notes": row["notes"] or "",
        }
    )
    return values


def _prepare_supplier_asset_payload(db, values):
    _validate_party_reference(db, values["party_code"])
    if not values["asset_code"]:
        values["asset_code"] = _next_reference_code(db, "supplier_assets", "asset_code", "AST")
    if not values["asset_name"]:
        raise ValidationError("Vehicle / asset name is required.")
    default_rate = _parse_decimal(values["default_rate"], "Default rate", required=False, default=0.0, minimum=0.0)
    return (
        values["asset_code"],
        values["party_code"],
        values["asset_name"],
        values["asset_type"],
        values["vehicle_no"],
        values["rate_basis"],
        default_rate,
        values["capacity"],
        values["status"],
        values["notes"],
    )


def _prepare_supplier_timesheet_payload(db, values):
    _validate_party_reference(db, values["party_code"])
    asset = db.execute(
        """
        SELECT asset_code, party_code, asset_name, rate_basis, default_rate
        FROM supplier_assets
        WHERE asset_code = ? AND party_code = ?
        """,
        (values["asset_code"], values["party_code"]),
    ).fetchone()
    if asset is None:
        raise ValidationError("Select a valid supplier vehicle first.")
    if not values["timesheet_no"]:
        values["timesheet_no"] = _next_reference_code(db, "supplier_timesheets", "timesheet_no", "TSH")
    entry_date = _validate_date_text(values["entry_date"], "Timesheet date")
    billable_qty = _parse_decimal(values["billable_qty"], "Billable quantity", required=True, minimum=0.01)
    timesheet_hours = _parse_decimal(values["timesheet_hours"], "Timesheet hours", required=False, default=0.0, minimum=0.0)
    rate = _parse_decimal(values["rate"], "Rate", required=False, default=float(asset["default_rate"] or 0.0), minimum=0.0)
    subtotal = round(billable_qty * rate, 2)
    values["subtotal"] = subtotal
    return (
        values["timesheet_no"],
        values["party_code"],
        values["asset_code"],
        values["period_month"],
        entry_date,
        values["billing_basis"] or asset["rate_basis"] or SUPPLIER_RATE_BASIS_OPTIONS[0],
        billable_qty,
        timesheet_hours,
        rate,
        subtotal,
        values["status"],
        values["notes"],
    )


def _prepare_new_supplier_voucher_payload(db, values):
    _validate_party_reference(db, values["party_code"])
    if not values["voucher_no"]:
        values["voucher_no"] = _next_reference_code(db, "supplier_vouchers", "voucher_no", "SPV")
    issue_date = _validate_date_text(values["issue_date"], "Voucher date")
    tax_percent = _parse_decimal(values["tax_percent"], "Tax percent", required=False, default=0.0, minimum=0.0)
    timesheets = db.execute(
        """
        SELECT timesheet_no, subtotal
        FROM supplier_timesheets
        WHERE party_code = ? AND period_month = ? AND COALESCE(voucher_no, '') = ''
        ORDER BY entry_date ASC, id ASC
        """,
        (values["party_code"], values["period_month"]),
    ).fetchall()
    if not timesheets:
        raise ValidationError("No open timesheet rows found for this month.")
    subtotal = round(sum(float(item["subtotal"] or 0.0) for item in timesheets), 2)
    tax_amount = round(subtotal * (tax_percent / 100.0), 2)
    total_amount = round(subtotal + tax_amount, 2)
    return (
        (
            values["voucher_no"],
            values["party_code"],
            values["period_month"],
            issue_date,
            subtotal,
            tax_percent,
            tax_amount,
            total_amount,
            0.0,
            total_amount,
            "Open",
            values["notes"],
        ),
        timesheets,
    )


def _prepare_existing_supplier_voucher_payload(db, values):
    voucher_lookup = values["original_voucher_no"] or values["voucher_no"]
    voucher = db.execute(
        "SELECT voucher_no, tax_percent FROM supplier_vouchers WHERE voucher_no = ? AND party_code = ?",
        (voucher_lookup, values["party_code"]),
    ).fetchone()
    if voucher is None:
        raise ValidationError("Supplier voucher was not found.")
    if not values["voucher_no"]:
        values["voucher_no"] = voucher_lookup
    issue_date = _validate_date_text(values["issue_date"], "Voucher date")
    tax_percent = _parse_decimal(values["tax_percent"], "Tax percent", required=False, default=float(voucher["tax_percent"] or 0.0), minimum=0.0)
    subtotal = float(
        db.execute(
            "SELECT COALESCE(SUM(subtotal), 0) FROM supplier_timesheets WHERE voucher_no = ?",
            (voucher_lookup,),
        ).fetchone()[0]
        or 0.0
    )
    paid_amount = _supplier_voucher_paid_amount(db, voucher_lookup)
    tax_amount = round(subtotal * (tax_percent / 100.0), 2)
    total_amount = round(subtotal + tax_amount, 2)
    if paid_amount - total_amount > 0.001:
        raise ValidationError("Voucher total cannot be less than already posted payments.")
    balance_amount = max(round(total_amount - paid_amount, 2), 0.0)
    status = _supplier_voucher_status(total_amount, paid_amount)
    return (
        values["voucher_no"],
        values["party_code"],
        values["period_month"],
        issue_date,
        subtotal,
        tax_percent,
        tax_amount,
        total_amount,
        round(paid_amount, 2),
        balance_amount,
        status,
        values["notes"],
    )


def _prepare_supplier_payment_payload(db, values):
    _validate_party_reference(db, values["party_code"])
    voucher = db.execute(
        """
        SELECT voucher_no, party_code, total_amount
        FROM supplier_vouchers
        WHERE voucher_no = ? AND party_code = ?
        """,
        (values["voucher_no"], values["party_code"]),
    ).fetchone()
    if voucher is None:
        raise ValidationError("Select a valid supplier voucher first.")
    if not values["payment_no"]:
        values["payment_no"] = _next_reference_code(db, "supplier_payments", "payment_no", "SPP")
    entry_date = _validate_date_text(values["entry_date"], "Payment date")
    amount = _parse_decimal(values["amount"], "Payment amount", required=True, minimum=0.01)
    other_paid = _supplier_voucher_paid_amount(db, values["voucher_no"], exclude_payment_no=values["original_payment_no"])
    remaining = float(voucher["total_amount"] or 0.0) - other_paid
    if amount - remaining > 0.001:
        raise ValidationError(f"Payment amount cannot be greater than voucher balance {remaining:,.2f}.")
    return (
        values["payment_no"],
        values["voucher_no"],
        values["party_code"],
        entry_date,
        amount,
        values["payment_method"],
        values["reference"],
        values["notes"],
    )


def _supplier_voucher_paid_amount(db, voucher_no: str, exclude_payment_no: str = "") -> float:
    if exclude_payment_no:
        row = db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM supplier_payments WHERE voucher_no = ? AND payment_no <> ?",
            (voucher_no, exclude_payment_no),
        ).fetchone()
    else:
        row = db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM supplier_payments WHERE voucher_no = ?",
            (voucher_no,),
        ).fetchone()
    return float(row[0] or 0.0)


def _supplier_voucher_status(total_amount: float, paid_amount: float) -> str:
    if total_amount <= 0.009 or paid_amount <= 0.009:
        return "Open"
    if total_amount - paid_amount <= 0.009:
        return "Paid"
    return "Partially Paid"


def _supplier_sync_voucher_balance(db, voucher_no: str):
    voucher = db.execute(
        "SELECT voucher_no, tax_percent FROM supplier_vouchers WHERE voucher_no = ?",
        (voucher_no,),
    ).fetchone()
    if voucher is None:
        return
    subtotal = float(
        db.execute(
            "SELECT COALESCE(SUM(subtotal), 0) FROM supplier_timesheets WHERE voucher_no = ?",
            (voucher_no,),
        ).fetchone()[0]
        or 0.0
    )
    tax_percent = float(voucher["tax_percent"] or 0.0)
    tax_amount = round(subtotal * (tax_percent / 100.0), 2)
    total_amount = round(subtotal + tax_amount, 2)
    paid_amount = _supplier_voucher_paid_amount(db, voucher_no)
    if paid_amount - total_amount > 0.001:
        raise ValidationError(f"Payments already posted are greater than voucher total for {voucher_no}.")
    balance_amount = max(round(total_amount - paid_amount, 2), 0.0)
    status = _supplier_voucher_status(total_amount, paid_amount)
    db.execute(
        """
        UPDATE supplier_vouchers
        SET subtotal = ?, tax_amount = ?, total_amount = ?, paid_amount = ?, balance_amount = ?, status = ?
        WHERE voucher_no = ?
        """,
        (subtotal, tax_amount, total_amount, round(paid_amount, 2), balance_amount, status, voucher_no),
    )


def _supplier_hub_summary(db):
    return {
        "supplier_count": int(db.execute("SELECT COUNT(*) FROM parties WHERE party_roles LIKE ?", ("%Supplier%",)).fetchone()[0]),
        "asset_count": int(db.execute("SELECT COUNT(*) FROM supplier_assets").fetchone()[0]),
        "unbilled_amount": float(db.execute("SELECT COALESCE(SUM(subtotal), 0) FROM supplier_timesheets WHERE COALESCE(voucher_no, '') = ''").fetchone()[0] or 0.0),
        "voucher_total": float(db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM supplier_vouchers").fetchone()[0] or 0.0),
        "paid_total": float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM supplier_payments").fetchone()[0] or 0.0),
        "outstanding_total": float(db.execute("SELECT COALESCE(SUM(balance_amount), 0) FROM supplier_vouchers").fetchone()[0] or 0.0),
        "open_vouchers": int(db.execute("SELECT COUNT(*) FROM supplier_vouchers WHERE balance_amount > 0.009").fetchone()[0]),
    }


def _supplier_directory_rows(db, query: str = "", limit: int | None = None):
    filters = ["p.party_roles LIKE ?"]
    params = ["%Supplier%"]
    if query:
        needle = f"%{query.strip().lower()}%"
        filters.append(
            """
            (
                LOWER(p.party_code) LIKE ? OR
                LOWER(p.party_name) LIKE ? OR
                LOWER(COALESCE(p.contact_person, '')) LIKE ? OR
                LOWER(COALESCE(p.phone_number, '')) LIKE ?
            )
            """
        )
        params.extend([needle, needle, needle, needle])
    limit_sql = f"LIMIT {int(limit)}" if limit else ""
    return db.execute(
        f"""
        SELECT
            p.party_code,
            p.party_name,
            p.party_kind,
            p.party_roles,
            p.contact_person,
            p.phone_number,
            p.email,
            p.trn_no,
            p.trade_license_no,
            p.status,
            COALESCE(asset_totals.asset_count, 0) AS asset_count,
            COALESCE(ts_totals.unbilled_count, 0) AS unbilled_count,
            COALESCE(ts_totals.unbilled_amount, 0) AS unbilled_amount,
            COALESCE(voucher_totals.voucher_count, 0) AS voucher_count,
            COALESCE(voucher_totals.total_amount, 0) AS voucher_total,
            COALESCE(voucher_totals.balance_amount, 0) AS outstanding_total,
            COALESCE(payment_totals.paid_amount, 0) AS paid_total
        FROM parties p
        LEFT JOIN (
            SELECT party_code, COUNT(*) AS asset_count
            FROM supplier_assets
            GROUP BY party_code
        ) asset_totals ON asset_totals.party_code = p.party_code
        LEFT JOIN (
            SELECT party_code, COUNT(*) AS unbilled_count, COALESCE(SUM(subtotal), 0) AS unbilled_amount
            FROM supplier_timesheets
            WHERE COALESCE(voucher_no, '') = ''
            GROUP BY party_code
        ) ts_totals ON ts_totals.party_code = p.party_code
        LEFT JOIN (
            SELECT party_code, COUNT(*) AS voucher_count, COALESCE(SUM(total_amount), 0) AS total_amount, COALESCE(SUM(balance_amount), 0) AS balance_amount
            FROM supplier_vouchers
            GROUP BY party_code
        ) voucher_totals ON voucher_totals.party_code = p.party_code
        LEFT JOIN (
            SELECT party_code, COALESCE(SUM(amount), 0) AS paid_amount
            FROM supplier_payments
            GROUP BY party_code
        ) payment_totals ON payment_totals.party_code = p.party_code
        WHERE {" AND ".join(filters)}
        ORDER BY CASE WHEN p.status = 'Active' THEN 0 ELSE 1 END,
                 COALESCE(voucher_totals.balance_amount, 0) DESC,
                 p.party_name ASC
        {limit_sql}
        """,
        params,
    ).fetchall()


def _supplier_asset_rows(db, party_code: str, limit: int = 40):
    return db.execute(
        f"""
        SELECT
            asset_code, party_code, asset_name, asset_type, vehicle_no,
            rate_basis, default_rate, capacity, status, notes
        FROM supplier_assets
        WHERE party_code = ?
        ORDER BY CASE WHEN status = 'Active' THEN 0 ELSE 1 END, asset_name ASC
        LIMIT {int(limit)}
        """,
        (party_code,),
    ).fetchall()


def _supplier_timesheet_rows(db, party_code: str, limit: int = 40):
    return db.execute(
        f"""
        SELECT
            t.timesheet_no,
            t.party_code,
            t.asset_code,
            a.asset_name,
            a.vehicle_no,
            t.period_month,
            t.entry_date,
            t.billing_basis,
            t.billable_qty,
            t.timesheet_hours,
            t.rate,
            t.subtotal,
            t.voucher_no,
            t.status,
            t.notes
        FROM supplier_timesheets t
        LEFT JOIN supplier_assets a ON a.asset_code = t.asset_code
        WHERE t.party_code = ?
        ORDER BY t.period_month DESC, t.entry_date DESC, t.id DESC
        LIMIT {int(limit)}
        """,
        (party_code,),
    ).fetchall()


def _supplier_voucher_rows(db, party_code: str, limit: int = 30):
    return db.execute(
        f"""
        SELECT
            voucher_no, party_code, period_month, issue_date,
            subtotal, tax_percent, tax_amount, total_amount,
            paid_amount, balance_amount, status, notes
        FROM supplier_vouchers
        WHERE party_code = ?
        ORDER BY issue_date DESC, id DESC
        LIMIT {int(limit)}
        """,
        (party_code,),
    ).fetchall()


def _supplier_payment_rows(db, party_code: str, limit: int = 30):
    return db.execute(
        f"""
        SELECT
            p.payment_no,
            p.voucher_no,
            p.party_code,
            p.entry_date,
            p.amount,
            p.payment_method,
            p.reference,
            p.notes,
            v.period_month,
            v.balance_amount
        FROM supplier_payments p
        LEFT JOIN supplier_vouchers v ON v.voucher_no = p.voucher_no
        WHERE p.party_code = ?
        ORDER BY p.entry_date DESC, p.id DESC
        LIMIT {int(limit)}
        """,
        (party_code,),
    ).fetchall()


def _supplier_detail_summary(db, party_code: str):
    return {
        "asset_count": int(db.execute("SELECT COUNT(*) FROM supplier_assets WHERE party_code = ?", (party_code,)).fetchone()[0]),
        "unbilled_count": int(db.execute("SELECT COUNT(*) FROM supplier_timesheets WHERE party_code = ? AND COALESCE(voucher_no, '') = ''", (party_code,)).fetchone()[0]),
        "unbilled_amount": float(db.execute("SELECT COALESCE(SUM(subtotal), 0) FROM supplier_timesheets WHERE party_code = ? AND COALESCE(voucher_no, '') = ''", (party_code,)).fetchone()[0] or 0.0),
        "voucher_total": float(db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM supplier_vouchers WHERE party_code = ?", (party_code,)).fetchone()[0] or 0.0),
        "paid_total": float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM supplier_payments WHERE party_code = ?", (party_code,)).fetchone()[0] or 0.0),
        "outstanding_total": float(db.execute("SELECT COALESCE(SUM(balance_amount), 0) FROM supplier_vouchers WHERE party_code = ?", (party_code,)).fetchone()[0] or 0.0),
        "open_voucher_count": int(db.execute("SELECT COUNT(*) FROM supplier_vouchers WHERE party_code = ? AND balance_amount > 0.009", (party_code,)).fetchone()[0]),
    }


def _supplier_statement_data(db, party_code: str):
    rows = []
    timesheets = db.execute(
        """
        SELECT t.entry_date, t.period_month, t.timesheet_no, t.subtotal, t.voucher_no, a.asset_name, a.vehicle_no
        FROM supplier_timesheets t
        LEFT JOIN supplier_assets a ON a.asset_code = t.asset_code
        WHERE t.party_code = ?
        ORDER BY t.entry_date ASC, t.id ASC
        """,
        (party_code,),
    ).fetchall()
    vouchers = db.execute(
        """
        SELECT issue_date, voucher_no, period_month, total_amount, balance_amount, status
        FROM supplier_vouchers
        WHERE party_code = ?
        ORDER BY issue_date ASC, id ASC
        """,
        (party_code,),
    ).fetchall()
    payments = db.execute(
        """
        SELECT entry_date, payment_no, voucher_no, amount, payment_method
        FROM supplier_payments
        WHERE party_code = ?
        ORDER BY entry_date ASC, id ASC
        """,
        (party_code,),
    ).fetchall()
    for row in timesheets:
        rows.append(
            {
                "entry_date": row["entry_date"],
                "reference": row["timesheet_no"],
                "entry_type": "Timesheet",
                "details": f"{row['asset_name'] or 'Asset'} / {row['vehicle_no'] or '-'} / {format_month_label(row['period_month'])}",
                "work_amount": float(row["subtotal"] or 0.0),
                "voucher_amount": 0.0,
                "payment_amount": 0.0,
            }
        )
    for row in vouchers:
        rows.append(
            {
                "entry_date": row["issue_date"],
                "reference": row["voucher_no"],
                "entry_type": "Voucher",
                "details": f"{format_month_label(row['period_month'])} / {row['status']}",
                "work_amount": 0.0,
                "voucher_amount": float(row["total_amount"] or 0.0),
                "payment_amount": 0.0,
            }
        )
    for row in payments:
        rows.append(
            {
                "entry_date": row["entry_date"],
                "reference": row["payment_no"],
                "entry_type": "Payment",
                "details": f"{row['voucher_no']} / {row['payment_method'] or '-'}",
                "work_amount": 0.0,
                "voucher_amount": 0.0,
                "payment_amount": float(row["amount"] or 0.0),
            }
        )
    sort_order = {"Timesheet": 0, "Voucher": 1, "Payment": 2}
    rows.sort(key=lambda item: (item["entry_date"], sort_order.get(item["entry_type"], 9), item["reference"]))
    running_balance = 0.0
    for item in rows:
        if item["entry_type"] == "Voucher":
            running_balance += item["voucher_amount"]
        elif item["entry_type"] == "Payment":
            running_balance -= item["payment_amount"]
        item["running_balance"] = max(round(running_balance, 2), 0.0)

    summary = {
        "work_logged": sum(item["work_amount"] for item in rows),
        "total_vouchers": sum(item["voucher_amount"] for item in rows),
        "total_paid": sum(item["payment_amount"] for item in rows),
        "outstanding": max(round(sum(item["voucher_amount"] for item in rows) - sum(item["payment_amount"] for item in rows), 2), 0.0),
    }
    return rows, summary


def _supplier_payment_with_context(db, payment_no: str):
    return db.execute(
        """
        SELECT
            pay.payment_no,
            pay.voucher_no,
            pay.party_code,
            pay.entry_date,
            pay.amount,
            pay.payment_method,
            pay.reference,
            pay.notes,
            party.party_name,
            party.contact_person,
            party.phone_number,
            voucher.period_month,
            voucher.issue_date,
            voucher.total_amount,
            voucher.paid_amount,
            voucher.balance_amount,
            voucher.status
        FROM supplier_payments pay
        LEFT JOIN parties party ON party.party_code = pay.party_code
        LEFT JOIN supplier_vouchers voucher ON voucher.voucher_no = pay.voucher_no
        WHERE pay.payment_no = ?
        """,
        (payment_no,),
    ).fetchone()


def _supplier_output_dir(app, party_code: str) -> Path:
    return Path(app.config["GENERATED_DIR"]) / "suppliers" / party_code


def _prepare_agreement_payload(db, values):
    if not values["agreement_no"]:
        values["agreement_no"] = _next_reference_code(db, "agreements", "agreement_no", "AGR")
    _validate_party_reference(db, values["party_code"])
    start_date = _validate_date_text(values["start_date"], "Agreement start date")
    end_date = _validate_date_text(values["end_date"], "Agreement end date", required=False)
    amount = _parse_decimal(values["amount"], "Agreement amount", required=False, default=0.0, minimum=0.0)
    tax_percent = _parse_decimal(values["tax_percent"], "Agreement tax percent", required=False, default=0.0, minimum=0.0)
    return (
        values["agreement_no"], values["party_code"], values["agreement_kind"], start_date, end_date or None,
        values["rate_type"], amount, tax_percent, values["scope"], values["notes"], values["status"],
    )


def _prepare_lpo_payload(db, values):
    if not values["lpo_no"]:
        values["lpo_no"] = _next_reference_code(db, "lpos", "lpo_no", "LPO")
    _validate_party_reference(db, values["party_code"])
    agreement_no = _optional_reference_exists(db, "agreements", "agreement_no", values["agreement_no"], "Agreement")
    issue_date = _validate_date_text(values["issue_date"], "LPO issue date")
    valid_until = _validate_date_text(values["valid_until"], "LPO valid until", required=False)
    amount = _parse_decimal(values["amount"], "LPO amount", required=False, default=0.0, minimum=0.0)
    tax_percent = _parse_decimal(values["tax_percent"], "LPO tax percent", required=False, default=0.0, minimum=0.0)
    return (values["lpo_no"], values["party_code"], agreement_no or None, issue_date, valid_until or None, amount, tax_percent, values["description"], values["status"])


def _prepare_hire_payload(db, values):
    if not values["hire_no"]:
        values["hire_no"] = _next_reference_code(db, "hire_records", "hire_no", "HIR")
    _validate_party_reference(db, values["party_code"])
    agreement_no = _optional_reference_exists(db, "agreements", "agreement_no", values["agreement_no"], "Agreement")
    lpo_no = _optional_reference_exists(db, "lpos", "lpo_no", values["lpo_no"], "LPO")
    entry_date = _validate_date_text(values["entry_date"], "Hire date")
    quantity = _parse_decimal(values["quantity"], "Hire quantity", required=False, default=1.0, minimum=0.01)
    rate = _parse_decimal(values["rate"], "Hire rate", required=True, minimum=0.0)
    tax_percent = _parse_decimal(values["tax_percent"], "Hire tax percent", required=False, default=0.0, minimum=0.0)
    if not values["asset_name"]:
        raise ValidationError("Asset / vehicle name is required.")
    subtotal = round(quantity * rate, 2)
    tax_amount = round(subtotal * (tax_percent / 100.0), 2)
    total_amount = round(subtotal + tax_amount, 2)
    values["total_amount"] = total_amount
    return (values["hire_no"], values["party_code"], agreement_no or None, lpo_no or None, entry_date, values["direction"], values["asset_name"], values["asset_type"], values["unit_type"], quantity, rate, subtotal, tax_percent, tax_amount, total_amount, values["status"], values["notes"])


def _prepare_invoice_line_payloads(db, values, line_rows):
    prepared_lines = []
    for row in line_rows:
        description = (row.get("description") or "").strip()
        quantity_raw = (row.get("quantity") or "").strip()
        unit_label = (row.get("unit_label") or "").strip()
        rate_raw = (row.get("rate") or "").strip()
        subtotal_raw = (row.get("subtotal") or "").strip()
        if not any([description, quantity_raw, unit_label, rate_raw, subtotal_raw]):
            continue
        if not description:
            raise ValidationError(f"Invoice line {row['line_no']} description is required.")
        quantity = _parse_decimal(quantity_raw or "1", f"Invoice line {row['line_no']} quantity", required=True, minimum=0.01)
        rate = _parse_decimal(rate_raw or "0", f"Invoice line {row['line_no']} rate", required=False, default=0.0, minimum=0.0)
        subtotal = round(quantity * rate, 2)
        prepared_lines.append(
            {
                "line_no": len(prepared_lines) + 1,
                "description": description,
                "quantity": quantity,
                "unit_label": unit_label,
                "rate": rate,
                "subtotal": subtotal,
            }
        )

    if prepared_lines:
        return prepared_lines

    hire_no = (values.get("hire_no") or "").strip().upper()
    if hire_no:
        hire_row = db.execute(
            """
            SELECT asset_name, unit_type, quantity, rate, subtotal
            FROM hire_records
            WHERE hire_no = ?
            """,
            (hire_no,),
        ).fetchone()
        if hire_row is not None:
            return [
                {
                    "line_no": 1,
                    "description": hire_row["asset_name"] or f"Hire {hire_no}",
                    "quantity": float(hire_row["quantity"] or 1.0),
                    "unit_label": hire_row["unit_type"] or "",
                    "rate": float(hire_row["rate"] or 0.0),
                    "subtotal": float(hire_row["subtotal"] or 0.0),
                }
            ]

    return []


def _save_invoice_lines(db, invoice_no: str, line_rows):
    for row in line_rows:
        db.execute(
            """
            INSERT INTO account_invoice_lines (
                invoice_no, line_no, description, quantity, unit_label, rate, subtotal
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_no,
                row["line_no"],
                row["description"],
                row["quantity"],
                row["unit_label"] or None,
                row["rate"],
                row["subtotal"],
            ),
        )


def _prepare_invoice_payload(db, values, line_rows):
    if not values["invoice_no"]:
        values["invoice_no"] = _next_reference_code(db, "account_invoices", "invoice_no", "INV")
    if values["document_type"] not in INVOICE_DOCUMENT_OPTIONS:
        values["document_type"] = INVOICE_DOCUMENT_OPTIONS[0]
    _validate_party_reference(db, values["party_code"])
    agreement_no = _optional_reference_exists(db, "agreements", "agreement_no", values["agreement_no"], "Agreement")
    lpo_no = _optional_reference_exists(db, "lpos", "lpo_no", values["lpo_no"], "LPO")
    hire_no = _optional_reference_exists(db, "hire_records", "hire_no", values["hire_no"], "Hire register")
    issue_date = _validate_date_text(values["issue_date"], "Invoice date")
    due_date = _validate_date_text(values["due_date"], "Invoice due date", required=False)
    prepared_lines = _prepare_invoice_line_payloads(db, values, line_rows)
    if prepared_lines:
        subtotal = round(sum(float(row["subtotal"]) for row in prepared_lines), 2)
    else:
        subtotal = _parse_decimal(values["subtotal"], "Invoice subtotal", required=True, minimum=0.0)
    tax_percent = _parse_decimal(values["tax_percent"], "Invoice tax percent", required=False, default=0.0, minimum=0.0)
    tax_amount = round(subtotal * (tax_percent / 100.0), 2)
    total_amount = round(subtotal + tax_amount, 2)
    values["total_amount"] = total_amount
    return (
        (
            values["invoice_no"],
            values["party_code"],
            agreement_no or None,
            lpo_no or None,
            hire_no or None,
            values["invoice_kind"],
            values["document_type"],
            issue_date,
            due_date or None,
            subtotal,
            tax_percent,
            tax_amount,
            total_amount,
            0.0,
            total_amount,
            "Open",
            None,
            values["notes"],
        ),
        prepared_lines,
    )


def _prepare_payment_payload(invoice, values):
    db = open_db()
    if not values["voucher_no"]:
        values["voucher_no"] = _next_reference_code(db, "account_payments", "voucher_no", "PAY")
    entry_date = _validate_date_text(values["entry_date"], "Payment date")
    amount = _parse_decimal(values["amount"], "Payment amount", required=True, minimum=0.01)
    current_balance = float(invoice["balance_amount"])
    if amount - current_balance > 0.001:
        raise ValidationError(f"Payment amount cannot be greater than invoice balance {current_balance:,.2f}.")
    payment_kind = "Received" if (invoice["invoice_kind"] or "Sales") == "Sales" else "Paid"
    new_paid_amount = round(float(invoice["paid_amount"]) + amount, 2)
    new_balance = round(float(invoice["total_amount"]) - new_paid_amount, 2)
    status = "Paid" if new_balance <= 0.009 else "Partially Paid"
    return ((values["voucher_no"], invoice["invoice_no"], invoice["party_code"], payment_kind, entry_date, amount, values["payment_method"], values["reference"], values["notes"]), (new_paid_amount, max(new_balance, 0.0), status, invoice["invoice_no"]))


def _prepare_loan_payload(db, values):
    if not values["loan_no"]:
        values["loan_no"] = _next_reference_code(db, "loan_entries", "loan_no", "LOAN")
    _validate_party_reference(db, values["party_code"])
    entry_date = _validate_date_text(values["entry_date"], "Loan date")
    amount = _parse_decimal(values["amount"], "Loan amount", required=True, minimum=0.01)
    return (values["loan_no"], values["party_code"], entry_date, values["loan_type"], amount, values["payment_method"], values["reference"], values["notes"])


def _prepare_fee_payload(db, values):
    if not values["fee_no"]:
        values["fee_no"] = _next_reference_code(db, "annual_fee_entries", "fee_no", "FEE")
    _validate_party_reference(db, values["party_code"])
    due_date = _validate_date_text(values["due_date"], "Fee due date")
    annual_amount = _parse_decimal(values["annual_amount"], "Annual amount", required=True, minimum=0.0)
    received_amount = _parse_decimal(values["received_amount"], "Received amount", required=False, default=0.0, minimum=0.0)
    if received_amount - annual_amount > 0.001:
        raise ValidationError("Received amount cannot be greater than annual amount.")
    balance_amount = round(annual_amount - received_amount, 2)
    status = "Closed" if balance_amount <= 0.009 else values["status"]
    return (values["fee_no"], values["party_code"], values["fee_type"], values["description"], values["vehicle_no"], due_date, annual_amount, received_amount, max(balance_amount, 0.0), status, values["notes"])


def _agreement_rows(db, limit: int = 12):
    return db.execute(f"SELECT a.agreement_no, a.party_code, p.party_name, a.agreement_kind, a.start_date, a.end_date, a.rate_type, a.amount, a.tax_percent, a.status, a.scope FROM agreements a LEFT JOIN parties p ON p.party_code = a.party_code ORDER BY a.start_date DESC, a.id DESC LIMIT {int(limit)}").fetchall()


def _lpo_rows(db, limit: int = 12):
    return db.execute(f"SELECT l.lpo_no, l.party_code, p.party_name, l.agreement_no, l.issue_date, l.valid_until, l.amount, l.tax_percent, l.status, l.description FROM lpos l LEFT JOIN parties p ON p.party_code = l.party_code ORDER BY l.issue_date DESC, l.id DESC LIMIT {int(limit)}").fetchall()


def _hire_rows(db, direction: str | None = None, limit: int = 12):
    params = []
    where_sql = ""
    if direction:
        where_sql = "WHERE h.direction = ?"
        params.append(direction)
    return db.execute(f"SELECT h.hire_no, h.party_code, p.party_name, h.agreement_no, h.lpo_no, h.entry_date, h.direction, h.asset_name, h.asset_type, h.unit_type, h.quantity, h.rate, h.subtotal, h.tax_percent, h.tax_amount, h.total_amount, h.status, h.notes FROM hire_records h LEFT JOIN parties p ON p.party_code = h.party_code {where_sql} ORDER BY h.entry_date DESC, h.id DESC LIMIT {int(limit)}", params).fetchall()


def _invoice_rows(db, invoice_kind: str | None = None, limit: int = 12):
    params = []
    where_sql = ""
    if invoice_kind:
        where_sql = "WHERE i.invoice_kind = ?"
        params.append(invoice_kind)
    return db.execute(f"SELECT i.invoice_no, i.party_code, p.party_name, i.agreement_no, i.lpo_no, i.hire_no, i.invoice_kind, i.document_type, i.issue_date, i.due_date, i.subtotal, i.tax_percent, i.tax_amount, i.total_amount, i.paid_amount, i.balance_amount, i.status, i.pdf_path, i.notes FROM account_invoices i LEFT JOIN parties p ON p.party_code = i.party_code {where_sql} ORDER BY i.issue_date DESC, i.id DESC LIMIT {int(limit)}", params).fetchall()


def _payment_rows(db, limit: int = 12):
    return db.execute(f"SELECT p.voucher_no, p.invoice_no, p.party_code, party.party_name, p.payment_kind, p.entry_date, p.amount, p.payment_method, p.reference, p.notes FROM account_payments p LEFT JOIN parties party ON party.party_code = p.party_code ORDER BY p.entry_date DESC, p.id DESC LIMIT {int(limit)}").fetchall()


def _open_invoice_rows(db):
    return db.execute("SELECT i.invoice_no, i.invoice_kind, i.party_code, p.party_name, i.issue_date, i.balance_amount FROM account_invoices i LEFT JOIN parties p ON p.party_code = i.party_code WHERE i.balance_amount > 0.009 ORDER BY i.issue_date DESC, i.id DESC").fetchall()


def _loan_rows(db, limit: int = 12):
    return db.execute(f"SELECT l.loan_no, l.party_code, p.party_name, l.entry_date, l.loan_type, l.amount, l.payment_method, l.reference, l.notes FROM loan_entries l LEFT JOIN parties p ON p.party_code = l.party_code ORDER BY l.entry_date DESC, l.id DESC LIMIT {int(limit)}").fetchall()


def _annual_fee_rows(db, limit: int = 12, due_only: bool = False):
    where_sql = "WHERE f.balance_amount > 0.009" if due_only else ""
    return db.execute(f"SELECT f.fee_no, f.party_code, p.party_name, f.fee_type, f.description, f.vehicle_no, f.due_date, f.annual_amount, f.received_amount, f.balance_amount, f.status, f.notes FROM annual_fee_entries f LEFT JOIN parties p ON p.party_code = f.party_code {where_sql} ORDER BY f.due_date ASC, f.id DESC LIMIT {int(limit)}").fetchall()


def _supplier_summary(db):
    return {"supplier_count": len(_parties_by_role(db, "Supplier")), "open_purchase_invoices": int(db.execute("SELECT COUNT(*) FROM account_invoices WHERE invoice_kind = 'Purchase' AND balance_amount > 0.009").fetchone()[0]), "payable_total": float(db.execute("SELECT COALESCE(SUM(balance_amount), 0) FROM account_invoices WHERE invoice_kind = 'Purchase'").fetchone()[0]), "hire_total": float(db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM hire_records WHERE direction = 'Supplier Hire'").fetchone()[0])}


def _customer_summary(db):
    return {"customer_count": len(_parties_by_role(db, "Customer")), "open_sales_invoices": int(db.execute("SELECT COUNT(*) FROM account_invoices WHERE invoice_kind = 'Sales' AND balance_amount > 0.009").fetchone()[0]), "receivable_total": float(db.execute("SELECT COALESCE(SUM(balance_amount), 0) FROM account_invoices WHERE invoice_kind = 'Sales'").fetchone()[0]), "rental_total": float(db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM hire_records WHERE direction = 'Customer Rental'").fetchone()[0])}


def _invoice_center_summary(db):
    return {"sales_total": float(db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM account_invoices WHERE invoice_kind = 'Sales'").fetchone()[0]), "purchase_total": float(db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM account_invoices WHERE invoice_kind = 'Purchase'").fetchone()[0]), "received_total": float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM account_payments WHERE payment_kind = 'Received'").fetchone()[0]), "paid_total": float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM account_payments WHERE payment_kind = 'Paid'").fetchone()[0]), "open_invoice_count": int(db.execute("SELECT COUNT(*) FROM account_invoices WHERE balance_amount > 0.009").fetchone()[0])}


def _loan_summary(db):
    total_given = float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM loan_entries WHERE loan_type = 'Given'").fetchone()[0])
    total_recovered = float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM loan_entries WHERE loan_type = 'Recovered'").fetchone()[0])
    return {"total_given": total_given, "total_recovered": total_recovered, "outstanding": max(total_given - total_recovered, 0.0)}


def _annual_fee_summary(db):
    total_annual = float(db.execute("SELECT COALESCE(SUM(annual_amount), 0) FROM annual_fee_entries").fetchone()[0])
    total_received = float(db.execute("SELECT COALESCE(SUM(received_amount), 0) FROM annual_fee_entries").fetchone()[0])
    total_balance = float(db.execute("SELECT COALESCE(SUM(balance_amount), 0) FROM annual_fee_entries").fetchone()[0])
    due_count = int(db.execute("SELECT COUNT(*) FROM annual_fee_entries WHERE balance_amount > 0.009").fetchone()[0])
    return {"total_annual": total_annual, "total_received": total_received, "total_balance": total_balance, "due_count": due_count}


def _tax_summary(db):
    output_sales = float(db.execute("SELECT COALESCE(SUM(subtotal), 0) FROM account_invoices WHERE invoice_kind = 'Sales'").fetchone()[0])
    output_vat = float(db.execute("SELECT COALESCE(SUM(tax_amount), 0) FROM account_invoices WHERE invoice_kind = 'Sales'").fetchone()[0])
    input_purchase = float(db.execute("SELECT COALESCE(SUM(subtotal), 0) FROM account_invoices WHERE invoice_kind = 'Purchase'").fetchone()[0])
    input_vat = float(db.execute("SELECT COALESCE(SUM(tax_amount), 0) FROM account_invoices WHERE invoice_kind = 'Purchase'").fetchone()[0])
    return {"taxable_sales": output_sales, "output_vat": output_vat, "taxable_purchases": input_purchase, "input_vat": input_vat, "net_vat": output_vat - input_vat}


def _party_balance_rows(db, invoice_kind: str, limit: int = 8):
    return db.execute(f"SELECT i.party_code, p.party_name, COUNT(*) AS invoice_count, COALESCE(SUM(i.total_amount), 0) AS total_amount, COALESCE(SUM(i.balance_amount), 0) AS balance_amount FROM account_invoices i LEFT JOIN parties p ON p.party_code = i.party_code WHERE i.invoice_kind = ? GROUP BY i.party_code, p.party_name HAVING COALESCE(SUM(i.total_amount), 0) > 0 ORDER BY COALESCE(SUM(i.balance_amount), 0) DESC, p.party_name ASC LIMIT {int(limit)}", (invoice_kind,)).fetchall()


def _party_statement(db, party_code: str, *, invoice_kind: str, hire_direction: str):
    rows = []
    invoices = db.execute("SELECT issue_date, invoice_no, total_amount, balance_amount, status FROM account_invoices WHERE party_code = ? AND invoice_kind = ? ORDER BY issue_date ASC, id ASC", (party_code, invoice_kind)).fetchall()
    payments = db.execute("SELECT entry_date, voucher_no, amount, payment_kind, payment_method FROM account_payments WHERE party_code = ? ORDER BY entry_date ASC, id ASC", (party_code,)).fetchall()
    hires = db.execute("SELECT entry_date, hire_no, asset_name, total_amount, status FROM hire_records WHERE party_code = ? AND direction = ? ORDER BY entry_date ASC, id ASC", (party_code, hire_direction)).fetchall()
    for row in hires:
        rows.append({"entry_date": row["entry_date"], "reference": row["hire_no"], "entry_type": "Hire", "details": f"{row['asset_name']} / {row['status']}", "invoice_amount": 0.0, "payment_amount": 0.0, "note_amount": float(row["total_amount"])})
    for row in invoices:
        rows.append({"entry_date": row["issue_date"], "reference": row["invoice_no"], "entry_type": "Invoice", "details": row["status"] or "-", "invoice_amount": float(row["total_amount"]), "payment_amount": 0.0, "note_amount": float(row["balance_amount"])})
    payment_kind = "Received" if invoice_kind == "Sales" else "Paid"
    for row in payments:
        if (row["payment_kind"] or payment_kind) != payment_kind:
            continue
        rows.append({"entry_date": row["entry_date"], "reference": row["voucher_no"], "entry_type": "Payment", "details": row["payment_method"] or "-", "invoice_amount": 0.0, "payment_amount": float(row["amount"]), "note_amount": 0.0})
    rows.sort(key=lambda item: (item["entry_date"], item["reference"]))
    running_balance = 0.0
    for row in rows:
        running_balance = round(running_balance + row["invoice_amount"] - row["payment_amount"], 2)
        row["running_balance"] = running_balance
    total_invoiced = sum(row["invoice_amount"] for row in rows)
    total_paid = sum(row["payment_amount"] for row in rows)
    total_hires = sum(row["note_amount"] for row in rows if row["entry_type"] == "Hire")
    summary = {"total_hires": total_hires, "total_invoiced": total_invoiced, "total_paid": total_paid, "outstanding": max(total_invoiced - total_paid, 0.0)}
    return rows, summary
def _log_import_history(db, source_type: str, file_name: str, imported_count: int, notes: str = ""):
    db.execute(
        """
        INSERT INTO import_history (source_type, file_name, imported_count, notes)
        VALUES (?, ?, ?, ?)
        """,
        (source_type, file_name, imported_count, notes),
    )


def _chart_rows(rows):
    prepared = [{"label": row["label"], "value": int(row["value"])} for row in rows if row["label"]]
    if not prepared:
        return []
    max_value = max(item["value"] for item in prepared) or 1
    for item in prepared:
        item["width"] = max(8, int((item["value"] / max_value) * 100))
    return prepared


def _driver_search_clause(query: str):
    if not query:
        return "", []
    needle = f"%{query}%"
    return "WHERE (driver_id LIKE ? OR full_name LIKE ? OR vehicle_no LIKE ? OR phone_number LIKE ?)", [
        needle,
        needle,
        needle,
        needle,
    ]


def _driver_form_data(request):
    return {
        "driver_id": request.form.get("driver_id", "").strip(),
        "full_name": request.form.get("full_name", "").strip(),
        "phone_number": request.form.get("phone_number", "").strip(),
        "driver_pin": request.form.get("driver_pin", "").strip(),
        "confirm_driver_pin": request.form.get("confirm_driver_pin", "").strip(),
        "vehicle_no": request.form.get("vehicle_no", "").strip(),
        "shift": request.form.get("shift", "").strip(),
        "vehicle_type": request.form.get("vehicle_type", "").strip(),
        "basic_salary": request.form.get("basic_salary", "").strip(),
        "ot_rate": request.form.get("ot_rate", "").strip(),
        "duty_start": request.form.get("duty_start", "").strip(),
        "photo_name": request.form.get("photo_name", "").strip(),
        "status": request.form.get("status", "Active").strip() or "Active",
        "remarks": request.form.get("remarks", "").strip(),
    }


def _driver_insert_values(form, basic_salary: float, ot_rate: float, pin_hash: str, uploaded_photo=None):
    return (
        form["driver_id"],
        form["full_name"],
        _normalize_phone(form["phone_number"]),
        pin_hash,
        form["vehicle_no"],
        form["shift"],
        form["vehicle_type"],
        basic_salary,
        ot_rate,
        form["duty_start"],
        form["photo_name"],
        uploaded_photo["photo_data"] if uploaded_photo else "",
        uploaded_photo["photo_content_type"] if uploaded_photo else "",
        form["status"],
        form["remarks"],
    )


def _safe_float(value: str) -> float:
    return _parse_decimal(value, "Number", required=False, default=0.0)


def _parse_decimal(value: str, field_name: str, *, required: bool = True, default=None, minimum=None, maximum=None) -> float:
    text = (value or "").strip()
    if not text:
        if required:
            raise ValidationError(f"{field_name} is required.")
        return default
    try:
        amount = float(text)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be a valid number.") from exc
    if minimum is not None and amount < minimum:
        raise ValidationError(f"{field_name} must be {minimum:g} or greater.")
    if maximum is not None and amount > maximum:
        raise ValidationError(f"{field_name} must be {maximum:g} or less.")
    return amount


def _normalize_required_phone(value: str) -> str:
    normalized = _normalize_phone(value)
    if len(normalized) < 7:
        raise ValidationError("Phone number must contain at least 7 digits.")
    return normalized


def _driver_pin_hash_from_form(form, *, edit_mode: bool, existing_pin_hash: str = "") -> str:
    pin = form.get("driver_pin", "").strip()
    confirm_pin = form.get("confirm_driver_pin", "").strip()

    if edit_mode and not pin and not confirm_pin:
        return existing_pin_hash

    if not pin or not confirm_pin:
        raise ValidationError("Driver PIN and confirm PIN are required.")
    if pin != confirm_pin:
        raise ValidationError("Driver PIN and confirm PIN must match.")
    if not pin.isdigit() or len(pin) < 4:
        raise ValidationError("Driver PIN must be at least 4 digits.")
    return generate_password_hash(pin)


def _default_salary_form(salary_month: str, duty_start: str | None = None):
    normalized_month = _normalize_month(salary_month)
    return {
        "entry_date": date.today().isoformat(),
        "salary_month": normalized_month,
        "ot_month": _previous_month_value(normalized_month),
        "salary_mode": "full",
        "prorata_start_date": (duty_start or "").strip(),
        "ot_hours": "0",
        "personal_vehicle": "0",
        "remarks": "",
    }


def _salary_form_from_row(row):
    return {
        "entry_date": _date_only_value(row["entry_date"]),
        "salary_month": row["salary_month"],
        "ot_month": row["ot_month"] or _previous_month_value(row["salary_month"]),
        "salary_mode": (row["salary_mode"] or "full").strip().lower(),
        "prorata_start_date": _date_only_value(row["prorata_start_date"]) if row["prorata_start_date"] else "",
        "ot_hours": f"{float(row['ot_hours']):.2f}",
        "personal_vehicle": f"{float(row['personal_vehicle']):.2f}",
        "remarks": row["remarks"] or "",
    }


def _salary_preview_from_row(row):
    salary_month = _normalize_month(row["salary_month"])
    salary_mode = (row["salary_mode"] or "full").strip().lower()
    if salary_mode not in {"full", "prorata"}:
        salary_mode = "full"
    monthly_basic_salary = float(row["monthly_basic_salary"]) if row["monthly_basic_salary"] is not None else float(row["basic_salary"])
    daily_rate = float(row["daily_rate"]) if row["daily_rate"] is not None else round(monthly_basic_salary / 30.0, 6)
    return {
        "entry_date": _date_only_value(row["entry_date"]),
        "salary_month": salary_month,
        "ot_month": row["ot_month"] or _previous_month_value(salary_month),
        "salary_mode": salary_mode,
        "salary_mode_label": _salary_mode_label(salary_mode),
        "prorata_start_date": _date_only_value(row["prorata_start_date"]) if row["prorata_start_date"] else "",
        "salary_days": float(row["salary_days"]) if row["salary_days"] is not None else 30.0,
        "daily_rate": daily_rate,
        "monthly_basic_salary": monthly_basic_salary,
        "basic_salary": float(row["basic_salary"]),
        "ot_hours": float(row["ot_hours"]),
        "ot_rate": float(row["ot_rate"]),
        "ot_amount": float(row["ot_amount"]),
        "personal_vehicle": float(row["personal_vehicle"]),
        "net_salary": float(row["net_salary"]),
        "remarks": row["remarks"] or "",
        "cutoff_day": _salary_cutoff_day(salary_month),
    }


def _calculate_salary_preview(driver, form):
    salary_month = _normalize_month(form.get("salary_month", _current_month_value()))
    salary_mode = (form.get("salary_mode", "full") or "full").strip().lower()
    if salary_mode not in {"full", "prorata"}:
        salary_mode = "full"
    monthly_basic_salary = float(driver["basic_salary"])
    cutoff_day = _salary_cutoff_day(salary_month)
    daily_rate = round(monthly_basic_salary / 30.0, 6)
    prorata_start_date = ""
    salary_days = 30.0
    basic_salary = monthly_basic_salary
    if salary_mode == "prorata":
        prorata_start_date = (form.get("prorata_start_date", "") or "").strip() or (driver.get("duty_start", "") or "").strip()
        if not prorata_start_date:
            raise ValidationError("Prorata start date is required when salary mode is prorata.")
        try:
            start_date = datetime.strptime(prorata_start_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValidationError("Prorata start date is not valid.") from exc
        if start_date.strftime("%Y-%m") != salary_month:
            raise ValidationError("Prorata start date must be inside the selected salary month.")
        if start_date.day > cutoff_day:
            raise ValidationError(f"Prorata start date must be on or before day {cutoff_day} for this payroll month.")
        salary_days = float(cutoff_day - start_date.day + 1)
        basic_salary = round(daily_rate * salary_days, 2)
    ot_rate = float(driver["ot_rate"])
    ot_hours = _parse_decimal(form.get("ot_hours", "0"), "OT hours", required=False, default=0.0, minimum=0.0)
    personal_vehicle = _parse_decimal(form.get("personal_vehicle", "0"), "Personal / Vehicle", required=False, default=0.0)
    ot_amount = round(ot_hours * ot_rate, 2)
    net_salary = round(basic_salary + ot_amount + personal_vehicle, 2)
    return {
        "entry_date": form.get("entry_date", date.today().isoformat()),
        "salary_month": salary_month,
        "ot_month": form.get("ot_month", "").strip() or _previous_month_value(salary_month),
        "salary_mode": salary_mode,
        "salary_mode_label": _salary_mode_label(salary_mode),
        "prorata_start_date": prorata_start_date,
        "salary_days": salary_days,
        "daily_rate": daily_rate,
        "monthly_basic_salary": monthly_basic_salary,
        "basic_salary": basic_salary,
        "ot_hours": ot_hours,
        "ot_rate": ot_rate,
        "ot_amount": ot_amount,
        "personal_vehicle": personal_vehicle,
        "net_salary": net_salary,
        "remarks": form.get("remarks", ""),
        "cutoff_day": cutoff_day,
    }


def _driver_balance(db, driver_id: str) -> float:
    total_salary = db.execute(
        "SELECT COALESCE(SUM(net_salary), 0) FROM salary_store WHERE driver_id = ?",
        (driver_id,),
    ).fetchone()[0]
    total_deducted = db.execute(
        "SELECT COALESCE(SUM(total_deductions), 0) FROM salary_slips WHERE driver_id = ?",
        (driver_id,),
    ).fetchone()[0]
    return max(float(total_salary) - float(total_deducted), 0.0)


def _advance_summary(db, driver_id: str, exclude_salary_store_id: int | None = None) -> dict[str, float]:
    total_advance = float(
        db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM driver_transactions WHERE driver_id = ?",
            (driver_id,),
        ).fetchone()[0]
    )
    if exclude_salary_store_id is None:
        total_deducted = float(
            db.execute(
                "SELECT COALESCE(SUM(total_deductions), 0) FROM salary_slips WHERE driver_id = ?",
                (driver_id,),
            ).fetchone()[0]
        )
    else:
        total_deducted = float(
            db.execute(
                """
                SELECT COALESCE(SUM(total_deductions), 0)
                FROM salary_slips
                WHERE driver_id = ? AND salary_store_id != ?
                """,
                (driver_id, exclude_salary_store_id),
            ).fetchone()[0]
        )
    remaining_advance = max(total_advance - total_deducted, 0.0)
    return {
        "total_advance": total_advance,
        "total_deducted": total_deducted,
        "remaining_advance": remaining_advance,
    }


def _outstanding_advance(db, driver_id: str, exclude_salary_store_id: int | None = None) -> float:
    return _advance_summary(db, driver_id, exclude_salary_store_id)["remaining_advance"]


def _owner_fund_totals(db):
    incoming = float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM owner_fund_entries").fetchone()[0])
    outgoing_transactions = float(
        db.execute("SELECT COALESCE(SUM(amount), 0) FROM driver_transactions WHERE source = 'Owner Fund'").fetchone()[0]
    )
    outgoing_salary = float(
        db.execute("SELECT COALESCE(SUM(net_payable), 0) FROM salary_slips WHERE payment_source = 'Owner Fund'").fetchone()[0]
    )
    outgoing = outgoing_transactions + outgoing_salary
    return incoming, outgoing, incoming - outgoing


def _owner_fund_statement(db, reverse: bool = True):
    rows = []
    for entry in db.execute(
        """
        SELECT owner_name, entry_date, amount, received_by, details
        FROM owner_fund_entries
        ORDER BY entry_date ASC, id ASC
        """
    ).fetchall():
        rows.append(
            {
                "entry_date": entry["entry_date"],
                "reference": f"Owner Fund / {entry['owner_name']}",
                "party": entry["received_by"] or "-",
                "details": entry["details"] or "-",
                "incoming": float(entry["amount"]),
                "outgoing": 0.0,
            }
        )
    for entry in db.execute(
        """
        SELECT entry_date, driver_id, given_by, amount, details
        FROM driver_transactions
        WHERE source = 'Owner Fund'
        ORDER BY entry_date ASC, id ASC
        """
    ).fetchall():
        rows.append(
            {
                "entry_date": entry["entry_date"],
                "reference": f"Driver Txn / {entry['driver_id']}",
                "party": entry["given_by"] or "-",
                "details": entry["details"] or "-",
                "incoming": 0.0,
                "outgoing": float(entry["amount"]),
            }
        )
    for entry in db.execute(
        """
        SELECT generated_at, driver_id, paid_by, net_payable, salary_month
        FROM salary_slips
        WHERE payment_source = 'Owner Fund'
        ORDER BY generated_at ASC, id ASC
        """
    ).fetchall():
        rows.append(
            {
                "entry_date": _date_only_value(entry["generated_at"]),
                "reference": f"Salary Slip / {entry['driver_id']}",
                "party": entry["paid_by"] or "-",
                "details": f"Salary {entry['salary_month']}",
                "incoming": 0.0,
                "outgoing": float(entry["net_payable"]),
            }
        )
    rows.sort(key=lambda item: item["entry_date"])
    balance = 0.0
    for row in rows:
        balance += row["incoming"] - row["outgoing"]
        row["balance"] = balance
    if reverse:
        rows.reverse()
    return rows[:60] if reverse else rows


def _current_month_value() -> str:
    return date.today().strftime("%Y-%m")


def _normalize_month(value: str) -> str:
    if not value:
        return _current_month_value()
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%Y-%m")
    except ValueError:
        return _current_month_value()


def _previous_month_value(value: str) -> str:
    normalized = _normalize_month(value)
    month_date = datetime.strptime(f"{normalized}-01", "%Y-%m-%d")
    if month_date.month == 1:
        return f"{month_date.year - 1}-12"
    return f"{month_date.year}-{month_date.month - 1:02d}"


def _salary_cutoff_day(salary_month: str) -> int:
    normalized = _normalize_month(salary_month)
    year, month = [int(part) for part in normalized.split("-")]
    return min(monthrange(year, month)[1], 30)


def _salary_mode_label(value: str) -> str:
    return "Prorata From Duty Start" if value == "prorata" else "Full Salary (30-Day Basis)"


def _date_only_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _driver_output_dir(app: Flask, driver_id: str, *, driver=None, full_name: str | None = None) -> Path:
    drivers_root = Path(app.config["GENERATED_DIR"]) / "drivers"
    legacy_dir = drivers_root / driver_id
    existing_named_dir = next(
        (item for item in drivers_root.glob(f"*__{driver_id.lower()}") if item.is_dir()),
        None,
    )
    if existing_named_dir is not None:
        base_dir = existing_named_dir
    elif legacy_dir.exists() and any(legacy_dir.iterdir()):
        base_dir = legacy_dir
    else:
        if driver is not None:
            full_name = driver["full_name"]
        elif not full_name:
            db = open_db()
            found = _fetch_driver(db, driver_id)
            full_name = found["full_name"] if found else driver_id
        base_dir = drivers_root / _driver_folder_name(full_name or driver_id, driver_id)
    (base_dir / "salary_slips").mkdir(parents=True, exist_ok=True)
    (base_dir / "kata_pdfs").mkdir(parents=True, exist_ok=True)
    (base_dir / "timesheets").mkdir(parents=True, exist_ok=True)
    (base_dir / "profile").mkdir(parents=True, exist_ok=True)
    return base_dir


def _driver_folder_name(full_name: str, driver_id: str) -> str:
    safe = "".join(character if character.isalnum() else "-" for character in full_name.lower()).strip("-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    safe = safe or driver_id.lower()
    return f"{safe}__{driver_id.lower()}"


def _regenerate_kata_for_driver(app: Flask, db, driver):
    salary_rows = db.execute(
        """
        SELECT entry_date, salary_month, net_salary
        FROM salary_store
        WHERE driver_id = ?
        ORDER BY entry_date ASC, id ASC
        """,
        (driver["driver_id"],),
    ).fetchall()
    transactions = db.execute(
        """
        SELECT entry_date, txn_type, source, given_by, amount
        FROM driver_transactions
        WHERE driver_id = ?
        ORDER BY entry_date ASC, id ASC
        """,
        (driver["driver_id"],),
    ).fetchall()
    salary_slips = db.execute(
        """
        SELECT generated_at, salary_month, total_deductions, remaining_advance, net_payable, payment_source, paid_by
        FROM salary_slips
        WHERE driver_id = ?
        ORDER BY generated_at ASC, id ASC
        """,
        (driver["driver_id"],),
    ).fetchall()
    if not salary_rows and not transactions and not salary_slips:
        return None
    output_dir = _driver_output_dir(app, driver["driver_id"], driver=driver) / "kata_pdfs"
    return generate_kata_pdf(driver, salary_rows, transactions, salary_slips, str(output_dir), app.config["STATIC_ASSETS_DIR"])


def _save_driver_photo(app: Flask, driver_id: str, full_name: str, photo_file):
    if photo_file is None or not photo_file.filename:
        return None
    safe_name = secure_filename(photo_file.filename)
    if not safe_name:
        return None
    extension = Path(safe_name).suffix.lower() or ".jpg"
    target = _driver_output_dir(app, driver_id, full_name=full_name) / "profile" / f"photo{extension}"
    photo_bytes = photo_file.read()
    if not photo_bytes:
        return None
    target.write_bytes(photo_bytes)
    return {
        "photo_name": target.relative_to(app.config["GENERATED_DIR"]).as_posix(),
        "photo_data": base64.b64encode(photo_bytes).decode("ascii"),
        "photo_content_type": photo_file.mimetype or "image/jpeg",
    }


def _remove_driver_generated_files(app: Flask, driver) -> None:
    drivers_root = Path(app.config["GENERATED_DIR"]) / "drivers"
    candidates = {drivers_root / driver["driver_id"], drivers_root / _driver_folder_name(driver["full_name"], driver["driver_id"])}
    candidates.update(folder for folder in drivers_root.glob(f"*__{driver['driver_id'].lower()}") if folder.is_dir())

    for folder in candidates:
        try:
            resolved = folder.resolve()
            root_resolved = drivers_root.resolve()
        except FileNotFoundError:
            continue
        if folder.exists() and root_resolved in resolved.parents:
            shutil.rmtree(folder, ignore_errors=True)


def _driver_photo_url(app: Flask, driver) -> str | None:
    if driver and driver.get("photo_data"):
        return url_for("driver_photo", driver_id=driver["driver_id"])
    photo_name = driver["photo_name"] if driver and driver["photo_name"] else ""
    if not photo_name:
        return None
    photo_path = Path(app.config["GENERATED_DIR"]) / photo_name
    if photo_path.exists():
        return url_for("generated_file", filename=photo_name)
    return None


def _restore_generated_file(app: Flask, db, filename: str) -> str | None:
    slip = db.execute(
        """
        SELECT id, driver_id, salary_store_id, salary_month, total_deductions, available_advance,
               remaining_advance, payment_source, paid_by, net_payable, pdf_path
        FROM salary_slips
        WHERE pdf_path = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (filename,),
    ).fetchone()
    if slip is not None:
        return _rebuild_salary_slip_pdf(app, db, slip)

    invoice = db.execute(
        """
        SELECT invoice_no
        FROM account_invoices
        WHERE pdf_path = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (filename,),
    ).fetchone()
    if invoice is not None:
        return _regenerate_invoice_pdf(app, db, invoice["invoice_no"])

    if filename.startswith("drivers/") and "/kata_pdfs/" in filename:
        parts = filename.split("/")
        if len(parts) >= 2:
            folder_name = parts[1]
            resolved_driver_id = folder_name.rsplit("__", 1)[-1].upper() if "__" in folder_name else folder_name
            driver = _fetch_driver(db, resolved_driver_id)
            if driver is not None:
                return _regenerate_kata_for_driver(app, db, driver)

    if filename.startswith("owner_fund/"):
        incoming, outgoing, balance = _owner_fund_totals(db)
        statement = _owner_fund_statement(db, reverse=False)
        output_dir = Path(app.config["GENERATED_DIR"]) / "owner_fund"
        return generate_owner_fund_pdf(
            statement,
            {"incoming": incoming, "outgoing": outgoing, "balance": balance},
            str(output_dir),
            app.config["STATIC_ASSETS_DIR"],
        )

    return None


def _rebuild_salary_slip_pdf(app: Flask, db, slip) -> str | None:
    driver = _fetch_driver(db, slip["driver_id"])
    if driver is None:
        return None
    salary_row = db.execute(
        "SELECT * FROM salary_store WHERE id = ? AND driver_id = ?",
        (slip["salary_store_id"], slip["driver_id"]),
    ).fetchone()
    if salary_row is None:
        return None
    slip_payload = {
        "available_advance": float(slip["available_advance"]),
        "deduction_amount": float(slip["total_deductions"]),
        "remaining_advance": float(slip["remaining_advance"]),
        "payment_source": slip["payment_source"] or PAYMENT_SOURCES[0],
        "paid_by": slip["paid_by"] or "",
        "net_payable": float(slip["net_payable"]),
    }
    output_dir = _driver_output_dir(app, slip["driver_id"], driver=driver) / "salary_slips"
    return generate_salary_slip_pdf(
        driver,
        salary_row,
        slip_payload,
        str(output_dir),
        app.config["STATIC_ASSETS_DIR"],
        app.config["GENERATED_DIR"],
    )


def _invoice_output_dir(app: Flask) -> Path:
    output_dir = Path(app.config["GENERATED_DIR"]) / "invoices"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _invoice_line_rows(db, invoice_no: str):
    return db.execute(
        """
        SELECT line_no, description, quantity, unit_label, rate, subtotal
        FROM account_invoice_lines
        WHERE invoice_no = ?
        ORDER BY line_no ASC, id ASC
        """,
        (invoice_no,),
    ).fetchall()


def _regenerate_invoice_pdf(app: Flask, db, invoice_no: str) -> str | None:
    invoice = db.execute(
        """
        SELECT invoice_no, party_code, agreement_no, lpo_no, hire_no, invoice_kind, document_type,
               issue_date, due_date, subtotal, tax_percent, tax_amount, total_amount, paid_amount,
               balance_amount, status, notes, pdf_path
        FROM account_invoices
        WHERE invoice_no = ?
        """,
        (invoice_no,),
    ).fetchone()
    if invoice is None:
        return None
    party = _fetch_party(db, invoice["party_code"])
    if party is None:
        return None
    company_profile = _company_profile_values(db)
    line_rows = _invoice_line_rows(db, invoice_no)
    if not line_rows:
        fallback_description = invoice.get("notes") or invoice.get("hire_no") or invoice.get("document_type") or "Invoice line"
        line_rows = [
            {
                "line_no": 1,
                "description": fallback_description,
                "quantity": 1.0,
                "unit_label": "Lot",
                "rate": float(invoice["subtotal"] or 0.0),
                "subtotal": float(invoice["subtotal"] or 0.0),
            }
        ]
    output_path = generate_tax_invoice_pdf(
        company_profile,
        party,
        invoice,
        line_rows,
        str(_invoice_output_dir(app)),
        app.config["STATIC_ASSETS_DIR"],
    )
    relative_path = Path(output_path).relative_to(Path(app.config["GENERATED_DIR"])).as_posix()
    db.execute("UPDATE account_invoices SET pdf_path = ? WHERE invoice_no = ?", (relative_path, invoice_no))
    db.commit()
    return output_path


def _timesheet_total_for_month(db, driver_id: str, month_value: str) -> float:
    prefix = f"{month_value}-%"
    return float(
        db.execute(
            """
            SELECT COALESCE(SUM(work_hours), 0)
            FROM driver_timesheets
            WHERE driver_id = ? AND entry_date LIKE ?
            """,
            (driver_id, prefix),
        ).fetchone()[0]
    )


def _driver_month_calendar(db, driver_id: str, month_value: str):
    year, month = [int(part) for part in month_value.split("-")]
    total_days = monthrange(year, month)[1]
    rows = db.execute(
        """
        SELECT entry_date, work_hours, remarks
        FROM driver_timesheets
        WHERE driver_id = ? AND entry_date LIKE ?
        ORDER BY entry_date ASC
        """,
        (driver_id, f"{month_value}-%"),
    ).fetchall()
    by_day = {int(row["entry_date"][-2:]): row for row in rows}
    calendar_days = []
    for day in range(1, total_days + 1):
        iso_date = f"{month_value}-{day:02d}"
        row = by_day.get(day)
        work_hours = float(row["work_hours"]) if row else 0.0
        calendar_days.append(
            {
                "day": day,
                "date": iso_date,
                "entered": row is not None and work_hours > 0,
                "work_hours": work_hours,
                "remarks": (row["remarks"] or "") if row else "",
            }
        )
    return calendar_days


def _timesheet_month_summary(calendar_days):
    entered_days = sum(1 for item in calendar_days if item["entered"])
    total_hours = sum(item["work_hours"] for item in calendar_days if item["entered"])
    return {
        "entered_days": entered_days,
        "missing_days": len(calendar_days) - entered_days,
        "total_hours": total_hours,
    }


def _can_access_generated_file(filename: str) -> bool:
    role = _current_role()
    if role == "admin":
        return True
    if role == "owner":
        return filename.startswith("owner_fund/")
    if role == "driver":
        driver_id = _current_driver_id()
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        drivers_root = Path(current_app.config["GENERATED_DIR"]) / "drivers"
        prefixes = {f"drivers/{driver_id}/"}
        if driver is not None:
            prefixes.add(f"drivers/{_driver_folder_name(driver['full_name'], driver_id)}/")
        for folder in drivers_root.glob(f"*__{driver_id.lower()}"):
            if folder.is_dir():
                prefixes.add(f"drivers/{folder.name}/")
        return any(filename.startswith(prefix) for prefix in prefixes)
    return False


def _recent_generated_files(folder: Path, prefix: str):
    if not folder.exists():
        return []
    files = sorted(
        [item for item in folder.glob(f"{prefix}*.pdf") if item.is_file()],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return [f"owner_fund/{item.name}" for item in files[:6]]

