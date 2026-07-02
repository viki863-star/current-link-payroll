import json
import re
import os
import requests
from datetime import date
from flask import request, jsonify, current_app
from . import ai_bp
from ..database import open_db

SCHEMA = """
employees(employee_id TEXT pk, full_name, phone, email, type, dept, salary NUMERIC, status)
drivers(driver_id TEXT pk, full_name, phone, vehicle_no, shift, salary NUMERIC, status)
field_staff(staff_id TEXT pk, full_name, phone, username)
cash_receipts(staff_id TEXT, amount NUMERIC, receipt_date)
vehicles(plate_no TEXT pk, type, model, year INT, status)
vehicle_assignments(vehicle_id TEXT, driver_id TEXT, is_current INT=1)
salary_store(emp_id TEXT, month, basic NUMERIC, ot, deductions, net NUMERIC)
salary_slips(emp_id, month, basic NUMERIC, net, status)
salary_payments(emp_id, month, amount NUMERIC, date)
maintenance_jobs(vehicle_id TEXT, staff_id TEXT, amount NUMERIC, category, status)
technicians(technician_code TEXT pk, user_id, phone)
maintenance_advances(staff_code TEXT, amount, date)
maintenance_papers(paper_no TEXT, total, status)
parties(party_code TEXT pk, name, phone, role, status)
suppliers(supplier_code TEXT, name, category, status)
supplier_invoices(invoice_no TEXT, supplier_code, amount, status)
supplier_bills(bill_no TEXT, supplier_code, amount, vat, total, status)
account_invoices(invoice_no TEXT, party_code, total, status)
fuel_entries(vehicle_id TEXT, liters, cost, date)
"""


def _execute_sql(sql):
    db = open_db()
    try:
        result = db.execute(sql).fetchall()
        return [dict(row) for row in result] if result else []
    except Exception as e:
        return {"error": str(e)}


def _call_llm(messages):
    api_key = os.getenv("AI_API_KEY") or os.getenv("GROQ_API_KEY") or ""
    api_url = os.getenv("AI_API_URL", "https://api.groq.com/openai/v1/chat/completions")
    api_model = os.getenv("AI_MODEL", "llama-3.3-70b-versatile")

    if not api_key:
        return None, "AI_API_KEY not configured. Set in .env"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": api_model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 1024,
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=30)
        data = resp.json()
        if "choices" not in data or not data["choices"]:
            err = data.get("error", {}).get("message", str(data))
            return None, f"AI error: {err}"

        raw = data["choices"][0]["message"]["content"].strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        raw = raw.strip()

        # Try to extract JSON from anywhere in the response
        json_match = re.search(r'\{[^{}]*"sql"[^{}]*\}', raw, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                return parsed, None
            except json.JSONDecodeError:
                pass

        # Fallback: try parsing whole response as JSON
        if raw.startswith("{"):
            try:
                return json.loads(raw), None
            except json.JSONDecodeError:
                pass

        # Use entire response as explanation
        prefix = re.sub(r'\{.*', '', raw, count=1).strip()
        return {"explanation": prefix or raw, "sql": ""}, None
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

        backend = current_app.config.get("DATABASE_BACKEND", "sqlite")
        pg = " CRITICAL: TEXT columns need single-quoted values. NEVER compare TEXT=INT. is_current is INT 0/1." if backend == "postgres" else ""

        system = (
            f"Date:{today}. ERP SQL assistant.{pg}\n"
            f"Tables:\n{SCHEMA}\n"
            'Reply ONLY JSON: {"sql":"SELECT...","explanation":"answer in user language with {column_aliases}"}. '
            "SELECT only. ALWAYS use AS aliases for columns. "
            'Ex: {"sql":"SELECT count(*) AS cnt FROM drivers WHERE status=\'Active\'","explanation":"{cnt} active drivers hain"}'
        )

        messages = [{"role": "system", "content": system}]
        for h in history[-8:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_msg})

        result, err = _call_llm(messages)
        if err:
            return jsonify({"error": err}), 500

        if not isinstance(result, dict):
            return jsonify({"reply": str(result), "sql": None, "data": None})

        explanation = result.get("explanation", "")
        sql = result.get("sql", "")

        if not sql:
            return jsonify({"reply": explanation or "Done.", "sql": None, "data": None})

        rows = _execute_sql(sql)
        if isinstance(rows, dict) and "error" in rows:
            return jsonify({"reply": f"SQL error: {rows['error']}", "sql": sql, "data": None})

        if rows and explanation:
            for row in rows[:1]:
                for k, v in row.items():
                    explanation = explanation.replace("{" + k + "}", str(v if v is not None else "0"))

        # Strip "SQL:" lines that LLM sometimes includes in explanation
        explanation = re.sub(r'(?m)^SQL:.*$', '', explanation).strip()
        # Strip raw JSON that might leak into explanation
        explanation = re.sub(r'\{"sql":.*', '', explanation).strip()
        # Replace any remaining {placeholders} with "?"
        explanation = re.sub(r'\{[^}]+\}', '?', explanation)

        if not explanation or explanation == "?":
            explanation = "\n".join(" | ".join(f"{k}: {v}" for k, v in r.items()) for r in rows[:5])
        elif rows:
            # Append data if placeholders weren't fully resolved
            remaining = [r for r in rows if any(v not in ("", None, "0", 0) for v in r.values())]
            if remaining:
                data_strs = []
                for r in remaining[:3]:
                    data_strs.append(", ".join(f"{k}: {v}" for k, v in r.items() if v not in (None, "")))
                if data_strs:
                    explanation += "\n" + "\n".join(data_strs)

        return jsonify({"reply": explanation, "sql": sql, "data": rows[:20] if rows else None})

    except Exception as e:
        import traceback
        current_app.logger.error("AI Chat error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": f"Server error: {e}"}), 500
