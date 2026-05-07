import sqlite3
conn = sqlite3.connect('payroll.db')
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor]
print('All tables:')
for table in tables:
    if 'advance' in table.lower():
        print(f'  {table}')
        # show columns
        cols = conn.execute(f'PRAGMA table_info({table})').fetchall()
        for col in cols:
            print(f'    {col[1]}')
conn.close()