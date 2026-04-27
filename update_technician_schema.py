#!/usr/bin/env python3
"""Update technician schema to make technician_code and party_code nullable."""

import re

def main():
    with open('app/database.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace SQLITE_SCHEMA technicians table
    # Find the CREATE TABLE statement for technicians in SQLITE_SCHEMA
    sqlite_pattern = r'(CREATE TABLE IF NOT EXISTS technicians \(\s*id INTEGER PRIMARY KEY AUTOINCREMENT,\s*technician_code TEXT )NOT NULL (UNIQUE,\s*party_code TEXT )NOT NULL (,)'
    sqlite_replacement = r'\1\2\3'
    
    # Find the CREATE TABLE statement for technicians in POSTGRES_SCHEMA  
    postgres_pattern = r'(CREATE TABLE IF NOT EXISTS technicians \(\s*id BIGSERIAL PRIMARY KEY,\s*technician_code TEXT )NOT NULL (UNIQUE,\s*party_code TEXT )NOT NULL (,)'
    postgres_replacement = r'\1\2\3'
    
    # Apply replacements
    new_content = re.sub(sqlite_pattern, sqlite_replacement, content, flags=re.DOTALL)
    new_content = re.sub(postgres_pattern, postgres_replacement, new_content, flags=re.DOTALL)
    
    # Check if changes were made
    if new_content != content:
        with open('app/database.py', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Database schema updated successfully")
    else:
        print("No changes made - pattern not found")
        
        # Try a different approach - manual replacement
        print("Trying manual replacement...")
        lines = content.split('\n')
        updated = False
        
        for i, line in enumerate(lines):
            if 'technician_code TEXT NOT NULL UNIQUE' in line:
                lines[i] = line.replace('technician_code TEXT NOT NULL UNIQUE', 'technician_code TEXT UNIQUE')
                updated = True
                print(f"Updated line {i+1}: {lines[i]}")
            elif 'party_code TEXT NOT NULL' in line and 'CREATE TABLE IF NOT EXISTS technicians' in '\n'.join(lines[max(0, i-5):i]):
                # Make sure we're in the technicians table
                lines[i] = line.replace('party_code TEXT NOT NULL', 'party_code TEXT')
                updated = True
                print(f"Updated line {i+1}: {lines[i]}")
        
        if updated:
            with open('app/database.py', 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print("Manual update successful")
        else:
            print("Manual update failed - patterns not found")

if __name__ == '__main__':
    main()