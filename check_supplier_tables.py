import sqlite3
import json

def check_supplier_tables():
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    all_tables = cursor.fetchall()
    
    print("All tables in database:")
    for table in all_tables:
        print(f"  - {table[0]}")
    
    # Find supplier-related tables
    supplier_tables = []
    for table in all_tables:
        table_name = table[0].lower()
        if 'supplier' in table_name or 'cash' in table_name or 'payment' in table_name or 'voucher' in table_name:
            supplier_tables.append(table[0])
    
    print("\nSupplier-related tables:")
    for table in supplier_tables:
        cursor.execute(f"PRAGMA table_info({table})")
        cols = cursor.fetchall()
        print(f"  - {table} ({len(cols)} columns)")
        # Print first few column names
        col_names = [col[1] for col in cols[:5]]
        print(f"    Columns: {', '.join(col_names)}" + ("..." if len(cols) > 5 else ""))
        
        # Count rows
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"    Rows: {count}")
    
    conn.close()
    
    return supplier_tables

if __name__ == "__main__":
    check_supplier_tables()