#!/usr/bin/env python3
"""
Debug inquiry functionality
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
import sqlite3

def check_csrf_token():
    """Check CSRF token in modal form"""
    print("=== Checking CSRF Token ===")
    
    template_path = 'app/templates/supplier_detail.html'
    with open(template_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find modal
    modal_start = content.find('<div id="inquiryModal"')
    if modal_start == -1:
        print("ERROR: inquiryModal not found")
        return
    
    modal_end = content.find('</div>', modal_start) + 6
    modal_content = content[modal_start:modal_end]
    
    print(f"Modal found (length: {len(modal_content)} chars)")
    
    # Check for CSRF token
    if 'csrf_token' in modal_content:
        print("[OK] 'csrf_token' found in modal")
        
        # Find the exact line
        lines = modal_content.split('\n')
        for i, line in enumerate(lines):
            if 'csrf_token' in line:
                print(f"  Line {i}: {line.strip()}")
    else:
        print("[FAIL] 'csrf_token' NOT found in modal")
    
    # Also check for the form
    if '<form method="post"' in modal_content:
        print("[OK] Form found in modal")
    else:
        print("[FAIL] Form NOT found in modal")

def test_auth():
    """Test authentication"""
    print("\n=== Testing Authentication ===")
    
    app = create_app()
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.test_client() as client:
        # Test 1: No session
        print("Test 1: No session")
        response = client.post('/suppliers/PTY-0001/send-inquiry', data={})
        print(f"  Status: {response.status_code}")
        print(f"  Redirect to login: {'/login' in response.data.decode('utf-8', errors='ignore')}")
        
        # Test 2: With session but wrong key
        print("\nTest 2: With user_role (wrong key)")
        with client.session_transaction() as session:
            session['user_role'] = 'admin'
            session['user_id'] = 'admin'
            session['display_name'] = 'Test Admin'
        
        response = client.post('/suppliers/PTY-0001/send-inquiry', data={})
        print(f"  Status: {response.status_code}")
        print(f"  Redirect to login: {'/login' in response.data.decode('utf-8', errors='ignore')}")
        
        # Test 3: With correct key 'role'
        print("\nTest 3: With role (correct key)")
        with client.session_transaction() as session:
            session['role'] = 'admin'
            session['user_id'] = 'admin'
            session['display_name'] = 'Test Admin'
        
        response = client.post('/suppliers/PTY-0001/send-inquiry', data={
            'subject': 'Test',
            'description': 'Test description'
        })
        print(f"  Status: {response.status_code}")
        print(f"  Response preview: {response.data[:200]}")

def check_database():
    """Check database table"""
    print("\n=== Checking Database ===")
    
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    
    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='supplier_inquiries'")
    table_exists = cursor.fetchone()
    print(f"Table 'supplier_inquiries' exists: {bool(table_exists)}")
    
    if table_exists:
        cursor.execute("PRAGMA table_info(supplier_inquiries)")
        columns = cursor.fetchall()
        print(f"Columns: {[col[1] for col in columns]}")
        
        cursor.execute("SELECT COUNT(*) FROM supplier_inquiries")
        count = cursor.fetchone()[0]
        print(f"Total rows: {count}")
        
        if count > 0:
            cursor.execute("SELECT * FROM supplier_inquiries LIMIT 3")
            rows = cursor.fetchall()
            for row in rows:
                print(f"  Row: {row}")

if __name__ == "__main__":
    check_csrf_token()
    test_auth()
    check_database()