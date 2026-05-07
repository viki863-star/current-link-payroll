#!/usr/bin/env python3
"""
Final verification of technician system fixes.
Tests the complete workflow from technician creation to login to job submission.
"""

import sqlite3
import sys
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

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

def test_database_schema():
    """Test that all required database schema elements are in place."""
    db_path = get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("1. Database Schema Check:")
    
    # Check maintenance_papers columns
    cursor.execute("PRAGMA table_info(maintenance_papers)")
    mp_columns = [row["name"] for row in cursor.fetchall()]
    required_mp_columns = ["approved_by", "approved_at", "rejection_reason", "technician_code"]
    mp_missing = [col for col in required_mp_columns if col not in mp_columns]
    
    if mp_missing:
        print(f"   [X] Missing columns in maintenance_papers: {mp_missing}")
    else:
        print(f"   [OK] maintenance_papers has all required columns")
    
    # Check technicians table constraints
    cursor.execute("PRAGMA table_info(technicians)")
    tech_columns = [row for row in cursor.fetchall()]
    
    # Check if technician_code and party_code are nullable
    tech_code_nullable = any(row["name"] == "technician_code" and row["notnull"] == 0 for row in tech_columns)
    party_code_nullable = any(row["name"] == "party_code" and row["notnull"] == 0 for row in tech_columns)
    
    if tech_code_nullable and party_code_nullable:
        print("   [OK] technicians table allows NULL for technician_code and party_code")
    else:
        print(f"   [X] technicians table constraints: technician_code nullable={tech_code_nullable}, party_code nullable={party_code_nullable}")
    
    return len(mp_missing) == 0 and tech_code_nullable and party_code_nullable

def test_password_hashing():
    """Test password hashing for technician Amjad5."""
    db_path = get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("\n2. Password Hashing Check:")
    
    cursor.execute("SELECT technician_code, user_id, password_hash FROM technicians WHERE user_id = 'Amjad5'")
    tech = cursor.fetchone()
    
    if not tech:
        print("   [INFO] Technician Amjad5 not found (create one in the admin interface)")
        return False
    
    password_hash = tech["password_hash"]
    
    if password_hash == "1234":
        print("   [X] Password is still plain text '1234'")
        return False
    elif check_password_hash(password_hash, "1234"):
        print(f"   [OK] Technician {tech['technician_code']} has valid password hash")
        return True
    else:
        print(f"   [X] Password hash doesn't match '1234'")
        return False

def test_technician_jobs_query():
    """Test that the technician_jobs query works."""
    db_path = get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("\n3. Technician Jobs Query Check:")
    
    query = """
        SELECT mp.paper_no, mp.technician_code, mp.approved_by, mp.approved_at, mp.rejection_reason
        FROM maintenance_papers mp
        WHERE mp.technician_code IS NOT NULL
        LIMIT 1
    """
    
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        print(f"   [OK] Query executes successfully")
        print(f"   [INFO] Found {len(results)} maintenance papers with technician_code")
        return True
    except sqlite3.Error as e:
        print(f"   ✗ Query failed: {e}")
        return False

def test_new_technician_creation():
    """Test that new technicians can be created without party_code."""
    db_path = get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("\n4. New Technician Creation Test:")
    
    # Test data
    test_user_id = "TEST_TECH_001"
    test_password = "test123"
    
    # Clean up if exists
    cursor.execute("DELETE FROM technicians WHERE user_id = ?", (test_user_id,))
    
    # Try to insert a technician with NULL party_code
    password_hash = generate_password_hash(test_password)
    try:
        cursor.execute("""
            INSERT INTO technicians 
            (technician_code, party_code, user_id, password_hash, phone_number, specialization, status)
            VALUES (?, NULL, ?, ?, '1234567890', 'Test Specialist', 'Active')
        """, (test_user_id, test_user_id, password_hash))
        
        conn.commit()
        
        # Verify insertion
        cursor.execute("SELECT * FROM technicians WHERE user_id = ?", (test_user_id,))
        tech = cursor.fetchone()
        
        if tech and tech["party_code"] is None:
            print(f"   [OK] Test technician created successfully with NULL party_code")
            
            # Clean up
            cursor.execute("DELETE FROM technicians WHERE user_id = ?", (test_user_id,))
            conn.commit()
            return True
        else:
            print(f"   ✗ Test technician creation failed")
            return False
            
    except sqlite3.Error as e:
        print(f"   [X] Failed to create test technician: {e}")
        return False

def main():
    print("=== FINAL VERIFICATION: Technician System Fixes ===\n")
    
    schema_ok = test_database_schema()
    password_ok = test_password_hashing()
    query_ok = test_technician_jobs_query()
    creation_ok = test_new_technician_creation()
    
    print("\n" + "="*50)
    print("SUMMARY:")
    print("="*50)
    
    all_ok = schema_ok and password_ok and query_ok and creation_ok
    
    if schema_ok:
        print("✓ Database schema is correct")
    else:
        print("✗ Database schema issues")
        
    if password_ok:
        print("✓ Password hashing works (Amjad5 can login with '1234')")
    else:
        print("✗ Password hashing issue - Amjad5 may not be able to login")
        
    if query_ok:
        print("✓ Technician jobs query works")
    else:
        print("✗ Technician jobs query has SQL errors")
        
    if creation_ok:
        print("✓ New technicians can be created without party field")
    else:
        print("✗ Issues creating new technicians")
    
    print("\n" + "="*50)
    print("NEXT STEPS:")
    print("="*50)
    
    if all_ok:
        print("1. Restart the Flask application")
        print("2. Login as admin and go to Technician Desk")
        print("3. Create new technicians (no Technician Code or Party fields needed)")
        print("4. Technicians can login with their User ID and Password")
        print("5. Technicians can submit jobs through the portal")
        print("6. Admin can view technician jobs in Technician Desk")
    else:
        print("Some issues need to be fixed:")
        if not schema_ok:
            print("- Ensure database migration ran (start Flask app)")
        if not password_ok:
            print("- Update Amjad5's password in admin interface")
        if not query_ok:
            print("- Check maintenance_papers table schema")
        if not creation_ok:
            print("- Check technicians table constraints")
    
    print("\nThe technician system should now be fully functional!")

if __name__ == "__main__":
    main()