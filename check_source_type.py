import sqlite3
conn = sqlite3.connect('payroll.db')
cursor = conn.execute('SELECT DISTINCT source_type FROM supplier_vouchers LIMIT 10')
print('Distinct source_type values:')
for row in cursor:
    print(row)
cursor = conn.execute('SELECT COUNT(*) FROM supplier_vouchers WHERE source_type = ?', ('Advance',))
print('Rows with source_type = Advance:', cursor.fetchone()[0])
cursor = conn.execute('SELECT COUNT(*) FROM supplier_vouchers')
print('Total rows:', cursor.fetchone()[0])
conn.close()