#!/usr/bin/env python3
import sqlite3
import os

def check_database():
    # Check for database file
    db_files = ['payroll.db', 'app/payroll.db', 'database.db']
    db_path = None
    
    for file in db_files:
        if os.path.exists(file):
            db_path = file
            break
    
    if not db_path:
        print("No database file found. Checking current directory...")
        import subprocess
        result = subprocess.run(['dir', '*.db'], capture_output=True, text=True, shell=True)
        print(result.stdout)
        return
    
    print(f"Found database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check technicians table
    print("\n=== Technicians Table ===")
    cursor.execute("PRAGMA table_info(technicians)")
    columns = cursor.fetchall()
    
    if not columns:
        print("Technicians table does not exist!")
    else:
        print("Columns:")
        for col in columns:
            not_null = "NOT NULL" if col[3] else "NULL"
            print(f"  {col[1]:20} {col[2]:15} {not_null}")
    
    # Check vehicle_master table
    print("\n=== Vehicle Master Table ===")
    cursor.execute("PRAGMA table_info(vehicle_master)")
    columns = cursor.fetchall()
    
    if not columns:
        print("Vehicle_master table does not exist!")
    else:
        print("Columns:")
        for col in columns:
            print(f"  {col[1]:20} {col[2]:15}")
    
    # Check foreign keys
    print("\n=== Foreign Keys for technicians ===")
    cursor.execute("PRAGMA foreign_key_list(technicians)")
    fks = cursor.fetchall()
    
    if fks:
        for fk in fks:
            print(f"  Foreign key: {fk[3]} -> {fk[2]}.{fk[4]}")
    else:
        print("  No foreign keys found")
    
    # Check sample data
    print("\n=== Sample Data in technicians ===")
    cursor.execute("SELECT COUNT(*) as count FROM technicians")
    count = cursor.fetchone()[0]
    print(f"Total technicians: {count}")
    
    if count > 0:
        cursor.execute("SELECT technician_code, party_code, user_id, status FROM technicians LIMIT 5")
        rows = cursor.fetchall()
        for row in rows:
            print(f"  Code: {row[0]}, Party: {row[1]}, User: {row[2]}, Status: {row[3]}")
    
    conn.close()

if __name__ == "__main__":
    check_database()