#!/usr/bin/env python3
"""
Manually trigger schema migration to add missing columns.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

# Create app which will trigger init_db
app = create_app()

# The init_db function should have been called during app creation
# which runs _ensure_columns to add missing columns

print("Schema migration should have been triggered.")
print("Check if maintenance_papers table now has technician_code column.")

# Now let's verify
import sqlite3
conn = sqlite3.connect('payroll.db')
cursor = conn.cursor()

# Check maintenance_papers table
cursor.execute("PRAGMA table_info(maintenance_papers)")
columns = cursor.fetchall()

print("\nColumns in maintenance_papers table:")
for col in columns:
    print(f"  {col[1]:30} {col[2]:15} NOT NULL: {col[3]}")

# Check if technician_code exists
has_tech_code = any(col[1] == 'technician_code' for col in columns)
print(f"\nHas technician_code column: {has_tech_code}")

# Check technicians table
cursor.execute("PRAGMA table_info(technicians)")
tech_columns = cursor.fetchall()

print("\nColumns in technicians table:")
for col in tech_columns:
    print(f"  {col[1]:30} {col[2]:15} NOT NULL: {col[3]}")

conn.close()

if has_tech_code:
    print("\n✓ Schema migration successful!")
else:
    print("\n✗ technician_code column still missing. Manual intervention may be needed.")