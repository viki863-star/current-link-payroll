#!/usr/bin/env python3
"""
Final test for inquiry functionality with CSRF handling
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
import sqlite3

def test_inquiry_with_csrf():
    """Test inquiry submission with CSRF token"""
    print("=== Testing Inquiry with CSRF ===")
    
    # Clean up any existing test data
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM supplier_inquiries WHERE inquiry_no LIKE "INQ%"')
    conn.commit()
    
    cursor.execute('SELECT COUNT(*) FROM supplier_inquiries')
    initial_count = cursor.fetchone()[0]
    print(f"Initial inquiry count: {initial_count}")
    
    # Get a test supplier
    cursor.execute("SELECT party_code FROM parties WHERE party_roles LIKE '%Supplier%' AND status='Active' LIMIT 1")
    row = cursor.fetchone()
    if not row:
        print("ERROR: No active supplier found")
        return False
    
    party_code = row[0]
    print(f"Test supplier: {party_code}")
    
    # Create app with test config
    app = create_app()
    app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for testing
    
    with app.test_client() as client:
        # Login as admin
        with client.session_transaction() as session:
            session['user_role'] = 'admin'
            session['user_id'] = 'admin'
            session['display_name'] = 'Test Admin'
        
        # Test data
        test_data = {
            'subject': 'Final Test Inquiry',
            'description': 'This is a final test of the inquiry functionality.',
            'priority': 'High',
            'due_date': '2026-12-31',
            'response_deadline': '2026-12-15'
        }
        
        print(f"Submitting inquiry to /suppliers/{party_code}/send-inquiry")
        response = client.post(f"/suppliers/{party_code}/send-inquiry", data=test_data)
        print(f"Response status: {response.status_code}")
        print(f"Response data: {response.data[:200]}")
        
        # Check if inquiry was created
        cursor.execute('SELECT COUNT(*) FROM supplier_inquiries')
        new_count = cursor.fetchone()[0]
        print(f"New inquiry count: {new_count}")
        
        if new_count > initial_count:
            cursor.execute('SELECT inquiry_no, subject FROM supplier_inquiries ORDER BY created_at DESC LIMIT 1')
            inquiry = cursor.fetchone()
            print(f"SUCCESS: Inquiry created: {inquiry}")
            return True
        else:
            print("FAILURE: Inquiry not created")
            # Check what's in the table
            cursor.execute('SELECT * FROM supplier_inquiries')
            rows = cursor.fetchall()
            print(f"All rows in table: {rows}")
            return False

def check_modal_form():
    """Check that modal form has CSRF token"""
    print("\n=== Checking Modal Form ===")
    
    # Read the template file
    template_path = 'app/templates/supplier_detail.html'
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for CSRF token in modal
        modal_start = content.find('<div id="inquiryModal"')
        if modal_start == -1:
            print("[FAIL] inquiryModal not found")
            return False
        
        modal_end = content.find('</div>', modal_start) + 6
        modal_content = content[modal_start:modal_end]
        
        if 'name="csrf_token"' in modal_content:
            print("[OK] CSRF token found in modal form")
            return True
        else:
            print("[FAIL] CSRF token missing in modal form")
            return False
    except Exception as e:
        print(f"[ERROR] Could not check modal form: {e}")
        return False

def main():
    print("Running final inquiry tests...")
    
    # Check modal form
    modal_ok = check_modal_form()
    
    # Test inquiry submission
    inquiry_ok = test_inquiry_with_csrf()
    
    print("\n=== Test Summary ===")
    print(f"Modal form check: {'PASS' if modal_ok else 'FAIL'}")
    print(f"Inquiry submission: {'PASS' if inquiry_ok else 'FAIL'}")
    
    if modal_ok and inquiry_ok:
        print("\n[SUCCESS] All tests passed!")
        return 0
    else:
        print("\n[FAILURE] Some tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())