file_path = r'c:\Users\user\current-link-payroll\app\hr\routes.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the assigned_vehicle reference in render_template
old_line = '        assigned_vehicle=assigned_vehicle["vehicle_id"] if assigned_vehicle else "",'
new_line = '        assigned_vehicle="",'

content = content.replace(old_line, new_line)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed assigned_vehicle reference')
