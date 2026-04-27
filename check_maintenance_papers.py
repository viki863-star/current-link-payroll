#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('payroll.db')
cursor = conn.cursor()

# Check if maintenance_papers table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='maintenance_papers'")
table_exists = cursor.fetchone()
if table_exists:
    print("maintenance_papers table exists")
    
    # Get column info
    cursor.execute("PRAGMA table_info(maintenance_papers)")
    columns = cursor.fetchall()
    
    print("\nColumns in maintenance_papers table:")
    for col in columns:
        print(f"  {col[1]:30} {col[2]:15} NOT NULL: {col[3]}")
        
    # Check if technician_code column exists
    has_technician_code = any(col[1] == 'technician_code' for col in columns)
    print(f"\nHas technician_code column: {has_technician_code}")
    
    # Check if there's a typo like 'technician_code' vs 'technician_code'
    for col in columns:
        if 'technician' in col[1].lower():
            print(f"  Found similar column: {col[1]}")
else:
    print("maintenance_papers table does not exist")

conn.close()