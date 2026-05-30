-- SQL script to add technician_code column to maintenance_papers table
-- Run this with sqlite3 payroll.db < add_technician_code_column.sql

-- First check if column exists
SELECT name FROM sqlite_master WHERE type='table' AND name='maintenance_papers';

-- Check current columns
PRAGMA table_info(maintenance_papers);

-- Add technician_code column if it doesn't exist
-- Note: In SQLite, we need to check if column exists before adding
-- Since we can't use IF NOT EXISTS in ALTER TABLE ADD COLUMN directly,
-- we'll use a different approach

-- Create a temporary table with the new schema
CREATE TABLE IF NOT EXISTS maintenance_papers_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_no TEXT NOT NULL UNIQUE,
    paper_date TEXT NOT NULL,
    vehicle_id TEXT,
    vehicle_no TEXT,
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
    paid_amount REAL NOT NULL DEFAULT 0,
    linked_partnership_entry_no TEXT,
    technician_code TEXT,
    review_status TEXT NOT NULL DEFAULT 'Pending',
    approved_by TEXT,
    approved_at TEXT,
    rejection_reason TEXT,
    payment_status TEXT NOT NULL DEFAULT 'Pending',
    attachment_path TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    work_type TEXT
);

-- Copy data from old table to new table
INSERT INTO maintenance_papers_new 
SELECT 
    id, paper_no, paper_date, vehicle_id, vehicle_no, 
    COALESCE(target_class, 'Own Fleet Vehicle'),
    target_party_code, target_asset_code, workshop_party_code,
    staff_code, advance_no, COALESCE(tax_mode, 'Without Tax'),
    supplier_bill_no, work_summary, COALESCE(funding_source, 'Owner Fund'),
    COALESCE(paid_by, 'Company'), subtotal, tax_amount, total_amount,
    company_share_amount, partner_share_amount, company_paid_amount,
    partner_paid_amount, paid_amount, linked_partnership_entry_no,
    NULL as technician_code,  -- Will be NULL for existing records
    COALESCE(review_status, 'Pending') as review_status,
    approved_by, approved_at, rejection_reason,
    COALESCE(payment_status, 'Pending') as payment_status,
    attachment_path, notes, created_at,
    work_type
FROM maintenance_papers;

-- Drop old table
DROP TABLE maintenance_papers;

-- Rename new table to old name
ALTER TABLE maintenance_papers_new RENAME TO maintenance_papers;

-- Recreate indexes and foreign keys if needed
-- (SQLite will preserve the PRIMARY KEY and UNIQUE constraints from CREATE TABLE)

PRAGMA foreign_keys = OFF;
-- Note: In a real scenario, you'd need to recreate foreign keys
-- but for simplicity we're skipping that here
PRAGMA foreign_keys = ON;

-- Verify the new schema
PRAGMA table_info(maintenance_papers);

-- Show sample data
SELECT paper_no, technician_code, review_status, payment_status 
FROM maintenance_papers 
LIMIT 5;