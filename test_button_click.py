#!/usr/bin/env python3
"""
Test if Send Inquiry button is properly rendered and clickable
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
import sqlite3

def test_button_rendering():
    print("=== Testing Send Inquiry Button Rendering ===")
    
    # Get a test supplier
    conn = sqlite3.connect('payroll.db')
    cursor = conn.cursor()
    cursor.execute("SELECT party_code FROM parties WHERE party_roles LIKE '%Supplier%' AND status='Active' LIMIT 1")
    row = cursor.fetchone()
    if not row:
        print("ERROR: No active supplier found")
        return False
    
    party_code = row[0]
    print(f"Test supplier: {party_code}")
    
    # Create app
    app = create_app()
    
    with app.test_client() as client:
        # Login as admin
        with client.session_transaction() as session:
            session['role'] = 'admin'
            session['user_id'] = 'admin'
            session['display_name'] = 'Test Admin'
        
        # Get supplier detail page
        response = client.get(f"/suppliers/{party_code}?screen=portal")
        print(f"Page status: {response.status_code}")
        
        if response.status_code == 200:
            html = response.data.decode('utf-8', errors='ignore')
            
            # Check for button
            if 'Send Inquiry</button>' in html:
                print("[OK] 'Send Inquiry' button text found in HTML")
            else:
                print("[WARNING] 'Send Inquiry' button text not found")
                
            # Check for onclick handler
            if 'onclick="openInquiryModal()"' in html:
                print("[OK] onclick='openInquiryModal()' found")
            else:
                print("[WARNING] onclick handler not found")
                
            # Check for modal
            if 'id="inquiryModal"' in html:
                print("[OK] inquiryModal div found")
            else:
                print("[WARNING] inquiryModal not found")
                
            # Check for JavaScript functions
            if 'function openInquiryModal()' in html:
                print("[OK] openInquiryModal function defined")
            else:
                print("[WARNING] openInquiryModal function not found")
                
            # Check if button is actually in the rendered HTML (not commented out)
            # Look for the specific button pattern
            import re
            button_pattern = r'<button[^>]*Send Inquiry[^>]*>'
            matches = re.findall(button_pattern, html)
            if matches:
                print(f"[OK] Button HTML found: {matches[0][:100]}...")
            else:
                print("[FAIL] No button HTML matching pattern found")
                
            # Save HTML for inspection
            with open('test_button_output.html', 'w', encoding='utf-8') as f:
                f.write(html)
            print("HTML saved to test_button_output.html for inspection")
            
            return True
        else:
            print(f"[FAIL] Page load failed with status {response.status_code}")
            return False

if __name__ == "__main__":
    test_button_rendering()