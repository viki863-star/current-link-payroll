file_path = r'c:\Users\user\current-link-payroll\app\hr\routes.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add error handling to the entire employee_new function
old_func_start = '''@hr_bp.route("/hr/employees/new", methods=["GET", "POST"])
@_login_required("admin")
def employee_new():
    _touch_admin_workspace("hr")
    ensure_employees_table()
    db = open_db()

    values = employee_form_data()
    if not values["employee_id"]:
        values["employee_id"] = next_employee_id(db)

    vehicles = db.execute("SELECT plate_no, vehicle_type, model FROM vehicles WHERE status = 'Active' ORDER BY plate_no").fetchall()'''

new_func_start = '''@hr_bp.route("/hr/employees/new", methods=["GET", "POST"])
@_login_required("admin")
def employee_new():
    try:
        _touch_admin_workspace("hr")
        ensure_employees_table()
        db = open_db()

        values = employee_form_data()
        if not values["employee_id"]:
            values["employee_id"] = next_employee_id(db)

        vehicles = db.execute("SELECT plate_no, vehicle_type, model FROM vehicles WHERE status = 'Active' ORDER BY plate_no").fetchall()
    except Exception as e:
        import traceback
        current_app.logger.error(f"Employee new page error: {e}\\n{traceback.format_exc()}")
        flash(f"Error loading employee form: {str(e)}", "error")
        return redirect(url_for("hr.employee_list"))'''

content = content.replace(old_func_start, new_func_start)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Added error handling to GET request')
