import sqlite3
conn = sqlite3.connect('payroll.db')
cursor = conn.cursor()

# Check current inquiries
cursor.execute('SELECT COUNT(*) FROM supplier_inquiries')
count = cursor.fetchone()[0]
print(f'Current inquiry count: {count}')

# Check if table has data
cursor.execute('SELECT * FROM supplier_inquiries')
rows = cursor.fetchall()
print(f'All inquiries: {rows}')

# Try to insert manually
try:
    cursor.execute('''
        INSERT INTO supplier_inquiries (
            inquiry_no, party_code, inquiry_date, subject, description,
            priority, status, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', ('INQ-TEST-001', 'PTY-0001', '2026-04-30', 'Test', 'Test desc', 'Normal', 'Open', 'Admin'))
    conn.commit()
    print('Manual insert successful')
except Exception as e:
    print(f'Manual insert error: {e}')

cursor.execute('SELECT COUNT(*) FROM supplier_inquiries')
print(f'New inquiry count: {cursor.fetchone()[0]}')

conn.close()