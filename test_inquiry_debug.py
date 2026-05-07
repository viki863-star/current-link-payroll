#!/usr/bin/env python3
"""
Debug script for inquiry functionality
"""
import sqlite3
from datetime import date

print("=== Testing Inquiry Functionality ===")

# Connect to database
conn = sqlite3.connect('payroll.db')
cursor = conn.cursor()

# Check if table exists
cursor.execute('SELECT name FROM sqlite_master WHERE type="table" AND name="supplier_inquiries"')
table_exists = cursor.fetchone()
print(f"1. Table exists: {table_exists}")

if table_exists:
    # Check row count
    cursor.execute('SELECT COUNT(*) FROM supplier_inquiries')
    count = cursor.fetchone()[0]
    print(f"2. Row count: {count}")
    
    # Check table schema
    cursor.execute('PRAGMA table_info(supplier_inquiries)')
    columns = cursor.fetchall()
    print(f"3. Table has {len(columns)} columns:")
    for col in columns:
        print(f"   {col}")
    
    # Try to insert a test record
    print("\n4. Testing manual insert...")
    try:
        cursor.execute('''
            INSERT INTO supplier_inquiries (
                inquiry_no, party_code, inquiry_date, subject, description,
                priority, status, due_date, response_deadline, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            'INQ-TEST-001',
            'PTY-0001',
            date.today().isoformat(),
            'Test Subject',
            'Test Description',
            'Normal',
            'Open',
            '2026-05-15',
            '2026-05-10',
            'Test Admin'
        ))
        conn.commit()
        print("   Insert successful!")
        
        cursor.execute('SELECT COUNT(*) FROM supplier_inquiries')
        new_count = cursor.fetchone()[0]
        print(f"   New row count: {new_count}")
        
        # Clean up
        cursor.execute('DELETE FROM supplier_inquiries WHERE inquiry_no = ?', ('INQ-TEST-001',))
        conn.commit()
        print("   Test record cleaned up")
    except Exception as e:
        print(f"   Error during insert: {e}")
        import traceback
        traceback.print_exc()

# Check if PTY-0001 exists
print("\n5. Checking if PTY-0001 exists in parties table...")
cursor.execute('SELECT party_code, party_name FROM parties WHERE party_code = ?', ('PTY-0001',))
party = cursor.fetchone()
print(f"   Party PTY-0001: {party}")

conn.close()
print("\n=== Debug complete ===")