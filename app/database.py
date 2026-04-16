import os
import sqlite3
from pathlib import Path

from flask import Flask, current_app, g


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    phone_number TEXT,
    pin_hash TEXT,
    vehicle_no TEXT NOT NULL,
    shift TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,
    basic_salary REAL NOT NULL,
    ot_rate REAL NOT NULL DEFAULT 0,
    duty_start TEXT,
    photo_name TEXT,
    photo_data TEXT,
    photo_content_type TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    remarks TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS driver_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    txn_type TEXT NOT NULL,
    source TEXT NOT NULL,
    given_by TEXT,
    amount REAL NOT NULL,
    details TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
);

CREATE TABLE IF NOT EXISTS driver_timesheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    work_hours REAL NOT NULL DEFAULT 0,
    remarks TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(driver_id, entry_date),
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
);

CREATE TABLE IF NOT EXISTS salary_store (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    salary_month TEXT NOT NULL,
    ot_month TEXT,
    salary_mode TEXT NOT NULL DEFAULT 'full',
    prorata_start_date TEXT,
    salary_days REAL NOT NULL DEFAULT 30,
    daily_rate REAL NOT NULL DEFAULT 0,
    monthly_basic_salary REAL NOT NULL DEFAULT 0,
    basic_salary REAL NOT NULL,
    ot_hours REAL NOT NULL DEFAULT 0,
    ot_rate REAL NOT NULL DEFAULT 0,
    ot_amount REAL NOT NULL DEFAULT 0,
    personal_vehicle REAL NOT NULL DEFAULT 0,
    net_salary REAL NOT NULL,
    remarks TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(driver_id, salary_month),
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
);

CREATE TABLE IF NOT EXISTS salary_slips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id TEXT NOT NULL,
    salary_store_id INTEGER NOT NULL,
    salary_month TEXT NOT NULL,
    source_filter TEXT,
    total_deductions REAL NOT NULL DEFAULT 0,
    available_advance REAL NOT NULL DEFAULT 0,
    remaining_advance REAL NOT NULL DEFAULT 0,
    payment_source TEXT,
    paid_by TEXT,
    net_payable REAL NOT NULL,
    pdf_path TEXT NOT NULL,
    generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id),
    FOREIGN KEY(salary_store_id) REFERENCES salary_store(id)
);

CREATE TABLE IF NOT EXISTS owner_fund_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_name TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    amount REAL NOT NULL,
    received_by TEXT,
    payment_method TEXT DEFAULT 'Cash',
    details TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    legal_name TEXT,
    trade_license_no TEXT,
    trade_license_expiry TEXT,
    trn_no TEXT,
    vat_status TEXT NOT NULL DEFAULT 'Registered',
    address TEXT,
    phone_number TEXT,
    email TEXT,
    bank_name TEXT,
    bank_account_name TEXT,
    bank_account_number TEXT,
    iban TEXT,
    swift_code TEXT,
    invoice_terms TEXT,
    base_currency TEXT NOT NULL DEFAULT 'AED',
    financial_year_label TEXT,
    financial_year_start TEXT,
    financial_year_end TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS branches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_code TEXT NOT NULL UNIQUE,
    branch_name TEXT NOT NULL,
    address TEXT,
    contact_person TEXT,
    phone_number TEXT,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_currencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    currency_code TEXT NOT NULL UNIQUE,
    currency_name TEXT NOT NULL,
    symbol TEXT,
    exchange_rate REAL NOT NULL DEFAULT 1,
    is_base INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS financial_years (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year_code TEXT NOT NULL UNIQUE,
    year_label TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open',
    is_current INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    party_code TEXT NOT NULL UNIQUE,
    party_name TEXT NOT NULL,
    party_kind TEXT NOT NULL DEFAULT 'Company',
    party_roles TEXT NOT NULL,
    contact_person TEXT,
    phone_number TEXT,
    email TEXT,
    trn_no TEXT,
    trade_license_no TEXT,
    address TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS supplier_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    party_code TEXT NOT NULL UNIQUE,
    supplier_mode TEXT NOT NULL DEFAULT 'Normal',
    partner_party_code TEXT,
    partner_name TEXT,
    default_company_share_percent REAL NOT NULL DEFAULT 100,
    default_partner_share_percent REAL NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code),
    FOREIGN KEY(partner_party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS supplier_portal_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    party_code TEXT NOT NULL UNIQUE,
    login_email TEXT NOT NULL,
    password_hash TEXT,
    portal_enabled INTEGER NOT NULL DEFAULT 0,
    activation_status TEXT NOT NULL DEFAULT 'Invited',
    last_login_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS supplier_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_code TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    asset_name TEXT NOT NULL,
    asset_type TEXT NOT NULL DEFAULT 'Trailer',
    vehicle_no TEXT,
    rate_basis TEXT NOT NULL DEFAULT 'Hours',
    default_rate REAL NOT NULL DEFAULT 0,
    double_shift_mode TEXT NOT NULL DEFAULT 'Single Shift',
    partnership_mode TEXT NOT NULL DEFAULT 'Standard',
    partner_name TEXT,
    company_share_percent REAL NOT NULL DEFAULT 100,
    partner_share_percent REAL NOT NULL DEFAULT 0,
    day_shift_paid_by TEXT NOT NULL DEFAULT 'Company',
    night_shift_paid_by TEXT NOT NULL DEFAULT 'Company',
    capacity TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS supplier_timesheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timesheet_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    asset_code TEXT NOT NULL,
    period_month TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    billing_basis TEXT NOT NULL DEFAULT 'Hours',
    billable_qty REAL NOT NULL DEFAULT 0,
    timesheet_hours REAL NOT NULL DEFAULT 0,
    rate REAL NOT NULL DEFAULT 0,
    subtotal REAL NOT NULL DEFAULT 0,
    voucher_no TEXT,
    status TEXT NOT NULL DEFAULT 'Open',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code),
    FOREIGN KEY(asset_code) REFERENCES supplier_assets(asset_code)
);

