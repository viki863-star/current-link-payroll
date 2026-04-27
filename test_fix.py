import sqlite3
conn = sqlite3.connect('payroll.db')
cursor = conn.execute("""
SELECT COUNT(*)
FROM supplier_vouchers sv
JOIN supplier_profile p ON sv.party_code = p.party_code
WHERE p.supplier_mode IN ('Cash', 'Loan') AND 1=0
""")
result = cursor.fetchone()
print('Query executed successfully, count:', result[0])
conn.close()