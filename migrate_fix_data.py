"""
PostgreSQL data migration: fix empty LPO numbers, 0-rate invoice/LPO items.

Run on the production server:
    python migrate_fix_data.py

Requires DATABASE_URL environment variable to be set (same as the web app).
"""
import os
import sys

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable not set.")
    sys.exit(1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = False
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
fixed = {"lpos_empty_no": 0, "lpos_no_items": 0, "lpo_items_fixed": 0,
         "invoices_no_items": 0, "invoice_items_fixed": 0, "invoices_linked": 0}

print("=== LPOs with empty LPO number ===")
cur.execute("SELECT id, customer_id, amount, service_order_no FROM customer_lpos WHERE lpo_no IS NULL OR lpo_no = ''")
lpos_empty = cur.fetchall()
if not lpos_empty:
    print("  None found.")
else:
    print(f"  Found {len(lpos_empty)} LPO(s) with no number.")
    for l in lpos_empty:
        cur.execute("SELECT customer_name FROM customers WHERE id=%s", (l["customer_id"],))
        c = cur.fetchone()
        cname = c["customer_name"] if c else "?"
        print(f"    ID={l['id']} | Customer={cname} | Amount=AED {l['amount'] or 0} | SO={l['service_order_no'] or '—'}")
    answer = input("  Enter a generic LPO prefix to assign (e.g. 'LPO-') or 'skip' to skip: ").strip()
    if answer.lower() != "skip" and answer:
        idx = 1
        for l in lpos_empty:
            new_no = f"{answer}{idx}"
            cur.execute("UPDATE customer_lpos SET lpo_no=%s WHERE id=%s", (new_no, l["id"]))
            print(f"    LPO ID {l['id']} -> {new_no}")
            idx += 1
            fixed["lpos_empty_no"] += 1
        conn.commit()
        print(f"  Assigned numbers to {fixed['lpos_empty_no']} LPO(s).")
    else:
        conn.rollback()
        print("  Skipped.")

print()
print("=== LPOs with amount > 0 but empty line items ===")
cur.execute("""SELECT l.id, l.customer_id, l.amount, l.lpo_no
    FROM customer_lpos l
    WHERE (l.amount IS NOT NULL AND l.amount > 0)
      AND NOT EXISTS (SELECT 1 FROM lpo_items li WHERE li.lpo_id = l.id AND li.amount > 0)""")
lpos_no_items = cur.fetchall()
if not lpos_no_items:
    print("  None found.")
else:
    print(f"  Found {len(lpos_no_items)} LPO(s) with amount but no valid items.")
    for l in lpos_no_items:
        print(f"    ID={l['id']} LPO={l['lpo_no'] or '—'} Amount=AED {l['amount']}")
        cur.execute("INSERT INTO lpo_items (lpo_id, description, quantity, rate, amount, unit_type, sort_order) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (l["id"], "Service as per agreement", 1, l["amount"], l["amount"], "hour", 0))
        fixed["lpo_items_fixed"] += 1
    conn.commit()
    print(f"  Created {fixed['lpo_items_fixed']} default item(s) for LPO(s).")

print()
print("=== Invoices with amount > 0 but empty line items ===")
cur.execute("""SELECT i.id, i.customer_id, i.amount, i.invoice_no, i.lpo_no
    FROM customer_invoices i
    WHERE (i.amount IS NOT NULL AND i.amount > 0)
      AND NOT EXISTS (SELECT 1 FROM customer_invoice_items ii WHERE ii.invoice_id = i.id AND ii.amount > 0)""")
inv_no_items = cur.fetchall()
if not inv_no_items:
    print("  None found.")
else:
    print(f"  Found {len(inv_no_items)} invoice(s) with amount but no valid items.")
    for i in inv_no_items:
        print(f"    ID={i['id']} Invoice={i['invoice_no'] or '—'} Amount=AED {i['amount']}")
        cur.execute("INSERT INTO customer_invoice_items (invoice_id, description, quantity, rate, amount, unit, sort_order) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (i["id"], "Service as per agreement", 1, i["amount"], i["amount"], "hour", 0))
        fixed["invoice_items_fixed"] += 1
    conn.commit()
    print(f"  Created {fixed['invoice_items_fixed']} default item(s) for invoice(s).")

print()
print("=== Invoices with no LPO reference — try to match by customer + amount ===")
cur.execute("""SELECT i.id, i.invoice_no, i.customer_id, i.amount
    FROM customer_invoices i
    WHERE (i.lpo_no IS NULL OR i.lpo_no = '')
      AND (i.amount IS NOT NULL AND i.amount > 0)""")
inv_no_lpo = cur.fetchall()
if not inv_no_lpo:
    print("  None found.")
else:
    matched = 0
    for i in inv_no_lpo:
        cur.execute("""SELECT id, lpo_no FROM customer_lpos
            WHERE customer_id=%s AND amount=%s AND (lpo_no IS NOT NULL AND lpo_no != '')
            LIMIT 1""", (i["customer_id"], i["amount"]))
        lpo = cur.fetchone()
        if lpo:
            cur.execute("UPDATE customer_invoices SET lpo_no=%s WHERE id=%s", (lpo["lpo_no"], i["id"]))
            matched += 1
            print(f"    Invoice {i['invoice_no'] or i['id']} -> LPO {lpo['lpo_no']} (AED {i['amount']})")
    if matched:
        conn.commit()
        fixed["invoices_linked"] = matched
        print(f"  Linked {matched} invoice(s) to LPOs.")
    else:
        print("  No matches found (no LPO with same customer+amount+number).")
        conn.rollback()

print()
print("=== SUMMARY ===")
print(f"  LPOs assigned numbers:     {fixed['lpos_empty_no']}")
print(f"  LPOs with items created:   {fixed['lpo_items_fixed']}")
print(f"  Invoices with items created: {fixed['invoice_items_fixed']}")
print(f"  Invoices linked to LPO:    {fixed['invoices_linked']}")

cur.close()
conn.close()