CREATE TABLE IF NOT EXISTS supplier_vouchers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    period_month TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    subtotal REAL NOT NULL DEFAULT 0,
    tax_percent REAL NOT NULL DEFAULT 0,
    tax_amount REAL NOT NULL DEFAULT 0,
    total_amount REAL NOT NULL DEFAULT 0,
    paid_amount REAL NOT NULL DEFAULT 0,
    balance_amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Open',
    source_type TEXT NOT NULL DEFAULT 'Timesheet',
    source_reference TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS supplier_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_no TEXT NOT NULL UNIQUE,
    voucher_no TEXT NOT NULL,
    party_code TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    payment_method TEXT NOT NULL DEFAULT 'Bank',
    reference TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(voucher_no) REFERENCES supplier_vouchers(voucher_no),
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS supplier_invoice_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    source_channel TEXT NOT NULL DEFAULT 'By Hand',
    external_invoice_no TEXT NOT NULL,
    period_month TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    subtotal REAL NOT NULL DEFAULT 0,
    vat_amount REAL NOT NULL DEFAULT 0,
    total_amount REAL NOT NULL DEFAULT 0,
    invoice_attachment_path TEXT,
    timesheet_attachment_path TEXT,
    notes TEXT,
    review_status TEXT NOT NULL DEFAULT 'Pending',
    review_note TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    linked_voucher_no TEXT,
    created_by_role TEXT,
    created_by_name TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code),
    FOREIGN KEY(linked_voucher_no) REFERENCES supplier_vouchers(voucher_no)
);

CREATE TABLE IF NOT EXISTS supplier_partnership_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    asset_code TEXT NOT NULL,
    period_month TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    entry_kind TEXT NOT NULL DEFAULT 'Vehicle Expense',
    expense_head TEXT,
    shift_label TEXT NOT NULL DEFAULT 'General',
    driver_name TEXT,
    paid_by TEXT NOT NULL DEFAULT 'Company',
    amount REAL NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code),
    FOREIGN KEY(asset_code) REFERENCES supplier_assets(asset_code)
);

CREATE TABLE IF NOT EXISTS agreements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agreement_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    agreement_kind TEXT NOT NULL DEFAULT 'Customer',
    start_date TEXT NOT NULL,
    end_date TEXT,
    rate_type TEXT,
    amount REAL NOT NULL DEFAULT 0,
    tax_percent REAL NOT NULL DEFAULT 0,
    scope TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS lpos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lpo_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    agreement_no TEXT,
    issue_date TEXT NOT NULL,
    valid_until TEXT,
    amount REAL NOT NULL DEFAULT 0,
    tax_percent REAL NOT NULL DEFAULT 0,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'Open',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS hire_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hire_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    agreement_no TEXT,
    lpo_no TEXT,
    entry_date TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'Supplier Hire',
    asset_name TEXT NOT NULL,
    asset_type TEXT,
    unit_type TEXT NOT NULL DEFAULT 'Days',
    quantity REAL NOT NULL DEFAULT 1,
    rate REAL NOT NULL DEFAULT 0,
    subtotal REAL NOT NULL DEFAULT 0,
    tax_percent REAL NOT NULL DEFAULT 0,
    tax_amount REAL NOT NULL DEFAULT 0,
    total_amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Open',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS account_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    agreement_no TEXT,
    lpo_no TEXT,
    hire_no TEXT,
    invoice_kind TEXT NOT NULL DEFAULT 'Sales',
    document_type TEXT NOT NULL DEFAULT 'Tax Invoice',
    issue_date TEXT NOT NULL,
    due_date TEXT,
    subtotal REAL NOT NULL DEFAULT 0,
    tax_percent REAL NOT NULL DEFAULT 0,
    tax_amount REAL NOT NULL DEFAULT 0,
    total_amount REAL NOT NULL DEFAULT 0,
    paid_amount REAL NOT NULL DEFAULT 0,
    balance_amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Open',
    pdf_path TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS account_invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    unit_label TEXT,
    rate REAL NOT NULL DEFAULT 0,
    subtotal REAL NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(invoice_no) REFERENCES account_invoices(invoice_no)
);

