#!/usr/bin/env python3
"""
Test script to verify technician login and job submission fixes.
"""
import sqlite3
import hashlib
import sys

def test_database_schema():
    """Check if maintenance_papers has technician_code column."""
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    
    # Check maintenance_papers table columns
    cursor.execute("PRAGMA table_info(maintenance_papers)")
    columns = cursor.fetchall()
    
    print("Columns in maintenance_papers table:")
    column_names = []
    for col in columns:
        column_names.append(col[1])
        print(f"  {col[1]:30} {col[2]:15} NOT NULL: {col[3]}")
    
    # Check for technician_code
    has_technician_code = 'technician_code' in column_names
    print(f"\nHas technician_code column: {has_technician_code}")
    
    # Check for review_status and payment_status
    has_review_status = 'review_status' in column_names
    has_payment_status = 'payment_status' in column_names
    print(f"Has review_status column: {has_review_status}")
    print(f"Has payment_status column: {has_payment_status}")
    
    # Check technicians table
    cursor.execute("PRAGMA table_info(technicians)")
    tech_columns = cursor.fetchall()
    
    print("\nColumns in technicians table:")
    for col in tech_columns:
        print(f"  {col[1]:30} {col[2]:15} NOT NULL: {col[3]}")
    
    # Check if technician_code and party_code are nullable
    tech_col_names = [col[1] for col in tech_columns]
    if 'technician_code' in tech_col_names:
        idx = tech_col_names.index('technician_code')
        print(f"\ntechnician_code NOT NULL: {tech_columns[idx][3]} (0 means nullable)")
    
    if 'party_code' in tech_col_names:
        idx = tech_col_names.index('party_code')
        print(f"party_code NOT NULL: {tech_columns[idx][3]} (0 means nullable)")
    
    conn.close()
    return has_technician_code

def test_technician_login():
    """Test technician login with sample data."""
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    
    # Check if technician Amjad5 exists
    cursor.execute("SELECT user_id, password_hash FROM technicians WHERE user_id = ?", ('Amjad5',))
    tech = cursor.fetchone()
    
    if tech:
        user_id, password_hash = tech
        print(f"\nFound technician: {user_id}")
        print(f"Password hash: {password_hash[:20]}...")
        
        # Test password hashing
        test_password = "1234"
        # Check if password is hashed with SHA-256
        test_hash = hashlib.sha256(test_password.encode()).hexdigest()
        
        if password_hash == test_hash:
            print("✓ Password hash matches '1234'")
        else:
            print("✗ Password hash does NOT match '1234'")
            print(f"  Expected: {test_hash}")
            print(f"  Actual:   {password_hash}")
    else:
        print("\n✗ Technician Amjad5 not found in database")
        
        # List all technicians
        cursor.execute("SELECT user_id, technician_code FROM technicians LIMIT 5")
        all_techs = cursor.fetchall()
        print("First 5 technicians:")
        for t in all_techs:
            print(f"  {t[0]} - {t[1]}")
    
    conn.close()

def test_technician_jobs_query():
    """Test the technician jobs query from routes.py."""
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    
    # Try to run a simplified version of the query
    query = """
        SELECT mp.paper_no, mp.technician_code, mp.review_status, mp.payment_status
        FROM maintenance_papers mp
        WHERE mp.technician_code IS NOT NULL
        LIMIT 5
    """
    
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        print(f"\nTechnician jobs query successful, found {len(results)} records")
        for row in results:
            print(f"  Paper: {row[0]}, Tech: {row[1]}, Status: {row[2]}, Payment: {row[3]}")
    except sqlite3.OperationalError as e:
        print(f"\n✗ Technician jobs query failed: {e}")
        
        # Check what columns exist
        cursor.execute("PRAGMA table_info(maintenance_papers)")
        columns = cursor.fetchall()
        col_names = [col[1] for col in columns]
        print("Available columns:", ", ".join(col_names))
    
    conn.close()

def main():
    print("=== Testing Technician System Fixes ===\n")
    
    # Test 1: Database schema
    print("1. Testing database schema...")
    schema_ok = test_database_schema()
    
    # Test 2: Technician login
    print("\n2. Testing technician login...")
    test_technician_login()
    
    # Test 3: Technician jobs query
    print("\n3. Testing technician jobs query...")
    test_technician_jobs_query()
    
    print("\n=== Test Complete ===")
    
    if schema_ok:
        print("✓ Schema appears to be correct")
    else:
        print("✗ Schema issues detected - technician_code column may be missing")

if __name__ == "__main__":
    main()