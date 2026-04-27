#!/usr/bin/env python3
"""Check the current technicians table schema."""

import sqlite3
import os

def check_technician_schema():
    """Check if technicians table has been modified correctly."""
    db_path = "payroll.db"
    if not os.path.exists(db_path):
        print(f"Database file {db_path} not found")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check table info
    cursor.execute('PRAGMA table_info(technicians)')
    columns = cursor.fetchall()
    
    print("Technicians table columns:")
    print("-" * 60)
    for col in columns:
        col_id, name, type_, notnull, default_value, pk = col
        nullable = "NULL" if notnull == 0 else "NOT NULL"
        print(f"  {name:20} {type_:15} {nullable:10} PK: {pk}")
    
    # Check foreign key constraints
    cursor.execute("PRAGMA foreign_key_list(technicians)")
    fks = cursor.fetchall()
    
    print("\nForeign key constraints:")
    print("-" * 60)
    if fks:
        for fk in fks:
            print(f"  Column: {fk[3]} -> {fk[2]}.{fk[4]}")
    else:
        print("  No foreign key constraints")
    
    # Check sample data
    cursor.execute("SELECT COUNT(*) FROM technicians")
    count = cursor.fetchone()[0]
    print(f"\nTotal technicians in database: {count}")
    
    if count > 0:
        cursor.execute("SELECT technician_code, party_code, user_id, status FROM technicians LIMIT 5")
        print("\nSample technicians:")
        print("-" * 60)
        for row in cursor.fetchall():
            print(f"  Code: {row[0]}, Party: {row[1]}, User: {row[2]}, Status: {row[3]}")
    
    conn.close()

if __name__ == "__main__":
    check_technician_schema()