CREATE TABLE IF NOT EXISTS account_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_no TEXT NOT NULL UNIQUE,
    invoice_no TEXT,
    party_code TEXT NOT NULL,
    payment_kind TEXT NOT NULL DEFAULT 'Received',
    entry_date TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    payment_method TEXT NOT NULL DEFAULT 'Bank',
    reference TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS loan_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    loan_type TEXT NOT NULL DEFAULT 'Given',
    amount REAL NOT NULL DEFAULT 0,
    payment_method TEXT NOT NULL DEFAULT 'Cash',
    reference TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS annual_fee_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fee_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    fee_type TEXT NOT NULL DEFAULT 'Visa',
    description TEXT,
    vehicle_no TEXT,
    due_date TEXT NOT NULL,
    annual_amount REAL NOT NULL DEFAULT 0,
    received_amount REAL NOT NULL DEFAULT 0,
    balance_amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Due',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS vehicle_master (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id TEXT NOT NULL UNIQUE,
    vehicle_no TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,
    make_model TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    shift_mode TEXT NOT NULL DEFAULT 'Single Shift',
    ownership_mode TEXT NOT NULL DEFAULT 'Standard',
    source_type TEXT NOT NULL DEFAULT 'Own Fleet Vehicle',
    source_party_code TEXT,
    source_asset_code TEXT,
    partner_party_code TEXT,
    partner_name TEXT,
    company_share_percent REAL NOT NULL DEFAULT 100,
    partner_share_percent REAL NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS maintenance_staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_code TEXT NOT NULL UNIQUE,
    staff_name TEXT NOT NULL,
    phone_number TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS maintenance_staff_advances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    advance_no TEXT NOT NULL UNIQUE,
    staff_code TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    funding_source TEXT NOT NULL DEFAULT 'Owner Fund',
    amount REAL NOT NULL DEFAULT 0,
    settled_amount REAL NOT NULL DEFAULT 0,
    balance_amount REAL NOT NULL DEFAULT 0,
    reference TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(staff_code) REFERENCES maintenance_staff(staff_code)
);

CREATE TABLE IF NOT EXISTS maintenance_papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_no TEXT NOT NULL UNIQUE,
    paper_date TEXT NOT NULL,
    vehicle_id TEXT NOT NULL,
    vehicle_no TEXT NOT NULL,
    target_class TEXT NOT NULL DEFAULT 'Own Fleet Vehicle',
    target_party_code TEXT,
    target_asset_code TEXT,
    workshop_party_code TEXT,
    staff_code TEXT,
    advance_no TEXT,
    tax_mode TEXT NOT NULL DEFAULT 'Without Tax',
    supplier_bill_no TEXT,
    work_summary TEXT,
    funding_source TEXT NOT NULL DEFAULT 'Owner Fund',
    paid_by TEXT NOT NULL DEFAULT 'Company',
    subtotal REAL NOT NULL DEFAULT 0,
    tax_amount REAL NOT NULL DEFAULT 0,
    total_amount REAL NOT NULL DEFAULT 0,
    company_share_amount REAL NOT NULL DEFAULT 0,
    partner_share_amount REAL NOT NULL DEFAULT 0,
    company_paid_amount REAL NOT NULL DEFAULT 0,
    partner_paid_amount REAL NOT NULL DEFAULT 0,
    linked_partnership_entry_no TEXT,
    attachment_path TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(vehicle_id) REFERENCES vehicle_master(vehicle_id),
    FOREIGN KEY(workshop_party_code) REFERENCES parties(party_code),
    FOREIGN KEY(staff_code) REFERENCES maintenance_staff(staff_code),
    FOREIGN KEY(advance_no) REFERENCES maintenance_staff_advances(advance_no)
);

CREATE TABLE IF NOT EXISTS maintenance_paper_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_no TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    rate REAL NOT NULL DEFAULT 0,
    amount REAL NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(paper_no) REFERENCES maintenance_papers(paper_no)
);

