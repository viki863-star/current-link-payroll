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
            'due_date': '2026-05-20',
            'response_deadline': '2026-05-15'
        }
        
        print(f"Submitting inquiry to /suppliers/{party_code}/send-inquiry")
        response = client.post(f'/suppliers/{party_code}/send-inquiry', 
                              data=test_data, 
                              follow_redirects=True)
        
        print(f"Response status: {response.status_code}")
        
        # Check if inquiry was created
        cursor.execute('SELECT COUNT(*) FROM supplier_inquiries')
        new_count = cursor.fetchone()[0]
        print(f"New inquiry count: {new_count}")
        
        if new_count > initial_count:
            print("[SUCCESS] Inquiry successfully created!")
            cursor.execute('SELECT inquiry_no, subject, priority, status FROM supplier_inquiries ORDER BY created_at DESC LIMIT 1')
            inquiry = cursor.fetchone()
            print(f"  Inquiry No: {inquiry[0]}")
            print(f"  Subject: {inquiry[1]}")
            print(f"  Priority: {inquiry[2]}")
            print(f"  Status: {inquiry[3]}")
            
            # Clean up
            cursor.execute('DELETE FROM supplier_inquiries WHERE inquiry_no = ?', (inquiry[0],))
            conn.commit()
            print("  Test inquiry cleaned up")
            success = True
        else:
            print("[FAILURE] Inquiry not created")
            # Check response content for clues
            if b'CSRF' in response.data:
                print("  CSRF error detected in response")
            success = False
    
    conn.close()
    return success

def test_modal_form():
    """Verify modal form has CSRF token"""
    print("\n=== Checking Modal Form ===")
    
    with open('app/templates/supplier_detail.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for CSRF token in modal form
    modal_start = content.find('<div id="inquiryModal"')
    if modal_start == -1:
        print("[FAIL] Modal not found")
        return False
    
    modal_end = content.find('</div>', modal_start) + 6
    modal_content = content[modal_start:modal_end]
    
    if 'name="csrf_token"' in modal_content:
        print("[OK] CSRF token found in modal form")
        return True
    else:
        print("[FAIL] CSRF token missing in modal form")
        return False

if __name__ == '__main__':
    print("Running final inquiry tests...")
    
    form_ok = test_modal_form()
    inquiry_ok = test_inquiry_with_csrf()
    
    print("\n=== Test Summary ===")
    print(f"Modal form check: {'PASS' if form_ok else 'FAIL'}")
    print(f"Inquiry submission: {'PASS' if inquiry_ok else 'FAIL'}")
    
    if form_ok and inquiry_ok:
        print("\n✅ All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed")
        sys.exit(1)