#!/usr/bin/env python3
"""
Test script to verify updated statistics on Online Supplier page.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.database import open_db

def test_supplier_hub_summary():
    """Test the _supplier_hub_summary function with new statistics."""
    app = create_app()
    
    with app.app_context():
        db = open_db()
        
        # Import the function
        from app.routes import _supplier_hub_summary
        
        # Get summary for Normal mode (Online Suppliers)
        summary = _supplier_hub_summary(db, "Normal")
        
        print("=== Supplier Hub Summary (Normal Mode) ===")
        print(f"supplier_count: {summary.get('supplier_count', 0)}")
        print(f"asset_count: {summary.get('asset_count', 0)}")
        print(f"double_shift_count: {summary.get('double_shift_count', 0)}")
        print(f"outstanding_total: {summary.get('outstanding_total', 0)}")
        
        # New statistics
        print(f"\n=== New Statistics ===")
        print(f"pending_inquiries_count: {summary.get('pending_inquiries_count', 0)}")
        print(f"pending_quotations_count: {summary.get('pending_quotations_count', 0)}")
        print(f"active_inquiries_count: {summary.get('active_inquiries_count', 0)}")
        print(f"portal_users_count: {summary.get('portal_users_count', 0)}")
        print(f"open_vouchers: {summary.get('open_vouchers', 0)}")
        
        # Check if all keys exist
        required_keys = [
            'supplier_count', 'asset_count', 'double_shift_count', 
            'outstanding_total', 'pending_inquiries_count', 
            'pending_quotations_count', 'active_inquiries_count',
            'portal_users_count', 'open_vouchers'
        ]
        
        missing_keys = [key for key in required_keys if key not in summary]
        if missing_keys:
            print(f"\n[ERROR] Missing keys in summary: {missing_keys}")
            return False
        
        print(f"\n[OK] All statistics are available in summary")
        return True

def test_online_suppliers_route():
    """Test the /suppliers route (Online Suppliers page)."""
    app = create_app()
    
    with app.test_client() as client:
        # Set up session for admin access
        with client.session_transaction() as session:
            session['role'] = 'admin'
            session['user_id'] = 'test_admin'
        
        # Access the Online Suppliers page
        response = client.get('/suppliers')
        
        print(f"\n=== Online Suppliers Page Test ===")
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"[ERROR] Expected 200, got {response.status_code}")
            return False
        
        # Check if new statistics appear in HTML
        html = response.get_data(as_text=True)
        
        # Check for new statistics labels
        checks = [
            ("Pending Inquiries", "pending_inquiries_count label"),
            ("Pending Quotations", "pending_quotations_count label"),
            ("Portal Users", "portal_users_count label"),
            ("Active Suppliers", "active_suppliers label"),
        ]
        
        all_passed = True
        for text, description in checks:
            if text in html:
                print(f"[OK] Found '{text}' in page")
            else:
                print(f"[WARNING] '{text}' not found in page ({description})")
                all_passed = False
        
        # Check for numeric values (they should be rendered)
        import re
        # Look for pattern like <strong>0</strong> or <span class="stat-value">0</span>
        strong_pattern = r'<strong>(\d+)</strong>'
        stat_value_pattern = r'<span class="stat-value">(\d+)</span>'
        
        strong_matches = re.findall(strong_pattern, html)
        stat_matches = re.findall(stat_value_pattern, html)
        
        print(f"\nFound {len(strong_matches)} <strong>number</strong> elements")
        print(f"Found {len(stat_matches)} stat-value elements")
        
        if len(strong_matches) >= 4:  # At least 4 statistics in top toolbar
            print("[OK] Statistics are being rendered with numbers")
        else:
            print("[WARNING] Fewer statistics numbers than expected")
            all_passed = False
        
        return all_passed

def main():
    print("Testing Updated Statistics on Online Supplier Page")
    print("=" * 50)
    
    # Test 1: Function level
    func_ok = test_supplier_hub_summary()
    
    # Test 2: Route level
    route_ok = test_online_suppliers_route()
    
    print("\n" + "=" * 50)
    print("SUMMARY:")
    print(f"Function test: {'PASS' if func_ok else 'FAIL'}")
    print(f"Route test: {'PASS' if route_ok else 'FAIL'}")
    
    if func_ok and route_ok:
        print("\n[SUCCESS] All tests passed!")
        return 0
    else:
        print("\n[FAILURE] Some tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())