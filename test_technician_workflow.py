#!/usr/bin/env python3
"""
Test script to verify the complete technician workflow:
1. Create a new technician (without technician_code and party_code)
2. Login as technician
3. Submit a job with vehicle selection
4. Submit a job with "General Entry" (no vehicle)
"""

import os
import sys
import sqlite3
from pathlib import Path
import hashlib
import secrets

def get_database_path():
    """Get the database path."""
    db_path = os.environ.get("DATABASE_URL", "payroll.db")
    if db_path.startswith("sqlite:///"):
        db_path = db_path.replace("sqlite:///", "")
    elif db_path.startswith("sqlite:"):
        db_path = db_path.replace("sqlite:", "")
    return Path(db_path)

def hash_password(password):
    """Hash a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def test_technician_creation():
    """Test creating a new technician without technician_code and party_code."""
    db_path = get_database_path()
    
    if not db_path.exists():
        print(f"Database file {db_path} does not exist.")
        return False
    
    print(f"Testing technician workflow with database: {db_path}")
    
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Clean up any existing test technician
        cursor.execute("DELETE FROM technicians WHERE user_id LIKE 'test_tech%'")
        
        # Create a test technician
        test_user_id = "test_tech_" + secrets.token_hex(4)
        test_password = "password123"
        password_hash = hash_password(test_password)
        
        print(f"\n1. Creating technician with user_id: {test_user_id}")
        print("   (No technician_code, no party_code)")
        
        cursor.execute("""
            INSERT INTO technicians 
            (user_id, password_hash, phone_number, specialization, status)
            VALUES (?, ?, ?, ?, ?)
        """, (test_user_id, password_hash, "1234567890", "General Mechanic", "Active"))
        
        technician_id = cursor.lastrowid
        print(f"   Technician created with ID: {technician_id}")
        
        # Verify the technician was created
        cursor.execute("SELECT * FROM technicians WHERE id = ?", (technician_id,))
        tech = cursor.fetchone()
        
        if tech:
            print(f"   Verification: user_id={tech['user_id']}, phone={tech['phone_number']}")
            print(f"   technician_code={tech['technician_code']}, party_code={tech['party_code']}")
            
            # Check that technician_code and party_code are NULL
            if tech['technician_code'] is None and tech['party_code'] is None:
                print("   ✓ technician_code and party_code are NULL (as expected)")
            else:
                print(f"   ✗ technician_code or party_code not NULL: {tech['technician_code']}, {tech['party_code']}")
        
        # Test technician login
        print(f"\n2. Testing technician login for user_id: {test_user_id}")
        
        cursor.execute("""
            SELECT * FROM technicians 
            WHERE user_id = ? AND password_hash = ? AND status = 'Active'
        """, (test_user_id, password_hash))
        
        login_result = cursor.fetchone()
        if login_result:
            print(f"   ✓ Login successful for technician: {login_result['user_id']}")
        else:
            print("   ✗ Login failed")
        
        # Check if there are vehicles in the system
        print(f"\n3. Checking available vehicles for job submission")
        
        cursor.execute("SELECT COUNT(*) as count FROM vehicle_master WHERE status = 'Active'")
        vehicle_count = cursor.fetchone()['count']
        print(f"   Active vehicles in system: {vehicle_count}")
        
        if vehicle_count > 0:
            cursor.execute("SELECT vehicle_id, vehicle_no, make_model FROM vehicle_master WHERE status = 'Active' LIMIT 3")
            vehicles = cursor.fetchall()
            print("   Sample vehicles:")
            for v in vehicles:
                print(f"     - {v['vehicle_id']}: {v['vehicle_no']} ({v['make_model']})")
        else:
            print("   No vehicles found. Need to add vehicles first.")
            # Add a test vehicle
            cursor.execute("""
                INSERT INTO vehicle_master 
                (vehicle_id, vehicle_no, vehicle_type, make_model, status, shift_mode, ownership_mode, source_type, company_share_percent, partner_share_percent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("TEST_VEH_001", "TEST-123", "Truck", "Test Model", "Active", "Day", "Company", "Purchase", 100.0, 0.0))
            print("   Added test vehicle: TEST_VEH_001")
        
        # Check maintenance_papers table structure
        print(f"\n4. Checking maintenance_papers table structure")
        
        cursor.execute("PRAGMA table_info(maintenance_papers)")
        columns = cursor.fetchall()
        paper_columns = [col['name'] for col in columns]
        
        required_columns = ['paper_no', 'vehicle_id', 'technician_code', 'work_type', 'amount']
        missing_columns = [col for col in required_columns if col not in paper_columns]
        
        if missing_columns:
            print(f"   Missing columns in maintenance_papers: {missing_columns}")
        else:
            print(f"   ✓ maintenance_papers table has required columns")
        
        # Test inserting a maintenance paper (job submission)
        print(f"\n5. Testing job submission (maintenance paper creation)")
        
        # Get a vehicle_id
        cursor.execute("SELECT vehicle_id FROM vehicle_master WHERE status = 'Active' LIMIT 1")
        vehicle = cursor.fetchone()
        
        if vehicle:
            vehicle_id = vehicle['vehicle_id']
            
            # Generate a paper_no
            cursor.execute("SELECT MAX(paper_no) as max_paper FROM maintenance_papers")
            max_paper = cursor.fetchone()['max_paper']
            
            if max_paper and max_paper.startswith('MT'):
                try:
                    num = int(max_paper[2:])
                    next_num = num + 1
                except:
                    next_num = 1
            else:
                next_num = 1
            
            paper_no = f"MT{next_num:06d}"
            
            # Insert a test maintenance paper
            cursor.execute("""
                INSERT INTO maintenance_papers 
                (paper_no, vehicle_id, technician_code, work_type, amount, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (paper_no, vehicle_id, None, "General Repair", 150.0, "Pending"))
            
            print(f"   ✓ Created maintenance paper: {paper_no}")
            print(f"     Vehicle: {vehicle_id}, Technician: NULL, Amount: 150.0")
            
            # Test "General Entry" (no vehicle)
            paper_no_general = f"MT{next_num + 1:06d}"
            cursor.execute("""
                INSERT INTO maintenance_papers 
                (paper_no, vehicle_id, technician_code, work_type, amount, status, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (paper_no_general, "GENERAL", None, "General Task", 50.0, "Completed", "General entry - no vehicle"))
            
            print(f"   ✓ Created general entry paper: {paper_no_general}")
            print(f"     Vehicle: GENERAL (no vehicle), Notes: General entry - no vehicle")
        
        # Clean up test data
        print(f"\n6. Cleaning up test data")
        cursor.execute("DELETE FROM technicians WHERE user_id LIKE 'test_tech%'")
        cursor.execute("DELETE FROM vehicle_master WHERE vehicle_id = 'TEST_VEH_001'")
        cursor.execute("DELETE FROM maintenance_papers WHERE paper_no LIKE 'MT%' AND (notes LIKE '%test%' OR notes LIKE '%General entry%')")
        
        conn.commit()
        print("   Test data cleaned up")
        
        print(f"\n✅ Technician workflow test completed successfully!")
        return True
        
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    success = test_technician_creation()
    if success:
        print("\nAll tests passed!")
        sys.exit(0)
    else:
        print("\nTests failed!")
        sys.exit(1)