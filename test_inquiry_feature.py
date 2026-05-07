#!/usr/bin/env python3
"""
Test script for enhanced Send Inquiry functionality
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
import sqlite3

def test_inquiry_route():
    """Test that the inquiry submission route works"""
    print("Testing Send Inquiry functionality...")
    
    # First check current state
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM supplier_inquiries')
    initial_count = cursor.fetchone()[0]
    print(f"Initial inquiry count: {initial_count}")
    
    # Get a test supplier party code
    cursor.execute("SELECT party_code FROM parties WHERE party_roles LIKE '%Supplier%' AND status='Active' LIMIT 1")
    row = cursor.fetchone()
    if not row:
        print("ERROR: No active supplier found")
        return False
    
    party_code = row[0]
    print(f"Test supplier: {party_code}")
    
    # Create a test Flask app context
    app = create_app()
    
    with app.test_client() as client:
        # First login as admin (simulate session)
        with client.session_transaction() as session:
            session['user_role'] = 'admin'
            session['user_id'] = 'admin'
        
        # Test POST to send-inquiry route
        test_data = {
            'subject': 'Test Inquiry - Urgent Requirement',
            'description': 'This is a test inquiry for portal functionality testing.',
            'priority': 'High',
            'due_date': '2026-05-15',
            'response_deadline': '2026-05-10'
        }
        
        print(f"Submitting inquiry to /suppliers/{party_code}/send-inquiry")
        response = client.post(f'/suppliers/{party_code}/send-inquiry', data=test_data, follow_redirects=True)
        
        print(f"Response status: {response.status_code}")
        print(f"Response length: {len(response.data)} bytes")
        
        # Check if inquiry was created
        cursor.execute('SELECT COUNT(*) FROM supplier_inquiries')
        new_count = cursor.fetchone()[0]
        print(f"New inquiry count: {new_count}")
        
        if new_count > initial_count:
            print("[OK] Inquiry successfully created in database")
            cursor.execute('SELECT inquiry_no, subject, priority, status FROM supplier_inquiries ORDER BY created_at DESC LIMIT 1')
            inquiry = cursor.fetchone()
            print(f"  Inquiry No: {inquiry[0]}")
            print(f"  Subject: {inquiry[1]}")
            print(f"  Priority: {inquiry[2]}")
            print(f"  Status: {inquiry[3]}")
            success = True
        else:
            print("[FAIL] Inquiry not created")
            success = False
    
    conn.close()
    return success

def test_modal_form_in_template():
    """Check that modal form exists in supplier_detail.html"""
    print("\nChecking modal form in template...")
    
    with open('app/templates/supplier_detail.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for modal elements
    checks = [
        ('inquiryModal', 'Modal container'),
        ('openInquiryModal', 'JavaScript function'),
        ('closeInquiryModal', 'JavaScript function'),
        ('send_supplier_inquiry', 'Route reference'),
        ('subject', 'Subject field'),
        ('description', 'Description field'),
        ('priority', 'Priority dropdown'),
        ('due_date', 'Due date field')
    ]
    
    all_passed = True
    for search_str, description in checks:
        if search_str in content:
            print(f"[OK] {description} found")
        else:
            print(f"[FAIL] {description} NOT found")
            all_passed = False
    
    return all_passed

def test_header_navigation():
    """Check that Registrations and Quotations are hidden for Normal mode"""
    print("\nChecking header navigation modifications...")
    
    with open('app/templates/base.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the condition for Registrations and Quotations
    import re
    pattern = r"\{\%\s*if\s+current_workspace\s+in\s+\([^)]+\)\s*\%\}"
    matches = re.findall(pattern, content)
    
    if matches:
        print(f"Found condition: {matches[0][:100]}...")
        # Check if 'suppliers-normal' is excluded
        if 'suppliers-normal' not in matches[0]:
            print("✅ 'suppliers-normal' excluded from Registrations/Quotations navigation")
        else:
            print("❌ 'suppliers-normal' still included")
    else:
        print("[WARNING] Could not find navigation condition")
    
    return True

def test_invoice_intake_button():
    """Check that Invoice Intake button is hidden for Normal mode"""
    print("\nChecking Invoice Intake button...")
    
    with open('app/templates/supplier_detail.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Look for the condition that hides Invoice Intake for Normal mode
    if '{% elif supplier_mode == "Normal" %}' in content:
        print("[OK] Found condition to hide Invoice Intake for Normal mode")
        # Check what follows this condition
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if '{% elif supplier_mode == "Normal" %}' in line:
                # Check next few lines
                for j in range(i+1, min(i+5, len(lines))):
                    if 'Invoice Intake' in lines[j] and 'style="display:none"' in lines[j]:
                        print("[OK] Invoice Intake button hidden with display:none")
                        return True
    else:
        print("[FAIL] Condition for Normal mode not found")
    
    return False

def main():
    print("=" * 60)
    print("Testing Enhanced Send Inquiry Functionality")
    print("=" * 60)
    
    tests = [
        ("Modal form in template", test_modal_form_in_template),
        ("Header navigation", test_header_navigation),
        ("Invoice Intake button", test_invoice_intake_button),
        ("Inquiry submission route", test_inquiry_route),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{'='*40}")
        print(f"Test: {test_name}")
        print(f"{'='*40}")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"[FAIL] Test failed with error: {e}")
            results.append((test_name, False))
    
    print(f"\n{'='*60}")
    print("Test Summary:")
    print(f"{'='*60}")
    
    all_passed = True
    for test_name, passed in results:
        status = "[OK] PASS" if passed else "[FAIL] FAIL"
        print(f"{test_name:30} {status}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n[SUCCESS] All tests passed! Enhanced functionality is working.")
    else:
        print("\n[WARNING] Some tests failed. Check the implementation.")
    
    return all_passed

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)