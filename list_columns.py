import sqlite3
conn = sqlite3.connect('payroll.db')
cursor = conn.execute('PRAGMA table_info(supplier_vouchers)')
print('Columns:')
for row in cursor:
    print(f'{row[1]} ({row[2]})')
conn.close()