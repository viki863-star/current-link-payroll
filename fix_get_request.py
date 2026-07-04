file_path = r'c:\Users\user\current-link-payroll\app\hr\routes.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the assigned_vehicle query that runs on GET request for new employees
# This query is unnecessary for new employees and can fail if vehicle_assignments table doesn't exist
old_code = '''    assigned_vehicle = db.execute(
        "SELECT vehicle_id FROM vehicle_assignments WHERE driver_id = ? AND is_current = 1 LIMIT 1",
        (values["employee_id"],),
    ).fetchone()
    return render_template('''

new_code = '''    # For new employees, no assigned vehicle needed
    assigned_vehicle = None
    return render_template('''

content = content.replace(old_code, new_code)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed GET request error by removing unnecessary vehicle assignment query')