CREATE TABLE IF NOT EXISTS maintenance_settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_no TEXT NOT NULL UNIQUE,
    paper_no TEXT NOT NULL,
    settlement_type TEXT NOT NULL DEFAULT 'Direct',
    advance_no TEXT,
    party_code TEXT,
    amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Settled',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(paper_no) REFERENCES maintenance_papers(paper_no),
    FOREIGN KEY(advance_no) REFERENCES maintenance_staff_advances(advance_no),
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS import_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    file_name TEXT NOT NULL,
    imported_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_role TEXT,
    actor_name TEXT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    status TEXT NOT NULL DEFAULT 'success',
    details TEXT,
    ip_address TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_rate_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    identifier TEXT NOT NULL,
    failures INTEGER NOT NULL DEFAULT 0,
    blocked_until TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role, identifier)
);
"""


POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS drivers (
    id BIGSERIAL PRIMARY KEY,
    driver_id TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    phone_number TEXT,
    pin_hash TEXT,
    vehicle_no TEXT NOT NULL,
    shift TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,
    basic_salary DOUBLE PRECISION NOT NULL,
    ot_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    duty_start TEXT,
    photo_name TEXT,
    photo_data TEXT,
    photo_content_type TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS driver_transactions (
    id BIGSERIAL PRIMARY KEY,
    driver_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    txn_type TEXT NOT NULL,
    source TEXT NOT NULL,
    given_by TEXT,
    amount DOUBLE PRECISION NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
);

CREATE TABLE IF NOT EXISTS driver_timesheets (
    id BIGSERIAL PRIMARY KEY,
    driver_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    work_hours DOUBLE PRECISION NOT NULL DEFAULT 0,
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(driver_id, entry_date),
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
);

CREATE TABLE IF NOT EXISTS salary_store (
    id BIGSERIAL PRIMARY KEY,
    driver_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    salary_month TEXT NOT NULL,
    ot_month TEXT,
    salary_mode TEXT NOT NULL DEFAULT 'full',
    prorata_start_date TEXT,
    salary_days DOUBLE PRECISION NOT NULL DEFAULT 30,
    daily_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    monthly_basic_salary DOUBLE PRECISION NOT NULL DEFAULT 0,
    basic_salary DOUBLE PRECISION NOT NULL,
    ot_hours DOUBLE PRECISION NOT NULL DEFAULT 0,
    ot_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    ot_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    personal_vehicle DOUBLE PRECISION NOT NULL DEFAULT 0,
    net_salary DOUBLE PRECISION NOT NULL,
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(driver_id, salary_month),
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id)
);

CREATE TABLE IF NOT EXISTS salary_slips (
    id BIGSERIAL PRIMARY KEY,
    driver_id TEXT NOT NULL,
    salary_store_id BIGINT NOT NULL,
    salary_month TEXT NOT NULL,
    source_filter TEXT,
    total_deductions DOUBLE PRECISION NOT NULL DEFAULT 0,
    available_advance DOUBLE PRECISION NOT NULL DEFAULT 0,
    remaining_advance DOUBLE PRECISION NOT NULL DEFAULT 0,
    payment_source TEXT,
    paid_by TEXT,
    net_payable DOUBLE PRECISION NOT NULL,
    pdf_path TEXT NOT NULL,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(driver_id) REFERENCES drivers(driver_id),
    FOREIGN KEY(salary_store_id) REFERENCES salary_store(id)
);

CREATE TABLE IF NOT EXISTS owner_fund_entries (
    id BIGSERIAL PRIMARY KEY,
    owner_name TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    received_by TEXT,
    payment_method TEXT DEFAULT 'Cash',
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_profile (
    id BIGSERIAL PRIMARY KEY,
    company_name TEXT NOT NULL,
    legal_name TEXT,
    trade_license_no TEXT,
    trade_license_expiry TEXT,
    trn_no TEXT,
    vat_status TEXT NOT NULL DEFAULT 'Registered',
    address TEXT,
    phone_number TEXT,
    email TEXT,
    bank_name TEXT,
    bank_account_name TEXT,
    bank_account_number TEXT,
    iban TEXT,
    swift_code TEXT,
    invoice_terms TEXT,
    base_currency TEXT NOT NULL DEFAULT 'AED',
    financial_year_label TEXT,
    financial_year_start TEXT,
    financial_year_end TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS branches (
    id BIGSERIAL PRIMARY KEY,
    branch_code TEXT NOT NULL UNIQUE,
    branch_name TEXT NOT NULL,
    address TEXT,
    contact_person TEXT,
    phone_number TEXT,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_currencies (
    id BIGSERIAL PRIMARY KEY,
    currency_code TEXT NOT NULL UNIQUE,
    currency_name TEXT NOT NULL,
    symbol TEXT,
    exchange_rate DOUBLE PRECISION NOT NULL DEFAULT 1,
    is_base INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS financial_years (
    id BIGSERIAL PRIMARY KEY,
    year_code TEXT NOT NULL UNIQUE,
    year_label TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open',
    is_current INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parties (
    id BIGSERIAL PRIMARY KEY,
    party_code TEXT NOT NULL UNIQUE,
    party_name TEXT NOT NULL,
    party_kind TEXT NOT NULL DEFAULT 'Company',
    party_roles TEXT NOT NULL,
    contact_person TEXT,
    phone_number TEXT,
    email TEXT,
    trn_no TEXT,
    trade_license_no TEXT,
    address TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS supplier_profile (
    id BIGSERIAL PRIMARY KEY,
    party_code TEXT NOT NULL UNIQUE,
    supplier_mode TEXT NOT NULL DEFAULT 'Normal',
    partner_party_code TEXT,
    partner_name TEXT,
    default_company_share_percent DOUBLE PRECISION NOT NULL DEFAULT 100,
    default_partner_share_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code),
    FOREIGN KEY(partner_party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS supplier_portal_accounts (
    id BIGSERIAL PRIMARY KEY,
    party_code TEXT NOT NULL UNIQUE,
    login_email TEXT NOT NULL,
    password_hash TEXT,
    portal_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    activation_status TEXT NOT NULL DEFAULT 'Invited',
    last_login_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS supplier_assets (
    id BIGSERIAL PRIMARY KEY,
    asset_code TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    asset_name TEXT NOT NULL,
    asset_type TEXT NOT NULL DEFAULT 'Trailer',
    vehicle_no TEXT,
    rate_basis TEXT NOT NULL DEFAULT 'Hours',
    default_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    double_shift_mode TEXT NOT NULL DEFAULT 'Single Shift',
    partnership_mode TEXT NOT NULL DEFAULT 'Standard',
    partner_name TEXT,
    company_share_percent DOUBLE PRECISION NOT NULL DEFAULT 100,
    partner_share_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    day_shift_paid_by TEXT NOT NULL DEFAULT 'Company',
    night_shift_paid_by TEXT NOT NULL DEFAULT 'Company',
    capacity TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS supplier_timesheets (
    id BIGSERIAL PRIMARY KEY,
    timesheet_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    asset_code TEXT NOT NULL,
    period_month TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    billing_basis TEXT NOT NULL DEFAULT 'Hours',
    billable_qty DOUBLE PRECISION NOT NULL DEFAULT 0,
    timesheet_hours DOUBLE PRECISION NOT NULL DEFAULT 0,
    rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    subtotal DOUBLE PRECISION NOT NULL DEFAULT 0,
    voucher_no TEXT,
    status TEXT NOT NULL DEFAULT 'Open',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code),
    FOREIGN KEY(asset_code) REFERENCES supplier_assets(asset_code)
);

CREATE TABLE IF NOT EXISTS supplier_vouchers (
    id BIGSERIAL PRIMARY KEY,
    voucher_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    period_month TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    subtotal DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    paid_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    balance_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Open',
    source_type TEXT NOT NULL DEFAULT 'Timesheet',
    source_reference TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS supplier_payments (
    id BIGSERIAL PRIMARY KEY,
    payment_no TEXT NOT NULL UNIQUE,
    voucher_no TEXT NOT NULL,
    party_code TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    payment_method TEXT NOT NULL DEFAULT 'Bank',
    reference TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(voucher_no) REFERENCES supplier_vouchers(voucher_no),
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS supplier_invoice_submissions (
    id BIGSERIAL PRIMARY KEY,
    submission_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    source_channel TEXT NOT NULL DEFAULT 'By Hand',
    external_invoice_no TEXT NOT NULL,
    period_month TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    subtotal DOUBLE PRECISION NOT NULL DEFAULT 0,
    vat_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    invoice_attachment_path TEXT,
    timesheet_attachment_path TEXT,
    notes TEXT,
    review_status TEXT NOT NULL DEFAULT 'Pending',
    review_note TEXT,
    reviewed_by TEXT,
    reviewed_at TIMESTAMP,
    linked_voucher_no TEXT,
    created_by_role TEXT,
    created_by_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code),
    FOREIGN KEY(linked_voucher_no) REFERENCES supplier_vouchers(voucher_no)
);

CREATE TABLE IF NOT EXISTS supplier_partnership_entries (
    id BIGSERIAL PRIMARY KEY,
    entry_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    asset_code TEXT NOT NULL,
    period_month TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    entry_kind TEXT NOT NULL DEFAULT 'Vehicle Expense',
    expense_head TEXT,
    shift_label TEXT NOT NULL DEFAULT 'General',
    driver_name TEXT,
    paid_by TEXT NOT NULL DEFAULT 'Company',
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code),
    FOREIGN KEY(asset_code) REFERENCES supplier_assets(asset_code)
);

CREATE TABLE IF NOT EXISTS agreements (
    id BIGSERIAL PRIMARY KEY,
    agreement_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    agreement_kind TEXT NOT NULL DEFAULT 'Customer',
    start_date TEXT NOT NULL,
    end_date TEXT,
    rate_type TEXT,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    scope TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS lpos (
    id BIGSERIAL PRIMARY KEY,
    lpo_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    agreement_no TEXT,
    issue_date TEXT NOT NULL,
    valid_until TEXT,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'Open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS hire_records (
    id BIGSERIAL PRIMARY KEY,
    hire_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    agreement_no TEXT,
    lpo_no TEXT,
    entry_date TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'Supplier Hire',
    asset_name TEXT NOT NULL,
    asset_type TEXT,
    unit_type TEXT NOT NULL DEFAULT 'Days',
    quantity DOUBLE PRECISION NOT NULL DEFAULT 1,
    rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    subtotal DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Open',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS account_invoices (
    id BIGSERIAL PRIMARY KEY,
    invoice_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    agreement_no TEXT,
    lpo_no TEXT,
    hire_no TEXT,
    invoice_kind TEXT NOT NULL DEFAULT 'Sales',
    document_type TEXT NOT NULL DEFAULT 'Tax Invoice',
    issue_date TEXT NOT NULL,
    due_date TEXT,
    subtotal DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    paid_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    balance_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Open',
    pdf_path TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS account_invoice_lines (
    id BIGSERIAL PRIMARY KEY,
    invoice_no TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantity DOUBLE PRECISION NOT NULL DEFAULT 1,
    unit_label TEXT,
    rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    subtotal DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(invoice_no) REFERENCES account_invoices(invoice_no)
);

CREATE TABLE IF NOT EXISTS account_payments (
    id BIGSERIAL PRIMARY KEY,
    voucher_no TEXT NOT NULL UNIQUE,
    invoice_no TEXT,
    party_code TEXT NOT NULL,
    payment_kind TEXT NOT NULL DEFAULT 'Received',
    entry_date TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    payment_method TEXT NOT NULL DEFAULT 'Bank',
    reference TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS loan_entries (
    id BIGSERIAL PRIMARY KEY,
    loan_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    loan_type TEXT NOT NULL DEFAULT 'Given',
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    payment_method TEXT NOT NULL DEFAULT 'Cash',
    reference TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS annual_fee_entries (
    id BIGSERIAL PRIMARY KEY,
    fee_no TEXT NOT NULL UNIQUE,
    party_code TEXT NOT NULL,
    fee_type TEXT NOT NULL DEFAULT 'Visa',
    description TEXT,
    vehicle_no TEXT,
    due_date TEXT NOT NULL,
    annual_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    received_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    balance_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Due',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS vehicle_master (
    id BIGSERIAL PRIMARY KEY,
    vehicle_id TEXT NOT NULL UNIQUE,
    vehicle_no TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,
    make_model TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    shift_mode TEXT NOT NULL DEFAULT 'Single Shift',
    ownership_mode TEXT NOT NULL DEFAULT 'Standard',
    source_type TEXT NOT NULL DEFAULT 'Own Fleet Vehicle',
    source_party_code TEXT,
    source_asset_code TEXT,
    partner_party_code TEXT,
    partner_name TEXT,
    company_share_percent DOUBLE PRECISION NOT NULL DEFAULT 100,
    partner_share_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS maintenance_staff (
    id BIGSERIAL PRIMARY KEY,
    staff_code TEXT NOT NULL UNIQUE,
    staff_name TEXT NOT NULL,
    phone_number TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS maintenance_staff_advances (
    id BIGSERIAL PRIMARY KEY,
    advance_no TEXT NOT NULL UNIQUE,
    staff_code TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    funding_source TEXT NOT NULL DEFAULT 'Owner Fund',
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    settled_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    balance_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    reference TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(staff_code) REFERENCES maintenance_staff(staff_code)
);

CREATE TABLE IF NOT EXISTS maintenance_papers (
    id BIGSERIAL PRIMARY KEY,
    paper_no TEXT NOT NULL UNIQUE,
    paper_date TEXT NOT NULL,
    vehicle_id TEXT NOT NULL,
    vehicle_no TEXT NOT NULL,
    target_class TEXT NOT NULL DEFAULT 'Own Fleet Vehicle',
    target_party_code TEXT,
    target_asset_code TEXT,
    workshop_party_code TEXT,
    staff_code TEXT,
    advance_no TEXT,
    tax_mode TEXT NOT NULL DEFAULT 'Without Tax',
    supplier_bill_no TEXT,
    work_summary TEXT,
    funding_source TEXT NOT NULL DEFAULT 'Owner Fund',
    paid_by TEXT NOT NULL DEFAULT 'Company',
    subtotal DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    company_share_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    partner_share_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    company_paid_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    partner_paid_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    linked_partnership_entry_no TEXT,
    attachment_path TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(vehicle_id) REFERENCES vehicle_master(vehicle_id),
    FOREIGN KEY(workshop_party_code) REFERENCES parties(party_code),
    FOREIGN KEY(staff_code) REFERENCES maintenance_staff(staff_code),
    FOREIGN KEY(advance_no) REFERENCES maintenance_staff_advances(advance_no)
);

CREATE TABLE IF NOT EXISTS maintenance_paper_lines (
    id BIGSERIAL PRIMARY KEY,
    paper_no TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantity DOUBLE PRECISION NOT NULL DEFAULT 1,
    rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(paper_no) REFERENCES maintenance_papers(paper_no)
);

CREATE TABLE IF NOT EXISTS maintenance_settlements (
    id BIGSERIAL PRIMARY KEY,
    settlement_no TEXT NOT NULL UNIQUE,
    paper_no TEXT NOT NULL,
    settlement_type TEXT NOT NULL DEFAULT 'Direct',
    advance_no TEXT,
    party_code TEXT,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Settled',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(paper_no) REFERENCES maintenance_papers(paper_no),
    FOREIGN KEY(advance_no) REFERENCES maintenance_staff_advances(advance_no),
    FOREIGN KEY(party_code) REFERENCES parties(party_code)
);

CREATE TABLE IF NOT EXISTS import_history (
    id BIGSERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    file_name TEXT NOT NULL,
    imported_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    actor_role TEXT,
    actor_name TEXT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    status TEXT NOT NULL DEFAULT 'success',
    details TEXT,
    ip_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_rate_limits (
    id BIGSERIAL PRIMARY KEY,
    role TEXT NOT NULL,
    identifier TEXT NOT NULL,
    failures INTEGER NOT NULL DEFAULT 0,
    blocked_until TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role, identifier)
);
"""


