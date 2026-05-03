#!/usr/bin/env python3
"""
Test the technician_jobs query to ensure it works without SQL errors.
"""

import sqlite3
import sys
from pathlib import Path

def get_database_path():
    """Get the database path from environment or default."""
    db_path = Path("payroll.db")
    if not db_path.exists():
        # Try to find it in the current directory
        db_path = Path("app/payroll.db")
    if not db_path.exists():
        print("ERROR: Database file not found")
        sys.exit(1)
    return db_path

def test_technician_jobs_query():
    """Test the exact query from technician_jobs() function."""
    db_path = get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # This is the exact query from routes.py (simplified)
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
            mp.review_status, mp.approved_by, mp.approved_at, mp.rejection_reason,
            mp.payment_status, mp.created_at, mp.attachment_path as bill_image,
            COALESCE(wp.party_name, mp.workshop_party_code) as workshop_name,
            mp.work_type
        FROM maintenance_papers mp
        LEFT JOIN vehicle_master vm ON mp.vehicle_id = vm.vehicle_id
        LEFT JOIN technicians t ON mp.technician_code = t.technician_code
        LEFT JOIN parties p ON t.party_code = p.party_code
        LEFT JOIN parties wp ON mp.workshop_party_code = wp.party_code
        WHERE mp.technician_code IS NOT NULL
        ORDER BY mp.paper_date DESC, mp.paper_no DESC LIMIT 5
    """
    
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        
        print(f"SUCCESS: Query executed without errors")
        print(f"Found {len(results)} maintenance papers with technician_code")
        
        if results:
            print("\nFirst result:")
            for key in results[0].keys():
                print(f"  {key}: {results[0][key]}")
        
        # Also check if there are any maintenance papers with technician_code
        cursor.execute("SELECT COUNT(*) as count FROM maintenance_papers WHERE technician_code IS NOT NULL")
        count_row = cursor.fetchone()
        print(f"\nTotal maintenance papers with technician_code: {count_row['count']}")
        
        return True
        
    except sqlite3.Error as e:
        print(f"ERROR: Query failed: {e}")
        return False

def check_tables_exist():
    """Check if all required tables exist."""
    db_path = get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    tables = ["maintenance_papers", "vehicle_master", "technicians", "parties"]
    missing = []
    
    for table in tables:
        try:
            cursor.execute(f"SELECT 1 FROM {table} LIMIT 1")
        except sqlite3.Error:
            missing.append(table)
    
    if missing:
        print(f"ERROR: Missing tables: {missing}")
        return False
    else:
        print("SUCCESS: All required tables exist")
        return True

def main():
    print("=== Testing Technician Jobs Query ===\n")
    
    # Check tables
    print("1. Checking required tables...")
    tables_ok = check_tables_exist()
    
    # Test query
    print("\n2. Testing technician_jobs query...")
    query_ok = test_technician_jobs_query()
    
    print("\n=== Summary ===")
    if tables_ok and query_ok:
        print("SUCCESS: Technician jobs page should work correctly")
        print("The SQL error 'no such column: mp.approved_by' should be resolved")
    else:
        print("ISSUES FOUND: Need to fix database schema or query")

if __name__ == "__main__":
    main()