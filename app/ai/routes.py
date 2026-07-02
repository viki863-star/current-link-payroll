import json
import re
import os
import requests
from datetime import date
from flask import request, jsonify, current_app
from . import ai_bp
from ..database import open_db

SCHEMA = """
employees(id,full_name,phone,email,type,dept,designation,salary,status,join_date)
drivers(id,full_name,phone,vehicle_no,shift,salary,status)
field_staff(id,full_name,phone,username)
cash_receipts(staff_id,amount,receipt_date)
vehicles(plate_no,type,model,year,status)
vehicle_assignments(vehicle_id,driver_id,from,is_current)
salary_store(emp_id,month,basic,ot,advances,deductions,net)
salary_slips(emp_id,month,basic,net,status)
salary_payments(emp_id,month,amount,date)
maintenance_jobs(vehicle_id,staff_id,amount,category,status)
technicians(code,user_id,phone)
maintenance_advances(staff_code,amount,date)
maintenance_papers(code,total,status)
parties(code,name,phone,role,status)
suppliers(code,name,category,status)
supplier_invoices(code,inv_no,amount,status)
supplier_bills(code,bill_no,amount,vat,total,status)
account_invoices(inv_no,party,total,status)
fuel_entries(vehicle_id,liters,cost,date)
"""


def _execute_sql(sql):
    db = open_db()
    try:
        result = db.execute(sql).fetchall()
        return [dict(row) for row in result] if result else []
    except Exception as e:
        return {"error": str(e)}


def _call_llm(messages):
    api_key = os.getenv("GROQ_API_KEY") or current_app.config.get("GROQ_API_KEY", "")
    if not api_key:
        return None, "GROQ_API_KEY not configured. Set in .env"

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 1024,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        data = resp.json()
        if "choices" not in data or not data["choices"]:
            err = data.get("error", {}).get("message", str(data))
            return None, f"Groq error: {err}"

        text = data["choices"][0]["message"]["content"].strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip()

        if text.startswith("{"):
            return json.loads(text), None
        return {"explanation": text, "sql": ""}, None
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
            f"Date: {today}. You are an ERP SQL assistant. "
            f"Tables:\n{SCHEMA}\n"
            "Reply ONLY valid JSON: {\"sql\":\"SELECT...\",\"explanation\":\"answer in user's language\"}. "
            "SELECT only. Max 20 rows. COALESCE nulls. "
            'Ex: {"sql":"SELECT count(*) FROM drivers WHERE status=\'Active\'","explanation":"15 drivers are active"}'
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
            try:
                for row in rows[:1]:
                    for k, v in row.items():
                        explanation = explanation.replace("{" + k + "}", str(v or "0"))
            except Exception:
                pass

        if not explanation and rows:
            explanation = "\n".join(" | ".join(f"{k}:{v}" for k, v in r.items()) for r in rows[:5])

        return jsonify({"reply": explanation, "sql": sql, "data": rows[:20] if rows else None})

    except Exception as e:
        import traceback
        current_app.logger.error("AI Chat error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": f"Server error: {e}"}), 500
