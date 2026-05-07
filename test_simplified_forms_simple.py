#!/usr/bin/env python3
"""
Simple test to verify simplified forms in template
"""

import os
import re

def check_template_fields():
    """Check the template file directly for field presence"""
    template_path = os.path.join('app', 'templates', 'supplier_mode_register.html')
    
    with open(template_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print("Checking supplier_mode_register.html template...")
    print("="*60)
    
    # Find all conditional blocks
    managed_start = content.find('{% if supplier_mode == "Managed" %}')
    partnership_start = content.find('{% elif supplier_mode == "Partnership" %}')
    else_start = content.find('{% else %}')
    
    if managed_start == -1:
        print("✗ Managed supplier condition not found")
        return
    
    if partnership_start == -1:
        print("✗ Partnership supplier condition not found")
        return
    
    if else_start == -1:
        print("✗ Else condition not found")
        return
    
    # Extract sections
    managed_section = content[managed_start:partnership_start]
    partnership_section = content[partnership_start:else_start]
    else_section = content[else_start:]
    
    print("\n1. MANAGED SUPPLIER FORM:")
    print("-" * 40)
    
    # Check for fields that SHOULD be present
    required_fields = [
        "Supplier Code", "Supplier Name", "Kind", "Contact Person",
        "Phone", "Email", "Address", "Notes", "Status"
    ]
    
    for field in required_fields:
        if field in managed_section:
            print(f"  [OK] '{field}' field found")
        else:
            print(f"  [FAIL] '{field}' field NOT found")
    
    # Check for fields that should NOT be present
    unwanted_fields = [
        "TRN / VAT", "Trade License", "Additional Tags",
        "Portal Login Email", "Portal Access"
    ]
    
    print("\n  Checking for unwanted fields:")
    for field in unwanted_fields:
        if field in managed_section:
            print(f"  [FAIL] UNWANTED: '{field}' found (should not be in simplified form)")
        else:
            print(f"  [OK] '{field}' not found (good)")
    
    # Check button text
    if "Create Managed Supplier Card" in managed_section:
        print("\n  [OK] Button text: 'Create Managed Supplier Card'")
    else:
        print("\n  [FAIL] Button text not found or incorrect")
    
    print("\n2. PARTNERSHIP SUPPLIER FORM:")
    print("-" * 40)
    
    # Check for basic fields
    for field in required_fields:
        if field in partnership_section:
            print(f"  ✓ '{field}' field found")
        else:
            print(f"  ✗ '{field}' field NOT found")
    
    # Check for partnership-specific fields
    partnership_fields = [
        "Partner Party", "Partner Name", "Company Share %", "Partner Share %"
    ]
    
    print("\n  Checking partnership-specific fields:")
    for field in partnership_fields:
        if field in partnership_section:
            print(f"  ✓ '{field}' field found")
        else:
            print(f"  ✗ '{field}' field NOT found")
    
    # Check for unwanted fields
    print("\n  Checking for unwanted fields:")
    for field in unwanted_fields:
        if field in partnership_section:
            print(f"  ✗ UNWANTED: '{field}' found (should not be in simplified form)")
        else:
            print(f"  ✓ '{field}' not found (good)")
    
    # Check button text
    if "Create Partnership Supplier Card" in partnership_section:
        print("\n  ✓ Button text: 'Create Partnership Supplier Card'")
    else:
        print("\n  ✗ Button text not found or incorrect")
    
    print("\n3. OTHER SUPPLIER MODES (Normal, Cash):")
    print("-" * 40)
    
    # Check that unwanted fields ARE present in else section
    print("  Checking that full form has all fields:")
    for field in unwanted_fields:
        if field in else_section:
            print(f"  ✓ '{field}' found in full form (expected)")
        else:
            print(f"  ? '{field}' not found in full form")
    
    # Check for portal fields in Normal supplier section
    if "Portal Login Email" in else_section:
        print("  ✓ Portal fields present in full form")
    
    print("\n" + "="*60)
    print("SUMMARY:")
    
    # Count form sections
    form_count = content.count('<form method="post" class="desk-form-grid')
    print(f"Total form sections in template: {form_count}")
    
    if form_count >= 3:
        print("✓ Template has multiple form sections (Managed, Partnership, Others)")
    else:
        print("✗ Expected at least 3 form sections")
    
    # Check for simplified-form class
    simplified_count = content.count('simplified-form')
    print(f"Forms with 'simplified-form' class: {simplified_count}")
    
    if simplified_count == 2:
        print("✓ Both Managed and Partnership forms are marked as simplified")
    else:
        print(f"✗ Expected 2 simplified forms, found {simplified_count}")

if __name__ == "__main__":
    check_template_fields()