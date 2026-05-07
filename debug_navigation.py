#!/usr/bin/env python3
"""
Debug navigation bar for different supplier workspaces
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

app = create_app()
app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False

with app.app_context():
    client = app.test_client()
    
    # Mock session
    with client.session_transaction() as sess:
        sess['role'] = 'admin'
        sess['display_name'] = 'Test Admin'
    
    print("=== Testing Managed Supplier (/suppliers/managed) ===")
    response = client.get('/suppliers/managed')
    html = response.data.decode('utf-8')
    
    # Find navigation bar section
    import re
    
    # Look for bh-nav section
    nav_match = re.search(r'<nav class="bh-nav"[^>]*>.*?</nav>', html, re.DOTALL)
    if nav_match:
        nav_html = nav_match.group(0)
        print("Navigation bar found (first 500 chars):")
        print(nav_html[:500])
        
        # Check for Registrations and Quotations links
        if 'Registrations' in nav_html:
            print("FOUND: 'Registrations' in navigation bar")
        else:
            print("NOT FOUND: 'Registrations' NOT found in navigation bar")
            
        if 'Quotations' in nav_html:
            print("FOUND: 'Quotations' in navigation bar")
        else:
            print("NOT FOUND: 'Quotations' NOT found in navigation bar")
    else:
        print("Navigation bar not found in HTML")
    
    print("\n=== Testing Partnership Supplier (/suppliers/partnership) ===")
    response = client.get('/suppliers/partnership')
    html = response.data.decode('utf-8')
    
    # Find navigation bar section
    nav_match = re.search(r'<nav class="bh-nav"[^>]*>.*?</nav>', html, re.DOTALL)
    if nav_match:
        nav_html = nav_match.group(0)
        print("Navigation bar found (first 500 chars):")
        print(nav_html[:500])
        
        # Check for Registrations and Quotations links
        if 'Registrations' in nav_html:
            print("FOUND: 'Registrations' in navigation bar")
        else:
            print("NOT FOUND: 'Registrations' NOT found in navigation bar")
            
        if 'Quotations' in nav_html:
            print("FOUND: 'Quotations' in navigation bar")
        else:
            print("NOT FOUND: 'Quotations' NOT found in navigation bar")
    else:
        print("Navigation bar not found in HTML")
    
    print("\n=== Testing Cash Supplier (/suppliers/cash) ===")
    response = client.get('/suppliers/cash')
    html = response.data.decode('utf-8')
    
    # Find navigation bar section
    nav_match = re.search(r'<nav class="bh-nav"[^>]*>.*?</nav>', html, re.DOTALL)
    if nav_match:
        nav_html = nav_match.group(0)
        print("Navigation bar found (first 500 chars):")
        print(nav_html[:500])
        
        # Check for Registrations and Quotations links
        if 'Registrations' in nav_html:
            print("FOUND: 'Registrations' in navigation bar")
        else:
            print("NOT FOUND: 'Registrations' NOT found in navigation bar")
            
        if 'Quotations' in nav_html:
            print("FOUND: 'Quotations' in navigation bar")
        else:
            print("NOT FOUND: 'Quotations' NOT found in navigation bar")
    else:
        print("Navigation bar not found in HTML")