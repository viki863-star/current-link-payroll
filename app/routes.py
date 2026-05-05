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
    has_request_context,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
import re
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from flask_wtf.csrf import CSRFError

from .database import open_db
from .excel_import import load_driver_records, upsert_driver_records
from .pdf_driver_import import load_driver_records_from_pdf, load_driver_records_from_pdf_bytes
from .pdf_vehicle_import import load_vehicle_records_from_pdf_bytes
from .pdf_service import (
    format_month_label,
    generate_cash_supplier_kata_pdf,
    generate_cash_supplier_payment_voucher_pdf,
    generate_kata_pdf,
    generate_lpo_pdf,
    generate_owner_fund_pdf,
    generate_partnership_supplier_statement_pdf,
    generate_plain_supplier_statement_pdf,
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
    "Technician",
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
SUPPLIER_CASH_EARNING_BASIS_OPTIONS = ["Trips", "Hours", "Monthly", "Fixed"]
SUPPLIER_CASH_KATA_TYPE_OPTIONS = [
    ("all", "All Entries"),
    ("earning", "Earnings"),
    ("debit", "Debits / Loans"),
    ("payment", "Payments"),
]
LOAN_TYPE_OPTIONS = ["Given", "Recovered"]
FEE_TYPE_OPTIONS = ["Visa", "Vehicle"]
OWNER_FUND_MOVEMENT_OPTIONS = ["All", "Incoming", "Outgoing"]
SUPPLIER_RATE_BASIS_OPTIONS = ["Hours", "Days", "Trips", "Monthly", "Fixed"]
SUPPLIER_VOUCHER_STATUS_OPTIONS = ["Open", "Partially Paid", "Paid"]
SUPPLIER_SHIFT_MODE_OPTIONS = ["Single Shift", "Double Shift"]
SUPPLIER_PARTNERSHIP_MODE_OPTIONS = ["Standard", "Partnership"]
SUPPLIER_MODE_OPTIONS = ["Normal", "Partnership", "Managed", "Cash", "Loan"]
PARTNERSHIP_ENTRY_KIND_OPTIONS = ["Vehicle Expense", "Driver Salary", "OT / Allowance", "Other"]
PARTNERSHIP_PAID_BY_OPTIONS = ["Company", "Partner"]
PARTNERSHIP_SHIFT_OPTIONS = ["General", "Day", "Night"]
FLEET_SHIFT_MODE_OPTIONS = ["Single Shift", "Double Shift"]
FLEET_OWNERSHIP_MODE_OPTIONS = ["Standard", "Partnership"]
MAINTENANCE_TAX_MODE_OPTIONS = ["Without Tax", "Tax Invoice"]
MAINTENANCE_FUNDING_SOURCE_OPTIONS = ["Owner Fund", "Bank", "Owner Direct", "Technician Advance", "Workshop Credit", "Other"]
MAINTENANCE_ADVANCE_SOURCE_OPTIONS = ["Owner Fund", "Bank", "Owner Direct", "Other"]
MAINTENANCE_PAID_BY_OPTIONS = ["Company", "Partner"]
MAINTENANCE_SETTLEMENT_STATUS_OPTIONS = ["Open", "Settled"]
MAINTENANCE_TARGET_CLASS_OPTIONS = ["Own Fleet Vehicle", "Partnership Supplier Vehicle"]
MAINTENANCE_LINE_SLOTS = 4
BRANCH_STATUS_OPTIONS = ["Active", "Inactive"]
FINANCIAL_YEAR_STATUS_OPTIONS = ["Open", "Closed", "Archived"]
INVOICE_LINE_SLOTS = 4
ADMIN_WORKSPACE_ORDER = ["universal", "drivers", "suppliers-normal", "suppliers-partnership", "suppliers-managed", "suppliers-cash", "customers", "accounts", "technicians"]
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
    "suppliers-normal": {
        "label": "Suppliers",
        "eyebrow": "Supplier Desk",
        "title": "Supplier Desk",
        "summary": "Supplier vehicles, timesheets and payables.",
    },
    "suppliers-partnership": {
        "label": "Partnership Suppliers",
        "eyebrow": "Partnership Desk",
        "title": "Partnership Supplier Desk",
        "summary": "Shared vehicles, shifts, partner split and payable control.",
    },
    "suppliers-managed": {
        "label": "Managed Suppliers",
        "eyebrow": "Managed Desk",
        "title": "Managed Supplier Desk",
        "summary": "Admin-managed suppliers: quotations, LPOs, invoices.",
    },
    "suppliers-cash": {
        "label": "Cash Suppliers",
        "eyebrow": "Cash Desk",
        "title": "Cash Supplier Desk",
        "summary": "Trip-based cash suppliers: earnings, loans, payments.",
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
        "summary": "Fund, tax, reports and fleet.",
    },
    "technicians": {
        "label": "Field Staff",
        "eyebrow": "Field Staff Desk",
        "title": "Field Staff Desk",
        "summary": "Manage field staff, give owner cash, and review workshop, fuel, and general expense entries.",
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
        request_active = has_request_context()
        current_role = _current_role() if request_active else ""
        current_workspace = _current_admin_workspace() if current_role == "admin" else ""
        workspace_home_endpoint = _workspace_home_endpoint(current_workspace) if current_role == "admin" else ""
        return {
            "current_role": current_role,
            "current_driver_id": session.get("driver_id") if request_active else "",
            "current_user_name": session.get("display_name", "") if request_active else "",
            "is_admin": current_role == "admin",
            "is_driver": current_role == "driver",
            "is_owner": current_role == "owner",
            "is_supplier": current_role == "supplier",
            "current_supplier_party_code": session.get("supplier_party_code", "") if request_active else "",
            "current_admin_workspace": current_workspace,
            "current_workspace_meta": _current_workspace_meta(),
            "admin_workspace_links": _admin_workspace_links() if current_role == "admin" else [],
            "admin_module_links": _admin_module_links(current_workspace) if current_role == "admin" else [],
            "admin_workspace_home_endpoint": workspace_home_endpoint,
            "admin_workspace_home_url": url_for(workspace_home_endpoint) if request_active and workspace_home_endpoint else "",
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

        return render_template("login-premium.html", selected_role=selected_role)

    @app.get("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "success")
        return redirect(url_for("login"))

    @app.route("/supplier-register", methods=["GET", "POST"])
    def supplier_register():
        if _current_role():
            return redirect(url_for(_role_home_endpoint()))

        values = _default_supplier_registration_form()
        if request.method == "POST":
            values = _supplier_registration_form_data(request)
            db = open_db()
            try:
                payload = _prepare_supplier_registration_payload(db, values)
                db.execute(
                    """
                    INSERT INTO supplier_registration_requests (
                        request_no, company_name, contact_person, phone_number, email,
                        trn_no, trade_license_no, address, notes, user_id, password_hash,
                        approval_status, reviewed_by, reviewed_at, rejection_note, approved_party_code
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
                _audit_log(
                    db,
                    "supplier_registration_requested",
                    entity_type="supplier_registration",
                    entity_id=values["request_no"],
                    details=f"{values['company_name']} / {values['user_id']}",
                )
                db.commit()
                flash("Supplier registration submitted. We will review and approve it before login opens.", "success")
                return redirect(url_for("supplier_login"))
            except ValidationError as exc:
                flash(str(exc), "error")

        return render_template("supplier_register.html", values=values)

    @app.route("/supplier-activate", methods=["GET", "POST"])
    def supplier_activate():
        return redirect(url_for("supplier_register"))
    @app.route("/supplier-quotations", methods=["GET", "POST"])
    def supplier_quotations():
        if _current_role() != "supplier":
            return redirect(url_for("login"))

        db = open_db()
        party_code = session.get("supplier_party_code")

        if request.method == "POST":
            quotation_no = request.form.get("quotation_no", "").strip().upper()
            quotation_date = request.form.get("quotation_date", "").strip()
            job_title = request.form.get("job_title", "").strip()
            rate_basis = request.form.get("rate_basis", "").strip()
            amount = float(request.form.get("amount") or 0)
            notes = request.form.get("notes", "").strip()

            try:
                if not quotation_no:
                    raise ValidationError("Quotation number is required.")
                if not quotation_date:
                    raise ValidationError("Quotation date is required.")
                if not job_title:
                    raise ValidationError("Job title / description is required.")

                # ── Phase 6A: save optional quotation attachment ──────────────
                attachment_file = request.files.get("quotation_attachment")
                attachment_path = _save_supplier_quotation_attachment(
                    quotation_no, party_code, attachment_file
                ) or None
                # ─────────────────────────────────────────────────────────────

                db.execute("""
                    INSERT INTO supplier_quotation_submissions
                    (quotation_no, party_code, quotation_date, job_title, rate_basis, amount, notes,
                     attachment_path, review_status, created_by_role, created_by_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', 'supplier', ?)
                """, (quotation_no, party_code, quotation_date, job_title, rate_basis, amount, notes,
                       attachment_path, session.get("display_name", "")))

                _audit_log(
                    db,
                    "supplier_quotation_submitted",
                    entity_type="supplier_quotation",
                    entity_id=quotation_no,
                    details=f"Portal / {party_code} / {job_title}",
                )
                db.commit()
                flash("Quotation submitted successfully. Awaiting admin review.", "success")
                return redirect(url_for("supplier_quotations"))
            except ValidationError as exc:
                flash(str(exc), "error")

        quotations = db.execute("""
            SELECT * FROM supplier_quotation_submissions
            WHERE party_code = ?
            ORDER BY created_at DESC
        """, (party_code,)).fetchall()

        return render_template("supplier_quotations.html", quotations=quotations)

    @app.route("/admin/supplier-quotations", methods=["GET", "POST"])
    @_login_required("admin")
    def admin_supplier_quotations():
        _touch_admin_workspace("suppliers-normal")
        db = open_db()

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            quotation_id = request.form.get("quotation_id", "").strip()
            review_note = request.form.get("review_note", "").strip()
            reviewer = session.get("display_name", "") or "Admin"

            if action == "approve" and quotation_id:
                db.execute("""
                    UPDATE supplier_quotation_submissions
                    SET review_status = 'Approved', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP,
                        review_note = ?
                    WHERE id = ?
                """, (reviewer, review_note or None, quotation_id))
                _audit_log(db, "supplier_quotation_approved", entity_type="supplier_quotation",
                           entity_id=quotation_id, details=reviewer)
                flash("Quotation approved.", "success")

            elif action == "reject" and quotation_id:
                db.execute("""
                    UPDATE supplier_quotation_submissions
                    SET review_status = 'Rejected', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP,
                        review_note = ?
                    WHERE id = ?
                """, (reviewer, review_note or "Rejected", quotation_id))
                _audit_log(db, "supplier_quotation_rejected", entity_type="supplier_quotation",
                           entity_id=quotation_id, details=review_note or "Rejected")
                flash("Quotation rejected.", "success")

            else:
                flash("Invalid action.", "error")

            db.commit()
            return redirect(url_for("admin_supplier_quotations"))

        quotations = db.execute("""
            SELECT q.*, p.party_name,
                   l.lpo_no AS lpo_no, l.status AS lpo_status
            FROM supplier_quotation_submissions q
            LEFT JOIN parties p ON p.party_code = q.party_code
            LEFT JOIN lpos l ON l.quotation_no = q.quotation_no
            ORDER BY q.created_at DESC
        """).fetchall()

        return render_template("admin_supplier_quotations.html", quotations=quotations)

    # ── Phase 6B/C/D/E: Issue LPO from approved quotation ──────────────────────
    @app.route("/admin/quotations/<quotation_no>/issue-lpo", methods=["GET", "POST"])
    @_login_required("admin")
    def admin_issue_lpo(quotation_no: str):
        _touch_admin_workspace("suppliers-normal")
        db = open_db()
        quotation_no = quotation_no.strip().upper()
        q = _supplier_quotation_row(db, quotation_no)
        if q is None or (q["review_status"] or "") != "Approved":
            flash("Only approved quotations can have an LPO issued.", "error")
            return redirect(url_for("admin_supplier_quotations"))

        party = _fetch_supplier_party(db, q["party_code"])
        existing_lpo = db.execute(
            "SELECT lpo_no, status, pdf_path FROM lpos WHERE quotation_no = ? LIMIT 1",
            (quotation_no,),
        ).fetchone()
        company = db.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
        suggested_lpo_no = _next_reference_code(db, "lpos", "lpo_no", "LPO")

        if request.method == "POST":
            try:
                lpo_no = request.form.get("lpo_no", "").strip().upper() or suggested_lpo_no
                issue_date = request.form.get("issue_date", "").strip()
                valid_until = request.form.get("valid_until", "").strip()
                if not issue_date:
                    raise ValidationError("Issue date is required.")
                amount_raw = request.form.get("amount", "0").strip()
                tax_percent_raw = request.form.get("tax_percent", "5").strip()
                amount = _parse_decimal(amount_raw, "Amount", required=True, minimum=0.0)
                tax_percent = _parse_decimal(tax_percent_raw, "VAT %", required=False, default=0.0, minimum=0.0)
                tax_amount = round(amount * tax_percent / 100.0, 2)
                total_amount = round(amount + tax_amount, 2)
                description = request.form.get("description", "").strip()
                payment_terms = request.form.get("payment_terms", "").strip()
                delivery_terms = request.form.get("delivery_terms", "").strip()
                additional_terms = request.form.get("additional_terms", "").strip()
                notes = request.form.get("notes", "").strip()
                issued_by = session.get("display_name", "") or "Admin"

                _ensure_reference_available(db, "lpos", "lpo_no", lpo_no, "", "LPO number")

                db.execute(
                    """
                    INSERT INTO lpos (
                        lpo_no, party_code, quotation_no, issue_date, valid_until,
                        amount, tax_percent, description, job_title, payment_terms,
                        delivery_terms, additional_terms, notes, status, issued_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Issued', ?)
                    """,
                    (
                        lpo_no, q["party_code"], quotation_no, issue_date, valid_until or None,
                        amount, tax_percent, description, q.get("job_title") or "",
                        payment_terms, delivery_terms, additional_terms, notes, issued_by,
                    ),
                )

                lpo_data = {
                    "lpo_no": lpo_no,
                    "issue_date": issue_date,
                    "valid_until": valid_until,
                    "quotation_no": quotation_no,
                    "description": description,
                    "job_title": q.get("job_title") or "",
                    "amount": amount,
                    "tax_percent": tax_percent,
                    "tax_amount": tax_amount,
                    "total_amount": total_amount,
                    "payment_terms": payment_terms,
                    "delivery_terms": delivery_terms,
                    "additional_terms": additional_terms,
                    "notes": notes,
                }
                output_dir = Path(current_app.config["GENERATED_DIR"]) / "lpos"
                output_dir.mkdir(parents=True, exist_ok=True)
                pdf_path = generate_lpo_pdf(
                    company=company,
                    party=party,
                    lpo=lpo_data,
                    assets_dir=current_app.config["STATIC_ASSETS_DIR"],
                    output_dir=str(output_dir),
                )
                _mirror_generated_file(current_app, pdf_path)
                relative_pdf = Path(pdf_path).relative_to(current_app.config["GENERATED_DIR"]).as_posix()
                db.execute("UPDATE lpos SET pdf_path = ? WHERE lpo_no = ?", (relative_pdf, lpo_no))

                _audit_log(
                    db, "lpo_issued",
                    entity_type="lpo", entity_id=lpo_no,
                    details=f"{q['party_code']} / Quotation:{quotation_no} / AED {total_amount}",
                )
                db.commit()
                flash(f"LPO {lpo_no} issued and PDF generated successfully.", "success")
                return redirect(url_for("admin_supplier_quotations"))
            except ValidationError as exc:
                flash(str(exc), "error")

        return render_template(
            "admin_issue_lpo.html",
            quotation=q,
            party=party,
            existing_lpo=existing_lpo,
            lpo_no=suggested_lpo_no,
            company=company,
        )
    # ── End Phase 6 route ──────────────────────────────────────────────────────

    # ── Phase 7: Managed supplier admin routes ─────────────────────────────────

    @app.route("/admin/managed-quotation/<party_code>", methods=["GET", "POST"])
    @_login_required("admin")
    def admin_managed_quotation(party_code: str):
        """Admin creates a quotation on behalf of a managed supplier."""
        db = open_db()
        party_code = party_code.strip().upper()
        party = _fetch_supplier_party(db, party_code)
        if party is None:
            flash("Supplier not found.", "error")
            return redirect(url_for("managed_suppliers"))

        suggested_no = _next_reference_code(db, "supplier_quotation_submissions", "quotation_no", "QUO")

        if request.method == "POST":
            try:
                quotation_no = request.form.get("quotation_no", "").strip().upper() or suggested_no
                quotation_date = request.form.get("quotation_date", "").strip()
                job_title = request.form.get("job_title", "").strip()
                rate_basis = request.form.get("rate_basis", "").strip()
                amount = _parse_decimal(request.form.get("amount", "0"), "Amount", required=True, minimum=0.0)
                notes = request.form.get("notes", "").strip()

                if not quotation_date:
                    raise ValidationError("Quotation date is required.")
                if not job_title:
                    raise ValidationError("Job title is required.")

                _ensure_reference_available(db, "supplier_quotation_submissions", "quotation_no", quotation_no, "", "Quotation number")

                attachment_path = None
                attachment = request.files.get("quotation_attachment")
                if attachment and attachment.filename:
                    attachment_path = _save_supplier_quotation_attachment(quotation_no, party_code, attachment)

                db.execute(
                    """
                    INSERT INTO supplier_quotation_submissions (
                        quotation_no, party_code, quotation_date, job_title, rate_basis,
                        amount, notes, attachment_path, review_status,
                        created_by_role, created_by_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Approved', 'admin', ?)
                    """,
                    (
                        quotation_no, party_code, quotation_date, job_title,
                        rate_basis or None, amount, notes or None,
                        attachment_path, session.get("display_name", "") or "Admin",
                    ),
                )
                _audit_log(
                    db, "managed_quotation_created",
                    entity_type="quotation", entity_id=quotation_no,
                    details=f"{party_code} / AED {amount} / Auto-Approved",
                )
                db.commit()
                flash(f"Quotation {quotation_no} created and auto-approved.", "success")
                return redirect(url_for("supplier_detail", party_code=party_code, screen="billing"))
            except ValidationError as exc:
                flash(str(exc), "error")

        return render_template(
            "admin_managed_quotation.html",
            party=party,
            quotation_no=suggested_no,
        )

    @app.route("/admin/managed-invoice/<party_code>", methods=["GET", "POST"])
    @_login_required("admin")
    def admin_managed_invoice(party_code: str):
        """Admin enters an invoice on behalf of a managed supplier."""
        db = open_db()
        party_code = party_code.strip().upper()
        party = _fetch_supplier_party(db, party_code)
        if party is None:
            flash("Supplier not found.", "error")
            return redirect(url_for("managed_suppliers"))

        available_lpos = db.execute(
            "SELECT lpo_no, issue_date, amount, status, quotation_no, description, pdf_path FROM lpos WHERE party_code = ? ORDER BY issue_date DESC",
            (party_code,),
        ).fetchall()

        submission_values = _default_supplier_submission_form(db, party_code, source_channel="Managed")

        if request.method == "POST":
            try:
                submission_values = _supplier_submission_form_data(request, party_code, source_channel="Managed")
                payload = _prepare_supplier_submission_payload(
                    db, submission_values,
                    party_code=party_code,
                    source_channel="Managed",
                    created_by_role="admin",
                    created_by_name=session.get("display_name", "") or "Admin",
                )

                lpo_no = submission_values.get("lpo_no", "").strip()
                if lpo_no:
                    lpo_row = db.execute("SELECT lpo_no FROM lpos WHERE lpo_no = ? AND party_code = ?", (lpo_no, party_code)).fetchone()
                    if lpo_row is None:
                        raise ValidationError(f"LPO {lpo_no} not found for this supplier.")

                inv_attach = request.files.get("invoice_attachment")
                ts_attach = request.files.get("timesheet_attachment")
                inv_path = None
                ts_path = None
                if inv_attach and inv_attach.filename:
                    inv_dir = Path(current_app.config["GENERATED_DIR"]) / "supplier_invoices" / party_code.lower()
                    inv_dir.mkdir(parents=True, exist_ok=True)
                    ext = Path(inv_attach.filename).suffix.lower()
                    inv_path = str(inv_dir / f"{submission_values['submission_no'].lower()}_invoice{ext}")
                    inv_attach.save(inv_path)
                    _mirror_generated_file(current_app, inv_path)
                    inv_path = Path(inv_path).relative_to(current_app.config["GENERATED_DIR"]).as_posix()
                if ts_attach and ts_attach.filename:
                    ts_dir = Path(current_app.config["GENERATED_DIR"]) / "supplier_invoices" / party_code.lower()
                    ts_dir.mkdir(parents=True, exist_ok=True)
                    ext = Path(ts_attach.filename).suffix.lower()
                    ts_path = str(ts_dir / f"{submission_values['submission_no'].lower()}_timesheet{ext}")
                    ts_attach.save(ts_path)
                    _mirror_generated_file(current_app, ts_path)
                    ts_path = Path(ts_path).relative_to(current_app.config["GENERATED_DIR"]).as_posix()

                db.execute(
                    """
                    INSERT INTO supplier_invoice_submissions (
                        submission_no, party_code, lpo_no, source_channel, external_invoice_no,
                        period_month, invoice_date, subtotal, vat_amount, total_amount,
                        invoice_attachment_path, timesheet_attachment_path, notes,
                        review_status, created_by_role, created_by_name
                    ) VALUES (?, ?, ?, 'Managed', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Approved', 'admin', ?)
                    """,
                    (
                        submission_values["submission_no"], party_code,
                        lpo_no or None, submission_values.get("external_invoice_no", ""),
                        submission_values.get("period_month", ""),
                        submission_values.get("invoice_date", ""),
                        float(submission_values.get("subtotal", 0)),
                        float(submission_values.get("vat_amount", 0)),
                        float(submission_values.get("total_amount", 0)),
                        inv_path, ts_path,
                        submission_values.get("notes", ""),
                        session.get("display_name", "") or "Admin",
                    ),
                )
                _audit_log(
                    db, "managed_invoice_created",
                    entity_type="invoice", entity_id=submission_values["submission_no"],
                    details=f"{party_code} / AED {submission_values.get('total_amount', 0)} / Managed",
                )
                db.commit()
                flash(f"Invoice {submission_values['submission_no']} created for managed supplier.", "success")
                return redirect(url_for("supplier_detail", party_code=party_code, screen="billing"))
            except ValidationError as exc:
                flash(str(exc), "error")

        return render_template(
            "admin_managed_invoice.html",
            party=party,
            available_lpos=available_lpos,
            submission_values=submission_values,
        )

    # ── End Phase 7 managed supplier routes ────────────────────────────────────

    @app.route("/supplier-login", methods=["GET", "POST"])
    def supplier_login():
        if _current_role():
            return redirect(url_for(_role_home_endpoint()))
    
        values = {"user_id": ""}
    
        if request.method == "POST":
            values["user_id"] = request.form.get("user_id", "").strip()
            password = request.form.get("password", "").strip()
    
            db = open_db()
            identifier = _auth_identifier("supplier", supplier_code=values["user_id"])
            lock_info = _get_login_lock(db, "supplier", identifier)
    
            if lock_info["locked"]:
                flash(lock_info["message"], "error")
                _audit_log(
                    db,
                    "login_blocked",
                    entity_type="auth",
                    entity_id=values["user_id"] or "supplier",
                    status="blocked",
                    details=lock_info["message"],
                )
                db.commit()
                return render_template("supplier_login.html", values=values)
    
            try:
                account, party = _supplier_login_target(db, values["user_id"])
    
                if (account["activation_status"] or "") != "Approved":
                    raise ValidationError("Your supplier account is not approved yet. Please wait for admin approval.")
    
                if not password:
                    raise ValidationError("Supplier password is required.")
    
                if not account["password_hash"]:
                    raise ValidationError("Supplier account is not active yet.")
    
                if not check_password_hash(account["password_hash"], password):
                    raise ValidationError("Supplier password is not correct.")
    
                db.execute(
                    """
                    UPDATE supplier_portal_accounts
                    SET last_login_at = CURRENT_TIMESTAMP
                    WHERE party_code = ?
                    """,
                    (account["party_code"],),
                )
    
                _clear_failed_login(db, "supplier", identifier)
    
                _audit_log(
                    db,
                    "login_success",
                    entity_type="auth",
                    entity_id=account["party_code"],
                    details=f"Supplier login / {party['party_name']}",
                )
    
                db.commit()
    
                _set_session(
                    "supplier",
                    supplier_party_code=account["party_code"],
                    display_name=party["party_name"],
                )
    
                flash(f"Welcome {party['party_name']}.", "success")
    
                return redirect(url_for("supplier_portal"))
    
            except ValidationError as exc:
                _record_failed_login(db, "supplier", identifier)
    
                _audit_log(
                    db,
                    "login_failed",
                    entity_type="auth",
                    entity_id=values["user_id"] or "supplier",
                    status="failed",
                    details=str(exc),
                )
    
                db.commit()
    
                flash(_latest_login_error(db, "supplier", identifier, str(exc)), "error")
    
        return render_template("supplier_login.html", values=values)
    @app.route("/supplier-forgot-password", methods=["GET", "POST"])
    def supplier_forgot_password():
        if _current_role():
            return redirect(url_for(_role_home_endpoint()))

        values = {"user_id": "", "email": ""}
        if request.method == "POST":
            values["user_id"] = request.form.get("user_id", "").strip()
            values["email"] = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "").strip()
            confirm_password = request.form.get("confirm_password", "").strip()
            db = open_db()
            try:
                account, party = _supplier_reset_target(db, values["user_id"], values["email"])
                if len(password) < 6:
                    raise ValidationError("Password must be at least 6 characters.")
                if password != confirm_password:
                    raise ValidationError("Password confirmation does not match.")
                db.execute(
                    """
                    UPDATE supplier_portal_accounts
                    SET password_hash = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE party_code = ?
                    """,
                    (generate_password_hash(password), account["party_code"]),
                )
                _audit_log(
                    db,
                    "supplier_password_reset",
                    entity_type="supplier_portal",
                    entity_id=account["party_code"],
                    details=party["party_name"],
                )
                db.commit()
                flash("Password updated. You can sign in now.", "success")
                return redirect(url_for("supplier_login"))
            except ValidationError as exc:
                flash(str(exc), "error")

        return render_template("supplier_forgot_password.html", values=values)
    
    @app.route("/technician-login", methods=["GET", "POST"])
    def technician_login():
        if _current_role():
            return redirect(url_for(_role_home_endpoint()))
        
        values = {"user_id": ""}
        
        if request.method == "POST":
            values["user_id"] = request.form.get("user_id", "").strip()
            password = request.form.get("password", "").strip()
            
            db = open_db()
            identifier = _auth_identifier("technician", technician_code=values["user_id"])
            lock_info = _get_login_lock(db, "technician", identifier)
            
            if lock_info["locked"]:
                flash(lock_info["message"], "error")
                _audit_log(
                    db,
                    "login_blocked",
                    entity_type="auth",
                    entity_id=values["user_id"] or "technician",
                    status="blocked",
                    details=lock_info["message"],
                )
                db.commit()
                return render_template("technician_login.html", values=values)
            
            try:
                technician, party = _technician_login_target(db, values["user_id"])
                
                if (technician["status"] or "") != "Active":
                    raise ValidationError("Your field staff account is not active.")
                
                if not password:
                    raise ValidationError("Field staff password is required.")
                
                if not technician["password_hash"]:
                    raise ValidationError("Field staff password is not set yet.")
                
                if not check_password_hash(technician["password_hash"], password):
                    raise ValidationError("Field staff password is not correct.")
                
                _clear_failed_login(db, "technician", identifier)
                
                _audit_log(
                    db,
                    "login_success",
                    entity_type="auth",
                    entity_id=technician["technician_code"],
                    details=f"Field staff login / {technician.get('specialization', 'Field Staff')}",
                )
                
                db.commit()
                
                _set_session(
                    "technician",
                    display_name=f"Field Staff {technician['technician_code']}",
                )
                session["technician_code"] = technician["technician_code"]
                session["technician_party_code"] = technician["party_code"]
                
                flash(f"Welcome Field Staff {technician['technician_code']}.", "success")
                
                return redirect(url_for("technician_portal"))
                
            except ValidationError as exc:
                _record_failed_login(db, "technician", identifier)
                
                _audit_log(
                    db,
                    "login_failed",
                    entity_type="auth",
                    entity_id=values["user_id"] or "technician",
                    status="failed",
                    details=str(exc),
                )
                
                db.commit()
                
                flash(_latest_login_error(db, "technician", identifier, str(exc)), "error")
        
        return render_template("technician_login.html", values=values)
    
    @app.route("/admin/supplier-registrations", methods=["GET", "POST"])
    @_login_required("admin")
    def supplier_registrations():
        _touch_admin_workspace("suppliers-normal")
        db = open_db()

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            request_no = request.form.get("request_no", "").strip().upper()
            review_note = request.form.get("review_note", "").strip()
            reviewer = session.get("display_name", "") or "Admin"

            try:
                if action == "approve_registration":
                    party_code = _approve_supplier_registration(db, request_no, reviewer)
                    _audit_log(
                        db,
                        "supplier_registration_approved",
                        entity_type="supplier_registration",
                        entity_id=request_no,
                        details=party_code,
                    )
                    db.commit()
                    flash("Supplier registration approved successfully.", "success")

                elif action == "reject_registration":
                    _reject_supplier_registration(db, request_no, reviewer, review_note)
                    _audit_log(
                        db,
                        "supplier_registration_rejected",
                        entity_type="supplier_registration",
                        entity_id=request_no,
                        details=review_note or "Rejected",
                    )
                    db.commit()
                    flash("Supplier registration rejected.", "success")

                else:
                    flash("Invalid action.", "error")

            except ValidationError as exc:
                flash(str(exc), "error")

            return redirect(url_for("supplier_registrations"))

        rows = _supplier_registration_rows(db, limit=200)
        return render_template("supplier_registrations.html", rows=rows)


    @app.route("/portal/supplier", methods=["GET", "POST"])
    @_login_required("supplier")
    def supplier_portal():
        db = open_db()
        party_code = _current_supplier_party_code()
        available_lpos = db.execute("""
    SELECT lpo_no, issue_date, amount, status, quotation_no, description, pdf_path
    FROM lpos
    WHERE party_code = ?
      AND status IN ('Issued', 'Open', 'Approved')
    ORDER BY issue_date DESC, id DESC
""", (party_code,)).fetchall()
        party = _fetch_supplier_party(db, party_code)
        if party is None or _supplier_mode_for_party(db, party_code) != "Normal" or (party["party_kind"] or "") != "Company":
            session.clear()
            flash("Supplier portal access is no longer available for this account.", "error")
            return redirect(url_for("supplier_login"))

        portal_account = _supplier_portal_account_row(db, party_code)
        if portal_account is None or not int(portal_account["portal_enabled"] or 0):
            session.clear()
            flash("Supplier portal is disabled for this account.", "error")
            return redirect(url_for("supplier_login"))

        submission_values = _default_supplier_submission_form(db, party_code, source_channel="Portal")
        resubmit_submission = request.args.get("resubmit_submission", "").strip().upper()
        if request.method == "GET" and resubmit_submission:
            row = db.execute(
                """
                SELECT
                    submission_no,
                    party_code,
                    lpo_no,
                    external_invoice_no,
                    period_month,
                    invoice_date,
                    subtotal,
                    vat_amount,
                    total_amount,
                    notes,
                    review_note
                FROM supplier_invoice_submissions
                WHERE submission_no = ? AND party_code = ? AND review_status = 'Rejected'
                LIMIT 1
                """,
                (resubmit_submission, party_code),
            ).fetchone()
            if row is not None:
                submission_values = _supplier_submission_form_from_row(db, row, source_channel="Portal")
                flash("You can resubmit this invoice with corrected files or amounts.", "info")
        if request.method == "POST":
            action = request.form.get("action", "").strip()
            if action == "submit_invoice":
                submission_values = _supplier_submission_form_data(request, party_code, source_channel="Portal")
                try:
                    # ── LPO validation (STEP 3) ──────────────────────────────
                    lpo_no = submission_values.get("lpo_no", "").strip().upper()
                    if not lpo_no:
                        raise ValidationError(
                            "Please select an LPO before submitting an invoice."
                        )
                    lpo_row = db.execute(
                        """
                        SELECT lpo_no, party_code, status
                        FROM lpos
                        WHERE lpo_no = ? AND party_code = ?
                          AND status IN ('Issued', 'Open', 'Approved')
                        LIMIT 1
                        """,
                        (lpo_no, party_code),
                    ).fetchone()
                    if lpo_row is None:
                        raise ValidationError(
                            "Selected LPO is not valid or does not belong to your account. "
                            "Only open / approved LPOs may be invoiced."
                        )
                    # ────────────────────────────────────────────────────────
                    payload = _prepare_supplier_submission_payload(
                        db,
                        submission_values,
                        source_channel="Portal",
                        created_by_role="supplier",
                        created_by_name=party["party_name"],
                        invoice_file=request.files.get("invoice_attachment"),
                        timesheet_file=request.files.get("timesheet_attachment"),
                    )
                    db.execute(
                        """
                        INSERT INTO supplier_invoice_submissions (
                            submission_no, party_code, lpo_no, source_channel, external_invoice_no,
                            period_month, invoice_date, subtotal, vat_amount, total_amount,
                            invoice_attachment_path, timesheet_attachment_path, notes,
                            review_status, review_note, reviewed_by, reviewed_at,
                            linked_voucher_no, created_by_role, created_by_name
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (payload[0], payload[1], lpo_no, *payload[2:]),
                    )
                    _audit_log(
                        db,
                        "supplier_submission_created",
                        entity_type="supplier_submission",
                        entity_id=submission_values["submission_no"],
                        details=f"Portal / {party_code} / {submission_values['external_invoice_no']} / LPO:{lpo_no}",
                    )
                    db.commit()
                    flash("Invoice submitted successfully. It is now waiting for review.", "success")
                    return redirect(url_for("supplier_portal"))
                except ValidationError as exc:
                    flash(str(exc), "error")

        statement_rows, statement_summary = _supplier_statement_data(db, party_code, supplier_mode="Normal")
        return render_template(
            "supplier_portal.html",
            party=party,
            portal_account=portal_account,
            submission_values=submission_values,
            submissions=_supplier_submission_rows(db, party_code, limit=20),
            statement_rows=statement_rows,
            statement_summary=statement_summary,
            statement_pdf_url=url_for("supplier_portal_statement_pdf"),
            available_lpos=available_lpos,
        )

    @app.get("/portal/supplier/statement-pdf")
    @_login_required("supplier")
    def supplier_portal_statement_pdf():
        db = open_db()
        party_code = _current_supplier_party_code()
        party = _fetch_supplier_party(db, party_code)
        if party is None:
            flash("Supplier portal account was not found.", "error")
            return redirect(url_for("supplier_login"))
        statement_rows, statement_summary = _supplier_statement_data(db, party_code, supplier_mode="Normal")
        output_dir = _supplier_output_dir(app, party_code) / "portal_statements"
        pdf_path = generate_plain_supplier_statement_pdf(
            party,
            statement_rows,
            statement_summary,
            str(output_dir),
            title="Supplier Portal Statement",
        )
        _mirror_generated_file(app, pdf_path)
        relative_path = Path(pdf_path).relative_to(app.config["GENERATED_DIR"]).as_posix()
        return redirect(url_for("generated_file", filename=relative_path))

    @app.route("/portal/technician", methods=["GET", "POST"])
    @_login_required("technician")
    def technician_portal():
        db = open_db()
        technician_code = session.get("technician_code", "")
        party_code = session.get("technician_party_code", "")
        
        if not technician_code:
            session.clear()
            flash("Field staff session expired. Please login again.", "error")
            return redirect(url_for("technician_login"))
        
        # Fetch technician details
        technician = db.execute(
            """
            SELECT technician_code, party_code, user_id, phone_number,
                   specialization, status, created_at
            FROM technicians
            WHERE technician_code = ?
            """,
            (technician_code,)
        ).fetchone()
        
        if technician is None or (technician["status"] or "") != "Active":
            session.clear()
            flash("Field staff account is no longer active.", "error")
            return redirect(url_for("technician_login"))
        
        # Fetch party information
        party = None
        if party_code:
            party = db.execute(
                """
                SELECT party_code, party_name, party_kind, party_roles
                FROM parties
                WHERE party_code = ?
                """,
                (party_code,)
            ).fetchone()
        
        # Calculate technician statistics
        # Total jobs
        total_jobs = db.execute(
            """
            SELECT COUNT(*) as count
            FROM maintenance_papers
            WHERE technician_code = ?
            """,
            (technician_code,)
        ).fetchone()["count"] or 0
        
        total_received = db.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as total
            FROM maintenance_staff_advances
            WHERE staff_code = ?
            """,
            (technician_code,),
        ).fetchone()["total"] or 0

        # Total approved amount
        total_approved = db.execute(
            """
            SELECT COALESCE(SUM(total_amount), 0) as total
            FROM maintenance_papers
            WHERE technician_code = ? AND review_status = 'Approved'
            """,
            (technician_code,)
        ).fetchone()["total"] or 0

        total_spent = db.execute(
            """
            SELECT COALESCE(SUM(total_amount), 0) as total
            FROM maintenance_papers
            WHERE technician_code = ?
            """,
            (technician_code,)
        ).fetchone()["total"] or 0

        total_paid_to_vendors = db.execute(
            """
            SELECT COALESCE(SUM(paid_amount), 0) as total
            FROM maintenance_papers
            WHERE technician_code = ?
            """,
            (technician_code,)
        ).fetchone()["total"] or 0

        pending_review = db.execute(
            """
            SELECT COALESCE(SUM(total_amount), 0) as total
            FROM maintenance_papers
            WHERE technician_code = ? AND review_status = 'Pending'
            """,
            (technician_code,),
        ).fetchone()["total"] or 0

        balance_available = float(total_received or 0) - float(total_spent or 0)
        
        # Recent jobs (last 10) - updated to match actual schema
        recent_jobs = db.execute(
            """
            SELECT paper_no, paper_date as entry_date, vehicle_id,
                   work_summary as details,
                   supplier_bill_no as bill_no,
                   total_amount, review_status, payment_status,
                   work_type,
                   attachment_path as bill_image,
                   COALESCE(wp.party_name, workshop_party_code) as workshop_name
            FROM maintenance_papers mp
            LEFT JOIN parties wp ON mp.workshop_party_code = wp.party_code
            WHERE technician_code = ?
            ORDER BY paper_date DESC, paper_no DESC
            LIMIT 10
            """,
            (technician_code,)
        ).fetchall()
        
        # Top vehicles (most worked on) - vehicles with most jobs
        top_vehicles = db.execute(
            """
            SELECT
                COALESCE(vm.vehicle_no, 'General Entry') as vehicle_no,
                COALESCE(vm.make_model, mp.vehicle_id, 'General Work') as vehicle_name,
                COALESCE(vm.ownership_mode, 'General') as ownership_mode,
                COUNT(*) as job_count,
                COALESCE(SUM(mp.total_amount), 0) as total_spent
            FROM maintenance_papers mp
            LEFT JOIN vehicle_master vm ON mp.vehicle_id = vm.vehicle_id
            WHERE mp.technician_code = ? AND mp.vehicle_id IS NOT NULL AND mp.vehicle_id != ''
            GROUP BY mp.vehicle_id, vm.vehicle_no, vm.make_model, vm.ownership_mode
            ORDER BY job_count DESC, total_spent DESC
            LIMIT 5
            """,
            (technician_code,)
        ).fetchall()
        
        # Monthly expense analysis kept backend-neutral for SQLite/Postgres.
        monthly_rows = db.execute(
            """
            SELECT paper_date, total_amount, COALESCE(paid_amount, 0) as paid_amount
            FROM maintenance_papers
            WHERE technician_code = ?
            """,
            (technician_code,)
        ).fetchall()
        monthly_map = {}
        for row in monthly_rows:
            month_key = (row["paper_date"] or "")[:7]
            if not month_key:
                continue
            bucket = monthly_map.setdefault(
                month_key,
                {"month": month_key, "job_count": 0, "total_amount": 0.0, "paid_amount": 0.0},
            )
            bucket["job_count"] += 1
            bucket["total_amount"] += float(row["total_amount"] or 0)
            bucket["paid_amount"] += float(row["paid_amount"] or 0)
        monthly_expenses = sorted(monthly_map.values(), key=lambda item: item["month"], reverse=True)[:6]
        max_monthly_amount = max((item["total_amount"] for item in monthly_expenses), default=0.0)
        
        # Work type distribution
        work_type_distribution = db.execute(
            """
            SELECT
                work_type,
                COUNT(*) as job_count,
                COALESCE(SUM(total_amount), 0) as total_amount
            FROM maintenance_papers
            WHERE technician_code = ? AND work_type IS NOT NULL AND work_type != ''
            GROUP BY work_type
            ORDER BY total_amount DESC
            LIMIT 8
            """,
            (technician_code,)
        ).fetchall()
        
        # Vehicle options for new job form
        vehicle_options = db.execute(
            """
            SELECT vehicle_id, vehicle_no, make_model as vehicle_name, ownership_mode
            FROM vehicle_master
            WHERE status = 'Active'
            ORDER BY vehicle_no
            """
        ).fetchall()
        
        # Default form for new job
        default_form = {
            "entry_date": datetime.now().strftime("%Y-%m-%d"),
            "vehicle_id": "",
            "vehicle_no": "",
            "workshop_name": "",
            "bill_no": "",
            "work_type": "",
            "details": "",
            "amount": "",
            "tax_mode": "Inclusive",
            "tax_amount": "",
            "total_amount": "",
            "remarks": "",
        }
        
        form_values = default_form.copy()
        
        if request.method == "POST":
            action = request.form.get("action", "").strip()
            if action == "submit_job":
                # Handle job submission
                form_values = {
                    "entry_date": request.form.get("entry_date", "").strip(),
                    "vehicle_id": request.form.get("vehicle_id", "").strip(),
                    "vehicle_no": "",
                    "workshop_name": request.form.get("workshop_name", "").strip(),
                    "bill_no": request.form.get("bill_no", "").strip(),
                    "work_type": request.form.get("work_type", "").strip(),
                    "details": request.form.get("details", "").strip(),
                    "amount": request.form.get("amount", "").strip(),
                    "tax_mode": request.form.get("tax_mode", "").strip(),
                    "tax_amount": request.form.get("tax_amount", "").strip(),
                    "total_amount": request.form.get("total_amount", "").strip(),
                    "remarks": request.form.get("remarks", "").strip(),
                }
                
                # Basic validation
                errors = []
                selected_vehicle = None
                if not form_values["entry_date"]:
                    errors.append("Date is required")
                if form_values["vehicle_id"] == "GENERAL":
                    form_values["vehicle_id"] = None
                    form_values["vehicle_no"] = "GENERAL"
                elif not form_values["vehicle_id"]:
                    form_values["vehicle_id"] = None
                    form_values["vehicle_no"] = "GENERAL"
                else:
                    selected_vehicle = db.execute(
                        """
                        SELECT vehicle_id, vehicle_no, make_model, ownership_mode, source_type
                        FROM vehicle_master
                        WHERE vehicle_id = ?
                        """,
                        (form_values["vehicle_id"],),
                    ).fetchone()
                    if selected_vehicle is None:
                        errors.append("Selected vehicle was not found")
                    else:
                        form_values["vehicle_no"] = selected_vehicle["vehicle_no"] or form_values["vehicle_id"]
                if not form_values["workshop_name"]:
                    errors.append("Workshop/Shop name is required")
                if not form_values["bill_no"]:
                    errors.append("Bill number is required")
                if not form_values["work_type"]:
                    errors.append("Work type is required")
                if not form_values["amount"]:
                    errors.append("Amount is required")
                
                if errors:
                    for error in errors:
                        flash(error, "error")
                else:
                    # Generate paper_no
                    paper_no = _next_reference_code(db, "maintenance_papers", "paper_no", "MT")
                    
                    # Calculate amounts
                    try:
                        amount = float(form_values["amount"] or 0)
                        tax_amount = float(form_values["tax_amount"] or 0)
                        total_amount = float(form_values["total_amount"] or amount + tax_amount)
                    except ValueError:
                        amount = 0.0
                        tax_amount = 0.0
                        total_amount = 0.0
                    
                    try:
                        workshop_party_code = _ensure_workshop_party(db, form_values["workshop_name"])
                        attachment_path = _save_maintenance_attachment(app, paper_no, request.files.get("attachment"))
                        db.execute(
                            """
                            INSERT INTO maintenance_papers (
                                paper_no, paper_date, vehicle_id, vehicle_no, workshop_party_code, supplier_bill_no,
                                work_type, work_summary, subtotal, tax_mode, tax_amount, total_amount,
                                attachment_path, notes, technician_code, review_status, payment_status, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', 'Pending', CURRENT_TIMESTAMP)
                            """,
                            (
                                paper_no,
                                form_values["entry_date"],
                                form_values["vehicle_id"],
                                form_values["vehicle_no"],
                                workshop_party_code,
                                form_values["bill_no"],
                                form_values["work_type"],
                                form_values["details"],
                                amount,
                                form_values["tax_mode"],
                                tax_amount,
                                total_amount,
                                attachment_path,
                                form_values["remarks"],
                                technician_code,
                            )
                        )
                        
                        _audit_log(
                            db,
                            "technician_job_submitted",
                            entity_type="maintenance_paper",
                            entity_id=paper_no,
                            details=f"Technician {technician_code} submitted job {paper_no}",
                        )
                        
                        db.commit()
                        flash(f"Entry {paper_no} submitted successfully. Waiting for admin review.", "success")
                        return redirect(url_for("technician_portal"))
                    except Exception as exc:
                        db.rollback()
                        flash(f"Error submitting field staff entry: {exc}", "error")
        
        return render_template(
            "technician_portal.html",
            technician=technician,
            party=party,
            total_jobs=total_jobs,
            total_received=total_received,
            total_spent=total_spent,
            balance_available=balance_available,
            pending_review=pending_review,
            total_approved=total_approved,
            total_paid=total_paid_to_vendors,
            top_vehicles=top_vehicles,
            monthly_expenses=monthly_expenses,
            max_monthly_amount=max_monthly_amount,
            work_type_distribution=work_type_distribution,
            recent_jobs=recent_jobs,
            vehicle_options=vehicle_options,
            form_values=form_values,
        )
    
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

    @app.route("/supplier-desk", methods=["GET"])
    @_login_required("admin")
    def supplier_desk_home():
        """Supplier Desk Home Page - shows 4 cards for different supplier types"""
        db = open_db()
        query = request.args.get("q", "").strip()
        
        # Get stats for each supplier type
        stats = {
            "total_suppliers": 0,
            "online_count": 0,
            "cash_count": 0,
            "managed_count": 0,
            "partnership_count": 0,
            "total_outstanding": 0.0,
            # Detailed stats for each card
            "online_registrations": 0,
            "online_quotations": 0,
            "online_lpos": 0,
            "cash_trips": 0,
            "cash_advances": 0,
            "cash_balance": 0.0,
            "managed_quotations": 0,
            "managed_lpos": 0,
            "managed_invoices": 0,
            "partnership_splits": 0,
            "partnership_vouchers": 0,
            "partnership_statements": 0
        }
        
        # Helper function to get count for a specific supplier mode
        def get_supplier_count(modes, label):
            if isinstance(modes, str):
                normalized_modes = [modes]
            else:
                normalized_modes = list(modes)
            normalized_modes = [mode if mode in SUPPLIER_MODE_OPTIONS else "Normal" for mode in normalized_modes] or ["Normal"]
            placeholders = ", ".join("?" for _ in normalized_modes)
            result = _safe_dashboard_scalar(
                db,
                f"""
                SELECT COUNT(*)
                FROM parties p
                LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
                WHERE p.party_roles LIKE ? AND COALESCE(profile.supplier_mode, 'Normal') IN ({placeholders})
                """,
                ("%Supplier%", *normalized_modes),
                default=0,
                label=label,
            )
            return int(result or 0)
        
        # Get counts for each type
        stats["online_count"] = get_supplier_count("Normal", "supplier desk online count")
        cash_directory_summary = _cash_supplier_directory_summary(_cash_supplier_directory_rows(db, active_only=True))
        stats["cash_count"] = int(cash_directory_summary["supplier_count"])
        stats["managed_count"] = get_supplier_count("Managed", "supplier desk managed count")
        stats["partnership_count"] = get_supplier_count("Partnership", "supplier desk partnership count")
        stats["total_suppliers"] = sum([
            stats["online_count"],
            stats["cash_count"],
            stats["managed_count"],
            stats["partnership_count"]
        ])
        
        # Get total outstanding (simplified - sum of all supplier outstanding)
        total_outstanding_result = _safe_dashboard_scalar(
            db,
            """
            SELECT COALESCE(SUM(balance_amount), 0)
            FROM supplier_vouchers
            WHERE status IN ('Open', 'Partially Paid')
            """,
            default=0.0,
            label="supplier desk total outstanding",
        )
        stats["total_outstanding"] = float(total_outstanding_result or 0.0)
        
        # Get detailed statistics for Online Suppliers
        # Count supplier registrations (pending approval)
        registrations_result = _safe_dashboard_scalar(
            db,
            """
            SELECT COUNT(*)
            FROM supplier_registration_requests
            WHERE approval_status = 'Pending Approval'
            """,
            default=0,
            label="supplier desk online registrations",
        )
        stats["online_registrations"] = int(registrations_result or 0)
        
        # Count quotations for online suppliers
        quotations_result = _safe_dashboard_scalar(
            db,
            """
            SELECT COUNT(*)
            FROM supplier_quotation_submissions
            WHERE review_status IN ('Pending', 'Submitted')
            """,
            default=0,
            label="supplier desk online quotations",
        )
        stats["online_quotations"] = int(quotations_result or 0)
        
        # Count LPOs for online suppliers
        lpos_result = _safe_dashboard_scalar(
            db,
            """
            SELECT COUNT(*)
            FROM lpos
            WHERE status IN ('Issued', 'Pending')
            """,
            default=0,
            label="supplier desk online lpos",
        )
        stats["online_lpos"] = int(lpos_result or 0)
        
        # Get cash/loan supplier statistics (trips, advances, balance)
        # Count cash/loan supplier trips (timesheets)
        cash_trips_result = _safe_dashboard_scalar(
            db,
            """
            SELECT COUNT(*)
            FROM cash_supplier_trips st
            JOIN supplier_profile p ON st.party_code = p.party_code
            JOIN parties party ON party.party_code = st.party_code
            WHERE p.supplier_mode IN ('Cash', 'Loan') AND party.status = 'Active'
            """,
            default=0,
            label="supplier desk cash trips",
        )
        stats["cash_trips"] = int(cash_trips_result or 0)
        
        # Count cash/loan supplier advances
        cash_advances_result = _safe_dashboard_scalar(
            db,
            """
            SELECT COUNT(*)
            FROM cash_supplier_debits debit
            JOIN supplier_profile p ON debit.party_code = p.party_code
            JOIN parties party ON party.party_code = debit.party_code
            WHERE p.supplier_mode IN ('Cash', 'Loan') AND party.status = 'Active'
            """,
            default=0,
            label="supplier desk cash advances",
        )
        stats["cash_advances"] = int(cash_advances_result or 0)
        
        # Calculate cash/loan supplier total balance
        stats["cash_balance"] = float(cash_directory_summary["outstanding_total"] or 0.0)
        
        # Get managed supplier statistics
        # Count managed supplier quotations
        managed_quotations_result = _safe_dashboard_scalar(
            db,
            """
            SELECT COUNT(*)
            FROM supplier_quotation_submissions q
            JOIN supplier_profile p ON q.party_code = p.party_code
            WHERE p.supplier_mode = 'Managed'
            """,
            default=0,
            label="supplier desk managed quotations",
        )
        stats["managed_quotations"] = int(managed_quotations_result or 0)
        
        # Count managed supplier LPOs
        managed_lpos_result = _safe_dashboard_scalar(
            db,
            """
            SELECT COUNT(*)
            FROM lpos l
            JOIN supplier_profile p ON l.party_code = p.party_code
            WHERE p.supplier_mode = 'Managed'
            """,
            default=0,
            label="supplier desk managed lpos",
        )
        stats["managed_lpos"] = int(managed_lpos_result or 0)
        
        # Count managed supplier invoices
        managed_invoices_result = _safe_dashboard_scalar(
            db,
            """
            SELECT COUNT(*)
            FROM account_invoices i
            JOIN supplier_profile p ON i.party_code = p.party_code
            WHERE p.supplier_mode = 'Managed'
            """,
            default=0,
            label="supplier desk managed invoices",
        )
        stats["managed_invoices"] = int(managed_invoices_result or 0)
        
        # Get partnership supplier statistics
        # Count partnership entries
        partnership_splits_result = _safe_dashboard_scalar(
            db,
            """
            SELECT COUNT(*)
            FROM supplier_partnership_entries
            """,
            default=0,
            label="supplier desk partnership splits",
        )
        stats["partnership_splits"] = int(partnership_splits_result or 0)
        
        # Count partnership vouchers
        partnership_vouchers_result = _safe_dashboard_scalar(
            db,
            """
            SELECT COUNT(*)
            FROM supplier_vouchers sv
            JOIN supplier_profile p ON sv.party_code = p.party_code
            WHERE p.supplier_mode = 'Partnership'
            """,
            default=0,
            label="supplier desk partnership vouchers",
        )
        stats["partnership_vouchers"] = int(partnership_vouchers_result or 0)
        
        # Count partnership statements (distinct months with entries)
        partnership_statements_result = _safe_dashboard_scalar(
            db,
            """
            SELECT COUNT(DISTINCT SUBSTR(entry_date, 1, 7))
            FROM supplier_partnership_entries
            """,
            default=0,
            label="supplier desk partnership statements",
        )
        stats["partnership_statements"] = int(partnership_statements_result or 0)
        
        return render_template(
            "supplier_desk_home.html",
            stats=stats,
            query=query
        )

    @app.route("/suppliers", methods=["GET"])
    @_login_required("admin")
    def suppliers():
        supplier_mode = "Normal"
        _touch_admin_workspace(_supplier_mode_workspace_key(supplier_mode))
        db = open_db()
        query = request.args.get("q", "").strip()
        edit_party_code = request.args.get("edit", "").strip().upper()
        if edit_party_code:
            return redirect(url_for("admin_supplier_register", mode=supplier_mode, edit=edit_party_code))

        context = _supplier_cards_context(db, supplier_mode, query=query)
        context.update(
            {
                "desk_title": "Online Supplier Desk",
                "supplier_type_label": "Online Supplier",
                "toolbar_links": [
                    {"label": "Register Online Supplier", "href": url_for("admin_supplier_register", mode=supplier_mode), "primary": True},
                ],
                "empty_title": "No Online Suppliers Found",
                "empty_copy": "Add your first online supplier to get started.",
            }
        )
        return render_template("supplier_mode_cards.html", **context)

    @app.route("/suppliers/admin/register", methods=["GET", "POST"])
    @_login_required("admin")
    def admin_supplier_register():
        requested_mode = (request.args.get("mode", "Normal").strip().title() or "Normal")
        supplier_mode = requested_mode if requested_mode in {"Normal", "Managed", "Partnership"} else "Normal"
        db = open_db()
        values = _default_supplier_form(supplier_mode)
        edit_party_code = request.args.get("edit", "").strip().upper()
        if edit_party_code:
            existing_party = _fetch_party(db, edit_party_code)
            if existing_party is not None and "Supplier" in _deserialize_party_roles(existing_party["party_roles"] or ""):
                supplier_mode = _supplier_mode_for_party(db, edit_party_code)
                values = _supplier_form_from_party(
                    existing_party,
                    _supplier_profile_row(db, edit_party_code),
                    _supplier_portal_account_row(db, edit_party_code),
                )

        if request.method == "POST":
            values = _supplier_form_data(request, supplier_mode)
            try:
                message = _save_admin_supplier_record(db, values)
                db.commit()
                flash(message, "success")
                return redirect(url_for(_supplier_cards_endpoint(values["supplier_mode"])))
            except ValidationError as exc:
                flash(str(exc), "error")
            except Exception:
                current_app.logger.exception("Supplier save failed for %s", values.get("party_code") or values.get("original_party_code") or "new")
                flash("Supplier save failed. Please check portal email and supplier details, then try again.", "error")

        return render_template(
            "supplier_mode_register.html",
            values=values,
            supplier_mode=supplier_mode,
            summary=_supplier_hub_summary(db, supplier_mode),
            role_options=[item for item in PARTY_ROLE_OPTIONS if item != "Supplier"],
            desk_title="Online Supplier Desk",
            supplier_type_label="Online Supplier",
            desk_endpoint="suppliers",
            cards_endpoint=_supplier_cards_endpoint(supplier_mode),
            toolbar_links=[
                {"label": "Back to Cards", "href": url_for(_supplier_cards_endpoint(supplier_mode))},
            ],
            partner_parties=_supplier_partner_parties(db),
        )

    @app.route("/suppliers/partnership", methods=["GET", "POST"])
    @_login_required("admin")
    def partnership_suppliers():
        supplier_mode = "Partnership"
        _touch_admin_workspace(_supplier_mode_workspace_key(supplier_mode))
        db = open_db()
        values = _default_supplier_form(supplier_mode)
        query = request.args.get("q", "").strip()
        edit_party_code = request.args.get("edit", "").strip().upper()
        if edit_party_code:
            existing_party = _fetch_party(db, edit_party_code)
            if existing_party is not None and "Supplier" in _deserialize_party_roles(existing_party["party_roles"] or ""):
                values = _supplier_form_from_party(
                    existing_party,
                    _supplier_profile_row(db, edit_party_code),
                    _supplier_portal_account_row(db, edit_party_code),
                )

        if request.method == "POST":
            values = _supplier_form_data(request, supplier_mode)
            try:
                message = _save_admin_supplier_record(db, values)
                db.commit()
                flash(message, "success")
                return redirect(url_for("partnership_supplier_cards"))
            except ValidationError as exc:
                flash(str(exc), "error")
            except Exception:
                current_app.logger.exception("Partnership supplier save failed for %s", values.get("party_code") or values.get("original_party_code") or "new")
                flash("Supplier save failed. Please review the partnership details and try again.", "error")

        return render_template(
            "supplier_mode_register.html",
            values=values,
            summary=_supplier_hub_summary(db, supplier_mode),
            role_options=[item for item in PARTY_ROLE_OPTIONS if item != "Supplier"],
            supplier_mode=supplier_mode,
            desk_title="Partnership Supplier Desk",
            desk_endpoint="partnership_suppliers",
            cards_endpoint="partnership_supplier_cards",
            supplier_type_label="Partnership Supplier",
            toolbar_links=[
                {"label": "Back to Cards", "href": url_for("partnership_supplier_cards")},
            ],
            partner_parties=_supplier_partner_parties(db),
        )

    @app.route("/suppliers/managed", methods=["GET", "POST"])
    @_login_required("admin")
    def managed_suppliers():
        supplier_mode = "Managed"
        _touch_admin_workspace(_supplier_mode_workspace_key(supplier_mode))
        db = open_db()
        values = _default_supplier_form(supplier_mode)
        query = request.args.get("q", "").strip()
        edit_party_code = request.args.get("edit", "").strip().upper()
        if edit_party_code:
            existing_party = _fetch_party(db, edit_party_code)
            if existing_party is not None and "Supplier" in _deserialize_party_roles(existing_party["party_roles"] or ""):
                values = _supplier_form_from_party(
                    existing_party,
                    _supplier_profile_row(db, edit_party_code),
                    _supplier_portal_account_row(db, edit_party_code),
                )

        if request.method == "POST":
            values = _supplier_form_data(request, supplier_mode)
            try:
                message = _save_admin_supplier_record(db, values)
                db.commit()
                flash(message, "success")
                return redirect(url_for("managed_supplier_cards"))
            except ValidationError as exc:
                flash(str(exc), "error")
            except Exception:
                current_app.logger.exception("Managed supplier save failed for %s", values.get("party_code") or values.get("original_party_code") or "new")
                flash("Supplier save failed. Please review the details and try again.", "error")

        return render_template(
            "supplier_mode_register.html",
            values=values,
            summary=_supplier_hub_summary(db, supplier_mode),
            role_options=[item for item in PARTY_ROLE_OPTIONS if item != "Supplier"],
            supplier_mode=supplier_mode,
            desk_title="Managed Supplier Desk",
            desk_endpoint="managed_suppliers",
            cards_endpoint="managed_supplier_cards",
            supplier_type_label="Managed Supplier",
            toolbar_links=[
                {"label": "Back to Cards", "href": url_for("managed_supplier_cards")},
            ],
            partner_parties=_supplier_partner_parties(db),
        )

    @app.route("/suppliers/managed/cards", methods=["GET"])
    @_login_required("admin")
    def managed_supplier_cards():
        supplier_mode = "Managed"
        _touch_admin_workspace(_supplier_mode_workspace_key(supplier_mode))
        db = open_db()
        query = request.args.get("q", "").strip()
        context = _supplier_cards_context(db, supplier_mode, query=query)
        context.update(
            {
                "desk_title": "Managed Supplier Desk",
                "supplier_type_label": "Managed Supplier",
                "toolbar_links": [
                    {"label": "Register Managed Supplier", "href": url_for("managed_suppliers"), "primary": True},
                ],
                "empty_title": "No Managed Suppliers Found",
                "empty_copy": "Register your first managed supplier to start quotations and invoices.",
            }
        )
        return render_template("supplier_mode_cards.html", **context)

    @app.route("/suppliers/partnership/cards", methods=["GET"])
    @_login_required("admin")
    def partnership_supplier_cards():
        supplier_mode = "Partnership"
        _touch_admin_workspace(_supplier_mode_workspace_key(supplier_mode))
        db = open_db()
        query = request.args.get("q", "").strip()
        context = _supplier_cards_context(db, supplier_mode, query=query)
        context.update(
            {
                "desk_title": "Partnership Supplier Desk",
                "supplier_type_label": "Partnership Supplier",
                "toolbar_links": [
                    {"label": "Register Partnership Supplier", "href": url_for("partnership_suppliers"), "primary": True},
                ],
                "empty_title": "No Partnership Suppliers Found",
                "empty_copy": "Register your first partnership supplier to track split results and statements.",
            }
        )
        return render_template("supplier_mode_cards.html", **context)

    @app.route("/suppliers/cash", methods=["GET", "POST"])
    @_login_required("admin")
    def cash_suppliers():
        supplier_mode = "Cash"
        _touch_admin_workspace(_supplier_mode_workspace_key(supplier_mode))
        db = open_db()
        values = _default_supplier_form(supplier_mode)
        query = request.args.get("q", "").strip()
        edit_party_code = request.args.get("edit", "").strip().upper()
        if edit_party_code:
            existing_party = _fetch_party(db, edit_party_code)
            if existing_party is not None and "Supplier" in _deserialize_party_roles(existing_party["party_roles"] or ""):
                values = _supplier_form_from_party(
                    existing_party,
                    _supplier_profile_row(db, edit_party_code),
                    _supplier_portal_account_row(db, edit_party_code),
                )

        if request.method == "POST":
            values = _supplier_form_data(request, supplier_mode)
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
                    _upsert_supplier_profile(db, payload[0], values)
                    _audit_log(db, "supplier_updated", entity_type="supplier", entity_id=payload[0], details=f"{payload[1]} / Cash")
                    message = "Cash supplier updated."
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
                    _upsert_supplier_profile(db, payload[0], values)
                    _audit_log(db, "supplier_created", entity_type="supplier", entity_id=payload[0], details=f"{payload[1]} / Cash")
                    message = "Cash supplier created."
                db.commit()
                flash(message, "success")
                return redirect(url_for("cash_supplier_cards"))
            except ValidationError as exc:
                flash(str(exc), "error")
            except Exception:
                current_app.logger.exception("Cash supplier save failed")
                flash("Supplier save failed.", "error")

        cash_supplier_rows = _cash_supplier_directory_rows(db, active_only=True)
        summary = _cash_supplier_directory_summary(cash_supplier_rows)
        return render_template(
            "cash_suppliers_clean.html",
            values=values,
            query=query,
            summary=summary,
            role_options=[item for item in PARTY_ROLE_OPTIONS if item != "Supplier"],
            supplier_mode=supplier_mode,
            desk_title="Cash & Loan Supplier Desk",
            detail_endpoint="supplier_detail",
            desk_endpoint="cash_suppliers",
            counterpart_endpoint="suppliers",
            counterpart_label="Portal Desk",
            partner_parties=_supplier_partner_parties(db),
        )

    @app.route("/suppliers/cash/cards", methods=["GET"])
    @_login_required("admin")
    def cash_supplier_cards():
        _touch_admin_workspace(_supplier_mode_workspace_key("Cash"))
        db = open_db()
        query = request.args.get("q", "").strip()
        suppliers = _cash_supplier_directory_rows(db, query=query, active_only=True)
        summary = _cash_supplier_directory_summary(suppliers)
        return render_template(
            "cash_supplier_cards.html",
            query=query,
            suppliers=suppliers,
            summary=summary,
        )

    @app.route("/suppliers/<party_code>", methods=["GET", "POST"])
    @_login_required("admin")
    def supplier_detail(party_code: str):
        db = open_db()
        party = _fetch_supplier_party(db, party_code)
        if party is None:
            flash("Supplier was not found.", "error")
            return redirect(url_for("suppliers"))

        supplier_mode = _supplier_mode_for_party(db, party_code)
        _touch_admin_workspace(_supplier_mode_workspace_key(supplier_mode))
        active_screen = _normalize_supplier_screen(request.args.get("screen", ""), supplier_mode)

        asset_values = _apply_supplier_mode_to_asset_values(db, _default_supplier_asset_form(db, party_code), supplier_mode, party_code)
        timesheet_values = _default_supplier_timesheet_form(db, party_code)
        voucher_values = _default_supplier_voucher_form(db, party_code)
        payment_values = _default_supplier_payment_form(db, party_code)
        submission_values = _default_supplier_submission_form(db, party_code, source_channel="By Hand")
        partnership_values = _default_supplier_partnership_form(db, party_code)
        portal_account = _supplier_portal_account_row(db, party_code)

        edit_asset_code = request.args.get("edit_asset", "").strip().upper()
        edit_timesheet_no = request.args.get("edit_timesheet", "").strip().upper()
        edit_voucher_no = request.args.get("edit_voucher", "").strip().upper()
        edit_payment_no = request.args.get("edit_payment", "").strip().upper()
        edit_entry_no = request.args.get("edit_entry", "").strip().upper()
        partnership_month = _normalize_month(request.args.get("partnership_month", "").strip() or _current_month_value())
        kata_month_filter = request.args.get("kata_month", "").strip()
        try:
            kata_month_filter = datetime.strptime(kata_month_filter, "%Y-%m").strftime("%Y-%m") if kata_month_filter else ""
        except ValueError:
            kata_month_filter = ""
        kata_type_filter = request.args.get("kata_type", "all").strip().lower() or "all"
        kata_search = request.args.get("kata_search", "").strip()

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
        if edit_entry_no:
            row = db.execute("SELECT * FROM supplier_partnership_entries WHERE entry_no = ? AND party_code = ?", (edit_entry_no, party_code)).fetchone()
            if row is not None:
                partnership_values = _supplier_partnership_form_from_row(row)

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            try:
                if action == "save_asset":
                    asset_values = _supplier_asset_form_data(request, party_code)
                    asset_values = _apply_supplier_mode_to_asset_values(db, asset_values, supplier_mode, party_code)
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
                                rate_basis = ?, default_rate = ?, double_shift_mode = ?, partnership_mode = ?,
                                partner_name = ?, company_share_percent = ?, partner_share_percent = ?,
                                day_shift_paid_by = ?, night_shift_paid_by = ?, capacity = ?, status = ?, notes = ?
                            WHERE asset_code = ?
                            """,
                            payload + (asset_values["original_asset_code"],),
                        )
                        if asset_values["original_asset_code"] != asset_values["asset_code"]:
                            db.execute(
                                "UPDATE supplier_timesheets SET asset_code = ? WHERE asset_code = ?",
                                (asset_values["asset_code"], asset_values["original_asset_code"]),
                            )
                            db.execute(
                                "UPDATE supplier_partnership_entries SET asset_code = ? WHERE asset_code = ?",
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
                                rate_basis, default_rate, double_shift_mode, partnership_mode, partner_name,
                                company_share_percent, partner_share_percent, day_shift_paid_by, night_shift_paid_by,
                                capacity, status, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    return redirect(url_for("supplier_detail", party_code=party_code, screen="vehicles", partnership_month=partnership_month))

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
                    return redirect(url_for("supplier_detail", party_code=party_code, screen="timesheets", partnership_month=partnership_month))

                if action == "save_submission":
                    if supplier_mode != "Normal":
                        raise ValidationError("Invoice intake is only available in supplier desk.")
                    submission_values = _supplier_submission_form_data(request, party_code, source_channel="By Hand")
                    payload = _prepare_supplier_submission_payload(
                        db,
                        submission_values,
                        source_channel="By Hand",
                        created_by_role="admin",
                        created_by_name=session.get("display_name", "") or "Admin",
                        invoice_file=request.files.get("invoice_attachment"),
                        timesheet_file=request.files.get("timesheet_attachment"),
                    )
                    db.execute(
                        """
                        INSERT INTO supplier_invoice_submissions (
                            submission_no, party_code, source_channel, external_invoice_no, period_month,
                            invoice_date, subtotal, vat_amount, total_amount, invoice_attachment_path,
                            timesheet_attachment_path, notes, review_status, review_note, reviewed_by,
                            reviewed_at, linked_voucher_no, created_by_role, created_by_name
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        payload,
                    )
                    _audit_log(
                        db,
                        "supplier_submission_created",
                        entity_type="supplier_submission",
                        entity_id=submission_values["submission_no"],
                        details=f"By Hand / {party_code} / {submission_values['external_invoice_no']}",
                    )
                    db.commit()
                    flash("By-hand supplier invoice saved and marked ready for voucher.", "success")
                    return redirect(url_for("supplier_detail", party_code=party_code, screen="billing", partnership_month=partnership_month))

                if action == "approve_submission":
                    if supplier_mode != "Normal":
                        raise ValidationError("Submission review is only available in supplier desk.")
                    submission_no = request.form.get("submission_no", "").strip().upper()
                    review_note = request.form.get("review_note", "").strip()
                    _set_supplier_submission_status(
                        db,
                        party_code,
                        submission_no,
                        "Approved",
                        review_note=review_note,
                        reviewed_by=session.get("display_name", "") or "Admin",
                    )
                    _audit_log(db, "supplier_submission_approved", entity_type="supplier_submission", entity_id=submission_no, details=party_code)
                    db.commit()
                    flash("Supplier invoice approved and moved to ready queue.", "success")
                    return redirect(url_for("supplier_detail", party_code=party_code, screen="billing", partnership_month=partnership_month))

                if action == "reject_submission":
                    if supplier_mode != "Normal":
                        raise ValidationError("Submission review is only available in supplier desk.")
                    submission_no = request.form.get("submission_no", "").strip().upper()
                    review_note = request.form.get("review_note", "").strip()
                    _set_supplier_submission_status(
                        db,
                        party_code,
                        submission_no,
                        "Rejected",
                        review_note=review_note,
                        reviewed_by=session.get("display_name", "") or "Admin",
                    )
                    _audit_log(db, "supplier_submission_rejected", entity_type="supplier_submission", entity_id=submission_no, details=party_code)
                    db.commit()
                    flash("Supplier invoice rejected.", "success")
                    return redirect(url_for("supplier_detail", party_code=party_code, screen="billing", partnership_month=partnership_month))

                if action == "convert_submission":
                    if supplier_mode != "Normal":
                        raise ValidationError("Submission conversion is only available in supplier desk.")
                    submission_no = request.form.get("submission_no", "").strip().upper()
                    new_voucher_no = _convert_supplier_submission_to_voucher(
                        db,
                        party_code,
                        submission_no,
                        actor_name=session.get("display_name", "") or "Admin",
                    )
                    _audit_log(
                        db,
                        "supplier_submission_converted",
                        entity_type="supplier_submission",
                        entity_id=submission_no,
                        details=f"{party_code} / {new_voucher_no}",
                    )
                    db.commit()
                    flash("Supplier invoice converted into payable voucher.", "success")
                    return redirect(url_for("supplier_detail", party_code=party_code, screen="billing", partnership_month=partnership_month))

                if action == "save_voucher":
                    voucher_values = _supplier_voucher_form_data(request, party_code)
                    if (
                        supplier_mode == "Normal"
                        and (party["party_kind"] or "") == "Company"
                        and portal_account is not None
                        and int(portal_account["portal_enabled"] or 0)
                        and not voucher_values["original_voucher_no"]
                    ):
                        raise ValidationError("Use invoice intake and convert approved supplier invoices into vouchers.")
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
                                status = ?, notes = ?, source_type = ?, source_reference = ?
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
                            db.execute(
                                "UPDATE supplier_invoice_submissions SET linked_voucher_no = ? WHERE linked_voucher_no = ?",
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
                                tax_percent, tax_amount, total_amount, paid_amount, balance_amount, status, notes,
                                source_type, source_reference
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    return redirect(url_for("supplier_detail", party_code=party_code, screen="billing", partnership_month=partnership_month))

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
                    try:
                        _ensure_supplier_payment_voucher_pdf(app, db, payment_values["payment_no"])
                        flash(f"{message} Payment voucher PDF is ready.", "success")
                    except Exception:
                        flash(message, "success")
                    return redirect(url_for("supplier_detail", party_code=party_code, screen="billing", partnership_month=partnership_month))

                if action == "save_partnership_entry":
                    if supplier_mode != "Partnership":
                        raise ValidationError("Partnership entries are only available in partnership supplier desk.")
                    partnership_values = _supplier_partnership_form_data(request, party_code)
                    payload = _prepare_supplier_partnership_payload(db, partnership_values)
                    _ensure_reference_available(
                        db,
                        "supplier_partnership_entries",
                        "entry_no",
                        partnership_values["entry_no"],
                        partnership_values["original_entry_no"],
                        "Partnership entry number",
                    )
                    if partnership_values["original_entry_no"]:
                        db.execute(
                            """
                            UPDATE supplier_partnership_entries
                            SET entry_no = ?, party_code = ?, asset_code = ?, period_month = ?, entry_date = ?,
                                entry_kind = ?, expense_head = ?, shift_label = ?, driver_name = ?, paid_by = ?,
                                amount = ?, notes = ?
                            WHERE entry_no = ?
                            """,
                            payload + (partnership_values["original_entry_no"],),
                        )
                        _audit_log(
                            db,
                            "supplier_partnership_entry_updated",
                            entity_type="supplier_partnership_entry",
                            entity_id=partnership_values["entry_no"],
                            details=f"{party_code} / {partnership_values['asset_code']} / AED {partnership_values['amount']}",
                        )
                        message = "Partnership entry updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO supplier_partnership_entries (
                                entry_no, party_code, asset_code, period_month, entry_date,
                                entry_kind, expense_head, shift_label, driver_name, paid_by, amount, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        _audit_log(
                            db,
                            "supplier_partnership_entry_created",
                            entity_type="supplier_partnership_entry",
                            entity_id=partnership_values["entry_no"],
                            details=f"{party_code} / {partnership_values['asset_code']} / AED {partnership_values['amount']}",
                        )
                        message = "Partnership entry saved successfully."
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("supplier_detail", party_code=party_code, screen="partnership", partnership_month=partnership_values["period_month"]))
            except ValidationError as exc:
                flash(str(exc), "error")

            # ── Cash/Loan supplier actions ─────────────────────────────
            if supplier_mode in ("Cash", "Loan") and action in ("save_trip", "save_debit", "save_cash_payment"):
                try:
                    if action == "save_trip":
                        trip_no = request.form.get("trip_no", "").strip().upper() or _next_reference_code(db, "cash_supplier_trips", "trip_no", "TRP")
                        entry_date = request.form.get("entry_date", "").strip()
                        period_month = request.form.get("period_month", "").strip()
                        earning_basis = request.form.get("earning_basis", "Trips").strip() or "Trips"
                        if earning_basis not in SUPPLIER_CASH_EARNING_BASIS_OPTIONS:
                            earning_basis = "Trips"
                        quantity_label = {
                            "Trips": "Trip count",
                            "Hours": "Hours",
                            "Monthly": "Months",
                            "Fixed": "Units",
                        }.get(earning_basis, "Quantity")
                        trip_count = _parse_decimal(request.form.get("trip_count", "1"), quantity_label, minimum=0.0)
                        rate = _parse_decimal(request.form.get("rate", "0"), "Rate", minimum=0.0)
                        total_amount = round(trip_count * rate, 2)
                        vehicle_no = request.form.get("vehicle_no", "").strip()
                        notes = request.form.get("notes", "").strip()
                        if not entry_date:
                            raise ValidationError("Entry date is required.")
                        if not period_month and len(entry_date) >= 7:
                            period_month = entry_date[:7]
                        _ensure_reference_available(db, "cash_supplier_trips", "trip_no", trip_no, "", "Trip number")
                        db.execute("""
                            INSERT INTO cash_supplier_trips (trip_no, party_code, entry_date, period_month, earning_basis, trip_count, rate, total_amount, vehicle_no, notes, created_by)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (trip_no, party_code, entry_date, period_month or None, earning_basis, trip_count, rate, total_amount, vehicle_no or None, notes or None, session.get("display_name", "") or "Admin"))
                        db.commit()
                        flash(f"{earning_basis} earning {trip_no} saved - AED {total_amount}", "success")
                        return redirect(url_for("supplier_detail", party_code=party_code, screen="kata"))

                    elif action == "save_debit":
                        debit_no = request.form.get("debit_no", "").strip().upper() or _next_reference_code(db, "cash_supplier_debits", "debit_no", "DEB")
                        entry_date = request.form.get("entry_date", "").strip()
                        debit_type = request.form.get("debit_type", "Advance").strip()
                        amount = _parse_decimal(request.form.get("amount", "0"), "Amount", required=True, minimum=0.01)
                        description = request.form.get("description", "").strip()
                        notes = request.form.get("notes", "").strip()
                        if not entry_date:
                            raise ValidationError("Entry date is required.")
                        _ensure_reference_available(db, "cash_supplier_debits", "debit_no", debit_no, "", "Debit number")
                        db.execute("""
                            INSERT INTO cash_supplier_debits (debit_no, party_code, entry_date, debit_type, amount, description, notes, created_by)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (debit_no, party_code, entry_date, debit_type, amount, description or None, notes or None, session.get("display_name", "") or "Admin"))
                        db.commit()
                        flash(f"Debit {debit_no} saved — AED {amount}", "success")
                        return redirect(url_for("supplier_detail", party_code=party_code, screen="kata"))

                    elif action == "save_cash_payment":
                        payment_no = request.form.get("payment_no", "").strip().upper() or _next_reference_code(db, "cash_supplier_payments", "payment_no", "CPY")
                        entry_date = request.form.get("entry_date", "").strip()
                        amount = _parse_decimal(request.form.get("amount", "0"), "Amount", required=True, minimum=0.01)
                        payment_method = request.form.get("payment_method", "Cash").strip()
                        reference = request.form.get("reference", "").strip()
                        notes = request.form.get("notes", "").strip()
                        if not entry_date:
                            raise ValidationError("Entry date is required.")
                        _ensure_reference_available(db, "cash_supplier_payments", "payment_no", payment_no, "", "Payment number")
                        db.execute("""
                            INSERT INTO cash_supplier_payments (payment_no, party_code, entry_date, amount, payment_method, reference, notes, created_by)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (payment_no, party_code, entry_date, amount, payment_method, reference or None, notes or None, session.get("display_name", "") or "Admin"))
                        db.commit()
                        try:
                            _ensure_cash_supplier_payment_voucher_pdf(app, db, payment_no)
                            flash(f"Payment {payment_no} saved - AED {amount}. Voucher PDF is ready.", "success")
                        except Exception:
                            flash(f"Payment {payment_no} saved - AED {amount}", "success")
                        return redirect(url_for("supplier_detail", party_code=party_code, screen="kata"))

                except ValidationError as exc:
                    flash(str(exc), "error")

        supplier_assets = _safe_supplier_view_value("supplier assets", [], _supplier_asset_rows, db, party_code)
        supplier_timesheets = _safe_supplier_view_value("supplier timesheets", [], _supplier_timesheet_rows, db, party_code)
        supplier_vouchers = _safe_supplier_view_value("supplier vouchers", [], _supplier_voucher_rows, db, party_code)
        supplier_payments = _safe_supplier_view_value("supplier payments", [], _supplier_payment_rows, db, party_code)
        supplier_submissions = _safe_supplier_view_value("supplier submissions", [], _supplier_submission_rows, db, party_code, 30) if supplier_mode in ("Normal", "Managed") else []
        partnership_entries = _safe_supplier_view_value("supplier partnership entries", [], _supplier_partnership_rows, db, party_code) if supplier_mode == "Partnership" else []
        partnership_summary = _safe_supplier_view_value(
            "supplier partnership summary",
            {
                "period_month": partnership_month,
                "work_total": 0.0,
                "company_paid": 0.0,
                "partner_paid": 0.0,
                "company_salary": 0.0,
                "partner_salary": 0.0,
                "company_maintenance": 0.0,
                "partner_maintenance": 0.0,
                "total_salary_cost": 0.0,
                "total_maintenance_cost": 0.0,
                "total_cost": 0.0,
                "net_profit": 0.0,
                "company_profit_share": 0.0,
                "partner_profit_share": 0.0,
                "company_should_receive": 0.0,
                "partner_should_receive": 0.0,
            },
            _supplier_partnership_summary,
            db,
            party_code,
            partnership_month,
        ) if supplier_mode == "Partnership" else {"work_total": 0.0, "company_paid": 0.0, "partner_paid": 0.0, "total_cost": 0.0}
        partnership_assets = _safe_supplier_view_value("supplier partnership assets", [], _supplier_partnership_asset_rows, db, party_code, partnership_month) if supplier_mode == "Partnership" else []
        statement_rows, statement_summary = _safe_supplier_view_value(
            "supplier statement data",
            (
                [],
                {
                    "all_submitted": 0.0,
                    "approved_total": 0.0,
                    "approved_outstanding": 0.0,
                    "pending_submitted": 0.0,
                    "total_paid": 0.0,
                    "work_logged": 0.0,
                    "total_vouchers": 0.0,
                    "outstanding": 0.0,
                },
            ),
            _supplier_statement_data,
            db,
            party_code,
            supplier_mode,
        )

        # ── Cash/Loan supplier kata data ─────────────────────────────
        kata_rows = []
        kata_summary = {"total_earned": 0.0, "total_debits": 0.0, "total_paid": 0.0, "balance": 0.0}
        kata_filters = {
            "month": kata_month_filter,
            "type": kata_type_filter,
            "search": kata_search,
            "active": bool(kata_month_filter or kata_search or (kata_type_filter and kata_type_filter != "all")),
        }
        if supplier_mode in ("Cash", "Loan"):
            kata_rows, kata_summary = _safe_supplier_view_value(
                "cash supplier kata",
                ([], {"total_earned": 0.0, "total_debits": 0.0, "total_paid": 0.0, "balance": 0.0}),
                _cash_supplier_kata,
                db,
                party_code,
            )
            kata_rows = _filter_cash_supplier_kata_rows(
                kata_rows,
                month_filter=kata_month_filter,
                type_filter=kata_type_filter,
                search_text=kata_search,
            )
            kata_summary = _cash_supplier_kata_summary(kata_rows)

        detail_summary = _safe_supplier_view_value(
            "supplier detail summary",
            {
                "asset_count": 0,
                "double_shift_count": 0,
                "partnership_count": 0,
                "unbilled_count": 0,
                "unbilled_amount": 0.0,
                "voucher_total": 0.0,
                "paid_total": 0.0,
                "outstanding_total": 0.0,
                "open_voucher_count": 0,
            },
            _supplier_detail_summary,
            db,
            party_code,
        )

        cash_trip_no = ""
        cash_debit_no = ""
        cash_payment_no = ""
        if supplier_mode in ("Cash", "Loan"):
            cash_trip_no = _safe_supplier_view_value("cash trip number", "", _next_reference_code, db, "cash_supplier_trips", "trip_no", "TRP")
            cash_debit_no = _safe_supplier_view_value("cash debit number", "", _next_reference_code, db, "cash_supplier_debits", "debit_no", "DEB")
            cash_payment_no = _safe_supplier_view_value("cash payment number", "", _next_reference_code, db, "cash_supplier_payments", "payment_no", "CPY")

        portal_snapshot = {
            "intro_label": "Supplier Portal",
            "intro_title": "Supplier Portal",
            "intro_copy": "",
            "modules": [],
            "recent_groups": [],
            "company_details": [],
        }
        if active_screen == "portal":
            try:
                portal_snapshot = _supplier_portal_snapshot(
                    db,
                    party,
                    supplier_mode,
                    detail_summary,
                    partnership_summary=partnership_summary,
                    partnership_month=partnership_month,
                    portal_account=portal_account,
                )
            except Exception:
                current_app.logger.exception("Failed to build supplier portal snapshot for %s", party_code)

        return render_template(
            "supplier_detail.html",
            party=party,
            asset_values=asset_values,
            timesheet_values=timesheet_values,
            voucher_values=voucher_values,
            payment_values=payment_values,
            submission_values=submission_values,
            partnership_values=partnership_values,
            portal_account=portal_account,
            summary=detail_summary,
            statement_rows=statement_rows,
            statement_summary=statement_summary,
            submissions=supplier_submissions,
            partnership_entries=partnership_entries,
            partnership_summary=partnership_summary,
            partnership_assets=partnership_assets,
            partnership_month=partnership_month,
            assets=supplier_assets,
            timesheets=supplier_timesheets,
            vouchers=supplier_vouchers,
            payments=supplier_payments,
            rate_basis_options=SUPPLIER_RATE_BASIS_OPTIONS,
            shift_mode_options=SUPPLIER_SHIFT_MODE_OPTIONS,
            partnership_mode_options=SUPPLIER_PARTNERSHIP_MODE_OPTIONS,
            partnership_entry_kind_options=PARTNERSHIP_ENTRY_KIND_OPTIONS,
            partnership_paid_by_options=PARTNERSHIP_PAID_BY_OPTIONS,
            partnership_shift_options=PARTNERSHIP_SHIFT_OPTIONS,
            payment_method_options=PAYMENT_METHOD_OPTIONS,
            cash_earning_basis_options=SUPPLIER_CASH_EARNING_BASIS_OPTIONS,
            cash_kata_type_options=SUPPLIER_CASH_KATA_TYPE_OPTIONS,
            voucher_status_options=SUPPLIER_VOUCHER_STATUS_OPTIONS,
            supplier_mode=supplier_mode,
            active_screen=active_screen,
            screen_options=_supplier_screen_options(supplier_mode),
            desk_endpoint=_supplier_desk_endpoint(supplier_mode),
            kata_rows=kata_rows,
            kata_summary=kata_summary,
            kata_filters=kata_filters,
            cash_trip_no=cash_trip_no,
            cash_debit_no=cash_debit_no,
            cash_payment_no=cash_payment_no,
            portal_snapshot=portal_snapshot,
        )

    @app.route("/suppliers/<party_code>/send-inquiry", methods=["POST"])
    @_login_required("admin")
    def send_supplier_inquiry(party_code: str):
        """Create a new inquiry for a supplier."""
        db = open_db()
        party = _fetch_supplier_party(db, party_code)
        if party is None:
            flash("Supplier not found.", "error")
            return redirect(url_for("suppliers"))

        subject = request.form.get("subject", "").strip()
        description = request.form.get("description", "").strip()
        priority = request.form.get("priority", "Normal").strip()
        due_date = request.form.get("due_date", "").strip()
        response_deadline = request.form.get("response_deadline", "").strip()

        if not subject:
            flash("Subject is required.", "error")
            return redirect(url_for("supplier_detail", party_code=party_code, screen="portal"))
        if not description:
            flash("Description is required.", "error")
            return redirect(url_for("supplier_detail", party_code=party_code, screen="portal"))

        # Generate inquiry number
        inquiry_no = _next_reference_code(db, "supplier_inquiries", "inquiry_no", "INQ")

        db.execute(
            """
            INSERT INTO supplier_inquiries (
                inquiry_no, party_code, inquiry_date, subject, description,
                priority, status, due_date, response_deadline, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inquiry_no,
                party_code,
                date.today().isoformat(),
                subject,
                description,
                priority,
                "Open",
                due_date if due_date else None,
                response_deadline if response_deadline else None,
                session.get("display_name", "Admin"),
            ),
        )
        db.commit()

        # TODO: Send email notification to supplier
        # For now, just log
        _audit_log(
            db,
            "inquiry_created",
            entity_type="supplier_inquiry",
            entity_id=inquiry_no,
            details=f"Inquiry {inquiry_no} created for {party_code}",
        )

        flash(f"Inquiry {inquiry_no} sent to supplier.", "success")
        return redirect(url_for("supplier_detail", party_code=party_code, screen="portal"))

    @app.get("/suppliers/<party_code>/statement")
    @_login_required("admin")
    def supplier_statement(party_code: str):
        return redirect(url_for("supplier_detail", party_code=party_code, screen="statement"))

    @app.post("/cash-trips/<trip_no>/edit")
    @_login_required("admin")
    def edit_cash_trip(trip_no: str):
        db = open_db()
        row = db.execute(
            "SELECT trip_no, party_code FROM cash_supplier_trips WHERE trip_no = ?",
            ((trip_no or "").strip().upper(),),
        ).fetchone()
        if row is None:
            flash("Cash trip was not found.", "error")
            return redirect(url_for("cash_suppliers"))
        flash("Cash trip editing is not available yet. Please recreate the entry if needed.", "error")
        return redirect(url_for("supplier_detail", party_code=row["party_code"], screen="kata"))

    @app.post("/cash-trips/<trip_no>/delete")
    @_login_required("admin")
    def delete_cash_trip(trip_no: str):
        db = open_db()
        row = db.execute(
            "SELECT trip_no, party_code FROM cash_supplier_trips WHERE trip_no = ?",
            ((trip_no or "").strip().upper(),),
        ).fetchone()
        if row is None:
            flash("Cash trip was not found.", "error")
            return redirect(url_for("cash_suppliers"))
        db.execute("DELETE FROM cash_supplier_trips WHERE trip_no = ?", (row["trip_no"],))
        _audit_log(db, "cash_supplier_trip_deleted", entity_type="cash_supplier_trip", entity_id=row["trip_no"], details=row["party_code"])
        db.commit()
        flash("Cash trip deleted successfully.", "success")
        return redirect(url_for("supplier_detail", party_code=row["party_code"], screen="kata"))

    @app.post("/cash-debits/<debit_no>/edit")
    @_login_required("admin")
    def edit_cash_debit(debit_no: str):
        db = open_db()
        row = db.execute(
            "SELECT debit_no, party_code FROM cash_supplier_debits WHERE debit_no = ?",
            ((debit_no or "").strip().upper(),),
        ).fetchone()
        if row is None:
            flash("Cash debit was not found.", "error")
            return redirect(url_for("cash_suppliers"))
        flash("Cash debit editing is not available yet. Please recreate the entry if needed.", "error")
        return redirect(url_for("supplier_detail", party_code=row["party_code"], screen="kata"))

    @app.post("/cash-debits/<debit_no>/delete")
    @_login_required("admin")
    def delete_cash_debit(debit_no: str):
        db = open_db()
        row = db.execute(
            "SELECT debit_no, party_code FROM cash_supplier_debits WHERE debit_no = ?",
            ((debit_no or "").strip().upper(),),
        ).fetchone()
        if row is None:
            flash("Cash debit was not found.", "error")
            return redirect(url_for("cash_suppliers"))
        db.execute("DELETE FROM cash_supplier_debits WHERE debit_no = ?", (row["debit_no"],))
        _audit_log(db, "cash_supplier_debit_deleted", entity_type="cash_supplier_debit", entity_id=row["debit_no"], details=row["party_code"])
        db.commit()
        flash("Cash debit deleted successfully.", "success")
        return redirect(url_for("supplier_detail", party_code=row["party_code"], screen="kata"))

    @app.post("/cash-payments/<payment_no>/edit")
    @_login_required("admin")
    def edit_cash_payment(payment_no: str):
        db = open_db()
        row = db.execute(
            "SELECT payment_no, party_code FROM cash_supplier_payments WHERE payment_no = ?",
            ((payment_no or "").strip().upper(),),
        ).fetchone()
        if row is None:
            flash("Cash payment was not found.", "error")
            return redirect(url_for("cash_suppliers"))
        flash("Cash payment editing is not available yet. Please recreate the entry if needed.", "error")
        return redirect(url_for("supplier_detail", party_code=row["party_code"], screen="kata"))

    @app.post("/cash-payments/<payment_no>/delete")
    @_login_required("admin")
    def delete_cash_payment(payment_no: str):
        db = open_db()
        row = db.execute(
            "SELECT payment_no, party_code FROM cash_supplier_payments WHERE payment_no = ?",
            ((payment_no or "").strip().upper(),),
        ).fetchone()
        if row is None:
            flash("Cash payment was not found.", "error")
            return redirect(url_for("cash_suppliers"))
        db.execute("DELETE FROM cash_supplier_payments WHERE payment_no = ?", (row["payment_no"],))
        _audit_log(db, "cash_supplier_payment_deleted", entity_type="cash_supplier_payment", entity_id=row["payment_no"], details=row["party_code"])
        db.commit()
        flash("Cash payment deleted successfully.", "success")
        return redirect(url_for("supplier_detail", party_code=row["party_code"], screen="kata"))

    @app.get("/suppliers/<party_code>/statement-pdf")
    @_login_required("admin")
    def supplier_statement_pdf(party_code: str):
        db = open_db()
        party = _fetch_supplier_party(db, party_code)
        if party is None:
            flash("Supplier was not found.", "error")
            return redirect(url_for("suppliers"))
        supplier_mode = _supplier_mode_for_party(db, party_code)
        output_dir = _supplier_output_dir(app, party_code) / "statements"
        if supplier_mode in ("Cash", "Loan"):
            kata_rows, kata_summary = _cash_supplier_kata(db, party_code)
            kata_month_filter = request.args.get("kata_month", "").strip()
            try:
                kata_month_filter = datetime.strptime(kata_month_filter, "%Y-%m").strftime("%Y-%m") if kata_month_filter else ""
            except ValueError:
                kata_month_filter = ""
            kata_type_filter = request.args.get("kata_type", "all").strip().lower() or "all"
            kata_search = request.args.get("kata_search", "").strip()
            kata_rows = _filter_cash_supplier_kata_rows(
                kata_rows,
                month_filter=kata_month_filter,
                type_filter=kata_type_filter,
                search_text=kata_search,
            )
            kata_summary = _cash_supplier_kata_summary(kata_rows)
            filter_parts = []
            if kata_month_filter:
                filter_parts.append(f"Month: {format_month_label(kata_month_filter)}")
            if kata_type_filter and kata_type_filter != "all":
                filter_parts.append(f"Type: {kata_type_filter.title()}")
            if kata_search:
                filter_parts.append(f"Search: {kata_search}")
            pdf_path = generate_cash_supplier_kata_pdf(
                party,
                kata_rows,
                kata_summary,
                str(output_dir),
                app.config["STATIC_ASSETS_DIR"],
                title="Cash Supplier Kata" if supplier_mode == "Cash" else "Loan Supplier Kata",
                filter_caption=" | ".join(filter_parts),
            )
        else:
            statement_rows, statement_summary = _supplier_statement_data(db, party_code, supplier_mode=supplier_mode)
            if supplier_mode == "Partnership":
                partnership_month = _normalize_month(request.args.get("month", "").strip() or _current_month_value())
                asset_rows = _supplier_partnership_asset_rows(db, party_code, partnership_month)
                pdf_path = generate_partnership_supplier_statement_pdf(
                    party,
                    partnership_month,
                    asset_rows,
                    statement_summary,
                    str(output_dir),
                )
            else:
                pdf_path = generate_plain_supplier_statement_pdf(
                    party,
                    statement_rows,
                    statement_summary,
                    str(output_dir),
                    title="Supplier Statement of Account",
                )
        _mirror_generated_file(app, pdf_path)
        relative_path = Path(pdf_path).relative_to(app.config["GENERATED_DIR"]).as_posix()
        return redirect(url_for("generated_file", filename=relative_path))

    @app.post("/suppliers/<party_code>/archive")
    @_login_required("admin")
    def archive_supplier(party_code: str):
        db = open_db()
        party = _fetch_supplier_party(db, party_code)
        if party is None:
            flash("Supplier was not found.", "error")
            return redirect(url_for("suppliers"))
        next_status = "Inactive" if (party["status"] or "Active") == "Active" else "Active"
        db.execute("UPDATE parties SET status = ? WHERE party_code = ?", (next_status, party_code))
        _audit_log(
            db,
            "supplier_status_updated",
            entity_type="supplier",
            entity_id=party_code,
            details=f"{party['party_name']} / {next_status}",
        )
        db.commit()
        flash(f"{party['party_name']} marked as {next_status}.", "success")
        return redirect(url_for(_supplier_desk_endpoint(_supplier_mode_for_party(db, party_code))))

    @app.post("/suppliers/<party_code>/delete")
    @_login_required("admin")
    def delete_supplier(party_code: str):
        db = open_db()
        try:
            party_name, supplier_mode = _delete_supplier_cascade(db, party_code)
            db.commit()
            _delete_supplier_generated_files(current_app, party_code)
            flash(f"{party_name} and all linked supplier data deleted successfully.", "success")
            return redirect(url_for(_supplier_cards_endpoint(supplier_mode)))
        except ValidationError as exc:
            flash(str(exc), "error")
        except Exception:
            current_app.logger.exception("Supplier delete failed for %s", party_code)
            flash("Supplier delete failed. Please try again.", "error")
        return redirect(url_for("supplier_desk_home"))

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
            return redirect(url_for("supplier_detail", party_code=asset["party_code"], screen="vehicles"))
        db.execute("DELETE FROM supplier_assets WHERE asset_code = ?", (asset_code,))
        _audit_log(db, "supplier_asset_deleted", entity_type="supplier_asset", entity_id=asset_code, details=asset["asset_name"])
        db.commit()
        flash("Supplier vehicle deleted successfully.", "success")
        return redirect(url_for("supplier_detail", party_code=asset["party_code"], screen="vehicles"))

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
            return redirect(url_for("supplier_detail", party_code=row["party_code"], screen="timesheets"))
        db.execute("DELETE FROM supplier_timesheets WHERE timesheet_no = ?", (timesheet_no,))
        _audit_log(db, "supplier_timesheet_deleted", entity_type="supplier_timesheet", entity_id=timesheet_no, details=timesheet_no)
        db.commit()
        flash("Supplier timesheet deleted successfully.", "success")
        return redirect(url_for("supplier_detail", party_code=row["party_code"], screen="timesheets"))

    @app.post("/supplier-vouchers/<voucher_no>/delete")
    @_login_required("admin")
    def delete_supplier_voucher(voucher_no: str):
        db = open_db()
        voucher = db.execute(
            "SELECT voucher_no, party_code, source_type, source_reference FROM supplier_vouchers WHERE voucher_no = ?",
            (voucher_no,),
        ).fetchone()
        if voucher is None:
            flash("Supplier voucher was not found.", "error")
            return redirect(url_for("suppliers"))
        count = int(db.execute("SELECT COUNT(*) FROM supplier_payments WHERE voucher_no = ?", (voucher_no,)).fetchone()[0])
        if count:
            flash(f"Voucher cannot be deleted because {count} payment row(s) are linked.", "error")
            return redirect(url_for("supplier_detail", party_code=voucher["party_code"], screen="billing"))
        if (voucher["source_type"] or "Timesheet") == "Submission" and voucher["source_reference"]:
            db.execute(
                """
                UPDATE supplier_invoice_submissions
                SET review_status = 'Approved', linked_voucher_no = NULL, reviewed_at = CURRENT_TIMESTAMP
                WHERE submission_no = ? AND party_code = ?
                """,
                (voucher["source_reference"], voucher["party_code"]),
            )
        else:
            db.execute("UPDATE supplier_timesheets SET voucher_no = NULL, status = 'Open' WHERE voucher_no = ?", (voucher_no,))
        db.execute("DELETE FROM supplier_vouchers WHERE voucher_no = ?", (voucher_no,))
        _audit_log(db, "supplier_voucher_deleted", entity_type="supplier_voucher", entity_id=voucher_no, details=voucher_no)
        db.commit()
        flash("Supplier voucher deleted successfully.", "success")
        return redirect(url_for("supplier_detail", party_code=voucher["party_code"], screen="billing"))

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
        return redirect(url_for("supplier_detail", party_code=payment["party_code"], screen="billing"))

    @app.post("/supplier-partnership/<entry_no>/delete")
    @_login_required("admin")
    def delete_supplier_partnership_entry(entry_no: str):
        db = open_db()
        entry = db.execute(
            "SELECT entry_no, party_code FROM supplier_partnership_entries WHERE entry_no = ?",
            (entry_no,),
        ).fetchone()
        if entry is None:
            flash("Partnership entry was not found.", "error")
            return redirect(url_for("suppliers"))
        db.execute("DELETE FROM supplier_partnership_entries WHERE entry_no = ?", (entry_no,))
        _audit_log(db, "supplier_partnership_entry_deleted", entity_type="supplier_partnership_entry", entity_id=entry_no, details=entry_no)
        db.commit()
        flash("Partnership entry deleted successfully.", "success")
        return redirect(url_for("supplier_detail", party_code=entry["party_code"], screen="partnership"))

    @app.get("/supplier-payments/<payment_no>/voucher")
    @_login_required("admin")
    def supplier_payment_voucher(payment_no: str):
        db = open_db()
        try:
            pdf_path = _ensure_supplier_payment_voucher_pdf(app, db, payment_no)
        except ValidationError:
            flash("Supplier payment voucher was not found.", "error")
            return redirect(url_for("suppliers"))
        relative_path = Path(pdf_path).relative_to(app.config["GENERATED_DIR"]).as_posix()
        return redirect(url_for("generated_file", filename=relative_path))

    @app.get("/cash-payments/<payment_no>/voucher")
    @_login_required("admin")
    def cash_supplier_payment_voucher(payment_no: str):
        db = open_db()
        try:
            pdf_path = _ensure_cash_supplier_payment_voucher_pdf(app, db, (payment_no or "").strip().upper())
        except ValidationError:
            flash("Cash supplier payment voucher was not found.", "error")
            return redirect(url_for("cash_suppliers"))
        relative_path = Path(pdf_path).relative_to(app.config["GENERATED_DIR"]).as_posix()
        return redirect(url_for("generated_file", filename=relative_path))

    @app.route("/customers", methods=["GET", "POST"])
    @_login_required("admin")
    def customers():
        _touch_admin_workspace("customers")
        db = open_db()
        values = _default_customer_form()
        edit_party_code = request.args.get("edit", "").strip().upper()
        if edit_party_code:
            existing_party = _fetch_party(db, edit_party_code)
            if existing_party is not None and "Customer" in _deserialize_party_roles(existing_party["party_roles"] or ""):
                values = _customer_form_from_party(existing_party)

        if request.method == "POST":
            values = _customer_form_data(request)
            try:
                payload = _prepare_customer_party_payload(db, values)
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
                        "customer_updated",
                        entity_type="customer",
                        entity_id=payload[0],
                        details=payload[1],
                    )
                    message = "Customer updated successfully."
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
                        "customer_created",
                        entity_type="customer",
                        entity_id=payload[0],
                        details=payload[1],
                    )
                    message = "Customer saved successfully."
                db.commit()
                flash(message, "success")
                return redirect(url_for("customers"))
            except ValidationError as exc:
                flash(str(exc), "error")
            except Exception:
                current_app.logger.exception("Customer save failed for %s", values.get("party_code") or values.get("original_party_code") or "new")
                flash("Customer save failed. Please review the form and try again.", "error")

        customer_parties = _parties_by_role(db, "Customer", active_only=True)
        summary = _customer_summary(db)
        top_receivables = _party_balance_rows(db, invoice_kind="Sales", limit=8)
        recent_hires = _hire_rows(db, direction="Customer Rental", limit=8)
        recent_invoices = _invoice_rows(db, invoice_kind="Sales", limit=8)
        return render_template(
            "customers.html",
            values=values,
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

    @app.post("/customers/<party_code>/archive")
    @_login_required("admin")
    def archive_customer(party_code: str):
        db = open_db()
        party = _fetch_party(db, party_code)
        if party is None or "Customer" not in _deserialize_party_roles(party["party_roles"] or ""):
            flash("Customer was not found.", "error")
            return redirect(url_for("customers"))
        next_status = "Inactive" if (party["status"] or "Active") == "Active" else "Active"
        db.execute("UPDATE parties SET status = ? WHERE party_code = ?", (next_status, party_code))
        _audit_log(
            db,
            "customer_status_updated",
            entity_type="customer",
            entity_id=party_code,
            details=f"{party['party_name']} / {next_status}",
        )
        db.commit()
        flash(f"{party['party_name']} marked as {next_status}.", "success")
        return redirect(url_for("customers"))

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
                            SET lpo_no = ?, party_code = ?, quotation_no = ?, agreement_no = ?, issue_date = ?, valid_until = ?,
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
                                lpo_no, party_code, quotation_no, agreement_no, issue_date, valid_until,
                                amount, tax_percent, description, status
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    @app.route("/fleet-maintenance", methods=["GET", "POST"])
    @_login_required("admin")
    def fleet_maintenance():
        _touch_admin_workspace("accounts")
        db = open_db()
        filters = _fleet_maintenance_filter_values(request)
        current_screen = _fleet_maintenance_screen_value(request.args.get("screen", "overview"))
        vehicle_values = _default_fleet_vehicle_form(db)
        staff_values = _default_maintenance_staff_form(db)
        advance_values = _default_maintenance_advance_form(db)
        paper_values = _default_maintenance_paper_form(db)
        paper_line_rows = _default_maintenance_paper_lines()
        edit_paper_no = request.args.get("edit_paper", "").strip().upper()
        edit_vehicle_id = request.args.get("edit_vehicle", "").strip().upper()

        if edit_paper_no:
            existing_paper = _maintenance_paper_row(db, edit_paper_no)
            if existing_paper is not None:
                paper_values = _maintenance_paper_form_from_row(existing_paper)
                paper_line_rows = _maintenance_paper_line_rows_for_form(db, edit_paper_no)
                current_screen = "papers"
        if edit_vehicle_id:
            existing_vehicle = db.execute(
                """
                SELECT *
                FROM vehicle_master
                WHERE vehicle_id = ?
                """,
                (edit_vehicle_id,),
            ).fetchone()
            if existing_vehicle is not None:
                vehicle_values = _fleet_vehicle_form_from_row(existing_vehicle)
                current_screen = "vehicles"

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            try:
                if action == "save_vehicle":
                    vehicle_values = _fleet_vehicle_form_data(request)
                    payload = _prepare_fleet_vehicle_payload(db, vehicle_values)
                    _ensure_reference_available(
                        db,
                        "vehicle_master",
                        "vehicle_id",
                        vehicle_values["vehicle_id"],
                        vehicle_values["original_vehicle_id"],
                        "Vehicle ID",
                    )
                    if vehicle_values["original_vehicle_id"]:
                        db.execute(
                            """
                            UPDATE vehicle_master
                            SET vehicle_id = ?, vehicle_no = ?, vehicle_type = ?, make_model = ?, status = ?,
                                shift_mode = ?, ownership_mode = ?, source_type = ?, source_party_code = ?, source_asset_code = ?,
                                partner_party_code = ?, partner_name = ?, company_share_percent = ?, partner_share_percent = ?, notes = ?
                            WHERE vehicle_id = ?
                            """,
                            payload + (vehicle_values["original_vehicle_id"],),
                        )
                        message = "Vehicle updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO vehicle_master (
                                vehicle_id, vehicle_no, vehicle_type, make_model, status,
                                shift_mode, ownership_mode, source_type, source_party_code, source_asset_code,
                                partner_party_code, partner_name, company_share_percent, partner_share_percent, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        message = "Vehicle saved successfully."
                    _audit_log(
                        db,
                        "fleet_vehicle_saved",
                        entity_type="fleet_vehicle",
                        entity_id=vehicle_values["vehicle_id"],
                        details=f"{vehicle_values['vehicle_no']} / {vehicle_values['ownership_mode']}",
                    )
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("fleet_maintenance", screen="vehicles", month=filters["month"]))

                if action == "import_vehicle_pdf":
                    uploaded_pdf = request.files.get("vehicle_pdf")
                    if uploaded_pdf is None or not getattr(uploaded_pdf, "filename", ""):
                        raise ValidationError("Upload a vehicle list PDF before importing.")
                    pdf_bytes = uploaded_pdf.read()
                    file_name = uploaded_pdf.filename or "vehicle-list.pdf"
                    records = load_vehicle_records_from_pdf_bytes(pdf_bytes)
                    if not records:
                        raise ValidationError("No vehicle rows were found in the uploaded PDF.")
                    stored_path = _save_fleet_vehicle_import_pdf(app, uploaded_pdf, pdf_bytes)
                    imported = _upsert_fleet_vehicle_records(db, records)
                    _log_import_history(db, "Fleet Vehicle PDF", file_name, imported, notes=f"Stored at {stored_path}")
                    _audit_log(
                        db,
                        "fleet_vehicle_pdf_uploaded",
                        entity_type="fleet_vehicle_import",
                        entity_id=Path(stored_path).name,
                        details=stored_path,
                    )
                    db.commit()
                    flash(f"Imported or updated {imported} fleet vehicles from PDF.", "success")
                    return redirect(url_for("fleet_maintenance", screen="import", month=filters["month"]))

                if action == "save_staff":
                    staff_values = _maintenance_staff_form_data(request)
                    payload = _prepare_maintenance_staff_payload(db, staff_values)
                    _ensure_reference_available(
                        db,
                        "maintenance_staff",
                        "staff_code",
                        staff_values["staff_code"],
                        staff_values["original_staff_code"],
                        "Technician ID",
                    )
                    if staff_values["original_staff_code"]:
                        db.execute(
                            """
                            UPDATE maintenance_staff
                            SET staff_code = ?, staff_name = ?, phone_number = ?, status = ?, notes = ?
                            WHERE staff_code = ?
                            """,
                            payload + (staff_values["original_staff_code"],),
                        )
                        message = "Technician updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO maintenance_staff (
                                staff_code, staff_name, phone_number, status, notes
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        message = "Technician saved successfully."
                    _audit_log(
                        db,
                        "maintenance_staff_saved",
                        entity_type="maintenance_staff",
                        entity_id=staff_values["staff_code"],
                        details=staff_values["staff_name"],
                    )
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("fleet_maintenance", screen="overview", month=filters["month"]))

                if action == "save_advance":
                    advance_values = _maintenance_advance_form_data(request)
                    payload = _prepare_maintenance_advance_payload(db, advance_values)
                    _ensure_reference_available(
                        db,
                        "maintenance_staff_advances",
                        "advance_no",
                        advance_values["advance_no"],
                        advance_values["original_advance_no"],
                        "Advance number",
                    )
                    if advance_values["original_advance_no"]:
                        db.execute(
                            """
                            UPDATE maintenance_staff_advances
                            SET advance_no = ?, staff_code = ?, entry_date = ?, funding_source = ?,
                                amount = ?, settled_amount = ?, balance_amount = ?, reference = ?, notes = ?
                            WHERE advance_no = ?
                            """,
                            payload + (advance_values["original_advance_no"],),
                        )
                        message = "Field staff payment updated successfully."
                    else:
                        db.execute(
                            """
                            INSERT INTO maintenance_staff_advances (
                                advance_no, staff_code, entry_date, funding_source,
                                amount, settled_amount, balance_amount, reference, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
                        message = "Field staff payment saved successfully."
                    _audit_log(
                        db,
                        "maintenance_advance_saved",
                        entity_type="maintenance_advance",
                        entity_id=advance_values["advance_no"],
                        details=f"{advance_values['staff_code']} / AED {advance_values['amount']}",
                    )
                    db.commit()
                    flash(message, "success")
                    return redirect(url_for("fleet_maintenance", screen="overview", month=filters["month"]))

                if action == "save_paper":
                    paper_values = _maintenance_paper_form_data(request)
                    paper_line_rows = _maintenance_paper_line_form_data(request)
                    prepared = _prepare_maintenance_paper_payload(db, paper_values, paper_line_rows)
                    existing_paper = None
                    attachment_path = None
                    if paper_values["original_paper_no"]:
                        existing_paper = _maintenance_paper_row(db, paper_values["original_paper_no"], required=True)
                        _ensure_reference_available(
                            db,
                            "maintenance_papers",
                            "paper_no",
                            prepared["paper_no"],
                            paper_values["original_paper_no"],
                            "Paper number",
                        )
                        attachment_path = _save_maintenance_attachment(app, prepared["paper_no"], request.files.get("attachment")) or existing_paper["attachment_path"]
                        _reverse_maintenance_paper_effects(db, existing_paper)
                        db.execute(
                            """
                            UPDATE maintenance_papers
                            SET paper_no = ?, paper_date = ?, vehicle_id = ?, vehicle_no = ?, target_class = ?, target_party_code = ?, target_asset_code = ?,
                                workshop_party_code = ?, staff_code = ?, advance_no = ?, tax_mode = ?, supplier_bill_no = ?, work_summary = ?,
                                funding_source = ?, paid_by = ?, subtotal = ?, tax_amount = ?, total_amount = ?,
                                company_share_amount = ?, partner_share_amount = ?, company_paid_amount = ?, partner_paid_amount = ?,
                                linked_partnership_entry_no = ?, attachment_path = ?, notes = ?
                            WHERE paper_no = ?
                            """,
                            (
                                prepared["paper_no"],
                                prepared["paper_date"],
                                prepared["vehicle_id"],
                                prepared["vehicle_no"],
                                prepared["target_class"],
                                prepared["target_party_code"],
                                prepared["target_asset_code"],
                                prepared["workshop_party_code"],
                                prepared["staff_code"],
                                prepared["advance_no"],
                                prepared["tax_mode"],
                                prepared["supplier_bill_no"],
                                prepared["work_summary"],
                                prepared["funding_source"],
                                prepared["paid_by"],
                                prepared["subtotal"],
                                prepared["tax_amount"],
                                prepared["total_amount"],
                                prepared["company_share_amount"],
                                prepared["partner_share_amount"],
                                prepared["company_paid_amount"],
                                prepared["partner_paid_amount"],
                                None,
                                attachment_path,
                                prepared["notes"],
                                paper_values["original_paper_no"],
                            ),
                        )
                    else:
                        attachment_path = _save_maintenance_attachment(app, prepared["paper_no"], request.files.get("attachment"))
                        db.execute(
                            """
                            INSERT INTO maintenance_papers (
                                paper_no, paper_date, vehicle_id, vehicle_no, target_class, target_party_code, target_asset_code,
                                workshop_party_code, staff_code, advance_no, tax_mode, supplier_bill_no, work_summary, funding_source, paid_by,
                                subtotal, tax_amount, total_amount, company_share_amount, partner_share_amount, company_paid_amount,
                                partner_paid_amount, linked_partnership_entry_no, attachment_path, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                prepared["paper_no"],
                                prepared["paper_date"],
                                prepared["vehicle_id"],
                                prepared["vehicle_no"],
                                prepared["target_class"],
                                prepared["target_party_code"],
                                prepared["target_asset_code"],
                                prepared["workshop_party_code"],
                                prepared["staff_code"],
                                prepared["advance_no"],
                                prepared["tax_mode"],
                                prepared["supplier_bill_no"],
                                prepared["work_summary"],
                                prepared["funding_source"],
                                prepared["paid_by"],
                                prepared["subtotal"],
                                prepared["tax_amount"],
                                prepared["total_amount"],
                                prepared["company_share_amount"],
                                prepared["partner_share_amount"],
                                prepared["company_paid_amount"],
                                prepared["partner_paid_amount"],
                                None,
                                attachment_path,
                                prepared["notes"],
                            ),
                        )
                    _save_maintenance_paper_lines(db, prepared["paper_no"], prepared["line_payloads"])
                    if prepared["settlement_payload"] is not None:
                        db.execute(
                            """
                            INSERT INTO maintenance_settlements (
                                settlement_no, paper_no, settlement_type, advance_no, party_code, amount, status, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            prepared["settlement_payload"],
                        )
                    if prepared["advance_update"] is not None:
                        db.execute(
                            """
                            UPDATE maintenance_staff_advances
                            SET settled_amount = ?, balance_amount = ?
                            WHERE advance_no = ?
                            """,
                            (
                                prepared["advance_update"]["settled_amount"],
                                prepared["advance_update"]["balance_amount"],
                                prepared["advance_update"]["advance_no"],
                            ),
                        )
                    linked_partnership_entry_no = _save_maintenance_linked_partnership_entry(db, prepared)
                    if linked_partnership_entry_no:
                        db.execute(
                            "UPDATE maintenance_papers SET linked_partnership_entry_no = ? WHERE paper_no = ?",
                            (linked_partnership_entry_no, prepared["paper_no"]),
                        )
                    _audit_log(
                        db,
                        "maintenance_paper_saved",
                        entity_type="maintenance_paper",
                        entity_id=prepared["paper_no"],
                        details=f"{prepared['vehicle_no']} / {prepared['funding_source']} / AED {prepared['total_amount']}",
                    )
                    db.commit()
                    flash("Maintenance paper saved successfully.", "success")
                    return redirect(url_for("fleet_maintenance", screen="papers", month=prepared["view_month"], vehicle_id=filters["vehicle_id"], funding_source=filters["funding_source"], search=filters["search"]))
            except ValidationError as exc:
                flash(str(exc), "error")

        summary = _fleet_maintenance_summary(db, filters["month"])
        vehicle_rows = _fleet_vehicle_rows(db)
        fleet_vehicle_rows = _fleet_vehicle_directory_rows(db, filters)
        filter_vehicle_rows = _maintenance_target_vehicle_rows(db)
        staff_rows = _maintenance_staff_rows(db)
        advance_rows = _maintenance_advance_rows(db)
        paper_rows = _maintenance_paper_rows(db, filters, limit=18)
        workshop_payables = _maintenance_workshop_payables(db, filters)
        vehicle_statement_rows = _vehicle_maintenance_statement_rows(db, filters)
        partnership_rows = _maintenance_partnership_rows(db, filters)
        technician_ledgers = _maintenance_staff_ledger_rows(db)
        recent_vehicle_imports = _fleet_vehicle_import_rows(app)
        focus_vehicle = None
        if filters["vehicle_id"]:
            focus_vehicle = next((item for item in fleet_vehicle_rows if item["vehicle_id"] == filters["vehicle_id"]), None)
        elif filters["search"] and len(fleet_vehicle_rows) == 1:
            focus_vehicle = fleet_vehicle_rows[0]

        return render_template(
            "fleet_maintenance.html",
            current_screen=current_screen,
            filters=filters,
            summary=summary,
            vehicle_values=vehicle_values,
            staff_values=staff_values,
            advance_values=advance_values,
            paper_values=paper_values,
            paper_line_rows=paper_line_rows,
            vehicle_rows=vehicle_rows,
            fleet_vehicle_rows=fleet_vehicle_rows,
            filter_vehicle_rows=filter_vehicle_rows,
            staff_rows=staff_rows,
            advance_rows=advance_rows,
            paper_rows=paper_rows,
            workshop_payables=workshop_payables,
            vehicle_statement_rows=vehicle_statement_rows,
            partnership_rows=partnership_rows,
            technician_ledgers=technician_ledgers,
            recent_vehicle_imports=recent_vehicle_imports,
            focus_vehicle=focus_vehicle,
            shift_mode_options=FLEET_SHIFT_MODE_OPTIONS,
            ownership_mode_options=FLEET_OWNERSHIP_MODE_OPTIONS,
            tax_mode_options=MAINTENANCE_TAX_MODE_OPTIONS,
            advance_source_options=MAINTENANCE_ADVANCE_SOURCE_OPTIONS,
            funding_source_options=MAINTENANCE_FUNDING_SOURCE_OPTIONS,
            paid_by_options=MAINTENANCE_PAID_BY_OPTIONS,
            workshop_parties=_parties_by_role(db, "Supplier"),
            partner_parties=_parties_by_role(db, "Partner"),
            target_class_options=MAINTENANCE_TARGET_CLASS_OPTIONS,
            partnership_supplier_assets=_partnership_supplier_asset_options(db),
        )

    @app.post("/fleet-maintenance/vehicles/<vehicle_id>/delete")
    @_login_required("admin")
    def delete_fleet_vehicle(vehicle_id: str):
        db = open_db()
        vehicle = db.execute(
            """
            SELECT vehicle_id, vehicle_no, ownership_mode, source_type
            FROM vehicle_master
            WHERE vehicle_id = ?
            """,
            (vehicle_id,),
        ).fetchone()
        if vehicle is None:
            flash("Vehicle was not found.", "error")
            return redirect(url_for("fleet_maintenance", screen="overview"))
        linked_count = int(
            db.execute("SELECT COUNT(*) FROM maintenance_papers WHERE vehicle_id = ?", (vehicle_id,)).fetchone()[0]
        )
        if linked_count:
            flash(f"Vehicle cannot be deleted because {linked_count} maintenance paper(s) are linked.", "error")
            return redirect(url_for("fleet_maintenance", screen="overview", vehicle_id=vehicle_id))
        db.execute("DELETE FROM vehicle_master WHERE vehicle_id = ?", (vehicle_id,))
        _audit_log(
            db,
            "fleet_vehicle_deleted",
            entity_type="fleet_vehicle",
            entity_id=vehicle_id,
            details=f"{vehicle['vehicle_no']} / {vehicle['ownership_mode'] or vehicle['source_type'] or 'Fleet'}",
        )
        db.commit()
        flash(f"Vehicle {vehicle['vehicle_no']} deleted successfully.", "success")
        return redirect(url_for("fleet_maintenance", screen="overview"))

    @app.get("/fleet-maintenance/vehicles/<vehicle_id>")
    @_login_required("admin")
    def fleet_vehicle_detail(vehicle_id: str):
        _touch_admin_workspace("accounts")
        db = open_db()
        vehicle = db.execute(
            """
            SELECT
                v.vehicle_id,
                v.vehicle_no,
                v.vehicle_type,
                v.make_model,
                v.status,
                v.shift_mode,
                v.ownership_mode,
                v.notes,
                COALESCE(partner.party_name, v.partner_name, '-') AS partner_name
            FROM vehicle_master v
            LEFT JOIN parties partner ON partner.party_code = v.partner_party_code
            WHERE v.vehicle_id = ?
            """,
            (vehicle_id,),
        ).fetchone()
        if vehicle is None:
            flash("Vehicle was not found.", "error")
            return redirect(url_for("fleet_maintenance"))

        detail_filters = {
            "month": request.args.get("month", "").strip() or "",
            "vehicle_id": vehicle_id,
            "funding_source": request.args.get("funding_source", "").strip(),
            "search": request.args.get("search", "").strip(),
        }
        if detail_filters["month"]:
            detail_filters["month"] = _normalize_month(detail_filters["month"])
        history_rows = _maintenance_paper_rows(db, detail_filters, limit=200)
        month_statement = _vehicle_maintenance_statement_rows(db, detail_filters)
        month_summary = month_statement[0] if month_statement else {
            "paper_count": 0,
            "subtotal": 0.0,
            "tax_amount": 0.0,
            "total_amount": 0.0,
            "company_paid_amount": 0.0,
            "partner_paid_amount": 0.0,
        }
        lifetime_summary = db.execute(
            """
            SELECT
                COUNT(*) AS paper_count,
                COALESCE(SUM(subtotal), 0) AS subtotal,
                COALESCE(SUM(tax_amount), 0) AS tax_amount,
                COALESCE(SUM(total_amount), 0) AS total_amount
            FROM maintenance_papers
            WHERE vehicle_id = ?
            """,
            (vehicle_id,),
        ).fetchone()
        monthly_rows = db.execute(
            """
            SELECT
                SUBSTR(paper_date, 1, 7) AS period_month,
                COUNT(*) AS paper_count,
                COALESCE(SUM(total_amount), 0) AS total_amount
            FROM maintenance_papers
            WHERE vehicle_id = ?
            GROUP BY SUBSTR(paper_date, 1, 7)
            ORDER BY period_month DESC
            LIMIT 12
            """,
            (vehicle_id,),
        ).fetchall()
        return render_template(
            "fleet_vehicle_detail.html",
            vehicle=vehicle,
            filters=detail_filters,
            history_rows=history_rows,
            month_summary=month_summary,
            lifetime_summary=lifetime_summary,
            monthly_rows=monthly_rows,
        )

    @app.post("/fleet-maintenance/<paper_no>/delete")
    @_login_required("admin")
    def delete_maintenance_paper(paper_no: str):
        db = open_db()
        paper = _maintenance_paper_row(db, paper_no)
        if paper is None:
            flash("Maintenance paper was not found.", "error")
            return redirect(url_for("fleet_maintenance"))
        _delete_maintenance_paper_record(db, app, paper)
        _audit_log(
            db,
            "maintenance_paper_deleted",
            entity_type="maintenance_paper",
            entity_id=paper_no,
            details=f"{paper['vehicle_no']} / AED {float(paper['total_amount'] or 0.0):.2f}",
        )
        db.commit()
        flash("Maintenance paper deleted successfully.", "success")
        return redirect(url_for("fleet_maintenance", month=(paper["paper_date"] or "")[:7]))

    @app.route("/admin/technician-jobs", methods=["GET", "POST"])
    @_login_required("admin")
    def technician_jobs():
        _touch_admin_workspace("technicians")
        db = open_db()
        
        # Get filter values from request
        filters = {
            "status": request.args.get("status", "").strip(),
            "technician_code": request.args.get("technician_code", "").strip(),
            "vehicle_id": request.args.get("vehicle_id", "").strip(),
            "payment_status": request.args.get("payment_status", "").strip(),
        }
        
        # Build query for jobs - updated to match actual schema
        query = """
            SELECT
                mp.paper_no, mp.paper_date as entry_date, mp.vehicle_id,
                COALESCE(vm.vehicle_no, mp.vehicle_id) as vehicle_no,
                COALESCE(vm.make_model, mp.vehicle_id) as vehicle_name,
                mp.work_summary as details,
                mp.supplier_bill_no as bill_no,
                mp.subtotal as amount,
                mp.tax_amount, mp.total_amount,
                mp.notes as remarks,
                mp.technician_code,
                COALESCE(p.party_name, t.specialization, mp.technician_code) as technician_name,
                mp.review_status,
                '' as approved_by,
                mp.created_at as approved_at,
                '' as rejection_reason,
                mp.payment_status, COALESCE(mp.paid_amount, 0) as paid_amount,
                mp.created_at, mp.attachment_path as bill_image,
                -- Add workshop name from parties table if workshop_party_code exists
                COALESCE(wp.party_name, mp.workshop_party_code) as workshop_name,
                mp.work_type
            FROM maintenance_papers mp
            LEFT JOIN vehicle_master vm ON mp.vehicle_id = vm.vehicle_id
            LEFT JOIN technicians t ON mp.technician_code = t.technician_code
            LEFT JOIN parties p ON t.party_code = p.party_code
            LEFT JOIN parties wp ON mp.workshop_party_code = wp.party_code
            WHERE mp.technician_code IS NOT NULL
        """
        params = []
        
        if filters["status"]:
            query += " AND mp.review_status = ?"
            params.append(filters["status"])
        
        if filters["technician_code"]:
            query += " AND mp.technician_code = ?"
            params.append(filters["technician_code"])
        
        if filters["vehicle_id"]:
            query += " AND mp.vehicle_id = ?"
            params.append(filters["vehicle_id"])
        
        if filters["payment_status"]:
            query += " AND mp.payment_status = ?"
            params.append(filters["payment_status"])
        
        query += " ORDER BY mp.paper_date DESC, mp.paper_no DESC LIMIT 50"
        
        jobs = db.execute(query, params).fetchall()
        
        # Get technician list for filter (with party names)
        technicians = db.execute(
            """
            SELECT t.technician_code,
                   t.specialization,
                   COALESCE(p.party_name, t.specialization, t.technician_code) as party_name
            FROM technicians t
            LEFT JOIN parties p ON t.party_code = p.party_code
            WHERE t.status = 'Active'
            ORDER BY COALESCE(p.party_name, t.specialization, t.technician_code), t.technician_code
            """
        ).fetchall()
        
        # Get vehicle list for filter
        vehicles = db.execute(
            """
            SELECT vehicle_id, vehicle_no, make_model as vehicle_name
            FROM vehicle_master
            WHERE status = 'Active'
            ORDER BY vehicle_no
            """
        ).fetchall()
        
        # Handle POST actions
        if request.method == "POST":
            action = request.form.get("action", "").strip()
            paper_no = request.form.get("paper_no", "").strip().upper()
            reviewer = session.get("display_name", "") or "Admin"
            
            try:
                if action == "approve":
                    # Get job details to calculate split
                    job = db.execute(
                        """
                        SELECT mp.total_amount, mp.vehicle_id, vm.ownership_mode,
                               vm.company_share_percent, vm.partner_share_percent
                        FROM maintenance_papers mp
                        LEFT JOIN vehicle_master vm ON mp.vehicle_id = vm.vehicle_id
                        WHERE mp.paper_no = ?
                        """,
                        (paper_no,)
                    ).fetchone()
                    
                    if not job:
                        raise ValidationError(f"Job {paper_no} not found.")
                    
                    total_amount = float(job["total_amount"] or 0)
                    ownership_mode = job["ownership_mode"] or "Standard"
                    company_share_percent = float(job["company_share_percent"] or 100)
                    partner_share_percent = float(job["partner_share_percent"] or 0)
                    
                    # Calculate split amounts
                    if ownership_mode in ["Standard", "Own Fleet"]:
                        # Company vehicle - 100% company expense
                        company_share_amount = total_amount
                        partner_share_amount = 0.0
                    else:
                        # Partnership or supplier vehicle - split based on percentages
                        company_share_amount = total_amount * (company_share_percent / 100)
                        partner_share_amount = total_amount * (partner_share_percent / 100)
                    
                    # Update job status to Approved with split amounts
                    db.execute(
                        """
                        UPDATE maintenance_papers
                        SET review_status = 'Approved',
                            company_share_amount = ?,
                            partner_share_amount = ?
                        WHERE paper_no = ?
                        """,
                        (company_share_amount, partner_share_amount, paper_no)
                    )
                    
                    _audit_log(
                        db,
                        "technician_job_approved",
                        entity_type="maintenance_paper",
                        entity_id=paper_no,
                        details=f"Job {paper_no} approved by {reviewer}. Split: Company AED {company_share_amount:.2f}, Partner AED {partner_share_amount:.2f}",
                    )
                    
                    db.commit()
                    flash(f"Job {paper_no} approved successfully. Split calculated: Company AED {company_share_amount:.2f}, Partner AED {partner_share_amount:.2f}", "success")
                    
                elif action == "reject":
                    rejection_reason = request.form.get("rejection_reason", "").strip()
                    if not rejection_reason:
                        rejection_reason = "No reason provided"
                    
                    db.execute(
                        """
                        UPDATE maintenance_papers
                        SET review_status = 'Rejected'
                        WHERE paper_no = ?
                        """,
                        (paper_no,)
                    )
                    
                    _audit_log(
                        db,
                        "technician_job_rejected",
                        entity_type="maintenance_paper",
                        entity_id=paper_no,
                        details=f"Job {paper_no} rejected: {rejection_reason}",
                    )
                    
                    db.commit()
                    flash(f"Job {paper_no} rejected.", "success")
                    
                elif action == "mark_paid":
                    # Mark job as fully paid
                    db.execute(
                        """
                        UPDATE maintenance_papers
                        SET payment_status = 'Paid',
                            paid_amount = total_amount,
                            company_paid_amount = total_amount
                        WHERE paper_no = ?
                        """,
                        (paper_no,)
                    )
                    
                    _audit_log(
                        db,
                        "technician_job_paid",
                        entity_type="maintenance_paper",
                        entity_id=paper_no,
                        details=f"Job {paper_no} marked as paid",
                    )
                    
                    db.commit()
                    flash(f"Job {paper_no} marked as paid.", "success")

                elif action == "delete":
                    if not paper_no:
                        raise ValidationError("Select a field staff entry to delete.")
                    job = _maintenance_paper_row(db, paper_no)
                    if not job:
                        raise ValidationError(f"Job {paper_no} was not found.")
                    _delete_maintenance_paper_record(db, app, job)
                    _audit_log(
                        db,
                        "technician_job_deleted",
                        entity_type="maintenance_paper",
                        entity_id=paper_no,
                        details=f"Job {paper_no} deleted by {reviewer}",
                    )
                    db.commit()
                    flash(f"Job {paper_no} deleted successfully.", "success")
                    
                elif action == "process_payment":
                    payment_amount = float(request.form.get("payment_amount", "0").strip() or 0)
                    if payment_amount <= 0:
                        raise ValidationError("Payment amount must be greater than 0")
                    
                    # Get current payment details including split amounts
                    job = db.execute(
                        """
                        SELECT total_amount, paid_amount,
                               company_paid_amount, partner_paid_amount,
                               company_share_amount, partner_share_amount
                        FROM maintenance_papers
                        WHERE paper_no = ?
                        """,
                        (paper_no,)
                    ).fetchone()
                    
                    if job:
                        total_amount = float(job["total_amount"] or 0)
                        paid_amount = float(job["paid_amount"] or 0)
                        company_paid_amount = float(job["company_paid_amount"] or 0)
                        partner_paid_amount = float(job["partner_paid_amount"] or 0)
                        
                        # For now, assume payment is made by company
                        # In future, we could add a paid_by field to the form
                        new_company_paid = company_paid_amount + payment_amount
                        new_paid = new_company_paid + partner_paid_amount
                        
                        if new_paid >= total_amount:
                            payment_status = "Paid"
                        elif new_paid > 0:
                            payment_status = "Partial"
                        else:
                            payment_status = "Pending"
                        
                        db.execute(
                            """
                            UPDATE maintenance_papers
                            SET payment_status = ?,
                                paid_amount = ?,
                                company_paid_amount = ?
                            WHERE paper_no = ?
                            """,
                            (payment_status, new_paid, new_company_paid, paper_no)
                        )
                        
                        _audit_log(
                            db,
                            "technician_payment_processed",
                            entity_type="maintenance_paper",
                            entity_id=paper_no,
                            details=f"Payment of AED {payment_amount:.2f} processed for job {paper_no} (Company paid)",
                        )
                        
                        db.commit()
                        flash(f"Payment of AED {payment_amount:.2f} processed for job {paper_no}.", "success")
                
            except ValidationError as exc:
                db.rollback()
                flash(str(exc), "error")
            except Exception as exc:
                db.rollback()
                flash(f"Error processing action: {str(exc)}", "error")
            
            return redirect(url_for("technician_jobs", **filters))
        
        # Calculate summary statistics
        stats = {}
        
        # Pending count
        stats["pending_count"] = db.execute(
            "SELECT COUNT(*) FROM maintenance_papers WHERE review_status = 'Pending' AND technician_code IS NOT NULL"
        ).fetchone()[0] or 0
        
        # Approved amount
        stats["approved_amount"] = float(db.execute(
            "SELECT COALESCE(SUM(total_amount), 0) FROM maintenance_papers WHERE review_status = 'Approved' AND technician_code IS NOT NULL"
        ).fetchone()[0] or 0)
        
        # Paid amount
        stats["paid_amount"] = float(db.execute(
            "SELECT COALESCE(SUM(COALESCE(paid_amount, 0)), 0) FROM maintenance_papers WHERE technician_code IS NOT NULL"
        ).fetchone()[0] or 0)
        
        # Total jobs
        stats["total_jobs"] = db.execute(
            "SELECT COUNT(*) FROM maintenance_papers WHERE technician_code IS NOT NULL"
        ).fetchone()[0] or 0
        
        # Total amount
        stats["total_amount"] = float(db.execute(
            "SELECT COALESCE(SUM(total_amount), 0) FROM maintenance_papers WHERE technician_code IS NOT NULL"
        ).fetchone()[0] or 0)
        
        # Balance due
        stats["balance_due"] = stats["total_amount"] - stats["paid_amount"]
        
        # Technician count
        stats["technician_count"] = db.execute(
            "SELECT COUNT(*) FROM technicians WHERE status = 'Active'"
        ).fetchone()[0] or 0
        
        # Get pending payments (approved but not fully paid)
        pending_payments = db.execute(
            """
            SELECT mp.paper_no, mp.technician_code,
                   COALESCE(p.party_name, t.specialization, mp.technician_code) as technician_name,
                   mp.total_amount, COALESCE(mp.paid_amount, 0) as paid_amount,
                   mp.created_at as approved_at
            FROM maintenance_papers mp
            LEFT JOIN technicians t ON mp.technician_code = t.technician_code
            LEFT JOIN parties p ON t.party_code = p.party_code
            WHERE mp.review_status = 'Approved'
              AND mp.payment_status IN ('Pending', 'Partial')
              AND mp.technician_code IS NOT NULL
            ORDER BY mp.created_at DESC
            LIMIT 10
            """
        ).fetchall()
        
        # Get technician summary
        technician_summary = db.execute(
            """
            SELECT
                mp.technician_code,
                COALESCE(p.party_name, t.specialization, mp.technician_code) as technician_name,
                COUNT(*) as job_count,
                SUM(CASE WHEN mp.review_status = 'Approved' THEN mp.total_amount ELSE 0 END) as total_approved,
                SUM(COALESCE(mp.paid_amount, 0)) as total_paid,
                SUM(CASE WHEN mp.review_status = 'Approved' THEN mp.total_amount ELSE 0 END) - SUM(COALESCE(mp.paid_amount, 0)) as balance_due
            FROM maintenance_papers mp
            LEFT JOIN technicians t ON mp.technician_code = t.technician_code
            LEFT JOIN parties p ON t.party_code = p.party_code
            WHERE mp.technician_code IS NOT NULL
            GROUP BY mp.technician_code, p.party_name, t.specialization
            ORDER BY total_approved DESC
            LIMIT 10
            """
        ).fetchall()
        
        # Current month for export
        from datetime import datetime
        current_month = datetime.now().strftime("%Y-%m")

        vehicle_expense_report = db.execute(
            """
            SELECT
                mp.vehicle_id,
                COALESCE(vm.vehicle_no, mp.vehicle_no, mp.vehicle_id, 'General Entry') as vehicle_no,
                COALESCE(vm.make_model, mp.vehicle_id, 'General Work') as vehicle_name,
                COALESCE(vm.ownership_mode, 'Standard') as ownership_mode,
                COUNT(*) as job_count,
                COALESCE(SUM(mp.total_amount), 0) as total_amount,
                COALESCE(SUM(mp.company_share_amount), 0) as company_share_amount,
                COALESCE(SUM(mp.partner_share_amount), 0) as partner_share_amount,
                COALESCE(SUM(mp.company_paid_amount), 0) as company_paid_amount,
                COALESCE(SUM(mp.partner_paid_amount), 0) as partner_paid_amount
            FROM maintenance_papers mp
            LEFT JOIN vehicle_master vm ON mp.vehicle_id = vm.vehicle_id
            WHERE mp.technician_code IS NOT NULL
            GROUP BY mp.vehicle_id, vm.vehicle_no, mp.vehicle_no, vm.make_model, vm.ownership_mode
            ORDER BY total_amount DESC, job_count DESC
            LIMIT 12
            """
        ).fetchall()

        partnership_report = db.execute(
            """
            SELECT
                mp.vehicle_id,
                COALESCE(vm.vehicle_no, mp.vehicle_no, mp.vehicle_id) as vehicle_no,
                COALESCE(vm.make_model, mp.vehicle_id, 'Vehicle') as vehicle_name,
                COUNT(*) as job_count,
                COALESCE(SUM(mp.total_amount), 0) as total_amount,
                COALESCE(SUM(mp.company_share_amount), 0) as company_share_amount,
                COALESCE(SUM(mp.partner_share_amount), 0) as partner_share_amount,
                COALESCE(SUM(mp.company_paid_amount), 0) as company_paid_amount,
                COALESCE(SUM(mp.partner_paid_amount), 0) as partner_paid_amount
            FROM maintenance_papers mp
            LEFT JOIN vehicle_master vm ON mp.vehicle_id = vm.vehicle_id
            WHERE mp.technician_code IS NOT NULL
              AND COALESCE(vm.ownership_mode, '') = 'Partnership'
            GROUP BY mp.vehicle_id, vm.vehicle_no, mp.vehicle_no, vm.make_model
            ORDER BY total_amount DESC, job_count DESC
            LIMIT 12
            """
        ).fetchall()
        
        return render_template(
            "technician_jobs.html",
            jobs=jobs,
            technicians=technicians,
            vehicles=vehicles,
            filters=filters,
            stats=stats,
            pending_payments=pending_payments,
            technician_summary=technician_summary,
            current_month=current_month,
            vehicle_expense_report=vehicle_expense_report,
            partnership_report=partnership_report,
        )
    
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

    @app.route("/technicians", methods=["GET", "POST"])
    @_login_required("admin")
    def technicians():
        """Field staff management - list, create, edit, delete and issue payments."""
        _touch_admin_workspace("technicians")
        db = open_db()

        def _sync_field_staff_profile(staff_code: str, staff_name: str, phone_number: str, status: str):
            existing_staff = db.execute(
                """
                SELECT staff_code
                FROM maintenance_staff
                WHERE staff_code = ?
                """,
                (staff_code,),
            ).fetchone()
            if existing_staff:
                db.execute(
                    """
                    UPDATE maintenance_staff
                    SET staff_name = ?, phone_number = ?, status = ?
                    WHERE staff_code = ?
                    """,
                    (staff_name, phone_number or None, status, staff_code),
                )
            else:
                db.execute(
                    """
                    INSERT INTO maintenance_staff (
                        staff_code, staff_name, phone_number, status, notes
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (staff_code, staff_name, phone_number or None, status, "Auto-synced from Field Staff Desk"),
                )
        
        # Get filter values
        status_filter = request.args.get("status", "").strip()
        search_q = request.args.get("search", "").strip()
        
        # Build query
        query = """
            SELECT t.id, t.technician_code, t.user_id,
                   t.phone_number, t.specialization, t.status, t.created_at,
                   COALESCE(pay.given_amount, 0) as given_amount,
                   COALESCE(spend.vehicle_spent, 0) as vehicle_spent,
                   COALESCE(spend.general_spent, 0) as general_spent,
                   COALESCE(spend.total_spent, 0) as total_spent,
                   COALESCE(pay.given_amount, 0) - COALESCE(spend.total_spent, 0) as balance_amount
            FROM technicians t
            LEFT JOIN (
                SELECT staff_code, COALESCE(SUM(amount), 0) as given_amount
                FROM maintenance_staff_advances
                GROUP BY staff_code
            ) pay ON pay.staff_code = t.technician_code
            LEFT JOIN (
                SELECT
                    technician_code,
                    COALESCE(SUM(CASE WHEN vehicle_id IS NOT NULL AND vehicle_id != '' THEN total_amount ELSE 0 END), 0) as vehicle_spent,
                    COALESCE(SUM(CASE WHEN vehicle_id IS NULL OR vehicle_id = '' THEN total_amount ELSE 0 END), 0) as general_spent,
                    COALESCE(SUM(total_amount), 0) as total_spent
                FROM maintenance_papers
                WHERE technician_code IS NOT NULL
                GROUP BY technician_code
            ) spend ON spend.technician_code = t.technician_code
            WHERE 1=1
        """
        params = []
        
        if status_filter:
            query += " AND t.status = ?"
            params.append(status_filter)
        
        if search_q:
            query += " AND (t.technician_code LIKE ? OR t.user_id LIKE ? OR t.specialization LIKE ?)"
            search_term = f"%{search_q}%"
            params.extend([search_term, search_term, search_term])
        
        query += " ORDER BY t.created_at DESC"
        
        technicians_list = db.execute(query, params).fetchall()
        
        summary = {
            "staff_count": len(technicians_list),
            "active_count": len([item for item in technicians_list if (item["status"] or "") == "Active"]),
            "given_amount": sum(float(item["given_amount"] or 0) for item in technicians_list),
            "spent_amount": sum(float(item["total_spent"] or 0) for item in technicians_list),
            "balance_amount": sum(float(item["balance_amount"] or 0) for item in technicians_list),
        }

        _, _, owner_fund_balance = _owner_fund_totals(db)

        recent_payments = db.execute(
            """
            SELECT
                adv.advance_no,
                adv.staff_code as technician_code,
                COALESCE(t.specialization, adv.staff_code) as technician_name,
                adv.entry_date,
                adv.funding_source,
                adv.amount,
                adv.reference,
                adv.notes
            FROM maintenance_staff_advances adv
            LEFT JOIN technicians t ON t.technician_code = adv.staff_code
            ORDER BY adv.entry_date DESC, adv.id DESC
            LIMIT 12
            """
        ).fetchall()

        parties = []
        
        # Handle form submission for create/edit
        edit_technician_code = request.args.get("edit", "").strip()
        values = {
            "technician_code": "",
            "user_id": "",
            "password": "",
            "confirm_password": "",
            "phone_number": "",
            "specialization": "",
            "status": "Active",
        }
        payment_values = {
            "technician_code": request.args.get("pay", "").strip(),
            "entry_date": date.today().isoformat(),
            "funding_source": "Owner Fund",
            "amount": "",
            "reference": "",
            "notes": "",
        }
        
        if edit_technician_code:
            # Load existing technician for editing
            tech = db.execute("""
                SELECT technician_code, user_id, phone_number, specialization, status
                FROM technicians
                WHERE technician_code = ?
            """, (edit_technician_code,)).fetchone()
            if tech:
                values = {
                    "technician_code": tech["technician_code"],
                    "user_id": tech["user_id"] or "",
                    "password": "",
                    "confirm_password": "",
                    "phone_number": tech["phone_number"] or "",
                    "specialization": tech["specialization"] or "",
                    "status": tech["status"] or "Active",
                }
        
        if request.method == "POST":
            action = request.form.get("action", "").strip()
            if action in {"create", "update"}:
                values = {
                    "technician_code": "",  # Will be auto-generated
                    "user_id": request.form.get("user_id", "").strip(),
                    "password": request.form.get("password", "").strip(),
                    "confirm_password": request.form.get("confirm_password", "").strip(),
                    "phone_number": request.form.get("phone_number", "").strip(),
                    "specialization": request.form.get("specialization", "").strip(),
                    "status": request.form.get("status", "Active").strip(),
                }

                errors = []
                if not values["user_id"]:
                    errors.append("User ID is required")
                if not values["specialization"]:
                    errors.append("Field staff name is required")
                if not values["password"] and action == "create":
                    errors.append("Password is required for new field staff")
                if values["password"] != values["confirm_password"]:
                    errors.append("Password and confirmation do not match")

                if action == "create":
                    last_tech = db.execute(
                        "SELECT technician_code FROM technicians WHERE technician_code LIKE 'TECH-%%' ORDER BY technician_code DESC LIMIT 1"
                    ).fetchone()
                    if last_tech:
                        last_num = int(last_tech["technician_code"].split("-")[1])
                        values["technician_code"] = f"TECH-{last_num + 1:03d}"
                    else:
                        values["technician_code"] = "TECH-001"
                else:
                    values["technician_code"] = request.form.get("technician_code", "").strip()
                    if not values["technician_code"]:
                        errors.append("Field staff code is required for updates")

                if errors:
                    for err in errors:
                        flash(err, "error")
                else:
                    try:
                        if action == "create":
                            existing = db.execute(
                                "SELECT technician_code FROM technicians WHERE technician_code = ?",
                                (values["technician_code"],)
                            ).fetchone()
                            if existing:
                                flash("Field staff code already exists", "error")
                            else:
                                password_hash = generate_password_hash(values["password"]) if values["password"] else ""
                                db.execute("""
                                    INSERT INTO technicians
                                    (technician_code, party_code, user_id, password_hash, phone_number, specialization, status)
                                    VALUES (?, NULL, ?, ?, ?, ?, ?)
                                """, (
                                    values["technician_code"],
                                    values["user_id"],
                                    password_hash,
                                    values["phone_number"],
                                    values["specialization"],
                                    values["status"],
                                ))
                                _sync_field_staff_profile(
                                    values["technician_code"],
                                    values["specialization"],
                                    values["phone_number"],
                                    values["status"],
                                )
                                db.commit()
                                flash("Field staff created successfully", "success")
                                return redirect(url_for("technicians"))

                        elif action == "update":
                            db.execute("""
                                UPDATE technicians
                                SET user_id = ?, phone_number = ?,
                                    specialization = ?, status = ?
                                WHERE technician_code = ?
                            """, (
                                values["user_id"],
                                values["phone_number"],
                                values["specialization"],
                                values["status"],
                                values["technician_code"],
                            ))
                            if values["password"]:
                                password_hash = generate_password_hash(values["password"])
                                db.execute("""
                                    UPDATE technicians
                                    SET password_hash = ?
                                    WHERE technician_code = ?
                                """, (password_hash, values["technician_code"]))
                            _sync_field_staff_profile(
                                values["technician_code"],
                                values["specialization"],
                                values["phone_number"],
                                values["status"],
                            )
                            db.commit()
                            flash("Field staff updated successfully", "success")
                            return redirect(url_for("technicians"))

                    except Exception as e:
                        db.rollback()
                        flash(f"Error saving field staff: {str(e)}", "error")

            elif action == "issue_payment":
                payment_values = {
                    "technician_code": request.form.get("payment_technician_code", "").strip(),
                    "entry_date": request.form.get("payment_entry_date", "").strip() or date.today().isoformat(),
                    "funding_source": request.form.get("payment_funding_source", "Owner Fund").strip() or "Owner Fund",
                    "amount": request.form.get("payment_amount", "").strip(),
                    "reference": request.form.get("payment_reference", "").strip(),
                    "notes": request.form.get("payment_notes", "").strip(),
                }
                try:
                    if not payment_values["technician_code"]:
                        raise ValidationError("Select field staff for payment.")
                    staff_row = db.execute(
                        """
                        SELECT technician_code, specialization, phone_number, status
                        FROM technicians
                        WHERE technician_code = ?
                        """,
                        (payment_values["technician_code"],),
                    ).fetchone()
                    if staff_row is None:
                        raise ValidationError("Selected field staff was not found.")
                    amount = float(payment_values["amount"] or 0)
                    if amount <= 0:
                        raise ValidationError("Payment amount must be greater than 0.")
                    _sync_field_staff_profile(
                        staff_row["technician_code"],
                        staff_row["specialization"] or staff_row["technician_code"],
                        staff_row["phone_number"] or "",
                        staff_row["status"] or "Active",
                    )
                    advance_no = _next_reference_code(db, "maintenance_staff_advances", "advance_no", "ADV")
                    db.execute(
                        """
                        INSERT INTO maintenance_staff_advances (
                            advance_no, staff_code, entry_date, funding_source,
                            amount, settled_amount, balance_amount, reference, notes
                        ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                        """,
                        (
                            advance_no,
                            payment_values["technician_code"],
                            payment_values["entry_date"],
                            payment_values["funding_source"],
                            amount,
                            amount,
                            payment_values["reference"] or None,
                            payment_values["notes"] or None,
                        ),
                    )
                    db.commit()
                    flash(f"Payment of AED {amount:.2f} issued to {staff_row['specialization'] or staff_row['technician_code']}.", "success")
                    return redirect(url_for("technicians"))
                except ValidationError as exc:
                    db.rollback()
                    flash(str(exc), "error")
                except Exception as exc:
                    db.rollback()
                    flash(f"Error issuing field staff payment: {exc}", "error")

            elif action == "delete":
                technician_code = request.form.get("technician_code", "").strip()
                try:
                    if not technician_code:
                        raise ValidationError("Field staff code is required for delete.")
                    linked_jobs = int(db.execute("SELECT COUNT(*) FROM maintenance_papers WHERE technician_code = ?", (technician_code,)).fetchone()[0] or 0)
                    linked_advances = int(db.execute("SELECT COUNT(*) FROM maintenance_staff_advances WHERE staff_code = ?", (technician_code,)).fetchone()[0] or 0)
                    if linked_jobs > 0 or linked_advances > 0:
                        db.execute("UPDATE technicians SET status = 'Inactive' WHERE technician_code = ?", (technician_code,))
                        db.execute("UPDATE maintenance_staff SET status = 'Inactive' WHERE staff_code = ?", (technician_code,))
                        db.commit()
                        flash("Field staff has linked entries, so the account was set to Inactive instead of being deleted.", "warning")
                    else:
                        db.execute("DELETE FROM maintenance_staff WHERE staff_code = ?", (technician_code,))
                        db.execute("DELETE FROM technicians WHERE technician_code = ?", (technician_code,))
                        db.commit()
                        flash("Field staff deleted successfully.", "success")
                    return redirect(url_for("technicians"))
                except ValidationError as exc:
                    db.rollback()
                    flash(str(exc), "error")
                except Exception as exc:
                    db.rollback()
                    flash(f"Error deleting field staff: {exc}", "error")

            elif action == "delete_payment":
                advance_no = request.form.get("advance_no", "").strip().upper()
                try:
                    if not advance_no:
                        raise ValidationError("Payment reference is required for delete.")
                    payment_row = db.execute(
                        """
                        SELECT advance_no
                        FROM maintenance_staff_advances
                        WHERE advance_no = ?
                        """,
                        (advance_no,),
                    ).fetchone()
                    if payment_row is None:
                        raise ValidationError("Payment record was not found.")
                    linked_papers = int(
                        db.execute(
                            "SELECT COUNT(*) FROM maintenance_papers WHERE advance_no = ?",
                            (advance_no,),
                        ).fetchone()[0]
                        or 0
                    )
                    if linked_papers > 0:
                        raise ValidationError("This payment is linked with expense entries and cannot be deleted.")
                    db.execute(
                        "DELETE FROM maintenance_staff_advances WHERE advance_no = ?",
                        (advance_no,),
                    )
                    db.commit()
                    flash("Field staff payment deleted successfully.", "success")
                    return redirect(url_for("technicians"))
                except ValidationError as exc:
                    db.rollback()
                    flash(str(exc), "error")
                except Exception as exc:
                    db.rollback()
                    flash(f"Error deleting field staff payment: {exc}", "error")
        
        return render_template(
            "technicians.html",
            technicians=technicians_list,
            parties=parties,
            values=values,
            payment_values=payment_values,
            recent_payments=recent_payments,
            summary=summary,
            owner_fund_balance=owner_fund_balance,
            edit_technician_code=edit_technician_code,
            status_filter=status_filter,
            search_q=search_q,
        )

    @app.route("/owner-fund", methods=["GET", "POST"])
    @_login_required("admin", "owner")
    def owner_fund():
        if _current_role() == "admin":
            _touch_admin_workspace("accounts")
        db = open_db()
        can_edit = _current_role() == "admin"
        filters = _owner_fund_filter_values(request)
        edit_entry_id = request.args.get("edit", "").strip()
        values = {
            "entry_id": "",
            "owner_name": "",
            "entry_date": date.today().isoformat(),
            "amount": "",
            "received_by": "",
            "payment_method": "Cash",
            "transaction_type": "IN",
            "details": "",
        }

        if edit_entry_id:
            existing_entry = db.execute(
                """
                SELECT id, owner_name, entry_date, amount, received_by, payment_method, transaction_type, details
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
                    "transaction_type": existing_entry["transaction_type"] or "IN",
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
                "transaction_type": request.form.get("transaction_type", "IN").strip() or "IN",
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
                            SET owner_name = ?, entry_date = ?, amount = ?, received_by = ?, payment_method = ?, transaction_type = ?, details = ?
                            WHERE id = ?
                            """,
                            (
                                values["owner_name"],
                                values["entry_date"],
                                amount,
                                values["received_by"],
                                values["payment_method"],
                                values["transaction_type"],
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
                            INSERT INTO owner_fund_entries (owner_name, entry_date, amount, received_by, payment_method, transaction_type, details)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                values["owner_name"],
                                values["entry_date"],
                                amount,
                                values["received_by"],
                                values["payment_method"],
                                values["transaction_type"],
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
        view_rows = _owner_fund_statement(db, reverse=False, filters=filters)
        view_incoming, view_outgoing, view_net, view_closing = _owner_fund_view_totals(view_rows)
        entries = db.execute(
            """
            SELECT id, owner_name, entry_date, amount, received_by, payment_method, transaction_type, details
            FROM owner_fund_entries
            ORDER BY entry_date DESC, id DESC
            LIMIT 20
            """
        ).fetchall()
        statement = list(reversed(view_rows))
        pdf_files = _recent_generated_files(Path(app.config["GENERATED_DIR"]) / "owner_fund", "owner-fund-kata")
        pdf_url = url_for(
            "owner_fund_pdf",
            month=filters["month"],
            movement=filters["movement"],
            search=filters["search"],
        )

        return render_template(
            "owner_fund.html",
            values=values,
            incoming=incoming,
            outgoing=outgoing,
            balance=balance,
            view_incoming=view_incoming,
            view_outgoing=view_outgoing,
            view_net=view_net,
            view_closing=view_closing,
            entries=entries,
            statement=statement,
            can_edit=can_edit,
            pdf_files=pdf_files,
            filters=filters,
            movement_options=OWNER_FUND_MOVEMENT_OPTIONS,
            pdf_url=pdf_url,
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
        filters = _owner_fund_filter_values(request)
        statement = _owner_fund_statement(db, reverse=False, filters=filters)
        view_incoming, view_outgoing, view_net, view_closing = _owner_fund_view_totals(statement)
        output_dir = Path(app.config["GENERATED_DIR"]) / "owner_fund"
        pdf_path = generate_owner_fund_pdf(
            statement,
            {
                "incoming": view_incoming,
                "outgoing": view_outgoing,
                "balance": view_net,
                "closing_balance": view_closing if statement else balance,
                "overall_balance": balance,
                "overall_incoming": incoming,
                "overall_outgoing": outgoing,
            },
            str(output_dir),
            app.config["STATIC_ASSETS_DIR"],
            filters=filters,
        )
        _mirror_generated_file(app, pdf_path)
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
            SELECT entry_date, txn_type, source, given_by, amount, details
            FROM driver_transactions
            WHERE driver_id = ? AND entry_date >= ? AND entry_date < ?
            ORDER BY entry_date DESC, id DESC
            LIMIT 12
            """,
            (driver["driver_id"], f"{selected_month}-01", f"{_next_month_value(selected_month)}-01"),
        ).fetchall()
        salary_slips = db.execute(
            """
            SELECT salary_month, net_payable, total_deductions, salary_after_deduction, actual_paid_amount,
                   company_balance_due, pdf_path, payment_source, generated_at
            FROM salary_slips
            WHERE driver_id = ? AND salary_month = ?
            ORDER BY generated_at DESC, id DESC
            LIMIT 12
            """,
            (driver["driver_id"], selected_month),
        ).fetchall()
        month_hours = _timesheet_total_for_month(db, driver["driver_id"], selected_month)
        month_calendar = _driver_month_calendar(db, driver["driver_id"], selected_month)
        timesheet_summary = _timesheet_month_summary(month_calendar)
        kata_entries, kata_summary = _driver_kata_month_data(db, driver["driver_id"], selected_month)

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
            kata_entries=kata_entries,
            kata_summary=kata_summary,
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

    @app.route("/drivers/payroll")
    @_login_required("admin")
    def driver_payroll_board():
        _touch_admin_workspace("drivers")
        db = open_db()

        # ── Filters ──────────────────────────────────────────────────
        selected_year = request.args.get("year", "").strip()
        selected_month = request.args.get("month", "").strip()  # e.g. "04"
        status_filter = request.args.get("pay_status", "").strip()  # Paid/Partial/Unpaid/Stored/All
        search_q = request.args.get("q", "").strip().lower()

        current_year = date.today().year
        if not selected_year or not selected_year.isdigit():
            selected_year = str(current_year)
        year_int = int(selected_year)

        # Available years: from earliest salary_store entry to current
        year_range_row = db.execute("SELECT MIN(salary_month), MAX(salary_month) FROM salary_store").fetchone()
        min_year = int((year_range_row[0] or f"{current_year}-01")[:4])
        max_year = max(int((year_range_row[1] or f"{current_year}-12")[:4]), current_year)
        available_years = list(range(min_year, max_year + 1))

        # Month columns for selected year
        month_keys = [f"{year_int:04d}-{m:02d}" for m in range(1, 13)]  # "2025-01" … "2025-12"
        month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        # ── Fetch all drivers ────────────────────────────────────────
        all_drivers = db.execute(
            """
            SELECT driver_id, full_name, basic_salary, status
            FROM drivers
            ORDER BY CASE WHEN status = 'Active' THEN 0 ELSE 1 END, full_name ASC
            """
        ).fetchall()

        # ── Fetch salary_store rows for this year (all drivers) ──────
        salary_rows = db.execute(
            """
            SELECT driver_id, salary_month, net_salary
            FROM salary_store
            WHERE salary_month LIKE ?
            """,
            (f"{year_int}-%",),
        ).fetchall()
        # {driver_id: {month_key: net_salary}}
        salary_map: dict[str, dict[str, float]] = {}
        for row in salary_rows:
            salary_map.setdefault(row["driver_id"], {})[row["salary_month"]] = float(row["net_salary"] or 0)

        # ── Fetch salary_slips for this year (total paid deductions) ─
        slip_rows = db.execute(
            """
            SELECT driver_id, salary_month, SUM(net_payable) AS total_net_payable
            FROM salary_slips
            WHERE salary_month LIKE ?
            GROUP BY driver_id, salary_month
            """,
            (f"{year_int}-%",),
        ).fetchall()
        # {driver_id: {month_key: total_net_payable}}
        slip_map: dict[str, dict[str, float]] = {}
        for row in slip_rows:
            slip_map.setdefault(row["driver_id"], {})[row["salary_month"]] = float(row["total_net_payable"] or 0)

        # ── Build matrix rows ────────────────────────────────────────
        # Status logic per month cell:
        #  "paid"    → slip net_payable >= salary net_salary (with small tolerance)
        #  "partial" → slip exists but partial
        #  "stored"  → salary stored but no slip generated yet
        #  "unpaid"  → no salary_store entry

        today_month = _current_month_value()

        def _month_status(driver_id, month_key):
            net_salary = salary_map.get(driver_id, {}).get(month_key)
            net_paid = slip_map.get(driver_id, {}).get(month_key)
            if net_salary is None:
                return "unpaid"  # no record
            if net_paid is None or net_paid <= 0:
                return "stored"  # salary stored, not yet paid
            if net_paid >= net_salary - 0.5:
                return "paid"
            return "partial"

        matrix = []
        for driver in all_drivers:
            did = driver["driver_id"]
            name = driver["full_name"] or ""
            # Apply search filter
            if search_q and search_q not in name.lower() and search_q not in did.lower():
                continue

            months_data = []
            for mk in month_keys:
                st = _month_status(did, mk)
                # Future months that haven't arrived yet → mark as future
                if mk > today_month:
                    st = "future"
                months_data.append({"key": mk, "status": st})

            # Current-month status
            cur_status = _month_status(did, today_month)
            if today_month > month_keys[-1] or today_month < month_keys[0]:
                cur_status = "future"

            paid_count = sum(1 for m in months_data if m["status"] == "paid")
            partial_count = sum(1 for m in months_data if m["status"] == "partial")
            outstanding = max(
                sum(salary_map.get(did, {}).get(mk, 0) for mk in month_keys
                    if _month_status(did, mk) in ("unpaid", "stored", "partial"))
                - sum(slip_map.get(did, {}).get(mk, 0) for mk in month_keys),
                0.0,
            )

            row_obj = {
                "driver_id": did,
                "name": name,
                "basic_salary": float(driver["basic_salary"] or 0),
                "status": driver["status"] or "",
                "months": months_data,
                "cur_status": cur_status,
                "paid_count": paid_count,
                "partial_count": partial_count,
                "outstanding": round(outstanding, 2),
            }

            # Apply pay_status filter (based on current/selected month)
            if status_filter and status_filter != "all":
                ref_month = f"{year_int}-{selected_month.zfill(2)}" if selected_month else today_month
                ref_st = _month_status(did, ref_month)
                if ref_month > today_month:
                    ref_st = "future"
                if status_filter == "paid" and ref_st != "paid":
                    continue
                if status_filter == "partial" and ref_st != "partial":
                    continue
                if status_filter == "unpaid" and ref_st not in ("unpaid", "stored"):
                    continue

            matrix.append(row_obj)

        # ── Summary cards ────────────────────────────────────────────
        ref_month_for_summary = f"{year_int}-{selected_month.zfill(2)}" if selected_month else today_month
        if ref_month_for_summary > today_month:
            ref_month_for_summary = today_month

        paid_this_month = sum(
            1 for r in matrix
            if _month_status(r["driver_id"], ref_month_for_summary) == "paid"
        )
        partial_this_month = sum(
            1 for r in matrix
            if _month_status(r["driver_id"], ref_month_for_summary) == "partial"
        )
        stored_this_month = sum(
            1 for r in matrix
            if _month_status(r["driver_id"], ref_month_for_summary) == "stored"
        )
        unpaid_this_month = sum(
            1 for r in matrix
            if _month_status(r["driver_id"], ref_month_for_summary) == "unpaid"
        )
        total_salary_this_month = round(sum(
            salary_map.get(r["driver_id"], {}).get(ref_month_for_summary, 0)
            for r in matrix
        ), 2)
        total_paid_this_month = round(sum(
            slip_map.get(r["driver_id"], {}).get(ref_month_for_summary, 0)
            for r in matrix
        ), 2)
        total_outstanding = round(sum(r["outstanding"] for r in matrix), 2)

        summary = {
            "total_drivers": len(matrix),
            "paid_this_month": paid_this_month,
            "partial_this_month": partial_this_month,
            "stored_this_month": stored_this_month,
            "unpaid_this_month": unpaid_this_month,
            "total_salary_this_month": total_salary_this_month,
            "total_paid_this_month": total_paid_this_month,
            "total_outstanding": total_outstanding,
            "ref_month_label": f"{year_int}-{selected_month.zfill(2)}" if selected_month else today_month,
        }

        return render_template(
            "driver_payroll.html",
            matrix=matrix,
            month_labels=month_labels,
            month_keys=month_keys,
            summary=summary,
            selected_year=selected_year,
            selected_month=selected_month,
            status_filter=status_filter,
            search_q=search_q,
            available_years=available_years,
            today_month=today_month,
            ref_month_for_summary=ref_month_for_summary,
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
        selected_kata_month = _normalize_month(request.args.get("kata_month", "").strip() or current_month)
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
        kata_entries, kata_summary = _driver_kata_month_data(db, driver_id, selected_kata_month)

        return render_template(
            "driver_action.html",
            driver=driver,
            photo_url=_driver_photo_url(app, driver),
            salary_status="Stored" if current_salary else "Not Stored",
            current_month_label=format_month_label(current_month),
            current_month_value=current_month,
            selected_kata_month=selected_kata_month,
            selected_kata_month_label=format_month_label(selected_kata_month),
            salary_due=_driver_balance(db, driver_id),
            advance_summary=_advance_summary(db, driver_id),
            outstanding_advance=_outstanding_advance(db, driver_id),
            transaction_count=db.execute(
                "SELECT COUNT(*) FROM driver_transactions WHERE driver_id = ?",
                (driver_id,),
            ).fetchone()[0],
            kata_entries=kata_entries,
            kata_summary=kata_summary,
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

        history_rows = _driver_transaction_history_rows(db, driver_id)
        return render_template(
            "driver_transactions.html",
            driver=driver,
            photo_url=_driver_photo_url(app, driver),
            values=form,
            history_rows=history_rows,
            transaction_types=TRANSACTION_TYPES,
            payment_sources=PAYMENT_SOURCES,
            salary_due=_driver_balance(db, driver_id),
            advance_summary=_advance_summary(db, driver_id),
            history_total=len(history_rows),
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

    @app.post("/drivers/<driver_id>/salary-slip/<int:slip_id>/delete")
    @_login_required("admin")
    def delete_salary_slip(driver_id: str, slip_id: int):
        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for("dashboard"))
        existing_slip = db.execute(
            "SELECT id FROM salary_slips WHERE id = ? AND driver_id = ?",
            (slip_id, driver_id),
        ).fetchone()
        if existing_slip is not None:
            db.execute(
                "DELETE FROM salary_slips WHERE id = ? AND driver_id = ?",
                (slip_id, driver_id),
            )
            _audit_log(
                db,
                "salary_slip_deleted",
                entity_type="salary_slip",
                entity_id=str(slip_id),
                details=driver_id,
            )
            db.commit()
            _regenerate_kata_for_driver(app, db, driver)
            flash("Salary paid entry deleted and KATA refreshed.", "success")
        else:
            flash("Salary paid entry was not found.", "error")
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
                "prorata_end_date": request.form.get("prorata_end_date", "").strip(),
                "ot_hours": request.form.get("ot_hours", "0").strip() or "0",
                "personal_vehicle": request.form.get("personal_vehicle", "0").strip() or "0",
                "personal_vehicle_note": request.form.get("personal_vehicle_note", "").strip(),
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
                               ot_amount, personal_vehicle, personal_vehicle_note, net_salary, remarks
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
                        ot_amount, personal_vehicle, personal_vehicle_note, net_salary, remarks
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        personal_vehicle_note = excluded.personal_vehicle_note,
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
                        preview["personal_vehicle_note"] or None,
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
                   ot_amount, personal_vehicle, personal_vehicle_note, net_salary, remarks
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
        values = {
            "deduction_amount": "0.00",
            "actual_paid_amount": "",
            "payment_source": PAYMENT_SOURCES[0],
            "paid_by": "",
        }

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
                    slip_amounts = _salary_slip_amounts(existing_slip)
                    values = {
                        "deduction_amount": f"{float(existing_slip['total_deductions']):.2f}",
                        "actual_paid_amount": f"{slip_amounts['actual_paid_amount']:.2f}",
                        "payment_source": existing_slip["payment_source"] or PAYMENT_SOURCES[0],
                        "paid_by": existing_slip["paid_by"] or "",
                    }

        if request.method == "POST":
            selected_salary_id = request.form.get("salary_store_id", "").strip()
            values = {
                "deduction_amount": request.form.get("deduction_amount", "0").strip() or "0",
                "actual_paid_amount": request.form.get("actual_paid_amount", "").strip(),
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
                    salary_after_deduction = float(selected_salary["net_salary"]) - deduction_amount
                    if salary_after_deduction < 0:
                        flash("Deduction cannot be greater than the salary amount.", "error")
                    else:
                        try:
                            actual_paid_amount = _parse_decimal(
                                values["actual_paid_amount"] or f"{salary_after_deduction:.2f}",
                                "Actual paid amount",
                                required=False,
                                default=salary_after_deduction,
                                minimum=0.0,
                            )
                        except ValidationError as exc:
                            flash(str(exc), "error")
                            actual_paid_amount = None
                        if actual_paid_amount is None:
                            pass
                        elif actual_paid_amount > salary_after_deduction + 0.001:
                            flash(f"Actual paid amount cannot be more than {salary_after_deduction:,.2f}.", "error")
                        else:
                            company_balance_due = max(salary_after_deduction - actual_paid_amount, 0.0)
                            slip_payload = {
                                "available_advance": available_advance,
                                "deduction_amount": deduction_amount,
                                "remaining_advance": max(available_advance - deduction_amount, 0),
                                "salary_after_deduction": salary_after_deduction,
                                "actual_paid_amount": actual_paid_amount,
                                "company_balance_due": company_balance_due,
                                "payment_source": values["payment_source"],
                                "paid_by": values["paid_by"],
                                "net_payable": actual_paid_amount,
                            }
                            pdf_path = generate_salary_slip_pdf(
                                driver,
                                selected_salary,
                                slip_payload,
                                str(_driver_output_dir(app, driver_id, driver=driver) / "salary_slips"),
                                app.config["STATIC_ASSETS_DIR"],
                                app.config["GENERATED_DIR"],
                            )
                            _mirror_generated_file(app, pdf_path)
                            relative_path = Path(pdf_path).relative_to(app.config["GENERATED_DIR"]).as_posix()
                            if existing_slip is not None:
                                db.execute(
                                    """
                                    UPDATE salary_slips
                                    SET total_deductions = ?, available_advance = ?, remaining_advance = ?,
                                        salary_after_deduction = ?, actual_paid_amount = ?, company_balance_due = ?,
                                        payment_source = ?, paid_by = ?, net_payable = ?, pdf_path = ?,
                                        generated_at = CURRENT_TIMESTAMP
                                    WHERE id = ? AND driver_id = ?
                                    """,
                                    (
                                        deduction_amount,
                                        available_advance,
                                        max(available_advance - deduction_amount, 0),
                                        salary_after_deduction,
                                        actual_paid_amount,
                                        company_balance_due,
                                        values["payment_source"],
                                        values["paid_by"],
                                        actual_paid_amount,
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
                                    details=f"{driver_id}:{selected_salary['salary_month']} / paid AED {actual_paid_amount:.2f} / balance AED {company_balance_due:.2f}",
                                )
                                success_message = "Salary slip updated and KATA refreshed inside the driver folder."
                            else:
                                db.execute(
                                    """
                                    INSERT INTO salary_slips (
                                        driver_id, salary_store_id, salary_month, source_filter, total_deductions,
                                        available_advance, remaining_advance, salary_after_deduction, actual_paid_amount,
                                        company_balance_due, payment_source, paid_by, net_payable, pdf_path
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        driver_id,
                                        selected_salary["id"],
                                        selected_salary["salary_month"],
                                        None,
                                        deduction_amount,
                                        available_advance,
                                        max(available_advance - deduction_amount, 0),
                                        salary_after_deduction,
                                        actual_paid_amount,
                                        company_balance_due,
                                        values["payment_source"],
                                        values["paid_by"],
                                        actual_paid_amount,
                                        relative_path,
                                    ),
                                )
                                _audit_log(
                                    db,
                                    "salary_slip_generated",
                                    entity_type="salary_slip",
                                    entity_id=f"{driver_id}:{selected_salary['salary_month']}",
                                    details=f"OT month {selected_salary['ot_month'] or _previous_month_value(selected_salary['salary_month'])} / paid AED {actual_paid_amount:.2f} / balance AED {company_balance_due:.2f}",
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
                   salary_after_deduction, actual_paid_amount, company_balance_due,
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
                salary_after_deduction = max(float(selected_salary["net_salary"]) - deduction_amount, 0.0)
                actual_paid_amount = None
                if values["actual_paid_amount"].strip():
                    try:
                        actual_paid_amount = _parse_decimal(
                            values["actual_paid_amount"],
                            "Actual paid amount",
                            required=False,
                            default=salary_after_deduction,
                            minimum=0.0,
                        )
                    except ValidationError:
                        actual_paid_amount = None
                if actual_paid_amount is None:
                    actual_paid_amount = salary_after_deduction
                preview = {
                    "gross": float(selected_salary["net_salary"]),
                    "available_advance": available_advance,
                    "deduction_amount": deduction_amount,
                    "remaining_advance": max(available_advance - deduction_amount, 0),
                    "salary_after_deduction": salary_after_deduction,
                    "actual_paid_amount": actual_paid_amount,
                    "company_balance_due": max(salary_after_deduction - actual_paid_amount, 0.0),
                    "net_payable": actual_paid_amount,
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
    @_login_required("admin", "driver")
    def driver_kata_pdf(driver_id: str):
        if _current_role() == "driver" and _current_driver_id() != driver_id:
            flash("You do not have access to that KATA.", "error")
            return redirect(url_for("driver_portal"))

        db = open_db()
        driver = _fetch_driver(db, driver_id)
        if driver is None:
            flash("Driver not found.", "error")
            return redirect(url_for(_role_home_endpoint()))
        selected_month = _normalize_month(request.args.get("month", "").strip() or _current_month_value())
        statement_mode = request.args.get("mode", "").strip().lower()
        pdf_path = _regenerate_kata_for_driver(
            app,
            db,
            driver,
            month_value=None if statement_mode == "full" else selected_month,
        )
        if pdf_path is None:
            flash("No salary or transaction data is available for this driver yet.", "error")
            if _current_role() == "driver":
                return redirect(url_for("driver_portal", month=selected_month))
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
        _mirror_generated_file(app, pdf_path)
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
    @_login_required("admin", "owner", "driver", "supplier")
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


def _auth_identifier(role: str, phone_number: str = "", supplier_code: str = "", technician_code: str = "") -> str:
    if role == "driver":
        normalized_phone = _normalize_phone(phone_number)
        return normalized_phone or _client_ip()
    if role == "supplier":
        return (supplier_code or "").strip().upper() or _client_ip()
    if role == "technician":
        return (technician_code or "").strip().upper() or _client_ip()
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


def _set_session(role: str, driver_id: str | None = None, supplier_party_code: str | None = None, display_name: str = "") -> None:
    session.clear()
    session.permanent = True
    session["role"] = role
    session["display_name"] = display_name
    if role == "admin":
        session["admin_workspace"] = "universal"
    if driver_id:
        session["driver_id"] = driver_id
    if supplier_party_code:
        session["supplier_party_code"] = supplier_party_code


def _current_role() -> str:
    return session.get("role", "")


def _current_driver_id() -> str:
    return session.get("driver_id", "")


def _current_supplier_party_code() -> str:
    return session.get("supplier_party_code", "")


def _role_home_endpoint() -> str:
    role = _current_role()
    if role == "admin":
        return _workspace_home_endpoint(_current_admin_workspace())
    if role == "owner":
        return "owner_fund"
    if role == "driver":
        return "driver_portal"
    if role == "supplier":
        return "supplier_portal"
    if role == "technician":
        return "technician_portal"
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
        "suppliers-normal": "suppliers",
        "suppliers-partnership": "partnership_suppliers",
        "suppliers-managed": "managed_suppliers",
        "suppliers-cash": "cash_suppliers",
        "customers": "customers",
        "accounts": "reports_center",
        "technicians": "technicians",
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
    if role == "supplier":
        return {
            "key": "supplier",
            "label": "Supplier",
            "eyebrow": "Supplier Portal",
            "title": "Supplier Procurement Portal",
            "summary": "Submit quotations, track LPOs, manage invoices and review your statement of account.",
        }
    if role == "technician":
        return {
            "key": "technician",
            "label": "Field Staff",
            "eyebrow": "Field Staff Portal",
            "title": "Field Staff Self Service",
            "summary": "Submit workshop, fuel and general expense entries with bill photos from mobile.",
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
            {"label": "Normal Desk", "endpoint": "suppliers", "primary": True},
            {"label": "Partnership Desk", "endpoint": "partnership_suppliers"},
        ],
        "suppliers-normal": [
            {"label": "New Supplier", "endpoint": "suppliers", "primary": True},
            {"label": "Partnership Desk", "endpoint": "partnership_suppliers"},
            {"label": "Managed Desk", "endpoint": "managed_suppliers"},
            {"label": "Quotations", "endpoint": "admin_supplier_quotations"},
            {"label": "Registrations", "endpoint": "supplier_registrations"},
        ],
        "suppliers-partnership": [
            {"label": "New Partner Supplier", "endpoint": "partnership_suppliers", "primary": True},
            {"label": "Normal Desk", "endpoint": "suppliers"},
            {"label": "Managed Desk", "endpoint": "managed_suppliers"},
        ],
        "suppliers-managed": [
            {"label": "New Managed Supplier", "endpoint": "managed_suppliers", "primary": True},
            {"label": "Supplier Cards", "endpoint": "managed_supplier_cards"},
        ],
        "suppliers-cash": [
            {"label": "New Cash Supplier", "endpoint": "cash_suppliers", "primary": True},
            {"label": "Supplier Cards", "endpoint": "cash_supplier_cards"},
            {"label": "Portal Desk", "endpoint": "suppliers"},
        ],
        "customers": [
            {"label": "Invoices", "endpoint": "invoice_center"},
        ],
        "accounts": [
            {"label": "Owner Fund", "endpoint": "owner_fund", "primary": True},
            {"label": "Fleet Maintenance", "endpoint": "fleet_maintenance"},
            {"label": "Tax", "endpoint": "tax_center"},
        ],
        "technicians": [
            {"label": "Field Staff", "endpoint": "technicians", "primary": True},
            {"label": "Field Staff Entries", "endpoint": "technician_jobs"},
            {"label": "Field Staff Portal", "endpoint": "technician_portal"},
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


def _default_customer_form():
    values = _default_party_form()
    values["party_roles"] = ["Customer"]
    values["original_party_code"] = ""
    return values


def _customer_form_data(request):
    values = _party_form_data(request)
    values["original_party_code"] = request.form.get("original_party_code", "").strip().upper()
    values["party_roles"] = ["Customer"]
    return values


def _customer_form_from_party(record):
    values = _party_values_from_record(record)
    values["original_party_code"] = record["party_code"]
    values["party_roles"] = ["Customer"]
    return values


def _prepare_customer_party_payload(db, values):
    if not values["party_name"]:
        raise ValidationError("Customer name is required.")
    values["party_roles"] = ["Customer"]
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


def _ensure_workshop_party(db, workshop_name: str) -> str:
    normalized_name = (workshop_name or "").strip()
    if not normalized_name:
        raise ValidationError("Workshop / shop name is required.")
    existing = db.execute(
        """
        SELECT party_code
        FROM parties
        WHERE LOWER(party_name) = LOWER(?)
        ORDER BY party_code ASC
        LIMIT 1
        """,
        (normalized_name,),
    ).fetchone()
    if existing is not None:
        return existing["party_code"]

    party_code = _next_party_code(db)
    db.execute(
        """
        INSERT INTO parties (
            party_code, party_name, party_kind, party_roles, contact_person,
            phone_number, email, trn_no, trade_license_no, address, notes, status
        ) VALUES (?, ?, 'Company', ?, '', '', '', '', '', '', ?, 'Active')
        """,
        (
            party_code,
            normalized_name,
            _serialize_party_roles(["Supplier"]),
            "Auto-created from field staff portal",
        ),
    )
    return party_code



def _parties_by_role(db, role: str, active_only: bool = False):
    status_clause = "AND status = 'Active'" if active_only else ""
    return db.execute(
        f"""
        SELECT
            party_code, party_name, party_kind, party_roles, contact_person,
            phone_number, email, trn_no, trade_license_no, address, notes, status, created_at
        FROM parties
        WHERE party_roles LIKE ?
        {status_clause}
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


def _fleet_vehicle_row(db, vehicle_id: str, *, required: bool = False):
    row = db.execute(
        """
        SELECT
            vehicle_id, vehicle_no, vehicle_type, make_model, status, shift_mode, ownership_mode,
            source_type, source_party_code, source_asset_code,
            partner_party_code, partner_name, company_share_percent, partner_share_percent, notes, created_at
        FROM vehicle_master
        WHERE vehicle_id = ?
        """,
        (vehicle_id,),
    ).fetchone()
    if row is None and required:
        raise ValidationError("Selected vehicle was not found.")
    return row


def _partnership_supplier_asset_row(db, asset_code: str, *, required: bool = False):
    row = db.execute(
        """
        SELECT
            asset.asset_code,
            asset.party_code,
            asset.asset_name,
            asset.asset_type,
            asset.vehicle_no,
            asset.double_shift_mode,
            asset.partnership_mode,
            COALESCE(profile.partner_party_code, '') AS partner_party_code,
            COALESCE(profile.partner_name, asset.partner_name, '') AS partner_name,
            CASE
                WHEN asset.company_share_percent IS NULL OR asset.company_share_percent = 0
                THEN COALESCE(profile.default_company_share_percent, 50)
                ELSE asset.company_share_percent
            END AS company_share_percent,
            CASE
                WHEN asset.partner_share_percent IS NULL OR asset.partner_share_percent = 0
                THEN COALESCE(profile.default_partner_share_percent, 50)
                ELSE asset.partner_share_percent
            END AS partner_share_percent,
            party.party_name
        FROM supplier_assets asset
        JOIN parties party ON party.party_code = asset.party_code
        LEFT JOIN supplier_profile profile ON profile.party_code = asset.party_code
        WHERE asset.asset_code = ? AND COALESCE(profile.supplier_mode, 'Normal') = 'Partnership'
        """,
        (asset_code,),
    ).fetchone()
    if row is None and required:
        raise ValidationError("Select a valid partnership supplier vehicle first.")
    return row


def _partnership_supplier_asset_options(db):
    return db.execute(
        """
        SELECT
            asset.asset_code,
            asset.party_code,
            asset.asset_name,
            asset.vehicle_no,
            asset.asset_type,
            asset.double_shift_mode,
            party.party_name,
            COALESCE(profile.partner_name, asset.partner_name, 'Partner') AS partner_name
        FROM supplier_assets asset
        JOIN parties party ON party.party_code = asset.party_code
        LEFT JOIN supplier_profile profile ON profile.party_code = asset.party_code
        WHERE COALESCE(profile.supplier_mode, 'Normal') = 'Partnership'
        ORDER BY party.party_name ASC, asset.asset_name ASC
        """
    ).fetchall()


def _ensure_supplier_vehicle_shadow(db, asset_row):
    vehicle_id = f"PSV-{asset_row['asset_code']}"
    payload = (
        vehicle_id,
        (asset_row["vehicle_no"] or asset_row["asset_code"] or "").strip().upper(),
        asset_row["asset_type"] or "Supplier Vehicle",
        asset_row["asset_name"] or "Partnership Supplier Vehicle",
        "Active",
        asset_row["double_shift_mode"] or FLEET_SHIFT_MODE_OPTIONS[0],
        "Partnership",
        "Partnership Supplier Vehicle",
        asset_row["party_code"],
        asset_row["asset_code"],
        asset_row["partner_party_code"] or None,
        asset_row["partner_name"] or None,
        float(asset_row["company_share_percent"] or 50.0),
        float(asset_row["partner_share_percent"] or 50.0),
        f"Mirror vehicle for supplier asset {asset_row['asset_code']}",
    )
    existing = _fleet_vehicle_row(db, vehicle_id)
    if existing is None:
        db.execute(
            """
            INSERT INTO vehicle_master (
                vehicle_id, vehicle_no, vehicle_type, make_model, status,
                shift_mode, ownership_mode, source_type, source_party_code, source_asset_code,
                partner_party_code, partner_name, company_share_percent, partner_share_percent, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
    else:
        db.execute(
            """
            UPDATE vehicle_master
            SET vehicle_no = ?, vehicle_type = ?, make_model = ?, status = ?,
                shift_mode = ?, ownership_mode = ?, source_type = ?, source_party_code = ?, source_asset_code = ?,
                partner_party_code = ?, partner_name = ?, company_share_percent = ?, partner_share_percent = ?, notes = ?
            WHERE vehicle_id = ?
            """,
            payload[1:] + (vehicle_id,),
        )
    return _fleet_vehicle_row(db, vehicle_id, required=True)


def _maintenance_staff_row(db, staff_code: str, *, required: bool = False):
    row = db.execute(
        """
        SELECT staff_code, staff_name, phone_number, status, notes, created_at
        FROM maintenance_staff
        WHERE staff_code = ?
        """,
        (staff_code,),
    ).fetchone()
    if row is None and required:
        raise ValidationError("Selected technician was not found.")
    return row


def _maintenance_advance_row(db, advance_no: str, *, required: bool = False):
    row = db.execute(
        """
        SELECT
            advance_no, staff_code, entry_date, funding_source, amount, settled_amount, balance_amount,
            reference, notes, created_at
        FROM maintenance_staff_advances
        WHERE advance_no = ?
        """,
        (advance_no,),
    ).fetchone()
    if row is None and required:
        raise ValidationError("Selected field staff advance was not found.")
    return row


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
        "quotation_no": "",
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


def _default_fleet_vehicle_form(db=None):
    db = db or open_db()
    return {
        "original_vehicle_id": "",
        "vehicle_id": _next_reference_code(db, "vehicle_master", "vehicle_id", "VEH"),
        "vehicle_no": "",
        "vehicle_type": "",
        "make_model": "",
        "status": "Active",
        "shift_mode": FLEET_SHIFT_MODE_OPTIONS[0],
        "ownership_mode": FLEET_OWNERSHIP_MODE_OPTIONS[0],
        "partner_party_code": "",
        "partner_name": "",
        "company_share_percent": "100",
        "partner_share_percent": "0",
        "notes": "",
    }


def _default_maintenance_staff_form(db=None):
    db = db or open_db()
    return {
        "original_staff_code": "",
        "staff_code": _next_reference_code(db, "maintenance_staff", "staff_code", "TEC"),
        "staff_name": "",
        "phone_number": "",
        "status": "Active",
        "notes": "",
    }


def _default_maintenance_advance_form(db=None):
    db = db or open_db()
    return {
        "original_advance_no": "",
        "advance_no": _next_reference_code(db, "maintenance_staff_advances", "advance_no", "ADV"),
        "staff_code": "",
        "entry_date": date.today().isoformat(),
        "funding_source": MAINTENANCE_ADVANCE_SOURCE_OPTIONS[0],
        "amount": "",
        "reference": "",
        "notes": "",
    }


def _default_maintenance_paper_form(db=None):
    db = db or open_db()
    return {
        "original_paper_no": "",
        "paper_no": _next_reference_code(db, "maintenance_papers", "paper_no", "MTP"),
        "paper_date": date.today().isoformat(),
        "target_class": MAINTENANCE_TARGET_CLASS_OPTIONS[0],
        "vehicle_id": "",
        "target_asset_code": "",
        "workshop_party_code": "",
        "staff_code": "",
        "advance_no": "",
        "tax_mode": MAINTENANCE_TAX_MODE_OPTIONS[0],
        "supplier_bill_no": "",
        "work_summary": "",
        "funding_source": MAINTENANCE_FUNDING_SOURCE_OPTIONS[0],
        "paid_by": MAINTENANCE_PAID_BY_OPTIONS[0],
        "tax_amount": "0",
        "notes": "",
    }


def _default_maintenance_paper_lines():
    return [
        {
            "line_no": index + 1,
            "description": "",
            "quantity": "1",
            "rate": "",
            "amount": "",
        }
        for index in range(MAINTENANCE_LINE_SLOTS)
    ]


def _maintenance_paper_form_from_row(row):
    return {
        "original_paper_no": row["paper_no"],
        "paper_no": row["paper_no"],
        "paper_date": row["paper_date"],
        "target_class": row["target_class"] or MAINTENANCE_TARGET_CLASS_OPTIONS[0],
        "vehicle_id": row["vehicle_id"] or "",
        "target_asset_code": row["target_asset_code"] or "",
        "workshop_party_code": row["workshop_party_code"] or "",
        "staff_code": row["staff_code"] or "",
        "advance_no": row["advance_no"] or "",
        "tax_mode": row["tax_mode"] or MAINTENANCE_TAX_MODE_OPTIONS[0],
        "supplier_bill_no": row["supplier_bill_no"] or "",
        "work_summary": row["work_summary"] or "",
        "funding_source": row["funding_source"] or MAINTENANCE_FUNDING_SOURCE_OPTIONS[0],
        "paid_by": row["paid_by"] or MAINTENANCE_PAID_BY_OPTIONS[0],
        "tax_amount": f"{float(row['tax_amount'] or 0.0):.2f}",
        "notes": row["notes"] or "",
    }


def _fleet_vehicle_form_from_row(row):
    return {
        "original_vehicle_id": row["vehicle_id"],
        "vehicle_id": row["vehicle_id"],
        "vehicle_no": row["vehicle_no"] or "",
        "vehicle_type": row["vehicle_type"] or "",
        "make_model": row["make_model"] or "",
        "status": row["status"] or "Active",
        "shift_mode": row["shift_mode"] or FLEET_SHIFT_MODE_OPTIONS[0],
        "ownership_mode": row["ownership_mode"] or FLEET_OWNERSHIP_MODE_OPTIONS[0],
        "partner_party_code": row["partner_party_code"] or "",
        "partner_name": row["partner_name"] or "",
        "company_share_percent": f"{float(row['company_share_percent'] or 100.0):.2f}".rstrip("0").rstrip("."),
        "partner_share_percent": f"{float(row['partner_share_percent'] or 0.0):.2f}".rstrip("0").rstrip("."),
        "notes": row["notes"] or "",
    }


def _maintenance_paper_line_rows_for_form(db, paper_no: str):
    rows = db.execute(
        """
        SELECT line_no, description, quantity, rate, amount
        FROM maintenance_paper_lines
        WHERE paper_no = ?
        ORDER BY line_no ASC, id ASC
        """,
        (paper_no,),
    ).fetchall()
    slots = _default_maintenance_paper_lines()
    for index, row in enumerate(rows[:MAINTENANCE_LINE_SLOTS]):
        slots[index] = {
            "line_no": index + 1,
            "description": row["description"] or "",
            "quantity": f"{float(row['quantity'] or 0.0):.2f}".rstrip("0").rstrip("."),
            "rate": f"{float(row['rate'] or 0.0):.2f}".rstrip("0").rstrip("."),
            "amount": f"{float(row['amount'] or 0.0):.2f}".rstrip("0").rstrip("."),
        }
    return slots


def _fleet_vehicle_form_data(request):
    return {
        "original_vehicle_id": request.form.get("original_vehicle_id", "").strip().upper(),
        "vehicle_id": request.form.get("vehicle_id", "").strip().upper(),
        "vehicle_no": request.form.get("vehicle_no", "").strip().upper(),
        "vehicle_type": request.form.get("vehicle_type", "").strip(),
        "make_model": request.form.get("make_model", "").strip(),
        "status": request.form.get("status", "Active").strip() or "Active",
        "shift_mode": request.form.get("shift_mode", FLEET_SHIFT_MODE_OPTIONS[0]).strip() or FLEET_SHIFT_MODE_OPTIONS[0],
        "ownership_mode": request.form.get("ownership_mode", FLEET_OWNERSHIP_MODE_OPTIONS[0]).strip() or FLEET_OWNERSHIP_MODE_OPTIONS[0],
        "partner_party_code": request.form.get("partner_party_code", "").strip().upper(),
        "partner_name": request.form.get("partner_name", "").strip(),
        "company_share_percent": request.form.get("company_share_percent", "100").strip() or "100",
        "partner_share_percent": request.form.get("partner_share_percent", "0").strip() or "0",
        "notes": request.form.get("notes", "").strip(),
    }


def _maintenance_staff_form_data(request):
    return {
        "original_staff_code": request.form.get("original_staff_code", "").strip().upper(),
        "staff_code": request.form.get("staff_code", "").strip().upper(),
        "staff_name": request.form.get("staff_name", "").strip(),
        "phone_number": request.form.get("phone_number", "").strip(),
        "status": request.form.get("status", "Active").strip() or "Active",
        "notes": request.form.get("notes", "").strip(),
    }


def _maintenance_advance_form_data(request):
    funding_source = request.form.get("funding_source", MAINTENANCE_ADVANCE_SOURCE_OPTIONS[0]).strip() or MAINTENANCE_ADVANCE_SOURCE_OPTIONS[0]
    if funding_source not in MAINTENANCE_ADVANCE_SOURCE_OPTIONS:
        funding_source = MAINTENANCE_ADVANCE_SOURCE_OPTIONS[0]
    return {
        "original_advance_no": request.form.get("original_advance_no", "").strip().upper(),
        "advance_no": request.form.get("advance_no", "").strip().upper(),
        "staff_code": request.form.get("staff_code", "").strip().upper(),
        "entry_date": request.form.get("entry_date", "").strip(),
        "funding_source": funding_source,
        "amount": request.form.get("amount", "").strip(),
        "reference": request.form.get("reference", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }


def _maintenance_paper_form_data(request):
    tax_mode = request.form.get("tax_mode", MAINTENANCE_TAX_MODE_OPTIONS[0]).strip() or MAINTENANCE_TAX_MODE_OPTIONS[0]
    if tax_mode not in MAINTENANCE_TAX_MODE_OPTIONS:
        tax_mode = MAINTENANCE_TAX_MODE_OPTIONS[0]
    funding_source = request.form.get("funding_source", MAINTENANCE_FUNDING_SOURCE_OPTIONS[0]).strip() or MAINTENANCE_FUNDING_SOURCE_OPTIONS[0]
    if funding_source not in MAINTENANCE_FUNDING_SOURCE_OPTIONS:
        funding_source = MAINTENANCE_FUNDING_SOURCE_OPTIONS[0]
    paid_by = request.form.get("paid_by", MAINTENANCE_PAID_BY_OPTIONS[0]).strip() or MAINTENANCE_PAID_BY_OPTIONS[0]
    if paid_by not in MAINTENANCE_PAID_BY_OPTIONS:
        paid_by = MAINTENANCE_PAID_BY_OPTIONS[0]
    target_class = request.form.get("target_class", MAINTENANCE_TARGET_CLASS_OPTIONS[0]).strip() or MAINTENANCE_TARGET_CLASS_OPTIONS[0]
    if target_class not in MAINTENANCE_TARGET_CLASS_OPTIONS:
        target_class = MAINTENANCE_TARGET_CLASS_OPTIONS[0]
    return {
        "original_paper_no": request.form.get("original_paper_no", "").strip().upper(),
        "paper_no": request.form.get("paper_no", "").strip().upper(),
        "paper_date": request.form.get("paper_date", "").strip(),
        "target_class": target_class,
        "vehicle_id": request.form.get("vehicle_id", "").strip().upper(),
        "target_asset_code": request.form.get("target_asset_code", "").strip().upper(),
        "workshop_party_code": request.form.get("workshop_party_code", "").strip().upper(),
        "staff_code": request.form.get("staff_code", "").strip().upper(),
        "advance_no": request.form.get("advance_no", "").strip().upper(),
        "tax_mode": tax_mode,
        "supplier_bill_no": request.form.get("supplier_bill_no", "").strip(),
        "work_summary": request.form.get("work_summary", "").strip(),
        "funding_source": funding_source,
        "paid_by": paid_by,
        "tax_amount": request.form.get("tax_amount", "0").strip() or "0",
        "notes": request.form.get("notes", "").strip(),
    }


def _maintenance_paper_line_form_data(request):
    rows = []
    for index in range(1, MAINTENANCE_LINE_SLOTS + 1):
        rows.append(
            {
                "line_no": index,
                "description": request.form.get(f"line_description_{index}", "").strip(),
                "quantity": request.form.get(f"line_quantity_{index}", "").strip(),
                "rate": request.form.get(f"line_rate_{index}", "").strip(),
                "amount": request.form.get(f"line_amount_{index}", "").strip(),
            }
        )
    return rows


def _prepare_fleet_vehicle_payload(db, values):
    if not values["vehicle_id"]:
        values["vehicle_id"] = _next_reference_code(db, "vehicle_master", "vehicle_id", "VEH")
    if not values["vehicle_no"]:
        raise ValidationError("Vehicle number is required.")
    if not values["vehicle_type"]:
        raise ValidationError("Vehicle type is required.")
    shift_mode = values["shift_mode"] if values["shift_mode"] in FLEET_SHIFT_MODE_OPTIONS else FLEET_SHIFT_MODE_OPTIONS[0]
    ownership_mode = values["ownership_mode"] if values["ownership_mode"] in FLEET_OWNERSHIP_MODE_OPTIONS else FLEET_OWNERSHIP_MODE_OPTIONS[0]
    partner_party_code = values["partner_party_code"]
    partner_name = values["partner_name"]
    if partner_party_code:
        partner_party = _validate_party_reference(db, partner_party_code)
        partner_name = partner_party["party_name"]
    company_share_percent = _parse_decimal(values["company_share_percent"], "Company share percent", required=True, minimum=0.0, maximum=100.0)
    partner_share_percent = _parse_decimal(values["partner_share_percent"], "Partner share percent", required=True, minimum=0.0, maximum=100.0)
    if ownership_mode == "Partnership":
        if not (partner_party_code or partner_name):
            raise ValidationError("Select or enter a partner for partnership vehicle.")
        if abs((company_share_percent + partner_share_percent) - 100.0) > 0.01:
            raise ValidationError("Company and partner share must total 100.")
    else:
        partner_party_code = None
        partner_name = ""
        company_share_percent = 100.0
        partner_share_percent = 0.0
    return (
        values["vehicle_id"],
        values["vehicle_no"],
        values["vehicle_type"],
        values["make_model"] or None,
        values["status"],
        shift_mode,
        ownership_mode,
        "Own Fleet Vehicle",
        None,
        None,
        partner_party_code,
        partner_name or None,
        company_share_percent,
        partner_share_percent,
        values["notes"] or None,
    )


def _prepare_maintenance_staff_payload(db, values):
    if not values["staff_code"]:
        values["staff_code"] = _next_reference_code(db, "maintenance_staff", "staff_code", "TEC")
    if not values["staff_name"]:
        raise ValidationError("Technician name is required.")
    return (
        values["staff_code"],
        values["staff_name"],
        _normalize_optional_phone(values["phone_number"]) or None,
        values["status"],
        values["notes"] or None,
    )


def _prepare_maintenance_advance_payload(db, values):
    if not values["advance_no"]:
        values["advance_no"] = _next_reference_code(db, "maintenance_staff_advances", "advance_no", "ADV")
    _maintenance_staff_row(db, values["staff_code"], required=True)
    entry_date = _validate_date_text(values["entry_date"], "Advance date")
    amount = _parse_decimal(values["amount"], "Advance amount", required=True, minimum=0.01)
    settled_amount = 0.0
    if values["original_advance_no"]:
        existing = _maintenance_advance_row(db, values["original_advance_no"], required=True)
        settled_amount = float(existing["settled_amount"] or 0.0)
        if settled_amount - amount > 0.001:
            raise ValidationError("Advance amount cannot be lower than already settled amount.")
    balance_amount = round(amount - settled_amount, 2)
    return (
        values["advance_no"],
        values["staff_code"],
        entry_date,
        values["funding_source"],
        amount,
        settled_amount,
        max(balance_amount, 0.0),
        values["reference"] or None,
        values["notes"] or None,
    )


def _prepare_maintenance_line_payloads(line_rows):
    prepared = []
    for row in line_rows:
        if not any([(row.get("description") or "").strip(), (row.get("quantity") or "").strip(), (row.get("rate") or "").strip()]):
            continue
        description = (row.get("description") or "").strip()
        if not description:
            raise ValidationError(f"Maintenance line {row['line_no']} description is required.")
        quantity = _parse_decimal(row.get("quantity") or "1", f"Maintenance line {row['line_no']} quantity", required=True, minimum=0.01)
        rate = _parse_decimal(row.get("rate") or "0", f"Maintenance line {row['line_no']} rate", required=True, minimum=0.0)
        amount = round(quantity * rate, 2)
        prepared.append(
            {
                "line_no": len(prepared) + 1,
                "description": description,
                "quantity": quantity,
                "rate": rate,
                "amount": amount,
            }
        )
    if not prepared:
        raise ValidationError("Add at least one maintenance work line.")
    return prepared


def _prepare_maintenance_paper_payload(db, values, line_rows):
    if not values["paper_no"]:
        values["paper_no"] = _next_reference_code(db, "maintenance_papers", "paper_no", "MTP")
    paper_date = _validate_date_text(values["paper_date"], "Paper date")
    target_class = values["target_class"] if values["target_class"] in MAINTENANCE_TARGET_CLASS_OPTIONS else MAINTENANCE_TARGET_CLASS_OPTIONS[0]
    target_party_code = None
    target_asset_code = None
    if target_class == "Partnership Supplier Vehicle":
        supplier_asset = _partnership_supplier_asset_row(db, values["target_asset_code"], required=True)
        vehicle = _ensure_supplier_vehicle_shadow(db, supplier_asset)
        target_party_code = supplier_asset["party_code"]
        target_asset_code = supplier_asset["asset_code"]
    else:
        vehicle = _fleet_vehicle_row(db, values["vehicle_id"], required=True)
    workshop_party_code = values["workshop_party_code"] or ""
    if workshop_party_code:
        _validate_party_reference(db, workshop_party_code)
    staff_code = values["staff_code"] or ""
    if staff_code:
        _maintenance_staff_row(db, staff_code, required=True)

    advance_row = None
    if values["advance_no"]:
        advance_row = _maintenance_advance_row(db, values["advance_no"], required=True)
        if staff_code and advance_row["staff_code"] != staff_code:
            raise ValidationError("Selected advance does not belong to the chosen technician.")
        staff_code = advance_row["staff_code"]

    if values["funding_source"] == "Technician Advance":
        if not staff_code:
            raise ValidationError("Select field staff for field staff advance settlement.")
        if advance_row is None:
            raise ValidationError("Select the field staff advance that will settle this paper.")
    if values["funding_source"] == "Workshop Credit" and not workshop_party_code:
        raise ValidationError("Select workshop / auto shop for workshop credit paper.")

    prepared_lines = _prepare_maintenance_line_payloads(line_rows)
    subtotal = round(sum(float(item["amount"]) for item in prepared_lines), 2)
    tax_amount = 0.0
    if values["tax_mode"] == "Tax Invoice":
        tax_amount = _parse_decimal(values["tax_amount"], "VAT amount", required=True, minimum=0.0)
    total_amount = round(subtotal + tax_amount, 2)

    if values["work_summary"]:
        work_summary = values["work_summary"]
    else:
        work_summary = "; ".join(item["description"] for item in prepared_lines[:2])

    if (vehicle["ownership_mode"] or FLEET_OWNERSHIP_MODE_OPTIONS[0]) == "Partnership":
        company_share_percent = float(vehicle["company_share_percent"] or 0.0)
        partner_share_percent = float(vehicle["partner_share_percent"] or 0.0)
        company_share_amount = round(total_amount * (company_share_percent / 100.0), 2)
        partner_share_amount = round(total_amount * (partner_share_percent / 100.0), 2)
    else:
        company_share_amount = total_amount
        partner_share_amount = 0.0

    if values["funding_source"] == "Workshop Credit":
        company_paid_amount = 0.0
        partner_paid_amount = 0.0
    elif values["paid_by"] == "Partner":
        company_paid_amount = 0.0
        partner_paid_amount = total_amount
    else:
        company_paid_amount = total_amount
        partner_paid_amount = 0.0

    settlement_payload = None
    advance_update = None
    if values["funding_source"] == "Technician Advance":
        available_amount = float(advance_row["balance_amount"] or 0.0)
        if total_amount - available_amount > 0.001:
            raise ValidationError(f"Paper total cannot exceed selected advance balance {available_amount:,.2f}.")
        settlement_payload = (
            _next_reference_code(db, "maintenance_settlements", "settlement_no", "MTS"),
            values["paper_no"],
            "Technician Advance",
            advance_row["advance_no"],
            None,
            total_amount,
            "Settled",
            values["notes"] or work_summary,
        )
        advance_update = {
            "advance_no": advance_row["advance_no"],
            "settled_amount": round(float(advance_row["settled_amount"] or 0.0) + total_amount, 2),
            "balance_amount": round(float(advance_row["balance_amount"] or 0.0) - total_amount, 2),
        }
    elif values["funding_source"] == "Workshop Credit":
        settlement_payload = (
            _next_reference_code(db, "maintenance_settlements", "settlement_no", "MTS"),
            values["paper_no"],
            "Workshop Credit",
            None,
            workshop_party_code,
            total_amount,
            "Open",
            values["notes"] or work_summary,
        )
    else:
        settlement_payload = (
            _next_reference_code(db, "maintenance_settlements", "settlement_no", "MTS"),
            values["paper_no"],
            "Direct",
            None,
            workshop_party_code or None,
            total_amount,
            "Settled",
            values["notes"] or work_summary,
        )

    return {
        "paper_no": values["paper_no"],
        "paper_date": paper_date,
        "target_class": target_class,
        "target_party_code": target_party_code,
        "target_asset_code": target_asset_code,
        "vehicle_id": vehicle["vehicle_id"],
        "vehicle_no": vehicle["vehicle_no"],
        "workshop_party_code": workshop_party_code or None,
        "staff_code": staff_code or None,
        "advance_no": advance_row["advance_no"] if advance_row else None,
        "tax_mode": values["tax_mode"],
        "supplier_bill_no": values["supplier_bill_no"] or None,
        "work_summary": work_summary,
        "funding_source": values["funding_source"],
        "paid_by": values["paid_by"],
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "company_share_amount": company_share_amount,
        "partner_share_amount": partner_share_amount,
        "company_paid_amount": company_paid_amount,
        "partner_paid_amount": partner_paid_amount,
        "notes": values["notes"] or None,
        "line_payloads": prepared_lines,
        "settlement_payload": settlement_payload,
        "advance_update": advance_update,
        "view_month": paper_date[:7],
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
        "quotation_no": request.form.get("quotation_no", "").strip().upper(),
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
            "quotation_no": row["quotation_no"] or "",
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


def _supplier_mode_workspace_key(supplier_mode: str) -> str:
    mode = supplier_mode or "Normal"
    if mode == "Partnership":
        return "suppliers-partnership"
    if mode == "Managed":
        return "suppliers-managed"
    if mode == "Cash":
        return "suppliers-cash"
    return "suppliers-normal"


def _supplier_desk_endpoint(supplier_mode: str) -> str:
    mode = supplier_mode or "Normal"
    if mode == "Partnership":
        return "partnership_suppliers"
    if mode == "Managed":
        return "managed_suppliers"
    if mode == "Cash":
        return "cash_suppliers"
    return "suppliers"


def _supplier_cards_endpoint(supplier_mode: str) -> str:
    mode = supplier_mode or "Normal"
    if mode == "Partnership":
        return "partnership_supplier_cards"
    if mode == "Managed":
        return "managed_supplier_cards"
    if mode == "Cash":
        return "cash_supplier_cards"
    return "suppliers"


def _supplier_register_endpoint(supplier_mode: str) -> str:
    mode = supplier_mode or "Normal"
    if mode == "Partnership":
        return "partnership_suppliers"
    if mode == "Managed":
        return "managed_suppliers"
    if mode == "Cash":
        return "cash_suppliers"
    return "admin_supplier_register"


def _supplier_detail_endpoint(supplier_mode: str) -> str:
    return "supplier_detail"


def _supplier_screen_options(supplier_mode: str):
    if supplier_mode in ("Cash", "Loan"):
        return [
            {"key": "portal", "label": "Portal"},
            {"key": "kata", "label": "Kata / Statement"},
        ]

    if supplier_mode == "Normal":
        options = [
            {"key": "portal", "label": "Portal"},
            {"key": "statement", "label": "SOA"},
        ]
        return options

    if supplier_mode == "Managed":
        options = [
            {"key": "portal", "label": "Portal"},
            {"key": "statement", "label": "SOA"},
        ]
        return options

    if supplier_mode == "Partnership":
        options = [
            {"key": "portal", "label": "Portal"},
            {"key": "vehicles", "label": "Vehicles"},
            {"key": "timesheets", "label": "Timesheets"},
            {"key": "billing", "label": "Expenses & Salary Split"},
            {"key": "statement", "label": "SOA"},
            {"key": "partnership", "label": "Profit Result"},
        ]
        return options

    options = [
        {"key": "portal", "label": "Portal"},
        {"key": "vehicles", "label": "Vehicles"},
        {"key": "timesheets", "label": "Timesheets"},
        {"key": "billing", "label": "Invoice Intake & Payment"},
        {"key": "statement", "label": "SOA"},
    ]
    return options


def _default_supplier_screen(supplier_mode: str) -> str:
    return "portal"


def _normalize_supplier_screen(screen: str, supplier_mode: str) -> str:
    requested = (screen or "").strip().lower()
    valid = {item["key"] for item in _supplier_screen_options(supplier_mode)}
    return requested if requested in valid else _default_supplier_screen(supplier_mode)


def _supplier_partner_parties(db):
    return db.execute(
        """
        SELECT party_code, party_name
        FROM parties
        WHERE party_roles LIKE ?
        ORDER BY party_name ASC
        """,
        ("%Partner%",),
    ).fetchall()


def _supplier_profile_row(db, party_code: str):
    return db.execute(
        """
        SELECT
            party_code,
            supplier_mode,
            partner_party_code,
            partner_name,
            default_company_share_percent,
            default_partner_share_percent
        FROM supplier_profile
        WHERE party_code = ?
        """,
        (party_code,),
    ).fetchone()


def _supplier_mode_for_party(db, party_code: str) -> str:
    profile = _supplier_profile_row(db, party_code)
    if profile is not None and (profile["supplier_mode"] or "") in SUPPLIER_MODE_OPTIONS:
        return profile["supplier_mode"]
    return "Normal"


def _default_supplier_form(supplier_mode: str = "Normal"):
    values = _default_party_form()
    values["original_party_code"] = ""
    values["party_roles"] = ["Supplier"]
    values["supplier_mode"] = supplier_mode if supplier_mode in SUPPLIER_MODE_OPTIONS else SUPPLIER_MODE_OPTIONS[0]
    values["partner_party_code"] = ""
    values["partner_name"] = ""
    values["default_company_share_percent"] = "50" if values["supplier_mode"] == "Partnership" else "100"
    values["default_partner_share_percent"] = "50" if values["supplier_mode"] == "Partnership" else "0"
    values["portal_enabled"] = False
    values["portal_login_email"] = ""
    values["portal_activation_status"] = "Invited"
    values["portal_last_login_at"] = ""
    return values


def _supplier_form_data(request, supplier_mode: str = "Normal"):
    form_mode = request.form.get("supplier_mode", "").strip().title() or supplier_mode
    if form_mode not in SUPPLIER_MODE_OPTIONS:
        form_mode = supplier_mode if supplier_mode in SUPPLIER_MODE_OPTIONS else SUPPLIER_MODE_OPTIONS[0]
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
        "supplier_mode": form_mode,
        "partner_party_code": request.form.get("partner_party_code", "").strip().upper(),
        "partner_name": request.form.get("partner_name", "").strip(),
        "default_company_share_percent": request.form.get("default_company_share_percent", "100").strip() or "100",
        "default_partner_share_percent": request.form.get("default_partner_share_percent", "0").strip() or "0",
        "portal_enabled": request.form.get("portal_enabled", "").strip() in {"1", "true", "on", "yes"},
        "portal_login_email": request.form.get("portal_login_email", "").strip(),
        "portal_activation_status": request.form.get("portal_activation_status", "").strip() or "Invited",
        "portal_last_login_at": request.form.get("portal_last_login_at", "").strip(),
    }


def _supplier_cards_context(db, supplier_mode: str, query: str = "") -> dict:
    normalized_mode = supplier_mode if supplier_mode in SUPPLIER_MODE_OPTIONS else "Normal"
    return {
        "query": query,
        "suppliers": _supplier_directory_rows(db, query=query, supplier_mode=normalized_mode),
        "summary": _supplier_hub_summary(db, normalized_mode),
        "supplier_mode": normalized_mode,
        "detail_endpoint": "supplier_detail",
        "desk_endpoint": _supplier_desk_endpoint(normalized_mode),
        "cards_endpoint": _supplier_cards_endpoint(normalized_mode),
        "register_endpoint": _supplier_register_endpoint(normalized_mode),
        "statement_endpoint": "supplier_statement",
        "delete_endpoint": "delete_supplier",
    }


def _supplier_portal_snapshot(
    db,
    party,
    supplier_mode: str,
    detail_summary: dict,
    *,
    partnership_summary: dict | None = None,
    partnership_month: str = "",
    portal_account=None,
) -> dict:
    party_code = party["party_code"]
    normalized_mode = supplier_mode or "Normal"

    def money(amount: float) -> str:
        return f"AED {float(amount or 0.0):,.2f}"

    def supplier_screen_href(screen: str = "portal", anchor: str = "") -> str:
        href = url_for("supplier_detail", party_code=party_code, screen=screen)
        return f"{href}#{anchor}" if anchor else href

    company_details = [
        {"label": "Supplier Code", "value": party["party_code"]},
        {
            "label": "Type",
            "value": f"{normalized_mode} / {party['party_kind']}",
        },
        {"label": "Status", "value": party["status"] or "-"},
        {"label": "Contact", "value": party["contact_person"] or "-"},
        {"label": "Phone", "value": party["phone_number"] or "-"},
        {"label": "Email", "value": party["email"] or "-"},
        {"label": "Address", "value": party["address"] or "-"},
    ]
    if normalized_mode == "Partnership":
        profile = _supplier_profile_row(db, party_code)
        if profile is not None:
            company_details.append({"label": "Partner", "value": profile["partner_name"] or "-"})
            company_details.append(
                {
                    "label": "Split",
                    "value": f"{float(profile['default_company_share_percent'] or 0):.0f}% / {float(profile['default_partner_share_percent'] or 0):.0f}%",
                }
            )
    if normalized_mode == "Normal" and portal_account is not None:
        company_details.append(
            {
                "label": "Portal Access",
                "value": "Enabled" if portal_account["portal_enabled"] else "Disabled",
            }
        )

    if normalized_mode in ("Cash", "Loan"):
        trip_count = int(db.execute("SELECT COUNT(*) FROM cash_supplier_trips WHERE party_code = ?", (party_code,)).fetchone()[0] or 0)
        debit_count = int(db.execute("SELECT COUNT(*) FROM cash_supplier_debits WHERE party_code = ?", (party_code,)).fetchone()[0] or 0)
        payment_count = int(db.execute("SELECT COUNT(*) FROM cash_supplier_payments WHERE party_code = ?", (party_code,)).fetchone()[0] or 0)
        total_earned = float(db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM cash_supplier_trips WHERE party_code = ?", (party_code,)).fetchone()[0] or 0.0)
        total_debits = float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM cash_supplier_debits WHERE party_code = ?", (party_code,)).fetchone()[0] or 0.0)
        total_paid = float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM cash_supplier_payments WHERE party_code = ?", (party_code,)).fetchone()[0] or 0.0)
        balance_label, balance_tone, balance_amount = _cash_supplier_balance_meta(total_earned - total_debits - total_paid)
        trip_rows = db.execute(
            """
            SELECT trip_no, entry_date, total_amount, vehicle_no
            FROM cash_supplier_trips
            WHERE party_code = ?
            ORDER BY entry_date DESC, id DESC
            LIMIT 4
            """,
            (party_code,),
        ).fetchall()
        debit_rows = db.execute(
            """
            SELECT debit_no, entry_date, amount, debit_type
            FROM cash_supplier_debits
            WHERE party_code = ?
            ORDER BY entry_date DESC, id DESC
            LIMIT 4
            """,
            (party_code,),
        ).fetchall()
        payment_rows = db.execute(
            """
            SELECT payment_no, entry_date, amount, payment_method
            FROM cash_supplier_payments
            WHERE party_code = ?
            ORDER BY entry_date DESC, id DESC
            LIMIT 4
            """,
            (party_code,),
        ).fetchall()
        return {
            "intro_label": "Supplier Portal",
            "intro_title": "Cash Supplier Portal",
            "intro_copy": "Open the supplier's own operating view for kata, trip earnings, debit entries and payments.",
            "modules": [
                {
                    "eyebrow": "Running Position",
                    "title": "Kata / Statement",
                    "value": money(balance_amount),
                    "caption": balance_label,
                    "href": supplier_screen_href("kata"),
                    "tone": balance_tone,
                },
                {
                    "eyebrow": "Trip Earnings",
                    "title": "Trips",
                    "value": str(trip_count),
                    "caption": f"Work logged {money(total_earned)}",
                    "href": supplier_screen_href("kata", "recent-trips"),
                    "tone": "cash",
                },
                {
                    "eyebrow": "Deductions",
                    "title": "Debit Entries",
                    "value": str(debit_count),
                    "caption": f"Debits total {money(total_debits)}",
                    "href": supplier_screen_href("kata", "recent-debits"),
                    "tone": "warning",
                },
                {
                    "eyebrow": "Settlements",
                    "title": "Payments",
                    "value": str(payment_count),
                    "caption": f"Paid out {money(total_paid)}",
                    "href": supplier_screen_href("kata", "recent-payments"),
                    "tone": "success",
                },
                {
                    "eyebrow": "Fleet",
                    "title": "Vehicles",
                    "value": str(detail_summary.get("asset_count", 0)),
                    "caption": "Assigned cash units",
                    "href": supplier_screen_href("portal"),
                    "tone": "info",
                },
                {
                    "eyebrow": "Master",
                    "title": "Company Details",
                    "value": party["party_kind"] or "Supplier",
                    "caption": party["contact_person"] or party["phone_number"] or "Supplier master card",
                    "href": supplier_screen_href("portal", "company-details"),
                    "tone": "neutral",
                },
            ],
            "recent_groups": [
                {
                    "anchor": "recent-trips",
                    "eyebrow": "Trips",
                    "title": "Recent Earnings",
                    "empty_copy": "No trip earnings have been recorded yet.",
                    "rows": [
                        {
                            "headline": row["trip_no"],
                            "subline": row["entry_date"],
                            "meta": f"{money(row['total_amount'])} / {row['vehicle_no'] or 'No vehicle'}",
                            "status": "Earning",
                        }
                        for row in trip_rows
                    ],
                },
                {
                    "anchor": "recent-debits",
                    "eyebrow": "Debits",
                    "title": "Recent Deductions",
                    "empty_copy": "No debit entries have been recorded yet.",
                    "rows": [
                        {
                            "headline": row["debit_no"],
                            "subline": row["entry_date"],
                            "meta": f"{money(row['amount'])} / {row['debit_type'] or 'Debit'}",
                            "status": row["debit_type"] or "Debit",
                        }
                        for row in debit_rows
                    ],
                },
                {
                    "anchor": "recent-payments",
                    "eyebrow": "Payments",
                    "title": "Recent Payments",
                    "empty_copy": "No supplier payments have been recorded yet.",
                    "rows": [
                        {
                            "headline": row["payment_no"],
                            "subline": row["entry_date"],
                            "meta": f"{money(row['amount'])} / {row['payment_method'] or 'Payment'}",
                            "status": row["payment_method"] or "Payment",
                        }
                        for row in payment_rows
                    ],
                },
            ],
            "company_details": company_details,
        }

    quotation_count = int(db.execute("SELECT COUNT(*) FROM supplier_quotation_submissions WHERE party_code = ?", (party_code,)).fetchone()[0] or 0)
    lpo_count = int(db.execute("SELECT COUNT(*) FROM lpos WHERE party_code = ?", (party_code,)).fetchone()[0] or 0)
    voucher_count = int(db.execute("SELECT COUNT(*) FROM supplier_vouchers WHERE party_code = ?", (party_code,)).fetchone()[0] or 0)

    quotation_rows = db.execute(
        """
        SELECT quotation_no, quotation_date, amount, review_status
        FROM supplier_quotation_submissions
        WHERE party_code = ?
        ORDER BY quotation_date DESC, id DESC
        LIMIT 4
        """,
        (party_code,),
    ).fetchall()
    lpo_rows = db.execute(
        """
        SELECT lpo_no, issue_date, amount, status
        FROM lpos
        WHERE party_code = ?
        ORDER BY issue_date DESC, id DESC
        LIMIT 4
        """,
        (party_code,),
    ).fetchall()
    voucher_rows = db.execute(
        """
        SELECT voucher_no, issue_date, total_amount, balance_amount, status
        FROM supplier_vouchers
        WHERE party_code = ?
        ORDER BY issue_date DESC, id DESC
        LIMIT 4
        """,
        (party_code,),
    ).fetchall()

    if normalized_mode == "Managed":
        invoice_count = int(db.execute("SELECT COUNT(*) FROM account_invoices WHERE party_code = ?", (party_code,)).fetchone()[0] or 0)
        invoice_rows = db.execute(
            """
            SELECT invoice_no, issue_date, total_amount, balance_amount, status
            FROM account_invoices
            WHERE party_code = ?
            ORDER BY issue_date DESC, id DESC
            LIMIT 4
            """,
            (party_code,),
        ).fetchall()
        invoice_title = "Invoices"
        invoice_caption = "Booked managed invoices"
        invoice_anchor = "recent-invoices"
        invoice_tone = "managed"
        invoice_module_label = "Invoices"
        invoice_recent_rows = [
            {
                "headline": row["invoice_no"],
                "subline": row["issue_date"],
                "meta": f"{money(row['total_amount'])} / Due {money(row['balance_amount'])}",
                "status": row["status"] or "Open",
            }
            for row in invoice_rows
        ]
    else:
        invoice_count = int(db.execute("SELECT COUNT(*) FROM supplier_invoice_submissions WHERE party_code = ?", (party_code,)).fetchone()[0] or 0)
        invoice_rows = db.execute(
            """
            SELECT submission_no, external_invoice_no, invoice_date, total_amount, review_status
            FROM supplier_invoice_submissions
            WHERE party_code = ?
            ORDER BY invoice_date DESC, created_at DESC, id DESC
            LIMIT 4
            """,
            (party_code,),
        ).fetchall()
        invoice_title = "Invoice Submissions"
        invoice_caption = "Submitted supplier invoices"
        invoice_anchor = "recent-invoices"
        invoice_tone = "normal"
        invoice_module_label = "Invoice Submissions"
        invoice_recent_rows = [
            {
                "headline": row["external_invoice_no"] or row["submission_no"],
                "subline": row["invoice_date"],
                "meta": f"{money(row['total_amount'])} / {row['submission_no']}",
                "status": row["review_status"] or "Pending",
            }
            for row in invoice_rows
        ]

    modules = [
        {
            "eyebrow": "Commercial",
            "title": "Quotations",
            "value": str(quotation_count),
            "caption": "Supplier quotations on record",
            "href": supplier_screen_href("portal", "recent-quotations"),
            "tone": "info",
        },
        {
            "eyebrow": "Purchase Orders",
            "title": "LPOs",
            "value": str(lpo_count),
            "caption": "Linked LPO documents",
            "href": supplier_screen_href("portal", "recent-lpos"),
            "tone": "normal",
        },
        {
            "eyebrow": "Invoices",
            "title": invoice_module_label,
            "value": str(invoice_count),
            "caption": invoice_caption,
            "href": supplier_screen_href("portal", invoice_anchor),
            "tone": invoice_tone,
        },
        {
            "eyebrow": "Settlement",
            "title": "Payment Vouchers",
            "value": str(voucher_count),
            "caption": f"{detail_summary.get('open_voucher_count', 0)} open vouchers",
            "href": supplier_screen_href("portal", "recent-vouchers"),
            "tone": "success",
        },
        {
            "eyebrow": "SOA",
            "title": "Statement of Account",
            "value": money(detail_summary.get("outstanding_total", 0.0)),
            "caption": f"Paid {money(detail_summary.get('paid_total', 0.0))}",
            "href": supplier_screen_href("statement"),
            "tone": "warning",
        },
        {
            "eyebrow": "Master",
            "title": "Company Details",
            "value": party["party_kind"] or "Supplier",
            "caption": party["contact_person"] or party["phone_number"] or "Supplier master profile",
            "href": supplier_screen_href("portal", "company-details"),
            "tone": "neutral",
        },
    ]
    if normalized_mode == "Partnership":
        modules.insert(
            4,
            {
                "eyebrow": "Profit Result",
                "title": "Partnership Split",
                "value": money((partnership_summary or {}).get("net_profit", 0.0)),
                "caption": format_month_label(partnership_month or _current_month_value()),
                "href": supplier_screen_href("partnership"),
                "tone": "partnership",
            },
        )

    return {
        "intro_label": "Supplier Portal",
        "intro_title": (
            "Managed Supplier Portal"
            if normalized_mode == "Managed"
            else "Partnership Supplier Portal"
            if normalized_mode == "Partnership"
            else "Online Supplier Portal"
        ),
        "intro_copy": (
            "Open a clean supplier landing view for quotations, LPOs, invoices, vouchers and company details."
            if normalized_mode != "Partnership"
            else "Open the supplier landing view for quotations, LPOs, invoices, vouchers, profit result and company details."
        ),
        "modules": modules,
        "recent_groups": [
            {
                "anchor": "recent-quotations",
                "eyebrow": "Quotations",
                "title": "Recent Quotations",
                "empty_copy": "No quotations have been recorded yet.",
                "rows": [
                    {
                        "headline": row["quotation_no"],
                        "subline": row["quotation_date"],
                        "meta": money(row["amount"]),
                        "status": row["review_status"] or "Pending",
                    }
                    for row in quotation_rows
                ],
            },
            {
                "anchor": "recent-lpos",
                "eyebrow": "LPOs",
                "title": "Recent Purchase Orders",
                "empty_copy": "No LPOs have been issued yet.",
                "rows": [
                    {
                        "headline": row["lpo_no"],
                        "subline": row["issue_date"],
                        "meta": money(row["amount"]),
                        "status": row["status"] or "Issued",
                    }
                    for row in lpo_rows
                ],
            },
            {
                "anchor": "recent-invoices",
                "eyebrow": "Invoices",
                "title": invoice_title,
                "empty_copy": "No invoice activity has been recorded yet.",
                "rows": invoice_recent_rows,
            },
            {
                "anchor": "recent-vouchers",
                "eyebrow": "Vouchers",
                "title": "Recent Payment Vouchers",
                "empty_copy": "No payment vouchers have been generated yet.",
                "rows": [
                    {
                        "headline": row["voucher_no"],
                        "subline": row["issue_date"],
                        "meta": f"{money(row['total_amount'])} / Due {money(row['balance_amount'])}",
                        "status": row["status"] or "Open",
                    }
                    for row in voucher_rows
                ],
            },
        ],
        "company_details": company_details,
    }


def _supplier_form_from_party(record, profile=None, portal_account=None):
    values = _party_values_from_record(record)
    profile = dict(profile) if profile else {}
    portal_account = dict(portal_account) if portal_account else {}
    supplier_mode = profile.get("supplier_mode") or "Normal"
    if supplier_mode not in SUPPLIER_MODE_OPTIONS:
        supplier_mode = "Normal"
    values["original_party_code"] = record["party_code"]
    values["supplier_mode"] = supplier_mode
    values["partner_party_code"] = profile.get("partner_party_code") or ""
    values["partner_name"] = profile.get("partner_name") or ""
    values["default_company_share_percent"] = _display_number(profile.get("default_company_share_percent", 100 if supplier_mode == "Normal" else 50))
    values["default_partner_share_percent"] = _display_number(profile.get("default_partner_share_percent", 0 if supplier_mode == "Normal" else 50))
    values["portal_enabled"] = bool(portal_account.get("portal_enabled"))
    values["portal_login_email"] = portal_account.get("login_email") or values.get("email", "")
    values["portal_activation_status"] = portal_account.get("activation_status") or "Invited"
    values["portal_last_login_at"] = portal_account.get("last_login_at") or ""
    return values


def _save_admin_supplier_record(db, values) -> str:
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
        _upsert_supplier_profile(db, payload[0], values)
        _upsert_supplier_portal_account(db, payload[0], values)
        _audit_log(
            db,
            "supplier_updated",
            entity_type="supplier",
            entity_id=payload[0],
            details=f"{payload[1]} / {values['supplier_mode']}",
        )
        return "Supplier updated successfully."

    db.execute(
        """
        INSERT INTO parties (
            party_code, party_name, party_kind, party_roles, contact_person,
            phone_number, email, trn_no, trade_license_no, address, notes, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    _upsert_supplier_profile(db, payload[0], values)
    _upsert_supplier_portal_account(db, payload[0], values)
    _audit_log(
        db,
        "supplier_created",
        entity_type="supplier",
        entity_id=payload[0],
        details=f"{payload[1]} / {values['supplier_mode']}",
    )
    return "Supplier registered successfully."


def _delete_supplier_generated_files(app: Flask, party_code: str) -> None:
    generated_root = Path(app.config["GENERATED_DIR"]) / "suppliers" / party_code
    if generated_root.exists():
        shutil.rmtree(generated_root, ignore_errors=True)


def _delete_supplier_cascade(db, party_code: str) -> tuple[str, str]:
    party = _fetch_supplier_party(db, party_code)
    if party is None:
        raise ValidationError("Supplier was not found.")

    supplier_mode = _supplier_mode_for_party(db, party_code)
    party_name = party["party_name"]

    db.execute(
        "UPDATE supplier_profile SET partner_party_code = NULL WHERE partner_party_code = ?",
        (party_code,),
    )
    db.execute(
        "UPDATE maintenance_papers SET workshop_party_code = NULL WHERE workshop_party_code = ?",
        (party_code,),
    )
    db.execute(
        "UPDATE maintenance_settlements SET party_code = NULL WHERE party_code = ?",
        (party_code,),
    )
    db.execute(
        "DELETE FROM account_invoice_lines WHERE invoice_no IN (SELECT invoice_no FROM account_invoices WHERE party_code = ?)",
        (party_code,),
    )
    db.execute("DELETE FROM account_payments WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM account_invoices WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM hire_records WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM lpos WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM agreements WHERE party_code = ?", (party_code,))

    db.execute("DELETE FROM supplier_invoice_submissions WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM supplier_payments WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM supplier_vouchers WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM supplier_timesheets WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM supplier_partnership_entries WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM supplier_assets WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM supplier_quotation_submissions WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM cash_supplier_payments WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM cash_supplier_debits WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM cash_supplier_trips WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM loan_entries WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM annual_fee_entries WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM supplier_registration_requests WHERE approved_party_code = ?", (party_code,))
    db.execute("DELETE FROM supplier_portal_accounts WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM supplier_profile WHERE party_code = ?", (party_code,))
    db.execute("DELETE FROM parties WHERE party_code = ?", (party_code,))

    _audit_log(
        db,
        "supplier_deleted",
        entity_type="supplier",
        entity_id=party_code,
        details=f"{party_name} / {supplier_mode}",
    )
    return party_name, supplier_mode


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


def _prepare_supplier_profile_payload(db, values):
    supplier_mode = values.get("supplier_mode") or "Normal"
    if supplier_mode not in SUPPLIER_MODE_OPTIONS:
        supplier_mode = "Normal"
    partner_party_code = values.get("partner_party_code", "")
    partner_name = values.get("partner_name", "")
    if partner_party_code:
        partner_row = _validate_party_reference(db, partner_party_code)
        partner_name = partner_row["party_name"]
    if supplier_mode == "Partnership":
        company_share = _parse_decimal(values.get("default_company_share_percent", "50"), "Company share percent", required=True, minimum=0.0, maximum=100.0)
        partner_share = _parse_decimal(values.get("default_partner_share_percent", "50"), "Partner share percent", required=True, minimum=0.0, maximum=100.0)
        if abs((company_share + partner_share) - 100.0) > 0.01:
            raise ValidationError("Company and partner share must total 100.")
        if not (partner_party_code or partner_name):
            raise ValidationError("Partnership supplier needs partner details.")
    else:
        partner_party_code = ""
        partner_name = ""
        company_share = 100.0
        partner_share = 0.0
    return (
        supplier_mode,
        partner_party_code or None,
        partner_name or None,
        company_share,
        partner_share,
    )


def _upsert_supplier_profile(db, party_code: str, values) -> None:
    profile_payload = _prepare_supplier_profile_payload(db, values)
    existing = _supplier_profile_row(db, party_code)
    if existing is None:
        db.execute(
            """
            INSERT INTO supplier_profile (
                party_code, supplier_mode, partner_party_code, partner_name,
                default_company_share_percent, default_partner_share_percent
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (party_code,) + profile_payload,
        )
    else:
        db.execute(
            """
            UPDATE supplier_profile
            SET supplier_mode = ?, partner_party_code = ?, partner_name = ?,
                default_company_share_percent = ?, default_partner_share_percent = ?
            WHERE party_code = ?
            """,
            profile_payload + (party_code,),
        )


def _supplier_portal_is_eligible(supplier_mode: str, party_kind: str) -> bool:
    return (supplier_mode or "Normal") == "Normal" and (party_kind or "Company") == "Company"


def _supplier_portal_account_row(db, party_code: str):
    return db.execute(
        """
        SELECT
            party_code,
            user_id,
            login_email,
            password_hash,
            portal_enabled,
            activation_status,
            last_login_at
        FROM supplier_portal_accounts
        WHERE party_code = ?
        """,
        (party_code,),
    ).fetchone()


def _supplier_portal_account_by_user_id(db, user_id: str):
    return db.execute(
        """
        SELECT
            party_code,
            user_id,
            login_email,
            password_hash,
            portal_enabled,
            activation_status,
            last_login_at
        FROM supplier_portal_accounts
        WHERE LOWER(user_id) = LOWER(?)
        """,
        ((user_id or "").strip(),),
    ).fetchone()


def _upsert_supplier_portal_account(db, party_code: str, values) -> None:
    eligible = _supplier_portal_is_eligible(values.get("supplier_mode"), values.get("party_kind"))
    portal_enabled = bool(values.get("portal_enabled")) if eligible else False
    login_email = (values.get("portal_login_email") or values.get("email") or "").strip().lower()
    user_id = (values.get("portal_user_id") or values.get("user_id") or party_code.lower()).strip()
    if portal_enabled and not login_email:
        raise ValidationError("Portal login email is required when supplier portal is enabled.")
    if portal_enabled and not user_id:
        raise ValidationError("Portal user ID is required when supplier portal is enabled.")
    if login_email:
        _validate_optional_email(login_email)
    if user_id:
        _validate_supplier_user_id(user_id)

    existing = _supplier_portal_account_row(db, party_code)
    if not eligible and existing is None:
        return

    if not eligible:
        if existing is not None:
            db.execute(
                """
                UPDATE supplier_portal_accounts
                SET login_email = ?, portal_enabled = ?, activation_status = 'Suspended', updated_at = CURRENT_TIMESTAMP
                WHERE party_code = ?
                """,
                (login_email or existing["login_email"] or "", False, party_code),
            )
        return

    if existing is None:
        if not login_email and not portal_enabled:
            return
        activation_status = "Approved" if portal_enabled else "Suspended"
        db.execute(
            """
            INSERT INTO supplier_portal_accounts (
                party_code, user_id, login_email, password_hash, portal_enabled, activation_status, last_login_at
            ) VALUES (?, ?, ?, '', ?, ?, NULL)
            """,
            (party_code, user_id or party_code.lower(), login_email, bool(portal_enabled), activation_status),
        )
        return

    activation_status = existing["activation_status"] or "Approved"
    if not portal_enabled:
        activation_status = "Suspended"
    elif existing["password_hash"]:
        activation_status = "Active"
    elif activation_status in {"Rejected", "Pending Approval"}:
        activation_status = "Approved"

    db.execute(
        """
        UPDATE supplier_portal_accounts
        SET user_id = ?, login_email = ?, portal_enabled = ?, activation_status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE party_code = ?
        """,
        (user_id or existing["user_id"] or party_code.lower(), login_email or existing["login_email"] or "", bool(portal_enabled), activation_status, party_code),
    )


def _supplier_portal_auth_target(db, user_id: str, *, allow_incomplete_password: bool = False):
    normalized_user_id = (user_id or "").strip()
    if not normalized_user_id:
        raise ValidationError("User ID is required.")
    account = _supplier_portal_account_by_user_id(db, normalized_user_id)
    if account is None:
        pending = _supplier_registration_request_by_user_id(db, normalized_user_id)
        if pending is not None and (pending["approval_status"] or "") == "Pending Approval":
            raise ValidationError("Your supplier registration is still waiting for approval.")
        raise ValidationError("Supplier portal account was not found.")
    party = _fetch_supplier_party(db, account["party_code"])
    if party is None:
        raise ValidationError("Supplier company is no longer available.")
    if _supplier_mode_for_party(db, account["party_code"]) != "Normal" or (party["party_kind"] or "") != "Company":
        raise ValidationError("Supplier portal is not available for this supplier.")
    if not bool(account["portal_enabled"]):
        raise ValidationError("Supplier portal is disabled.")
    status = (account["activation_status"] or "").strip()
    if status == "Pending Approval":
        raise ValidationError("Your supplier registration is still waiting for approval.")
    if status == "Rejected":
        raise ValidationError("Supplier portal registration was rejected.")
    if status == "Suspended":
        raise ValidationError("Supplier portal is suspended.")
    if status == "Approved" and not allow_incomplete_password and not account["password_hash"]:
        raise ValidationError("Supplier account is approved but password setup is incomplete.")
    return account, party


def _supplier_login_target(db, user_id: str):
    return _supplier_portal_auth_target(db, user_id)


def _supplier_reset_target(db, user_id: str, email: str):
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        raise ValidationError("Email is required.")
    _validate_optional_email(normalized_email)
    account, party = _supplier_portal_auth_target(db, user_id, allow_incomplete_password=True)
    if (account["login_email"] or "").strip().lower() != normalized_email:
        raise ValidationError("User ID and email do not match.")
    if (account["activation_status"] or "") not in {"Approved", "Active"}:
        raise ValidationError("Password reset is only available for approved supplier accounts.")
    return account, party


def _technician_login_target(db, user_id: str):
    normalized_user_id = (user_id or "").strip()
    if not normalized_user_id:
        raise ValidationError("User ID is required.")
    
    # Try to find technician by technician_code or user_id
    technician = db.execute(
        """
        SELECT
            technician_code, party_code, user_id, password_hash,
            phone_number, specialization, status, created_at
        FROM technicians
        WHERE technician_code = ? OR user_id = ?
        """,
        (normalized_user_id, normalized_user_id),
    ).fetchone()
    
    if technician is None:
        raise ValidationError("Field staff account was not found.")
    
    # Fetch party information if party_code exists
    party = None
    if technician["party_code"]:
        party = db.execute(
            """
            SELECT party_code, party_name, party_kind, party_roles
            FROM parties
            WHERE party_code = ?
            """,
            (technician["party_code"],),
        ).fetchone()
    
    # Create a dummy party object if party_code is NULL
    if party is None:
        party = {
            "party_code": technician["party_code"] or "",
            "party_name": technician["specialization"] or "Independent Field Staff",
            "party_kind": "Individual",
            "party_roles": ["Field Staff"],
        }
    
    if (technician["status"] or "").strip() != "Active":
        raise ValidationError("Field staff account is not active.")
    
    if not technician["password_hash"]:
        raise ValidationError("Field staff account password is not set yet.")
    
    return technician, party


def _default_supplier_registration_form(db=None):
    db = db or open_db()
    return {
        "request_no": _next_reference_code(db, "supplier_registration_requests", "request_no", "SRG"),
        "company_name": "",
        "contact_person": "",
        "phone_number": "",
        "email": "",
        "trn_no": "",
        "trade_license_no": "",
        "address": "",
        "notes": "",
        "user_id": "",
    }


def _supplier_registration_form_data(request):
    return {
        "request_no": request.form.get("request_no", "").strip().upper(),
        "company_name": request.form.get("company_name", "").strip(),
        "contact_person": request.form.get("contact_person", "").strip(),
        "phone_number": request.form.get("phone_number", "").strip(),
        "email": request.form.get("email", "").strip().lower(),
        "trn_no": request.form.get("trn_no", "").strip(),
        "trade_license_no": request.form.get("trade_license_no", "").strip(),
        "address": request.form.get("address", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "user_id": request.form.get("user_id", "").strip(),
    }


def _validate_supplier_user_id(user_id: str) -> str:
    normalized = (user_id or "").strip()
    if not normalized:
        raise ValidationError("User ID is required.")
    if len(normalized) < 4:
        raise ValidationError("User ID must be at least 4 characters.")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", normalized):
        raise ValidationError("User ID can only use letters, numbers, dot, underscore and dash.")
    return normalized


def _prepare_supplier_registration_payload(db, values):
    if not values["request_no"]:
        values["request_no"] = _next_reference_code(db, "supplier_registration_requests", "request_no", "SRG")
    if not values["company_name"]:
        raise ValidationError("Company name is required.")
    values["phone_number"] = _normalize_optional_phone(values["phone_number"])
    _validate_optional_email(values["email"])
    values["user_id"] = _validate_supplier_user_id(values["user_id"])
    if db.execute("SELECT 1 FROM supplier_registration_requests WHERE LOWER(user_id) = LOWER(?)", (values["user_id"],)).fetchone():
        raise ValidationError("This user ID is already used in a supplier registration.")
    if db.execute("SELECT 1 FROM supplier_portal_accounts WHERE LOWER(user_id) = LOWER(?)", (values["user_id"],)).fetchone():
        raise ValidationError("This user ID is already active in the supplier portal.")
    password = request.form.get("password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()
    if len(password) < 6:
        raise ValidationError("Password must be at least 6 characters.")
    if password != confirm_password:
        raise ValidationError("Password confirmation does not match.")
    return (
        values["request_no"],
        values["company_name"],
        values["contact_person"],
        values["phone_number"],
        values["email"],
        values["trn_no"],
        values["trade_license_no"],
        values["address"],
        values["notes"],
        values["user_id"],
        generate_password_hash(password),
        "Pending Approval",
        None,
        None,
        None,
        None,
    )


def _supplier_registration_request_by_user_id(db, user_id: str):
    return db.execute(
        "SELECT * FROM supplier_registration_requests WHERE LOWER(user_id) = LOWER(?) LIMIT 1",
        ((user_id or "").strip(),),
    ).fetchone()


def _supplier_registration_request(db, request_no: str):
    return db.execute(
        "SELECT * FROM supplier_registration_requests WHERE request_no = ? LIMIT 1",
        ((request_no or "").strip().upper(),),
    ).fetchone()


def _supplier_registration_rows(db, status: str | None = None, limit: int = 50):
    params = []
    where_sql = ""
    if status:
        where_sql = "WHERE approval_status = ?"
        params.append(status)
    return db.execute(
        f"""
        SELECT request_no, company_name, contact_person, phone_number, email, user_id,
               trn_no, trade_license_no, approval_status, reviewed_by, reviewed_at,
               rejection_note, approved_party_code, created_at
        FROM supplier_registration_requests
        {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT {int(limit)}
        """,
        params,
    ).fetchall()


def _approve_supplier_registration(db, request_no: str, reviewer: str) -> str:
    row = _supplier_registration_request(db, request_no)
    if row is None:
        raise ValidationError("Supplier registration request was not found.")
    if (row["approval_status"] or "") != "Pending Approval":
        raise ValidationError("Only pending supplier registrations can be approved.")
    party_code = _next_party_code(db)
    roles = _serialize_party_roles(["Supplier"])
    db.execute(
        """
        INSERT INTO parties (
            party_code, party_name, party_kind, party_roles, contact_person,
            phone_number, email, trn_no, trade_license_no, address, notes, status
        ) VALUES (?, ?, 'Company', ?, ?, ?, ?, ?, ?, ?, ?, 'Active')
        """,
        (
            party_code,
            row["company_name"],
            roles,
            row["contact_person"] or row["company_name"],
            row["phone_number"] or "",
            row["email"],
            row["trn_no"] or "",
            row["trade_license_no"] or "",
            row["address"] or "",
            row["notes"] or "Portal supplier registration",
        ),
    )
    _upsert_supplier_profile(
        db,
        party_code,
        {
            "supplier_mode": "Normal",
            "partner_party_code": "",
            "partner_name": "",
            "default_company_share_percent": "100",
            "default_partner_share_percent": "0",
        },
    )
    db.execute(
        """
        INSERT INTO supplier_portal_accounts (
            party_code, user_id, login_email, password_hash, portal_enabled, activation_status, last_login_at
        ) VALUES (?, ?, ?, ?, ?, 'Approved', NULL)
        """,
        (
            party_code,
            row["user_id"],
            row["email"],
            row["password_hash"],
            True,
        ),
    )
    db.execute(
        """
        UPDATE supplier_registration_requests
        SET approval_status = 'Approved', reviewed_by = ?, reviewed_at = ?, approved_party_code = ?, rejection_note = NULL
        WHERE request_no = ?
        """,
        (reviewer, datetime.now().isoformat(timespec="seconds"), party_code, request_no),
    )
    return party_code


def _reject_supplier_registration(db, request_no: str, reviewer: str, note: str = "") -> None:
    row = _supplier_registration_request(db, request_no)
    if row is None:
        raise ValidationError("Supplier registration request was not found.")
    if (row["approval_status"] or "") != "Pending Approval":
        raise ValidationError("Only pending supplier registrations can be rejected.")
    db.execute(
        """
        UPDATE supplier_registration_requests
        SET approval_status = 'Rejected', reviewed_by = ?, reviewed_at = ?, rejection_note = ?
        WHERE request_no = ?
        """,
        (reviewer, datetime.now().isoformat(timespec="seconds"), note or "Registration rejected", request_no),
    )


def _normalize_supplier_roles(values) -> list[str]:
    selected = ["Supplier"]
    for role in PARTY_ROLE_OPTIONS:
        if role == "Supplier":
            continue
        if role in values and role not in selected:
            selected.append(role)
    return selected


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
        "double_shift_mode": SUPPLIER_SHIFT_MODE_OPTIONS[0],
        "partnership_mode": SUPPLIER_PARTNERSHIP_MODE_OPTIONS[0],
        "partner_name": "",
        "company_share_percent": "100",
        "partner_share_percent": "0",
        "day_shift_paid_by": PARTNERSHIP_PAID_BY_OPTIONS[0],
        "night_shift_paid_by": PARTNERSHIP_PAID_BY_OPTIONS[0],
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


def _default_supplier_submission_form(db=None, party_code: str = "", source_channel: str = "By Hand"):
    db = db or open_db()
    return {
        "original_submission_no": "",
        "submission_no": _next_reference_code(db, "supplier_invoice_submissions", "submission_no", "SIN"),
        "party_code": party_code,
        "lpo_no": "",
        "source_channel": source_channel,
        "external_invoice_no": "",
        "period_month": _current_month_value(),
        "invoice_date": date.today().isoformat(),
        "subtotal": "",
        "vat_amount": "",
        "total_amount": "",
        "notes": "",
        "review_note": "",
    }


def _supplier_submission_form_from_row(db, row, source_channel: str = "Portal"):
    values = _default_supplier_submission_form(db, row["party_code"], source_channel=source_channel)
    values.update(
        {
            "external_invoice_no": row["external_invoice_no"] or "",
            "lpo_no": row["lpo_no"] or "",
            "period_month": row["period_month"] or _current_month_value(),
            "invoice_date": row["invoice_date"] or date.today().isoformat(),
            "subtotal": _display_number(row["subtotal"]),
            "vat_amount": _display_number(row["vat_amount"]),
            "total_amount": _display_number(row["total_amount"]),
            "notes": row["notes"] or "",
            "review_note": row["review_note"] or "",
        }
    )
    return values


def _default_supplier_quotation_form(db=None, party_code: str = ""):
    db = db or open_db()
    return {
        "original_quotation_no": "",
        "quotation_no": _next_reference_code(db, "supplier_quotation_submissions", "quotation_no", "SQT"),
        "party_code": party_code,
        "quotation_date": date.today().isoformat(),
        "job_title": "",
        "amount_basis": "",
        "amount": "",
        "notes": "",
        "review_note": "",
    }


def _supplier_quotation_form_data(request, party_code: str):
    return {
        "original_quotation_no": request.form.get("original_quotation_no", "").strip().upper(),
        "quotation_no": request.form.get("quotation_no", "").strip().upper(),
        "party_code": party_code,
        "quotation_date": request.form.get("quotation_date", date.today().isoformat()).strip() or date.today().isoformat(),
        "job_title": request.form.get("job_title", "").strip(),
        "amount_basis": request.form.get("amount_basis", "").strip(),
        "amount": request.form.get("amount", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "review_note": request.form.get("review_note", "").strip(),
    }


def _supplier_quotation_attachment_dir(party_code: str) -> Path:
    folder = Path(current_app.config["GENERATED_DIR"]) / "suppliers" / party_code / "quotations"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _save_supplier_quotation_attachment(quotation_no: str, party_code: str, upload) -> str:
    if upload is None or not getattr(upload, "filename", ""):
        return ""
    safe_name = secure_filename(upload.filename or "")
    extension = Path(safe_name).suffix.lower()
    target = _supplier_quotation_attachment_dir(party_code) / f"{quotation_no.lower()}_quotation{extension or '.bin'}"
    upload.save(target)
    _mirror_generated_file(current_app, target)
    return target.relative_to(Path(current_app.config["GENERATED_DIR"])).as_posix()


def _prepare_supplier_quotation_payload(db, values, attachment_file):
    _validate_party_reference(db, values["party_code"])
    if not values["quotation_no"]:
        values["quotation_no"] = _next_reference_code(db, "supplier_quotation_submissions", "quotation_no", "SQT")
    if not values["job_title"]:
        raise ValidationError("Job or work title is required.")
    quotation_date = _validate_date_text(values["quotation_date"], "Quotation date")
    amount = _parse_decimal(values["amount"], "Quotation amount", required=True, minimum=0.0)
    attachment_path = _save_supplier_quotation_attachment(values["quotation_no"], values["party_code"], attachment_file)
    return (
        values["quotation_no"],
        values["party_code"],
        quotation_date,
        values["job_title"],
        values["amount_basis"],
        amount,
        values["notes"],
        attachment_path or None,
        "Pending",
        None,
        None,
        None,
    )


def _supplier_quotation_rows(db, party_code: str = "", limit: int = 40):
    where_sql = ""
    params = []
    if party_code:
        where_sql = "WHERE q.party_code = ?"
        params.append(party_code)
    return db.execute(
        f"""
        SELECT
            q.quotation_no,
            q.party_code,
            p.party_name,
            q.quotation_date,
            q.job_title,
            q.amount_basis,
            q.amount,
            q.notes,
            q.attachment_path,
            q.review_status,
            q.review_note,
            q.reviewed_by,
            q.reviewed_at,
            l.lpo_no,
            l.status AS lpo_status
        FROM supplier_quotation_submissions q
        LEFT JOIN parties p ON p.party_code = q.party_code
        LEFT JOIN lpos l ON l.quotation_no = q.quotation_no
        {where_sql}
        ORDER BY q.quotation_date DESC, q.id DESC
        LIMIT {int(limit)}
        """,
        params,
    ).fetchall()


def _supplier_quotation_row(db, quotation_no: str, party_code: str | None = None):
    params = [(quotation_no or "").strip().upper()]
    extra_sql = ""
    if party_code:
        params.append(party_code)
        extra_sql = "AND q.party_code = ?"
    return db.execute(
        f"""
        SELECT q.*, l.lpo_no
        FROM supplier_quotation_submissions q
        LEFT JOIN lpos l ON l.quotation_no = q.quotation_no
        WHERE q.quotation_no = ?
        {extra_sql}
        LIMIT 1
        """,
        params,
    ).fetchone()


def _set_supplier_quotation_status(db, quotation_no: str, status: str, reviewer: str, note: str = "") -> None:
    row = _supplier_quotation_row(db, quotation_no)
    if row is None:
        raise ValidationError("Quotation was not found.")
    if status not in {"Approved", "Rejected"}:
        raise ValidationError("Invalid quotation status.")
    db.execute(
        """
        UPDATE supplier_quotation_submissions
        SET review_status = ?, review_note = ?, reviewed_by = ?, reviewed_at = ?
        WHERE quotation_no = ?
        """,
        (status, note or None, reviewer, datetime.now().isoformat(timespec="seconds"), quotation_no),
    )


def _default_supplier_partnership_form(db=None, party_code: str = ""):
    db = db or open_db()
    return {
        "original_entry_no": "",
        "entry_no": _next_reference_code(db, "supplier_partnership_entries", "entry_no", "PEN"),
        "party_code": party_code,
        "asset_code": "",
        "period_month": _current_month_value(),
        "entry_date": date.today().isoformat(),
        "entry_kind": PARTNERSHIP_ENTRY_KIND_OPTIONS[0],
        "expense_head": "",
        "shift_label": PARTNERSHIP_SHIFT_OPTIONS[0],
        "driver_name": "",
        "paid_by": PARTNERSHIP_PAID_BY_OPTIONS[0],
        "amount": "",
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
        "double_shift_mode": request.form.get("double_shift_mode", SUPPLIER_SHIFT_MODE_OPTIONS[0]).strip() or SUPPLIER_SHIFT_MODE_OPTIONS[0],
        "partnership_mode": request.form.get("partnership_mode", SUPPLIER_PARTNERSHIP_MODE_OPTIONS[0]).strip() or SUPPLIER_PARTNERSHIP_MODE_OPTIONS[0],
        "partner_name": request.form.get("partner_name", "").strip(),
        "company_share_percent": request.form.get("company_share_percent", "100").strip() or "100",
        "partner_share_percent": request.form.get("partner_share_percent", "0").strip() or "0",
        "day_shift_paid_by": request.form.get("day_shift_paid_by", PARTNERSHIP_PAID_BY_OPTIONS[0]).strip() or PARTNERSHIP_PAID_BY_OPTIONS[0],
        "night_shift_paid_by": request.form.get("night_shift_paid_by", PARTNERSHIP_PAID_BY_OPTIONS[0]).strip() or PARTNERSHIP_PAID_BY_OPTIONS[0],
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


def _supplier_submission_form_data(request, party_code: str, source_channel: str = "By Hand"):
    return {
        "original_submission_no": request.form.get("original_submission_no", "").strip().upper(),
        "submission_no": request.form.get("submission_no", "").strip().upper(),
        "party_code": party_code,
        "lpo_no": request.form.get("lpo_no", "").strip().upper(),
        "source_channel": source_channel,
        "external_invoice_no": request.form.get("external_invoice_no", "").strip().upper(),
        "period_month": _normalize_month(request.form.get("period_month", "").strip() or request.form.get("invoice_date", "").strip()[:7] or _current_month_value()),
        "invoice_date": request.form.get("invoice_date", date.today().isoformat()).strip() or date.today().isoformat(),
        "subtotal": request.form.get("subtotal", "").strip(),
        "vat_amount": request.form.get("vat_amount", "").strip(),
        "total_amount": request.form.get("total_amount", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "review_note": request.form.get("review_note", "").strip(),
    }


def _supplier_partnership_form_data(request, party_code: str):
    return {
        "original_entry_no": request.form.get("original_entry_no", "").strip().upper(),
        "entry_no": request.form.get("entry_no", "").strip().upper(),
        "party_code": party_code,
        "asset_code": request.form.get("asset_code", "").strip().upper(),
        "period_month": _normalize_month(request.form.get("period_month", "").strip()),
        "entry_date": request.form.get("entry_date", date.today().isoformat()).strip() or date.today().isoformat(),
        "entry_kind": request.form.get("entry_kind", PARTNERSHIP_ENTRY_KIND_OPTIONS[0]).strip() or PARTNERSHIP_ENTRY_KIND_OPTIONS[0],
        "expense_head": request.form.get("expense_head", "").strip(),
        "shift_label": request.form.get("shift_label", PARTNERSHIP_SHIFT_OPTIONS[0]).strip() or PARTNERSHIP_SHIFT_OPTIONS[0],
        "driver_name": request.form.get("driver_name", "").strip(),
        "paid_by": request.form.get("paid_by", PARTNERSHIP_PAID_BY_OPTIONS[0]).strip() or PARTNERSHIP_PAID_BY_OPTIONS[0],
        "amount": request.form.get("amount", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }


def _supplier_submission_attachment_dir(party_code: str) -> Path:
    folder = Path(current_app.config["GENERATED_DIR"]) / "suppliers" / party_code / "submissions"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _save_supplier_submission_attachment(submission_no: str, party_code: str, upload, attachment_kind: str, required: bool) -> str:
    if upload is None or not getattr(upload, "filename", ""):
        if required:
            raise ValidationError(f"{attachment_kind.title()} attachment is required.")
        return ""
    safe_name = secure_filename(upload.filename or "")
    extension = Path(safe_name).suffix.lower()
    filename = f"{submission_no.lower()}_{attachment_kind.replace(' ', '_').lower()}{extension or '.bin'}"
    target = _supplier_submission_attachment_dir(party_code) / filename
    upload.save(target)
    _mirror_generated_file(current_app, target)
    return target.relative_to(Path(current_app.config["GENERATED_DIR"])).as_posix()


def _prepare_supplier_submission_payload(
    db,
    values,
    *,
    source_channel: str,
    created_by_role: str,
    created_by_name: str,
    invoice_file,
    timesheet_file,
):
    _validate_party_reference(db, values["party_code"])
    if not values["submission_no"]:
        values["submission_no"] = _next_reference_code(db, "supplier_invoice_submissions", "submission_no", "SIN")
    if not values["external_invoice_no"]:
        raise ValidationError("Invoice number is required.")
    invoice_date = _validate_date_text(values["invoice_date"], "Invoice date")
    subtotal = _parse_decimal(values["subtotal"], "Subtotal", required=True, minimum=0.01)
    vat_amount = _parse_decimal(values["vat_amount"], "VAT amount", required=False, default=0.0, minimum=0.0)
    total_amount = _parse_decimal(values["total_amount"], "Total amount", required=True, minimum=0.01)
    expected_total = round(subtotal + vat_amount, 2)
    if abs(total_amount - expected_total) > 0.01:
        raise ValidationError("Total amount must equal subtotal plus VAT.")
    if source_channel not in {"Portal", "By Hand"}:
        source_channel = "By Hand"

    invoice_attachment_path = _save_supplier_submission_attachment(
        values["submission_no"],
        values["party_code"],
        invoice_file,
        "invoice",
        required=source_channel == "Portal",
    )
    timesheet_attachment_path = _save_supplier_submission_attachment(
        values["submission_no"],
        values["party_code"],
        timesheet_file,
        "timesheet",
        required=source_channel == "Portal",
    )
    if source_channel == "Portal":
        review_status = "Pending"
        review_note = ""
        reviewed_by = None
        reviewed_at = None
    else:
        review_status = "Approved"
        review_note = values.get("review_note", "").strip() or "Ready for Voucher"
        reviewed_by = created_by_name
        reviewed_at = datetime.now().isoformat(timespec="seconds")

    return (
        values["submission_no"],
        values["party_code"],
        source_channel,
        values["external_invoice_no"],
        values["period_month"] or invoice_date[:7],
        invoice_date,
        subtotal,
        vat_amount,
        total_amount,
        invoice_attachment_path or None,
        timesheet_attachment_path or None,
        values.get("notes", "").strip(),
        review_status,
        review_note or None,
        reviewed_by,
        reviewed_at,
        None,
        created_by_role,
        created_by_name,
    )


def _supplier_submission_with_voucher(db, submission_no: str, party_code: str | None = None):
    params = [submission_no]
    party_sql = ""
    if party_code:
        params.append(party_code)
        party_sql = "AND s.party_code = ?"
    return db.execute(
        f"""
        SELECT
            s.submission_no,
            s.party_code,
            s.lpo_no,
            s.source_channel,
            s.external_invoice_no,
            s.period_month,
            s.invoice_date,
            s.subtotal,
            s.vat_amount,
            s.total_amount,
            s.invoice_attachment_path,
            s.timesheet_attachment_path,
            s.notes,
            s.review_status,
            s.review_note,
            s.reviewed_by,
            s.reviewed_at,
            s.linked_voucher_no,
            s.created_by_role,
            s.created_by_name,
            s.created_at,
            v.status AS voucher_status,
            v.paid_amount AS voucher_paid_amount,
            v.balance_amount AS voucher_balance_amount
        FROM supplier_invoice_submissions s
        LEFT JOIN supplier_vouchers v ON v.voucher_no = s.linked_voucher_no
        WHERE s.submission_no = ?
        {party_sql}
        """,
        params,
    ).fetchone()


def _set_supplier_submission_status(db, party_code: str, submission_no: str, status: str, *, review_note: str = "", reviewed_by: str = "") -> None:
    row = _supplier_submission_with_voucher(db, submission_no, party_code)
    if row is None:
        raise ValidationError("Supplier invoice submission was not found.")
    if row["linked_voucher_no"]:
        raise ValidationError("Converted supplier invoices cannot be reviewed again.")
    if status not in {"Approved", "Rejected"}:
        raise ValidationError("Invalid review status.")
    db.execute(
        """
        UPDATE supplier_invoice_submissions
        SET review_status = ?, review_note = ?, reviewed_by = ?, reviewed_at = ?
        WHERE submission_no = ? AND party_code = ?
        """,
        (
            status,
            review_note or None,
            reviewed_by or None,
            datetime.now().isoformat(timespec="seconds"),
            submission_no,
            party_code,
        ),
    )


def _convert_supplier_submission_to_voucher(db, party_code: str, submission_no: str, *, actor_name: str) -> str:
    row = _supplier_submission_with_voucher(db, submission_no, party_code)
    if row is None:
        raise ValidationError("Supplier invoice submission was not found.")
    if row["review_status"] != "Approved":
        raise ValidationError("Only approved supplier invoices can be converted.")
    if row["linked_voucher_no"]:
        raise ValidationError("This supplier invoice was already converted.")
    voucher_no = _next_reference_code(db, "supplier_vouchers", "voucher_no", "SPV")
    subtotal = float(row["subtotal"] or 0.0)
    vat_amount = float(row["vat_amount"] or 0.0)
    total_amount = float(row["total_amount"] or 0.0)
    tax_percent = round((vat_amount / subtotal) * 100.0, 4) if subtotal > 0 else 0.0
    db.execute(
        """
        INSERT INTO supplier_vouchers (
            voucher_no, party_code, period_month, issue_date, subtotal,
            tax_percent, tax_amount, total_amount, paid_amount, balance_amount,
            status, notes, source_type, source_reference
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            voucher_no,
            party_code,
            row["period_month"] or (row["invoice_date"] or "")[:7] or _current_month_value(),
            row["invoice_date"],
            subtotal,
            tax_percent,
            vat_amount,
            total_amount,
            0.0,
            total_amount,
            "Open",
            row["notes"] or "",
            "Submission",
            submission_no,
        ),
    )
    db.execute(
        """
        UPDATE supplier_invoice_submissions
        SET review_status = 'Converted', linked_voucher_no = ?, reviewed_by = ?, reviewed_at = ?
        WHERE submission_no = ? AND party_code = ?
        """,
        (
            voucher_no,
            actor_name or None,
            datetime.now().isoformat(timespec="seconds"),
            submission_no,
            party_code,
        ),
    )
    return voucher_no


def _supplier_submission_rows(db, party_code: str, limit: int = 30):
    rows = db.execute(
        f"""
        SELECT
            s.submission_no,
            s.party_code,
            s.lpo_no,
            s.source_channel,
            s.external_invoice_no,
            s.period_month,
            s.invoice_date,
            s.subtotal,
            s.vat_amount,
            s.total_amount,
            s.invoice_attachment_path,
            s.timesheet_attachment_path,
            s.notes,
            s.review_status,
            s.review_note,
            s.reviewed_by,
            s.reviewed_at,
            s.linked_voucher_no,
            s.created_by_role,
            s.created_by_name,
            s.created_at,
            v.status AS voucher_status,
            v.paid_amount AS voucher_paid_amount,
            v.balance_amount AS voucher_balance_amount
        FROM supplier_invoice_submissions s
        LEFT JOIN supplier_vouchers v ON v.voucher_no = s.linked_voucher_no
        WHERE s.party_code = ?
        ORDER BY s.invoice_date DESC, s.created_at DESC, s.id DESC
        LIMIT {int(limit)}
        """,
        (party_code,),
    ).fetchall()
    prepared = []
    for row in rows:
        total_amount = float(row["total_amount"] or 0.0)
        if row["linked_voucher_no"]:
            paid_amount = float(row["voucher_paid_amount"] or 0.0)
            balance_amount = float(row["voucher_balance_amount"] or 0.0)
            display_status = row["voucher_status"] or "Converted"
            if display_status == "Open":
                display_status = "Converted"
        else:
            paid_amount = 0.0
            if row["review_status"] == "Approved":
                balance_amount = total_amount
            else:
                balance_amount = 0.0
            display_status = row["review_status"] or "Pending"
        status_bucket = "approved"
        if display_status == "Pending":
            status_bucket = "pending"
        elif display_status == "Rejected":
            status_bucket = "rejected"
        prepared.append(
            {
                **dict(row),
                "total_amount": total_amount,
                "paid_amount_display": paid_amount,
                "balance_amount_display": balance_amount,
                "display_status": display_status,
                "status_bucket": status_bucket,
            }
        )
    return prepared


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
            "double_shift_mode": row["double_shift_mode"] or SUPPLIER_SHIFT_MODE_OPTIONS[0],
            "partnership_mode": row["partnership_mode"] or SUPPLIER_PARTNERSHIP_MODE_OPTIONS[0],
            "partner_name": row["partner_name"] or "",
            "company_share_percent": _display_number(row["company_share_percent"]),
            "partner_share_percent": _display_number(row["partner_share_percent"]),
            "day_shift_paid_by": row["day_shift_paid_by"] or PARTNERSHIP_PAID_BY_OPTIONS[0],
            "night_shift_paid_by": row["night_shift_paid_by"] or PARTNERSHIP_PAID_BY_OPTIONS[0],
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


def _supplier_partnership_form_from_row(row):
    values = _default_supplier_partnership_form()
    values.update(
        {
            "original_entry_no": row["entry_no"],
            "entry_no": row["entry_no"],
            "party_code": row["party_code"],
            "asset_code": row["asset_code"] or "",
            "period_month": row["period_month"] or _current_month_value(),
            "entry_date": row["entry_date"] or date.today().isoformat(),
            "entry_kind": row["entry_kind"] or PARTNERSHIP_ENTRY_KIND_OPTIONS[0],
            "expense_head": row["expense_head"] or "",
            "shift_label": row["shift_label"] or PARTNERSHIP_SHIFT_OPTIONS[0],
            "driver_name": row["driver_name"] or "",
            "paid_by": row["paid_by"] or PARTNERSHIP_PAID_BY_OPTIONS[0],
            "amount": _display_number(row["amount"]),
            "notes": row["notes"] or "",
        }
    )
    return values


def _supplier_profile_defaults(db, party_code: str):
    profile = _supplier_profile_row(db, party_code)
    if profile is None:
        return {
            "partner_name": "",
            "company_share_percent": 50.0,
            "partner_share_percent": 50.0,
        }
    return {
        "partner_name": profile["partner_name"] or "",
        "company_share_percent": float(profile["default_company_share_percent"] or 50.0),
        "partner_share_percent": float(profile["default_partner_share_percent"] or 50.0),
    }


def _apply_supplier_mode_to_asset_values(db, values, supplier_mode: str, party_code: str):
    values["party_code"] = party_code
    if (supplier_mode or "Normal") == "Partnership":
        defaults = _supplier_profile_defaults(db, party_code)
        values["partnership_mode"] = "Partnership"
        values["partner_name"] = values["partner_name"] or defaults["partner_name"]
        values["company_share_percent"] = values["company_share_percent"] or _display_number(defaults["company_share_percent"])
        values["partner_share_percent"] = values["partner_share_percent"] or _display_number(defaults["partner_share_percent"])
    else:
        values["partnership_mode"] = "Standard"
        values["partner_name"] = ""
        values["company_share_percent"] = "100"
        values["partner_share_percent"] = "0"
        values["day_shift_paid_by"] = PARTNERSHIP_PAID_BY_OPTIONS[0]
        values["night_shift_paid_by"] = PARTNERSHIP_PAID_BY_OPTIONS[0]
    return values


def _prepare_supplier_asset_payload(db, values):
    _validate_party_reference(db, values["party_code"])
    if not values["asset_code"]:
        values["asset_code"] = _next_reference_code(db, "supplier_assets", "asset_code", "AST")
    if not values["asset_name"]:
        raise ValidationError("Vehicle / asset name is required.")
    default_rate = _parse_decimal(values["default_rate"], "Default rate", required=False, default=0.0, minimum=0.0)
    double_shift_mode = values["double_shift_mode"] if values["double_shift_mode"] in SUPPLIER_SHIFT_MODE_OPTIONS else SUPPLIER_SHIFT_MODE_OPTIONS[0]
    partnership_mode = values["partnership_mode"] if values["partnership_mode"] in SUPPLIER_PARTNERSHIP_MODE_OPTIONS else SUPPLIER_PARTNERSHIP_MODE_OPTIONS[0]
    if partnership_mode == "Partnership":
        company_share_percent = _parse_decimal(values["company_share_percent"], "Company share percent", required=True, minimum=0.0)
        partner_share_percent = _parse_decimal(values["partner_share_percent"], "Partner share percent", required=True, minimum=0.0)
        if abs((company_share_percent + partner_share_percent) - 100.0) > 0.01:
            raise ValidationError("Company share and partner share must total 100.")
        if not values["partner_name"]:
            raise ValidationError("Partner name is required for partnership vehicles.")
    else:
        company_share_percent = 100.0
        partner_share_percent = 0.0
        values["partner_name"] = ""
    day_shift_paid_by = values["day_shift_paid_by"] if values["day_shift_paid_by"] in PARTNERSHIP_PAID_BY_OPTIONS else PARTNERSHIP_PAID_BY_OPTIONS[0]
    night_shift_paid_by = values["night_shift_paid_by"] if values["night_shift_paid_by"] in PARTNERSHIP_PAID_BY_OPTIONS else PARTNERSHIP_PAID_BY_OPTIONS[0]
    return (
        values["asset_code"],
        values["party_code"],
        values["asset_name"],
        values["asset_type"],
        values["vehicle_no"],
        values["rate_basis"],
        default_rate,
        double_shift_mode,
        partnership_mode,
        values["partner_name"],
        company_share_percent,
        partner_share_percent,
        day_shift_paid_by,
        night_shift_paid_by,
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
            "Timesheet",
            values["period_month"],
        ),
        timesheets,
    )


def _prepare_existing_supplier_voucher_payload(db, values):
    voucher_lookup = values["original_voucher_no"] or values["voucher_no"]
    voucher = db.execute(
        "SELECT voucher_no, tax_percent, source_type, source_reference, subtotal FROM supplier_vouchers WHERE voucher_no = ? AND party_code = ?",
        (voucher_lookup, values["party_code"]),
    ).fetchone()
    if voucher is None:
        raise ValidationError("Supplier voucher was not found.")
    if not values["voucher_no"]:
        values["voucher_no"] = voucher_lookup
    issue_date = _validate_date_text(values["issue_date"], "Voucher date")
    tax_percent = _parse_decimal(values["tax_percent"], "Tax percent", required=False, default=float(voucher["tax_percent"] or 0.0), minimum=0.0)
    if (voucher["source_type"] or "Timesheet") == "Submission":
        subtotal = float(voucher["subtotal"] or 0.0)
    else:
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
        voucher["source_type"] or "Timesheet",
        voucher["source_reference"],
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


def _prepare_supplier_partnership_payload(db, values):
    _validate_party_reference(db, values["party_code"])
    asset = db.execute(
        """
        SELECT asset_code, party_code, asset_name, partnership_mode, double_shift_mode
        FROM supplier_assets
        WHERE asset_code = ? AND party_code = ?
        """,
        (values["asset_code"], values["party_code"]),
    ).fetchone()
    if asset is None:
        raise ValidationError("Select a valid supplier vehicle first.")
    if not values["entry_no"]:
        values["entry_no"] = _next_reference_code(db, "supplier_partnership_entries", "entry_no", "PEN")
    entry_date = _validate_date_text(values["entry_date"], "Entry date")
    amount = _parse_decimal(values["amount"], "Amount", required=True, minimum=0.01)
    entry_kind = values["entry_kind"] if values["entry_kind"] in PARTNERSHIP_ENTRY_KIND_OPTIONS else PARTNERSHIP_ENTRY_KIND_OPTIONS[0]
    shift_label = values["shift_label"] if values["shift_label"] in PARTNERSHIP_SHIFT_OPTIONS else PARTNERSHIP_SHIFT_OPTIONS[0]
    paid_by = values["paid_by"] if values["paid_by"] in PARTNERSHIP_PAID_BY_OPTIONS else PARTNERSHIP_PAID_BY_OPTIONS[0]
    if asset["partnership_mode"] != "Partnership" and paid_by == "Partner":
        raise ValidationError("This vehicle is not marked as a partnership vehicle yet.")
    if asset["double_shift_mode"] != "Double Shift" and shift_label in {"Day", "Night"}:
        raise ValidationError("Day or night split can only be used on double-shift vehicles.")
    if entry_kind == "Driver Salary" and not values["driver_name"]:
        raise ValidationError("Driver name is required for salary split entries.")
    return (
        values["entry_no"],
        values["party_code"],
        values["asset_code"],
        values["period_month"],
        entry_date,
        entry_kind,
        values["expense_head"],
        shift_label,
        values["driver_name"],
        paid_by,
        amount,
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
        "SELECT voucher_no, tax_percent, source_type, subtotal FROM supplier_vouchers WHERE voucher_no = ?",
        (voucher_no,),
    ).fetchone()
    if voucher is None:
        return
    if (voucher["source_type"] or "Timesheet") == "Submission":
        subtotal = float(voucher["subtotal"] or 0.0)
    else:
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


def _safe_dashboard_scalar(db, sql: str, params=(), *, default=0, label: str = "dashboard metric"):
    try:
        row = db.execute(sql, params).fetchone()
    except Exception:
        current_app.logger.warning("Failed to load %s", label, exc_info=True)
        return default
    if row is None:
        return default
    value = row[0]
    return default if value is None else value


def _safe_supplier_view_value(label: str, fallback, loader, *args, **kwargs):
    try:
        return loader(*args, **kwargs)
    except Exception:
        current_app.logger.warning("Failed to load %s", label, exc_info=True)
        return fallback


def _generated_backup_root(app: Flask) -> Path | None:
    backup_root = (app.config.get("GENERATED_BACKUP_DIR") or "").strip()
    if not backup_root:
        return None
    return Path(backup_root)


def _mirror_generated_file(app: Flask, file_path: str | Path) -> None:
    backup_root = _generated_backup_root(app)
    if backup_root is None:
        return
    source_path = Path(file_path)
    generated_root = Path(app.config["GENERATED_DIR"])
    try:
        source_resolved = source_path.resolve()
        generated_resolved = generated_root.resolve()
        relative_path = source_resolved.relative_to(generated_resolved)
    except Exception:
        app.logger.warning("Generated backup skipped for %s", source_path)
        return
    if not source_path.exists() or not source_path.is_file():
        return
    backup_target = backup_root / relative_path
    try:
        backup_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, backup_target)
    except OSError:
        app.logger.warning("Generated backup failed for %s", source_path, exc_info=True)


def _supplier_hub_summary(db, supplier_mode: str = "Normal"):
    normalized_mode = supplier_mode if supplier_mode in SUPPLIER_MODE_OPTIONS else "Normal"
    
    # Helper to safely get scalar values, defaulting to 0 if table doesn't exist
    def safe_scalar(sql, params=(), default=0, label="supplier summary"):
        try:
            row = db.execute(sql, params).fetchone()
        except Exception:
            # If query fails (table missing), rollback to clear aborted transaction
            try:
                db.rollback()
            except Exception:
                pass  # Ignore rollback errors
            return default
        if row is None or row[0] is None:
            return default
        return row[0]
    
    return {
        "supplier_count": int(safe_scalar(
            """
            SELECT COUNT(*)
            FROM parties p
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            WHERE p.party_roles LIKE ? AND COALESCE(profile.supplier_mode, 'Normal') = ?
            """,
            ("%Supplier%", normalized_mode),
            default=0,
            label="supplier_count"
        )),
        "asset_count": int(safe_scalar(
            """
            SELECT COUNT(*)
            FROM supplier_assets asset
            JOIN parties p ON p.party_code = asset.party_code
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            WHERE COALESCE(profile.supplier_mode, 'Normal') = ?
            """,
            (normalized_mode,),
            default=0,
            label="asset_count"
        )),
        "double_shift_count": int(safe_scalar(
            """
            SELECT COUNT(*)
            FROM supplier_assets asset
            JOIN parties p ON p.party_code = asset.party_code
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            WHERE asset.double_shift_mode = 'Double Shift' AND COALESCE(profile.supplier_mode, 'Normal') = ?
            """,
            (normalized_mode,),
            default=0,
            label="double_shift_count"
        )),
        "partnership_count": int(safe_scalar(
            """
            SELECT COUNT(*)
            FROM supplier_assets asset
            JOIN parties p ON p.party_code = asset.party_code
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            WHERE asset.partnership_mode = 'Partnership' AND COALESCE(profile.supplier_mode, 'Normal') = ?
            """,
            (normalized_mode,),
            default=0,
            label="partnership_count"
        )),
        "unbilled_amount": float(safe_scalar(
            """
            SELECT COALESCE(SUM(t.subtotal), 0)
            FROM supplier_timesheets t
            JOIN parties p ON p.party_code = t.party_code
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            WHERE COALESCE(t.voucher_no, '') = '' AND COALESCE(profile.supplier_mode, 'Normal') = ?
            """,
            (normalized_mode,),
            default=0.0,
            label="unbilled_amount"
        ) or 0.0),
        "voucher_total": float(safe_scalar(
            """
            SELECT COALESCE(SUM(v.total_amount), 0)
            FROM supplier_vouchers v
            JOIN parties p ON p.party_code = v.party_code
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            WHERE COALESCE(profile.supplier_mode, 'Normal') = ?
            """,
            (normalized_mode,),
            default=0.0,
            label="voucher_total"
        ) or 0.0),
        "paid_total": float(safe_scalar(
            """
            SELECT COALESCE(SUM(pay.amount), 0)
            FROM supplier_payments pay
            JOIN parties p ON p.party_code = pay.party_code
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            WHERE COALESCE(profile.supplier_mode, 'Normal') = ?
            """,
            (normalized_mode,),
            default=0.0,
            label="paid_total"
        ) or 0.0),
        "outstanding_total": float(safe_scalar(
            """
            SELECT COALESCE(SUM(v.balance_amount), 0)
            FROM supplier_vouchers v
            JOIN parties p ON p.party_code = v.party_code
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            WHERE COALESCE(profile.supplier_mode, 'Normal') = ?
            """,
            (normalized_mode,),
            default=0.0,
            label="outstanding_total"
        ) or 0.0),
        "open_vouchers": int(safe_scalar(
            """
            SELECT COUNT(*)
            FROM supplier_vouchers v
            JOIN parties p ON p.party_code = v.party_code
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            WHERE v.balance_amount > 0.009 AND COALESCE(profile.supplier_mode, 'Normal') = ?
            """,
            (normalized_mode,),
            default=0,
            label="open_vouchers"
        )),
        "pending_inquiries_count": int(safe_scalar(
            """
            SELECT COUNT(*)
            FROM supplier_inquiries i
            JOIN parties p ON p.party_code = i.party_code
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            WHERE i.status IN ('Open', 'Pending') AND COALESCE(profile.supplier_mode, 'Normal') = ?
            """,
            (normalized_mode,),
            default=0,
            label="pending_inquiries_count"
        )),
        "pending_quotations_count": int(safe_scalar(
            """
            SELECT COUNT(*)
            FROM supplier_quotation_submissions q
            JOIN parties p ON p.party_code = q.party_code
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            WHERE q.review_status = 'Pending' AND COALESCE(profile.supplier_mode, 'Normal') = ?
            """,
            (normalized_mode,),
            default=0,
            label="pending_quotations_count"
        )),
        "active_inquiries_count": int(safe_scalar(
            """
            SELECT COUNT(*)
            FROM supplier_inquiries i
            JOIN parties p ON p.party_code = i.party_code
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            WHERE i.status = 'Active' AND COALESCE(profile.supplier_mode, 'Normal') = ?
            """,
            (normalized_mode,),
            default=0,
            label="active_inquiries_count"
        )),
        "portal_users_count": int(safe_scalar(
            """
            SELECT COUNT(*)
            FROM parties p
            LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
            LEFT JOIN supplier_portal_accounts portal ON portal.party_code = p.party_code
            WHERE p.party_roles LIKE ?
              AND COALESCE(profile.supplier_mode, 'Normal') = ?
              AND portal.user_id IS NOT NULL
            """,
            ("%Supplier%", normalized_mode),
            default=0,
            label="portal_users_count"
        )),
    }


def _cash_supplier_balance_meta(closing_balance: float):
    balance_value = round(float(closing_balance or 0.0), 2)
    if balance_value > 0.009:
        return "Balance Due", "due", balance_value
    if balance_value < -0.009:
        return "Advance Given", "advance", abs(balance_value)
    return "Settled", "settled", 0.0


def _cash_supplier_directory_rows(db, query: str = "", limit: int | None = None, active_only: bool = True):
    filters = ["p.party_roles LIKE ?", "COALESCE(profile.supplier_mode, 'Normal') IN (?, ?)"]
    params = ["%Supplier%", "Cash", "Loan"]
    if active_only:
        filters.append("p.status = 'Active'")
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

    rows = db.execute(
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
            COALESCE(profile.supplier_mode, 'Cash') AS supplier_mode,
            COALESCE(asset_totals.asset_count, 0) AS asset_count,
            COALESCE(asset_totals.double_shift_count, 0) AS double_shift_count,
            COALESCE(trip_totals.trip_count, 0) AS trip_count,
            COALESCE(trip_totals.earned_total, 0) AS earned_total,
            COALESCE(debit_totals.debit_count, 0) AS debit_count,
            COALESCE(debit_totals.debit_total, 0) AS debit_total,
            COALESCE(payment_totals.payment_count, 0) AS payment_count,
            COALESCE(payment_totals.paid_total, 0) AS paid_total
        FROM parties p
        LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
        LEFT JOIN (
            SELECT
                party_code,
                COUNT(*) AS asset_count,
                SUM(CASE WHEN double_shift_mode = 'Double Shift' THEN 1 ELSE 0 END) AS double_shift_count
            FROM supplier_assets
            GROUP BY party_code
        ) asset_totals ON asset_totals.party_code = p.party_code
        LEFT JOIN (
            SELECT
                party_code,
                COUNT(*) AS trip_count,
                COALESCE(SUM(total_amount), 0) AS earned_total
            FROM cash_supplier_trips
            GROUP BY party_code
        ) trip_totals ON trip_totals.party_code = p.party_code
        LEFT JOIN (
            SELECT
                party_code,
                COUNT(*) AS debit_count,
                COALESCE(SUM(amount), 0) AS debit_total
            FROM cash_supplier_debits
            GROUP BY party_code
        ) debit_totals ON debit_totals.party_code = p.party_code
        LEFT JOIN (
            SELECT
                party_code,
                COUNT(*) AS payment_count,
                COALESCE(SUM(amount), 0) AS paid_total
            FROM cash_supplier_payments
            GROUP BY party_code
        ) payment_totals ON payment_totals.party_code = p.party_code
        WHERE {" AND ".join(filters)}
        """,
        params,
    ).fetchall()

    prepared_rows = []
    for row in rows:
        item = dict(row)
        item["asset_count"] = int(item.get("asset_count") or 0)
        item["double_shift_count"] = int(item.get("double_shift_count") or 0)
        item["trip_count"] = int(item.get("trip_count") or 0)
        item["debit_count"] = int(item.get("debit_count") or 0)
        item["payment_count"] = int(item.get("payment_count") or 0)
        item["earned_total"] = round(float(item.get("earned_total") or 0.0), 2)
        item["debit_total"] = round(float(item.get("debit_total") or 0.0), 2)
        item["paid_total"] = round(float(item.get("paid_total") or 0.0), 2)
        item["closing_balance"] = round(item["earned_total"] - item["debit_total"] - item["paid_total"], 2)
        balance_label, balance_state, display_balance_amount = _cash_supplier_balance_meta(item["closing_balance"])
        item["balance_label"] = balance_label
        item["balance_state"] = balance_state
        item["display_balance_amount"] = round(display_balance_amount, 2)
        prepared_rows.append(item)

    prepared_rows.sort(
        key=lambda item: (
            0 if item.get("status") == "Active" else 1,
            0 if item.get("balance_state") == "due" else 1 if item.get("balance_state") == "advance" else 2,
            -abs(float(item.get("closing_balance") or 0.0)),
            str(item.get("party_name") or "").lower(),
        )
    )
    if limit:
        return prepared_rows[: int(limit)]
    return prepared_rows


def _cash_supplier_directory_summary(rows) -> dict:
    directory_rows = list(rows or [])
    return {
        "supplier_count": len(directory_rows),
        "asset_count": sum(int(item.get("asset_count") or 0) for item in directory_rows),
        "double_shift_count": sum(int(item.get("double_shift_count") or 0) for item in directory_rows),
        "trip_count": sum(int(item.get("trip_count") or 0) for item in directory_rows),
        "debit_count": sum(int(item.get("debit_count") or 0) for item in directory_rows),
        "payment_count": sum(int(item.get("payment_count") or 0) for item in directory_rows),
        "total_earned": round(sum(float(item.get("earned_total") or 0.0) for item in directory_rows), 2),
        "total_debits": round(sum(float(item.get("debit_total") or 0.0) for item in directory_rows), 2),
        "total_paid": round(sum(float(item.get("paid_total") or 0.0) for item in directory_rows), 2),
        "outstanding_total": round(sum(max(float(item.get("closing_balance") or 0.0), 0.0) for item in directory_rows), 2),
        "advance_total": round(sum(max(-(float(item.get("closing_balance") or 0.0)), 0.0) for item in directory_rows), 2),
        "settled_count": sum(1 for item in directory_rows if item.get("balance_state") == "settled"),
    }


def _supplier_directory_rows(db, query: str = "", limit: int | None = None, supplier_mode: str = "Normal", active_only: bool = True):
    normalized_mode = supplier_mode if supplier_mode in SUPPLIER_MODE_OPTIONS else "Normal"
    filters = ["p.party_roles LIKE ?"]
    params = ["%Supplier%"]
    filters.append("COALESCE(profile.supplier_mode, 'Normal') = ?")
    params.append(normalized_mode)
    if active_only:
        filters.append("p.status = 'Active'")
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
            COALESCE(profile.supplier_mode, 'Normal') AS supplier_mode,
            COALESCE(profile.partner_party_code, '') AS partner_party_code,
            COALESCE(profile.partner_name, '') AS partner_name,
            COALESCE(profile.default_company_share_percent, 100) AS default_company_share_percent,
            COALESCE(profile.default_partner_share_percent, 0) AS default_partner_share_percent,
            COALESCE(asset_totals.asset_count, 0) AS asset_count,
            COALESCE(asset_totals.double_shift_count, 0) AS double_shift_count,
            COALESCE(asset_totals.partnership_count, 0) AS partnership_count,
            COALESCE(ts_totals.unbilled_count, 0) AS unbilled_count,
            COALESCE(ts_totals.unbilled_amount, 0) AS unbilled_amount,
            COALESCE(voucher_totals.voucher_count, 0) AS voucher_count,
            COALESCE(voucher_totals.total_amount, 0) AS voucher_total,
            COALESCE(voucher_totals.balance_amount, 0) AS outstanding_total,
            COALESCE(payment_totals.paid_amount, 0) AS paid_total
        FROM parties p
        LEFT JOIN supplier_profile profile ON profile.party_code = p.party_code
        LEFT JOIN (
            SELECT
                party_code,
                COUNT(*) AS asset_count,
                SUM(CASE WHEN double_shift_mode = 'Double Shift' THEN 1 ELSE 0 END) AS double_shift_count,
                SUM(CASE WHEN partnership_mode = 'Partnership' THEN 1 ELSE 0 END) AS partnership_count
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
            rate_basis, default_rate, double_shift_mode, partnership_mode, partner_name,
            company_share_percent, partner_share_percent, day_shift_paid_by, night_shift_paid_by,
            capacity, status, notes
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
            paid_amount, balance_amount, status, notes, source_type, source_reference
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


def _supplier_partnership_rows(db, party_code: str, limit: int = 40):
    return db.execute(
        f"""
        SELECT
            e.entry_no,
            e.party_code,
            e.asset_code,
            a.asset_name,
            a.vehicle_no,
            e.period_month,
            e.entry_date,
            e.entry_kind,
            e.expense_head,
            e.shift_label,
            e.driver_name,
            e.paid_by,
            e.amount,
            e.notes
        FROM supplier_partnership_entries e
        LEFT JOIN supplier_assets a ON a.asset_code = e.asset_code
        WHERE e.party_code = ?
        ORDER BY e.period_month DESC, e.entry_date DESC, e.id DESC
        LIMIT {int(limit)}
        """,
        (party_code,),
    ).fetchall()


def _supplier_detail_summary(db, party_code: str):
    return {
        "asset_count": int(db.execute("SELECT COUNT(*) FROM supplier_assets WHERE party_code = ?", (party_code,)).fetchone()[0]),
        "double_shift_count": int(db.execute("SELECT COUNT(*) FROM supplier_assets WHERE party_code = ? AND double_shift_mode = 'Double Shift'", (party_code,)).fetchone()[0]),
        "partnership_count": int(db.execute("SELECT COUNT(*) FROM supplier_assets WHERE party_code = ? AND partnership_mode = 'Partnership'", (party_code,)).fetchone()[0]),
        "unbilled_count": int(db.execute("SELECT COUNT(*) FROM supplier_timesheets WHERE party_code = ? AND COALESCE(voucher_no, '') = ''", (party_code,)).fetchone()[0]),
        "unbilled_amount": float(db.execute("SELECT COALESCE(SUM(subtotal), 0) FROM supplier_timesheets WHERE party_code = ? AND COALESCE(voucher_no, '') = ''", (party_code,)).fetchone()[0] or 0.0),
        "voucher_total": float(db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM supplier_vouchers WHERE party_code = ?", (party_code,)).fetchone()[0] or 0.0),
        "paid_total": float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM supplier_payments WHERE party_code = ?", (party_code,)).fetchone()[0] or 0.0),
        "outstanding_total": float(db.execute("SELECT COALESCE(SUM(balance_amount), 0) FROM supplier_vouchers WHERE party_code = ?", (party_code,)).fetchone()[0] or 0.0),
        "open_voucher_count": int(db.execute("SELECT COUNT(*) FROM supplier_vouchers WHERE party_code = ? AND balance_amount > 0.009", (party_code,)).fetchone()[0]),
    }


def _supplier_statement_data(db, party_code: str, supplier_mode: str = "Normal"):
    if supplier_mode in ("Normal", "Managed"):
        rows = [item for item in _supplier_submission_rows(db, party_code, limit=200) if item["status_bucket"] != "rejected"]
        summary = {
            "all_submitted": round(sum(item["total_amount"] for item in rows), 2),
            "approved_total": round(sum(item["total_amount"] for item in rows if item["status_bucket"] == "approved"), 2),
            "approved_outstanding": round(
                sum(
                    item["balance_amount_display"]
                    for item in rows
                    if item["status_bucket"] == "approved"
                ),
                2,
            ),
            "pending_submitted": round(sum(item["total_amount"] for item in rows if item["status_bucket"] == "pending"), 2),
            "total_paid": round(sum(item["paid_amount_display"] for item in rows if item["status_bucket"] == "approved"), 2),
        }
        return rows, summary

    # Cash/Loan suppliers use the dedicated kata view — statement is not applicable
    if supplier_mode in ("Cash", "Loan"):
        return [], {
            "work_logged": 0.0, "total_vouchers": 0.0,
            "total_paid": 0.0, "outstanding": 0.0,
        }

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


def _statement_pdf_date(value: str) -> str:
    if not value:
        return ""
    for pattern in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(str(value), pattern).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return str(value)


def _statement_pdf_month(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.strptime(str(value), "%Y-%m").strftime("%b-%y")
    except ValueError:
        return str(value)


def _statement_pdf_quantity(value) -> str:
    number = float(value or 0.0)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _statement_pdf_amount(value) -> str:
    return f"{float(value or 0.0):.2f}"


def _cash_supplier_kata(db, party_code: str):
    """Build a running statement (kata) for a cash supplier.

    Returns (rows, summary) where each row has:
      entry_date, reference, entry_type, description,
      earned, debit, paid, running_balance
    """
    rows = []

    # 1. Trip earnings (credit to supplier)
    trips = db.execute("""
        SELECT trip_no, entry_date, period_month, earning_basis, trip_count, rate, total_amount, vehicle_no, notes
        FROM cash_supplier_trips
        WHERE party_code = ?
        ORDER BY entry_date ASC, id ASC
    """, (party_code,)).fetchall()
    for row in trips:
        earning_basis = row["earning_basis"] or "Trips"
        period_month = row["period_month"] or ""
        quantity_label = {
            "Trips": "Trips",
            "Hours": "Hours",
            "Monthly": "Months",
            "Fixed": "Units",
        }.get(earning_basis, earning_basis)
        rate_label = {
            "Trips": "Rate/Trip",
            "Hours": "Rate/Hour",
            "Monthly": "Rate/Month",
            "Fixed": "Rate/Unit",
        }.get(earning_basis, "Rate")
        period_text = format_month_label(period_month) if period_month else "-"
        details = [f"{quantity_label}: {row['trip_count']}", f"{rate_label}: {row['rate']}"]
        if period_month:
            details.append(f"Month: {period_text}")
        if row["vehicle_no"]:
            details.append(str(row["vehicle_no"]))
        if row["notes"]:
            details.append(str(row["notes"]))
        rows.append({
            "entry_date": row["entry_date"],
            "period_month": period_month,
            "period_month_display": period_text,
            "reference": row["trip_no"],
            "entry_type": "Earning",
            "earning_basis": earning_basis,
            "description": " / ".join(details),
            "pdf_date": _statement_pdf_date(row["entry_date"]),
            "pdf_vehicle_no": str(row["vehicle_no"] or ""),
            "pdf_month_label": _statement_pdf_month(period_month) if period_month else "",
            "pdf_qty_or_note": _statement_pdf_quantity(row["trip_count"]),
            "pdf_rate": _statement_pdf_amount(row["rate"]),
            "pdf_total_amount": _statement_pdf_amount(row["total_amount"]),
            "pdf_paid_amount": "",
            "pdf_balance": "",
            "pdf_row_kind": "earning",
            "earned": float(row["total_amount"] or 0.0),
            "debit": 0.0,
            "paid": 0.0,
        })

    # 2. Debit items (advance, loan, visa, transfer, etc.)
    debits = db.execute("""
        SELECT debit_no, entry_date, debit_type, amount, description, notes
        FROM cash_supplier_debits
        WHERE party_code = ?
        ORDER BY entry_date ASC, id ASC
    """, (party_code,)).fetchall()
    for row in debits:
        debit_text = row["description"] or row["debit_type"] or "Debit"
        if row["notes"]:
            debit_text = f"{debit_text} / {row['notes']}"
        rows.append({
            "entry_date": row["entry_date"],
            "period_month": "",
            "period_month_display": "-",
            "reference": row["debit_no"],
            "entry_type": row["debit_type"] or "Debit",
            "earning_basis": "",
            "description": debit_text,
            "pdf_date": _statement_pdf_date(row["entry_date"]),
            "pdf_vehicle_no": "",
            "pdf_month_label": "",
            "pdf_qty_or_note": debit_text,
            "pdf_rate": "",
            "pdf_total_amount": _statement_pdf_amount(row["amount"]),
            "pdf_paid_amount": "",
            "pdf_balance": "",
            "pdf_row_kind": "debit",
            "earned": 0.0,
            "debit": float(row["amount"] or 0.0),
            "paid": 0.0,
        })

    # 3. Cash payments (paid to supplier)
    payments = db.execute("""
        SELECT payment_no, entry_date, amount, payment_method, reference, notes
        FROM cash_supplier_payments
        WHERE party_code = ?
        ORDER BY entry_date ASC, id ASC
    """, (party_code,)).fetchall()
    for row in payments:
        payment_note = (row["notes"] or "").strip() or (row["reference"] or "").strip() or (row["payment_method"] or "Payment").strip()
        rows.append({
            "entry_date": row["entry_date"],
            "period_month": "",
            "period_month_display": "-",
            "reference": row["payment_no"],
            "entry_type": "Payment",
            "earning_basis": "",
            "description": (row["payment_method"] or "Cash") + (f" / Ref: {row['reference']}" if row["reference"] else "") + (f" / {row['notes']}" if row["notes"] else ""),
            "pdf_date": _statement_pdf_date(row["entry_date"]),
            "pdf_vehicle_no": "",
            "pdf_month_label": "",
            "pdf_qty_or_note": payment_note,
            "pdf_rate": "",
            "pdf_total_amount": "",
            "pdf_paid_amount": _statement_pdf_amount(row["amount"]),
            "pdf_balance": "",
            "pdf_row_kind": "payment",
            "earned": 0.0,
            "debit": 0.0,
            "paid": float(row["amount"] or 0.0),
        })

    # Sort chronologically
    sort_order = {"Earning": 0, "Advance": 1, "Loan": 1, "Visa": 1, "Transfer": 1, "Debit": 1, "Other": 1, "Payment": 2}
    rows.sort(key=lambda item: (item["entry_date"], sort_order.get(item["entry_type"], 1), item["reference"]))

    # Running balance: earned builds up, debits add to owed, payments reduce owed
    # Balance = (total_earned) - (total_debits) - (total_paid)
    #   positive = supplier is owed money
    #   negative = supplier owes money (has advances)
    running = 0.0
    for item in rows:
        running += item["earned"]
        running -= item["debit"]
        running -= item["paid"]
        item["running_balance"] = round(running, 2)
        item["pdf_balance"] = _statement_pdf_amount(item["running_balance"])

    total_earned = round(sum(r["earned"] for r in rows), 2)
    total_debits = round(sum(r["debit"] for r in rows), 2)
    total_paid = round(sum(r["paid"] for r in rows), 2)

    summary = {
        "total_earned": total_earned,
        "total_debits": total_debits,
        "total_paid": total_paid,
        "balance": round(total_earned - total_debits - total_paid, 2),
    }
    return rows, summary


def _cash_supplier_kata_entry_group(row: dict) -> str:
    entry_type = str(row.get("entry_type") or "").strip()
    if entry_type == "Earning":
        return "earning"
    if entry_type == "Payment":
        return "payment"
    return "debit"


def _cash_supplier_kata_summary(rows) -> dict:
    rows = list(rows or [])
    total_earned = round(sum(float(item.get("earned") or 0.0) for item in rows), 2)
    total_debits = round(sum(float(item.get("debit") or 0.0) for item in rows), 2)
    total_paid = round(sum(float(item.get("paid") or 0.0) for item in rows), 2)
    return {
        "total_earned": total_earned,
        "total_debits": total_debits,
        "total_paid": total_paid,
        "balance": round(total_earned - total_debits - total_paid, 2),
    }


def _filter_cash_supplier_kata_rows(rows, *, month_filter: str = "", type_filter: str = "all", search_text: str = ""):
    filtered_rows = []
    type_value = (type_filter or "all").strip().lower()
    if type_value not in {item[0] for item in SUPPLIER_CASH_KATA_TYPE_OPTIONS}:
        type_value = "all"
    search_value = (search_text or "").strip().lower()

    for row in rows or []:
        entry_group = _cash_supplier_kata_entry_group(row)
        entry_month = str(row.get("period_month") or "").strip() or str(row.get("entry_date") or "")[:7]
        if month_filter and entry_month != month_filter:
            continue
        if type_value != "all" and entry_group != type_value:
            continue
        if search_value:
            haystack = " ".join(
                [
                    str(row.get("entry_date") or ""),
                    str(row.get("period_month_display") or ""),
                    str(row.get("reference") or ""),
                    str(row.get("entry_type") or ""),
                    str(row.get("earning_basis") or ""),
                    str(row.get("description") or ""),
                    f"{float(row.get('earned') or 0.0):.2f}",
                    f"{float(row.get('debit') or 0.0):.2f}",
                    f"{float(row.get('paid') or 0.0):.2f}",
                    f"{float(row.get('running_balance') or 0.0):.2f}",
                ]
            ).lower()
            if search_value not in haystack:
                continue
        filtered_rows.append(row)

    return filtered_rows


def _supplier_partnership_summary(db, party_code: str, period_month: str):
    month_value = _normalize_month(period_month)
    work_total = float(
        db.execute(
            """
            SELECT COALESCE(SUM(subtotal), 0)
            FROM supplier_timesheets
            WHERE party_code = ? AND period_month = ?
            """,
            (party_code, month_value),
        ).fetchone()[0]
        or 0.0
    )
    company_paid = float(
        db.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM supplier_partnership_entries
            WHERE party_code = ? AND period_month = ? AND paid_by = 'Company'
            """,
            (party_code, month_value),
        ).fetchone()[0]
        or 0.0
    )
    partner_paid = float(
        db.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM supplier_partnership_entries
            WHERE party_code = ? AND period_month = ? AND paid_by = 'Partner'
            """,
            (party_code, month_value),
        ).fetchone()[0]
        or 0.0
    )
    company_salary = float(
        db.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM supplier_partnership_entries
            WHERE party_code = ? AND period_month = ? AND paid_by = 'Company' AND entry_kind = 'Driver Salary'
            """,
            (party_code, month_value),
        ).fetchone()[0]
        or 0.0
    )
    partner_salary = float(
        db.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM supplier_partnership_entries
            WHERE party_code = ? AND period_month = ? AND paid_by = 'Partner' AND entry_kind = 'Driver Salary'
            """,
            (party_code, month_value),
        ).fetchone()[0]
        or 0.0
    )
    company_maintenance = float(
        db.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM supplier_partnership_entries
            WHERE party_code = ? AND period_month = ? AND paid_by = 'Company' AND entry_kind = 'Vehicle Expense'
            """,
            (party_code, month_value),
        ).fetchone()[0]
        or 0.0
    )
    partner_maintenance = float(
        db.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM supplier_partnership_entries
            WHERE party_code = ? AND period_month = ? AND paid_by = 'Partner' AND entry_kind = 'Vehicle Expense'
            """,
            (party_code, month_value),
        ).fetchone()[0]
        or 0.0
    )
    total_salary_cost = round(company_salary + partner_salary, 2)
    total_maintenance_cost = round(company_maintenance + partner_maintenance, 2)
    total_cost = round(company_paid + partner_paid, 2)
    net_profit = round(work_total - total_cost, 2)
    company_profit_share = round(net_profit * 0.5, 2)
    partner_profit_share = round(net_profit * 0.5, 2)
    return {
        "period_month": month_value,
        "work_total": work_total,
        "company_paid": company_paid,
        "partner_paid": partner_paid,
        "company_salary": company_salary,
        "partner_salary": partner_salary,
        "company_maintenance": company_maintenance,
        "partner_maintenance": partner_maintenance,
        "total_salary_cost": total_salary_cost,
        "total_maintenance_cost": total_maintenance_cost,
        "total_cost": total_cost,
        "net_profit": net_profit,
        "company_profit_share": company_profit_share,
        "partner_profit_share": partner_profit_share,
        "company_should_receive": round(company_profit_share + company_paid, 2),
        "partner_should_receive": round(partner_profit_share + partner_paid, 2),
    }


def _supplier_partnership_asset_rows(db, party_code: str, period_month: str):
    month_value = _normalize_month(period_month)
    assets = db.execute(
        """
        SELECT
            asset_code,
            asset_name,
            vehicle_no,
            double_shift_mode,
            partnership_mode,
            partner_name,
            company_share_percent,
            partner_share_percent,
            day_shift_paid_by,
            night_shift_paid_by
        FROM supplier_assets
        WHERE party_code = ?
        ORDER BY asset_name ASC, asset_code ASC
        """,
        (party_code,),
    ).fetchall()
    rows = []
    for asset in assets:
        work_total = float(
            db.execute(
                """
                SELECT COALESCE(SUM(subtotal), 0)
                FROM supplier_timesheets
                WHERE party_code = ? AND asset_code = ? AND period_month = ?
                """,
                (party_code, asset["asset_code"], month_value),
            ).fetchone()[0]
            or 0.0
        )
        company_paid = float(
            db.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM supplier_partnership_entries
                WHERE party_code = ? AND asset_code = ? AND period_month = ? AND paid_by = 'Company'
                """,
                (party_code, asset["asset_code"], month_value),
            ).fetchone()[0]
            or 0.0
        )
        partner_paid = float(
            db.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM supplier_partnership_entries
                WHERE party_code = ? AND asset_code = ? AND period_month = ? AND paid_by = 'Partner'
                """,
                (party_code, asset["asset_code"], month_value),
            ).fetchone()[0]
            or 0.0
        )
        company_salary = float(
            db.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM supplier_partnership_entries
                WHERE party_code = ? AND asset_code = ? AND period_month = ? AND paid_by = 'Company' AND entry_kind = 'Driver Salary'
                """,
                (party_code, asset["asset_code"], month_value),
            ).fetchone()[0]
            or 0.0
        )
        partner_salary = float(
            db.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM supplier_partnership_entries
                WHERE party_code = ? AND asset_code = ? AND period_month = ? AND paid_by = 'Partner' AND entry_kind = 'Driver Salary'
                """,
                (party_code, asset["asset_code"], month_value),
            ).fetchone()[0]
            or 0.0
        )
        company_share_percent = float(asset["company_share_percent"] or 100.0)
        partner_share_percent = float(asset["partner_share_percent"] or 0.0)
        if (asset["partnership_mode"] or "Standard") != "Partnership":
            company_share_percent = 100.0
            partner_share_percent = 0.0
        company_maintenance = float(
            db.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM supplier_partnership_entries
                WHERE party_code = ? AND asset_code = ? AND period_month = ? AND paid_by = 'Company' AND entry_kind = 'Vehicle Expense'
                """,
                (party_code, asset["asset_code"], month_value),
            ).fetchone()[0]
            or 0.0
        )
        partner_maintenance = float(
            db.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM supplier_partnership_entries
                WHERE party_code = ? AND asset_code = ? AND period_month = ? AND paid_by = 'Partner' AND entry_kind = 'Vehicle Expense'
                """,
                (party_code, asset["asset_code"], month_value),
            ).fetchone()[0]
            or 0.0
        )
        total_salary_cost = round(company_salary + partner_salary, 2)
        total_maintenance_cost = round(company_maintenance + partner_maintenance, 2)
        total_cost = round(company_paid + partner_paid, 2)
        net_profit = round(work_total - total_cost, 2)
        company_share_amount = round(net_profit * (company_share_percent / 100.0), 2)
        partner_share_amount = round(net_profit * (partner_share_percent / 100.0), 2)
        rows.append(
            {
                "asset_code": asset["asset_code"],
                "asset_name": asset["asset_name"],
                "vehicle_no": asset["vehicle_no"],
                "double_shift_mode": asset["double_shift_mode"] or SUPPLIER_SHIFT_MODE_OPTIONS[0],
                "partnership_mode": asset["partnership_mode"] or SUPPLIER_PARTNERSHIP_MODE_OPTIONS[0],
                "partner_name": asset["partner_name"] or "-",
                "company_share_percent": company_share_percent,
                "partner_share_percent": partner_share_percent,
                "day_shift_paid_by": asset["day_shift_paid_by"] or PARTNERSHIP_PAID_BY_OPTIONS[0],
                "night_shift_paid_by": asset["night_shift_paid_by"] or PARTNERSHIP_PAID_BY_OPTIONS[0],
                "work_total": work_total,
                "company_paid": company_paid,
                "partner_paid": partner_paid,
                "company_salary": company_salary,
                "partner_salary": partner_salary,
                "company_maintenance": company_maintenance,
                "partner_maintenance": partner_maintenance,
                "total_salary_cost": total_salary_cost,
                "total_maintenance_cost": total_maintenance_cost,
                "total_cost": total_cost,
                "net_profit": net_profit,
                "company_share_amount": company_share_amount,
                "partner_share_amount": partner_share_amount,
                "company_should_receive": round(company_share_amount + company_paid, 2),
                "partner_should_receive": round(partner_share_amount + partner_paid, 2),
            }
        )
    return rows


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


def _cash_supplier_payment_with_context(db, payment_no: str):
    payment = db.execute(
        """
        SELECT
            pay.payment_no,
            pay.party_code,
            pay.entry_date,
            pay.amount,
            pay.payment_method,
            pay.reference,
            pay.notes,
            pay.created_by,
            party.party_name,
            party.contact_person,
            party.phone_number,
            COALESCE(profile.supplier_mode, 'Cash') AS supplier_mode
        FROM cash_supplier_payments pay
        LEFT JOIN parties party ON party.party_code = pay.party_code
        LEFT JOIN supplier_profile profile ON profile.party_code = pay.party_code
        WHERE pay.payment_no = ?
        """,
        (payment_no,),
    ).fetchone()
    if payment is None:
        return None
    summary = {
        "total_earned": float(db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM cash_supplier_trips WHERE party_code = ?", (payment["party_code"],)).fetchone()[0] or 0.0),
        "total_debits": float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM cash_supplier_debits WHERE party_code = ?", (payment["party_code"],)).fetchone()[0] or 0.0),
        "total_paid": float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM cash_supplier_payments WHERE party_code = ?", (payment["party_code"],)).fetchone()[0] or 0.0),
    }
    summary["balance"] = round(summary["total_earned"] - summary["total_debits"] - summary["total_paid"], 2)
    return {**dict(payment), **summary}


def _ensure_supplier_payment_voucher_pdf(app, db, payment_no: str) -> str:
    payment = _supplier_payment_with_context(db, payment_no)
    if payment is None:
        raise ValidationError("Supplier payment voucher was not found.")
    output_dir = _supplier_output_dir(app, payment["party_code"]) / "payment_vouchers"
    pdf_path = generate_supplier_payment_voucher_pdf(payment, payment, payment, str(output_dir), app.config["STATIC_ASSETS_DIR"])
    _mirror_generated_file(app, pdf_path)
    return pdf_path


def _ensure_cash_supplier_payment_voucher_pdf(app, db, payment_no: str) -> str:
    payment = _cash_supplier_payment_with_context(db, payment_no)
    if payment is None:
        raise ValidationError("Cash supplier payment voucher was not found.")
    output_dir = _supplier_output_dir(app, payment["party_code"]) / "payment_vouchers"
    pdf_path = generate_cash_supplier_payment_voucher_pdf(payment, payment, payment, str(output_dir), app.config["STATIC_ASSETS_DIR"])
    _mirror_generated_file(app, pdf_path)
    return pdf_path


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
    quotation_no = values.get("quotation_no", "").strip().upper()
    if quotation_no:
        quotation_row = _supplier_quotation_row(db, quotation_no)
        if quotation_row is None:
            raise ValidationError("Select a valid approved quotation.")
        if quotation_row["party_code"] != values["party_code"]:
            raise ValidationError("LPO supplier and quotation supplier must match.")
        if (quotation_row["review_status"] or "") != "Approved":
            raise ValidationError("Only approved quotations can be issued as LPO.")
    agreement_no = _optional_reference_exists(db, "agreements", "agreement_no", values["agreement_no"], "Agreement")
    issue_date = _validate_date_text(values["issue_date"], "LPO issue date")
    valid_until = _validate_date_text(values["valid_until"], "LPO valid until", required=False)
    amount = _parse_decimal(values["amount"], "LPO amount", required=False, default=0.0, minimum=0.0)
    tax_percent = _parse_decimal(values["tax_percent"], "LPO tax percent", required=False, default=0.0, minimum=0.0)
    return (values["lpo_no"], values["party_code"], quotation_no or None, agreement_no or None, issue_date, valid_until or None, amount, tax_percent, values["description"], values["status"])


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
    return db.execute(f"SELECT l.lpo_no, l.party_code, p.party_name, l.quotation_no, l.agreement_no, l.issue_date, l.valid_until, l.amount, l.tax_percent, l.status, l.description FROM lpos l LEFT JOIN parties p ON p.party_code = l.party_code ORDER BY l.issue_date DESC, l.id DESC LIMIT {int(limit)}").fetchall()


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


def _fleet_maintenance_filter_values(request):
    month_value = request.args.get("month", "").strip() or request.form.get("month", "").strip() or _current_month_value()
    funding_source = request.args.get("funding_source", "").strip() or request.form.get("funding_source", "").strip()
    if funding_source and funding_source not in MAINTENANCE_FUNDING_SOURCE_OPTIONS:
        funding_source = ""
    return {
        "month": _normalize_month(month_value) if month_value else _current_month_value(),
        "vehicle_id": request.args.get("vehicle_id", "").strip().upper() or request.form.get("vehicle_id", "").strip().upper(),
        "funding_source": funding_source,
        "search": request.args.get("search", "").strip() or request.form.get("search", "").strip(),
    }


def _fleet_maintenance_screen_value(value: str) -> str:
    selected = (value or "").strip().lower()
    if selected in {"overview", "vehicles", "import", "papers"}:
        return selected
    return "overview"


def _maintenance_paper_filter_clause(filters):
    clauses = []
    params = []
    if filters.get("month"):
        clauses.append("SUBSTR(p.paper_date, 1, 7) = ?")
        params.append(filters["month"])
    if filters.get("vehicle_id"):
        clauses.append("p.vehicle_id = ?")
        params.append(filters["vehicle_id"])
    if filters.get("funding_source"):
        clauses.append("p.funding_source = ?")
        params.append(filters["funding_source"])
    if filters.get("search"):
        needle = f"%{filters['search'].lower()}%"
        clauses.append(
            """
            (
                LOWER(COALESCE(p.paper_no, '')) LIKE ? OR
                LOWER(COALESCE(p.vehicle_no, '')) LIKE ? OR
                LOWER(COALESCE(p.work_summary, '')) LIKE ? OR
                LOWER(COALESCE(p.supplier_bill_no, '')) LIKE ? OR
                LOWER(COALESCE(workshop.party_name, '')) LIKE ? OR
                LOWER(COALESCE(staff.staff_name, '')) LIKE ?
            )
            """
        )
        params.extend([needle] * 6)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _fleet_maintenance_summary(db, month_value: str):
    month_total = float(
        db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM maintenance_papers WHERE SUBSTR(paper_date, 1, 7) = ?", (month_value,)).fetchone()[0]
        or 0.0
    )
    month_tax = float(
        db.execute("SELECT COALESCE(SUM(tax_amount), 0) FROM maintenance_papers WHERE SUBSTR(paper_date, 1, 7) = ?", (month_value,)).fetchone()[0]
        or 0.0
    )
    month_papers = int(
        db.execute("SELECT COUNT(*) FROM maintenance_papers WHERE SUBSTR(paper_date, 1, 7) = ?", (month_value,)).fetchone()[0]
        or 0
    )
    return {
        "vehicle_count": int(db.execute("SELECT COUNT(*) FROM vehicle_master WHERE COALESCE(source_type, 'Own Fleet Vehicle') = 'Own Fleet Vehicle'").fetchone()[0]),
        "partnership_count": int(db.execute("SELECT COUNT(*) FROM vehicle_master WHERE COALESCE(source_type, '') = 'Partnership Supplier Vehicle'").fetchone()[0]),
        "double_shift_count": int(db.execute("SELECT COUNT(*) FROM vehicle_master WHERE shift_mode = 'Double Shift'").fetchone()[0]),
        "open_advance_balance": float(db.execute("SELECT COALESCE(SUM(balance_amount), 0) FROM maintenance_staff_advances").fetchone()[0] or 0.0),
        "workshop_credit_balance": float(
            db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM maintenance_settlements WHERE settlement_type = 'Workshop Credit' AND status = 'Open'"
            ).fetchone()[0]
            or 0.0
        ),
        "month_total": month_total,
        "month_tax": month_tax,
        "month_papers": month_papers,
    }


def _fleet_vehicle_rows(db):
    return db.execute(
        """
        SELECT
            v.vehicle_id,
            v.vehicle_no,
            v.vehicle_type,
            v.make_model,
            v.status,
            v.shift_mode,
            v.ownership_mode,
            v.source_type,
            v.source_party_code,
            v.source_asset_code,
            COALESCE(partner.party_name, v.partner_name) AS partner_name,
            v.company_share_percent,
            v.partner_share_percent,
            v.notes
        FROM vehicle_master v
        LEFT JOIN parties partner ON partner.party_code = v.partner_party_code
        WHERE COALESCE(v.source_type, 'Own Fleet Vehicle') = 'Own Fleet Vehicle'
        ORDER BY CASE WHEN v.status = 'Active' THEN 0 ELSE 1 END, v.vehicle_no ASC, v.id DESC
        """
    ).fetchall()


def _fleet_vehicle_directory_rows(db, filters):
    clauses = []
    params = []
    if filters.get("vehicle_id"):
        clauses.append("v.vehicle_id = ?")
        params.append(filters["vehicle_id"])
    if filters.get("search"):
        needle = f"%{filters['search'].lower()}%"
        clauses.append(
            """
            (
                LOWER(COALESCE(v.vehicle_id, '')) LIKE ? OR
                LOWER(COALESCE(v.vehicle_no, '')) LIKE ? OR
                LOWER(COALESCE(v.vehicle_type, '')) LIKE ? OR
                LOWER(COALESCE(v.make_model, '')) LIKE ? OR
                LOWER(COALESCE(partner.party_name, v.partner_name, '')) LIKE ?
            )
            """
        )
        params.extend([needle] * 5)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return db.execute(
        f"""
        SELECT
            v.vehicle_id,
            v.vehicle_no,
            v.vehicle_type,
            v.make_model,
            v.status,
            v.shift_mode,
            v.ownership_mode,
            COALESCE(v.source_type, 'Own Fleet Vehicle') AS source_type,
            COALESCE(partner.party_name, v.partner_name) AS partner_name
        FROM vehicle_master v
        LEFT JOIN parties partner ON partner.party_code = v.partner_party_code
        {where_sql}
        ORDER BY
            CASE WHEN COALESCE(v.ownership_mode, 'Company') = 'Partnership' THEN 0 ELSE 1 END,
            CASE WHEN v.status = 'Active' THEN 0 ELSE 1 END,
            v.vehicle_no ASC,
            v.id DESC
        """,
        params,
    ).fetchall()


def _maintenance_target_vehicle_rows(db):
    return db.execute(
        """
        SELECT
            v.vehicle_id,
            v.vehicle_no,
            v.vehicle_type,
            v.shift_mode,
            COALESCE(v.source_type, 'Own Fleet Vehicle') AS source_type
        FROM vehicle_master v
        ORDER BY
            CASE WHEN COALESCE(v.source_type, 'Own Fleet Vehicle') = 'Own Fleet Vehicle' THEN 0 ELSE 1 END,
            v.vehicle_no ASC,
            v.id DESC
        """
    ).fetchall()


def _maintenance_paper_row(db, paper_no: str, *, required: bool = False):
    row = db.execute(
        """
        SELECT *
        FROM maintenance_papers
        WHERE paper_no = ?
        """,
        (paper_no,),
    ).fetchone()
    if row is None and required:
        raise ValidationError("Maintenance paper was not found.")
    return row


def _reverse_maintenance_paper_effects(db, paper_row):
    settlement_rows = db.execute(
        """
        SELECT settlement_type, advance_no, amount
        FROM maintenance_settlements
        WHERE paper_no = ?
        ORDER BY id ASC
        """,
        (paper_row["paper_no"],),
    ).fetchall()
    for settlement in settlement_rows:
        if settlement["settlement_type"] == "Technician Advance" and settlement["advance_no"]:
            advance_row = _maintenance_advance_row(db, settlement["advance_no"])
            if advance_row is None:
                continue
            new_settled = max(round(float(advance_row["settled_amount"] or 0.0) - float(settlement["amount"] or 0.0), 2), 0.0)
            new_balance = round(float(advance_row["amount"] or 0.0) - new_settled, 2)
            db.execute(
                """
                UPDATE maintenance_staff_advances
                SET settled_amount = ?, balance_amount = ?
                WHERE advance_no = ?
                """,
                (new_settled, max(new_balance, 0.0), settlement["advance_no"]),
            )
    db.execute("DELETE FROM maintenance_settlements WHERE paper_no = ?", (paper_row["paper_no"],))
    if paper_row["linked_partnership_entry_no"]:
        db.execute(
            "DELETE FROM supplier_partnership_entries WHERE entry_no = ?",
            (paper_row["linked_partnership_entry_no"],),
        )
    db.execute("DELETE FROM maintenance_paper_lines WHERE paper_no = ?", (paper_row["paper_no"],))


def _delete_maintenance_paper_record(db, app, paper_row):
    _reverse_maintenance_paper_effects(db, paper_row)
    attachment_path = (paper_row["attachment_path"] or "").strip() if paper_row else ""
    db.execute("DELETE FROM maintenance_papers WHERE paper_no = ?", (paper_row["paper_no"],))
    if _maintenance_paper_row(db, paper_row["paper_no"]) is not None:
        raise ValidationError(f"Maintenance paper {paper_row['paper_no']} could not be deleted.")
    if attachment_path:
        try:
            attachment_file = Path(app.config["GENERATED_DIR"]) / attachment_path
            attachment_file = attachment_file.resolve()
            generated_root = Path(app.config["GENERATED_DIR"]).resolve()
            if generated_root in attachment_file.parents and attachment_file.exists():
                attachment_file.unlink()
        except OSError:
            pass


def _maintenance_staff_rows(db):
    return db.execute(
        """
        SELECT
            staff.staff_code,
            staff.staff_name,
            staff.phone_number,
            staff.status,
            staff.notes,
            COALESCE(ledger.given_amount, 0) AS given_amount,
            COALESCE(ledger.settled_amount, 0) AS settled_amount,
            COALESCE(ledger.balance_amount, 0) AS balance_amount
        FROM maintenance_staff staff
        LEFT JOIN (
            SELECT
                staff_code,
                COALESCE(SUM(amount), 0) AS given_amount,
                COALESCE(SUM(settled_amount), 0) AS settled_amount,
                COALESCE(SUM(balance_amount), 0) AS balance_amount
            FROM maintenance_staff_advances
            GROUP BY staff_code
        ) ledger ON ledger.staff_code = staff.staff_code
        ORDER BY CASE WHEN staff.status = 'Active' THEN 0 ELSE 1 END, staff.staff_name ASC
        """
    ).fetchall()


def _maintenance_staff_ledger_rows(db):
    return db.execute(
        """
        SELECT
            staff.staff_code,
            staff.staff_name,
            COALESCE(SUM(adv.amount), 0) AS given_amount,
            COALESCE(SUM(adv.settled_amount), 0) AS settled_amount,
            COALESCE(SUM(adv.balance_amount), 0) AS balance_amount
        FROM maintenance_staff staff
        LEFT JOIN maintenance_staff_advances adv ON adv.staff_code = staff.staff_code
        GROUP BY staff.staff_code, staff.staff_name
        HAVING COALESCE(SUM(adv.amount), 0) > 0 OR COUNT(adv.id) > 0
        ORDER BY COALESCE(SUM(adv.balance_amount), 0) DESC, staff.staff_name ASC
        """
    ).fetchall()


def _maintenance_advance_rows(db, limit: int = 20):
    return db.execute(
        f"""
        SELECT
            adv.advance_no,
            adv.staff_code,
            staff.staff_name,
            adv.entry_date,
            adv.funding_source,
            adv.amount,
            adv.settled_amount,
            adv.balance_amount,
            adv.reference,
            adv.notes
        FROM maintenance_staff_advances adv
        LEFT JOIN maintenance_staff staff ON staff.staff_code = adv.staff_code
        ORDER BY adv.entry_date DESC, adv.id DESC
        LIMIT {int(limit)}
        """
    ).fetchall()


def _maintenance_paper_rows(db, filters, limit: int = 18):
    where_sql, params = _maintenance_paper_filter_clause(filters)
    return db.execute(
        f"""
        SELECT
            p.paper_no,
            p.paper_date,
            p.vehicle_id,
            p.vehicle_no,
            p.target_class,
            p.target_party_code,
            p.target_asset_code,
            vehicle.vehicle_type,
            vehicle.shift_mode,
            vehicle.ownership_mode,
            COALESCE(workshop.party_name, '-') AS workshop_name,
            COALESCE(staff.staff_name, '-') AS staff_name,
            p.tax_mode,
            p.supplier_bill_no,
            p.work_summary,
            p.funding_source,
            p.paid_by,
            p.subtotal,
            p.tax_amount,
            p.total_amount,
            p.company_share_amount,
            p.partner_share_amount,
            p.company_paid_amount,
            p.partner_paid_amount,
            p.linked_partnership_entry_no,
            p.attachment_path,
            p.notes
        FROM maintenance_papers p
        LEFT JOIN vehicle_master vehicle ON vehicle.vehicle_id = p.vehicle_id
        LEFT JOIN parties workshop ON workshop.party_code = p.workshop_party_code
        LEFT JOIN maintenance_staff staff ON staff.staff_code = p.staff_code
        {where_sql}
        ORDER BY p.paper_date DESC, p.id DESC
        LIMIT {int(limit)}
        """,
        params,
    ).fetchall()


def _maintenance_workshop_payables(db, filters):
    where_sql, params = _maintenance_paper_filter_clause(filters)
    prefix = " AND " if where_sql else " WHERE "
    return db.execute(
        f"""
        SELECT
            settlement.party_code,
            COALESCE(workshop.party_name, settlement.party_code, 'Workshop') AS party_name,
            COUNT(*) AS paper_count,
            COALESCE(SUM(settlement.amount), 0) AS balance_amount
        FROM maintenance_settlements settlement
        LEFT JOIN maintenance_papers p ON p.paper_no = settlement.paper_no
        LEFT JOIN parties workshop ON workshop.party_code = settlement.party_code
        LEFT JOIN maintenance_staff staff ON staff.staff_code = p.staff_code
        {where_sql}
        {prefix}settlement.settlement_type = 'Workshop Credit' AND settlement.status = 'Open'
        GROUP BY settlement.party_code, workshop.party_name
        ORDER BY COALESCE(SUM(settlement.amount), 0) DESC, workshop.party_name ASC
        """,
        params,
    ).fetchall()


def _vehicle_maintenance_statement_rows(db, filters):
    where_sql, params = _maintenance_paper_filter_clause(filters)
    return db.execute(
        f"""
        SELECT
            p.vehicle_id,
            p.vehicle_no,
            vehicle.vehicle_type,
            vehicle.shift_mode,
            COUNT(*) AS paper_count,
            COALESCE(SUM(p.subtotal), 0) AS subtotal,
            COALESCE(SUM(p.tax_amount), 0) AS tax_amount,
            COALESCE(SUM(p.total_amount), 0) AS total_amount,
            COALESCE(SUM(p.company_paid_amount), 0) AS company_paid_amount,
            COALESCE(SUM(p.partner_paid_amount), 0) AS partner_paid_amount
        FROM maintenance_papers p
        LEFT JOIN vehicle_master vehicle ON vehicle.vehicle_id = p.vehicle_id
        LEFT JOIN parties workshop ON workshop.party_code = p.workshop_party_code
        LEFT JOIN maintenance_staff staff ON staff.staff_code = p.staff_code
        {where_sql}
        GROUP BY p.vehicle_id, p.vehicle_no, vehicle.vehicle_type, vehicle.shift_mode
        ORDER BY COALESCE(SUM(p.total_amount), 0) DESC, p.vehicle_no ASC
        """
        ,
        params,
    ).fetchall()


def _maintenance_partnership_rows(db, filters):
    where_sql, params = _maintenance_paper_filter_clause(filters)
    prefix = " AND " if where_sql else " WHERE "
    return db.execute(
        f"""
        SELECT
            p.vehicle_id,
            p.vehicle_no,
            vehicle.vehicle_type,
            COALESCE(partner.party_name, vehicle.partner_name, 'Partner') AS partner_name,
            COUNT(*) AS paper_count,
            COALESCE(SUM(p.total_amount), 0) AS total_amount,
            COALESCE(SUM(p.company_share_amount), 0) AS company_share_amount,
            COALESCE(SUM(p.partner_share_amount), 0) AS partner_share_amount,
            COALESCE(SUM(p.company_paid_amount), 0) AS company_paid_amount,
            COALESCE(SUM(p.partner_paid_amount), 0) AS partner_paid_amount
        FROM maintenance_papers p
        LEFT JOIN vehicle_master vehicle ON vehicle.vehicle_id = p.vehicle_id
        LEFT JOIN parties workshop ON workshop.party_code = p.workshop_party_code
        LEFT JOIN maintenance_staff staff ON staff.staff_code = p.staff_code
        LEFT JOIN parties partner ON partner.party_code = vehicle.partner_party_code
        {where_sql}
        {prefix}p.target_class = 'Partnership Supplier Vehicle'
        GROUP BY p.vehicle_id, p.vehicle_no, vehicle.vehicle_type, partner.party_name, vehicle.partner_name
        ORDER BY COALESCE(SUM(p.total_amount), 0) DESC, p.vehicle_no ASC
        """,
        params,
    ).fetchall()


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
    cutoff_day = _salary_cutoff_day(normalized_month)
    return {
        "entry_date": date.today().isoformat(),
        "salary_month": normalized_month,
        "ot_month": _previous_month_value(normalized_month),
        "salary_mode": "full",
        "prorata_start_date": (duty_start or "").strip(),
        "prorata_end_date": f"{normalized_month}-{cutoff_day:02d}",
        "ot_hours": "0",
        "personal_vehicle": "0",
        "personal_vehicle_note": "",
        "remarks": "",
    }


def _salary_form_from_row(row):
    salary_month = _normalize_month(row["salary_month"])
    prorata_start_date = _date_only_value(row["prorata_start_date"]) if row["prorata_start_date"] else ""
    prorata_end_date = ""
    if (row["salary_mode"] or "full").strip().lower() == "prorata" and prorata_start_date:
        try:
            start_date = datetime.strptime(prorata_start_date, "%Y-%m-%d").date()
            salary_days = int(round(float(row["salary_days"] or 0)))
            if salary_days > 0:
                prorata_end_date = (start_date + timedelta(days=salary_days - 1)).isoformat()
        except (TypeError, ValueError):
            prorata_end_date = ""
    return {
        "entry_date": _date_only_value(row["entry_date"]),
        "salary_month": salary_month,
        "ot_month": row["ot_month"] or _previous_month_value(salary_month),
        "salary_mode": (row["salary_mode"] or "full").strip().lower(),
        "prorata_start_date": prorata_start_date,
        "prorata_end_date": prorata_end_date,
        "ot_hours": f"{float(row['ot_hours']):.2f}",
        "personal_vehicle": f"{float(row['personal_vehicle']):.2f}",
        "personal_vehicle_note": row["personal_vehicle_note"] or "",
        "remarks": row["remarks"] or "",
    }


def _salary_preview_from_row(row):
    salary_month = _normalize_month(row["salary_month"])
    salary_mode = (row["salary_mode"] or "full").strip().lower()
    if salary_mode not in {"full", "prorata"}:
        salary_mode = "full"
    monthly_basic_salary = float(row["monthly_basic_salary"]) if row["monthly_basic_salary"] is not None else float(row["basic_salary"])
    daily_rate = float(row["daily_rate"]) if row["daily_rate"] is not None else round(monthly_basic_salary / 30.0, 6)
    prorata_start_date = _date_only_value(row["prorata_start_date"]) if row["prorata_start_date"] else ""
    prorata_end_date = ""
    if salary_mode == "prorata" and prorata_start_date:
        try:
            start_date = datetime.strptime(prorata_start_date, "%Y-%m-%d").date()
            salary_days = int(round(float(row["salary_days"] or 0)))
            if salary_days > 0:
                prorata_end_date = (start_date + timedelta(days=salary_days - 1)).isoformat()
        except (TypeError, ValueError):
            prorata_end_date = ""
    return {
        "entry_date": _date_only_value(row["entry_date"]),
        "salary_month": salary_month,
        "ot_month": row["ot_month"] or _previous_month_value(salary_month),
        "salary_mode": salary_mode,
        "salary_mode_label": _salary_mode_label(salary_mode),
        "prorata_start_date": prorata_start_date,
        "prorata_end_date": prorata_end_date,
        "salary_days": float(row["salary_days"]) if row["salary_days"] is not None else 30.0,
        "daily_rate": daily_rate,
        "monthly_basic_salary": monthly_basic_salary,
        "basic_salary": float(row["basic_salary"]),
        "ot_hours": float(row["ot_hours"]),
        "ot_rate": float(row["ot_rate"]),
        "ot_amount": float(row["ot_amount"]),
        "personal_vehicle": float(row["personal_vehicle"]),
        "personal_vehicle_note": row["personal_vehicle_note"] or "",
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
    prorata_end_date = ""
    salary_days = 30.0
    basic_salary = monthly_basic_salary
    if salary_mode == "prorata":
        prorata_start_date = (form.get("prorata_start_date", "") or "").strip() or (driver.get("duty_start", "") or "").strip()
        prorata_end_date = (form.get("prorata_end_date", "") or "").strip()
        if not prorata_start_date:
            raise ValidationError("Prorata start date is required when salary mode is prorata.")
        if not prorata_end_date:
            raise ValidationError("Duty to date is required when salary mode is prorata.")
        try:
            start_date = datetime.strptime(prorata_start_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValidationError("Prorata start date is not valid.") from exc
        try:
            end_date = datetime.strptime(prorata_end_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValidationError("Duty to date is not valid.") from exc
        if start_date.strftime("%Y-%m") != salary_month:
            raise ValidationError("Prorata start date must be inside the selected salary month.")
        if end_date.strftime("%Y-%m") != salary_month:
            raise ValidationError("Duty to date must be inside the selected salary month.")
        if start_date.day > cutoff_day:
            raise ValidationError(f"Prorata start date must be on or before day {cutoff_day} for this payroll month.")
        if end_date.day > cutoff_day:
            raise ValidationError(f"Duty to date must be on or before day {cutoff_day} for this payroll month.")
        if end_date < start_date:
            raise ValidationError("Duty to date must be after or equal to duty from date.")
        salary_days = float((end_date - start_date).days + 1)
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
        "prorata_end_date": prorata_end_date,
        "salary_days": salary_days,
        "daily_rate": daily_rate,
        "monthly_basic_salary": monthly_basic_salary,
        "basic_salary": basic_salary,
        "ot_hours": ot_hours,
        "ot_rate": ot_rate,
        "ot_amount": ot_amount,
        "personal_vehicle": personal_vehicle,
        "personal_vehicle_note": (form.get("personal_vehicle_note", "") or "").strip(),
        "net_salary": net_salary,
        "remarks": form.get("remarks", ""),
        "cutoff_day": cutoff_day,
    }


def _salary_row_reason(row) -> str:
    remarks = (row["remarks"] or "").strip()
    personal_note = (row["personal_vehicle_note"] or "").strip() if "personal_vehicle_note" in row.keys() else ""
    personal_amount = float(row["personal_vehicle"] or 0.0) if "personal_vehicle" in row.keys() else 0.0
    parts = []
    if remarks:
        parts.append(remarks)
    if personal_amount > 0 and personal_note:
        parts.append(f"Personal / Vehicle: {personal_note}")
    return " | ".join(parts) if parts else "Monthly salary"


def _salary_slip_amounts(slip) -> dict[str, float]:
    net_payable = float(slip["net_payable"] or 0.0)
    salary_after_deduction = float(slip["salary_after_deduction"] or 0.0) if "salary_after_deduction" in slip.keys() else 0.0
    actual_paid_amount = float(slip["actual_paid_amount"] or 0.0) if "actual_paid_amount" in slip.keys() else 0.0
    company_balance_due = float(slip["company_balance_due"] or 0.0) if "company_balance_due" in slip.keys() else 0.0

    if salary_after_deduction <= 0 and net_payable > 0:
        salary_after_deduction = net_payable
    if actual_paid_amount <= 0 and net_payable > 0 and salary_after_deduction == net_payable and company_balance_due <= 0:
        actual_paid_amount = net_payable
    if company_balance_due <= 0 and salary_after_deduction >= actual_paid_amount:
        company_balance_due = max(salary_after_deduction - actual_paid_amount, 0.0)

    return {
        "salary_after_deduction": salary_after_deduction,
        "actual_paid_amount": actual_paid_amount,
        "company_balance_due": company_balance_due,
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
    total_paid = 0.0
    for slip in db.execute(
        """
        SELECT net_payable, salary_after_deduction, actual_paid_amount, company_balance_due
        FROM salary_slips
        WHERE driver_id = ?
        """,
        (driver_id,),
    ).fetchall():
        total_paid += _salary_slip_amounts(slip)["actual_paid_amount"]
    return max(float(total_salary) - float(total_deducted) - total_paid, 0.0)


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
    incoming = float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM owner_fund_entries WHERE transaction_type = 'IN'").fetchone()[0])
    outgoing_owner_fund = float(db.execute("SELECT COALESCE(SUM(amount), 0) FROM owner_fund_entries WHERE transaction_type = 'OUT'").fetchone()[0])
    outgoing_transactions = float(
        db.execute("SELECT COALESCE(SUM(amount), 0) FROM driver_transactions WHERE source = 'Owner Fund'").fetchone()[0]
    )
    outgoing_salary = float(
        db.execute(
            "SELECT COALESCE(SUM(COALESCE(actual_paid_amount, net_payable)), 0) FROM salary_slips WHERE payment_source = 'Owner Fund'"
        ).fetchone()[0]
    )
    outgoing_field_staff = float(
        db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM maintenance_staff_advances WHERE funding_source = 'Owner Fund'"
        ).fetchone()[0]
    )
    outgoing = outgoing_owner_fund + outgoing_transactions + outgoing_salary + outgoing_field_staff
    return incoming, outgoing, incoming - outgoing


def _owner_fund_filter_values(request):
    month_value = request.args.get("month", "").strip() or request.form.get("month", "").strip()
    filters = {
        "month": _normalize_month(month_value) if month_value else "",
        "movement": request.args.get("movement", "").strip() or request.form.get("movement", "").strip() or OWNER_FUND_MOVEMENT_OPTIONS[0],
        "search": request.args.get("search", "").strip() or request.form.get("search", "").strip(),
    }
    if filters["movement"] not in OWNER_FUND_MOVEMENT_OPTIONS:
        filters["movement"] = OWNER_FUND_MOVEMENT_OPTIONS[0]
    return filters


def _owner_fund_view_totals(rows):
    incoming = sum(float(row["incoming"]) for row in rows)
    outgoing = sum(float(row["outgoing"]) for row in rows)
    net = incoming - outgoing
    closing_balance = float(rows[-1]["balance"]) if rows else 0.0
    return incoming, outgoing, net, closing_balance


def _owner_fund_statement(db, reverse: bool = True, filters=None):
    filters = filters or {"month": "", "movement": OWNER_FUND_MOVEMENT_OPTIONS[0], "search": ""}
    rows = []
    for entry in db.execute(
        """
        SELECT owner_name, entry_date, amount, received_by, transaction_type, details
        FROM owner_fund_entries
        ORDER BY entry_date ASC, id ASC
        """
    ).fetchall():
        transaction_type = entry["transaction_type"] or "IN"
        if transaction_type == "IN":
            rows.append(
                {
                    "entry_date": entry["entry_date"],
                    "reference": f"Owner Fund / {entry['owner_name']}",
                    "party": entry["received_by"] or "-",
                    "details": entry["details"] or "-",
                    "incoming": float(entry["amount"]),
                    "outgoing": 0.0,
                    "movement": "Incoming",
                }
            )
        else:  # OUT
            rows.append(
                {
                    "entry_date": entry["entry_date"],
                    "reference": f"Owner Fund / {entry['owner_name']}",
                    "party": entry["received_by"] or "-",
                    "details": entry["details"] or "-",
                    "incoming": 0.0,
                    "outgoing": float(entry["amount"]),
                    "movement": "Outgoing",
                }
            )
    for entry in db.execute(
        """
        SELECT driver_transactions.entry_date, driver_transactions.driver_id, driver_transactions.given_by,
               driver_transactions.amount, driver_transactions.details, drivers.full_name
        FROM driver_transactions
        LEFT JOIN drivers ON drivers.driver_id = driver_transactions.driver_id
        WHERE source = 'Owner Fund'
        ORDER BY driver_transactions.entry_date ASC, driver_transactions.id ASC
        """
    ).fetchall():
        driver_name = entry["full_name"] or entry["driver_id"]
        rows.append(
            {
                "entry_date": entry["entry_date"],
                "reference": f"Driver Txn / {driver_name}",
                "party": entry["given_by"] or "-",
                "details": entry["details"] or "-",
                "incoming": 0.0,
                "outgoing": float(entry["amount"]),
                "movement": "Outgoing",
            }
        )
    for entry in db.execute(
        """
        SELECT salary_slips.generated_at, salary_slips.driver_id, salary_slips.paid_by,
               salary_slips.net_payable, salary_slips.actual_paid_amount, salary_slips.salary_month, drivers.full_name
        FROM salary_slips
        LEFT JOIN drivers ON drivers.driver_id = salary_slips.driver_id
        WHERE payment_source = 'Owner Fund'
        ORDER BY salary_slips.generated_at ASC, salary_slips.id ASC
        """
    ).fetchall():
        driver_name = entry["full_name"] or entry["driver_id"]
        rows.append(
            {
                "entry_date": _date_only_value(entry["generated_at"]),
                "reference": f"Salary Slip / {driver_name}",
                "party": entry["paid_by"] or "-",
                "details": f"Salary {entry['salary_month']}",
                "incoming": 0.0,
                "outgoing": _salary_slip_amounts(entry)["actual_paid_amount"],
                "movement": "Outgoing",
            }
        )
    for entry in db.execute(
        """
        SELECT
            adv.entry_date,
            adv.staff_code,
            adv.reference,
            adv.notes,
            adv.amount,
            staff.staff_name,
            tech.specialization
        FROM maintenance_staff_advances adv
        LEFT JOIN maintenance_staff staff ON staff.staff_code = adv.staff_code
        LEFT JOIN technicians tech ON tech.technician_code = adv.staff_code
        WHERE adv.funding_source = 'Owner Fund'
        ORDER BY adv.entry_date ASC, adv.id ASC
        """
    ).fetchall():
        staff_name = entry["staff_name"] or entry["specialization"] or entry["staff_code"]
        rows.append(
            {
                "entry_date": entry["entry_date"],
                "reference": f"Field Staff Payment / {staff_name}",
                "party": "Owner Fund",
                "details": entry["reference"] or entry["notes"] or "Field staff amount issued",
                "incoming": 0.0,
                "outgoing": float(entry["amount"]),
                "movement": "Outgoing",
            }
        )
    rows.sort(key=lambda item: (item["entry_date"], item["movement"], item["reference"]))
    balance = 0.0
    for row in rows:
        balance += row["incoming"] - row["outgoing"]
        row["balance"] = balance

    filtered_rows = []
    search_text = (filters.get("search") or "").strip().lower()
    month_filter = filters.get("month") or ""
    movement_filter = filters.get("movement") or OWNER_FUND_MOVEMENT_OPTIONS[0]

    for row in rows:
        if month_filter and str(row["entry_date"])[:7] != month_filter:
            continue
        if movement_filter != OWNER_FUND_MOVEMENT_OPTIONS[0] and row["movement"] != movement_filter:
            continue
        if search_text:
            haystack = " ".join(
                [
                    str(row["reference"]),
                    str(row["party"]),
                    str(row["details"]),
                    f"{float(row['incoming']):.2f}",
                    f"{float(row['outgoing']):.2f}",
                    f"{float(row['balance']):.2f}",
                ]
            ).lower()
            if search_text not in haystack:
                continue
        filtered_rows.append(row)

    if reverse:
        filtered_rows.reverse()
    return filtered_rows[:60] if reverse else filtered_rows


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


def _next_month_value(value: str) -> str:
    normalized = _normalize_month(value)
    month_date = datetime.strptime(f"{normalized}-01", "%Y-%m-%d")
    if month_date.month == 12:
        return f"{month_date.year + 1}-01"
    return f"{month_date.year}-{month_date.month + 1:02d}"


def _driver_kata_month_data(db, driver_id: str, month_value: str) -> tuple[list[dict], dict]:
    month_value = _normalize_month(month_value)
    next_month = _next_month_value(month_value)
    opening_balance = 0.0
    for slip in db.execute(
        """
        SELECT salary_after_deduction, actual_paid_amount, company_balance_due, net_payable
        FROM salary_slips
        WHERE driver_id = ? AND salary_month < ?
        ORDER BY salary_month ASC, id ASC
        """,
        (driver_id, month_value),
    ).fetchall():
        opening_balance += _salary_slip_amounts(slip)["company_balance_due"]
    opening_balance = max(opening_balance, 0.0)

    opening_advance_left = float(
        db.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM driver_transactions
            WHERE driver_id = ? AND entry_date < ?
            """,
            (driver_id, f"{month_value}-01"),
        ).fetchone()[0]
    )
    opening_advance_left -= float(
        db.execute(
            """
            SELECT COALESCE(SUM(total_deductions), 0)
            FROM salary_slips
            WHERE driver_id = ? AND salary_month < ?
            """,
            (driver_id, month_value),
        ).fetchone()[0]
    )
    opening_advance_left = max(opening_advance_left, 0.0)

    salary_rows = db.execute(
        """
        SELECT entry_date, salary_month, net_salary, remarks, personal_vehicle, personal_vehicle_note
        FROM salary_store
        WHERE driver_id = ? AND salary_month = ?
        ORDER BY entry_date ASC, id ASC
        """,
        (driver_id, month_value),
    ).fetchall()
    transaction_rows = db.execute(
        """
        SELECT entry_date, txn_type, source, given_by, amount, details
        FROM driver_transactions
        WHERE driver_id = ? AND entry_date >= ? AND entry_date < ?
        ORDER BY entry_date ASC, id ASC
        """,
        (driver_id, f"{month_value}-01", f"{next_month}-01"),
    ).fetchall()
    slip_rows = db.execute(
        """
        SELECT generated_at, salary_month, total_deductions, salary_after_deduction, actual_paid_amount,
               company_balance_due, net_payable, payment_source, paid_by, pdf_path
        FROM salary_slips
        WHERE driver_id = ? AND salary_month = ?
        ORDER BY generated_at ASC, id ASC
        """,
        (driver_id, month_value),
    ).fetchall()

    entries = []
    running_balance = opening_balance
    advance_left = opening_advance_left
    if month_value:
        entries.append(
            {
                "date": f"{month_value}-01",
                "amount": opening_balance,
                "paid_by": "Previous Month",
                "reason": "Opening company balance",
                "balance_after": opening_balance,
                "entry_kind": "opening",
            }
        )
    for salary in salary_rows:
        running_balance += float(salary["net_salary"])
        entries.append(
            {
                "date": salary["entry_date"],
                "amount": float(salary["net_salary"]),
                "paid_by": "Current Link",
                "reason": _salary_row_reason(salary),
                "balance_after": max(running_balance, 0.0),
                "entry_kind": "salary",
            }
        )
    for txn in transaction_rows:
        advance_left += float(txn["amount"])
        paid_by = (txn["source"] or txn["given_by"] or "-").strip()
        reason = (txn["details"] or txn["given_by"] or txn["txn_type"] or "-").strip()
        entries.append(
            {
                "date": txn["entry_date"],
                "amount": float(txn["amount"]),
                "paid_by": paid_by,
                "reason": reason,
                "balance_after": max(running_balance, 0.0),
                "entry_kind": "transaction",
            }
        )
    for slip in slip_rows:
        slip_amounts = _salary_slip_amounts(slip)
        deduction_amount = float(slip["total_deductions"] or 0.0)
        if deduction_amount > 0:
            running_balance = max(running_balance - deduction_amount, 0.0)
            advance_left = max(advance_left - deduction_amount, 0.0)
            entries.append(
                {
                    "date": str(slip["generated_at"])[:10],
                    "amount": deduction_amount,
                    "paid_by": (slip["payment_source"] or slip["paid_by"] or "-").strip(),
                    "reason": "Advance deduction",
                    "balance_after": running_balance,
                    "entry_kind": "deduction",
                }
            )
        actual_paid_amount = slip_amounts["actual_paid_amount"]
        if actual_paid_amount > 0:
            running_balance = max(running_balance - actual_paid_amount, 0.0)
            entries.append(
                {
                    "date": str(slip["generated_at"])[:10],
                    "amount": actual_paid_amount,
                    "paid_by": (slip["payment_source"] or slip["paid_by"] or "-").strip(),
                    "reason": "Actual salary paid",
                    "balance_after": running_balance,
                    "entry_kind": "payment",
                }
            )
        if slip_amounts["company_balance_due"] > 0:
            entries.append(
                {
                    "date": str(slip["generated_at"])[:10],
                    "amount": slip_amounts["company_balance_due"],
                    "paid_by": "Current Link",
                    "reason": "Company balance due",
                    "balance_after": running_balance,
                    "entry_kind": "company_balance",
                }
            )

    entries.sort(
        key=lambda item: (
            item["date"],
            0 if item["entry_kind"] == "opening"
            else 1 if item["entry_kind"] == "salary"
            else 2 if item["entry_kind"] == "transaction"
            else 3 if item["entry_kind"] == "deduction"
            else 4 if item["entry_kind"] == "payment"
            else 5
        )
    )

    summary = {
        "month": month_value,
        "month_label": format_month_label(month_value),
        "opening_balance": opening_balance,
        "salary_amount": sum(float(row["net_salary"]) for row in salary_rows),
        "cash_given": sum(float(row["amount"]) for row in transaction_rows),
        "deduction_amount": sum(float(row["total_deductions"]) for row in slip_rows),
        "paid_amount": sum(_salary_slip_amounts(row)["actual_paid_amount"] for row in slip_rows),
        "company_balance_due": sum(_salary_slip_amounts(row)["company_balance_due"] for row in slip_rows),
        "advance_left": advance_left,
        "closing_balance": max(running_balance, 0.0),
    }
    return entries, summary


def _driver_transaction_history_rows(db, driver_id: str, upto_date: str | None = None) -> list[dict]:
    cutoff_date = upto_date or date.today().isoformat()
    transaction_rows = db.execute(
        """
        SELECT id, entry_date, txn_type, source, given_by, amount, details
        FROM driver_transactions
        WHERE driver_id = ? AND entry_date <= ?
        ORDER BY entry_date DESC, id DESC
        """,
        (driver_id, cutoff_date),
    ).fetchall()
    salary_paid_rows = db.execute(
        """
        SELECT salary_slips.id, salary_slips.salary_store_id, salary_slips.salary_month,
               salary_slips.total_deductions, salary_slips.salary_after_deduction, salary_slips.actual_paid_amount,
               salary_slips.company_balance_due, salary_slips.net_payable, salary_slips.payment_source,
               salary_slips.paid_by, salary_slips.generated_at, salary_store.remarks,
               salary_store.personal_vehicle, salary_store.personal_vehicle_note
        FROM salary_slips
        LEFT JOIN salary_store ON salary_store.id = salary_slips.salary_store_id
        WHERE salary_slips.driver_id = ?
          AND DATE(salary_slips.generated_at) <= ?
        ORDER BY salary_slips.generated_at DESC, salary_slips.id DESC
        """,
        (driver_id, cutoff_date),
    ).fetchall()

    history_rows = []
    for txn in transaction_rows:
        history_rows.append(
            {
                "row_type": "transaction",
                "id": txn["id"],
                "date": txn["entry_date"],
                "type_label": txn["txn_type"],
                "amount": float(txn["amount"]),
                "source": (txn["source"] or "-").strip(),
                "given_by": (txn["given_by"] or "-").strip(),
                "details": (txn["details"] or "-").strip(),
                "edit_target": url_for("driver_transactions", driver_id=driver_id, edit=txn["id"]),
                "delete_target": url_for("delete_driver_transaction", driver_id=driver_id, transaction_id=txn["id"]),
                "edit_label": "Edit",
                "delete_label": "Delete",
                "sort_stamp": f"{txn['entry_date']}::{int(txn['id']):010d}::1",
            }
        )

    for slip in salary_paid_rows:
        month_label = format_month_label(slip["salary_month"])
        slip_amounts = _salary_slip_amounts(slip)
        deduction_amount = float(slip["total_deductions"] or 0.0)
        details = _salary_row_reason(slip) if "personal_vehicle_note" in slip.keys() else ((slip["remarks"] or "").strip() or f"{month_label} salary paid")
        if deduction_amount > 0:
            details = f"{details} | Deducted AED {deduction_amount:.2f}"
        if slip_amounts["company_balance_due"] > 0:
            details = f"{details} | Company balance AED {slip_amounts['company_balance_due']:.2f}"
        history_rows.append(
            {
                "row_type": "salary_paid",
                "id": slip["id"],
                "date": str(slip["generated_at"])[:10],
                "type_label": "Salary Paid",
                "amount": slip_amounts["actual_paid_amount"],
                "source": (slip["payment_source"] or "-").strip(),
                "given_by": (slip["paid_by"] or "-").strip(),
                "details": details,
                "edit_target": url_for("driver_salary_slip", driver_id=driver_id, salary_store_id=slip["salary_store_id"]),
                "delete_target": url_for("delete_salary_slip", driver_id=driver_id, slip_id=slip["id"]),
                "edit_label": "Edit Slip",
                "delete_label": "Delete Slip",
                "sort_stamp": f"{str(slip['generated_at'])[:10]}::{int(slip['id']):010d}::2",
            }
        )

    history_rows.sort(key=lambda item: item["sort_stamp"], reverse=True)
    return history_rows


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


def _regenerate_kata_for_driver(app: Flask, db, driver, month_value: str | None = None):
    salary_rows = db.execute(
        """
        SELECT entry_date, salary_month, net_salary, remarks, personal_vehicle, personal_vehicle_note
        FROM salary_store
        WHERE driver_id = ?
        ORDER BY entry_date ASC, id ASC
        """,
        (driver["driver_id"],),
    ).fetchall()
    transactions = db.execute(
        """
        SELECT entry_date, txn_type, source, given_by, amount, details
        FROM driver_transactions
        WHERE driver_id = ?
        ORDER BY entry_date ASC, id ASC
        """,
        (driver["driver_id"],),
    ).fetchall()
    salary_slips = db.execute(
        """
        SELECT generated_at, salary_month, total_deductions, remaining_advance, salary_after_deduction,
               actual_paid_amount, company_balance_due, net_payable, payment_source, paid_by
        FROM salary_slips
        WHERE driver_id = ?
        ORDER BY generated_at ASC, id ASC
        """,
        (driver["driver_id"],),
    ).fetchall()
    if not salary_rows and not transactions and not salary_slips:
        return None
    output_dir = _driver_output_dir(app, driver["driver_id"], driver=driver) / "kata_pdfs"
    pdf_path = generate_kata_pdf(
        driver,
        salary_rows,
        transactions,
        salary_slips,
        str(output_dir),
        app.config["STATIC_ASSETS_DIR"],
        month_value=month_value,
    )
    _mirror_generated_file(app, pdf_path)
    return pdf_path


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
    _mirror_generated_file(app, target)
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
               remaining_advance, salary_after_deduction, actual_paid_amount, company_balance_due,
               payment_source, paid_by, net_payable, pdf_path
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
        pdf_path = generate_owner_fund_pdf(
            statement,
            {"incoming": incoming, "outgoing": outgoing, "balance": balance},
            str(output_dir),
            app.config["STATIC_ASSETS_DIR"],
        )
        _mirror_generated_file(app, pdf_path)
        return pdf_path

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
        "salary_after_deduction": _salary_slip_amounts(slip)["salary_after_deduction"],
        "actual_paid_amount": _salary_slip_amounts(slip)["actual_paid_amount"],
        "company_balance_due": _salary_slip_amounts(slip)["company_balance_due"],
        "payment_source": slip["payment_source"] or PAYMENT_SOURCES[0],
        "paid_by": slip["paid_by"] or "",
        "net_payable": _salary_slip_amounts(slip)["actual_paid_amount"],
    }
    output_dir = _driver_output_dir(app, slip["driver_id"], driver=driver) / "salary_slips"
    pdf_path = generate_salary_slip_pdf(
        driver,
        salary_row,
        slip_payload,
        str(output_dir),
        app.config["STATIC_ASSETS_DIR"],
        app.config["GENERATED_DIR"],
    )
    _mirror_generated_file(app, pdf_path)
    return pdf_path


def _maintenance_output_dir(app: Flask, paper_no: str) -> Path:
    output_dir = Path(app.config["GENERATED_DIR"]) / "maintenance" / secure_filename((paper_no or "paper").lower())
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _save_maintenance_attachment(app: Flask, paper_no: str, upload_file) -> str | None:
    if upload_file is None or not getattr(upload_file, "filename", ""):
        return None
    safe_name = secure_filename(upload_file.filename)
    if not safe_name:
        return None
    output_dir = _maintenance_output_dir(app, paper_no)
    output_path = output_dir / safe_name
    upload_file.save(output_path)
    _mirror_generated_file(app, output_path)
    return output_path.relative_to(Path(app.config["GENERATED_DIR"])).as_posix()


def _save_fleet_vehicle_import_pdf(app: Flask, upload_file, pdf_bytes: bytes | None = None) -> str | None:
    if upload_file is None or not getattr(upload_file, "filename", ""):
        return None
    safe_name = secure_filename(upload_file.filename)
    if not safe_name or not safe_name.lower().endswith(".pdf"):
        raise ValidationError("Vehicle import only accepts PDF files.")
    output_dir = Path(app.config["GENERATED_DIR"]) / "fleet_vehicle_imports"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = output_dir / f"{timestamp}-{safe_name}"
    if pdf_bytes is not None:
        output_path.write_bytes(pdf_bytes)
    else:
        upload_file.save(output_path)
    _mirror_generated_file(app, output_path)
    return output_path.relative_to(Path(app.config["GENERATED_DIR"])).as_posix()


def _fleet_vehicle_import_rows(app: Flask):
    folder = Path(app.config["GENERATED_DIR"]) / "fleet_vehicle_imports"
    if not folder.exists():
        return []
    rows = []
    for item in sorted(folder.glob("*.pdf"), key=lambda path: path.stat().st_mtime, reverse=True)[:8]:
        rows.append(
            {
                "filename": item.name,
                "relative_path": item.relative_to(Path(app.config["GENERATED_DIR"])).as_posix(),
                "updated_at": datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            }
        )
    return rows


def _upsert_fleet_vehicle_records(db, records):
    imported = 0
    existing_rows = db.execute(
        """
        SELECT vehicle_id, vehicle_no, vehicle_type, make_model, status, shift_mode,
               ownership_mode, partner_party_code, partner_name, company_share_percent,
               partner_share_percent, notes
        FROM vehicle_master
        WHERE COALESCE(source_type, 'Own Fleet Vehicle') = 'Own Fleet Vehicle'
        """
    ).fetchall()
    by_vehicle_no = {(row["vehicle_no"] or "").strip().upper(): row for row in existing_rows if row["vehicle_no"]}
    next_number = _reference_max_number(db, "vehicle_master", "vehicle_id", "VEH")

    for record in records:
        vehicle_no = (record.vehicle_no or "").strip().upper()
        if not vehicle_no:
            continue
        existing = by_vehicle_no.get(vehicle_no)
        if existing is not None:
            db.execute(
                """
                UPDATE vehicle_master
                SET vehicle_type = ?, status = ?
                WHERE vehicle_id = ?
                """,
                (
                    record.vehicle_type or existing["vehicle_type"] or "General",
                    record.status or existing["status"] or "Active",
                    existing["vehicle_id"],
                ),
            )
        else:
            next_number += 1
            vehicle_id = f"VEH-{next_number:04d}"
            payload = (
                vehicle_id,
                vehicle_no,
                record.vehicle_type or "General",
                None,
                record.status or "Active",
                FLEET_SHIFT_MODE_OPTIONS[0],
                FLEET_OWNERSHIP_MODE_OPTIONS[0],
                "Own Fleet Vehicle",
                None,
                None,
                None,
                None,
                100.0,
                0.0,
                "Imported from fleet vehicle PDF",
            )
            db.execute(
                """
                INSERT INTO vehicle_master (
                    vehicle_id, vehicle_no, vehicle_type, make_model, status,
                    shift_mode, ownership_mode, source_type, source_party_code, source_asset_code,
                    partner_party_code, partner_name, company_share_percent, partner_share_percent, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            by_vehicle_no[vehicle_no] = {
                "vehicle_id": vehicle_id,
                "vehicle_no": vehicle_no,
                "vehicle_type": record.vehicle_type,
                "status": record.status,
            }
        imported += 1
    return imported


def _reference_max_number(db, table_name: str, field_name: str, prefix: str) -> int:
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
    return max_number


def _save_maintenance_paper_lines(db, paper_no: str, line_payloads):
    for row in line_payloads:
        db.execute(
            """
            INSERT INTO maintenance_paper_lines (
                paper_no, line_no, description, quantity, rate, amount
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                paper_no,
                row["line_no"],
                row["description"],
                row["quantity"],
                row["rate"],
                row["amount"],
            ),
        )


def _save_maintenance_linked_partnership_entry(db, prepared):
    if prepared["target_class"] != "Partnership Supplier Vehicle" or not prepared["target_party_code"] or not prepared["target_asset_code"]:
        return None
    entry_no = _next_reference_code(db, "supplier_partnership_entries", "entry_no", "PEN")
    paid_by = "Partner" if prepared["paid_by"] == "Partner" else "Company"
    db.execute(
        """
        INSERT INTO supplier_partnership_entries (
            entry_no, party_code, asset_code, period_month, entry_date,
            entry_kind, expense_head, shift_label, driver_name, paid_by, amount, notes, source_type, source_reference
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry_no,
            prepared["target_party_code"],
            prepared["target_asset_code"],
            prepared["paper_date"][:7],
            prepared["paper_date"],
            "Vehicle Expense",
            "Maintenance",
            "General",
            "",
            paid_by,
            prepared["total_amount"],
            f"Maintenance paper {prepared['paper_no']} / {prepared['work_summary']}",
            "maintenance_paper",
            prepared["paper_no"],
        ),
    )
    return entry_no


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
    _mirror_generated_file(app, output_path)
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
    if role == "supplier":
        party_code = _current_supplier_party_code()
        if not party_code:
            return False
        # Direct supplier folder access
        if filename.startswith(f"suppliers/{party_code}/"):
            return True
        # LPO PDF access — verify the supplier owns this LPO
        if filename.startswith("lpos/"):
            db = open_db()
            lpo = db.execute(
                "SELECT lpo_no FROM lpos WHERE pdf_path = ? AND party_code = ? LIMIT 1",
                (filename, party_code),
            ).fetchone()
            return lpo is not None
        return False
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
