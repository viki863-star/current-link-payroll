#!/usr/bin/env python3
"""
Test if the technician jobs query works.
"""
import sqlite3

def test_technician_jobs_query():
    """Test if the technician jobs query works now."""
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    
    print("Testing technician jobs query...")
    
    # First check the exact query from routes.py
    query = """
        SELECT
            mp.paper_no, mp.paper_date as entry_date, mp.vehicle_id,
            COALESCE(vm.vehicle_no, mp.vehicle_id) as vehicle_no,
            COALESCE(vm.make_model, mp.vehicle_id) as vehicle_name,
            mp.work_summary as details,
            mp.supplier_bill_no as bill_no,
            mp.subtotal as amount,
            mp.tax_amount, mp.total_amount,
            mp.notes as remarks,
            mp.technician_code,
            COALESCE(p.party_name, t.specialization, mp.technician_code) as technician_name,
            mp.review_status, mp.approved_by, mp.approved_at, mp.rejection_reason,
            mp.payment_status, mp.created_at, mp.attachment_path as bill_image,
            COALESCE(wp.party_name, mp.workshop_party_code) as workshop_name,
            mp.work_type
        FROM maintenance_papers mp
        LEFT JOIN vehicle_master vm ON mp.vehicle_id = vm.vehicle_id
        LEFT JOIN technicians t ON mp.technician_code = t.technician_code
        LEFT JOIN parties p ON t.party_code = p.party_code
        LEFT JOIN parties wp ON mp.workshop_party_code = wp.party_code
        WHERE mp.technician_code IS NOT NULL
        LIMIT 5
    """
    
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        print(f"SUCCESS: Query executed, found {len(results)} records")
        for row in results:
            print(f"  Paper: {row[0]}, Tech: {row[11]}, Status: {row[13]}")
    except sqlite3.OperationalError as e:
        print(f"ERROR: Query failed: {e}")
        
        # Try to identify which part failed
        print("\nTrying to identify the issue...")
        
        # Check if vehicle_master table has make_model column
        try:
            cursor.execute("PRAGMA table_info(vehicle_master)")
            vm_columns = cursor.fetchall()
            vm_col_names = [col[1] for col in vm_columns]
            print(f"vehicle_master columns: {', '.join(vm_col_names)}")
            if 'make_model' not in vm_col_names:
                print("WARNING: vehicle_master table doesn't have 'make_model' column")
        except:
            pass
        
        # Check if parties table exists
        try:
            cursor.execute("SELECT COUNT(*) FROM parties LIMIT 1")
            print("parties table exists")
        except:
            print("parties table may not exist or is empty")
        
        # Try a simpler query
        print("\nTrying simpler query...")
        simple_query = "SELECT mp.paper_no, mp.technician_code FROM maintenance_papers mp WHERE mp.technician_code IS NOT NULL LIMIT 5"
        try:
            cursor.execute(simple_query)
            simple_results = cursor.fetchall()
            print(f"Simple query works: found {len(simple_results)} records")
            for row in simple_results:
                print(f"  Paper: {row[0]}, Tech: {row[1]}")
        except sqlite3.OperationalError as e2:
            print(f"Even simple query failed: {e2}")
    
    conn.close()

def check_technician_amjad5():
    """Check technician Amjad5."""
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    
    print("\nChecking technician Amjad5...")
    
    # Check if technician exists
    cursor.execute("SELECT user_id, technician_code, password_hash FROM technicians WHERE user_id = ?", ('Amjad5',))
    tech = cursor.fetchone()
    
    if tech:
        user_id, tech_code, password_hash = tech
        print(f"Found technician: {user_id}, code: {tech_code}")
        print(f"Password hash: {password_hash[:20]}...")
        
        # Test password
        import hashlib
        test_hash = hashlib.sha256('1234'.encode()).hexdigest()
        if password_hash == test_hash:
            print("Password hash matches '1234'")
        else:
            print("Password hash does NOT match '1234'")
            print(f"Expected: {test_hash}")
            print(f"Actual:   {password_hash}")
    else:
        print("Technician Amjad5 not found")
        
        # List all technicians
        cursor.execute("SELECT user_id, technician_code FROM technicians LIMIT 5")
        all_techs = cursor.fetchall()
        print("First 5 technicians:")
        for t in all_techs:
            print(f"  {t[0]} - {t[1]}")
    
    conn.close()

def main():
    print("=== Testing Technician System ===\n")
    
    test_technician_jobs_query()
    check_technician_amjad5()
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    main()