#!/usr/bin/env python3
"""
Fix technician issues:
1. Alter technicians table to remove NOT NULL constraints from technician_code and party_code
2. Check vehicle_master table schema and fix query if needed
"""

import sys
import os
import sqlite3
from pathlib import Path

def get_database_path():
    """Get the database file path."""
    # Check for environment variable
    db_path = os.environ.get('DATABASE_URL', '')
    if db_path and db_path.startswith('sqlite:///'):
        return db_path.replace('sqlite:///', '')
    
    # Default path
    return 'payroll.db'

def fix_technicians_table():
    """Alter technicians table to remove NOT NULL constraints."""
    db_path = get_database_path()
    print(f"Connecting to database: {db_path}")
    
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Check current schema
        cursor.execute("PRAGMA table_info(technicians)")
        columns = cursor.fetchall()
        print("\nCurrent technicians table schema:")
        for col in columns:
            print(f"  {col[1]} - Type: {col[2]}, Not Null: {col[3]}")
        
        # Check if we need to alter the table
        tech_code_col = next((c for c in columns if c[1] == 'technician_code'), None)
        party_code_col = next((c for c in columns if c[1] == 'party_code'), None)
        
        needs_alter = False
        
        if tech_code_col and tech_code_col[3] == 1:
            print("\ntechnician_code has NOT NULL constraint, needs to be removed")
            needs_alter = True
        
        if party_code_col and party_code_col[3] == 1:
            print("\nparty_code has NOT NULL constraint, needs to be removed")
            needs_alter = True
        
        if not needs_alter:
            print("\nNo alterations needed - constraints already removed")
            return True
        
        # SQLite doesn't support ALTER TABLE to modify column constraints directly
        # We need to create a new table, copy data, drop old table, rename new table
        print("\nCreating new technicians table without NOT NULL constraints...")
        
        # Create new table with updated schema
        cursor.execute("""
            CREATE TABLE technicians_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                technician_code TEXT UNIQUE,
                party_code TEXT,
                user_id TEXT UNIQUE,
                password_hash TEXT,
                phone_number TEXT,
                specialization TEXT,
                status TEXT DEFAULT 'Active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(party_code) REFERENCES parties(party_code) ON DELETE SET NULL
            )
        """)
        
        # Copy data from old table to new table
        print("Copying data from old table to new table...")
        cursor.execute("""
            INSERT INTO technicians_new 
            (id, technician_code, party_code, user_id, password_hash, 
             phone_number, specialization, status, created_at)
            SELECT id, technician_code, party_code, user_id, password_hash,
                   phone_number, specialization, status, created_at
            FROM technicians
        """)
        
        # Drop old table
        print("Dropping old technicians table...")
        cursor.execute("DROP TABLE technicians")
        
        # Rename new table to technicians
        print("Renaming new table to technicians...")
        cursor.execute("ALTER TABLE technicians_new RENAME TO technicians")
        
        # Recreate indexes
        print("Recreating indexes...")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_technicians_technician_code ON technicians(technician_code)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_technicians_user_id ON technicians(user_id)")
        
        conn.commit()
        print("\n✅ Successfully updated technicians table schema")
        
        # Verify the changes
        cursor.execute("PRAGMA table_info(technicians)")
        columns = cursor.fetchall()
        print("\nUpdated technicians table schema:")
        for col in columns:
            print(f"  {col[1]} - Type: {col[2]}, Not Null: {col[3]}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def check_vehicle_master_table():
    """Check vehicle_master table schema."""
    db_path = get_database_path()
    
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Check vehicle_master table columns
        cursor.execute("PRAGMA table_info(vehicle_master)")
        columns = cursor.fetchall()
        
        print("\nvehicle_master table columns:")
        column_names = []
        for col in columns:
            print(f"  {col[1]} - Type: {col[2]}")
            column_names.append(col[1])
        
        # Check for plate_no or similar columns
        if 'plate_no' in column_names:
            print("\n✅ plate_no column exists in vehicle_master")
        else:
            print("\n❌ plate_no column NOT found in vehicle_master")
            print("Available columns that might be relevant:")
            for col in column_names:
                if 'plate' in col.lower() or 'number' in col.lower() or 'no' in col.lower():
                    print(f"  - {col}")
        
        # Check for vehicle_name column
        if 'vehicle_name' in column_names:
            print("✅ vehicle_name column exists in vehicle_master")
        else:
            print("❌ vehicle_name column NOT found in vehicle_master")
            
    except Exception as e:
        print(f"Error checking vehicle_master: {e}")
    finally:
        conn.close()

def fix_technician_jobs_query():
    """Check and fix the technician_jobs query if needed."""
    print("\n" + "="*50)
    print("Checking technician_jobs query...")
    
    # Read the routes.py file to check the query
    routes_path = "app/routes.py"
    if not os.path.exists(routes_path):
        print(f"routes.py not found at {routes_path}")
        return
    
    with open(routes_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the technician_jobs function
    import re
    pattern = r'def technician_jobs\(\):.*?query = """.*?"""'
    match = re.search(pattern, content, re.DOTALL)
    
    if match:
        print("Found technician_jobs query")
        # Check if the query uses vm.plate_no
        if 'vm.plate_no' in match.group(0):
            print("Query uses vm.plate_no")
            
            # Check what column vehicle_master actually has
            db_path = get_database_path()
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(vehicle_master)")
                columns = [col[1] for col in cursor.fetchall()]
                conn.close()
                
                if 'plate_no' not in columns:
                    print("⚠️  vehicle_master doesn't have plate_no column")
                    print("Available columns:", columns)
                    
                    # Suggest alternative column names
                    alternatives = []
                    for col in columns:
                        if 'plate' in col.lower():
                            alternatives.append(col)
                        elif 'number' in col.lower():
                            alternatives.append(col)
                        elif 'no' in col.lower() and 'plate' not in col.lower():
                            alternatives.append(col)
                    
                    if alternatives:
                        print(f"Suggested alternatives: {alternatives}")
                        # The query should use the correct column name
                        # We'll need to update the query in routes.py
                        return alternatives
    else:
        print("Could not find technician_jobs query")
    
    return []

def main():
    print("Fixing Technician Issues")
    print("="*50)
    
    # Fix technicians table NOT NULL constraints
    if not fix_technicians_table():
        print("\nFailed to fix technicians table")
        return
    
    # Check vehicle_master table
    check_vehicle_master_table()
    
    # Check technician_jobs query
    alternatives = fix_technician_jobs_query()
    
    print("\n" + "="*50)
    print("Summary:")
    print("1. Technicians table schema has been updated (NOT NULL constraints removed)")
    print("2. Check vehicle_master table for correct column names")
    
    if alternatives:
        print(f"3. Query needs to be updated to use one of: {alternatives}")
        print("\nTo fix the query, update app/routes.py line 4340:")
        print("Change 'vm.plate_no' to 'vm.{correct_column}'")
    else:
        print("3. Query appears to be correct")
    
    print("\nNext steps:")
    print("1. Restart the Flask application")
    print("2. Test creating a new technician (should work now)")
    print("3. Test accessing technician jobs page")

if __name__ == "__main__":
    main()