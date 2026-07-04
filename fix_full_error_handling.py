file_path = r'c:\Users\user\current-link-payroll\app\hr\routes.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the function and restructure it to have proper error handling
# The try block should wrap the entire function body, not just the initial setup

# Find the line with "try:" after "def employee_new():"
try_line_idx = None
for i, line in enumerate(lines):
    if 'def employee_new():' in line:
        try_line_idx = i + 1  # Next line should be try
        break

if try_line_idx is not None:
    # Remove the try block that only wraps the initial setup
    # We need to move the try block to wrap the entire function body
    # Find the matching except block
    except_line_idx = None
    indent_level = 8  # The function body is at 8 spaces
    
    for i in range(try_line_idx, len(lines)):
        if '        except Exception as e:' in lines[i]:
            except_line_idx = i
            break
    
    if except_line_idx is not None:
        # Remove the try and except lines
        del lines[try_line_idx]  # Remove "try:"
        del lines[except_line_idx - 1]  # Remove the except block (shifted by 1)
        
        # Add a single try block at the start of the function body
        lines.insert(try_line_idx, '    try:\n')
        
        # Find the end of the function (next function definition or end of file)
        end_idx = len(lines)
        for i in range(try_line_idx + 1, len(lines)):
            if lines[i].strip().startswith('@') or lines[i].strip().startswith('# ──'):
                end_idx = i
                break
        
        # Add except block before the end
        except_block = '''    except Exception as e:
        import traceback
        current_app.logger.error(f"Employee creation error: {e}\\n{traceback.format_exc()}")
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for("hr.employee_list"))

'''
        lines.insert(end_idx, except_block)

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Restructured error handling to wrap entire function')
