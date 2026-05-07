#!/usr/bin/env python3
with open('app/templates/supplier_detail.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the structure
in_block = False
block_depth = 0
for i, line in enumerate(lines):
    if '{% block' in line:
        in_block = True
        block_depth += 1
        print(f"Line {i+1}: START BLOCK - {line.strip()}")
    elif '{% endblock' in line:
        block_depth -= 1
        print(f"Line {i+1}: END BLOCK - {line.strip()}")
        if block_depth == 0:
            in_block = False
    elif '<script>' in line and i > 1020:
        print(f"Line {i+1}: SCRIPT TAG - {line.strip()}")
        # Show next few lines
        for j in range(i, min(i+5, len(lines))):
            print(f"  {j+1}: {lines[j].rstrip()}")
    elif 'function openInquiryModal' in line:
        print(f"Line {i+1}: FUNCTION DEFINITION - {line.strip()}")

# Check if script is inside or outside block
print("\n=== Checking if script is inside content block ===")
# Find the main content block
for i, line in enumerate(lines):
    if '{% block content %}' in line:
        print(f"Main content block starts at line {i+1}")
        # Find matching endblock
        for j in range(i+1, len(lines)):
            if '{% endblock %}' in lines[j]:
                print(f"Main content block ends at line {j+1}")
                # Check if script is between i and j
                script_line = None
                for k in range(i, j+1):
                    if '<script>' in lines[k]:
                        script_line = k+1
                        break
                if script_line:
                    print(f"Script tag found INSIDE content block at line {script_line}")
                else:
                    print("Script tag NOT FOUND inside content block")
                break
        break