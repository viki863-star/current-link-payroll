import sqlite3
conn = sqlite3.connect('payroll.db')
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
for row in cursor:
    table = row[0]
    cols = conn.execute(f'PRAGMA table_info({table})').fetchall()
    for col in cols:
        if 'voucher_type' in col[1].lower():
            print(f'Table {table} has column {col[1]}')
conn.close()