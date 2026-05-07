#!/usr/bin/env python3
import sqlite3
import sys

def check_table_columns():
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    
    # Check supplier_quotation_submissions table
    cursor.execute('PRAGMA table_info(supplier_quotation_submissions)')
    columns = cursor.fetchall()
    
    print("supplier_quotation_submissions columns:")
    for col in columns:
        print(f"  {col[1]} ({col[2]})")
    
    # Check if status column exists
    status_exists = any(col[1] == 'status' for col in columns)
    print(f"\nStatus column exists: {status_exists}")
    
    # Check what columns might be used for status
    possible_status_cols = [col[1] for col in columns if 'status' in col[1].lower() or 'review' in col[1].lower()]
    print(f"Possible status columns: {possible_status_cols}")
    
    # Check a few rows to see structure
    cursor.execute('SELECT * FROM supplier_quotation_submissions LIMIT 1')
    row = cursor.fetchone()
    if row:
        print(f"\nSample row (first): {row}")
        # Map column names to values
        for i, col in enumerate(columns):
            if i < len(row):
                print(f"  {col[1]}: {row[i]}")
    
    conn.close()

if __name__ == "__main__":
    check_table_columns()