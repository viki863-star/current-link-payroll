#!/usr/bin/env python3
"""
Final verification of updated statistics on Online Supplier page.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

def verify_statistics():
    """Verify the updated statistics are displayed correctly."""
    app = create_app()
    
    with app.test_client() as client:
        # Set up session for admin access
        with client.session_transaction() as session:
            session['role'] = 'admin'
            session['user_id'] = 'test_admin'
        
        # Access the Online Suppliers page
        response = client.get('/suppliers')
        
        if response.status_code != 200:
            print(f"ERROR: Status code {response.status_code}")
            return False
        
        html = response.get_data(as_text=True)
        
        print("=== Final Verification of Updated Statistics ===")
        print("Checking Online Supplier page (/suppliers)")
        
        # Expected statistics in top toolbar
        expected_stats = [
            ("Active Suppliers", "1"),
            ("Pending Inquiries", "4"),
            ("Pending Quotations", "0"),
            ("Total Due", "AED 0")
        ]
        
        all_passed = True
        
        # Check each expected statistic
        for label, expected_value in expected_stats:
            # Look for pattern: <strong>value</strong><small>label</small>
            import re
            pattern = rf'<strong>([^<]+)</strong><small>{re.escape(label)}</small>'
            match = re.search(pattern, html)
            
            if match:
                actual_value = match.group(1)
                if actual_value == expected_value:
                    print(f"[OK] {label}: {actual_value} (matches expected {expected_value})")
                else:
                    print(f"[FAIL] {label}: {actual_value} (expected {expected_value})")
                    all_passed = False
            else:
                print(f"[FAIL] {label}: Not found in page")
                all_passed = False
        
        # Also check that old statistics are NOT present
        old_stats = ["Fleet", "Double Shift", "Due"]
        for old_label in old_stats:
            if f"<small>{old_label}</small>" in html:
                print(f"⚠ Old statistic '{old_label}' still present (may be okay if used elsewhere)")
        
        # Check navigation buttons
        print("\n=== Navigation Buttons ===")
        nav_buttons = [
            "Dashboard",
            "Online Supplier Workspace",
            "Add New Supplier",
            "Registrations",
            "Quotations",
            "LPO Workspace",
            "Invoices",
            "Reports"
        ]
        
        for button in nav_buttons:
            if button in html:
                print(f"[OK] Navigation button: {button}")
            else:
                print(f"[WARNING] Navigation button missing: {button}")
        
        print("\n=== Summary ===")
        if all_passed:
            print("SUCCESS: All statistics updated correctly!")
            print("\nNew statistics displayed:")
            print("1. Active Suppliers - Shows total active online suppliers")
            print("2. Pending Inquiries - Shows inquiries with status 'Open' or 'Pending'")
            print("3. Pending Quotations - Shows quotations with review_status 'Pending'")
            print("4. Total Due - Shows total outstanding amount")
            return True
        else:
            print("FAILURE: Some statistics not updated correctly")
            return False

if __name__ == "__main__":
    success = verify_statistics()
    sys.exit(0 if success else 1)