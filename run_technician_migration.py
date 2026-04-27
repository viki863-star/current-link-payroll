#!/usr/bin/env python3
"""
Simple script to migrate technicians table to remove NOT NULL constraints.
Run with: py run_technician_migration.py
"""

import sqlite3
import os
import sys

def main():
    db_path = "payroll.db"
    
    if not os.path.exists(db_path):
        print(f"Error: Database file not found: {db_path}")
        return 1
    
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Check current schema
        print("\nCurrent technicians table schema:")
        cursor.execute("PRAGMA table_info(technicians)")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  {col[1]} - Type: {col[2]}, Not Null: {col[3]}")
        
        # Check if we need to alter the table
        tech_code_col = next((c for c in columns if c[1] == 'technician_code'), None)
        party_code_col = next((c for c in columns if c[1] == 'party_code'), None)
        
        needs_alter = False
        
        if tech_code_col and tech_code_col[3] == 1:
            print("\ntechnician_code has NOT NULL constraint (needs removal)")
            needs_alter = True
        elif tech_code_col:
            print("\ntechnician_code is already nullable")
        
        if party_code_col and party_code_col[3] == 1:
            print("party_code has NOT NULL constraint (needs removal)")
            needs_alter = True
        elif party_code_col:
            print("party_code is already nullable")
        
        if not needs_alter:
            print("\nNo changes needed - constraints are already nullable.")
            return 0
        
        print("\nRecreating technicians table without NOT NULL constraints...")
        
        # SQLite doesn't support ALTER COLUMN to remove NOT NULL directly
        # We need to recreate the table
        cursor.executescript("""
            -- Create a temporary table with the new schema
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
            );

            -- Copy data from old table
            INSERT INTO technicians_new 
            SELECT * FROM technicians;

            -- Drop old table
            DROP TABLE technicians;

            -- Rename new table to original name
            ALTER TABLE technicians_new RENAME TO technicians;

            -- Recreate indexes if any
            CREATE UNIQUE INDEX IF NOT EXISTS idx_technicians_user_id ON technicians(user_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_technicians_technician_code ON technicians(technician_code);
        """)
        
        conn.commit()
        
        print("Migration completed successfully.")
        
        # Verify the new schema
        print("\nNew technicians table schema:")
        cursor.execute("PRAGMA table_info(technicians)")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  {col[1]} - Type: {col[2]}, Not Null: {col[3]}")
        
        return 0
        
    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
        return 1
    finally:
        conn.close()

if __name__ == "__main__":
    sys.exit(main())