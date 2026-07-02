import json
import re
import os
import requests
from datetime import date
from flask import request, jsonify, current_app
from . import ai_bp
from ..database import open_db

SCHEMA_DESC = """Available tables:

1. employees(employee_id, full_name, phone_number, email, employee_type, department, designation, basic_salary, ot_rate, status, join_date, termination_date)
2. drivers(driver_id, full_name, phone_number, vehicle_no, shift, vehicle_type, basic_salary, ot_rate, status, termination_date)
3. field_staff(staff_id, full_name, phone, username, is_active)
4. cash_receipts(staff_id, given_by, amount, receipt_date)
5. vehicles(plate_no, vehicle_type, model, year, ownership_type, status)
6. vehicle_assignments(vehicle_id, driver_id, assigned_from, assigned_until, is_current)
7. salary_store(driver_id/employee_id, salary_month, basic_salary, ot_amount, advances, deductions, net_salary)
8. salary_slips(employee_id, salary_month, basic_salary, net_salary, status)
9. salary_payments(employee_id, salary_month, amount, payment_date)
10. maintenance_jobs(vehicle_id, staff_id, amount, category, status, description)
11. technicians(technician_code, user_id, phone_number, specialization, status)
12. maintenance_staff_advances(staff_code, amount, advance_date)
13. maintenance_papers(technician_code, total_amount, review_status)
14. parties(party_code, party_name, phone, role, status)
15. suppliers(supplier_code, supplier_name, category, status)
16. supplier_invoices(supplier_code, invoice_no, amount, status)
17. supplier_bills(supplier_code, bill_no, amount, vat_amount, total_amount, status)
18. account_invoices(invoice_no, party_code, total_amount, status)
19. account_invoice_lines(invoice_id, description, quantity, unit_price, amount)
20. account_payments(invoice_id, amount, payment_date)
21. fuel_entries(vehicle_id, liters, rate, total_cost, entry_date)
"""


def _execute_sql(sql):
    db = open_db()
    try:
        result = db.execute(sql).fetchall()
        if not result:
            return []
        return [dict(row) for row in result]
    except Exception as e:
        return {"error": str(e)}


def _call_gemini(messages, api_key=None):
    api_key = api_key or os.getenv("GEMINI_API_KEY") or current_app.config.get("GEMINI_API_KEY", "")
    if not api_key:
        return None, "GEMINI_API_KEY not configured. Set it in .env file."

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"

    gemini_contents = []
    for msg in messages:
        role = "user" if msg["role"] in ("user", "system") else "model"
        gemini_contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    payload = {
        "contents": gemini_contents,
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        data = resp.json()
        if "candidates" not in data or not data["candidates"]:
            err = data.get("error", {}).get("message", str(data))
            return None, f"Gemini API error: {err}"

        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip()

        parsed = json.loads(text)
        return parsed, None
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON from Gemini: {e}\nRaw: {text[:200]}"
    except Exception as e:
        return None, str(e)


@ai_bp.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "Message is required"}), 400

        user_msg = data["message"].strip()
        history = data.get("history", [])

        today = date.today().isoformat()
        system = (
            "You are an ERP AI assistant for Current Link Transport & General Contracting. "
            "Answer questions by writing SQL SELECT queries. "
            f"Current date: {today}.\n\n"
            + SCHEMA_DESC +
            "Rules:\n"
            "- Respond ONLY with valid JSON: {\"sql\": \"SELECT ...\", \"explanation\": \"...\"}\n"
            "- Use SELECT queries only (read-only)\n"
            "- Use SQLite syntax (? placeholders) - system auto-converts for PostgreSQL\n"
            "- Use strftime for dates in SQLite, EXTRACT in PostgreSQL\n"
            "- Use COALESCE for NULL values\n"
            "- Limit results to 20 rows\n"
            "- Explanation in same language as the user's question\n"
            "- For counts/sums always include the computed value in explanation\n"
            "- Use ROUND for currency amounts\n"
            "\nExample:\n"
            'User: "FS-01 ki total cash receipts?"\n'
            'Assistant: {"sql": "SELECT COUNT(*) AS cnt, COALESCE(SUM(amount),0) AS tot FROM cash_receipts WHERE staff_id = \'FS-01\'", "explanation": "FS-01 ne 5 cash receipts diye, total AED 1200"}\n\n'
            'User: "Kitne active drivers?"\n'
            'Assistant: {"sql": "SELECT COUNT(*) AS cnt FROM drivers WHERE status = \'Active\'", "explanation": "15 active drivers hain"}'
        )

        messages = [{"role": "system", "content": system}]
        for h in history[-8:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_msg})

        result, err = _call_gemini(messages)
        if err:
            return jsonify({"error": err}), 500

        if not isinstance(result, dict):
            return jsonify({"reply": str(result), "sql": None, "data": None})

        explanation = result.get("explanation", "")
        sql = result.get("sql", "")

        if not sql:
            return jsonify({"reply": explanation or "Sorry, I couldn't process that.", "sql": None, "data": None})

        rows = _execute_sql(sql)
        if isinstance(rows, dict) and "error" in rows:
            return jsonify({"reply": f"SQL error: {rows['error']}", "sql": sql, "data": None})

        if rows and explanation:
            try:
                for row in rows[:1]:
                    for k, v in row.items():
                        ph = "{" + k + "}"
                        if ph in explanation:
                            explanation = explanation.replace(ph, str(v) if v is not None else "0")
            except Exception:
                pass

        if not explanation and rows:
            parts = []
            for row in rows[:5]:
                parts.append(" | ".join(f"{k}: {v}" for k, v in row.items()))
            explanation = "\n".join(parts)

        return jsonify({"reply": explanation or "Done.", "sql": sql, "data": rows[:20] if rows else None})

    except Exception as e:
        import traceback
        current_app.logger.error("AI Chat error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": f"Server error: {e}"}), 500
