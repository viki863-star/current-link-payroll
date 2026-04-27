#!/usr/bin/env python3
"""
Test script to verify technician system fixes:
1. Check if maintenance_papers table has required columns
2. Test password hashing
3. Test technician creation and login
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

def check_maintenance_papers_columns():
    """Check if maintenance_papers table has the required columns."""
    db_path = get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get table info
    cursor.execute("PRAGMA table_info(maintenance_papers)")
    columns = [row["name"] for row in cursor.fetchall()]
    
    required_columns = ["approved_by", "approved_at", "rejection_reason"]
    missing = [col for col in required_columns if col not in columns]
    
    if missing:
        print(f"ERROR: Missing columns in maintenance_papers: {missing}")
        print(f"Existing columns: {columns}")
        return False
    else:
        print(f"SUCCESS: All required columns exist in maintenance_papers")
        return True

def test_password_hashing():
    """Test that password hashing works correctly."""
    password = "1234"
    hash1 = generate_password_hash(password)
    hash2 = generate_password_hash(password)
    
    # Hashes should be different (different salt)
    if hash1 == hash2:
        print("WARNING: Two hashes of same password are identical (unexpected)")
    
    # Both should verify correctly
    if check_password_hash(hash1, password) and check_password_hash(hash2, password):
        print("SUCCESS: Password hashing and verification works")
        return True
    else:
        print("ERROR: Password verification failed")
        return False

def check_existing_technician():
    """Check if technician Amjad5 exists and examine password hash."""
    db_path = get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT technician_code, user_id, password_hash FROM technicians WHERE user_id = 'Amjad5' OR technician_code = 'Amjad5'")
    tech = cursor.fetchone()
    
    if tech:
        print(f"Found technician: {tech['technician_code']} (user_id: {tech['user_id']})")
        print(f"Password hash: {tech['password_hash'][:50]}...")
        
        # Check if it's a plain text password
        password_hash = tech['password_hash']
        if password_hash == "1234":
            print("WARNING: Password is stored as plain text '1234'")
            print("You need to update the password hash for this technician")
            return False
        elif check_password_hash(password_hash, "1234"):
            print("SUCCESS: Password hash is valid for password '1234'")
            return True
        else:
            print("WARNING: Password hash doesn't match '1234'")
            return False
    else:
        print("INFO: Technician Amjad5 not found")
        return None

def main():
    print("=== Testing Technician System Fixes ===\n")
    
    # Test 1: Check maintenance_papers columns
    print("1. Checking maintenance_papers table columns...")
    cols_ok = check_maintenance_papers_columns()
    
    # Test 2: Test password hashing
    print("\n2. Testing password hashing...")
    hash_ok = test_password_hashing()
    
    # Test 3: Check existing technician
    print("\n3. Checking existing technician Amjad5...")
    tech_ok = check_existing_technician()
    
    print("\n=== Summary ===")
    if cols_ok:
        print("✓ maintenance_papers table has required columns")
    else:
        print("✗ maintenance_papers table missing columns")
        
    if hash_ok:
        print("✓ Password hashing works correctly")
    else:
        print("✗ Password hashing issue")
    
    if tech_ok is None:
        print("ℹ Technician Amjad5 not found (create a new one to test)")
    elif tech_ok:
        print("✓ Technician Amjad5 has valid password hash")
    else:
        print("✗ Technician Amjad5 has invalid password (needs update)")
    
    # Recommendations
    print("\n=== Recommendations ===")
    if not cols_ok:
        print("1. Start the Flask app to trigger database migration")
        print("   The REQUIRED_COLUMNS update will add missing columns")
    
    if tech_ok is False:
        print("2. Update Amjad5's password in the technicians admin page")
        print("   Or run: UPDATE technicians SET password_hash = ? WHERE user_id = 'Amjad5'")
        print(f"   Hash for '1234': {generate_password_hash('1234')}")
    
    print("\n3. Restart the Flask application for changes to take effect")

if __name__ == "__main__":
    main()