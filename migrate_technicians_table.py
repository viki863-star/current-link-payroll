#!/usr/bin/env python3
"""
Migration script to remove NOT NULL constraints from technicians table.
This script alters the technicians table to make technician_code and party_code nullable.
"""

import os
import sqlite3
from pathlib import Path

def get_database_path():
    """Get the database path from environment or default."""
    db_path = os.environ.get("DATABASE_URL", "payroll.db")
    if db_path.startswith("sqlite:///"):
        db_path = db_path.replace("sqlite:///", "")
    elif db_path.startswith("sqlite:"):
        db_path = db_path.replace("sqlite:", "")
    return Path(db_path)

def migrate_technicians_table():
    """Alter technicians table to remove NOT NULL constraints."""
    db_path = get_database_path()
    
    if not db_path.exists():
        print(f"Database file {db_path} does not exist.")
        return False
    
    print(f"Connecting to database: {db_path}")
    
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Check current schema
        cursor.execute("PRAGMA table_info(technicians)")
        columns = cursor.fetchall()
        print("Current technicians table schema:")
        for col in columns:
            print(f"  {col['name']:20} {col['type']:15} NOT NULL: {col['notnull']}")
        
        # Check if constraints already removed
        technician_code_notnull = any(col['name'] == 'technician_code' and col['notnull'] == 1 for col in columns)
        party_code_notnull = any(col['name'] == 'party_code' and col['notnull'] == 1 for col in columns)
        
        if not technician_code_notnull and not party_code_notnull:
            print("NOT NULL constraints already removed. No migration needed.")
            return True
        
        print("\nRemoving NOT NULL constraints from technicians table...")
        
        # SQLite doesn't support ALTER COLUMN to drop NOT NULL constraint directly.
        # We need to recreate the table.
        
        # 1. Create a new table with the same structure but without NOT NULL constraints
        cursor.execute("""
            CREATE TABLE technicians_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                technician_code TEXT UNIQUE,
                party_code TEXT,
                user_id TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                phone_number TEXT NOT NULL,
                specialization TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (party_code) REFERENCES parties (party_code) ON DELETE SET NULL
            )
        """)
        
        # 2. Copy data from old table to new table
        print("Copying data from old table to new table...")
        cursor.execute("""
            INSERT INTO technicians_new 
            (id, technician_code, party_code, user_id, password_hash, phone_number, specialization, status, created_at)
            SELECT id, technician_code, party_code, user_id, password_hash, phone_number, specialization, status, created_at
            FROM technicians
        """)
        
        # 3. Drop the old table
        cursor.execute("DROP TABLE technicians")
        
        # 4. Rename new table to technicians
        cursor.execute("ALTER TABLE technicians_new RENAME TO technicians")
        
        # 5. Recreate indexes
        cursor.execute("CREATE INDEX idx_technicians_user_id ON technicians (user_id)")
        cursor.execute("CREATE INDEX idx_technicians_party_code ON technicians (party_code)")
        cursor.execute("CREATE INDEX idx_technicians_status ON technicians (status)")
        
        # Verify the migration
        cursor.execute("PRAGMA table_info(technicians)")
        columns = cursor.fetchall()
        print("\nNew technicians table schema:")
        for col in columns:
            print(f"  {col['name']:20} {col['type']:15} NOT NULL: {col['notnull']}")
        
        # Count records
        cursor.execute("SELECT COUNT(*) as count FROM technicians")
        count = cursor.fetchone()['count']
        print(f"\nTotal technicians after migration: {count}")
        
        conn.commit()
        print("Migration completed successfully!")
        return True
        
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        conn.rollback()
        return False
    except Exception as e:
        print(f"Error: {e}")
        if 'conn' in locals():
            conn.rollback()
        return False
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    success = migrate_technicians_table()
    if success:
        print("\nMigration successful!")
    else:
        print("\nMigration failed!")
        exit(1)