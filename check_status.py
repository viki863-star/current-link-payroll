import sqlite3
conn = sqlite3.connect('payroll.db')
cursor = conn.execute('SELECT DISTINCT status FROM supplier_vouchers')
print('Distinct status values:')
for row in cursor:
    print(row)
cursor = conn.execute('SELECT DISTINCT source_type FROM supplier_vouchers')
print('Distinct source_type values:')
for row in cursor:
    print(row)
conn.close()