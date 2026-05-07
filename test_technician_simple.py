#!/usr/bin/env python3
"""
Simple test to verify technician creation works without NOT NULL constraints.
"""

import sqlite3
import hashlib

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def test():
    conn = sqlite3.connect('payroll.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("Testing technician creation without technician_code and party_code...")
    
    # Clean up any existing test technician
    cursor.execute("DELETE FROM technicians WHERE user_id LIKE 'test_tech%'")
    
    # Create a test technician without technician_code and party_code
    test_user_id = "test_tech_simple"
    test_password = "password123"
    password_hash = hash_password(test_password)
    
    cursor.execute("""
        INSERT INTO technicians 
        (user_id, password_hash, phone_number, specialization, status)
        VALUES (?, ?, ?, ?, ?)
    """, (test_user_id, password_hash, "1234567890", "General Mechanic", "Active"))
    
    technician_id = cursor.lastrowid
    print(f"Technician created with ID: {technician_id}")
    
    # Verify
    cursor.execute("SELECT * FROM technicians WHERE id = ?", (technician_id,))
    tech = cursor.fetchone()
    
    print(f"User ID: {tech['user_id']}")
    print(f"Phone: {tech['phone_number']}")
    print(f"Technician Code: {tech['technician_code']}")
    print(f"Party Code: {tech['party_code']}")
    
    if tech['technician_code'] is None and tech['party_code'] is None:
        print("SUCCESS: technician_code and party_code are NULL (constraints removed)")
    else:
        print(f"ERROR: technician_code={tech['technician_code']}, party_code={tech['party_code']}")
    
    # Test login
    cursor.execute("""
        SELECT * FROM technicians 
        WHERE user_id = ? AND password_hash = ? AND status = 'Active'
    """, (test_user_id, password_hash))
    
    login_result = cursor.fetchone()
    if login_result:
        print("SUCCESS: Technician login works")
    else:
        print("ERROR: Technician login failed")
    
    # Clean up
    cursor.execute("DELETE FROM technicians WHERE user_id LIKE 'test_tech%'")
    conn.commit()
    conn.close()
    
    print("\nTest completed successfully!")

if __name__ == "__main__":
    test()