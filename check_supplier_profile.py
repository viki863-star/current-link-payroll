import sqlite3
conn = sqlite3.connect('payroll.db')
cursor = conn.execute('PRAGMA table_info(supplier_profile)')
print('supplier_profile columns:')
for row in cursor:
    print(row[1])
conn.close()