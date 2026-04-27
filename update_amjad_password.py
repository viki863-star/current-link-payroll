#!/usr/bin/env python3
"""
Update technician Amjad5's password from plain text to hashed.
"""

import sqlite3
import sys
from pathlib import Path
from werkzeug.security import generate_password_hash

def get_database_path():
    """Get the database path from environment or default."""
    db_path = Path("payroll.db")
    if not db_path.exists():
        # Try to find it in the current directory
        db_path = Path("app/payroll.db")
    if not db_path.exists():
        print("ERROR: Database file not found")
        sys.exit(1)
    return db_path

def update_technician_password():
    """Update Amjad5's password hash."""
    db_path = get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Find technician
    cursor.execute("SELECT technician_code, user_id, password_hash FROM technicians WHERE user_id = 'Amjad5' OR technician_code = 'Amjad5'")
    tech = cursor.fetchone()
    
    if not tech:
        print("ERROR: Technician Amjad5 not found")
        return False
    
    print(f"Found technician: {tech['technician_code']} (user_id: {tech['user_id']})")
    print(f"Current password hash: {tech['password_hash']}")
    
    # Generate new hash for password "1234"
    new_hash = generate_password_hash("1234")
    print(f"New password hash: {new_hash[:50]}...")
    
    # Update the password
    cursor.execute(
        "UPDATE technicians SET password_hash = ? WHERE technician_code = ?",
        (new_hash, tech['technician_code'])
    )
    
    conn.commit()
    
    # Verify the update
    cursor.execute("SELECT password_hash FROM technicians WHERE technician_code = ?", (tech['technician_code'],))
    updated = cursor.fetchone()
    
    if updated["password_hash"] == new_hash:
        print("SUCCESS: Password updated successfully")
        return True
    else:
        print("ERROR: Password update failed")
        return False

def main():
    print("=== Updating Technician Amjad5 Password ===\n")
    
    success = update_technician_password()
    
    if success:
        print("\nNow Amjad5 should be able to login with password '1234'")
        print("Restart the Flask application if it's running")
    else:
        print("\nFailed to update password")

if __name__ == "__main__":
    main()