#!/usr/bin/env python3
"""
Test that Send Inquiry button is properly clickable.
Checks button HTML attributes and onclick handler.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, session
from app import create_app
import re

def test_button_clickable():
    """Test that Send Inquiry button has correct onclick handler."""
    print("Testing Send Inquiry button clickability...")
    
    # Create test app
    app = create_app()
    
    with app.test_client() as client:
        # Set up session as admin
        with client.session_transaction() as sess:
            sess['role'] = 'admin'
            sess['user_id'] = 'admin'
        
        # Get supplier detail page
        response = client.get('/suppliers/PTY-0001')
        
        if response.status_code != 200:
            print(f"ERROR: Failed to load page. Status: {response.status_code}")
            return False
        
        html = response.data.decode('utf-8')
        
        # Find the Send Inquiry button
        # Look for button with onclick="openInquiryModal()"
        # Better pattern that captures the whole button tag including closing tag
        button_pattern = r'<button[^>]*>.*?Send Inquiry.*?</button>'
        button_matches = re.findall(button_pattern, html, re.IGNORECASE | re.DOTALL)
        
        if not button_matches:
            print("ERROR: Could not find Send Inquiry button in HTML with regex")
            # Try simpler search
            if 'Send Inquiry' in html:
                print("  But 'Send Inquiry' text exists in HTML")
                # Extract context around the text
                idx = html.find('Send Inquiry')
                start = max(0, idx-200)
                end = min(len(html), idx+200)
                context = html[start:end]
                print(f"  Context: {context}")
                
                # Try to find the button tag manually
                # Look backwards for <button
                button_start = html.rfind('<button', 0, idx)
                if button_start != -1:
                    button_end = html.find('</button>', idx) + 9  # 9 = len('</button>')
                    if button_end > button_start:
                        button_html = html[button_start:button_end]
                        print(f"  Found button manually: {button_html}")
                        button_matches = [button_html]
            
            if not button_matches:
                return False
        
        print(f"Found {len(button_matches)} button(s) with 'Send Inquiry' text")
        
        for i, button_html in enumerate(button_matches):
            print(f"\nButton {i+1}: {button_html}")
            
            # Check onclick attribute
            if 'onclick=' in button_html:
                onclick_match = re.search(r'onclick\s*=\s*["\']([^"\']*)["\']', button_html)
                if onclick_match:
                    onclick_value = onclick_match.group(1)
                    print(f"  onclick handler: {onclick_value}")
                    
                    if 'openInquiryModal()' in onclick_value:
                        print("  [OK] Correct onclick handler: openInquiryModal()")
                    else:
                        print(f"  [FAIL] Wrong onclick handler: {onclick_value}")
                else:
                    print("  [FAIL] onclick attribute malformed")
            else:
                print("  [FAIL] No onclick attribute found")
            
            # Check button type
            if 'type="button"' in button_html:
                print("  [OK] Has type='button' (prevents form submission)")
            else:
                print("  [FAIL] Missing type='button' (might cause form submission)")
        
        # Also check that modal has proper display:none
        modal_pattern = r'<div[^>]*id="inquiryModal"[^>]*>'
        modal_match = re.search(modal_pattern, html, re.IGNORECASE)
        if modal_match:
            modal_html = modal_match.group(0)
            print(f"\nModal HTML: {modal_html}")
            
            if 'style="display:none;"' in modal_html:
                print("  [OK] Modal initially hidden (display:none)")
            else:
                print("  [FAIL] Modal not hidden initially")
        else:
            print("\n[FAIL] Could not find inquiryModal div")
        
        # Check CSS is loaded
        if '.modal {' in html:
            print("\n[OK] Modal CSS styles found in page")
        else:
            print("\n[FAIL] Modal CSS styles not found")
        
        return True

if __name__ == '__main__':
    success = test_button_clickable()
    sys.exit(0 if success else 1)