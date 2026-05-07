#!/usr/bin/env python3
"""
Manually add missing columns to maintenance_papers table.
"""
import sqlite3
import sys

def add_missing_columns():
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    
    # Check current columns
    cursor.execute("PRAGMA table_info(maintenance_papers)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    
    print("Existing columns:", ", ".join(sorted(existing_columns)))
    
    # Columns to add
    columns_to_add = [
        ("technician_code", "TEXT"),
        ("review_status", "TEXT NOT NULL DEFAULT 'Pending'"),
        ("payment_status", "TEXT NOT NULL DEFAULT 'Pending'"),
    ]
    
    for column_name, column_type in columns_to_add:
        if column_name not in existing_columns:
            print(f"Adding column: {column_name} {column_type}")
            try:
                # SQLite doesn't support IF NOT EXISTS for ADD COLUMN
                # We'll just try to add it and catch the error if it already exists
                cursor.execute(f"ALTER TABLE maintenance_papers ADD COLUMN {column_name} {column_type}")
                print(f"  ✓ Added {column_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    print(f"  Column {column_name} already exists")
                else:
                    print(f"  Error: {e}")
        else:
            print(f"Column {column_name} already exists")
    
    # Verify
    cursor.execute("PRAGMA table_info(maintenance_papers)")
    columns = cursor.fetchall()
    
    print("\nFinal schema:")
    for col in columns:
        print(f"  {col[1]:30} {col[2]:20} NOT NULL: {col[3]}")
    
    # Check if technician_code exists now
    has_tech_code = any(col[1] == 'technician_code' for col in columns)
    
    conn.commit()
    conn.close()
    
    return has_tech_code

def test_technician_jobs_query():
    """Test if the technician jobs query works now."""
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    
    print("\nTesting technician jobs query...")
    query = """
        SELECT mp.paper_no, mp.technician_code, mp.review_status, mp.payment_status
        FROM maintenance_papers mp
        WHERE mp.technician_code IS NOT NULL
        LIMIT 5
    """
    
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        print(f"✓ Query successful, found {len(results)} records")
        for row in results:
            print(f"  Paper: {row[0]}, Tech: {row[1]}, Status: {row[2]}, Payment: {row[3]}")
    except sqlite3.OperationalError as e:
        print(f"✗ Query failed: {e}")
        
        # Show what columns exist
        cursor.execute("PRAGMA table_info(maintenance_papers)")
        columns = cursor.fetchall()
        col_names = [col[1] for col in columns]
        print("Available columns:", ", ".join(col_names))
    
    conn.close()

def main():
    print("=== Adding missing columns to maintenance_papers table ===\n")
    
    success = add_missing_columns()
    
    if success:
        print("\n✓ Columns added successfully")
        test_technician_jobs_query()
    else:
        print("\n✗ Failed to add columns")
    
    print("\n=== Done ===")

if __name__ == "__main__":
    main()