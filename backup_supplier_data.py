#!/usr/bin/env python3
"""
Backup supplier data from payroll.db
"""
import sqlite3
import json
import csv
from datetime import datetime
import os

def backup_supplier_data():
    # Database path
    db_path = "payroll.db"
    backup_dir = "backups/supplier_desk_backup_20260430_1058"
    
    # Create backup directory if not exists
    os.makedirs(backup_dir, exist_ok=True)
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # List of supplier-related tables
    supplier_tables = [
        "supplier_quotation_submissions",
        "supplier_profile",
        "supplier_portal_accounts",
        "supplier_assets",
        "supplier_timesheets",
        "supplier_vouchers",
        "supplier_payments",
        "supplier_invoice_submissions",
        "supplier_registration_requests",
        "supplier_partnership_entries",
        "cash_supplier_trips",
        "cash_supplier_debits",
        "cash_supplier_payments",
        "parties",  # Contains supplier parties
        "agreements",  # Supplier agreements
        "lpos",  # Supplier LPOs
        "hire_records",  # Supplier hire records
    ]
    
    # Backup each table
    backup_info = {
        "backup_timestamp": datetime.now().isoformat(),
        "database": db_path,
        "tables_backed_up": []
    }
    
    for table in supplier_tables:
        try:
            # Check if table exists
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if cursor.fetchone():
                # Get table schema
                cursor.execute(f"PRAGMA table_info({table})")
                schema = cursor.fetchall()
                
                # Get all data
                cursor.execute(f"SELECT * FROM {table}")
                rows = cursor.fetchall()
                
                # Save as JSON
                json_file = os.path.join(backup_dir, f"{table}.json")
                with open(json_file, 'w', encoding='utf-8') as f:
                    data = {
                        "schema": [dict(col) for col in schema],
                        "data": [dict(row) for row in rows]
                    }
                    json.dump(data, f, indent=2, default=str)
                
                # Save as CSV
                csv_file = os.path.join(backup_dir, f"{table}.csv")
                if rows:
                    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        # Write header
                        writer.writerow([col[0] for col in schema])
                        # Write rows
                        for row in rows:
                            writer.writerow([row[col[0]] for col in schema])
                
                backup_info["tables_backed_up"].append({
                    "table": table,
                    "row_count": len(rows),
                    "json_file": json_file,
                    "csv_file": csv_file
                })
                print(f"[OK] Backed up {table}: {len(rows)} rows")
            else:
                print(f"[WARN] Table {table} does not exist")
        except Exception as e:
            print(f"[ERROR] Error backing up {table}: {e}")
    
    # Save backup info
    info_file = os.path.join(backup_dir, "backup_info.json")
    with open(info_file, 'w', encoding='utf-8') as f:
        json.dump(backup_info, f, indent=2, default=str)
    
    # Create a list of supplier templates
    templates_dir = "app/templates"
    supplier_templates = []
    for root, dirs, files in os.walk(templates_dir):
        for file in files:
            if 'supplier' in file.lower() or 'cash' in file.lower():
                supplier_templates.append(os.path.join(root, file))
    
    # Save template list
    templates_file = os.path.join(backup_dir, "supplier_templates.txt")
    with open(templates_file, 'w', encoding='utf-8') as f:
        f.write("Supplier-related templates:\n")
        f.write("=" * 50 + "\n")
        for template in supplier_templates:
            f.write(f"{template}\n")
    
    # Get supplier routes from routes.py
    routes_file = "app/routes.py"
    supplier_routes = []
    try:
        with open(routes_file, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if 'supplier' in line.lower() and '@app.route' in line:
                    # Get the next few lines to see function name
                    supplier_routes.append(line.strip())
    except Exception as e:
        print(f"Error reading routes: {e}")
    
    # Save routes list
    routes_list_file = os.path.join(backup_dir, "supplier_routes.txt")
    with open(routes_list_file, 'w', encoding='utf-8') as f:
        f.write("Supplier-related routes:\n")
        f.write("=" * 50 + "\n")
        for route in supplier_routes:
            f.write(f"{route}\n")
    
    # Create schema notes
    schema_file = os.path.join(backup_dir, "supplier_schema_notes.txt")
    with open(schema_file, 'w', encoding='utf-8') as f:
        f.write("Supplier Desk Schema Notes\n")
        f.write("=" * 50 + "\n\n")
        f.write("Supplier Mode Options: Normal, Partnership, Managed, Cash, Loan\n")
        f.write("Supplier Tables:\n")
        for table in supplier_tables:
            f.write(f"  - {table}\n")
    
    conn.close()
    
    print(f"\n[SUCCESS] Backup completed successfully!")
    print(f"[INFO] Backup location: {backup_dir}")
    print(f"[INFO] Tables backed up: {len(backup_info['tables_backed_up'])}")
    
    return backup_dir

if __name__ == "__main__":
    backup_supplier_data()