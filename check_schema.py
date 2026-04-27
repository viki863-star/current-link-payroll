#!/usr/bin/env python3
import sqlite3
import sys

def main():
    db_path = "payroll.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check technicians table
        cursor.execute("PRAGMA table_info(technicians)")
        cols = cursor.fetchall()
        
        print("Technicians table schema:")
        for col in cols:
            col_name = col[1]
            col_type = col[2]
            not_null = col[3]
            print(f"  {col_name:20} {col_type:15} NOT NULL: {not_null}")
        
        # Check vehicle_master table
        cursor.execute("PRAGMA table_info(vehicle_master)")
        cols = cursor.fetchall()
        
        print("\nVehicle_master table schema:")
        for col in cols:
            col_name = col[1]
            col_type = col[2]
            not_null = col[3]
            print(f"  {col_name:20} {col_type:15} NOT NULL: {not_null}")
        
        conn.close()
        
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())