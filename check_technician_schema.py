#!/usr/bin/env python3
"""
Check the database schema for technician system implementation.
"""

import sqlite3
import os

def check_maintenance_papers_schema():
    """Check if maintenance_papers table has all required columns."""
    db_path = "payroll.db"
    if not os.path.exists(db_path):
        print(f"Database file {db_path} not found.")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check maintenance_papers columns
    cursor.execute("PRAGMA table_info(maintenance_papers)")
    columns = cursor.fetchall()
    
    print("Maintenance Papers Table Columns:")
    print("-" * 80)
    for col in columns:
        col_id, col_name, col_type, not_null, default_val, pk = col
        print(f"  {col_id:2}. {col_name:30} {col_type:20} {'NOT NULL' if not_null else 'NULL':10} DEFAULT={default_val or 'NULL'}")
    
    # Check for specific columns we added
    required_columns = [
        "technician_code",
        "review_status", 
        "approved_by",
        "approved_at",
        "rejection_reason",
        "payment_status",
        "paid_amount",
        "company_share_amount",
        "partner_share_amount",
        "company_paid_amount",
        "partner_paid_amount"
    ]
    
    print("\nChecking required columns:")
    existing_cols = [col[1] for col in columns]
    for req_col in required_columns:
        if req_col in existing_cols:
            print(f"  ✓ {req_col}")
        else:
            print(f"  ✗ {req_col} - MISSING!")
    
    # Check technicians table
    print("\n" + "=" * 80)
    print("Technicians Table Columns:")
    print("-" * 80)
    try:
        cursor.execute("PRAGMA table_info(technicians)")
        tech_columns = cursor.fetchall()
        for col in tech_columns:
            col_id, col_name, col_type, not_null, default_val, pk = col
            print(f"  {col_id:2}. {col_name:30} {col_type:20} {'NOT NULL' if not_null else 'NULL':10} DEFAULT={default_val or 'NULL'}")
    except sqlite3.OperationalError:
        print("  Technicians table does not exist!")
    
    conn.close()

def check_sample_data():
    """Check if there's any sample data in the tables."""
    conn = sqlite3.connect("payroll.db")
    cursor = conn.cursor()
    
    print("\n" + "=" * 80)
    print("Sample Data Counts:")
    print("-" * 80)
    
    # Check technicians count
    try:
        cursor.execute("SELECT COUNT(*) FROM technicians")
        tech_count = cursor.fetchone()[0]
        print(f"Technicians: {tech_count}")
    except sqlite3.OperationalError:
        print("Technicians: Table does not exist")
    
    # Check maintenance_papers with technician_code count
    try:
        cursor.execute("SELECT COUNT(*) FROM maintenance_papers WHERE technician_code IS NOT NULL")
        tech_jobs_count = cursor.fetchone()[0]
        print(f"Technician Jobs: {tech_jobs_count}")
        
        cursor.execute("SELECT COUNT(*) FROM maintenance_papers WHERE review_status = 'Pending' AND technician_code IS NOT NULL")
        pending_count = cursor.fetchone()[0]
        print(f"Pending Technician Jobs: {pending_count}")
        
        cursor.execute("SELECT COUNT(*) FROM maintenance_papers WHERE review_status = 'Approved' AND technician_code IS NOT NULL")
        approved_count = cursor.fetchone()[0]
        print(f"Approved Technician Jobs: {approved_count}")
        
        cursor.execute("SELECT COUNT(*) FROM maintenance_papers WHERE payment_status != 'Pending' AND technician_code IS NOT NULL")
        paid_count = cursor.fetchone()[0]
        print(f"Paid/Partial Technician Jobs: {paid_count}")
    except sqlite3.OperationalError as e:
        print(f"Error querying maintenance_papers: {e}")
    
    conn.close()

if __name__ == "__main__":
    print("Checking Technician System Database Schema")
    print("=" * 80)
    check_maintenance_papers_schema()
    check_sample_data()