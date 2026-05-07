#!/usr/bin/env python3
import re

with open('app/templates/supplier_detail.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find modal using regex to get complete modal
pattern = r'<div id="inquiryModal"[^>]*>.*?</div>\s*</div>\s*</div>'
match = re.search(pattern, content, re.DOTALL)
if match:
    modal = match.group(0)
    print(f"Modal length: {len(modal)}")
    print("\n--- Modal content (first 1000 chars) ---")
    print(modal[:1000])
    print("\n--- Contains csrf_token? ---")
    print('csrf_token' in modal)
    print("\n--- Contains form? ---")
    print('<form method="post"' in modal)
    
    # Find csrf token line
    lines = modal.split('\n')
    for i, line in enumerate(lines):
        if 'csrf_token' in line:
            print(f"\nCSRF token line {i}: {line.strip()}")
else:
    print("Modal not found with regex")
    
    # Try simpler search
    start = content.find('<div id="inquiryModal"')
    if start != -1:
        # Find closing div for the modal (look for </div> with proper nesting)
        # Simple approach: find next occurrence of </div> after modal start
        end = content.find('</div>', start)
        if end != -1:
            modal = content[start:end+6]
            print(f"\nSimple modal extraction (length {len(modal)}):")
            print(modal[:500])
            print("\nContains csrf_token:", 'csrf_token' in modal)