REQUIRED_COLUMNS = {
    "drivers": {
        "phone_number": "TEXT",
        "pin_hash": "TEXT",
        "photo_data": "TEXT",
        "photo_content_type": "TEXT",
    },
    "driver_transactions": {
        "given_by": "TEXT",
    },
    "salary_slips": {
        "available_advance": "DOUBLE PRECISION NOT NULL DEFAULT 0",
        "remaining_advance": "DOUBLE PRECISION NOT NULL DEFAULT 0",
        "payment_source": "TEXT",
        "paid_by": "TEXT",
    },
    "salary_store": {
        "ot_month": "TEXT",
        "salary_mode": "TEXT NOT NULL DEFAULT 'full'",
        "prorata_start_date": "TEXT",
        "salary_days": "DOUBLE PRECISION NOT NULL DEFAULT 30",
        "daily_rate": "DOUBLE PRECISION NOT NULL DEFAULT 0",
        "monthly_basic_salary": "DOUBLE PRECISION NOT NULL DEFAULT 0",
    },
    "account_invoices": {
        "document_type": "TEXT NOT NULL DEFAULT 'Tax Invoice'",
        "pdf_path": "TEXT",
    },
    "supplier_assets": {
        "double_shift_mode": "TEXT NOT NULL DEFAULT 'Single Shift'",
        "partnership_mode": "TEXT NOT NULL DEFAULT 'Standard'",
        "partner_name": "TEXT",
        "company_share_percent": "DOUBLE PRECISION NOT NULL DEFAULT 100",
        "partner_share_percent": "DOUBLE PRECISION NOT NULL DEFAULT 0",
        "day_shift_paid_by": "TEXT NOT NULL DEFAULT 'Company'",
        "night_shift_paid_by": "TEXT NOT NULL DEFAULT 'Company'",
    },
    "supplier_profile": {
        "supplier_mode": "TEXT NOT NULL DEFAULT 'Normal'",
        "partner_party_code": "TEXT",
        "partner_name": "TEXT",
        "default_company_share_percent": "DOUBLE PRECISION NOT NULL DEFAULT 100",
        "default_partner_share_percent": "DOUBLE PRECISION NOT NULL DEFAULT 0",
    },
    "supplier_portal_accounts": {
        "password_hash": "TEXT",
        "portal_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
        "activation_status": "TEXT NOT NULL DEFAULT 'Invited'",
        "last_login_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    },
    "supplier_vouchers": {
        "source_type": "TEXT NOT NULL DEFAULT 'Timesheet'",
        "source_reference": "TEXT",
    },
    "supplier_invoice_submissions": {
        "source_channel": "TEXT NOT NULL DEFAULT 'By Hand'",
        "period_month": "TEXT NOT NULL DEFAULT ''",
        "vat_amount": "DOUBLE PRECISION NOT NULL DEFAULT 0",
        "invoice_attachment_path": "TEXT",
        "timesheet_attachment_path": "TEXT",
        "review_status": "TEXT NOT NULL DEFAULT 'Pending'",
        "review_note": "TEXT",
        "reviewed_by": "TEXT",
        "reviewed_at": "TIMESTAMP",
        "linked_voucher_no": "TEXT",
        "created_by_role": "TEXT",
        "created_by_name": "TEXT",
    },
    "supplier_partnership_entries": {
        "source_type": "TEXT",
        "source_reference": "TEXT",
    },
    "vehicle_master": {
        "source_type": "TEXT NOT NULL DEFAULT 'Own Fleet Vehicle'",
        "source_party_code": "TEXT",
        "source_asset_code": "TEXT",
    },
    "maintenance_papers": {
        "target_class": "TEXT NOT NULL DEFAULT 'Own Fleet Vehicle'",
        "target_party_code": "TEXT",
        "target_asset_code": "TEXT",
        "linked_partnership_entry_no": "TEXT",
    },
}


class Record(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class QueryResult:
    def __init__(self, cursor, backend: str):
        self.cursor = cursor
        self.backend = backend

    def fetchone(self):
        row = self.cursor.fetchone()
        return _to_record(row, self.cursor.description)

    def fetchall(self):
        return [_to_record(row, self.cursor.description) for row in self.cursor.fetchall()]


class DatabaseAdapter:
    def __init__(self, connection, backend: str):
        self.connection = connection
        self.backend = backend

    def execute(self, query: str, params=()):
        cursor = self.connection.cursor()
        cursor.execute(_prepare_query(query, self.backend), params or ())
        return QueryResult(cursor, self.backend)

    def executemany(self, query: str, params_seq):
        cursor = self.connection.cursor()
        cursor.executemany(_prepare_query(query, self.backend), params_seq)
        return QueryResult(cursor, self.backend)

    def executescript(self, script: str):
        if self.backend == "sqlite":
            self.connection.executescript(script)
            return
        cursor = self.connection.cursor()
        for statement in [part.strip() for part in script.split(";") if part.strip()]:
            cursor.execute(statement)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def init_db(app: Flask) -> None:
    database_url = (app.config.get("DATABASE_URL") or "").strip()
    database_file = app.config.get("DATABASE", "payroll.db")

    if database_url:
        app.config["DATABASE_BACKEND"] = "postgres"
        app.config["DATABASE_URL"] = _normalize_database_url(database_url)
        app.config["DATABASE_PATH"] = None
        db = DatabaseAdapter(_connect_postgres(app.config["DATABASE_URL"]), "postgres")
        try:
            db.executescript(POSTGRES_SCHEMA)
            _ensure_columns(db)
            db.commit()
        finally:
            db.close()
    else:
        database_path = Path(database_file)
        if not database_path.is_absolute():
            database_path = Path(app.root_path).parent / database_path
        app.config["DATABASE_BACKEND"] = "sqlite"
        app.config["DATABASE_PATH"] = database_path
        db = DatabaseAdapter(_connect_sqlite(database_path), "sqlite")
        try:
            db.executescript(SQLITE_SCHEMA)
            _ensure_columns(db)
            db.commit()
        finally:
            db.close()

    app.teardown_appcontext(close_db)


def open_db():
    if "db" not in g:
        backend = current_app.config.get("DATABASE_BACKEND", "sqlite")
        if backend == "postgres":
            connection = _connect_postgres(current_app.config["DATABASE_URL"])
        else:
            connection = _connect_sqlite(current_app.config["DATABASE_PATH"])
        g.db = DatabaseAdapter(connection, backend)
    return g.db


def close_db(exception=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _connect_sqlite(database_path: Path):
    connection = sqlite3.connect(database_path)
    connection.row_factory = _sqlite_row_factory
    return connection


def _connect_postgres(database_url: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            'Postgres mode requires psycopg. Install it with pip install "psycopg[binary]".'
        ) from exc

    return psycopg.connect(database_url)


def _sqlite_row_factory(cursor, row):
    return Record((column[0], row[index]) for index, column in enumerate(cursor.description))


def _to_record(row, description):
    if row is None:
        return None
    if isinstance(row, Record):
        return row
    if hasattr(row, "keys"):
        return Record((key, row[key]) for key in row.keys())
    return Record((column[0], row[index]) for index, column in enumerate(description or []))


def _prepare_query(query: str, backend: str) -> str:
    if backend == "postgres":
        return query.replace("?", "%s")
    return query


def _normalize_database_url(value: str) -> str:
    if value.startswith("postgres://"):
        return "postgresql://" + value[len("postgres://") :]
    return value


def _ensure_columns(db: DatabaseAdapter) -> None:
    for table_name, columns in REQUIRED_COLUMNS.items():
        existing_columns = _existing_columns(db, table_name)
        for column_name, column_type in columns.items():
            if column_name in existing_columns:
                continue
            db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _existing_columns(db: DatabaseAdapter, table_name: str) -> set[str]:
    if db.backend == "sqlite":
        rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row["name"] for row in rows}

    rows = db.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ?
        """,
        (table_name,),
    ).fetchall()
    return {row["column_name"] for row in rows}
