#!/usr/bin/env python3
"""Test the new portal feature for Online Suppliers"""

import sys
sys.path.insert(0, '.')

# Mock Flask app context
from app.routes import _supplier_screen_options, _normalize_supplier_screen

print("=== Testing Portal Feature ===")

# Test 1: Screen options for Normal mode
print("\n1. Testing screen options for Normal mode:")
options = _supplier_screen_options('Normal')
for i, opt in enumerate(options):
    print(f"   {i+1}. {opt['key']}: {opt['label']}")

# Check if portal is first
if options[0]['key'] == 'portal':
    print("   [OK] Portal screen is first option")
else:
    print("   [FAIL] Portal screen not first")

# Test 2: Screen normalization
print("\n2. Testing screen normalization:")
test_cases = [
    ('portal', 'Normal', 'portal'),
    ('vehicles', 'Normal', 'portal'),  # vehicles is not a valid option for Normal mode now, should default to portal
    ('statement', 'Normal', 'statement'),
    ('', 'Normal', 'portal'),  # default should be portal now
    ('', 'Cash', 'kata'),
]

for screen, mode, expected in test_cases:
    result = _normalize_supplier_screen(screen, mode)
    status = "[OK]" if result == expected else "[FAIL]"
    print(f"   {status} normalize('{screen}', '{mode}') = '{result}' (expected: '{expected}')")

# Test 3: Check default screen function
print("\n3. Testing default screen:")
from app.routes import _default_supplier_screen

# For Normal mode, default should be portal now
default_normal = _default_supplier_screen('Normal')
print(f"   Default for Normal mode: {default_normal}")
if default_normal == 'portal':
    print("   [OK] Default is portal for Normal mode")
else:
    print("   [FAIL] Default should be portal but is", default_normal)

print("\n=== All tests completed ===")