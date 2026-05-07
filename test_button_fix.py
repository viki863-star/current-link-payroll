#!/usr/bin/env python3
"""
Test script to verify Send Inquiry button fix.
Checks if JavaScript functions are present in rendered HTML.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, session, g
from app import create_app
import re

def test_button_fix():
    """Test that Send Inquiry button JavaScript is rendered."""
    print("Testing Send Inquiry button fix...")
    
    # Create test app
    app = create_app()
    
    with app.test_client() as client:
        # Set up session as admin
        with client.session_transaction() as sess:
            sess['role'] = 'admin'
            sess['user_id'] = 'admin'
        
        # Get supplier detail page for a Normal mode supplier
        response = client.get('/suppliers/PTY-0001')
        
        if response.status_code != 200:
            print(f"ERROR: Failed to load page. Status: {response.status_code}")
            return False
        
        html = response.data.decode('utf-8')
        
        # Check if Send Inquiry button exists
        if 'Send Inquiry' not in html:
            print("ERROR: 'Send Inquiry' button text not found in HTML")
            return False
        
        # Check if JavaScript functions are present
        js_functions = [
            'function openInquiryModal()',
            'function closeInquiryModal()',
            'document.getElementById(\'inquiryModal\')',
            'window.addEventListener(\'click\''
        ]
        
        for func in js_functions:
            if func not in html:
                print(f"ERROR: JavaScript function not found: {func}")
                return False
        
        # Check if modal HTML is present
        if 'id="inquiryModal"' not in html:
            print("ERROR: Inquiry modal HTML not found")
            return False
        
        # Check if CSRF token is present in form
        if 'name="csrf_token"' not in html:
            print("WARNING: CSRF token not found in form (might be okay for testing)")
        
        print("SUCCESS: All checks passed!")
        print("- Send Inquiry button found")
        print("- JavaScript functions found")
        print("- Modal HTML found")
        
        # Also check that script tag is inside content block
        # Count occurrences of script tags
        script_tags = re.findall(r'<script[^>]*>', html, re.IGNORECASE)
        print(f"Found {len(script_tags)} script tags in HTML")
        
        # Check if our specific functions appear after the content section
        # Simple check: look for openInquiryModal after the main content
        if html.find('</section>') < html.find('function openInquiryModal'):
            print("SUCCESS: JavaScript appears after main content (likely inside content block)")
        else:
            print("WARNING: JavaScript might be in wrong position")
        
        return True

if __name__ == '__main__':
    success = test_button_fix()
    sys.exit(0 if success else 1)