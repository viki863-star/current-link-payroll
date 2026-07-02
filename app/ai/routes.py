import json
import re
import os
import requests
from flask import request, jsonify, current_app
from . import ai_bp
from ..database import open_db

SYSTEM_PROMPT = """You are an ERP AI assistant for Current Link Transport & General Contracting. Your job is to answer questions about the company data by writing SQL queries.

Available tables and their key columns:

1. **employees** — employee_id (TEXT PK), full_name, phone_number, email, employee_type (Driver/Field Staff/Staff), department, designation, basic_salary, ot_rate, status (Active/Terminated/Inactive), join_date, termination_date, nationality, iqama_no, passport_no, bank_name, bank_account, iban
2. **drivers** — driver_id (TEXT PK), full_name, phone_number, vehicle_no, shift, vehicle_type, basic_salary, ot_rate, duty_start, status, termination_date
3. **field_staff** — staff_id (TEXT PK), full_name, phone, username, is_active
4. **cash_receipts** — id (INTEGER PK), staff_id → field_staff.staff_id, given_by, amount, receipt_date, notes
5. **vehicles** — plate_no (TEXT PK), vehicle_type, model, year, ownership_type (Standard/Partner), partner_name, partner_percent, status
6. **vehicle_assignments** — id (INTEGER PK), vehicle_id → vehicles.plate_no, driver_id, assigned_from, assigned_until, is_current
7. **salary_store** — id, driver_id/employee_id, entry_date, salary_month, salary_mode, basic_salary, ot_amount, advances, deductions, net_salary, remarks
8. **salary_slips** — id, employee_id, salary_month, basic_salary, ot_amount, advances, deductions, net_salary, status, generated_at
9. **salary_payments** — id, employee_id, salary_month, amount, payment_date, payment_mode, notes
10. **maintenance_jobs** — id, vehicle_id, staff_id, amount, category, description, status (pending/approved/rejected), created_at
11. **technicians** — technician_code, user_id, phone_number, specialization, status
12. **maintenance_staff_advances** — id, staff_code, amount, advance_date, notes
13. **maintenance_papers** — id, paper_no, technician_code, total_amount, review_status, created_at
14. **parties** — party_code (TEXT PK), party_name, phone, email, address, role, status
15. **suppliers** — id, supplier_code, supplier_name, contact_person, phone, email, category, status
16. **supplier_invoices** — id, supplier_code, invoice_no, invoice_date, amount, status
17. **supplier_bills** — id, supplier_code, bill_no, bill_date, amount, vat_amount, total_amount, status
18. **account_invoices** — id, invoice_no, party_code, invoice_date, total_amount, status
19. **account_invoice_lines** — id, invoice_id → account_invoices.id, description, quantity, unit_price, amount
20. **account_payments** — id, invoice_id, amount, payment_date, payment_mode
21. **fuel_entries** — id, vehicle_id, liters, rate, total_cost, entry_date, driver_id
22. **vehicles** (alias for vehicle records in maintenance) — plate_no, vehicle_type, model, status

Rules:
- ALWAYS respond with a JSON object: {"sql": "SELECT ...", "explanation": "..."}
- SQL must be a SELECT query ONLY (read-only)
- Use SQLite-compatible syntax (for PostgreSQL text columns use standard SQL)
- Use strftime for date extraction in SQLite, EXTRACT or TO_CHAR in PostgreSQL
- Current date is {today}
- When the user asks about "FS-01", "DRV-28", etc., use that as employee_id/driver_id/staff_id
- For amounts, use ROUND(column, 2) or CAST as needed
- Keep results to max 20 rows
- Use COALESCE for NULL values
- Use appropriate JOINs when data spans tables
- The explanation should be in the same language as the user's question (Urdu/English)
- If the question cannot be answered with SQL, explain why in a helpful way
- For summary questions (count, sum, average), always provide the calculated value

Example:
User: "FS-01 ne kitne cash receipts diye?"
Assistant: {{"sql": "SELECT COUNT(*) AS count, COALESCE(SUM(amount),0) AS total FROM cash_receipts WHERE staff_id = 'FS-01'", "explanation": "FS-01 ne {count} cash receipts diye hain, total AED {total}"}}

User: "Kitne active drivers hain?"
Assistant: {{"sql": "SELECT COUNT(*) AS count FROM drivers WHERE status = 'Active'", "explanation": "Total {count} active drivers hain."}}
"""


def _get_db_backend():
    return current_app.config.get("DATABASE_BACKEND", "sqlite")


def _execute_sql(sql):
    db = open_db()
    try:
        result = db.execute(sql).fetchall()
        if not result:
            return []
        columns = list(result[0].keys()) if hasattr(result[0], "keys") else []
        rows = [dict(row) for row in result]
        return rows
    except Exception as e:
        return {"error": str(e)}


def _call_llm(messages, api_key=None):
    api_key = api_key or os.getenv("GEMINI_API_KEY") or current_app.config.get("GEMINI_API_KEY", "")
    if not api_key:
        return None, "GEMINI_API_KEY not configured. Set it in .env file."

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    gemini_contents = []
    for msg in messages:
        role = "user" if msg["role"] in ("user", "system") else "model"
        text = msg["content"]
        gemini_contents.append({
            "role": role,
            "parts": [{"text": text}]
        })

    payload = {
        "contents": gemini_contents,
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1024,
        }
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        data = resp.json()
        if "candidates" in data and data["candidates"]:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            text = text.strip()
            if text.startswith("```"):
                text = re.sub(r'^```(?:json)?\s*', '', text)
                text = re.sub(r'\s*```$', '', text)
            return json.loads(text), None
        error_msg = data.get("error", {}).get("message", str(data))
        return None, error_msg
    except Exception as e:
        return None, str(e)


@ai_bp.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Message is required"}), 400

    user_message = data["message"].strip()
    history = data.get("history", [])

    today = __import__("datetime").date.today().isoformat()
    system = SYSTEM_PROMPT.format(today=today)

    messages = [{"role": "system", "content": system}]
    for h in history[-10:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_message})

    result, error = _call_llm(messages)
    if error:
        return jsonify({"error": error}), 500

    if not result or "sql" not in result:
        explanation = result.get("explanation", "Sorry, I couldn't process that.")
        return jsonify({
            "reply": explanation,
            "sql": None,
            "data": None
        })

    sql = result["sql"].strip()
    explanation = result.get("explanation", "")

    rows = _execute_sql(sql)
    if isinstance(rows, dict) and "error" in rows:
        return jsonify({
            "reply": f"SQL error: {rows['error']}",
            "sql": sql,
            "data": None
        })

    if rows and explanation:
        try:
            formatted = explanation
            for i, row in enumerate(rows):
                for key, val in row.items():
                    placeholder = "{" + key + "}"
                    if placeholder in formatted:
                        formatted = formatted.replace(placeholder, str(val) if val is not None else "0")
                    elif i == 0:
                        formatted = formatted.replace("{" + key + "}", str(val) if val is not None else "0")
            explanation = formatted
        except Exception:
            pass

    if not explanation and rows:
        explanation = "Here are the results:"
        for row in rows[:5]:
            explanation += "\n" + ", ".join(f"{k}: {v}" for k, v in row.items())

    return jsonify({
        "reply": explanation or "Done.",
        "sql": sql,
        "data": rows[:20] if rows else None
    })

from app import csrf
csrf.exempt(chat)
