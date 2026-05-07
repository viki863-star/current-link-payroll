#!/usr/bin/env python3
"""
Detailed debug script for inquiry functionality
"""
import sqlite3
import sys

print("=== Detailed Inquiry Debug ===")

conn = sqlite3.connect('payroll.db')
cursor = conn.cursor()

# 1. Check table exists
cursor.execute('SELECT name FROM sqlite_master WHERE type="table" AND name="supplier_inquiries"')
table = cursor.fetchone()
print(f"1. Table 'supplier_inquiries' exists: {table}")

if not table:
    print("ERROR: Table doesn't exist!")
    sys.exit(1)

# 2. Check row count
cursor.execute('SELECT COUNT(*) FROM supplier_inquiries')
count = cursor.fetchone()[0]
print(f"2. Row count: {count}")

# 3. Show all rows
if count > 0:
    print(f"3. Showing all {count} rows:")
    cursor.execute('SELECT inquiry_no, party_code, subject, status, created_at FROM supplier_inquiries')
    rows = cursor.fetchall()
    for i, row in enumerate(rows, 1):
        print(f"   {i}. {row}")
else:
    print("3. No rows in table")

# 4. Check if INQ-TEST-001 exists
cursor.execute('SELECT * FROM supplier_inquiries WHERE inquiry_no = ?', ('INQ-TEST-001',))
test_row = cursor.fetchone()
print(f"4. INQ-TEST-001 exists: {test_row is not None}")

# 5. Try to insert with different ID
print("\n5. Testing insert with new ID...")
try:
    cursor.execute('''
        INSERT INTO supplier_inquiries (
            inquiry_no, party_code, inquiry_date, subject, description,
            priority, status, due_date, response_deadline, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        'INQ-TEST-002',
        'PTY-0001',
        '2026-04-30',
        'Test Subject 2',
        'Test Description 2',
        'High',
        'Open',
        '2026-05-20',
        '2026-05-15',
        'Debug Script'
    ))
    conn.commit()
    print("   Insert successful!")
    
    cursor.execute('SELECT COUNT(*) FROM supplier_inquiries')
    new_count = cursor.fetchone()[0]
    print(f"   New row count: {new_count}")
    
    # Clean up
    cursor.execute('DELETE FROM supplier_inquiries WHERE inquiry_no = ?', ('INQ-TEST-002',))
    conn.commit()
    print("   Test record cleaned up")
except Exception as e:
    print(f"   Error: {e}")
    import traceback
    traceback.print_exc()

# 6. Check _next_reference_code function
print("\n6. Testing _next_reference_code simulation...")
cursor.execute('SELECT MAX(inquiry_no) FROM supplier_inquiries WHERE inquiry_no LIKE "INQ%"')
max_inq = cursor.fetchone()[0]
print(f"   Max inquiry_no: {max_inq}")

conn.close()
print("\n=== Debug complete ===")